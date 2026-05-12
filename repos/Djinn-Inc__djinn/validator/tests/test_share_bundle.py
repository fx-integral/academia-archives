"""Tests for the storeShareBundle + share-recovery endpoints (Phase 4 of share recovery)."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient
from nacl.public import PrivateKey, PublicKey, SealedBox

from djinn_validator.api.server import create_app
from djinn_validator.core.outcomes import OutcomeAttestor
from djinn_validator.core.purchase import PurchaseOrchestrator
from djinn_validator.core.shares import ShareStore


GENIUS = "0x" + "ab" * 20
SELF_VALIDATOR = "0x" + "11" * 20
PEER_A = "0x" + "22" * 20
PEER_B = "0x" + "33" * 20


@pytest.fixture
def keypair():
    priv = PrivateKey.generate()
    return bytes(priv), bytes(priv.public_key)


@pytest.fixture
def store():
    s = ShareStore()
    yield s
    s.close()


@pytest.fixture
def client(store, keypair):
    privkey, _ = keypair
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
        encryption_privkey=privkey,
        signer_address=SELF_VALIDATOR,
    )
    return TestClient(app)


def _seal(pubkey_bytes: bytes, plaintext: bytes) -> str:
    box = SealedBox(PublicKey(pubkey_bytes))
    return bytes(box.encrypt(plaintext)).hex()


def _share_y_bytes() -> bytes:
    return (12345).to_bytes(32, "big")


def _index_y_bytes() -> bytes:
    return (1).to_bytes(32, "big")


def test_bundle_stores_own_share_and_forwarding(client, keypair, store):
    _, my_pub = keypair
    peer_a_priv = PrivateKey.generate()
    peer_b_priv = PrivateKey.generate()

    payload = {
        "signal_id": "test-signal-001",
        "genius_address": GENIUS,
        "shamir_threshold": 2,
        "bundle": [
            {
                "target_address": SELF_VALIDATOR,
                "share_x": 1,
                "share_ciphertext": _seal(my_pub, _share_y_bytes()),
                "index_ciphertext": _seal(my_pub, _index_y_bytes()),
            },
            {
                "target_address": PEER_A,
                "share_x": 2,
                "share_ciphertext": _seal(bytes(peer_a_priv.public_key), _share_y_bytes()),
                "index_ciphertext": "",
            },
            {
                "target_address": PEER_B,
                "share_x": 3,
                "share_ciphertext": _seal(bytes(peer_b_priv.public_key), _share_y_bytes()),
                "index_ciphertext": "",
            },
        ],
        "precomputed_triples": [],
    }
    resp = client.post("/v1/signal/bundle", json=payload)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["own_share_stored"] is True
    assert body["forwarding_count"] == 2

    # Own share recoverable from share_store
    rec = store.get("test-signal-001")
    assert rec is not None
    assert rec.share.y == 12345

    # Forwarding entries stored
    fwd_a = store.get_forwarding("test-signal-001", PEER_A)
    assert fwd_a is not None
    assert fwd_a["share_x"] == 2
    fwd_b = store.get_forwarding("test-signal-001", PEER_B)
    assert fwd_b is not None
    assert fwd_b["share_x"] == 3


def test_bundle_without_own_entry_only_forwarding(client, store):
    peer_a_priv = PrivateKey.generate()
    payload = {
        "signal_id": "no-own-entry",
        "genius_address": GENIUS,
        "shamir_threshold": 2,
        "bundle": [
            {
                "target_address": PEER_A,
                "share_x": 2,
                "share_ciphertext": _seal(bytes(peer_a_priv.public_key), _share_y_bytes()),
                "index_ciphertext": "",
            },
        ],
        "precomputed_triples": [],
    }
    resp = client.post("/v1/signal/bundle", json=payload)
    assert resp.status_code == 200
    body = resp.json()
    assert body["own_share_stored"] is False
    assert body["forwarding_count"] == 1


def test_bundle_decrypt_failure_returns_400(client):
    payload = {
        "signal_id": "bad-ct",
        "genius_address": GENIUS,
        "shamir_threshold": 2,
        "bundle": [
            {
                "target_address": SELF_VALIDATOR,
                "share_x": 1,
                "share_ciphertext": "00" * 80,  # not a valid SealedBox ciphertext
                "index_ciphertext": "",
            },
        ],
        "precomputed_triples": [],
    }
    resp = client.post("/v1/signal/bundle", json=payload)
    assert resp.status_code == 400


def test_v1705_bundle_complete_ticks_metric(client, keypair, store):
    """v1705: a successful end-to-end bundle (own + forwarding all ok)
    ticks BUNDLE_STORE_RESULT.labels(outcome='complete')."""
    from djinn_validator.api.metrics import BUNDLE_STORE_RESULT

    _, my_pub = keypair
    peer_priv = PrivateKey.generate()
    payload = {
        "signal_id": "metric-complete-1",
        "genius_address": GENIUS,
        "shamir_threshold": 2,
        "bundle": [
            {
                "target_address": SELF_VALIDATOR,
                "share_x": 1,
                "share_ciphertext": _seal(my_pub, _share_y_bytes()),
                "index_ciphertext": "",
            },
            {
                "target_address": PEER_A,
                "share_x": 2,
                "share_ciphertext": _seal(bytes(peer_priv.public_key), _share_y_bytes()),
                "index_ciphertext": "",
            },
        ],
        "precomputed_triples": [],
    }
    before = BUNDLE_STORE_RESULT.labels(outcome="complete")._value.get()
    resp = client.post("/v1/signal/bundle", json=payload)
    assert resp.status_code == 200
    after = BUNDLE_STORE_RESULT.labels(outcome="complete")._value.get()
    assert after == before + 1


def test_v1705_bundle_missing_own_entry_ticks_metric(client, store):
    """v1705: a bundle that doesn't include this validator's address
    ticks BUNDLE_STORE_RESULT.labels(outcome='missing_own_entry')."""
    from djinn_validator.api.metrics import BUNDLE_STORE_RESULT

    peer_priv = PrivateKey.generate()
    payload = {
        "signal_id": "metric-missing-own",
        "genius_address": GENIUS,
        "shamir_threshold": 2,
        "bundle": [
            {
                "target_address": PEER_A,
                "share_x": 2,
                "share_ciphertext": _seal(bytes(peer_priv.public_key), _share_y_bytes()),
                "index_ciphertext": "",
            },
        ],
        "precomputed_triples": [],
    }
    before = BUNDLE_STORE_RESULT.labels(outcome="missing_own_entry")._value.get()
    resp = client.post("/v1/signal/bundle", json=payload)
    assert resp.status_code == 200
    after = BUNDLE_STORE_RESULT.labels(outcome="missing_own_entry")._value.get()
    assert after == before + 1


def test_v1705_bundle_decrypt_failure_ticks_metric(client):
    """v1705: bad SealedBox ciphertext ticks
    BUNDLE_STORE_RESULT.labels(outcome='own_decrypt_failed')."""
    from djinn_validator.api.metrics import BUNDLE_STORE_RESULT

    payload = {
        "signal_id": "metric-bad-ct",
        "genius_address": GENIUS,
        "shamir_threshold": 2,
        "bundle": [
            {
                "target_address": SELF_VALIDATOR,
                "share_x": 1,
                "share_ciphertext": "00" * 80,
                "index_ciphertext": "",
            },
        ],
        "precomputed_triples": [],
    }
    before = BUNDLE_STORE_RESULT.labels(outcome="own_decrypt_failed")._value.get()
    resp = client.post("/v1/signal/bundle", json=payload)
    assert resp.status_code == 400
    after = BUNDLE_STORE_RESULT.labels(outcome="own_decrypt_failed")._value.get()
    assert after == before + 1


def test_share_recovery_serves_forwarding_blob(client, keypair, store):
    _, my_pub = keypair
    peer_a_priv = PrivateKey.generate()
    payload = {
        "signal_id": "recovery-test",
        "genius_address": GENIUS,
        "shamir_threshold": 2,
        "bundle": [
            {
                "target_address": SELF_VALIDATOR,
                "share_x": 1,
                "share_ciphertext": _seal(my_pub, _share_y_bytes()),
                "index_ciphertext": "",
            },
            {
                "target_address": PEER_A,
                "share_x": 2,
                "share_ciphertext": _seal(bytes(peer_a_priv.public_key), _share_y_bytes()),
                "index_ciphertext": "",
            },
        ],
        "precomputed_triples": [],
    }
    client.post("/v1/signal/bundle", json=payload)

    resp = client.get(f"/v1/share-recovery/recovery-test/{PEER_A}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["target_address"] == PEER_A
    assert body["share_x"] == 2
    assert body["shamir_threshold"] == 2
    # Peer A can decrypt the returned ciphertext with their privkey
    ct = bytes.fromhex(body["share_ciphertext"])
    decrypted = SealedBox(peer_a_priv).decrypt(ct)
    assert int.from_bytes(decrypted, "big") == 12345


def test_share_recovery_404_for_unknown(client):
    resp = client.get(f"/v1/share-recovery/no-such-signal/{PEER_A}")
    assert resp.status_code == 404


def test_share_recovery_400_for_invalid_address(client):
    resp = client.get("/v1/share-recovery/some-signal/not-an-address")
    assert resp.status_code == 400


def test_bundle_without_keypair_returns_503(store):
    """If validator has no encryption keypair, bundle endpoint must fail loudly."""
    purchase_orch = PurchaseOrchestrator(store)
    outcome_attestor = OutcomeAttestor()
    mock_chain = AsyncMock()
    mock_chain.is_connected = AsyncMock(return_value=True)
    mock_chain.is_paused = AsyncMock(return_value=False)
    mock_chain.get_signal = AsyncMock(return_value=None)
    # No encryption_privkey or signer_address passed
    app = create_app(store, purchase_orch, outcome_attestor, chain_client=mock_chain)
    c = TestClient(app)

    payload = {
        "signal_id": "no-keys",
        "genius_address": GENIUS,
        "shamir_threshold": 2,
        "bundle": [
            {
                "target_address": SELF_VALIDATOR,
                "share_x": 1,
                "share_ciphertext": "ab" * 80,
                "index_ciphertext": "",
            }
        ],
        "precomputed_triples": [],
    }
    resp = c.post("/v1/signal/bundle", json=payload)
    assert resp.status_code == 503
