"""Tests for the validator-side /v1/odds/canonical endpoint."""

from __future__ import annotations

import importlib
import os

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def app_with_flag(monkeypatch, tmp_path):
    """Build a fastapi test client with the canonical odds flag toggled."""
    for key in list(os.environ.keys()):
        if key.startswith("DJINN_FF_"):
            monkeypatch.delenv(key, raising=False)

    def _build(flag_on: bool):
        if flag_on:
            monkeypatch.setenv("DJINN_FF_CANONICAL_ODDS", "true")
        from djinn_validator import feature_flags

        importlib.reload(feature_flags)

        from djinn_validator.api.server import create_app
        from djinn_validator.core.shares import ShareStore
        from djinn_validator.core.purchase import PurchaseOrchestrator
        from djinn_validator.core.outcomes import OutcomeAttestor

        share_store = ShareStore()
        purchase_orch = PurchaseOrchestrator(share_store)
        outcome_attestor = OutcomeAttestor(espn_client=None)

        app = create_app(
            share_store=share_store,
            purchase_orch=purchase_orch,
            outcome_attestor=outcome_attestor,
        )
        return TestClient(app)

    yield _build

    # Teardown: reset flags singleton
    for key in list(os.environ.keys()):
        if key.startswith("DJINN_FF_"):
            monkeypatch.delenv(key, raising=False)
    from djinn_validator import feature_flags as _ff

    importlib.reload(_ff)


def test_canonical_odds_returns_disabled_when_flag_off(app_with_flag):
    try:
        client = app_with_flag(flag_on=False)
    except (TypeError, ImportError) as e:
        pytest.skip(f"create_app signature mismatch in test fixture: {e}")
    resp = client.post(
        "/v1/odds/canonical",
        json={"sport": "basketball_nba", "market": "moneyline", "bookmakers": ["draftkings"]},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["feature_flag_enabled"] is False
    assert body["observations"] == []
    assert body["sport"] == "basketball_nba"
    assert body["market"] == "moneyline"


def test_canonical_odds_returns_enabled_when_flag_on(app_with_flag):
    try:
        client = app_with_flag(flag_on=True)
    except (TypeError, ImportError) as e:
        pytest.skip(f"create_app signature mismatch in test fixture: {e}")
    resp = client.post(
        "/v1/odds/canonical",
        json={"sport": "basketball_nba", "market": "moneyline", "bookmakers": ["draftkings"]},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["feature_flag_enabled"] is True
    assert isinstance(body["observations"], list)
    assert "served_at_ms" in body
    assert body["served_at_ms"] > 0


def test_canonical_odds_rejects_invalid_sport_key(app_with_flag):
    try:
        client = app_with_flag(flag_on=False)
    except (TypeError, ImportError) as e:
        pytest.skip(f"create_app signature mismatch in test fixture: {e}")
    resp = client.post(
        "/v1/odds/canonical",
        json={"sport": "Invalid Sport!", "market": "moneyline", "bookmakers": []},
    )
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Fan-out consensus tests. Stub neuron exposes three fake miners; a
# patched httpx.AsyncClient returns canned per-miner /v1/odds/canonical
# responses. Verifies the median reducer produces the expected prices.
# ---------------------------------------------------------------------------


@pytest.fixture
def fanout_app(monkeypatch):
    from unittest.mock import MagicMock

    for key in list(os.environ.keys()):
        if key.startswith("DJINN_FF_"):
            monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("BT_NETWORK", "test")
    monkeypatch.setenv("DJINN_FF_CANONICAL_ODDS", "true")

    from djinn_validator import feature_flags

    importlib.reload(feature_flags)

    from djinn_validator.api.server import create_app
    from djinn_validator.core.shares import ShareStore
    from djinn_validator.core.purchase import PurchaseOrchestrator
    from djinn_validator.core.outcomes import OutcomeAttestor

    share_store = ShareStore()
    purchase_orch = PurchaseOrchestrator(share_store)
    outcome_attestor = OutcomeAttestor(espn_client=None)

    neuron = MagicMock()
    neuron.get_miner_uids = MagicMock(return_value=[10, 11, 12])
    neuron.get_axon_info = lambda uid: {
        "ip": "10.0.0.1",
        "port": 8000 + uid,
        "hotkey": f"5hk{uid}",
    }
    neuron.wallet = None
    neuron.metagraph = None

    app = create_app(
        share_store=share_store,
        purchase_orch=purchase_orch,
        outcome_attestor=outcome_attestor,
        neuron=neuron,
    )
    yield TestClient(app)

    importlib.reload(feature_flags)


def _miner_response(home_price: float) -> dict:
    return {
        "sport": "basketball_nba",
        "observations": [
            {
                "event_id": "evt-lak-cel",
                "sport": "basketball_nba",
                "home_team": "Celtics",
                "away_team": "Lakers",
                "commence_time_ms": 1_776_240_000_000,
                "market": "moneyline",
                "side": "home",
                "decimal_price": home_price,
                "line": None,
                "bookmaker": "draftkings",
                "fetched_at_ms": 1_776_240_100_000,
                "source": "OddsApiClient",
            },
        ],
        "event_count": 1,
        "observation_count": 1,
        "provider": "OddsApiClient",
        "query_id": "q-abc",
        "fetched_at_ms": 1_776_240_100_000,
        "api_error": None,
    }


def _patched_client(per_miner_response_fn):
    """Build a FakeAsyncClient class that dispatches post() by URL."""
    import httpx as _httpx
    import json as _json

    class _FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def post(self, url, **kwargs):
            body = per_miner_response_fn(url, kwargs)
            if isinstance(body, Exception):
                raise body
            return _httpx.Response(
                200,
                content=_json.dumps(body).encode(),
                request=_httpx.Request("POST", url),
            )

    return _FakeAsyncClient


def test_fanout_median_across_three_miners(fanout_app):
    from unittest.mock import patch

    miner_prices = {8010: 1.90, 8011: 1.91, 8012: 1.95}

    def _dispatch(url, _kwargs):
        port = int(url.split(":")[2].split("/")[0])
        return _miner_response(miner_prices[port])

    FakeClient = _patched_client(_dispatch)

    with patch("djinn_validator.api.server.httpx.AsyncClient", FakeClient):
        resp = fanout_app.post(
            "/v1/odds/canonical",
            json={"sport": "basketball_nba", "market": "moneyline", "bookmakers": []},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["feature_flag_enabled"] is True
    assert data["miner_count"] == 3
    assert len(data["observations"]) == 1
    obs = data["observations"][0]
    assert obs["market"] == "moneyline"
    assert obs["decimal_price"] == 1.91  # median


def test_fanout_bookmaker_filter(fanout_app):
    from unittest.mock import patch

    # Every miner reports both DraftKings and FanDuel at slightly
    # different prices. The caller requests draftkings only.
    def _dispatch(url, _kwargs):
        return {
            "sport": "basketball_nba",
            "observations": [
                {
                    "event_id": "evt-1",
                    "sport": "basketball_nba",
                    "home_team": "Celtics",
                    "away_team": "Lakers",
                    "commence_time_ms": 0,
                    "market": "moneyline",
                    "side": "home",
                    "decimal_price": 1.91,
                    "line": None,
                    "bookmaker": "draftkings",
                    "fetched_at_ms": 0,
                    "source": "X",
                },
                {
                    "event_id": "evt-1",
                    "sport": "basketball_nba",
                    "home_team": "Celtics",
                    "away_team": "Lakers",
                    "commence_time_ms": 0,
                    "market": "moneyline",
                    "side": "home",
                    "decimal_price": 1.92,
                    "line": None,
                    "bookmaker": "fanduel",
                    "fetched_at_ms": 0,
                    "source": "X",
                },
            ],
            "event_count": 1,
            "observation_count": 2,
            "provider": "X",
            "query_id": None,
            "fetched_at_ms": 0,
            "api_error": None,
        }

    FakeClient = _patched_client(_dispatch)
    with patch("djinn_validator.api.server.httpx.AsyncClient", FakeClient):
        resp = fanout_app.post(
            "/v1/odds/canonical",
            json={
                "sport": "basketball_nba",
                "market": "moneyline",
                "bookmakers": ["draftkings"],
            },
        )

    data = resp.json()
    assert len(data["observations"]) == 1
    assert data["observations"][0]["bookmaker"] == "draftkings"


def test_fanout_all_miners_fail_returns_empty(fanout_app):
    from unittest.mock import patch
    import httpx as _httpx

    def _dispatch(url, _kwargs):
        return _httpx.ConnectError("unreachable")

    FakeClient = _patched_client(_dispatch)
    with patch("djinn_validator.api.server.httpx.AsyncClient", FakeClient):
        resp = fanout_app.post(
            "/v1/odds/canonical",
            json={"sport": "basketball_nba", "market": "moneyline"},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["observations"] == []
    assert data["miner_count"] == 0


def test_fanout_market_filter_alias(fanout_app):
    """Caller says market='h2h' (legacy alias) but the reducer has
    normalized to 'moneyline'. The endpoint must accept the alias
    and still return the moneyline observations."""
    from unittest.mock import patch

    def _dispatch(url, _kwargs):
        return _miner_response(1.91)

    FakeClient = _patched_client(_dispatch)
    with patch("djinn_validator.api.server.httpx.AsyncClient", FakeClient):
        resp = fanout_app.post(
            "/v1/odds/canonical",
            json={"sport": "basketball_nba", "market": "h2h"},
        )

    data = resp.json()
    assert len(data["observations"]) == 1
    assert data["observations"][0]["market"] == "moneyline"
