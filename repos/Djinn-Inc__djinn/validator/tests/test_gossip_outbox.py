"""Tests for the v1744 durable outbound gossip retry queue."""

from __future__ import annotations

import asyncio
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from djinn_validator.core import gossip_outbox


@pytest.fixture(autouse=True)
def reset_outbox(tmp_path):
    """Each test gets a fresh SQLite file. configure() opens it."""
    gossip_outbox.reset_for_tests()
    # Force a re-open by clearing the global state's connection.
    gossip_outbox._state.db = None
    db_path = tmp_path / "outbox.db"
    gossip_outbox.configure(str(db_path))
    yield
    gossip_outbox.reset_for_tests()
    gossip_outbox._state.db = None


def _payload(signal_id: str = "sig1", buyer: str = "0xb1") -> dict:
    return {
        "signal_id": signal_id,
        "buyer_address": buyer,
        "bpas": [1000, 1100, 1200],
        "wpas": [900, 1000, 1100],
        "bpa_mode": True,
    }


def test_enqueue_returns_true_on_first_insert():
    ok = gossip_outbox.enqueue(
        peer_uid=1,
        peer_url="http://1.2.3.4:8421",
        peer_hotkey="ss58_a",
        endpoint="/v1/purchase_odds/record",
        payload=_payload(),
    )
    assert ok is True
    assert gossip_outbox.pending_count() == 1


def test_enqueue_dedups_on_same_peer_endpoint_payload():
    p = _payload()
    first = gossip_outbox.enqueue(1, "http://1.2.3.4:8421", "ss58_a", "/v1/purchase_odds/record", p)
    second = gossip_outbox.enqueue(1, "http://1.2.3.4:8421", "ss58_a", "/v1/purchase_odds/record", p)
    assert first is True
    assert second is False  # dedup
    assert gossip_outbox.pending_count() == 1


def test_enqueue_different_peers_are_separate_rows():
    p = _payload()
    gossip_outbox.enqueue(1, "http://1.2.3.4:8421", "ss58_a", "/v1/purchase_odds/record", p)
    gossip_outbox.enqueue(2, "http://5.6.7.8:8421", "ss58_b", "/v1/purchase_odds/record", p)
    assert gossip_outbox.pending_count() == 2


def test_enqueue_different_payloads_are_separate_rows():
    gossip_outbox.enqueue(1, "http://1.2.3.4:8421", "ss58_a", "/v1/purchase_odds/record", _payload("sigA"))
    gossip_outbox.enqueue(1, "http://1.2.3.4:8421", "ss58_a", "/v1/purchase_odds/record", _payload("sigB"))
    assert gossip_outbox.pending_count() == 2


def test_stats_returns_per_status_counts():
    gossip_outbox.enqueue(1, "http://x:1", "ss58_a", "/v1/x", _payload())
    s = gossip_outbox.stats()
    assert s == {"pending": 1, "acked": 0, "failed_terminal": 0}


def test_drain_with_no_signer_reschedules_only():
    gossip_outbox.enqueue(1, "http://x:1", "ss58_a", "/v1/x", _payload())
    # Force eligibility (default initial interval is 5 min into the future).
    with gossip_outbox._state.db_lock:
        gossip_outbox._state.db.execute(
            "UPDATE gossip_outbox SET next_attempt_ts=?",
            (time.time() - 1,),
        )
        gossip_outbox._state.db.commit()
    # No signer configured; drain shouldn't crash and should leave row pending.
    n = asyncio.run(gossip_outbox.drain_once())
    assert n == 1
    assert gossip_outbox.pending_count() == 1


def test_drain_marks_acked_on_200():
    """A peer that returns 200 transitions the row to acked."""
    gossip_outbox.enqueue(1, "http://x:1", "ss58_a", "/v1/x", _payload())

    # Force the row to be eligible immediately.
    with gossip_outbox._state.db_lock:
        gossip_outbox._state.db.execute(
            "UPDATE gossip_outbox SET next_attempt_ts=? WHERE 1=1",
            (time.time() - 1,),
        )
        gossip_outbox._state.db.commit()

    def stub_signer(endpoint, body):
        return {"X-Hotkey": "h", "X-Signature": "s", "X-Timestamp": "1", "X-Nonce": "n"}

    gossip_outbox._state.signer = stub_signer

    class StubResponse:
        def __init__(self, status):
            self.status_code = status

    class StubClient:
        async def post(self, *args, **kwargs):
            return StubResponse(200)

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

    with patch("httpx.AsyncClient", return_value=StubClient()):
        asyncio.run(gossip_outbox.drain_once())

    s = gossip_outbox.stats()
    assert s["acked"] == 1
    assert s["pending"] == 0


def test_drain_marks_failed_terminal_on_4xx():
    """A peer that returns 4xx (e.g. 404 on old version) goes terminal."""
    gossip_outbox.enqueue(1, "http://x:1", "ss58_a", "/v1/x", _payload())

    with gossip_outbox._state.db_lock:
        gossip_outbox._state.db.execute(
            "UPDATE gossip_outbox SET next_attempt_ts=? WHERE 1=1",
            (time.time() - 1,),
        )
        gossip_outbox._state.db.commit()

    gossip_outbox._state.signer = lambda e, b: {"X-Hotkey": "h"}

    class StubResponse:
        def __init__(self, status):
            self.status_code = status

    class StubClient:
        async def post(self, *args, **kwargs):
            return StubResponse(404)

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

    with patch("httpx.AsyncClient", return_value=StubClient()):
        asyncio.run(gossip_outbox.drain_once())

    s = gossip_outbox.stats()
    assert s["failed_terminal"] == 1
    assert s["pending"] == 0


def test_drain_keeps_pending_with_backoff_on_5xx():
    """A peer that returns 5xx stays pending and the next attempt is pushed out."""
    gossip_outbox.enqueue(1, "http://x:1", "ss58_a", "/v1/x", _payload())

    with gossip_outbox._state.db_lock:
        gossip_outbox._state.db.execute(
            "UPDATE gossip_outbox SET next_attempt_ts=? WHERE 1=1",
            (time.time() - 1,),
        )
        gossip_outbox._state.db.commit()

    gossip_outbox._state.signer = lambda e, b: {"X-Hotkey": "h"}

    class StubResponse:
        def __init__(self, status):
            self.status_code = status

    class StubClient:
        async def post(self, *args, **kwargs):
            return StubResponse(503)

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

    with patch("httpx.AsyncClient", return_value=StubClient()):
        asyncio.run(gossip_outbox.drain_once())

    s = gossip_outbox.stats()
    assert s["pending"] == 1
    assert s["acked"] == 0
    assert s["failed_terminal"] == 0

    # Verify next_attempt_ts moved into the future.
    with gossip_outbox._state.db_lock:
        cur = gossip_outbox._state.db.execute(
            "SELECT next_attempt_ts, attempts, last_error FROM gossip_outbox"
        )
        next_ts, attempts, last_err = cur.fetchone()
    assert next_ts > time.time() + 60  # at least 1 min away
    assert attempts == 1
    assert "503" in last_err


def test_drain_marks_terminal_after_max_lifetime():
    """A row whose enqueue_ts is older than MAX_LIFETIME_SEC goes terminal."""
    gossip_outbox.enqueue(1, "http://x:1", "ss58_a", "/v1/x", _payload())

    # Backdate the enqueue.
    long_ago = time.time() - gossip_outbox.MAX_LIFETIME_SEC - 60
    with gossip_outbox._state.db_lock:
        gossip_outbox._state.db.execute(
            "UPDATE gossip_outbox SET enqueue_ts=?, next_attempt_ts=?",
            (long_ago, time.time() - 1),
        )
        gossip_outbox._state.db.commit()

    gossip_outbox._state.signer = lambda e, b: {"X-Hotkey": "h"}

    asyncio.run(gossip_outbox.drain_once())

    s = gossip_outbox.stats()
    assert s["failed_terminal"] == 1
    assert s["pending"] == 0

    with gossip_outbox._state.db_lock:
        cur = gossip_outbox._state.db.execute("SELECT last_error FROM gossip_outbox")
        last_err = cur.fetchone()[0]
    assert last_err == "max_lifetime_exceeded"


def test_drain_skips_rows_not_yet_due():
    """Rows whose next_attempt_ts is in the future are not attempted."""
    gossip_outbox.enqueue(1, "http://x:1", "ss58_a", "/v1/x", _payload())

    # Push the next attempt 1 hour out.
    with gossip_outbox._state.db_lock:
        gossip_outbox._state.db.execute(
            "UPDATE gossip_outbox SET next_attempt_ts=?",
            (time.time() + 3600,),
        )
        gossip_outbox._state.db.commit()

    gossip_outbox._state.signer = lambda e, b: {"X-Hotkey": "h"}

    n = asyncio.run(gossip_outbox.drain_once())
    assert n == 0
    assert gossip_outbox.pending_count() == 1


def test_pending_count_zero_when_db_unconfigured():
    gossip_outbox.reset_for_tests()
    gossip_outbox._state.db = None  # explicit
    assert gossip_outbox.pending_count() == 0
    s = gossip_outbox.stats()
    assert s == {"pending": 0, "acked": 0, "failed_terminal": 0}


def test_enqueue_returns_false_when_db_unconfigured():
    gossip_outbox.reset_for_tests()
    gossip_outbox._state.db = None
    ok = gossip_outbox.enqueue(1, "http://x:1", "ss58_a", "/v1/x", _payload())
    assert ok is False


def test_backoff_sequence_is_capped():
    """_backoff_seconds returns increasing intervals capped at MAX_RETRY_INTERVAL_SEC."""
    intervals = [gossip_outbox._backoff_seconds(i) for i in range(20)]
    # First few grow with BACKOFF_BASE^i.
    assert intervals[0] == gossip_outbox.INITIAL_RETRY_INTERVAL_SEC
    assert intervals[1] > intervals[0]
    # Eventually capped.
    assert intervals[-1] == gossip_outbox.MAX_RETRY_INTERVAL_SEC
    assert all(i <= gossip_outbox.MAX_RETRY_INTERVAL_SEC for i in intervals)
