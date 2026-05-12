"""Tests for the inter-validator MPC API endpoints."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from djinn_validator.api.server import create_app
from djinn_validator.core.mpc_coordinator import MPCCoordinator
from djinn_validator.core.outcomes import OutcomeAttestor
from djinn_validator.core.purchase import PurchaseOrchestrator
from djinn_validator.core.shares import ShareStore
from djinn_validator.utils.crypto import Share


@pytest.fixture
def coordinator() -> MPCCoordinator:
    return MPCCoordinator()


@pytest.fixture
def client(coordinator: MPCCoordinator) -> TestClient:
    share_store = ShareStore()
    purchase_orch = PurchaseOrchestrator(share_store)
    outcome_attestor = OutcomeAttestor()
    app = create_app(
        share_store,
        purchase_orch,
        outcome_attestor,
        mpc_coordinator=coordinator,
    )
    return TestClient(app)


class TestMPCInit:
    def test_init_session(self, client: TestClient, coordinator: MPCCoordinator) -> None:
        resp = client.post(
            "/v1/mpc/init",
            json={
                "session_id": "mpc-test-001",
                "signal_id": "sig-1",
                "available_indices": [1, 3, 5],
                "coordinator_x": 1,
                "participant_xs": [1, 2, 3, 4, 5, 6, 7],
                "threshold": 7,
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["accepted"] is True
        assert data["session_id"] == "mpc-test-001"

        # Session exists in coordinator
        session = coordinator.get_session("mpc-test-001")
        assert session is not None
        assert session.signal_id == "sig-1"

    def test_init_duplicate_accepted(self, client: TestClient) -> None:
        payload = {
            "session_id": "mpc-dup",
            "signal_id": "sig-1",
            "available_indices": [1],
            "coordinator_x": 1,
            "participant_xs": [1, 2, 3],
            "threshold": 3,
        }
        client.post("/v1/mpc/init", json=payload)
        resp = client.post("/v1/mpc/init", json=payload)
        assert resp.status_code == 200
        assert resp.json()["accepted"] is True


class TestMPCRound1:
    def test_submit_round1(self, client: TestClient, coordinator: MPCCoordinator) -> None:
        # Create session first
        coordinator.create_session("sig-1", [1], 1, [1, 2, 3], 3)
        session = list(coordinator._sessions.values())[0]

        resp = client.post(
            "/v1/mpc/round1",
            json={
                "session_id": session.session_id,
                "gate_idx": 0,
                "validator_x": 1,
                "d_value": hex(42),
                "e_value": hex(99),
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["accepted"] is True

    def test_submit_nonexistent_session(self, client: TestClient) -> None:
        resp = client.post(
            "/v1/mpc/round1",
            json={
                "session_id": "nope",
                "gate_idx": 0,
                "validator_x": 1,
                "d_value": hex(1),
                "e_value": hex(1),
            },
        )
        assert resp.status_code == 200
        assert resp.json()["accepted"] is False


class TestMPCResult:
    def test_accept_result(self, client: TestClient, coordinator: MPCCoordinator) -> None:
        session = coordinator.create_session("sig-1", [1], 1, [1, 2, 3], 3)

        resp = client.post(
            "/v1/mpc/result",
            json={
                "session_id": session.session_id,
                "signal_id": "sig-1",
                "available": True,
                "participating_validators": 3,
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["acknowledged"] is True

        # Verify session updated
        updated = coordinator.get_session(session.session_id)
        assert updated is not None
        assert updated.result is not None
        assert updated.result.available is True

    def test_result_nonexistent_session(self, client: TestClient) -> None:
        resp = client.post(
            "/v1/mpc/result",
            json={
                "session_id": "nope",
                "signal_id": "sig-1",
                "available": False,
                "participating_validators": 0,
            },
        )
        assert resp.status_code == 200
        assert resp.json()["acknowledged"] is False


class TestMPCStatus:
    def test_status_existing(self, client: TestClient, coordinator: MPCCoordinator) -> None:
        session = coordinator.create_session("sig-1", [1, 2], 1, [1, 2, 3], 3)

        resp = client.get(f"/v1/mpc/{session.session_id}/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "round1_collecting"
        assert data["total_participants"] == 3

    def test_status_nonexistent(self, client: TestClient) -> None:
        resp = client.get("/v1/mpc/nope/status")
        assert resp.status_code == 404

    def test_status_after_result(self, client: TestClient, coordinator: MPCCoordinator) -> None:
        session = coordinator.create_session("sig-1", [1], 1, [1, 2, 3], 3)
        client.post(
            "/v1/mpc/result",
            json={
                "session_id": session.session_id,
                "signal_id": "sig-1",
                "available": True,
                "participating_validators": 3,
            },
        )

        resp = client.get(f"/v1/mpc/{session.session_id}/status")
        data = resp.json()
        assert data["status"] == "complete"
        assert data["available"] is True
