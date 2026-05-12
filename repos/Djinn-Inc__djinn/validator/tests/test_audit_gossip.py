"""Tests for the v1710 audit-set push gossip path.

POST /v1/audit/gossip + _gossip_audit_set_to_peers helper. Receivers
must verify on-chain (Escrow.purchases(pid)) before adding to audit_
set_store; senders fan-out to every committee peer per new pair-add
discovered by audit_bootstrap.
"""

from __future__ import annotations

import os
from unittest.mock import AsyncMock, MagicMock, patch
from typing import Any

import pytest
from fastapi.testclient import TestClient


GENIUS = "0x" + "aa" * 20
IDIOT = "0x" + "bb" * 20
SIGNAL_ID = "sig-audit-gossip-1"
PURCHASE_ID = 12345


@pytest.fixture
def app_with_chain():
    """App fixture with a chain_client mock + audit_set_store wired."""
    os.environ["BT_NETWORK"] = "test"
    for key in list(os.environ.keys()):
        if key.startswith("DJINN_FF_"):
            del os.environ[key]

    from djinn_validator.api.server import create_app
    from djinn_validator.core.shares import ShareStore
    from djinn_validator.core.purchase import PurchaseOrchestrator
    from djinn_validator.core.outcomes import OutcomeAttestor
    from djinn_validator.core.audit_set import AuditSetStore

    share_store = ShareStore()
    purchase_orch = PurchaseOrchestrator(share_store)
    outcome_attestor = OutcomeAttestor(espn_client=None)
    audit_set_store = AuditSetStore()

    chain_client = AsyncMock()
    chain_client.is_connected = AsyncMock(return_value=True)
    chain_client.is_paused = AsyncMock(return_value=False)
    chain_client.get_purchase = AsyncMock(
        return_value={
            "signalId": SIGNAL_ID,
            "idiot": IDIOT,
            "notional": 10_000_000,
        }
    )

    application = create_app(
        share_store=share_store,
        purchase_orch=purchase_orch,
        outcome_attestor=outcome_attestor,
        chain_client=chain_client,
        audit_set_store=audit_set_store,
    )
    return TestClient(application), audit_set_store, chain_client


def test_audit_gossip_added_first_time(app_with_chain):
    """First-time gossip for a (G, I, sig, pid) tuple verifies on chain
    and adds to audit_set_store with reason='added'."""
    client, audit_set_store, chain_client = app_with_chain
    payload = {
        "genius": GENIUS,
        "idiot": IDIOT,
        "signal_id": SIGNAL_ID,
        "purchase_id": PURCHASE_ID,
        "source_uid": 7,
    }
    resp = client.post("/v1/audit/gossip", json=payload)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["accepted"] is True
    assert body["duplicate"] is False
    assert body["reason"] == "added"
    chain_client.get_purchase.assert_awaited_once_with(PURCHASE_ID)
    assert audit_set_store.get_pair_for_signal(SIGNAL_ID) is not None


def test_audit_gossip_duplicate_skips_chain_call(app_with_chain):
    """Repeat gossip for an already-stored tuple short-circuits the
    chain RPC and returns duplicate=True."""
    client, audit_set_store, chain_client = app_with_chain
    payload = {
        "genius": GENIUS,
        "idiot": IDIOT,
        "signal_id": SIGNAL_ID,
        "purchase_id": PURCHASE_ID,
        "source_uid": 7,
    }
    # First add
    client.post("/v1/audit/gossip", json=payload)
    chain_client.get_purchase.reset_mock()
    # Duplicate
    resp = client.post("/v1/audit/gossip", json=payload)
    assert resp.status_code == 200
    body = resp.json()
    assert body["accepted"] is True
    assert body["duplicate"] is True
    assert body["reason"] == "duplicate"
    # Chain RPC NOT called on the duplicate path.
    chain_client.get_purchase.assert_not_awaited()


def test_audit_gossip_chain_mismatch_rejected(app_with_chain):
    """If chain reports a different signal_id for the claimed
    purchase_id, gossip is rejected for forensics."""
    client, audit_set_store, chain_client = app_with_chain
    chain_client.get_purchase = AsyncMock(
        return_value={
            "signalId": "different-signal-id",
            "idiot": IDIOT,
            "notional": 10_000_000,
        }
    )
    payload = {
        "genius": GENIUS,
        "idiot": IDIOT,
        "signal_id": SIGNAL_ID,
        "purchase_id": PURCHASE_ID,
        "source_uid": 7,
    }
    resp = client.post("/v1/audit/gossip", json=payload)
    assert resp.status_code == 200
    body = resp.json()
    assert body["accepted"] is False
    assert body["reason"] == "chain_mismatch"
    # Tuple NOT added.
    assert audit_set_store.get_pair_for_signal(SIGNAL_ID) is None


def test_audit_gossip_chain_unreachable_rejected(app_with_chain):
    """Chain RPC raising = chain_unreachable response, no add."""
    client, audit_set_store, chain_client = app_with_chain
    chain_client.get_purchase = AsyncMock(side_effect=RuntimeError("rpc down"))
    payload = {
        "genius": GENIUS,
        "idiot": IDIOT,
        "signal_id": SIGNAL_ID,
        "purchase_id": PURCHASE_ID,
        "source_uid": 7,
    }
    resp = client.post("/v1/audit/gossip", json=payload)
    assert resp.status_code == 200
    body = resp.json()
    assert body["accepted"] is False
    assert body["reason"] == "chain_unreachable"
    assert audit_set_store.get_pair_for_signal(SIGNAL_ID) is None


def test_audit_gossip_purchase_not_on_chain(app_with_chain):
    """Chain returns None (purchase doesn't exist) → reject."""
    client, audit_set_store, chain_client = app_with_chain
    chain_client.get_purchase = AsyncMock(return_value=None)
    payload = {
        "genius": GENIUS,
        "idiot": IDIOT,
        "signal_id": SIGNAL_ID,
        "purchase_id": PURCHASE_ID,
        "source_uid": 7,
    }
    resp = client.post("/v1/audit/gossip", json=payload)
    assert resp.status_code == 200
    body = resp.json()
    assert body["accepted"] is False
    assert body["reason"] == "purchase_not_on_chain"


def test_audit_gossip_rejects_invalid_address():
    """Pydantic regex rejects malformed genius / idiot."""
    from djinn_validator.api.models import AuditGossipRequest
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        AuditGossipRequest(
            genius="0xGenius",  # too short
            idiot=IDIOT,
            signal_id=SIGNAL_ID,
            purchase_id=PURCHASE_ID,
            source_uid=7,
        )

    with pytest.raises(ValidationError):
        AuditGossipRequest(
            genius=GENIUS,
            idiot="0xnotvalid",
            signal_id=SIGNAL_ID,
            purchase_id=PURCHASE_ID,
            source_uid=7,
        )


@pytest.mark.asyncio
async def test_gossip_helper_no_op_without_neuron():
    """Helper returns silently when neuron is None (e.g. validator
    running in single-validator dev mode)."""
    from djinn_validator.api.server import _gossip_audit_set_to_peers

    await _gossip_audit_set_to_peers(
        neuron=None,
        genius=GENIUS,
        idiot=IDIOT,
        signal_id=SIGNAL_ID,
        purchase_id=PURCHASE_ID,
    )


@pytest.mark.asyncio
async def test_gossip_helper_ticks_sent_on_200():
    """200 response from peer ticks AUDIT_GOSSIP_PUSH_RESULT.sent."""
    from djinn_validator.api.server import _gossip_audit_set_to_peers
    from djinn_validator.api.metrics import AUDIT_GOSSIP_PUSH_RESULT

    neuron = MagicMock()
    neuron.uid = 0
    neuron.wallet = MagicMock()
    n = MagicMock()
    n.item = MagicMock(return_value=2)
    neuron.metagraph.n = n

    def _bool_item(val: bool) -> Any:
        m = MagicMock()
        m.item = MagicMock(return_value=val)
        return m

    neuron.metagraph.validator_permit = [_bool_item(True), _bool_item(True)]
    neuron.metagraph.axons = [
        MagicMock(ip="10.0.0.1", port=8421),
        MagicMock(ip="1.2.3.4", port=8421),
    ]
    neuron.metagraph.hotkeys = ["hk0", "hk1"]

    class FakeResp:
        status_code = 200

        def json(self) -> Any:
            return {"accepted": True, "duplicate": False, "reason": "added"}

    class FakeClient:
        async def __aenter__(self) -> "FakeClient":
            return self

        async def __aexit__(self, *a: Any) -> bool:
            return False

        async def post(self, url: str, **kw: Any) -> FakeResp:
            return FakeResp()

    before = AUDIT_GOSSIP_PUSH_RESULT.labels(outcome="sent")._value.get()
    with patch("httpx.AsyncClient", lambda **kw: FakeClient()), patch(
        "djinn_validator.api.middleware.create_signed_headers",
        return_value={"X-Hotkey": "x", "X-Signature": "y", "X-Timestamp": "0", "X-Nonce": "z"},
    ), patch(
        "djinn_validator.core.mpc_orchestrator._is_public_ip",
        side_effect=lambda ip: ip == "1.2.3.4",
    ):
        await _gossip_audit_set_to_peers(
            neuron=neuron,
            genius=GENIUS,
            idiot=IDIOT,
            signal_id=SIGNAL_ID,
            purchase_id=PURCHASE_ID,
        )
    after = AUDIT_GOSSIP_PUSH_RESULT.labels(outcome="sent")._value.get()
    assert after == before + 1


@pytest.mark.asyncio
async def test_gossip_helper_ticks_unreachable_on_httpx_error():
    """httpx error ticks AUDIT_GOSSIP_PUSH_RESULT.peer_unreachable."""
    import httpx

    from djinn_validator.api.server import _gossip_audit_set_to_peers
    from djinn_validator.api.metrics import AUDIT_GOSSIP_PUSH_RESULT

    neuron = MagicMock()
    neuron.uid = 0
    neuron.wallet = MagicMock()
    n = MagicMock()
    n.item = MagicMock(return_value=2)
    neuron.metagraph.n = n

    def _bool_item(val: bool) -> Any:
        m = MagicMock()
        m.item = MagicMock(return_value=val)
        return m

    neuron.metagraph.validator_permit = [_bool_item(True), _bool_item(True)]
    neuron.metagraph.axons = [
        MagicMock(ip="10.0.0.1", port=8421),
        MagicMock(ip="1.2.3.4", port=8421),
    ]
    neuron.metagraph.hotkeys = ["hk0", "hk1"]

    class FakeClient:
        async def __aenter__(self) -> "FakeClient":
            return self

        async def __aexit__(self, *a: Any) -> bool:
            return False

        async def post(self, url: str, **kw: Any) -> Any:
            raise httpx.ConnectTimeout("simulated peer down")

    before = AUDIT_GOSSIP_PUSH_RESULT.labels(outcome="peer_unreachable")._value.get()
    with patch("httpx.AsyncClient", lambda **kw: FakeClient()), patch(
        "djinn_validator.api.middleware.create_signed_headers",
        return_value={"X-Hotkey": "x", "X-Signature": "y", "X-Timestamp": "0", "X-Nonce": "z"},
    ), patch(
        "djinn_validator.core.mpc_orchestrator._is_public_ip",
        side_effect=lambda ip: ip == "1.2.3.4",
    ):
        await _gossip_audit_set_to_peers(
            neuron=neuron,
            genius=GENIUS,
            idiot=IDIOT,
            signal_id=SIGNAL_ID,
            purchase_id=PURCHASE_ID,
        )
    after = AUDIT_GOSSIP_PUSH_RESULT.labels(outcome="peer_unreachable")._value.get()
    assert after == before + 1
