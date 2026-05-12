"""Tests for the consensus circuit breaker /v1/cb/status and /v1/cb/appeal
endpoints.

The auth-enforcement path is tested separately in
test_purchase_odds_endpoint_auth.py. This file uses BT_NETWORK=test
mode so the cb endpoints take the same permissive escape hatch
validate_signed_request uses; the tests focus on business logic.
"""

from __future__ import annotations

import importlib
import os

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def app_with_cb(monkeypatch):
    """Build a FastAPI test client with the circuit breaker wired and
    optional flag toggling."""
    for key in list(os.environ.keys()):
        if key.startswith("DJINN_FF_"):
            monkeypatch.delenv(key, raising=False)

    def _build(*, appeal_on: bool = False, cb_on: bool = False):
        # BT_NETWORK=test makes the cb_status and cb_appeal endpoints
        # skip their auth check entirely (the same escape hatch
        # validate_signed_request uses for unauthenticated test
        # mode). Production uses BT_NETWORK=finney/mainnet which
        # enforces the auth check. The auth-enforcement path is
        # tested separately in test_purchase_odds_endpoint_auth.py.
        monkeypatch.setenv("BT_NETWORK", "test")
        if appeal_on:
            monkeypatch.setenv("DJINN_FF_APPEAL_MECHANISM", "true")
        if cb_on:
            monkeypatch.setenv("DJINN_FF_CIRCUIT_BREAKER", "true")
        from djinn_validator import feature_flags

        importlib.reload(feature_flags)

        from djinn_validator.api.server import create_app
        from djinn_validator.core.shares import ShareStore
        from djinn_validator.core.purchase import PurchaseOrchestrator
        from djinn_validator.core.outcomes import OutcomeAttestor
        from djinn_validator.core.scoring import MinerScorer
        from djinn_validator.core.circuit_breaker import ConsensusCircuitBreaker

        share_store = ShareStore()
        purchase_orch = PurchaseOrchestrator(share_store)
        outcome_attestor = OutcomeAttestor(espn_client=None)
        cb = ConsensusCircuitBreaker(tolerance=0.005, flag_threshold=5.0)
        scorer = MinerScorer(circuit_breaker=cb)

        app = create_app(
            share_store=share_store,
            purchase_orch=purchase_orch,
            outcome_attestor=outcome_attestor,
            scorer=scorer,
        )
        return TestClient(app), cb

    yield _build

    # monkeypatch fixture restores BT_NETWORK and DJINN_FF_* env vars
    # automatically. We just reload the feature_flags singleton to
    # forget any reloads done during the test.
    for key in list(os.environ.keys()):
        if key.startswith("DJINN_FF_"):
            monkeypatch.delenv(key, raising=False)
    from djinn_validator import feature_flags as _ff

    importlib.reload(_ff)


# ----------------------------------------------------------------------
# /v1/cb/status
# ----------------------------------------------------------------------


def test_status_unknown_hotkey_returns_default(app_with_cb):
    client, _ = app_with_cb()
    resp = client.get("/v1/cb/status/5UnknownHotkey")
    assert resp.status_code == 200
    body = resp.json()
    assert body["hotkey"] == "5UnknownHotkey"
    assert body["score"] == 0.0
    assert body["sample_count"] == 0
    assert body["flagged"] is False
    assert body["last_disputes"] == []


def test_status_after_observations(app_with_cb):
    client, cb = app_with_cb()
    for i in range(10):
        cb.record_observation(hotkey="5Aa", deviation=0.05, query_id=f"q{i}")
    resp = client.get("/v1/cb/status/5Aa")
    assert resp.status_code == 200
    body = resp.json()
    assert body["sample_count"] == 10
    assert body["score"] > 0
    assert len(body["last_disputes"]) == 10


def test_status_for_flagged_miner(app_with_cb):
    client, cb = app_with_cb()
    for i in range(200):
        cb.record_observation(hotkey="5BadKey", deviation=0.05, query_id=f"q{i}")
    resp = client.get("/v1/cb/status/5BadKey")
    body = resp.json()
    assert body["flagged"] is True
    assert body["flagged_at"] > 0
    assert body["score"] >= 5.0


def test_status_invalid_hotkey_too_long(app_with_cb):
    client, _ = app_with_cb()
    resp = client.get("/v1/cb/status/" + "x" * 200)
    assert resp.status_code == 400


# ----------------------------------------------------------------------
# /v1/cb/appeal
# ----------------------------------------------------------------------


def test_appeal_503_when_flag_off(app_with_cb):
    client, cb = app_with_cb()
    for i in range(200):
        cb.record_observation(hotkey="5Aa", deviation=0.05, query_id=f"q{i}")
    resp = client.post(
        "/v1/cb/appeal",
        json={
            "hotkey": "5Aa",
            "declared_source": "https://example.com",
            "disputed_query_ids": ["q1"],
        },
    )
    assert resp.status_code == 503


def test_appeal_not_flagged_returns_no_op(app_with_cb):
    client, cb = app_with_cb(appeal_on=True)
    cb.get_or_create("5Aa")
    resp = client.post(
        "/v1/cb/appeal",
        json={
            "hotkey": "5Aa",
            "declared_source": "https://example.com",
            "disputed_query_ids": ["q1"],
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["verdict"] == "not_flagged"
    assert body["cleared"] is False


def test_appeal_honor_system_accepted(app_with_cb):
    client, cb = app_with_cb(appeal_on=True)
    for i in range(200):
        cb.record_observation(hotkey="5Aa", deviation=0.05, query_id=f"q{i}")
    assert cb.is_flagged("5Aa")

    state = cb.get_state("5Aa")
    recorded_ids = [qid for qid, _ in state.last_disputes]

    resp = client.post(
        "/v1/cb/appeal",
        json={
            "hotkey": "5Aa",
            "declared_source": "https://example.com",
            "disputed_query_ids": recorded_ids[:3],
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["verdict"] == "honor_system_accepted"
    assert body["cleared"] is True
    assert body["new_score"] == 0.0
    assert body["verification_mode"] == "honor_system"
    assert not cb.is_flagged("5Aa")


def test_appeal_denied_when_disputes_dont_match(app_with_cb):
    client, cb = app_with_cb(appeal_on=True)
    for i in range(200):
        cb.record_observation(hotkey="5Aa", deviation=0.05, query_id=f"q{i}")
    resp = client.post(
        "/v1/cb/appeal",
        json={
            "hotkey": "5Aa",
            "declared_source": "https://example.com",
            "disputed_query_ids": ["wrong_id_1", "wrong_id_2"],
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["verdict"] == "denied"
    assert body["cleared"] is False
    assert cb.is_flagged("5Aa")  # still flagged


def test_appeal_validates_required_fields(app_with_cb):
    client, _ = app_with_cb(appeal_on=True)
    resp = client.post("/v1/cb/appeal", json={"hotkey": "5Aa"})
    assert resp.status_code == 422
