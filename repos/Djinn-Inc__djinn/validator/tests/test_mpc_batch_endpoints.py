"""Wire-contract tests for the batch settlement HTTP endpoints.

These tests pin the /v1/mpc/batch/* wire shapes before the real
handlers ship. They verify:

  - Auth is enforced in production (BT_NETWORK=finney returns 401 on
    unsigned requests).
  - The feature flag gate works: flag off returns 503 even for
    authenticated callers.
  - Pydantic request validation rejects malformed bodies with 422.
  - Response schemas are importable and self-consistent.

The actual protocol correctness is pinned by
test_mpc_batch_settlement.py against simulate_distributed_batch_settle.
When the handlers land, additional tests will assert that the HTTP
runtime produces the same totals as the simulator for the same inputs.
"""

from __future__ import annotations

import importlib
import os

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def batch_app(monkeypatch):
    """Build a FastAPI test client with the batch endpoints mounted.

    Same BT_NETWORK=test escape hatch pattern as the cb endpoint
    tests so we can exercise business logic without signing real
    hotkey requests. The flag-off path is verified separately with
    the prod fixture below.
    """
    for key in list(os.environ.keys()):
        if key.startswith("DJINN_FF_"):
            monkeypatch.delenv(key, raising=False)

    def _build(*, batch_on: bool = False):
        monkeypatch.setenv("BT_NETWORK", "test")
        # 2026-05-03 fix: feature_flags.batch_settlement_http defaults to
        # `_on_sepolia` (True when BASE_CHAIN_ID=84532). Just delenv'ing the
        # DJINN_FF_BATCH_SETTLEMENT_HTTP var leaves the default ON and the
        # `flag_off` test branch returns 400 (empty-batch) or 404 (signal
        # lookup miss) instead of the expected 503. To exercise the flag-off
        # path we have to explicitly set it false.
        if batch_on:
            monkeypatch.setenv("DJINN_FF_BATCH_SETTLEMENT_HTTP", "true")
        else:
            monkeypatch.setenv("DJINN_FF_BATCH_SETTLEMENT_HTTP", "false")
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

    for key in list(os.environ.keys()):
        if key.startswith("DJINN_FF_"):
            monkeypatch.delenv(key, raising=False)
    from djinn_validator import feature_flags as _ff

    importlib.reload(_ff)


@pytest.fixture
def prod_batch_app(monkeypatch):
    """Production-mode app for auth-gate tests. Uses monkeypatch so
    BT_NETWORK and DJINN_FF_* values are auto-reverted after the test
    and can't leak into other test files that rely on defaults.
    """
    for key in list(os.environ.keys()):
        if key.startswith("DJINN_FF_"):
            monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("BT_NETWORK", "finney")

    import importlib as _imp
    from djinn_validator import feature_flags

    _imp.reload(feature_flags)

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
    yield TestClient(app)

    # Reload feature_flags singleton so subsequent tests see default FF state.
    _imp.reload(feature_flags)


# ----------------------------------------------------------------------
# Auth enforcement (production) — every endpoint must be 401 unauthenticated
# ----------------------------------------------------------------------


def _good_init_payload() -> dict:
    return {
        "session_id": "batch-test-0001",
        "coordinator_x": 1,
        "participant_xs": [1, 2, 3],
        "threshold": 3,
        "purchases": [
            {
                "purchase_id": 1,
                "signal_id": "sig-aaa",
                "gain_vector": [hex(1_950_000), hex(1_850_000)],
                "triple_shares": [],
            },
        ],
    }


def test_batch_init_unauthenticated_rejected(prod_batch_app):
    resp = prod_batch_app.post("/v1/mpc/batch/init", json=_good_init_payload())
    assert resp.status_code == 401


def test_batch_compute_gate_unauthenticated_rejected(prod_batch_app):
    resp = prod_batch_app.post(
        "/v1/mpc/batch/compute_gate",
        json={
            "session_id": "batch-test-0001",
            "purchase_idx": 0,
            "gate_idx": 0,
            "prev_opened_d": None,
            "prev_opened_e": None,
        },
    )
    assert resp.status_code == 401


def test_batch_accumulate_unauthenticated_rejected(prod_batch_app):
    resp = prod_batch_app.post(
        "/v1/mpc/batch/accumulate",
        json={
            "session_id": "batch-test-0001",
            "purchase_idx": 0,
            "last_opened_d": hex(7),
            "last_opened_e": hex(11),
        },
    )
    assert resp.status_code == 401


def test_batch_open_unauthenticated_rejected(prod_batch_app):
    resp = prod_batch_app.post(
        "/v1/mpc/batch/open",
        json={"session_id": "batch-test-0001"},
    )
    assert resp.status_code == 401


# ----------------------------------------------------------------------
# Feature flag gate — flag OFF returns 503 (not 501), even in test mode
# ----------------------------------------------------------------------


def test_batch_init_flag_off_returns_503(batch_app):
    client = batch_app(batch_on=False)
    resp = client.post("/v1/mpc/batch/init", json=_good_init_payload())
    assert resp.status_code == 503


def test_batch_compute_gate_flag_off_returns_503(batch_app):
    client = batch_app(batch_on=False)
    resp = client.post(
        "/v1/mpc/batch/compute_gate",
        json={
            "session_id": "batch-test-0001",
            "purchase_idx": 0,
            "gate_idx": 0,
        },
    )
    assert resp.status_code == 503


def test_batch_accumulate_flag_off_returns_503(batch_app):
    client = batch_app(batch_on=False)
    resp = client.post(
        "/v1/mpc/batch/accumulate",
        json={
            "session_id": "batch-test-0001",
            "purchase_idx": 0,
            "last_opened_d": hex(7),
            "last_opened_e": hex(11),
        },
    )
    assert resp.status_code == 503


def test_batch_open_flag_off_returns_503(batch_app):
    client = batch_app(batch_on=False)
    resp = client.post(
        "/v1/mpc/batch/open",
        json={"session_id": "batch-test-0001"},
    )
    assert resp.status_code == 503


# ----------------------------------------------------------------------
# Pydantic validation — malformed bodies must be 422
# ----------------------------------------------------------------------


def test_batch_init_rejects_empty_gain_vector(batch_app):
    client = batch_app(batch_on=True)  # flag on so validation runs before 501
    bad = _good_init_payload()
    bad["purchases"][0]["gain_vector"] = [hex(1_950_000)]  # only 1 entry
    resp = client.post("/v1/mpc/batch/init", json=bad)
    assert resp.status_code == 422


def test_batch_init_idempotent_on_duplicate_session_id(three_peer_batch_apps):
    """v1692: duplicate session_id with matching params returns 200 (idempotent)
    instead of 409. Pre-fix, _peer_request retries on transport blip caused
    the second init to land at the server, see existing session, and 409 —
    coordinator treated this as protocol_failed and aborted the whole shadow
    settle. UID 0 logs at 11:22:07 caught this exact pattern."""
    clients, stores = three_peer_batch_apps
    from djinn_validator.utils.crypto import BN254_PRIME as _P, split_secret
    from djinn_validator.core.shares import SignalShareRecord

    # Seed peer x=1 with a share for sig-aaa.
    sig_id = "test-idempotent-sig"
    shares = split_secret(2, n=3, k=3, prime=_P)
    rec = SignalShareRecord(
        signal_id=sig_id,
        genius_address="0x" + "0" * 40,
        share=shares[0],
        encrypted_key_share=b"\x00" * 32,
        encrypted_index_share=b"\x00" * 32,
        shamir_threshold=3,
        precomputed_triples=[],
    )
    stores[1].store(
        signal_id=sig_id,
        genius_address="0x" + "0" * 40,
        share=shares[0],
        encrypted_key_share=b"\x00" * 32,
        encrypted_index_share=b"\x00" * 32,
        shamir_threshold=3,
        precomputed_triples=[],
    )

    payload = {
        "session_id": "batch-idempotent-test",
        "coordinator_x": 1,
        "participant_xs": [1, 2, 3],
        "threshold": 3,
        "purchases": [
            {
                "purchase_id": 1,
                "signal_id": sig_id,
                "gain_vector": [hex(1_950_000), hex(1_850_000)],
                "triple_shares": [],
            },
        ],
    }
    # First init creates the session on peer 1.
    resp1 = clients[1].post("/v1/mpc/batch/init", json=payload)
    assert resp1.status_code == 200, resp1.text
    # Second init with IDENTICAL params is treated as idempotent (200, not 409).
    resp2 = clients[1].post("/v1/mpc/batch/init", json=payload)
    assert resp2.status_code == 200, resp2.text
    body2 = resp2.json()
    assert body2["accepted"] is True
    assert body2["session_id"] == payload["session_id"]


def test_batch_init_409_on_duplicate_session_id_different_params(three_peer_batch_apps):
    """v1692: duplicate session_id with DIFFERENT params still 409s. Idempotency
    only kicks in when the re-init is a true retry of the same request."""
    clients, stores = three_peer_batch_apps
    from djinn_validator.utils.crypto import BN254_PRIME as _P, split_secret

    sig_id = "test-409-sig"
    shares = split_secret(2, n=3, k=3, prime=_P)
    stores[1].store(
        signal_id=sig_id,
        genius_address="0x" + "0" * 40,
        share=shares[0],
        encrypted_key_share=b"\x00" * 32,
        encrypted_index_share=b"\x00" * 32,
        shamir_threshold=3,
        precomputed_triples=[],
    )

    payload = {
        "session_id": "batch-409-test",
        "coordinator_x": 1,
        "participant_xs": [1, 2, 3],
        "threshold": 3,
        "purchases": [
            {
                "purchase_id": 1,
                "signal_id": sig_id,
                "gain_vector": [hex(1_950_000), hex(1_850_000)],
                "triple_shares": [],
            },
        ],
    }
    resp1 = clients[1].post("/v1/mpc/batch/init", json=payload)
    assert resp1.status_code == 200, resp1.text
    # Same session_id, different participant set.
    payload["participant_xs"] = [1, 2, 4]
    resp2 = clients[1].post("/v1/mpc/batch/init", json=payload)
    assert resp2.status_code == 409
    assert "different parameters" in resp2.json()["detail"]


def test_batch_init_rejects_duplicate_participant_xs(batch_app):
    client = batch_app(batch_on=True)
    bad = _good_init_payload()
    bad["participant_xs"] = [1, 2, 2]
    resp = client.post("/v1/mpc/batch/init", json=bad)
    assert resp.status_code == 422


def test_batch_init_rejects_invalid_signal_id(batch_app):
    client = batch_app(batch_on=True)
    bad = _good_init_payload()
    bad["purchases"][0]["signal_id"] = "sig with spaces"
    resp = client.post("/v1/mpc/batch/init", json=bad)
    assert resp.status_code == 422


def test_batch_init_rejects_non_hex_gain_value(batch_app):
    client = batch_app(batch_on=True)
    bad = _good_init_payload()
    bad["purchases"][0]["gain_vector"] = ["0x1950000", "not_hex", hex(2_000_000)]
    resp = client.post("/v1/mpc/batch/init", json=bad)
    assert resp.status_code == 422


def test_batch_compute_gate_rejects_out_of_range_idx(batch_app):
    client = batch_app(batch_on=True)
    resp = client.post(
        "/v1/mpc/batch/compute_gate",
        json={
            "session_id": "batch-test-0001",
            "purchase_idx": 999_999,  # over the 199 cap
            "gate_idx": 0,
        },
    )
    assert resp.status_code == 422


# ----------------------------------------------------------------------
# Flag-on + valid body = 501 (handler not yet implemented)
# ----------------------------------------------------------------------


def test_batch_init_flag_on_unknown_signal_returns_404(batch_app):
    """Flag on + valid body, but the peer has no local Shamir share
    for the batch's signals — reject with 404 so the coordinator
    can skip this peer or retry later."""
    client = batch_app(batch_on=True)
    resp = client.post("/v1/mpc/batch/init", json=_good_init_payload())
    # Peer has an empty share_store so any signal_id is unknown.
    assert resp.status_code == 404


# ----------------------------------------------------------------------
# End-to-end HTTP driver: three peers in-process, each a separate
# TestClient, each holding a distinct Shamir share. The test acts as
# the coordinator: POSTing init/compute_gate/accumulate/open to each
# peer and reconstructing the batch total from the three sum_share
# responses. Result must match the in-process simulator.
# ----------------------------------------------------------------------


@pytest.fixture
def three_peer_batch_apps(monkeypatch):
    """Three independent validator apps, one per Shamir x-coordinate.

    Each has DJINN_FF_BATCH_SETTLEMENT_HTTP=true + BT_NETWORK=test so
    auth is a no-op. Returns a dict {x: TestClient} that the test
    driver can POST to as if it were the batch coordinator.
    """
    for key in list(os.environ.keys()):
        if key.startswith("DJINN_FF_"):
            monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("BT_NETWORK", "test")
    monkeypatch.setenv("DJINN_FF_BATCH_SETTLEMENT_HTTP", "true")

    from djinn_validator import feature_flags

    importlib.reload(feature_flags)

    from djinn_validator.api.server import create_app
    from djinn_validator.core.shares import ShareStore
    from djinn_validator.core.purchase import PurchaseOrchestrator
    from djinn_validator.core.outcomes import OutcomeAttestor

    clients: dict[int, TestClient] = {}
    stores: dict[int, ShareStore] = {}
    for vx in (1, 2, 3):
        ss = ShareStore()
        stores[vx] = ss
        po = PurchaseOrchestrator(ss)
        oa = OutcomeAttestor(espn_client=None)
        app = create_app(
            share_store=ss,
            purchase_orch=po,
            outcome_attestor=oa,
        )
        clients[vx] = TestClient(app)

    yield clients, stores

    for ss in stores.values():
        try:
            ss.close()
        except Exception:
            pass
    importlib.reload(feature_flags)


def test_end_to_end_batch_settlement_http_happy_path(three_peer_batch_apps):
    """Full HTTP round-trip for a 2-purchase batch across 3 peers.

    Steps performed by the test (acting as the coordinator):
      1. Generate Shamir shares of two secret realIndex values, one
         per purchase; populate each peer's ShareStore with the
         corresponding (signal_id, share_x, share_y) record.
      2. Build public gain vectors + Beaver triples per purchase.
      3. POST /v1/mpc/batch/init to each peer.
      4. For each purchase, drive the power-chain gates across
         all three peers via /v1/mpc/batch/compute_gate.
      5. POST /v1/mpc/batch/accumulate to each peer after the
         purchase's last gate.
      6. POST /v1/mpc/batch/open to each peer; collect sum shares.
      7. Reconstruct the batch total and compare against the
         in-process simulator output.
    """
    clients, stores = three_peer_batch_apps

    from djinn_validator.core.mpc import (
        generate_beaver_triples,
        reconstruct_at_zero,
    )
    from djinn_validator.core.mpc_batch_settlement import (
        PurchaseInputs as _PI,
        OUTCOME_FAVORABLE as _FAV,
        OUTCOME_UNFAVORABLE as _UNFAV,
        OUTCOME_VOID as _VOID,
        compute_gain_vector as _cgv,
        decode_field_to_signed as _decode,
        simulate_distributed_batch_settle as _sim,
    )
    from djinn_validator.core.shares import SignalShareRecord
    from djinn_validator.utils.crypto import (
        BN254_PRIME as _P,
        Share,
        split_secret,
    )

    # Two purchases, each for a different signal, each with its own
    # realIndex. Shares split 3-of-3 across x=1,2,3.
    real_indices = {"sig-100": 2, "sig-200": 3}
    purchase_inputs = [
        _PI(
            purchase_id=100,
            shares=split_secret(2, n=3, k=3, prime=_P),
            notional=100_000_000,
            sla_bps=500,
            bpa_mode=True,
            bpas=[2_000_000, 1_910_000, 1_850_000],  # scale: decimal * 1e6
            wpas=[1_900_000, 1_800_000, 1_750_000],
            outcomes=[_FAV, _FAV, _FAV],
        ),
        _PI(
            purchase_id=200,
            shares=split_secret(3, n=3, k=3, prime=_P),
            notional=200_000_000,
            sla_bps=1000,
            bpa_mode=False,
            bpas=[2_000_000, 1_910_000, 1_850_000],
            wpas=[1_900_000, 1_800_000, 1_750_000],
            outcomes=[_UNFAV, _VOID, _FAV],
        ),
    ]

    # Seed each peer's ShareStore with its slice of the Shamir shares.
    for purchase in purchase_inputs:
        sig_id = f"sig-{purchase.purchase_id}"
        for s in purchase.shares:
            stores[s.x].store(
                signal_id=sig_id,
                genius_address="0x" + "ab" * 20,
                share=Share(x=s.x, y=0),  # key share y is irrelevant for batch MPC
                encrypted_key_share=b"placeholder",
                encrypted_index_share=int(s.y).to_bytes(32, "big"),
                shamir_threshold=3,
            )

    # Build gain vectors + Beaver triples per purchase.
    participant_xs = [1, 2, 3]
    per_purchase_gain_vec: list[list[int]] = []
    per_purchase_triples: list[list] = []
    for purchase in purchase_inputs:
        gv = _cgv(purchase, prime=_P)
        per_purchase_gain_vec.append(gv)
        n_gates = max(0, len(gv) - 2)
        if n_gates > 0:
            triples = generate_beaver_triples(
                n_gates,
                n=3,
                k=3,
                prime=_P,
                x_coords=participant_xs,
            )
        else:
            triples = []
        per_purchase_triples.append(triples)

    session_id = "batch-e2e-001"

    # POST init to each peer. Every peer gets its own slice of the
    # triple shares keyed by its x-coord.
    for vx in participant_xs:
        purchases_payload = []
        for p_idx, purchase in enumerate(purchase_inputs):
            gv = per_purchase_gain_vec[p_idx]
            triples = per_purchase_triples[p_idx]
            peer_triples = []
            x_idx = participant_xs.index(vx)
            for t in triples:
                peer_triples.append(
                    {
                        "a": hex(t.a_shares[x_idx].y),
                        "b": hex(t.b_shares[x_idx].y),
                        "c": hex(t.c_shares[x_idx].y),
                    }
                )
            purchases_payload.append(
                {
                    "purchase_id": purchase.purchase_id,
                    "signal_id": f"sig-{purchase.purchase_id}",
                    "gain_vector": [hex(g) for g in gv],
                    "triple_shares": peer_triples,
                }
            )

        resp = clients[vx].post(
            "/v1/mpc/batch/init",
            json={
                "session_id": session_id,
                "coordinator_x": 1,
                "participant_xs": participant_xs,
                "threshold": 3,
                "purchases": purchases_payload,
            },
        )
        assert resp.status_code == 200, f"peer {vx} init: {resp.text}"
        body = resp.json()
        assert body["accepted"] is True
        assert body["purchase_count"] == 2

    # Drive gate chains purchase-by-purchase. For each gate, collect
    # (d, e) shares from every peer, reconstruct, pass to next gate.
    for p_idx, purchase in enumerate(purchase_inputs):
        n_gates = max(0, len(per_purchase_gain_vec[p_idx]) - 2)
        prev_d: str | None = None
        prev_e: str | None = None
        for g_idx in range(n_gates):
            d_shares: dict[int, int] = {}
            e_shares: dict[int, int] = {}
            for vx in participant_xs:
                resp = clients[vx].post(
                    "/v1/mpc/batch/compute_gate",
                    json={
                        "session_id": session_id,
                        "purchase_idx": p_idx,
                        "gate_idx": g_idx,
                        "prev_opened_d": prev_d,
                        "prev_opened_e": prev_e,
                    },
                )
                assert resp.status_code == 200, f"peer {vx} compute_gate p={p_idx} g={g_idx}: {resp.text}"
                d_shares[vx] = int(resp.json()["d_value"], 16)
                e_shares[vx] = int(resp.json()["e_value"], 16)
            prev_d = hex(reconstruct_at_zero(d_shares, _P))
            prev_e = hex(reconstruct_at_zero(e_shares, _P))

        # Accumulate this purchase across all peers.
        for vx in participant_xs:
            resp = clients[vx].post(
                "/v1/mpc/batch/accumulate",
                json={
                    "session_id": session_id,
                    "purchase_idx": p_idx,
                    "last_opened_d": prev_d or hex(0),
                    "last_opened_e": prev_e or hex(0),
                },
            )
            assert resp.status_code == 200, f"peer {vx} accumulate p={p_idx}: {resp.text}"
            assert resp.json()["accumulated"] is True

    # Open every peer and collect sum shares.
    sum_share_by_x: dict[int, int] = {}
    public_c0_values: set[int] = set()
    for vx in participant_xs:
        resp = clients[vx].post(
            "/v1/mpc/batch/open",
            json={"session_id": session_id},
        )
        assert resp.status_code == 200, f"peer {vx} open: {resp.text}"
        body = resp.json()
        sum_share_by_x[vx] = int(body["sum_share"], 16)
        public_c0_values.add(int(body["public_c_0_sum"], 16))
        assert body["validator_x"] == vx
        assert body["purchases_accumulated"] == 2

    # Every peer must have computed the same public c_0 register —
    # they derive it from identical public inputs.
    assert len(public_c0_values) == 1
    public_c_0 = public_c0_values.pop()

    # Reconstruct the sum share and add the public register.
    q_minus_c0 = reconstruct_at_zero(sum_share_by_x, _P)
    total_field = (q_minus_c0 + public_c_0) % _P
    total_http = _decode(total_field, _P)

    expected = _sim(purchase_inputs, threshold=3)
    assert total_http == expected.total_score_change


def test_coordinator_driver_via_test_clients(three_peer_batch_apps):
    """Same end-to-end scenario, but the protocol is driven by
    drive_http_batch_settlement instead of hand-written test code.

    Injects a peer_rpc adapter that routes to the three TestClients
    so the coordinator code can run in-process without real HTTP.
    This is the exact same surface production will use when the
    MPCOrchestrator integration lands — the difference is just the
    transport layer underneath peer_rpc.
    """
    import asyncio as _asyncio

    clients, stores = three_peer_batch_apps

    from djinn_validator.core.mpc import generate_beaver_triples
    from djinn_validator.core.mpc_batch_settlement import (
        PurchaseInputs as _PI,
        OUTCOME_FAVORABLE as _FAV,
        OUTCOME_UNFAVORABLE as _UNFAV,
        OUTCOME_VOID as _VOID,
        drive_http_batch_settlement,
        simulate_distributed_batch_settle as _sim,
    )
    from djinn_validator.core.shares import Share
    from djinn_validator.utils.crypto import BN254_PRIME as _P, split_secret

    purchase_inputs = [
        _PI(
            purchase_id=500,
            shares=split_secret(1, n=3, k=3, prime=_P),
            notional=75_000_000,
            sla_bps=750,
            bpa_mode=True,
            bpas=[1_950_000, 2_100_000, 1_800_000],
            wpas=[1_850_000, 2_000_000, 1_700_000],
            outcomes=[_FAV, _FAV, _UNFAV],
        ),
        _PI(
            purchase_id=501,
            shares=split_secret(2, n=3, k=3, prime=_P),
            notional=150_000_000,
            sla_bps=1000,
            bpa_mode=False,
            bpas=[1_950_000, 2_100_000, 1_800_000],
            wpas=[1_850_000, 2_000_000, 1_700_000],
            outcomes=[_VOID, _VOID, _FAV],
        ),
    ]

    # Seed shares.
    for purchase in purchase_inputs:
        sig_id = f"sig-{purchase.purchase_id}"
        for s in purchase.shares:
            stores[s.x].store(
                signal_id=sig_id,
                genius_address="0x" + "cd" * 20,
                share=Share(x=s.x, y=0),  # key share y is irrelevant for batch MPC
                encrypted_key_share=b"placeholder",
                encrypted_index_share=int(s.y).to_bytes(32, "big"),
                shamir_threshold=3,
            )

    participant_xs = [1, 2, 3]

    # Pre-generate beaver triples per purchase; the driver only needs
    # to know how to split them across peers (it does that itself).
    triples_per_purchase = []
    for purchase in purchase_inputs:
        n_gates = len(purchase.bpas) - 2  # = 1 for a 3-line purchase
        if n_gates > 0:
            triples_per_purchase.append(
                generate_beaver_triples(
                    n_gates,
                    n=3,
                    k=3,
                    prime=_P,
                    x_coords=participant_xs,
                )
            )
        else:
            triples_per_purchase.append([])

    # Adapter: route (validator_x, endpoint, payload) to the right
    # TestClient and return the parsed JSON body.
    async def _peer_rpc(vx: int, endpoint: str, payload: dict) -> dict:
        resp = clients[vx].post(f"/v1/mpc/batch/{endpoint}", json=payload)
        if resp.status_code != 200:
            raise RuntimeError(f"peer {vx} {endpoint} failed: {resp.status_code} {resp.text}")
        return resp.json()

    result = _asyncio.run(
        drive_http_batch_settlement(
            session_id="batch-driver-001",
            participant_xs=participant_xs,
            threshold=3,
            batch=purchase_inputs,
            beaver_triples_per_purchase=triples_per_purchase,
            peer_rpc=_peer_rpc,
        )
    )

    expected = _sim(purchase_inputs, threshold=3)
    assert result.total_score_change == expected.total_score_change
    assert result.purchase_count == 2


def test_coordinator_driver_handles_two_line_purchases(three_peer_batch_apps):
    """Regression for codex-audit critical (2026-04-15): drive_http_batch_settlement
    used to send "0x0" as last_opened_d/e for 2-line purchases (n_gates=0),
    but BatchSession.accumulate() requires None for the trivial path. The
    chain hard-failed end-to-end on every 2-line purchase. Fixed by making
    the model fields Optional and the driver forward None unchanged.
    """
    import asyncio as _asyncio

    clients, stores = three_peer_batch_apps

    from djinn_validator.core.mpc_batch_settlement import (
        PurchaseInputs as _PI,
        OUTCOME_FAVORABLE as _FAV,
        OUTCOME_UNFAVORABLE as _UNFAV,
        drive_http_batch_settlement,
        simulate_distributed_batch_settle as _sim,
    )
    from djinn_validator.core.shares import Share
    from djinn_validator.utils.crypto import BN254_PRIME as _P, split_secret

    # Two purchases, BOTH 2-line (n_gates = 0).
    purchase_inputs = [
        _PI(
            purchase_id=600,
            shares=split_secret(1, n=3, k=3, prime=_P),
            notional=50_000_000,
            sla_bps=500,
            bpa_mode=True,
            bpas=[1_900_000, 2_000_000],
            wpas=[1_850_000, 1_950_000],
            outcomes=[_FAV, _UNFAV],
        ),
        _PI(
            purchase_id=601,
            shares=split_secret(2, n=3, k=3, prime=_P),
            notional=100_000_000,
            sla_bps=750,
            bpa_mode=False,
            bpas=[1_900_000, 2_000_000],
            wpas=[1_850_000, 1_950_000],
            outcomes=[_UNFAV, _FAV],
        ),
    ]

    for purchase in purchase_inputs:
        sig_id = f"sig-{purchase.purchase_id}"
        for s in purchase.shares:
            stores[s.x].store(
                signal_id=sig_id,
                genius_address="0x" + "ef" * 20,
                share=Share(x=s.x, y=0),  # key share y is irrelevant for batch MPC
                encrypted_key_share=b"placeholder",
                encrypted_index_share=int(s.y).to_bytes(32, "big"),
                shamir_threshold=3,
            )

    participant_xs = [1, 2, 3]
    # 2-line => no beaver triples needed.
    triples_per_purchase = [[], []]

    async def _peer_rpc(vx: int, endpoint: str, payload: dict) -> dict:
        resp = clients[vx].post(f"/v1/mpc/batch/{endpoint}", json=payload)
        if resp.status_code != 200:
            raise RuntimeError(f"peer {vx} {endpoint} failed: {resp.status_code} {resp.text}")
        return resp.json()

    result = _asyncio.run(
        drive_http_batch_settlement(
            session_id="batch-2line-regression",
            participant_xs=participant_xs,
            threshold=3,
            batch=purchase_inputs,
            beaver_triples_per_purchase=triples_per_purchase,
            peer_rpc=_peer_rpc,
        )
    )

    expected = _sim(purchase_inputs, threshold=3)
    assert result.total_score_change == expected.total_score_change
    assert result.purchase_count == 2


def _make_orch_with_fake_peer_request(peer_list, share_x_lookup):
    """Build an MPCOrchestrator instance with _get_peer_validators and
    _peer_request both mocked. ``peer_list`` is the fake peer dicts.
    ``share_x_lookup`` is a callable (peer_uid, signal_id) -> int | None
    that decides what share_info returns.
    """
    import httpx as _httpx
    import json as _json
    from djinn_validator.core.mpc_orchestrator import MPCOrchestrator
    from djinn_validator.core.mpc_coordinator import MPCCoordinator

    orch = MPCOrchestrator(
        coordinator=MPCCoordinator(),
        neuron=None,
        threshold=3,
    )
    orch._get_peer_validators = lambda: list(peer_list)  # type: ignore[method-assign]

    async def _fake_peer_request(method, url, *, peer_uid=None, **kwargs):
        # Extract signal_id from URL like /v1/signal/{id}/share_info
        import re as _re

        m = _re.search(r"/v1/signal/([^/]+)/share_info", url)
        if not m:
            raise RuntimeError(f"unexpected URL: {url}")
        signal_id = m.group(1)
        share_x = share_x_lookup(peer_uid, signal_id)
        if share_x is None:
            return _httpx.Response(
                404,
                content=_json.dumps({"detail": "not found"}).encode(),
                request=_httpx.Request(method, url),
            )
        return _httpx.Response(
            200,
            content=_json.dumps(
                {
                    "signal_id": signal_id,
                    "share_x": share_x,
                    "shamir_threshold": 3,
                }
            ).encode(),
            request=_httpx.Request(method, url),
        )

    orch._peer_request = _fake_peer_request  # type: ignore[method-assign]
    return orch


def test_resolve_batch_participants_happy_path():
    import asyncio as _asyncio

    peers = [
        {"uid": 1, "url": "http://p1.test", "hotkey": "h1"},
        {"uid": 2, "url": "http://p2.test", "hotkey": "h2"},
        {"uid": 3, "url": "http://p3.test", "hotkey": "h3"},
    ]
    # Each peer has a stable share_x across all signals in the batch.
    per_peer_x = {1: 1, 2: 2, 3: 3}
    orch = _make_orch_with_fake_peer_request(
        peers,
        lambda uid, sig_id: per_peer_x.get(uid),
    )
    participant_map = _asyncio.run(
        orch.resolve_batch_participants(
            signal_ids=["sig-a", "sig-b", "sig-c"],
            threshold=3,
        )
    )
    assert participant_map is not None
    assert set(participant_map.keys()) == {1, 2, 3}
    # participant_map values should be peer dicts
    assert participant_map[1]["uid"] == 1
    assert participant_map[2]["uid"] == 2
    _asyncio.run(orch.close())


def test_resolve_batch_participants_drops_peer_with_inconsistent_share_x():
    import asyncio as _asyncio

    peers = [
        {"uid": 1, "url": "http://p1.test", "hotkey": "h1"},
        {"uid": 2, "url": "http://p2.test", "hotkey": "h2"},
        {"uid": 3, "url": "http://p3.test", "hotkey": "h3"},
    ]

    def lookup(uid, sig_id):
        if uid == 2 and sig_id == "sig-b":
            return 99  # peer 2 has a different x for sig-b — inconsistent
        return {1: 1, 2: 2, 3: 3}[uid]

    orch = _make_orch_with_fake_peer_request(peers, lookup)
    participant_map = _asyncio.run(
        orch.resolve_batch_participants(
            signal_ids=["sig-a", "sig-b", "sig-c"],
            threshold=3,
        )
    )
    # Peer 2 is dropped because its share_x isn't consistent across
    # all three signals. Only peers 1 and 3 survive. threshold - 1 = 2,
    # so exactly at the floor.
    assert participant_map is not None
    assert set(participant_map.keys()) == {1, 3}
    _asyncio.run(orch.close())


def test_resolve_batch_participants_drops_peer_missing_a_signal():
    import asyncio as _asyncio

    peers = [
        {"uid": 1, "url": "http://p1.test", "hotkey": "h1"},
        {"uid": 2, "url": "http://p2.test", "hotkey": "h2"},
        {"uid": 3, "url": "http://p3.test", "hotkey": "h3"},
    ]

    def lookup(uid, sig_id):
        if uid == 3 and sig_id == "sig-b":
            return None  # 404
        return {1: 1, 2: 2, 3: 3}[uid]

    orch = _make_orch_with_fake_peer_request(peers, lookup)
    participant_map = _asyncio.run(
        orch.resolve_batch_participants(
            signal_ids=["sig-a", "sig-b", "sig-c"],
            threshold=3,
        )
    )
    # Peer 3 fails share_info for sig-b, so it's dropped.
    assert participant_map is not None
    assert set(participant_map.keys()) == {1, 2}
    _asyncio.run(orch.close())


def test_resolve_batch_participants_below_threshold_returns_none():
    import asyncio as _asyncio

    peers = [
        {"uid": 1, "url": "http://p1.test", "hotkey": "h1"},
        {"uid": 2, "url": "http://p2.test", "hotkey": "h2"},
    ]
    per_peer_x = {1: 1, 2: 2}
    orch = _make_orch_with_fake_peer_request(
        peers,
        lambda uid, sig_id: per_peer_x.get(uid),
    )
    # threshold=5, only 2 peers available, so threshold-1=4 > 2 -> None
    result = _asyncio.run(
        orch.resolve_batch_participants(
            signal_ids=["sig-a"],
            threshold=5,
        )
    )
    assert result is None
    _asyncio.run(orch.close())


def test_resolve_batch_participants_collision_drops_duplicate():
    import asyncio as _asyncio

    peers = [
        {"uid": 1, "url": "http://p1.test", "hotkey": "h1"},
        {"uid": 2, "url": "http://p2.test", "hotkey": "h2"},
        {"uid": 3, "url": "http://p3.test", "hotkey": "h3"},
    ]
    # Peer 3 claims share_x=1, which is already taken by peer 1.
    per_peer_x = {1: 1, 2: 2, 3: 1}
    orch = _make_orch_with_fake_peer_request(
        peers,
        lambda uid, sig_id: per_peer_x.get(uid),
    )
    participant_map = _asyncio.run(
        orch.resolve_batch_participants(
            signal_ids=["sig-a"],
            threshold=3,
        )
    )
    # The first peer to claim x=1 wins (peer 1); peer 3 is dropped.
    # Peer 2 keeps x=2. So we get {1, 2}, which is threshold-1=2 peers.
    assert participant_map is not None
    assert set(participant_map.keys()) == {1, 2}
    assert participant_map[1]["uid"] == 1
    _asyncio.run(orch.close())


def test_resolve_batch_participants_empty_peer_list_returns_none():
    import asyncio as _asyncio

    orch = _make_orch_with_fake_peer_request([], lambda uid, sig_id: None)
    result = _asyncio.run(
        orch.resolve_batch_participants(
            signal_ids=["sig-a"],
            threshold=3,
        )
    )
    assert result is None
    _asyncio.run(orch.close())


def test_orchestrator_run_batch_settlement_end_to_end(three_peer_batch_apps):
    """The MPCOrchestrator.run_batch_settlement wrapper drives the
    batch protocol through its own ``_peer_request`` path, so the
    same handler suite that answers real peers also answers the
    orchestrator. Test mocks ``_peer_request`` to route URL-based
    calls to the three TestClients based on the peer URL.
    """
    import asyncio as _asyncio
    from unittest.mock import MagicMock, AsyncMock

    clients, stores = three_peer_batch_apps

    from djinn_validator.core.mpc import generate_beaver_triples
    from djinn_validator.core.mpc_batch_settlement import (
        PurchaseInputs as _PI,
        OUTCOME_FAVORABLE as _FAV,
        OUTCOME_UNFAVORABLE as _UNFAV,
        simulate_distributed_batch_settle as _sim,
    )
    from djinn_validator.core.mpc_orchestrator import MPCOrchestrator
    from djinn_validator.core.mpc_coordinator import MPCCoordinator
    from djinn_validator.core.shares import Share
    from djinn_validator.utils.crypto import BN254_PRIME as _P, split_secret

    # Seed shares across the three peer ShareStores.
    purchase_inputs = [
        _PI(
            purchase_id=700,
            shares=split_secret(1, n=3, k=3, prime=_P),
            notional=50_000_000,
            sla_bps=500,
            bpa_mode=True,
            bpas=[1_950_000, 2_000_000, 1_850_000],
            wpas=[1_850_000, 1_900_000, 1_750_000],
            outcomes=[_FAV, _UNFAV, _FAV],
        ),
    ]
    for purchase in purchase_inputs:
        sig_id = f"sig-{purchase.purchase_id}"
        for s in purchase.shares:
            stores[s.x].store(
                signal_id=sig_id,
                genius_address="0x" + "ef" * 20,
                share=Share(x=s.x, y=0),  # key share y is irrelevant for batch MPC
                encrypted_key_share=b"placeholder",
                encrypted_index_share=int(s.y).to_bytes(32, "big"),
                shamir_threshold=3,
            )

    # Build participant peer map. URL scheme is cosmetic — the mocked
    # _peer_request routes by URL prefix back to the TestClients.
    participant_peers = {
        1: {"uid": 1, "url": "http://peer1.test", "hotkey": "h1"},
        2: {"uid": 2, "url": "http://peer2.test", "hotkey": "h2"},
        3: {"uid": 3, "url": "http://peer3.test", "hotkey": "h3"},
    }

    # Beaver triples per purchase.
    triples_per_purchase = []
    for purchase in purchase_inputs:
        n_gates = max(0, len(purchase.bpas) - 2)
        if n_gates > 0:
            triples_per_purchase.append(
                generate_beaver_triples(
                    n_gates,
                    n=3,
                    k=3,
                    prime=_P,
                    x_coords=[1, 2, 3],
                )
            )
        else:
            triples_per_purchase.append([])

    # Build a minimal orchestrator whose _peer_request routes to
    # TestClients based on the peer URL prefix.
    coordinator = MPCCoordinator()
    orch = MPCOrchestrator(coordinator=coordinator, neuron=None, threshold=3)

    async def _routed_peer_request(method, url, *, peer_uid=None, **kwargs):
        # Route based on the URL hostname to pick the right TestClient.
        target_vx = None
        for vx, peer in participant_peers.items():
            if url.startswith(peer["url"]):
                target_vx = vx
                break
        if target_vx is None:
            raise RuntimeError(f"no TestClient for URL {url}")

        # Pull the JSON body out of kwargs; both json= and content=
        # are supported by the production _peer_request, but drive_http_
        # batch_settlement uses json= so handle that form.
        body = kwargs.get("json")
        if body is None and "content" in kwargs:
            import json as _json

            body = _json.loads(kwargs["content"])

        # Extract endpoint path from URL.
        from urllib.parse import urlparse

        path = urlparse(url).path

        resp = clients[target_vx].post(path, json=body)

        # Wrap the TestClient Response in a shim that matches the
        # subset of httpx.Response the driver uses: status_code, text, json().
        class _ResponseShim:
            def __init__(self, r):
                self.status_code = r.status_code
                self.text = r.text
                self._r = r

            def json(self):
                return self._r.json()

        return _ResponseShim(resp)

    orch._peer_request = _routed_peer_request  # type: ignore[method-assign]

    result = _asyncio.run(
        orch.run_batch_settlement(
            session_id="batch-orch-001",
            batch=purchase_inputs,
            beaver_triples_per_purchase=triples_per_purchase,
            participant_peers=participant_peers,
            threshold=3,
        )
    )

    expected = _sim(purchase_inputs, threshold=3)
    assert result.total_score_change == expected.total_score_change
    assert result.purchase_count == 1

    _asyncio.run(orch.close())
