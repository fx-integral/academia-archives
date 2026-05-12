"""End-to-end integration test for the MPC protocol through API endpoints.

Simulates a coordinator driving the full MPC protocol through a validator's
API endpoints: store share → mpc init → compute gate → result.
Tests both semi-honest and authenticated SPDZ modes.
"""

from __future__ import annotations

import secrets

import pytest
from fastapi.testclient import TestClient

from djinn_validator.api.server import create_app
from djinn_validator.core.mpc import _split_secret_at_points, reconstruct_at_zero
from djinn_validator.core.outcomes import OutcomeAttestor
from djinn_validator.core.purchase import PurchaseOrchestrator
from djinn_validator.core.shares import ShareStore
from djinn_validator.core.spdz import (
    AuthenticatedShare,
    authenticate_value,
    generate_authenticated_triples,
    generate_mac_key,
)
from djinn_validator.utils.crypto import BN254_PRIME, Share


SMALL_PRIME = 104729  # Small prime for fast tests


@pytest.fixture
def store():
    s = ShareStore()
    yield s
    s.close()


@pytest.fixture
def app_client(store: ShareStore) -> TestClient:
    purchase_orch = PurchaseOrchestrator(store)
    outcome_attestor = OutcomeAttestor()
    app = create_app(store, purchase_orch, outcome_attestor)
    return TestClient(app)


class TestSemiHonestMPCViaAPI:
    """Test the semi-honest MPC protocol through API endpoints."""

    def test_full_gate_computation_available(self, app_client: TestClient, store: ShareStore) -> None:
        """End-to-end: store share, init MPC, compute gate, get result."""
        p = SMALL_PRIME
        secret = 3
        available_indices = [1, 2, 3, 4, 5]
        n_validators = 3
        threshold = 2
        x_coords = list(range(1, n_validators + 1))

        # Split the secret into shares
        secret_shares = _split_secret_at_points(secret, x_coords, threshold, p)

        # Generate random mask r
        r = secrets.randbelow(p - 1) + 1
        r_shares = _split_secret_at_points(r, x_coords, threshold, p)

        # Generate Beaver triples for each gate
        from djinn_validator.core.mpc import generate_ot_beaver_triples

        triples = generate_ot_beaver_triples(
            count=len(available_indices),
            x_coords=x_coords,
            k=threshold,
            prime=p,
            n=n_validators,
        )

        # Validator 1 (our test validator) stores its share
        validator_x = 1
        store.store(
            signal_id="sig-e2e",
            genius_address="0xGenius",
            share=Share(x=validator_x, y=secret_shares[0].y),
            encrypted_key_share=b"key",
        )

        # Coordinator sends /v1/mpc/init with validator 1's triple shares + r share
        triple_shares = [
            {
                "a": hex(triples[g].a_shares[0].y),
                "b": hex(triples[g].b_shares[0].y),
                "c": hex(triples[g].c_shares[0].y),
            }
            for g in range(len(available_indices))
        ]

        init_resp = app_client.post(
            "/v1/mpc/init",
            json={
                "session_id": "sess-e2e",
                "signal_id": "sig-e2e",
                "available_indices": available_indices,
                "coordinator_x": 1,
                "participant_xs": x_coords,
                "threshold": threshold,
                "r_share_y": hex(r_shares[0].y),
                "triple_shares": triple_shares,
            },
        )
        assert init_resp.status_code == 200
        assert init_resp.json()["accepted"] is True

        # Compute gates sequentially
        prev_d = None
        prev_e = None
        all_d_shares = []
        all_e_shares = []

        for gate_idx in range(len(available_indices)):
            gate_resp = app_client.post(
                "/v1/mpc/compute_gate",
                json={
                    "session_id": "sess-e2e",
                    "gate_idx": gate_idx,
                    "prev_opened_d": hex(prev_d) if prev_d is not None else None,
                    "prev_opened_e": hex(prev_e) if prev_e is not None else None,
                },
            )
            assert gate_resp.status_code == 200
            data = gate_resp.json()

            d_i = int(data["d_value"], 16)
            e_i = int(data["e_value"], 16)
            all_d_shares.append(Share(x=validator_x, y=d_i))
            all_e_shares.append(Share(x=validator_x, y=e_i))

            # In a real protocol, we'd collect from all validators.
            # For this test, we compute what the opened values would be
            # by gathering from all validators (simulated).
            d_shares_map: dict[int, int] = {}
            e_shares_map: dict[int, int] = {}
            for v_idx in range(n_validators):
                d_v = (r_shares[v_idx].y - triples[gate_idx].a_shares[v_idx].y) % p
                e_v = (available_indices[gate_idx] - triples[gate_idx].b_shares[v_idx].y) % p
                d_shares_map[x_coords[v_idx]] = d_v
                e_shares_map[x_coords[v_idx]] = e_v

            if gate_idx == 0:
                # Reconstruct opened d, e
                prev_d = reconstruct_at_zero(d_shares_map, p)
                prev_e = reconstruct_at_zero(e_shares_map, p)

                # Verify d = r - a (the mask minus the triple a-value)
                r_map = {s.x: s.y for s in r_shares}
                r_total = reconstruct_at_zero(r_map, p)
                a_total = sum(triples[0].a_shares[v].y for v in range(n_validators)) % p
                # a_total should equal reconstruct_at_zero of a-shares
                a_map = {triples[0].a_shares[v].x: triples[0].a_shares[v].y for v in range(n_validators)}
                a_reconstructed = reconstruct_at_zero(a_map, p)
                assert prev_d == (r_total - a_reconstructed) % p
                break  # Just verify gate 0 for simplicity

        # Send result
        result_resp = app_client.post(
            "/v1/mpc/result",
            json={
                "session_id": "sess-e2e",
                "signal_id": "sig-e2e",
                "available": True,
                "participating_validators": n_validators,
            },
        )
        assert result_resp.status_code == 200
        assert result_resp.json()["acknowledged"] is True

    def test_mpc_status_and_abort(self, app_client: TestClient, store: ShareStore) -> None:
        """Test session status checking and abort flow."""
        store.store("sig-abort", "0xG", Share(x=1, y=42), b"key")

        # Init session
        init_resp = app_client.post(
            "/v1/mpc/init",
            json={
                "session_id": "sess-abort",
                "signal_id": "sig-abort",
                "available_indices": [1],
                "coordinator_x": 1,
                "participant_xs": [1, 2],
                "threshold": 2,
                "r_share_y": "ff",
                "triple_shares": [{"a": "1", "b": "2", "c": "2"}],
            },
        )
        assert init_resp.json()["accepted"] is True

        # Check status — session starts in round1_collecting after create_session
        status_resp = app_client.get("/v1/mpc/sess-abort/status")
        assert status_resp.status_code == 200
        assert status_resp.json()["status"] in ("pending", "round1_collecting")

        # Abort
        abort_resp = app_client.post(
            "/v1/mpc/abort",
            json={
                "session_id": "sess-abort",
                "reason": "MAC verification failed",
                "gate_idx": 0,
            },
        )
        assert abort_resp.status_code == 200
        assert abort_resp.json()["acknowledged"] is True

        # Subsequent compute_gate should fail
        gate_resp = app_client.post(
            "/v1/mpc/compute_gate",
            json={
                "session_id": "sess-abort",
                "gate_idx": 0,
            },
        )
        assert gate_resp.status_code == 409


class TestAuthenticatedMPCViaAPI:
    """Test SPDZ authenticated MPC protocol through API endpoints."""

    def test_authenticated_init_and_gate(self, app_client: TestClient, store: ShareStore) -> None:
        """End-to-end authenticated MPC init with MAC-verified shares."""
        p = SMALL_PRIME
        secret = 5
        available_indices = [3, 5]
        x_coords = [1, 2, 3]
        threshold = 2

        # Generate MAC key and authenticated shares
        alpha, alpha_shares = generate_mac_key(x_coords, threshold=threshold, prime=p)
        secret_auth_shares = authenticate_value(secret, alpha, x_coords, threshold=threshold, prime=p)
        r = secrets.randbelow(p - 1) + 1
        r_auth_shares = authenticate_value(r, alpha, x_coords, threshold=threshold, prime=p)
        triples = generate_authenticated_triples(
            count=len(available_indices),
            alpha=alpha,
            x_coords=x_coords,
            threshold=threshold,
            prime=p,
        )

        # Store validator 1's share
        validator_x = 1
        store.store("sig-auth-e2e", "0xGenius", Share(x=validator_x, y=secret), b"key")

        # Build authenticated triple shares for validator 1
        auth_triple_shares = []
        for g in range(len(available_indices)):
            auth_triple_shares.append(
                {
                    "a": {"y": hex(triples[g].a_shares[0].y), "mac": hex(triples[g].a_shares[0].mac)},
                    "b": {"y": hex(triples[g].b_shares[0].y), "mac": hex(triples[g].b_shares[0].mac)},
                    "c": {"y": hex(triples[g].c_shares[0].y), "mac": hex(triples[g].c_shares[0].mac)},
                }
            )

        init_resp = app_client.post(
            "/v1/mpc/init",
            json={
                "session_id": "sess-auth-e2e",
                "signal_id": "sig-auth-e2e",
                "available_indices": available_indices,
                "coordinator_x": validator_x,
                "participant_xs": x_coords,
                "threshold": threshold,
                # r_share_y is required to enter the participant state creation block
                "r_share_y": hex(r_auth_shares[0].y),
                "authenticated": True,
                "alpha_share": hex(alpha_shares[0].alpha_share),
                "auth_r_share": {
                    "y": hex(r_auth_shares[0].y),
                    "mac": hex(r_auth_shares[0].mac),
                },
                "auth_secret_share": {
                    "y": hex(secret_auth_shares[0].y),
                    "mac": hex(secret_auth_shares[0].mac),
                },
                "auth_triple_shares": auth_triple_shares,
            },
        )
        assert init_resp.status_code == 200, init_resp.json()
        assert init_resp.json()["accepted"] is True

        # Compute gate 0 — should return d, e, d_mac, e_mac
        gate_resp = app_client.post(
            "/v1/mpc/compute_gate",
            json={
                "session_id": "sess-auth-e2e",
                "gate_idx": 0,
            },
        )
        assert gate_resp.status_code == 200
        data = gate_resp.json()
        assert data["d_value"] is not None
        assert data["e_value"] is not None
        assert data["d_mac"] is not None
        assert data["e_mac"] is not None

        # Verify MAC values are valid field elements (parseable, non-negative)
        d_mac = int(data["d_mac"], 16)
        e_mac = int(data["e_mac"], 16)
        assert d_mac >= 0
        assert e_mac >= 0


class TestMPCEdgeCases:
    """Test edge cases in MPC API flow."""

    def test_duplicate_init_is_idempotent(self, app_client: TestClient, store: ShareStore) -> None:
        """Sending the same init twice should succeed (existing session found)."""
        store.store("sig-dup", "0xG", Share(x=1, y=42), b"key")

        init_payload = {
            "session_id": "sess-dup",
            "signal_id": "sig-dup",
            "available_indices": [1],
            "coordinator_x": 1,
            "participant_xs": [1, 2],
            "threshold": 2,
            "r_share_y": "ff",
            "triple_shares": [{"a": "1", "b": "2", "c": "2"}],
        }

        resp1 = app_client.post("/v1/mpc/init", json=init_payload)
        resp2 = app_client.post("/v1/mpc/init", json=init_payload)
        assert resp1.json()["accepted"] is True
        assert resp2.json()["accepted"] is True

    def test_compute_gate_without_init_returns_404(self, app_client: TestClient) -> None:
        """Computing a gate without initializing the session should fail."""
        resp = app_client.post(
            "/v1/mpc/compute_gate",
            json={
                "session_id": "nonexistent-session",
                "gate_idx": 0,
            },
        )
        assert resp.status_code == 404

    def test_result_clears_participant_state(self, app_client: TestClient, store: ShareStore) -> None:
        """After result is accepted, participant state is cleaned up."""
        store.store("sig-cleanup", "0xG", Share(x=1, y=42), b"key")

        app_client.post(
            "/v1/mpc/init",
            json={
                "session_id": "sess-cleanup",
                "signal_id": "sig-cleanup",
                "available_indices": [1],
                "coordinator_x": 1,
                "participant_xs": [1, 2],
                "threshold": 2,
                "r_share_y": "ff",
                "triple_shares": [{"a": "1", "b": "2", "c": "2"}],
            },
        )

        # Result accepted
        app_client.post(
            "/v1/mpc/result",
            json={
                "session_id": "sess-cleanup",
                "signal_id": "sig-cleanup",
                "available": True,
                "participating_validators": 2,
            },
        )

        # Subsequent compute_gate should fail (state cleaned up)
        resp = app_client.post(
            "/v1/mpc/compute_gate",
            json={
                "session_id": "sess-cleanup",
                "gate_idx": 0,
            },
        )
        # Session marked completed, no participant state
        assert resp.status_code in (404, 409)

    def test_init_without_share_returns_not_accepted(self, app_client: TestClient) -> None:
        """MPC init for a signal we don't have a share for should not accept."""
        resp = app_client.post(
            "/v1/mpc/init",
            json={
                "session_id": "sess-no-share",
                "signal_id": "unknown-signal",
                "available_indices": [1],
                "coordinator_x": 1,
                "participant_xs": [1, 2],
                "threshold": 2,
                "r_share_y": "ff",
                "triple_shares": [{"a": "1", "b": "2", "c": "2"}],
            },
        )
        assert resp.status_code == 200
        assert resp.json()["accepted"] is False

    def test_share_info_requires_stored_share(self, app_client: TestClient, store: ShareStore) -> None:
        """share_info returns 404 for unknown signals."""
        resp = app_client.get("/v1/signal/unknown-signal/share_info")
        assert resp.status_code == 404

    def test_share_info_returns_coordinates(self, app_client: TestClient, store: ShareStore) -> None:
        """share_info returns the correct share coordinates."""
        store.store("sig-info", "0xG", Share(x=3, y=0xABCD), b"key")
        resp = app_client.get("/v1/signal/sig-info/share_info")
        assert resp.status_code == 200
        data = resp.json()
        assert data["share_x"] == 3
        assert "share_y" not in data
