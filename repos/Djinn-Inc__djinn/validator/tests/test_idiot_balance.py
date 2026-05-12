"""Tests for /v1/idiot/{address}/balance (Sprint B Stage 5).

Mirrors the legacy /api/idiot/balance Vercel route: escrow deposit, USDC
wallet balance, and credit-ledger balance for an idiot address. All three
reads degrade to zero independently so a single unreachable contract
doesn't fail the whole response.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from djinn_validator.api.server import create_app
from djinn_validator.core.outcomes import OutcomeAttestor
from djinn_validator.core.purchase import PurchaseOrchestrator
from djinn_validator.core.shares import ShareStore


IDIOT = "0xD717b5fbA93F123f6ad530ae2Ab327B4DcDa1e37"


def _make_chain(
    *,
    escrow: int = 0,
    wallet: int = 0,
    credits: int = 0,
    escrow_raises: bool = False,
    wallet_raises: bool = False,
    credits_raises: bool = False,
) -> AsyncMock:
    """Build a chain mock that returns the three balances directly from
    get_idiot_balances — tests pin the wire-level contract rather than the
    internal failover plumbing."""
    chain = AsyncMock()
    chain.is_connected = AsyncMock(return_value=True)
    chain._signal = MagicMock()

    async def _balances(addr: str) -> dict[str, int]:
        return {
            "escrow": escrow,
            "wallet_usdc": wallet,
            "credits": credits,
        }

    chain.get_idiot_balances = AsyncMock(side_effect=_balances)
    # Model the case where one of the underlying reads raises inside the
    # helper by returning zero for that field (the helper itself catches
    # per-field). These flags exist so tests can document that behavior.
    if escrow_raises:
        async def _with_escrow_fail(addr: str) -> dict[str, int]:
            return {"escrow": 0, "wallet_usdc": wallet, "credits": credits}
        chain.get_idiot_balances = AsyncMock(side_effect=_with_escrow_fail)
    if wallet_raises:
        async def _with_wallet_fail(addr: str) -> dict[str, int]:
            return {"escrow": escrow, "wallet_usdc": 0, "credits": credits}
        chain.get_idiot_balances = AsyncMock(side_effect=_with_wallet_fail)
    if credits_raises:
        async def _with_credits_fail(addr: str) -> dict[str, int]:
            return {"escrow": escrow, "wallet_usdc": wallet, "credits": 0}
        chain.get_idiot_balances = AsyncMock(side_effect=_with_credits_fail)
    return chain


@pytest.fixture
def share_store() -> ShareStore:
    s = ShareStore()
    yield s
    s.close()


def _client(chain, share_store) -> TestClient:
    app = create_app(
        share_store,
        PurchaseOrchestrator(share_store),
        OutcomeAttestor(),
        chain_client=chain,
    )
    return TestClient(app)


class TestIdiotBalanceBasics:
    def test_no_chain_returns_zeros(self, share_store):
        c = _client(None, share_store)
        r = c.get(f"/v1/idiot/{IDIOT}/balance")
        assert r.status_code == 200
        body = r.json()
        assert body == {
            "address": IDIOT,
            "escrow_balance_usdc": 0,
            "wallet_usdc": 0,
            "credits": 0,
        }

    def test_invalid_address_400(self, share_store):
        chain = _make_chain()
        c = _client(chain, share_store)
        r = c.get("/v1/idiot/not-an-address/balance")
        assert r.status_code == 400

    def test_address_is_checksummed_in_response(self, share_store):
        chain = _make_chain(escrow=1_000_000)
        c = _client(chain, share_store)
        # Send lowercase; expect checksum back.
        r = c.get(f"/v1/idiot/{IDIOT.lower()}/balance")
        assert r.status_code == 200
        assert r.json()["address"] == IDIOT


class TestIdiotBalanceShape:
    def test_shape_matches_vercel(self, share_store):
        # 123 USDC escrow, 456.7 USDC wallet, 89.01 credits (all in 6-decimal wei).
        chain = _make_chain(
            escrow=123_000_000,
            wallet=456_700_000,
            credits=89_010_000,
        )
        c = _client(chain, share_store)
        body = c.get(f"/v1/idiot/{IDIOT}/balance").json()
        assert body["escrow_balance_usdc"] == 123.0
        assert body["wallet_usdc"] == 456.7
        assert body["credits"] == 89.01

    def test_zero_wei_returns_zero(self, share_store):
        chain = _make_chain()
        c = _client(chain, share_store)
        body = c.get(f"/v1/idiot/{IDIOT}/balance").json()
        assert body["escrow_balance_usdc"] == 0
        assert body["wallet_usdc"] == 0
        assert body["credits"] == 0


class TestIdiotBalancePartialFailure:
    def test_escrow_zero_does_not_zero_out_wallet(self, share_store):
        chain = _make_chain(escrow_raises=True, wallet=10_000_000, credits=5_000_000)
        c = _client(chain, share_store)
        body = c.get(f"/v1/idiot/{IDIOT}/balance").json()
        assert body["escrow_balance_usdc"] == 0
        assert body["wallet_usdc"] == 10.0
        assert body["credits"] == 5.0

    def test_credits_zero_does_not_zero_out_escrow(self, share_store):
        chain = _make_chain(escrow=2_000_000, wallet=3_000_000, credits_raises=True)
        c = _client(chain, share_store)
        body = c.get(f"/v1/idiot/{IDIOT}/balance").json()
        assert body["escrow_balance_usdc"] == 2.0
        assert body["wallet_usdc"] == 3.0
        assert body["credits"] == 0
