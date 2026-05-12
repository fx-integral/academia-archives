"""Tests for /v1/genius/{address}/signals (Sprint B Stage 3).

The endpoint mirrors the legacy /api/genius/signals Vercel route: scans
SignalCommitted events filtered by genius, enriches each with a status
field (active|expired|cancelled|unknown), and paginates.
"""

from __future__ import annotations

import time
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from djinn_validator.api.server import create_app
from djinn_validator.core.outcomes import OutcomeAttestor
from djinn_validator.core.purchase import PurchaseOrchestrator
from djinn_validator.core.shares import ShareStore


GENIUS_A = "0xD717b5fbA93F123f6ad530ae2Ab327B4DcDa1e37"
GENIUS_B = "0x68fc8eeC9E5551d4c93a89b6d861f0a05e0A2A1d"


def _make_chain(
    events: list[dict[str, Any]],
    current_block: int = 1_000_000,
    active_ids: set[int] | None = None,
    active_raises: set[int] | None = None,
) -> AsyncMock:
    mock_chain = AsyncMock()
    mock_chain.is_connected = AsyncMock(return_value=True)
    mock_chain.get_current_block = AsyncMock(return_value=current_block)

    calls: dict[str, int] = {"n": 0}

    async def _events(**kwargs: Any) -> list[dict[str, Any]]:
        calls["n"] += 1
        # First call per cache miss returns events; subsequent calls (within
        # same cache window) should not happen.
        return events if calls["n"] == 1 else []

    mock_chain.get_recent_signal_events = AsyncMock(side_effect=_events)

    ids = active_ids if active_ids is not None else {int(e["signal_id"]) for e in events}
    raises = active_raises or set()

    async def _is_active(signal_id: int) -> bool:
        if int(signal_id) in raises:
            raise RuntimeError("rpc down")
        return int(signal_id) in ids

    mock_chain.is_signal_active = AsyncMock(side_effect=_is_active)
    mock_chain._signal = MagicMock()
    return mock_chain


@pytest.fixture
def share_store() -> ShareStore:
    store = ShareStore()
    yield store
    store.close()


def _future(seconds: int = 3600) -> int:
    return int(time.time()) + seconds


def _past(seconds: int = 3600) -> int:
    return int(time.time()) - seconds


def _client_with(chain_client: Any, share_store: ShareStore) -> TestClient:
    purchase_orch = PurchaseOrchestrator(share_store)
    outcome_attestor = OutcomeAttestor()
    app = create_app(share_store, purchase_orch, outcome_attestor, chain_client=chain_client)
    return TestClient(app)


def _event(
    signal_id: int,
    *,
    genius: str = GENIUS_A,
    sport: str = "basketball_nba",
    max_price_bps: int = 500,
    sla_multiplier_bps: int = 10_000,
    max_notional: int = 100_000_000,
    expires_at: int | None = None,
    block_number: int = 12345,
) -> dict[str, Any]:
    return {
        "signal_id": signal_id,
        "genius": genius,
        "sport": sport,
        "max_price_bps": max_price_bps,
        "sla_multiplier_bps": sla_multiplier_bps,
        "max_notional": max_notional,
        "expires_at": expires_at if expires_at is not None else _future(3600),
        "block_number": block_number,
    }


class TestGeniusSignalsBasics:
    def test_no_chain_returns_empty(self, share_store: ShareStore) -> None:
        c = _client_with(None, share_store)
        r = c.get(f"/v1/genius/{GENIUS_A}/signals")
        assert r.status_code == 200
        assert r.json() == {"signals": [], "total": 0, "offset": 0, "limit": 20}

    def test_invalid_address_rejected(self, share_store: ShareStore) -> None:
        chain = _make_chain([_event(1)])
        c = _client_with(chain, share_store)
        r = c.get("/v1/genius/not-an-address/signals")
        assert r.status_code == 400

    def test_default_returns_active_only(self, share_store: ShareStore) -> None:
        chain = _make_chain(
            [
                _event(1, expires_at=_future(3600)),
                _event(2, expires_at=_past(3600)),  # expired
                _event(3, expires_at=_future(3600)),
            ],
            active_ids={1, 3},
        )
        c = _client_with(chain, share_store)
        r = c.get(f"/v1/genius/{GENIUS_A}/signals")
        body = r.json()
        ids = {s["signal_id"] for s in body["signals"]}
        assert ids == {"1", "3"}
        assert body["total"] == 2
        for s in body["signals"]:
            assert s["status"] == "active"

    def test_include_all_returns_expired_and_cancelled(self, share_store: ShareStore) -> None:
        chain = _make_chain(
            [
                _event(1, expires_at=_future(3600)),
                _event(2, expires_at=_past(3600)),
                _event(3, expires_at=_future(3600)),
            ],
            active_ids={1},  # 3 exists but is cancelled (inactive)
        )
        c = _client_with(chain, share_store)
        r = c.get(f"/v1/genius/{GENIUS_A}/signals", params={"include_all": "1"})
        body = r.json()
        assert body["total"] == 3
        statuses = {s["signal_id"]: s["status"] for s in body["signals"]}
        assert statuses["1"] == "active"
        assert statuses["2"] == "expired"
        assert statuses["3"] == "cancelled"

    def test_unknown_status_on_isactive_error(self, share_store: ShareStore) -> None:
        chain = _make_chain(
            [_event(1, expires_at=_future(3600))],
            active_raises={1},
        )
        c = _client_with(chain, share_store)
        r = c.get(f"/v1/genius/{GENIUS_A}/signals", params={"include_all": "1"})
        body = r.json()
        assert body["signals"][0]["status"] == "unknown"


class TestGeniusSignalsResponseShape:
    def test_shape_matches_vercel(self, share_store: ShareStore) -> None:
        chain = _make_chain([_event(42, block_number=99_999, max_notional=250_000_000)])
        c = _client_with(chain, share_store)
        r = c.get(f"/v1/genius/{GENIUS_A}/signals")
        s = r.json()["signals"][0]
        assert s["signal_id"] == "42"
        assert s["genius"] == GENIUS_A
        assert s["sport"] == "basketball_nba"
        assert s["fee_bps"] == 500
        assert s["sla_multiplier_bps"] == 10_000
        assert s["max_notional"] == "250000000"
        assert s["min_notional"] == "0"
        assert "expires_at_unix" in s
        assert s["status"] == "active"
        assert s["block_number"] == 99_999


class TestGeniusSignalsSort:
    def test_newest_first_by_block(self, share_store: ShareStore) -> None:
        chain = _make_chain(
            [
                _event(1, block_number=100),
                _event(2, block_number=300),
                _event(3, block_number=200),
            ]
        )
        c = _client_with(chain, share_store)
        r = c.get(f"/v1/genius/{GENIUS_A}/signals")
        ids = [s["signal_id"] for s in r.json()["signals"]]
        assert ids == ["2", "3", "1"]


class TestGeniusSignalsPagination:
    def test_limit_caps_at_100(self, share_store: ShareStore) -> None:
        chain = _make_chain([_event(i, block_number=i) for i in range(1, 6)])
        c = _client_with(chain, share_store)
        r = c.get(f"/v1/genius/{GENIUS_A}/signals", params={"limit": 9999})
        assert r.json()["limit"] == 100

    def test_offset_slice(self, share_store: ShareStore) -> None:
        chain = _make_chain([_event(i, block_number=i) for i in range(1, 6)])
        c = _client_with(chain, share_store)
        # Newest-first: [5,4,3,2,1]; offset=2, limit=2 → [3,2]
        r = c.get(f"/v1/genius/{GENIUS_A}/signals", params={"limit": 2, "offset": 2})
        body = r.json()
        assert body["total"] == 5
        assert [s["signal_id"] for s in body["signals"]] == ["3", "2"]


class TestGeniusSignalsCache:
    def test_second_call_served_from_cache(self, share_store: ShareStore) -> None:
        chain = _make_chain([_event(1), _event(2)])
        c = _client_with(chain, share_store)
        c.get(f"/v1/genius/{GENIUS_A}/signals")
        first_count = chain.get_recent_signal_events.await_count
        for _ in range(5):
            c.get(f"/v1/genius/{GENIUS_A}/signals")
        assert chain.get_recent_signal_events.await_count == first_count

    def test_different_addresses_independent_cache(self, share_store: ShareStore) -> None:
        """Each genius address gets its own cache entry — cross-address traffic
        doesn't invalidate other entries."""

        async def _events(**kwargs: Any) -> list[dict[str, Any]]:
            genius = kwargs.get("genius_filter", "")
            if genius and genius.lower() == GENIUS_A.lower():
                return [_event(1, genius=GENIUS_A)]
            if genius and genius.lower() == GENIUS_B.lower():
                return [_event(2, genius=GENIUS_B)]
            return []

        chain = AsyncMock()
        chain.is_connected = AsyncMock(return_value=True)
        chain.get_current_block = AsyncMock(return_value=1_000_000)
        chain.get_recent_signal_events = AsyncMock(side_effect=_events)
        chain.is_signal_active = AsyncMock(return_value=True)
        chain._signal = MagicMock()

        c = _client_with(chain, share_store)
        r1 = c.get(f"/v1/genius/{GENIUS_A}/signals")
        r2 = c.get(f"/v1/genius/{GENIUS_B}/signals")
        assert {s["signal_id"] for s in r1.json()["signals"]} == {"1"}
        assert {s["signal_id"] for s in r2.json()["signals"]} == {"2"}
