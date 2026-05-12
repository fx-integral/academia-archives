"""Tests for /v1/settlement/{genius}/{idiot} (Sprint B Stage 9).

Mirrors the legacy /api/settlement/[genius]/[idiot] Vercel route.
Version-aware: v2 contracts use queue-state, v1 contracts use cycle +
purchase-id list. Cached 30s per pair.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from djinn_validator.api.server import create_app
from djinn_validator.core.outcomes import OutcomeAttestor
from djinn_validator.core.purchase import PurchaseOrchestrator
from djinn_validator.core.shares import ShareStore


GENIUS = "0x68fc8eeC9E5551d4c93a89b6d861f0a05e0A2A1d"
IDIOT_A = "0x1111111111111111111111111111111111111111"
IDIOT_B = "0x2222222222222222222222222222222222222222"


def _make_chain(
    *,
    status: dict[str, Any] | None = None,
    raises: bool = False,
) -> AsyncMock:
    mock_chain = AsyncMock()
    mock_chain.is_connected = AsyncMock(return_value=True)

    calls: dict[str, int] = {"n": 0}

    async def _status(genius: str, idiot: str, epoch: int = 0) -> dict[str, Any]:
        if raises:
            raise RuntimeError("rpc down")
        calls["n"] += 1
        return dict(status or {
            "contract_version": 2,
            "total_purchases": 0,
            "resolved_count": 0,
            "audited_count": 0,
            "audit_batch_count": 0,
            "ready_for_settlement": False,
            "current_cycle": 0,
            "signals_in_cycle": 0,
        })

    mock_chain.get_pair_settlement_status = AsyncMock(side_effect=_status)
    mock_chain.__status_calls__ = calls  # type: ignore[attr-defined]
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


class TestPairSettlementBasics:
    def test_invalid_genius_400(self, share_store):
        client = _client_with(_make_chain(), share_store)
        r = client.get(f"/v1/settlement/not-an-address/{IDIOT_A}")
        assert r.status_code == 400

    def test_invalid_idiot_400(self, share_store):
        client = _client_with(_make_chain(), share_store)
        r = client.get(f"/v1/settlement/{GENIUS}/not-an-address")
        assert r.status_code == 400

    def test_no_chain_returns_empty(self, share_store):
        orch = PurchaseOrchestrator(share_store)
        att = OutcomeAttestor()
        app = create_app(share_store, orch, att, chain_client=None)
        c = TestClient(app)
        body = c.get(f"/v1/settlement/{GENIUS}/{IDIOT_A}").json()
        assert body["genius"] == GENIUS
        assert body["idiot"] == IDIOT_A
        assert body["contract_version"] == 1
        assert body["ready_for_settlement"] is False


class TestPairSettlementV2:
    def test_v2_queue_state_shape(self, share_store):
        chain = _make_chain(status={
            "contract_version": 2,
            "total_purchases": 25,
            "resolved_count": 20,
            "audited_count": 5,
            "audit_batch_count": 1,
            "ready_for_settlement": True,
            "current_cycle": 1,
            "signals_in_cycle": 25,
        })
        body = _client_with(chain, share_store).get(
            f"/v1/settlement/{GENIUS}/{IDIOT_A}"
        ).json()
        assert body["contract_version"] == 2
        assert body["total_purchases"] == 25
        assert body["resolved_count"] == 20
        assert body["audited_count"] == 5
        assert body["audit_batch_count"] == 1
        assert body["ready_for_settlement"] is True

    def test_v2_not_ready_under_threshold(self, share_store):
        chain = _make_chain(status={
            "contract_version": 2,
            "total_purchases": 12,
            "resolved_count": 14,  # resolved - audited = 9, under 10
            "audited_count": 5,
            "audit_batch_count": 0,
            "ready_for_settlement": False,
            "current_cycle": 0,
            "signals_in_cycle": 12,
        })
        body = _client_with(chain, share_store).get(
            f"/v1/settlement/{GENIUS}/{IDIOT_A}"
        ).json()
        assert body["ready_for_settlement"] is False


class TestPairSettlementV1:
    def test_v1_cycle_based_shape(self, share_store):
        chain = _make_chain(status={
            "contract_version": 1,
            "current_cycle": 3,
            "signals_in_cycle": 10,
            "total_purchases": 10,
            "resolved_count": 0,
            "audited_count": 0,
            "audit_batch_count": 3,
            "ready_for_settlement": True,
        })
        body = _client_with(chain, share_store).get(
            f"/v1/settlement/{GENIUS}/{IDIOT_A}"
        ).json()
        assert body["contract_version"] == 1
        assert body["current_cycle"] == 3
        assert body["signals_in_cycle"] == 10
        assert body["ready_for_settlement"] is True

    def test_v1_not_ready_under_threshold(self, share_store):
        chain = _make_chain(status={
            "contract_version": 1,
            "current_cycle": 2,
            "signals_in_cycle": 7,
            "total_purchases": 7,
            "resolved_count": 0,
            "audited_count": 0,
            "audit_batch_count": 2,
            "ready_for_settlement": False,
        })
        body = _client_with(chain, share_store).get(
            f"/v1/settlement/{GENIUS}/{IDIOT_A}"
        ).json()
        assert body["ready_for_settlement"] is False


class TestPairSettlementResilience:
    def test_status_failure_returns_empty_body(self, share_store):
        chain = _make_chain(raises=True)
        r = _client_with(chain, share_store).get(
            f"/v1/settlement/{GENIUS}/{IDIOT_A}"
        )
        assert r.status_code == 200
        body = r.json()
        assert body["contract_version"] == 1
        assert body["ready_for_settlement"] is False


class TestPairSettlementCache:
    def test_second_call_served_from_cache(self, share_store):
        chain = _make_chain(status={
            "contract_version": 2,
            "total_purchases": 5,
            "resolved_count": 5,
            "audited_count": 0,
            "audit_batch_count": 0,
            "ready_for_settlement": False,
            "current_cycle": 0,
            "signals_in_cycle": 5,
        })
        client = _client_with(chain, share_store)
        client.get(f"/v1/settlement/{GENIUS}/{IDIOT_A}")
        client.get(f"/v1/settlement/{GENIUS}/{IDIOT_A}")
        assert chain.__status_calls__["n"] == 1

    def test_distinct_pairs_fetched_independently(self, share_store):
        chain = _make_chain()
        client = _client_with(chain, share_store)
        client.get(f"/v1/settlement/{GENIUS}/{IDIOT_A}")
        client.get(f"/v1/settlement/{GENIUS}/{IDIOT_B}")
        assert chain.__status_calls__["n"] == 2
