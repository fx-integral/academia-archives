"""Tests for /v1/idiot/browse (Sprint A Stage A-3 final route).

The endpoint mirrors the legacy /api/idiot/browse Vercel route byte-for-byte
on response shape so static IPFS web clients can hit the wildcard router
instead of a centralized proxy. These tests pin the filter/sort/pagination
semantics and the cache behavior.
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


def _make_chain(events: list[dict[str, Any]], current_block: int = 1_000_000, active_ids: set[int] | None = None) -> AsyncMock:
    """Build a chain_client mock that serves the supplied events once, then returns []."""
    mock_chain = AsyncMock()
    mock_chain.is_connected = AsyncMock(return_value=True)
    mock_chain.get_current_block = AsyncMock(return_value=current_block)

    # First call returns the seeded events; subsequent refreshes return nothing.
    calls: dict[str, int] = {"n": 0}

    async def _events(**kwargs: Any) -> list[dict[str, Any]]:
        calls["n"] += 1
        return events if calls["n"] == 1 else []

    mock_chain.get_recent_signal_events = AsyncMock(side_effect=_events)

    ids = active_ids if active_ids is not None else {int(e["signal_id"]) for e in events}

    async def _is_active(signal_id: int) -> bool:
        return int(signal_id) in ids

    mock_chain.is_signal_active = AsyncMock(side_effect=_is_active)

    # ChainClient.has self._signal attribute, tests need _signal truthy
    mock_chain._signal = MagicMock()
    return mock_chain


@pytest.fixture
def share_store() -> ShareStore:
    store = ShareStore()
    yield store
    store.close()


def _future(seconds: int = 3600) -> int:
    return int(time.time()) + seconds


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
) -> dict[str, Any]:
    return {
        "signal_id": signal_id,
        "genius": genius,
        "sport": sport,
        "max_price_bps": max_price_bps,
        "sla_multiplier_bps": sla_multiplier_bps,
        "max_notional": max_notional,
        "expires_at": expires_at if expires_at is not None else _future(3600),
        "block_number": 12345,
    }


class TestBrowseBasics:
    def test_no_chain_returns_empty(self, share_store: ShareStore) -> None:
        c = _client_with(None, share_store)
        r = c.get("/v1/idiot/browse")
        assert r.status_code == 200
        body = r.json()
        assert body == {"signals": [], "total": 0, "offset": 0, "limit": 20}

    def test_default_limit_and_offset(self, share_store: ShareStore) -> None:
        chain = _make_chain([_event(1), _event(2), _event(3)])
        c = _client_with(chain, share_store)
        r = c.get("/v1/idiot/browse")
        assert r.status_code == 200
        body = r.json()
        assert body["limit"] == 20
        assert body["offset"] == 0
        assert body["total"] == 3
        assert len(body["signals"]) == 3

    def test_response_shape_fields(self, share_store: ShareStore) -> None:
        chain = _make_chain([_event(42, max_notional=250_000_000, sport="icehockey_nhl")])
        c = _client_with(chain, share_store)
        r = c.get("/v1/idiot/browse")
        s = r.json()["signals"][0]
        assert s["signal_id"] == "42"
        assert s["sport"] == "icehockey_nhl"
        assert s["max_notional"] == "250000000"
        assert s["min_notional"] == "0"
        assert s["max_notional_usdc"] == 250.0
        assert s["expires_at"].endswith("Z")
        assert "fee_bps" in s and "expires_at_unix" in s


class TestBrowseFilters:
    def test_filter_by_sport(self, share_store: ShareStore) -> None:
        chain = _make_chain(
            [
                _event(1, sport="basketball_nba"),
                _event(2, sport="icehockey_nhl"),
                _event(3, sport="basketball_nba"),
            ]
        )
        c = _client_with(chain, share_store)
        r = c.get("/v1/idiot/browse", params={"sport": "basketball_nba"})
        body = r.json()
        assert body["total"] == 2
        assert {s["signal_id"] for s in body["signals"]} == {"1", "3"}

    def test_filter_by_genius(self, share_store: ShareStore) -> None:
        chain = _make_chain(
            [
                _event(1, genius=GENIUS_A),
                _event(2, genius=GENIUS_B),
                _event(3, genius=GENIUS_A),
            ]
        )
        c = _client_with(chain, share_store)
        r = c.get("/v1/idiot/browse", params={"genius": GENIUS_A})
        body = r.json()
        assert body["total"] == 2
        assert all(s["genius"].lower() == GENIUS_A.lower() for s in body["signals"])

    def test_invalid_genius_rejected(self, share_store: ShareStore) -> None:
        chain = _make_chain([_event(1)])
        c = _client_with(chain, share_store)
        r = c.get("/v1/idiot/browse", params={"genius": "not-an-address"})
        assert r.status_code == 400


class TestBrowseSort:
    def test_sort_expires_soon_ascending(self, share_store: ShareStore) -> None:
        chain = _make_chain(
            [
                _event(1, expires_at=_future(10_000)),
                _event(2, expires_at=_future(500)),
                _event(3, expires_at=_future(5000)),
            ]
        )
        c = _client_with(chain, share_store)
        r = c.get("/v1/idiot/browse", params={"sort": "expires_soon"})
        ids = [s["signal_id"] for s in r.json()["signals"]]
        assert ids == ["2", "3", "1"]

    def test_sort_by_fee_ascending(self, share_store: ShareStore) -> None:
        chain = _make_chain(
            [
                _event(1, max_price_bps=750),
                _event(2, max_price_bps=250),
                _event(3, max_price_bps=500),
            ]
        )
        c = _client_with(chain, share_store)
        r = c.get("/v1/idiot/browse", params={"sort": "fee"})
        ids = [s["signal_id"] for s in r.json()["signals"]]
        assert ids == ["2", "3", "1"]


class TestBrowsePagination:
    def test_limit_caps_at_100(self, share_store: ShareStore) -> None:
        chain = _make_chain([_event(i) for i in range(1, 6)])
        c = _client_with(chain, share_store)
        r = c.get("/v1/idiot/browse", params={"limit": 9999})
        body = r.json()
        assert body["limit"] == 100
        assert len(body["signals"]) == 5

    def test_offset_slice(self, share_store: ShareStore) -> None:
        chain = _make_chain([_event(i, max_price_bps=i * 100) for i in range(1, 6)])
        c = _client_with(chain, share_store)
        r = c.get("/v1/idiot/browse", params={"sort": "fee", "limit": 2, "offset": 2})
        body = r.json()
        assert body["total"] == 5
        assert [s["signal_id"] for s in body["signals"]] == ["3", "4"]


class TestBrowseIsActiveFilter:
    def test_inactive_signals_dropped(self, share_store: ShareStore) -> None:
        chain = _make_chain([_event(1), _event(2), _event(3)], active_ids={1, 3})
        c = _client_with(chain, share_store)
        r = c.get("/v1/idiot/browse")
        ids = {s["signal_id"] for s in r.json()["signals"]}
        assert ids == {"1", "3"}

    def test_expired_events_dropped_pre_enrich(self, share_store: ShareStore) -> None:
        chain = _make_chain(
            [
                _event(1, expires_at=_future(3600)),
                _event(2, expires_at=int(time.time()) - 10),
            ]
        )
        c = _client_with(chain, share_store)
        r = c.get("/v1/idiot/browse")
        ids = {s["signal_id"] for s in r.json()["signals"]}
        assert ids == {"1"}


class TestBrowseCacheBustResistance:
    """Anonymous callers cannot force a full RPC rescan via any query param.

    v1354 fresh-eyes audit flagged `/v1/idiot/browse?bust=true` as an
    unrate-limited DoS vector (each bust did a 7-day log scan under a
    global lock). v1355 dropped the `bust` parameter from the public
    endpoint so an unknown query string is ignored by FastAPI's pydantic
    coercion.
    """

    def test_bust_true_does_not_rescan_when_cache_is_fresh(self, share_store: ShareStore) -> None:
        chain = _make_chain([_event(1), _event(2)])
        c = _client_with(chain, share_store)
        # Warm the cache.
        first = c.get("/v1/idiot/browse")
        assert first.status_code == 200
        calls_after_warm = chain.get_recent_signal_events.await_count
        assert calls_after_warm == 1

        # Repeated bust=true must not trigger additional scans while cache is fresh.
        for _ in range(5):
            r = c.get("/v1/idiot/browse", params={"bust": "true"})
            assert r.status_code == 200
        assert chain.get_recent_signal_events.await_count == calls_after_warm

    def test_arbitrary_query_params_are_ignored(self, share_store: ShareStore) -> None:
        chain = _make_chain([_event(1)])
        c = _client_with(chain, share_store)
        c.get("/v1/idiot/browse")
        warm_calls = chain.get_recent_signal_events.await_count
        # Garbage params must not be rejected or interpreted as bust.
        r = c.get(
            "/v1/idiot/browse",
            params={"bust": "1", "force": "1", "refresh": "yes", "admin": "1"},
        )
        assert r.status_code == 200
        assert chain.get_recent_signal_events.await_count == warm_calls
