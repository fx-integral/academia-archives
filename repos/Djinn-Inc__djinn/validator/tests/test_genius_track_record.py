"""Tests for /v1/genius/{address}/track_record (Sprint B Stage 7).

Mirrors the legacy /api/idiot/genius/[address] Vercel route, but driven
by real AuditSettled events rather than the fictional AuditSetSettled
name the web route queried. Aggregates quality scores, derives
favorable/unfavorable/void from score sign, caches 30s per address.
"""

from __future__ import annotations

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
IDIOT_X = "0x1111111111111111111111111111111111111111"


def _evt(
    *,
    genius: str = GENIUS_A,
    idiot: str = IDIOT_X,
    batch_id: int = 1,
    quality_score: int = 100,
    tranche_a: int = 50_000_000,
    tranche_b: int = 50_000_000,
    protocol_fee: int = 500_000,
    block_number: int = 100,
) -> dict[str, Any]:
    return {
        "genius": genius,
        "idiot": idiot,
        "batch_id": batch_id,
        "quality_score": quality_score,
        "tranche_a": tranche_a,
        "tranche_b": tranche_b,
        "protocol_fee": protocol_fee,
        "block_number": block_number,
    }


def _make_chain(
    events: list[dict[str, Any]],
    current_block: int = 1_000_000,
    scan_raises: bool = False,
    block_raises: bool = False,
    audit_configured: bool = True,
) -> AsyncMock:
    mock_chain = AsyncMock()
    mock_chain.is_connected = AsyncMock(return_value=True)

    async def _block() -> int:
        if block_raises:
            raise RuntimeError("rpc down")
        return current_block

    mock_chain.get_current_block = AsyncMock(side_effect=_block)

    calls: dict[str, int] = {"n": 0}

    async def _events(**kwargs: Any) -> list[dict[str, Any]]:
        if scan_raises:
            raise RuntimeError("scan boom")
        calls["n"] += 1
        return events if calls["n"] == 1 else []

    mock_chain.get_recent_audit_settlements = AsyncMock(side_effect=_events)
    mock_chain._audit = MagicMock() if audit_configured else None
    mock_chain._signal = MagicMock()
    return mock_chain


@pytest.fixture
def share_store() -> ShareStore:
    store = ShareStore()
    yield store
    store.close()


def _client_with(chain_client: Any, share_store: ShareStore) -> TestClient:
    orch = PurchaseOrchestrator(share_store)
    att = OutcomeAttestor()
    app = create_app(share_store, orch, att, chain_client=chain_client)
    return TestClient(app)


class TestTrackRecordBasics:
    def test_invalid_address_400(self, share_store):
        client = _client_with(_make_chain([]), share_store)
        r = client.get("/v1/genius/not-an-address/track_record")
        assert r.status_code == 400

    def test_no_audit_contract_returns_empty(self, share_store):
        chain = _make_chain([], audit_configured=False)
        client = _client_with(chain, share_store)
        r = client.get(f"/v1/genius/{GENIUS_A}/track_record")
        assert r.status_code == 200
        body = r.json()
        assert body["address"] == GENIUS_A
        assert body["settled_batches"] == 0
        assert body["recent_settlements"] == []

    def test_no_chain_client_returns_empty(self, share_store):
        orch = PurchaseOrchestrator(share_store)
        att = OutcomeAttestor()
        app = create_app(share_store, orch, att, chain_client=None)
        c = TestClient(app)
        r = c.get(f"/v1/genius/{GENIUS_A}/track_record")
        assert r.status_code == 200
        body = r.json()
        assert body["settled_batches"] == 0
        assert body["favorable"] == 0

    def test_empty_history_returns_zeros(self, share_store):
        chain = _make_chain([])
        client = _client_with(chain, share_store)
        body = client.get(f"/v1/genius/{GENIUS_A}/track_record").json()
        assert body["quality_score_avg"] == 0
        assert body["settled_batches"] == 0
        assert body["total_signals"] == 0
        assert body["win_rate"] == 0.0


class TestTrackRecordAggregation:
    def test_favorable_unfavorable_void_classified_by_score_sign(self, share_store):
        events = [
            _evt(batch_id=1, quality_score=500, block_number=101),
            _evt(batch_id=2, quality_score=-200, block_number=102),
            _evt(batch_id=3, quality_score=0, block_number=103),
            _evt(batch_id=4, quality_score=1000, block_number=104),
        ]
        chain = _make_chain(events)
        body = _client_with(chain, share_store).get(
            f"/v1/genius/{GENIUS_A}/track_record"
        ).json()
        assert body["settled_batches"] == 4
        assert body["favorable"] == 2
        assert body["unfavorable"] == 1
        assert body["void"] == 1
        assert body["total_signals"] == 4

    def test_win_rate_excludes_void_from_denominator(self, share_store):
        events = [
            _evt(batch_id=1, quality_score=100, block_number=1),
            _evt(batch_id=2, quality_score=100, block_number=2),
            _evt(batch_id=3, quality_score=100, block_number=3),
            _evt(batch_id=4, quality_score=-100, block_number=4),
            _evt(batch_id=5, quality_score=0, block_number=5),
            _evt(batch_id=6, quality_score=0, block_number=6),
        ]
        chain = _make_chain(events)
        body = _client_with(chain, share_store).get(
            f"/v1/genius/{GENIUS_A}/track_record"
        ).json()
        # 3 fav / (3 fav + 1 unfav) = 0.75; void batches ignored in denominator.
        assert body["win_rate"] == 0.75

    def test_quality_score_avg_integer_division(self, share_store):
        events = [
            _evt(batch_id=1, quality_score=100, block_number=1),
            _evt(batch_id=2, quality_score=200, block_number=2),
            _evt(batch_id=3, quality_score=300, block_number=3),
        ]
        chain = _make_chain(events)
        body = _client_with(chain, share_store).get(
            f"/v1/genius/{GENIUS_A}/track_record"
        ).json()
        assert body["quality_score_avg"] == 200

    def test_recent_settlements_sorted_newest_first_capped_at_10(self, share_store):
        events = [
            _evt(batch_id=i, quality_score=i * 10, block_number=i)
            for i in range(1, 15)
        ]
        chain = _make_chain(events)
        body = _client_with(chain, share_store).get(
            f"/v1/genius/{GENIUS_A}/track_record"
        ).json()
        recent = body["recent_settlements"]
        assert len(recent) == 10
        # Newest (highest block_number) first.
        assert recent[0]["batch_id"] == 14
        assert recent[-1]["batch_id"] == 5

    def test_zero_division_when_only_voids(self, share_store):
        events = [
            _evt(batch_id=1, quality_score=0, block_number=1),
            _evt(batch_id=2, quality_score=0, block_number=2),
        ]
        chain = _make_chain(events)
        body = _client_with(chain, share_store).get(
            f"/v1/genius/{GENIUS_A}/track_record"
        ).json()
        assert body["win_rate"] == 0.0
        assert body["favorable"] == 0
        assert body["unfavorable"] == 0
        assert body["void"] == 2


class TestTrackRecordResilience:
    def test_block_fetch_failure_returns_empty_body(self, share_store):
        chain = _make_chain([], block_raises=True)
        body = _client_with(chain, share_store).get(
            f"/v1/genius/{GENIUS_A}/track_record"
        ).json()
        assert body["address"] == GENIUS_A
        assert body["settled_batches"] == 0

    def test_scan_failure_returns_empty_body(self, share_store):
        chain = _make_chain([], scan_raises=True)
        body = _client_with(chain, share_store).get(
            f"/v1/genius/{GENIUS_A}/track_record"
        ).json()
        assert body["settled_batches"] == 0
        # Scan failure should not blow up the response.
        assert body["favorable"] == 0


class TestTrackRecordCache:
    def test_second_call_served_from_cache(self, share_store):
        events = [_evt(batch_id=1, quality_score=100, block_number=1)]
        chain = _make_chain(events)
        c = _client_with(chain, share_store)
        c.get(f"/v1/genius/{GENIUS_A}/track_record")
        c.get(f"/v1/genius/{GENIUS_A}/track_record")
        # One RPC scan across two calls.
        assert chain.get_recent_audit_settlements.await_count == 1

    def test_distinct_addresses_scan_independently(self, share_store):
        events = [_evt(batch_id=1, quality_score=100, block_number=1)]
        chain = _make_chain(events)
        c = _client_with(chain, share_store)
        c.get(f"/v1/genius/{GENIUS_A}/track_record")
        c.get(f"/v1/genius/{GENIUS_B}/track_record")
        assert chain.get_recent_audit_settlements.await_count == 2
