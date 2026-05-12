"""Tests for djinn_validator.chain.subgraph."""

from __future__ import annotations

from unittest.mock import patch
from typing import Any

import pytest

from djinn_validator.chain.subgraph import SubgraphClient


class _FakeResp:
    def __init__(self, body: Any, status_code: int = 200) -> None:
        self._body = body
        self.status_code = status_code

    def json(self) -> Any:
        return self._body


class _FakeClient:
    def __init__(self, resp: _FakeResp | Exception) -> None:
        self._resp = resp

    async def __aenter__(self) -> "_FakeClient":
        return self

    async def __aexit__(self, *a: Any) -> bool:
        return False

    async def post(self, url: str, **kw: Any) -> _FakeResp:
        if isinstance(self._resp, Exception):
            raise self._resp
        return self._resp


@pytest.mark.asyncio
async def test_is_fresh_within_lag() -> None:
    sg = SubgraphClient(url="http://sg.example", max_lag_blocks=150)
    fake = _FakeClient(_FakeResp({"data": {"_meta": {"block": {"number": 1000}, "hasIndexingErrors": False}}}))
    with patch("httpx.AsyncClient", lambda **kw: fake):
        assert await sg.is_fresh(chain_latest_block=1100) is True


@pytest.mark.asyncio
async def test_is_fresh_outside_lag() -> None:
    sg = SubgraphClient(url="http://sg.example", max_lag_blocks=150)
    fake = _FakeClient(_FakeResp({"data": {"_meta": {"block": {"number": 1000}, "hasIndexingErrors": False}}}))
    with patch("httpx.AsyncClient", lambda **kw: fake):
        assert await sg.is_fresh(chain_latest_block=1200) is False


@pytest.mark.asyncio
async def test_is_fresh_indexing_errors_returns_false() -> None:
    sg = SubgraphClient(url="http://sg.example", max_lag_blocks=150)
    fake = _FakeClient(_FakeResp({"data": {"_meta": {"block": {"number": 1000}, "hasIndexingErrors": True}}}))
    with patch("httpx.AsyncClient", lambda **kw: fake):
        assert await sg.is_fresh(chain_latest_block=1000) is False


@pytest.mark.asyncio
async def test_is_fresh_transport_error_returns_false() -> None:
    import httpx

    sg = SubgraphClient(url="http://sg.example")
    fake = _FakeClient(httpx.ConnectError("simulated subgraph down"))
    with patch("httpx.AsyncClient", lambda **kw: fake):
        assert await sg.is_fresh(chain_latest_block=1000) is False


@pytest.mark.asyncio
async def test_get_pair_purchases_happy_path() -> None:
    sg = SubgraphClient(url="http://sg.example")
    body = {
        "data": {
            "purchases": [
                {
                    "onChainPurchaseId": "1459",
                    "notional": "10000000",
                    "signal": {"id": "5481", "slaMultiplierBps": "15000"},
                },
                {
                    "onChainPurchaseId": "1460",
                    "notional": "10000000",
                    "signal": {"id": "9677", "slaMultiplierBps": "15000"},
                },
            ]
        }
    }
    fake = _FakeClient(_FakeResp(body))
    with patch("httpx.AsyncClient", lambda **kw: fake):
        rows = await sg.get_pair_purchases("0xGenius", "0xIdiot")
    assert rows is not None
    assert len(rows) == 2
    assert rows[0]["purchase_id"] == 1459
    assert rows[0]["signal_id"] == "5481"
    assert rows[0]["sla_bps"] == 15000
    assert rows[0]["notional"] == 10_000_000


@pytest.mark.asyncio
async def test_get_pair_purchases_subgraph_errors_returns_none() -> None:
    sg = SubgraphClient(url="http://sg.example")
    body = {"errors": [{"message": "indexer overloaded"}]}
    fake = _FakeClient(_FakeResp(body))
    with patch("httpx.AsyncClient", lambda **kw: fake):
        rows = await sg.get_pair_purchases("0xGenius", "0xIdiot")
    assert rows is None


@pytest.mark.asyncio
async def test_get_pair_purchases_transport_error_returns_none() -> None:
    import httpx

    sg = SubgraphClient(url="http://sg.example")
    fake = _FakeClient(httpx.ReadTimeout("subgraph slow"))
    with patch("httpx.AsyncClient", lambda **kw: fake):
        rows = await sg.get_pair_purchases("0xGenius", "0xIdiot")
    assert rows is None


@pytest.mark.asyncio
async def test_get_pair_purchases_skips_malformed_row() -> None:
    """One bad row doesn't poison the rest of the response."""
    sg = SubgraphClient(url="http://sg.example")
    body = {
        "data": {
            "purchases": [
                {"onChainPurchaseId": "not-an-int", "notional": "x", "signal": {"id": "5481"}},
                {
                    "onChainPurchaseId": "1460",
                    "notional": "10000000",
                    "signal": {"id": "9677", "slaMultiplierBps": "15000"},
                },
            ]
        }
    }
    fake = _FakeClient(_FakeResp(body))
    with patch("httpx.AsyncClient", lambda **kw: fake):
        rows = await sg.get_pair_purchases("0xGenius", "0xIdiot")
    assert rows is not None
    assert len(rows) == 1  # bad row dropped
    assert rows[0]["purchase_id"] == 1460


def test_get_default_subgraph_client_uses_hardcoded_when_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    """v1711: env unset = hardcoded canonical default (operators don't have
    to opt in). Returns a client pointing at api.studio.thegraph.com."""
    from djinn_validator.chain.subgraph import get_default_subgraph_client

    monkeypatch.delenv("DJINN_SUBGRAPH_URL", raising=False)
    client = get_default_subgraph_client()
    assert client is not None
    assert "api.studio.thegraph.com" in client.url


def test_get_default_subgraph_client_returns_none_when_explicit_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Operators who explicitly opt out (env="") get None — RPC-only mode."""
    from djinn_validator.chain.subgraph import get_default_subgraph_client

    monkeypatch.setenv("DJINN_SUBGRAPH_URL", "")
    assert get_default_subgraph_client() is None


def test_get_default_subgraph_client_constructs_when_set(monkeypatch: pytest.MonkeyPatch) -> None:
    """Env override wins over the hardcoded default."""
    from djinn_validator.chain.subgraph import get_default_subgraph_client

    monkeypatch.setenv("DJINN_SUBGRAPH_URL", "http://sg.example/q")
    client = get_default_subgraph_client()
    assert client is not None
    assert client.url == "http://sg.example/q"
