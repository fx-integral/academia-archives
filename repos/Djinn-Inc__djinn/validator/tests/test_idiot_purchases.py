"""Tests for /v1/idiot/{address}/purchases (Sprint B Stage 10).

Mirrors the legacy /api/idiot/purchases Vercel route. Scans Escrow
SignalPurchased events by buyer, enriches with getPurchase outcomes,
applies status filter + pagination.
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


BUYER = "0xD717b5fbA93F123f6ad530ae2Ab327B4DcDa1e37"


def _evt(
    *,
    purchase_id: int,
    signal_id: int = 1,
    notional: int = 10_000_000,
    fee_paid: int = 100_000,
    credit_used: int = 0,
    usdc_paid: int = 10_100_000,
    block_number: int = 100,
) -> dict[str, Any]:
    return {
        "signal_id": str(signal_id),
        "buyer": BUYER,
        "purchase_id": purchase_id,
        "notional": notional,
        "fee_paid": fee_paid,
        "credit_used": credit_used,
        "usdc_paid": usdc_paid,
        "block_number": block_number,
    }


def _purch(outcome: int = 0, purchased_at: int = 1_700_000_000) -> tuple:
    # Mirrors Escrow.getPurchase return tuple:
    # (idiot, signalId, notional, feePaid, creditUsed, usdcPaid, odds, outcome, purchasedAt, lockedOdds)
    return (
        BUYER, 1, 10_000_000, 100_000, 0, 10_100_000, 150, outcome, purchased_at, 150,
    )


def _make_chain(
    *,
    events: list[dict[str, Any]] | None = None,
    outcomes_by_pid: dict[int, int] | None = None,
    escrow_configured: bool = True,
    scan_raises: bool = False,
    get_purchase_raises_for: set[int] | None = None,
) -> AsyncMock:
    mock_chain = AsyncMock()
    mock_chain.is_connected = AsyncMock(return_value=True)
    mock_chain.get_current_block = AsyncMock(return_value=1_000_000)
    mock_chain.get_block_timestamp = AsyncMock(return_value=1_700_000_500)

    scan_calls = {"n": 0}

    async def _scan(**kwargs: Any) -> list[dict[str, Any]]:
        if scan_raises:
            raise RuntimeError("scan boom")
        scan_calls["n"] += 1
        return list(events or [])

    mock_chain.get_recent_signal_purchases = AsyncMock(side_effect=_scan)

    async def _get_purchase(pid: int) -> tuple | None:
        if get_purchase_raises_for and pid in get_purchase_raises_for:
            raise RuntimeError("rpc flake")
        outcome = (outcomes_by_pid or {}).get(pid, 0)
        return _purch(outcome=outcome)

    mock_chain.get_purchase = AsyncMock(side_effect=_get_purchase)

    mock_chain._escrow = MagicMock() if escrow_configured else None
    mock_chain.__scan_calls__ = scan_calls  # type: ignore[attr-defined]
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


class TestPurchasesBasics:
    def test_invalid_address_400(self, share_store):
        client = _client_with(_make_chain(), share_store)
        r = client.get("/v1/idiot/not-an-address/purchases")
        assert r.status_code == 400

    def test_invalid_status_400(self, share_store):
        client = _client_with(_make_chain(), share_store)
        r = client.get(f"/v1/idiot/{BUYER}/purchases?status=bogus")
        assert r.status_code == 400

    def test_no_chain_returns_empty(self, share_store):
        orch = PurchaseOrchestrator(share_store)
        att = OutcomeAttestor()
        app = create_app(share_store, orch, att, chain_client=None)
        c = TestClient(app)
        body = c.get(f"/v1/idiot/{BUYER}/purchases").json()
        assert body == {"purchases": [], "total": 0, "offset": 0, "limit": 20}

    def test_no_escrow_returns_empty(self, share_store):
        chain = _make_chain(escrow_configured=False)
        body = _client_with(chain, share_store).get(
            f"/v1/idiot/{BUYER}/purchases"
        ).json()
        assert body["purchases"] == []
        assert body["total"] == 0


class TestPurchasesAggregation:
    def test_usdc_scaling(self, share_store):
        chain = _make_chain(events=[_evt(purchase_id=1, notional=5_000_000, fee_paid=50_000, credit_used=10_000, usdc_paid=5_040_000)])
        body = _client_with(chain, share_store).get(
            f"/v1/idiot/{BUYER}/purchases"
        ).json()
        p = body["purchases"][0]
        assert p["notional_usdc"] == 5.0
        assert p["fee_usdc"] == 0.05
        assert p["credit_used_usdc"] == 0.01
        assert p["usdc_paid"] == 5.04

    def test_outcome_label_mapping(self, share_store):
        chain = _make_chain(
            events=[
                _evt(purchase_id=1, block_number=10),
                _evt(purchase_id=2, block_number=20),
                _evt(purchase_id=3, block_number=30),
                _evt(purchase_id=4, block_number=40),
            ],
            outcomes_by_pid={1: 0, 2: 1, 3: 2, 4: 3},
        )
        body = _client_with(chain, share_store).get(
            f"/v1/idiot/{BUYER}/purchases"
        ).json()
        by_pid = {p["purchase_id"]: p for p in body["purchases"]}
        assert by_pid[1]["outcome"] == "pending"
        assert by_pid[1]["status"] == "pending"
        assert by_pid[2]["outcome"] == "favorable"
        assert by_pid[2]["status"] == "settled"
        assert by_pid[3]["outcome"] == "unfavorable"
        assert by_pid[3]["status"] == "settled"
        assert by_pid[4]["outcome"] == "void"
        assert by_pid[4]["status"] == "void"

    def test_sorted_newest_first(self, share_store):
        chain = _make_chain(events=[
            _evt(purchase_id=1, block_number=10),
            _evt(purchase_id=2, block_number=30),
            _evt(purchase_id=3, block_number=20),
        ])
        body = _client_with(chain, share_store).get(
            f"/v1/idiot/{BUYER}/purchases"
        ).json()
        pids = [p["purchase_id"] for p in body["purchases"]]
        assert pids == [2, 3, 1]

    def test_iso_purchased_at_format(self, share_store):
        chain = _make_chain(events=[_evt(purchase_id=1)])
        body = _client_with(chain, share_store).get(
            f"/v1/idiot/{BUYER}/purchases"
        ).json()
        ts = body["purchases"][0]["purchased_at"]
        assert ts.endswith("Z")
        assert "T" in ts

    def test_get_purchase_failure_falls_back_to_block_timestamp(self, share_store):
        chain = _make_chain(
            events=[_evt(purchase_id=1, block_number=77)],
            get_purchase_raises_for={1},
        )
        body = _client_with(chain, share_store).get(
            f"/v1/idiot/{BUYER}/purchases"
        ).json()
        assert body["total"] == 1
        assert body["purchases"][0]["purchased_at"].endswith("Z")


class TestPurchasesFilterAndPagination:
    def test_status_filter_pending(self, share_store):
        chain = _make_chain(
            events=[_evt(purchase_id=i, block_number=i) for i in range(1, 5)],
            outcomes_by_pid={1: 0, 2: 1, 3: 2, 4: 3},
        )
        body = _client_with(chain, share_store).get(
            f"/v1/idiot/{BUYER}/purchases?status=pending"
        ).json()
        assert body["total"] == 1
        assert body["purchases"][0]["outcome"] == "pending"

    def test_status_filter_settled_includes_both_fav_and_unfav(self, share_store):
        chain = _make_chain(
            events=[_evt(purchase_id=i, block_number=i) for i in range(1, 5)],
            outcomes_by_pid={1: 0, 2: 1, 3: 2, 4: 3},
        )
        body = _client_with(chain, share_store).get(
            f"/v1/idiot/{BUYER}/purchases?status=settled"
        ).json()
        assert body["total"] == 2
        assert {p["outcome"] for p in body["purchases"]} == {"favorable", "unfavorable"}

    def test_status_filter_void(self, share_store):
        chain = _make_chain(
            events=[_evt(purchase_id=i, block_number=i) for i in range(1, 5)],
            outcomes_by_pid={1: 0, 2: 1, 3: 2, 4: 3},
        )
        body = _client_with(chain, share_store).get(
            f"/v1/idiot/{BUYER}/purchases?status=void"
        ).json()
        assert body["total"] == 1
        assert body["purchases"][0]["outcome"] == "void"

    def test_limit_and_offset(self, share_store):
        chain = _make_chain(events=[_evt(purchase_id=i, block_number=i) for i in range(1, 11)])
        body = _client_with(chain, share_store).get(
            f"/v1/idiot/{BUYER}/purchases?limit=3&offset=2"
        ).json()
        assert body["limit"] == 3
        assert body["offset"] == 2
        assert body["total"] == 10
        assert len(body["purchases"]) == 3
        # Newest-first sort on block_number 1..10 means highest is first;
        # offset=2 skips 10 and 9, returns 8, 7, 6.
        assert [p["purchase_id"] for p in body["purchases"]] == [8, 7, 6]

    def test_limit_clamped_to_100(self, share_store):
        chain = _make_chain()
        r = _client_with(chain, share_store).get(
            f"/v1/idiot/{BUYER}/purchases?limit=9999"
        )
        assert r.json()["limit"] == 100

    def test_limit_clamped_to_1(self, share_store):
        chain = _make_chain()
        r = _client_with(chain, share_store).get(
            f"/v1/idiot/{BUYER}/purchases?limit=0"
        )
        assert r.json()["limit"] == 1


class TestPurchasesResilience:
    def test_scan_failure_returns_empty(self, share_store):
        chain = _make_chain(scan_raises=True)
        r = _client_with(chain, share_store).get(
            f"/v1/idiot/{BUYER}/purchases"
        )
        assert r.status_code == 200
        body = r.json()
        assert body["purchases"] == []
        assert body["total"] == 0


class TestPurchasesCache:
    def test_identical_query_hits_cache(self, share_store):
        chain = _make_chain(events=[_evt(purchase_id=1)])
        client = _client_with(chain, share_store)
        client.get(f"/v1/idiot/{BUYER}/purchases")
        client.get(f"/v1/idiot/{BUYER}/purchases")
        assert chain.__scan_calls__["n"] == 1

    def test_different_status_filter_scans_independently(self, share_store):
        chain = _make_chain(events=[_evt(purchase_id=1)])
        client = _client_with(chain, share_store)
        client.get(f"/v1/idiot/{BUYER}/purchases")
        client.get(f"/v1/idiot/{BUYER}/purchases?status=pending")
        assert chain.__scan_calls__["n"] == 2

    def test_different_pagination_scans_independently(self, share_store):
        chain = _make_chain(events=[_evt(purchase_id=1)])
        client = _client_with(chain, share_store)
        client.get(f"/v1/idiot/{BUYER}/purchases?limit=10")
        client.get(f"/v1/idiot/{BUYER}/purchases?limit=20")
        assert chain.__scan_calls__["n"] == 2
