"""Tests for the BPA/WPA gossip path.

P0-01 surfaced that the per-line BPA/WPA vectors are only written to
the purchase-handling validator's local ledger — no peer gets them —
so batch-audit settlement on any other validator silently produces
an empty batch. This module covers:

1. POST /v1/purchase_odds/record endpoint (inbound gossip receiver)
2. _gossip_purchase_odds_to_peers helper (outbound fan-out)
"""

from __future__ import annotations

import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient


BUYER = "0x1234567890123456789012345678901234567890"


@pytest.fixture
def app_with_ledger():
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

    application = create_app(
        share_store=share_store,
        purchase_orch=purchase_orch,
        outcome_attestor=outcome_attestor,
        purchase_odds_ledger=ledger,
    )
    return TestClient(application), ledger


@pytest.fixture
def app_without_ledger():
    os.environ["BT_NETWORK"] = "test"
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


# ----------------------------------------------------------------------
# POST /v1/purchase_odds/record — inbound gossip endpoint
# ----------------------------------------------------------------------


def test_record_endpoint_rejects_unauthenticated_in_production(app_with_ledger, monkeypatch):
    """Same auth guarantee as the GET endpoint: peer gossip has to be
    hotkey-signed by a registered validator."""
    client, _ = app_with_ledger
    monkeypatch.setenv("BT_NETWORK", "finney")
    resp = client.post(
        "/v1/purchase_odds/record",
        json={
            "signal_id": "sig1",
            "buyer_address": BUYER,
            "bpas": [1_950_000],
            "wpas": [1_910_000],
            "bpa_mode": True,
        },
    )
    assert resp.status_code == 401


def test_record_endpoint_test_mode_accepts_and_writes(app_with_ledger):
    """In test mode the endpoint writes to the ledger on first call."""
    client, ledger = app_with_ledger
    resp = client.post(
        "/v1/purchase_odds/record",
        json={
            "signal_id": "sig1",
            "buyer_address": BUYER,
            "bpas": [1_950_000, 1_850_000],
            "wpas": [1_910_000, 1_800_000],
            "bpa_mode": True,
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["recorded"] is True
    assert body["duplicate"] is False

    rec = ledger.get(signal_id="sig1", buyer_address=BUYER)
    assert rec is not None
    assert rec.bpas == [1_950_000, 1_850_000]
    assert rec.wpas == [1_910_000, 1_800_000]
    assert rec.bpa_mode is True


def test_record_endpoint_is_idempotent_on_duplicate(app_with_ledger):
    """Second call with the same (signal_id, buyer) returns duplicate=True
    and preserves the original vectors — first write wins."""
    client, ledger = app_with_ledger
    first_payload = {
        "signal_id": "sig1",
        "buyer_address": BUYER,
        "bpas": [1_000_000],
        "wpas": [1_000_000],
        "bpa_mode": True,
    }
    resp1 = client.post("/v1/purchase_odds/record", json=first_payload)
    assert resp1.status_code == 200
    assert resp1.json()["duplicate"] is False

    second_payload = dict(first_payload)
    second_payload["bpas"] = [9_999_999]
    second_payload["wpas"] = [9_999_999]
    resp2 = client.post("/v1/purchase_odds/record", json=second_payload)
    assert resp2.status_code == 200
    assert resp2.json()["recorded"] is True
    assert resp2.json()["duplicate"] is True

    rec = ledger.get(signal_id="sig1", buyer_address=BUYER)
    assert rec.bpas == [1_000_000]  # original preserved


def test_record_endpoint_rejects_mismatched_vector_lengths(app_with_ledger):
    """bpas and wpas must have equal length — this is enforced by the
    ledger.record() ValueError and surfaces as 400."""
    client, _ = app_with_ledger
    resp = client.post(
        "/v1/purchase_odds/record",
        json={
            "signal_id": "sig1",
            "buyer_address": BUYER,
            "bpas": [1_000_000, 2_000_000],
            "wpas": [1_000_000],
            "bpa_mode": False,
        },
    )
    assert resp.status_code == 400


def test_record_endpoint_rejects_invalid_buyer_address(app_with_ledger):
    """Pydantic validator enforces 0x + 40 hex chars."""
    client, _ = app_with_ledger
    resp = client.post(
        "/v1/purchase_odds/record",
        json={
            "signal_id": "sig1",
            "buyer_address": "not-a-valid-address",
            "bpas": [1_000_000],
            "wpas": [1_000_000],
            "bpa_mode": True,
        },
    )
    assert resp.status_code == 422


def test_record_endpoint_resets_abstain_on_arrival():
    """v1717: when BPA/WPA gossip lands for a signal whose audit_set was
    previously evicted from get_ready_sets via abstain threshold, the
    counter resets so the next get_ready_sets call surfaces the set
    again. Without this, an audit_set abstained during a brief gossip
    outage stays evicted forever."""
    os.environ["BT_NETWORK"] = "test"
    for key in list(os.environ.keys()):
        if key.startswith("DJINN_FF_"):
            del os.environ[key]

    from djinn_validator.api.server import create_app
    from djinn_validator.core.audit_set import AuditSetStore, SIGNALS_PER_CYCLE
    from djinn_validator.core.outcomes import Outcome, OutcomeAttestor
    from djinn_validator.core.purchase import PurchaseOrchestrator
    from djinn_validator.core.purchase_odds_ledger import PurchaseOddsLedger
    from djinn_validator.core.shares import ShareStore

    share_store = ShareStore()
    purchase_orch = PurchaseOrchestrator(share_store)
    outcome_attestor = OutcomeAttestor(espn_client=None)
    ledger = PurchaseOddsLedger()
    audit_set_store = AuditSetStore()

    genius = "0x" + "aa" * 20
    idiot = "0x" + "bb" * 20
    sample_outcomes = [Outcome.FAVORABLE for _ in range(100)]
    for i in range(SIGNALS_PER_CYCLE):
        sig_id = f"sig-reset-{i}"
        audit_set_store.add_signal(genius, idiot, 0, sig_id)
        audit_set_store.record_outcomes(sig_id, sample_outcomes)

    threshold = audit_set_store._abstain_threshold
    for _ in range(threshold):
        audit_set_store.mark_abstain(genius, idiot, 0)
    assert len(audit_set_store.get_ready_sets()) == 0, "evicted before gossip"

    application = create_app(
        share_store=share_store,
        purchase_orch=purchase_orch,
        outcome_attestor=outcome_attestor,
        purchase_odds_ledger=ledger,
        audit_set_store=audit_set_store,
    )
    client = TestClient(application)

    resp = client.post(
        "/v1/purchase_odds/record",
        json={
            "signal_id": "sig-reset-0",
            "buyer_address": idiot,
            "bpas": [1_950_000],
            "wpas": [1_910_000],
            "bpa_mode": True,
        },
    )
    assert resp.status_code == 200

    assert len(audit_set_store.get_ready_sets()) == 1, "reset after gossip"


def test_record_endpoint_returns_503_when_ledger_absent(app_without_ledger):
    """If the validator is running without a purchase_odds ledger
    configured (pre-ledger deploy), gossip is refused with 503 so the
    sender knows to retry later or fall back."""
    resp = app_without_ledger.post(
        "/v1/purchase_odds/record",
        json={
            "signal_id": "sig1",
            "buyer_address": BUYER,
            "bpas": [1_000_000],
            "wpas": [1_000_000],
            "bpa_mode": True,
        },
    )
    assert resp.status_code == 503


# ----------------------------------------------------------------------
# _gossip_purchase_odds_to_peers — outbound fan-out
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_gossip_helper_no_op_without_neuron():
    """Called with neuron=None (tests/unwired validators) must no-op, not raise."""
    from djinn_validator.api.server import _gossip_purchase_odds_to_peers

    await _gossip_purchase_odds_to_peers(
        neuron=None,
        signal_id="sig1",
        buyer_address=BUYER,
        bpas=[1_000_000],
        wpas=[1_000_000],
        bpa_mode=True,
    )  # does not raise


@pytest.mark.asyncio
async def test_gossip_helper_no_op_without_metagraph():
    """Neuron with metagraph=None (pre-sync) must no-op."""
    from djinn_validator.api.server import _gossip_purchase_odds_to_peers

    neuron = MagicMock()
    neuron.metagraph = None
    await _gossip_purchase_odds_to_peers(
        neuron=neuron,
        signal_id="sig1",
        buyer_address=BUYER,
        bpas=[1_000_000],
        wpas=[1_000_000],
        bpa_mode=True,
    )


@pytest.mark.asyncio
async def test_gossip_helper_skips_self_and_non_validators():
    """Peer discovery must skip (a) self, (b) UIDs without validator_permit,
    (c) UIDs with 0.0.0.0 axon."""
    from djinn_validator.api.server import _gossip_purchase_odds_to_peers

    neuron = MagicMock()
    neuron.uid = 0
    neuron.wallet = MagicMock()

    n = MagicMock()
    n.item = MagicMock(return_value=3)
    neuron.metagraph.n = n

    def _bool_item(val):
        m = MagicMock()
        m.item = MagicMock(return_value=val)
        return m

    # UID 0 (self, has permit), UID 1 (permit, has IP), UID 2 (permit, 0.0.0.0)
    neuron.metagraph.validator_permit = [_bool_item(True), _bool_item(True), _bool_item(True)]

    axon_self = MagicMock(ip="10.0.0.1", port=8421)
    axon_peer = MagicMock(ip="1.2.3.4", port=8421)
    axon_unset = MagicMock(ip="0.0.0.0", port=8421)
    neuron.metagraph.axons = [axon_self, axon_peer, axon_unset]
    neuron.metagraph.hotkeys = ["hk0", "hk1", "hk2"]

    captured_urls: list[str] = []

    class FakeResponse:
        status_code = 200

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, **kwargs):
            captured_urls.append(url)
            return FakeResponse()

    with patch("httpx.AsyncClient", lambda **kw: FakeClient()), patch(
        "djinn_validator.api.middleware.create_signed_headers",
        return_value={"X-Hotkey": "x", "X-Signature": "y", "X-Timestamp": "0", "X-Nonce": "z"},
    ), patch(
        "djinn_validator.core.mpc_orchestrator._is_public_ip",
        side_effect=lambda ip: ip == "1.2.3.4",
    ):
        await _gossip_purchase_odds_to_peers(
            neuron=neuron,
            signal_id="sig1",
            buyer_address=BUYER,
            bpas=[1_000_000],
            wpas=[1_000_000],
            bpa_mode=True,
        )

    assert captured_urls == ["http://1.2.3.4:8421/v1/purchase_odds/record"]


@pytest.mark.asyncio
async def test_gossip_helper_tolerates_peer_errors():
    """A peer returning 500 or timing out must not propagate — gossip is
    best-effort and must never fail the purchase response."""
    from djinn_validator.api.server import _gossip_purchase_odds_to_peers
    import httpx

    neuron = MagicMock()
    neuron.uid = 0
    neuron.wallet = MagicMock()
    n = MagicMock()
    n.item = MagicMock(return_value=2)
    neuron.metagraph.n = n

    def _bool_item(val):
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
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, **kwargs):
            raise httpx.ConnectTimeout("simulated peer down")

    with patch("httpx.AsyncClient", lambda **kw: FakeClient()), patch(
        "djinn_validator.api.middleware.create_signed_headers",
        return_value={"X-Hotkey": "x", "X-Signature": "y", "X-Timestamp": "0", "X-Nonce": "z"},
    ), patch(
        "djinn_validator.core.mpc_orchestrator._is_public_ip",
        side_effect=lambda ip: ip == "1.2.3.4",
    ):
        # Must not raise
        await _gossip_purchase_odds_to_peers(
            neuron=neuron,
            signal_id="sig1",
            buyer_address=BUYER,
            bpas=[1_000_000],
            wpas=[1_000_000],
            bpa_mode=True,
        )


@pytest.mark.asyncio
async def test_v1704_gossip_unreachable_ticks_metric(monkeypatch):
    """v1704: peer connect-error during purchase_odds gossip ticks
    GOSSIP_PUSH_RESULT.labels(path='purchase_odds', outcome='peer_unreachable').

    v1721 update: gossip retries up to 3 times on transient failures, so
    a permanently-down peer ticks the metric N+1 times (1 initial + N
    retries). Test sets DJINN_GOSSIP_BACKOFFS_S="" to disable retry and
    keep the original 1-tick semantics.
    """
    monkeypatch.setenv("DJINN_GOSSIP_BACKOFFS_S", "")
    from djinn_validator.api.server import _gossip_purchase_odds_to_peers
    from djinn_validator.api.metrics import GOSSIP_PUSH_RESULT
    import httpx

    neuron = MagicMock()
    neuron.uid = 0
    neuron.wallet = MagicMock()
    n = MagicMock()
    n.item = MagicMock(return_value=2)
    neuron.metagraph.n = n

    def _bool_item(val):
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
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, **kwargs):
            raise httpx.ConnectTimeout("simulated peer down")

    before = GOSSIP_PUSH_RESULT.labels(path="purchase_odds", outcome="peer_unreachable")._value.get()
    with patch("httpx.AsyncClient", lambda **kw: FakeClient()), patch(
        "djinn_validator.api.middleware.create_signed_headers",
        return_value={"X-Hotkey": "x", "X-Signature": "y", "X-Timestamp": "0", "X-Nonce": "z"},
    ), patch(
        "djinn_validator.core.mpc_orchestrator._is_public_ip",
        side_effect=lambda ip: ip == "1.2.3.4",
    ):
        await _gossip_purchase_odds_to_peers(
            neuron=neuron,
            signal_id="sig1",
            buyer_address=BUYER,
            bpas=[1_000_000],
            wpas=[1_000_000],
            bpa_mode=True,
        )
    after = GOSSIP_PUSH_RESULT.labels(path="purchase_odds", outcome="peer_unreachable")._value.get()
    assert after == before + 1


def test_v1707_receive_stored_ticks_metric(app_with_ledger):
    """v1707: 200 + first-time record on /v1/purchase_odds/record ticks
    GOSSIP_RECEIVE_RESULT.labels(path='purchase_odds', outcome='stored')."""
    from djinn_validator.api.metrics import GOSSIP_RECEIVE_RESULT

    client, _ledger = app_with_ledger
    payload = {
        "signal_id": "metric-stored-1",
        "buyer_address": BUYER,
        "bpa_mode": True,
        "bpas": [1_950_000],
        "wpas": [1_910_000],
    }
    before = GOSSIP_RECEIVE_RESULT.labels(path="purchase_odds", outcome="stored")._value.get()
    resp = client.post("/v1/purchase_odds/record", json=payload)
    assert resp.status_code == 200, resp.text
    after = GOSSIP_RECEIVE_RESULT.labels(path="purchase_odds", outcome="stored")._value.get()
    assert after == before + 1


def test_v1707_receive_duplicate_ticks_metric(app_with_ledger):
    """v1707: 200 + duplicate (already in ledger) ticks
    GOSSIP_RECEIVE_RESULT.labels(path='purchase_odds', outcome='duplicate')."""
    from djinn_validator.api.metrics import GOSSIP_RECEIVE_RESULT

    client, _ledger = app_with_ledger
    payload = {
        "signal_id": "metric-dup-1",
        "buyer_address": BUYER,
        "bpa_mode": True,
        "bpas": [1_950_000],
        "wpas": [1_910_000],
    }
    # First record (counts as `stored`).
    client.post("/v1/purchase_odds/record", json=payload)
    # Duplicate.
    before = GOSSIP_RECEIVE_RESULT.labels(path="purchase_odds", outcome="duplicate")._value.get()
    resp = client.post("/v1/purchase_odds/record", json=payload)
    assert resp.status_code == 200
    after = GOSSIP_RECEIVE_RESULT.labels(path="purchase_odds", outcome="duplicate")._value.get()
    assert after == before + 1


@pytest.mark.asyncio
async def test_v1704_gossip_success_ticks_sent():
    """v1704: 200 response from peer ticks
    GOSSIP_PUSH_RESULT.labels(path='purchase_odds', outcome='sent')."""
    from djinn_validator.api.server import _gossip_purchase_odds_to_peers
    from djinn_validator.api.metrics import GOSSIP_PUSH_RESULT

    neuron = MagicMock()
    neuron.uid = 0
    neuron.wallet = MagicMock()
    n = MagicMock()
    n.item = MagicMock(return_value=2)
    neuron.metagraph.n = n

    def _bool_item(val):
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

        def json(self):
            return {"ok": True}

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, **kwargs):
            return FakeResp()

    before = GOSSIP_PUSH_RESULT.labels(path="purchase_odds", outcome="sent")._value.get()
    with patch("httpx.AsyncClient", lambda **kw: FakeClient()), patch(
        "djinn_validator.api.middleware.create_signed_headers",
        return_value={"X-Hotkey": "x", "X-Signature": "y", "X-Timestamp": "0", "X-Nonce": "z"},
    ), patch(
        "djinn_validator.core.mpc_orchestrator._is_public_ip",
        side_effect=lambda ip: ip == "1.2.3.4",
    ):
        await _gossip_purchase_odds_to_peers(
            neuron=neuron,
            signal_id="sig1",
            buyer_address=BUYER,
            bpas=[1_000_000],
            wpas=[1_000_000],
            bpa_mode=True,
        )
    after = GOSSIP_PUSH_RESULT.labels(path="purchase_odds", outcome="sent")._value.get()
    assert after == before + 1


@pytest.mark.asyncio
async def test_v1744_gossip_outbox_enqueues_unreachable_peer(monkeypatch, tmp_path):
    """v1744: a peer that fails the entire in-memory retry budget
    (DJINN_GOSSIP_BACKOFFS_S="" → 1 attempt) lands in the durable
    gossip_outbox queue. Closes the >6min-peer-offline gap that v1721
    can't reach.
    """
    monkeypatch.setenv("DJINN_GOSSIP_BACKOFFS_S", "")
    from djinn_validator.api.server import _gossip_purchase_odds_to_peers
    from djinn_validator.core import gossip_outbox
    import httpx

    # Fresh outbox keyed to this test's tmp_path.
    gossip_outbox.reset_for_tests()
    gossip_outbox._state.db = None
    gossip_outbox.configure(str(tmp_path / "outbox.db"))

    neuron = MagicMock()
    neuron.uid = 0
    neuron.wallet = MagicMock()
    n = MagicMock()
    n.item = MagicMock(return_value=2)
    neuron.metagraph.n = n

    def _bool_item(val):
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
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, **kwargs):
            raise httpx.ConnectTimeout("simulated peer down")

    assert gossip_outbox.pending_count() == 0
    with patch("httpx.AsyncClient", lambda **kw: FakeClient()), patch(
        "djinn_validator.api.middleware.create_signed_headers",
        return_value={"X-Hotkey": "x", "X-Signature": "y", "X-Timestamp": "0", "X-Nonce": "z"},
    ), patch(
        "djinn_validator.core.mpc_orchestrator._is_public_ip",
        side_effect=lambda ip: ip == "1.2.3.4",
    ):
        await _gossip_purchase_odds_to_peers(
            neuron=neuron,
            signal_id="sig1",
            buyer_address=BUYER,
            bpas=[1_000_000],
            wpas=[1_000_000],
            bpa_mode=True,
        )

    # The 1.2.3.4 peer was unreachable across the entire retry budget;
    # it should now be in the durable queue.
    assert gossip_outbox.pending_count() == 1
    stats = gossip_outbox.stats()
    assert stats == {"pending": 1, "acked": 0, "failed_terminal": 0}

    gossip_outbox.reset_for_tests()
    gossip_outbox._state.db = None


@pytest.mark.asyncio
async def test_v1744_gossip_outbox_skips_acked_peers(monkeypatch, tmp_path):
    """A peer that 200s should NOT land in the outbox — only stragglers."""
    monkeypatch.setenv("DJINN_GOSSIP_BACKOFFS_S", "")
    from djinn_validator.api.server import _gossip_purchase_odds_to_peers
    from djinn_validator.core import gossip_outbox

    gossip_outbox.reset_for_tests()
    gossip_outbox._state.db = None
    gossip_outbox.configure(str(tmp_path / "outbox.db"))

    neuron = MagicMock()
    neuron.uid = 0
    neuron.wallet = MagicMock()
    n = MagicMock()
    n.item = MagicMock(return_value=2)
    neuron.metagraph.n = n

    def _bool_item(val):
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

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, **kwargs):
            return FakeResp()

    with patch("httpx.AsyncClient", lambda **kw: FakeClient()), patch(
        "djinn_validator.api.middleware.create_signed_headers",
        return_value={"X-Hotkey": "x", "X-Signature": "y", "X-Timestamp": "0", "X-Nonce": "z"},
    ), patch(
        "djinn_validator.core.mpc_orchestrator._is_public_ip",
        side_effect=lambda ip: ip == "1.2.3.4",
    ):
        await _gossip_purchase_odds_to_peers(
            neuron=neuron,
            signal_id="sig1",
            buyer_address=BUYER,
            bpas=[1_000_000],
            wpas=[1_000_000],
            bpa_mode=True,
        )

    assert gossip_outbox.pending_count() == 0

    gossip_outbox.reset_for_tests()
    gossip_outbox._state.db = None
