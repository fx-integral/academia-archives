"""End-to-end integration test for share recovery.

Exercises the forced-degraded path: a genius's bundle fan-out reaches
2 of 3 validators (the third is simulated as 504-ing). The missing
validator later runs share recovery against the 2 that received the
bundle, decrypts via SealedBox, and ends up with the share. This is
the protocol-level check that the C+F design closes the divergence
gap by going-forward signals only (Phase 6 of share recovery).
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient
from nacl.public import PrivateKey, PublicKey, SealedBox

from djinn_validator.api.server import create_app
from djinn_validator.core.outcomes import OutcomeAttestor
from djinn_validator.core.purchase import PurchaseOrchestrator
from djinn_validator.core.share_recovery import recover_missing_shares
from djinn_validator.core.shares import ShareStore


GENIUS = "0x" + "ab" * 20
SIGNAL_ID = "e2e-share-recovery"


def _make_validator(addr_suffix: str):
    """Spin up a validator with its own keypair, share_store, and FastAPI app."""
    priv = PrivateKey.generate()
    privkey_bytes = bytes(priv)
    pubkey_bytes = bytes(priv.public_key)
    addr = "0x" + addr_suffix.ljust(40, "0")
    store = ShareStore()
    purchase_orch = PurchaseOrchestrator(store)
    outcome_attestor = OutcomeAttestor()
    mock_chain = AsyncMock()
    mock_chain.is_connected = AsyncMock(return_value=True)
    mock_chain.is_paused = AsyncMock(return_value=False)
    mock_chain.get_signal = AsyncMock(return_value=None)
    app = create_app(
        store,
        purchase_orch,
        outcome_attestor,
        chain_client=mock_chain,
        encryption_privkey=privkey_bytes,
        signer_address=addr,
    )
    client = TestClient(app)
    return {
        "addr": addr,
        "privkey": privkey_bytes,
        "pubkey": pubkey_bytes,
        "store": store,
        "client": client,
    }


def _build_bundle_payload(
    validators: list[dict],
    *,
    signal_id: str,
    genius: str,
    secret_y_per_validator: dict[str, int],
    threshold: int = 2,
) -> dict:
    """Genius-side: build the encrypted bundle SealedBox-encrypted to each validator's pubkey."""
    bundle_entries = []
    for idx, v in enumerate(validators, start=1):
        share_y = secret_y_per_validator[v["addr"]]
        share_y_bytes = share_y.to_bytes(32, "big")
        ct = bytes(SealedBox(PublicKey(v["pubkey"])).encrypt(share_y_bytes))
        bundle_entries.append(
            {
                "target_address": v["addr"],
                "share_x": idx,
                "share_ciphertext": ct.hex(),
                "index_ciphertext": "",
            }
        )
    return {
        "signal_id": signal_id,
        "genius_address": genius,
        "shamir_threshold": threshold,
        "bundle": bundle_entries,
        "precomputed_triples": [],
    }


def test_e2e_forced_degraded_then_peer_recovery(httpx_mock):
    """
    Three validators (V1, V2, V3). The genius's bundle fan-out reaches
    only V1 and V2 — V3 is simulated as 504-ing during the original POST.
    V1 and V2 each decrypt their own entries and persist V3's forwarding
    blob locally. V3 then calls recover_missing_shares pointed at V1 + V2;
    the recovery loop pulls the forwarding blob from V1 (first 200) and
    decrypts it with V3's privkey. V3 ends up with its share.

    This validates the architectural close: a transiently-down validator
    that missed the original fan-out heals via peer recovery.
    """
    v1 = _make_validator("aaa1")
    v2 = _make_validator("bbb2")
    v3 = _make_validator("ccc3")
    validators = [v1, v2, v3]

    # Fake per-validator share_y values. Real Shamir sharing happens on the
    # genius client; here we just need three distinct "share" values that
    # we can identify post-recovery. Real implementations would use
    # splitSecret to produce points on a polynomial, but the recovery
    # protocol is share-content-agnostic.
    secret_per_v = {
        v1["addr"]: 0x1111,
        v2["addr"]: 0x2222,
        v3["addr"]: 0x3333,
    }

    bundle = _build_bundle_payload(
        validators,
        signal_id=SIGNAL_ID,
        genius=GENIUS,
        secret_y_per_validator=secret_per_v,
    )

    # Genius "fans out" to V1 and V2 successfully; V3 is simulated as 504.
    r1 = v1["client"].post("/v1/signal/bundle", json=bundle)
    assert r1.status_code == 200, r1.text
    body1 = r1.json()
    assert body1["own_share_stored"] is True
    assert body1["forwarding_count"] == 2

    r2 = v2["client"].post("/v1/signal/bundle", json=bundle)
    assert r2.status_code == 200, r2.text
    body2 = r2.json()
    assert body2["own_share_stored"] is True
    assert body2["forwarding_count"] == 2

    # V3 missed the bundle → no share locally
    assert v3["store"].has(SIGNAL_ID) is False

    # V3 has forwarding ciphertexts on V1 and V2 — verify they exist server-side
    fwd_on_v1 = v1["store"].get_forwarding(SIGNAL_ID, v3["addr"])
    fwd_on_v2 = v2["store"].get_forwarding(SIGNAL_ID, v3["addr"])
    assert fwd_on_v1 is not None
    assert fwd_on_v2 is not None
    assert fwd_on_v1["share_x"] == 3  # V3 was index 3 in the bundle

    # Use V1's TestClient to simulate the share-recovery GET that V3
    # would make. We patch httpx via httpx_mock so V3's recover_missing_shares
    # appears to call out to V1 and V2 over the network.
    v1_url = "http://v1.example"
    v2_url = "http://v2.example"

    # Pull V1's forwarding entry shape via its own GET endpoint to mirror the
    # real wire format.
    fwd_v1_resp = v1["client"].get(f"/v1/share-recovery/{SIGNAL_ID}/{v3['addr']}")
    assert fwd_v1_resp.status_code == 200
    fwd_v1_body = fwd_v1_resp.json()

    # Wire only V1's mock — recover_missing_shares stops at first 200,
    # so registering V2 would leave it unused (pytest-httpx warns).
    httpx_mock.add_response(
        url=f"{v1_url}/v1/share-recovery/{SIGNAL_ID}/{v3['addr'].lower()}",
        json=fwd_v1_body,
    )

    import asyncio

    tally = asyncio.run(
        recover_missing_shares(
            signal_ids=[SIGNAL_ID],
            share_store=v3["store"],
            peer_validators=[
                {"url": v1_url, "uid": 1},
                {"url": v2_url, "uid": 2},
            ],
            encryption_privkey=v3["privkey"],
            signer_address=v3["addr"],
            genius_address_for={SIGNAL_ID: GENIUS},
        )
    )
    assert tally.get("recovered") == 1

    # V3 now has the share locally
    rec = v3["store"].get(SIGNAL_ID)
    assert rec is not None
    assert rec.share.x == 3
    assert rec.share.y == 0x3333

    # And critically — V3's recovered share matches what the genius
    # encrypted ORIGINALLY. The forwarding blob round-tripped via V1
    # without ever being decrypted on V1 (V1 holds it as a forwarding
    # blob targeted at V3, not its own).
    assert rec.share.y == secret_per_v[v3["addr"]]

    for v in validators:
        v["store"].close()
