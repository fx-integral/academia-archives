"""Tests for /v1/genius/{address}/earnings (Sprint B Stage 8).

Mirrors the legacy /api/genius/earnings Vercel route: Collateral deposit
+ locked reads scaled to USDC, plus aggregate quality score from recent
AuditSettled events. Cached 30s per address.
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


def _evt(batch_id: int, quality_score: int, block_number: int) -> dict[str, Any]:
    return {
        "batch_id": batch_id,
        "quality_score": quality_score,
        "block_number": block_number,
        "genius": GENIUS_A,
        "idiot": "0x1111111111111111111111111111111111111111",
        "tranche_a": 0,
        "tranche_b": 0,
        "protocol_fee": 0,
    }


def _make_chain(
    *,
    deposited: int = 0,
    locked: int = 0,
    audit_events: list[dict[str, Any]] | None = None,
    audit_configured: bool = True,
    collateral_raises: bool = False,
    scan_raises: bool = False,
) -> AsyncMock:
    mock_chain = AsyncMock()
    mock_chain.is_connected = AsyncMock(return_value=True)
    mock_chain.get_current_block = AsyncMock(return_value=1_000_000)

    async def _collat(addr: str) -> dict[str, int]:
        if collateral_raises:
            raise RuntimeError("rpc down")
        return {"deposited": deposited, "locked": locked}

    mock_chain.get_genius_collateral = AsyncMock(side_effect=_collat)

    calls: dict[str, int] = {"n": 0}

    async def _events(**kwargs: Any) -> list[dict[str, Any]]:
        if scan_raises:
            raise RuntimeError("scan boom")
        calls["n"] += 1
        return list(audit_events or []) if calls["n"] == 1 else []

    mock_chain.get_recent_audit_settlements = AsyncMock(side_effect=_events)
    mock_chain._audit = MagicMock() if audit_configured else None
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


class TestEarningsBasics:
    def test_invalid_address_400(self, share_store):
        client = _client_with(_make_chain(), share_store)
        r = client.get("/v1/genius/not-an-address/earnings")
        assert r.status_code == 400

    def test_no_chain_returns_empty(self, share_store):
        orch = PurchaseOrchestrator(share_store)
        att = OutcomeAttestor()
        app = create_app(share_store, orch, att, chain_client=None)
        c = TestClient(app)
        body = c.get(f"/v1/genius/{GENIUS_A}/earnings").json()
        assert body["address"] == GENIUS_A
        assert body["collateral_deposited_usdc"] == 0.0
        assert body["settled_batches"] == 0

    def test_empty_history_zero_collateral(self, share_store):
        chain = _make_chain()
        body = _client_with(chain, share_store).get(
            f"/v1/genius/{GENIUS_A}/earnings"
        ).json()
        assert body["collateral_deposited_usdc"] == 0.0
        assert body["collateral_locked_usdc"] == 0.0
        assert body["collateral_available_usdc"] == 0.0
        assert body["settled_batches"] == 0
        assert body["quality_score_avg"] == 0


class TestEarningsCollateral:
    def test_deposits_and_locked_scaled_to_usdc(self, share_store):
        # 1,000,000 raw = 1.0 USDC (6 decimals).
        chain = _make_chain(deposited=5_000_000, locked=1_500_000)
        body = _client_with(chain, share_store).get(
            f"/v1/genius/{GENIUS_A}/earnings"
        ).json()
        assert body["collateral_deposited_usdc"] == 5.0
        assert body["collateral_locked_usdc"] == 1.5
        assert body["collateral_available_usdc"] == 3.5

    def test_collateral_read_failure_yields_zeros(self, share_store):
        chain = _make_chain(deposited=9_000_000, collateral_raises=True)
        body = _client_with(chain, share_store).get(
            f"/v1/genius/{GENIUS_A}/earnings"
        ).json()
        assert body["collateral_deposited_usdc"] == 0.0

    def test_available_usdc_can_be_zero_when_fully_locked(self, share_store):
        chain = _make_chain(deposited=10_000_000, locked=10_000_000)
        body = _client_with(chain, share_store).get(
            f"/v1/genius/{GENIUS_A}/earnings"
        ).json()
        assert body["collateral_available_usdc"] == 0.0


class TestEarningsAuditAgg:
    def test_quality_score_average_over_settled_batches(self, share_store):
        events = [
            _evt(1, 100, 1),
            _evt(2, 300, 2),
            _evt(3, 500, 3),
        ]
        chain = _make_chain(audit_events=events)
        body = _client_with(chain, share_store).get(
            f"/v1/genius/{GENIUS_A}/earnings"
        ).json()
        assert body["settled_batches"] == 3
        assert body["quality_score_avg"] == 300

    def test_recent_settlements_newest_first_capped_at_10(self, share_store):
        events = [_evt(i, i * 10, i) for i in range(1, 15)]
        chain = _make_chain(audit_events=events)
        body = _client_with(chain, share_store).get(
            f"/v1/genius/{GENIUS_A}/earnings"
        ).json()
        recent = body["recent_settlements"]
        assert len(recent) == 10
        assert recent[0]["batch_id"] == 14
        assert recent[-1]["batch_id"] == 5

    def test_audit_unconfigured_returns_zero_batches_preserves_collateral(self, share_store):
        chain = _make_chain(
            deposited=2_000_000,
            locked=500_000,
            audit_configured=False,
        )
        body = _client_with(chain, share_store).get(
            f"/v1/genius/{GENIUS_A}/earnings"
        ).json()
        assert body["settled_batches"] == 0
        assert body["collateral_deposited_usdc"] == 2.0

    def test_scan_failure_degrades_to_empty_events(self, share_store):
        chain = _make_chain(deposited=1_000_000, scan_raises=True)
        body = _client_with(chain, share_store).get(
            f"/v1/genius/{GENIUS_A}/earnings"
        ).json()
        assert body["settled_batches"] == 0
        assert body["collateral_deposited_usdc"] == 1.0


class TestEarningsCache:
    def test_second_call_hits_cache(self, share_store):
        events = [_evt(1, 100, 1)]
        chain = _make_chain(deposited=1_000_000, audit_events=events)
        c = _client_with(chain, share_store)
        c.get(f"/v1/genius/{GENIUS_A}/earnings")
        c.get(f"/v1/genius/{GENIUS_A}/earnings")
        assert chain.get_genius_collateral.await_count == 1
        assert chain.get_recent_audit_settlements.await_count == 1

    def test_distinct_addresses_fetched_independently(self, share_store):
        chain = _make_chain(deposited=1_000_000)
        c = _client_with(chain, share_store)
        c.get(f"/v1/genius/{GENIUS_A}/earnings")
        c.get(f"/v1/genius/{GENIUS_B}/earnings")
        assert chain.get_genius_collateral.await_count == 2
