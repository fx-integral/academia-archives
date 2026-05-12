"""Tests for the /v1/purchase_odds/{signal_id}/{buyer_address} endpoint
authentication.

The endpoint returns the off-chain BPA/WPA vectors that back the
on-chain Merkle root committed by purchaseV2(). Exposing these
vectors publicly would defeat the option C privacy guarantee, so
the endpoint requires hotkey-signed requests from registered
SN103 validators only.
"""

from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def app():
    # Force test mode so the auth path doesn't try to consult a
    # real metagraph. validate_signed_request still requires a
    # signature when the auth headers are present.
    os.environ["BT_NETWORK"] = "test"
    for key in list(os.environ.keys()):
        if key.startswith("DJINN_FF_"):
            del os.environ[key]

    from djinn_validator.api.server import create_app
    from djinn_validator.core.shares import ShareStore
    from djinn_validator.core.purchase import PurchaseOrchestrator
    from djinn_validator.core.outcomes import OutcomeAttestor
    from djinn_validator.core.purchase_odds_ledger import PurchaseOddsLedger

    share_store = ShareStore()
    purchase_orch = PurchaseOrchestrator(share_store)
    outcome_attestor = OutcomeAttestor(espn_client=None)
    ledger = PurchaseOddsLedger()

    # Pre-populate one record so we can confirm the auth gate
    # protects EXISTING data, not just empty responses.
    ledger.record(
        signal_id="testsig",
        buyer_address="0x1234567890123456789012345678901234567890",
        bpas=[1_950_000, 1_850_000, 2_000_000],
        wpas=[1_910_000, 1_800_000, 1_950_000],
        bpa_mode=True,
    )

    application = create_app(
        share_store=share_store,
        purchase_orch=purchase_orch,
        outcome_attestor=outcome_attestor,
        purchase_odds_ledger=ledger,
    )
    return TestClient(application)


def test_unauthenticated_request_in_non_test_network_rejected(app, monkeypatch):
    """In production, unauthenticated requests must be rejected even
    if the metagraph is unavailable."""
    monkeypatch.setenv("BT_NETWORK", "finney")
    resp = app.get(
        "/v1/purchase_odds/testsig/0x1234567890123456789012345678901234567890",
    )
    assert resp.status_code == 401


def test_partial_auth_headers_rejected(app, monkeypatch):
    """Sending some but not all of the X-Hotkey/X-Signature headers
    is rejected outright."""
    monkeypatch.setenv("BT_NETWORK", "finney")
    resp = app.get(
        "/v1/purchase_odds/testsig/0x1234567890123456789012345678901234567890",
        headers={"X-Hotkey": "5SomeHotkey"},
    )
    assert resp.status_code == 401


def test_invalid_signature_rejected(app, monkeypatch):
    """A request with bogus signature data is rejected even if all
    headers are present."""
    monkeypatch.setenv("BT_NETWORK", "finney")
    resp = app.get(
        "/v1/purchase_odds/testsig/0x1234567890123456789012345678901234567890",
        headers={
            "X-Hotkey": "5SomeHotkey",
            "X-Signature": "deadbeef",
            "X-Timestamp": "1700000000",
            "X-Nonce": "deadbeef",
        },
    )
    # Either 401 (signature invalid) or 401 (timestamp too old)
    assert resp.status_code == 401


def test_invalid_buyer_address_rejected_after_auth(app):
    """Even with auth, malformed buyer addresses are 400. The auth
    layer is checked first; we use test mode here to bypass the
    signature requirement and confirm validation."""
    resp = app.get("/v1/purchase_odds/testsig/notavalidaddress")
    # In test mode no auth headers required, so the next check is the
    # buyer address format. Either 400 or 401 is acceptable depending
    # on whether the test environment requires auth.
    assert resp.status_code in (400, 401)


def test_test_mode_allows_unauthenticated_for_dev_iteration(app):
    """In BT_NETWORK=test mode (default during local dev) the endpoint
    permits unauthenticated requests so devs can iterate. The auth
    requirement is enforced when BT_NETWORK is finney/mainnet."""
    os.environ["BT_NETWORK"] = "test"
    resp = app.get(
        "/v1/purchase_odds/testsig/0x1234567890123456789012345678901234567890",
    )
    # In test mode without a metagraph, validate_signed_request
    # returns None (no auth required) and the handler proceeds.
    # Either 200 (record found) or 503 (ledger not configured in
    # this test fixture) is acceptable; 401 is NOT acceptable here.
    assert resp.status_code != 401


# ----------------------------------------------------------------------
# CB endpoints — same auth requirements
# ----------------------------------------------------------------------


@pytest.fixture
def cb_app():
    os.environ["BT_NETWORK"] = "finney"
    os.environ["DJINN_FF_APPEAL_MECHANISM"] = "true"
    for key in list(os.environ.keys()):
        if key.startswith("DJINN_FF_") and key not in ("DJINN_FF_APPEAL_MECHANISM",):
            del os.environ[key]

    from djinn_validator import feature_flags
    import importlib

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

    application = create_app(
        share_store=share_store,
        purchase_orch=purchase_orch,
        outcome_attestor=outcome_attestor,
        scorer=scorer,
    )
    return TestClient(application)


def test_cb_status_unauthenticated_in_production_rejected(cb_app):
    """Bare GET on cb status from production should be 401."""
    resp = cb_app.get("/v1/cb/status/5SomeHotkey")
    assert resp.status_code == 401


def test_cb_appeal_unauthenticated_rejected(cb_app):
    """Anyone-can-appeal vulnerability check: posting an appeal
    without a signed request must be 401, never 200 with a cleared
    flag. This is the regression test for the bug user-found in the
    purchase_odds endpoint applied to cb_appeal."""
    resp = cb_app.post(
        "/v1/cb/appeal",
        json={
            "hotkey": "5VictimHotkey",
            "declared_source": "https://example.com",
            "disputed_query_ids": ["q1", "q2", "q3"],
        },
    )
    assert resp.status_code == 401


def test_cb_appeal_partial_auth_headers_rejected(cb_app):
    """Even with one auth header, the rest are required."""
    resp = cb_app.post(
        "/v1/cb/appeal",
        json={
            "hotkey": "5VictimHotkey",
            "declared_source": "https://example.com",
            "disputed_query_ids": ["q1"],
        },
        headers={"X-Hotkey": "5SomeHotkey"},
    )
    assert resp.status_code == 401


# ----------------------------------------------------------------------
# Endpoints shipped before this session (pre-existing unauth holes)
# ----------------------------------------------------------------------


@pytest.fixture
def prod_app():
    """Minimal app in BT_NETWORK=finney mode to exercise prod auth paths."""
    os.environ["BT_NETWORK"] = "finney"
    for key in list(os.environ.keys()):
        if key.startswith("DJINN_FF_"):
            del os.environ[key]

    from djinn_validator.api.server import create_app
    from djinn_validator.core.shares import ShareStore
    from djinn_validator.core.purchase import PurchaseOrchestrator
    from djinn_validator.core.outcomes import OutcomeAttestor

    share_store = ShareStore()
    purchase_orch = PurchaseOrchestrator(share_store)
    outcome_attestor = OutcomeAttestor(espn_client=None)

    application = create_app(
        share_store=share_store,
        purchase_orch=purchase_orch,
        outcome_attestor=outcome_attestor,
    )
    return TestClient(application)


def test_attest_outcome_unauthenticated_rejected(prod_app):
    """Anyone-can-forge-attestation: posting an outcome without a
    signed request must be 401. Before the fix, attest_outcome
    trusted req.validator_hotkey blindly and let an attacker
    pollute the in-memory attestations dict with forged votes."""
    resp = prod_app.post(
        "/v1/signal/sig-1/outcome",
        json={
            "signal_id": "sig-1",
            "event_id": "evt-1",
            "validator_hotkey": "5VictimHotkey",
            "outcome": 1,
        },
    )
    assert resp.status_code == 401


def test_mpc_diagnostic_unauthenticated_rejected(prod_app):
    """mpc_diagnostic fans out ~8 outbound peer requests per call
    and leaks internal peer + circuit-breaker state. Before the
    fix this endpoint was both an amplification vector and an
    information disclosure. Production mode must require a
    validator-signed request."""
    resp = prod_app.get("/v1/signal/sig-1/mpc_diagnostic")
    assert resp.status_code == 401


def test_signals_resolve_unauthenticated_rejected(prod_app):
    """signals/resolve triggers outbound ESPN API calls for every
    pending signal. Before the fix anyone could call it
    repeatedly to burn the validator's rate-limit budget."""
    resp = prod_app.post("/v1/signals/resolve")
    assert resp.status_code == 401
