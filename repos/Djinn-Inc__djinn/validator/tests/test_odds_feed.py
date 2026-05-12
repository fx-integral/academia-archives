"""Tests for Sprint-A validator odds endpoints + odds_feed module.

Mirrors behavior of `web/app/api/odds/__tests__/*` so cross-checking the
Next implementation against the validator stays trivial.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from fastapi.testclient import TestClient

from djinn_validator.api.server import create_app
from djinn_validator.core import odds_feed
from djinn_validator.core.outcomes import OutcomeAttestor
from djinn_validator.core.purchase import PurchaseOrchestrator
from djinn_validator.core.shares import ShareStore


@pytest.fixture(autouse=True)
def reset_odds_state():
    odds_feed.reset_state_for_tests()
    yield
    odds_feed.reset_state_for_tests()


@pytest.fixture
def client():
    store = ShareStore()
    try:
        orch = PurchaseOrchestrator(store)
        att = OutcomeAttestor()
        app = create_app(store, orch, att)
        yield TestClient(app)
    finally:
        store.close()


def _mock_200(payload):
    async def _get(url, params=None):
        return httpx.Response(
            200, json=payload, request=httpx.Request("GET", url)
        )

    c = AsyncMock(spec=httpx.AsyncClient)
    c.get = AsyncMock(side_effect=_get)
    return c


def _mock_status(status):
    async def _get(url, params=None):
        return httpx.Response(
            status,
            text=f"upstream {status}",
            request=httpx.Request("GET", url),
        )

    c = AsyncMock(spec=httpx.AsyncClient)
    c.get = AsyncMock(side_effect=_get)
    return c


# --- validation helpers ---

def test_validate_sport_rejects_unknown():
    with pytest.raises(odds_feed._InvalidRequest):
        odds_feed.validate_sport("cricket_t20")


def test_validate_sport_accepts_nba():
    assert odds_feed.validate_sport("basketball_nba") == "basketball_nba"


def test_validate_markets_defaults_when_empty():
    assert odds_feed.validate_markets(None) == "spreads,totals,h2h"


def test_validate_markets_filters_disallowed():
    assert odds_feed.validate_markets("spreads,alt_spreads,h2h") == "spreads,h2h"


def test_validate_markets_all_invalid_raises():
    with pytest.raises(odds_feed._InvalidRequest):
        odds_feed.validate_markets("foo,bar,baz")


def test_is_key_failure_classification():
    assert odds_feed.is_key_failure(401) is True
    assert odds_feed.is_key_failure(403) is True
    assert odds_feed.is_key_failure(429) is True
    assert odds_feed.is_key_failure(500) is True
    assert odds_feed.is_key_failure(503) is True
    assert odds_feed.is_key_failure(400) is False
    assert odds_feed.is_key_failure(404) is False
    assert odds_feed.is_key_failure(422) is False


# --- endpoints ---

def test_sports_endpoint_returns_catalog(client):
    resp = client.get("/v1/sports")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 8
    assert body["sports"][0]["key"] == "basketball_nba"
    # ESPN score-resolvable subset
    keys = [s["key"] for s in body["sports"]]
    assert "basketball_nba" in keys
    assert "icehockey_nhl" in keys
    assert "soccer_epl" in keys


def test_odds_endpoint_503_when_no_keys(client, monkeypatch):
    monkeypatch.setattr(odds_feed, "get_api_keys", lambda: [])
    resp = client.get("/v1/odds/basketball_nba")
    assert resp.status_code == 503
    assert "not configured" in resp.json()["detail"].lower()


def test_odds_endpoint_400_on_unknown_sport(client, monkeypatch):
    monkeypatch.setattr(odds_feed, "get_api_keys", lambda: ["k1"])
    resp = client.get("/v1/odds/cricket_t20")
    assert resp.status_code == 400


def test_odds_endpoint_happy_path_uses_cache(client, monkeypatch):
    monkeypatch.setattr(odds_feed, "get_api_keys", lambda: ["k1"])
    call_count = {"n": 0}

    async def _get(url, params=None):
        call_count["n"] += 1
        return httpx.Response(
            200, json=[{"id": "evt1"}], request=httpx.Request("GET", url)
        )

    # Inject a mock client by patching the module's httpx.AsyncClient ctor.
    class _StubClient:
        def __init__(self, *a, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def aclose(self):
            pass

        async def get(self, url, params=None):
            return await _get(url, params)

    monkeypatch.setattr(odds_feed.httpx, "AsyncClient", _StubClient)

    r1 = client.get("/v1/odds/basketball_nba")
    assert r1.status_code == 200, r1.text
    assert r1.json() == [{"id": "evt1"}]
    # Second request within TTL must hit cache.
    r2 = client.get("/v1/odds/basketball_nba")
    assert r2.status_code == 200
    assert call_count["n"] == 1


def test_odds_endpoint_502_when_all_keys_fail(client, monkeypatch):
    monkeypatch.setattr(odds_feed, "get_api_keys", lambda: ["k1", "k2"])
    seen = []

    class _StubClient:
        def __init__(self, *a, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def aclose(self):
            pass

        async def get(self, url, params=None):
            seen.append(params.get("apiKey"))
            return httpx.Response(
                429, text="rate limited", request=httpx.Request("GET", url)
            )

    monkeypatch.setattr(odds_feed.httpx, "AsyncClient", _StubClient)

    r = client.get("/v1/odds/basketball_nba")
    assert r.status_code == 502
    # Both keys were tried before bailing out.
    assert set(seen) == {"k1", "k2"}


def test_odds_endpoint_negative_cache_short_circuits(client, monkeypatch):
    monkeypatch.setattr(odds_feed, "get_api_keys", lambda: ["k1"])

    call_count = {"n": 0}

    class _StubClient:
        def __init__(self, *a, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def aclose(self):
            pass

        async def get(self, url, params=None):
            call_count["n"] += 1
            return httpx.Response(
                429, text="rate limited", request=httpx.Request("GET", url)
            )

    monkeypatch.setattr(odds_feed.httpx, "AsyncClient", _StubClient)

    r1 = client.get("/v1/odds/basketball_nba")
    assert r1.status_code == 502
    assert call_count["n"] == 1

    r2 = client.get("/v1/odds/basketball_nba")
    assert r2.status_code == 502
    # Neg cache blocked the second try; no upstream call.
    assert call_count["n"] == 1


def test_odds_endpoint_non_retriable_status_does_not_advance(client, monkeypatch):
    monkeypatch.setattr(odds_feed, "get_api_keys", lambda: ["k1", "k2"])
    seen = []

    class _StubClient:
        def __init__(self, *a, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def aclose(self):
            pass

        async def get(self, url, params=None):
            seen.append(params.get("apiKey"))
            return httpx.Response(404, text="not found", request=httpx.Request("GET", url))

    monkeypatch.setattr(odds_feed.httpx, "AsyncClient", _StubClient)

    r = client.get("/v1/odds/basketball_nba")
    assert r.status_code == 502
    # 404 bails after first key (same across keys).
    assert len(seen) == 1


def test_odds_alt_endpoint_happy_path(client, monkeypatch):
    monkeypatch.setattr(odds_feed, "get_api_keys", lambda: ["k1"])

    class _StubClient:
        def __init__(self, *a, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def aclose(self):
            pass

        async def get(self, url, params=None):
            return httpx.Response(
                200, json={"event_id": "abc", "bookmakers": []},
                request=httpx.Request("GET", url),
            )

    monkeypatch.setattr(odds_feed.httpx, "AsyncClient", _StubClient)

    r = client.get("/v1/odds/basketball_nba/events/abc/alt")
    assert r.status_code == 200, r.text
    assert r.json()["event_id"] == "abc"


def test_odds_alt_endpoint_rejects_bad_sport(client, monkeypatch):
    monkeypatch.setattr(odds_feed, "get_api_keys", lambda: ["k1"])
    r = client.get("/v1/odds/cricket_t20/events/abc/alt")
    assert r.status_code == 400


def test_rotation_shared_across_main_and_alt(client, monkeypatch):
    monkeypatch.setattr(odds_feed, "get_api_keys", lambda: ["kA", "kB"])

    stage = {"n": 0}
    keys_used = []

    class _StubClient:
        def __init__(self, *a, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def aclose(self):
            pass

        async def get(self, url, params=None):
            keys_used.append(params.get("apiKey"))
            stage["n"] += 1
            # First main call: 429 on kA (advance to kB), then OK.
            # Alt call: should start at kB without probing kA.
            if stage["n"] == 1:
                return httpx.Response(429, text="x", request=httpx.Request("GET", url))
            return httpx.Response(
                200,
                json=([] if "odds?" in url or "/odds" in url.split("/events/")[0] else {"ok": True}),
                request=httpx.Request("GET", url),
            )

    monkeypatch.setattr(odds_feed.httpx, "AsyncClient", _StubClient)

    r1 = client.get("/v1/odds/basketball_nba")
    assert r1.status_code == 200, r1.text
    # kA failed, kB succeeded. Rotation pointer now on kB.
    assert keys_used[:2] == ["kA", "kB"]

    r2 = client.get("/v1/odds/basketball_nba/events/x/alt")
    assert r2.status_code == 200
    # Alt started on kB (shared rotation) — no kA retry.
    assert keys_used[2] == "kB"


def test_debug_metagraph_503_without_neuron(client):
    # Admin auth is a no-op when ADMIN_API_KEY is unset (same pattern as
    # /v1/activity + /v1/telemetry). With no neuron attached in this fixture,
    # the endpoint 503s instead of crashing.
    r = client.get("/v1/debug/metagraph")
    assert r.status_code == 503
    assert "metagraph" in r.json()["detail"].lower()
