"""Tests for djinn_validator.core.share_recovery."""

from __future__ import annotations

import pytest
from nacl.public import PrivateKey, PublicKey, SealedBox

from djinn_validator.core.share_recovery import recover_missing_shares
from djinn_validator.core.shares import ShareStore


SELF_ADDR = "0x" + "11" * 20


@pytest.fixture
def keypair():
    priv = PrivateKey.generate()
    return bytes(priv), bytes(priv.public_key)


@pytest.fixture
def store():
    s = ShareStore()
    yield s
    s.close()


def _seal(pubkey_bytes: bytes, plaintext: bytes) -> str:
    return bytes(SealedBox(PublicKey(pubkey_bytes)).encrypt(plaintext)).hex()


@pytest.mark.asyncio
async def test_recover_from_first_peer_with_blob(keypair, store, httpx_mock):
    privkey, pubkey = keypair
    share_y_bytes = (98765).to_bytes(32, "big")
    httpx_mock.add_response(
        url=f"http://peer-a.example/v1/share-recovery/sig-1/{SELF_ADDR}",
        status_code=404,
    )
    httpx_mock.add_response(
        url=f"http://peer-b.example/v1/share-recovery/sig-1/{SELF_ADDR}",
        json={
            "signal_id": "sig-1",
            "target_address": SELF_ADDR,
            "share_x": 7,
            "share_ciphertext": _seal(pubkey, share_y_bytes),
            "index_ciphertext": "",
            "shamir_threshold": 2,
        },
    )
    peers = [
        {"url": "http://peer-a.example", "uid": 1},
        {"url": "http://peer-b.example", "uid": 2},
    ]
    tally = await recover_missing_shares(
        signal_ids=["sig-1"],
        share_store=store,
        peer_validators=peers,
        encryption_privkey=privkey,
        signer_address=SELF_ADDR,
    )
    assert tally.get("recovered") == 1
    rec = store.get("sig-1")
    assert rec is not None
    assert rec.share.y == 98765
    assert rec.share.x == 7


@pytest.mark.asyncio
async def test_skip_signals_already_present(keypair, store):
    privkey, _ = keypair
    from djinn_validator.utils.crypto import Share

    store.store(
        signal_id="sig-already-have",
        genius_address="0x" + "ab" * 20,
        share=Share(x=1, y=42),
        encrypted_key_share=b"\x01" * 32,
    )
    peers = [{"url": "http://peer.example", "uid": 1}]
    # No httpx_mock needed: present-share path never makes a request.
    tally = await recover_missing_shares(
        signal_ids=["sig-already-have"],
        share_store=store,
        peer_validators=peers,
        encryption_privkey=privkey,
        signer_address=SELF_ADDR,
    )
    assert tally.get("skip_present") == 1
    assert tally.get("recovered", 0) == 0


@pytest.mark.asyncio
async def test_no_peer_has_blob_returns_no_peer_had_it(keypair, store, httpx_mock):
    privkey, _ = keypair
    httpx_mock.add_response(
        url=f"http://peer-a.example/v1/share-recovery/sig-1/{SELF_ADDR}",
        status_code=404,
    )
    httpx_mock.add_response(
        url=f"http://peer-b.example/v1/share-recovery/sig-1/{SELF_ADDR}",
        status_code=404,
    )
    peers = [
        {"url": "http://peer-a.example", "uid": 1},
        {"url": "http://peer-b.example", "uid": 2},
    ]
    tally = await recover_missing_shares(
        signal_ids=["sig-1"],
        share_store=store,
        peer_validators=peers,
        encryption_privkey=privkey,
        signer_address=SELF_ADDR,
    )
    assert tally.get("no_peer_had_it") == 1


@pytest.mark.asyncio
async def test_decrypt_failure_keeps_polling_other_peers(keypair, store, httpx_mock):
    privkey, pubkey = keypair
    other_priv = PrivateKey.generate()
    share_y_bytes_good = (12345).to_bytes(32, "big")
    httpx_mock.add_response(
        url=f"http://peer-bad.example/v1/share-recovery/sig-1/{SELF_ADDR}",
        json={
            "signal_id": "sig-1",
            "target_address": SELF_ADDR,
            "share_x": 1,
            "share_ciphertext": _seal(bytes(other_priv.public_key), share_y_bytes_good),
            "index_ciphertext": "",
            "shamir_threshold": 2,
        },
    )
    httpx_mock.add_response(
        url=f"http://peer-good.example/v1/share-recovery/sig-1/{SELF_ADDR}",
        json={
            "signal_id": "sig-1",
            "target_address": SELF_ADDR,
            "share_x": 2,
            "share_ciphertext": _seal(pubkey, share_y_bytes_good),
            "index_ciphertext": "",
            "shamir_threshold": 2,
        },
    )
    peers = [
        {"url": "http://peer-bad.example", "uid": 1},
        {"url": "http://peer-good.example", "uid": 2},
    ]
    tally = await recover_missing_shares(
        signal_ids=["sig-1"],
        share_store=store,
        peer_validators=peers,
        encryption_privkey=privkey,
        signer_address=SELF_ADDR,
    )
    assert tally.get("recovered") == 1
    assert any(k.startswith("decrypt_failed_") for k in tally.keys())
    rec = store.get("sig-1")
    assert rec is not None
    assert rec.share.y == 12345
    assert rec.share.x == 2


@pytest.mark.asyncio
async def test_empty_inputs(keypair, store):
    privkey, _ = keypair
    tally = await recover_missing_shares(
        signal_ids=[],
        share_store=store,
        peer_validators=[{"url": "http://peer.example", "uid": 1}],
        encryption_privkey=privkey,
        signer_address=SELF_ADDR,
    )
    assert tally == {}

    tally = await recover_missing_shares(
        signal_ids=["sig-1"],
        share_store=store,
        peer_validators=[],
        encryption_privkey=privkey,
        signer_address=SELF_ADDR,
    )
    assert tally == {}


@pytest.mark.asyncio
async def test_peer_404_is_distinct_from_peer_unreachable(keypair, store, httpx_mock):
    """v1701: peer 404 and peer connection error must surface as distinct
    counter labels so operators can tell upstream-replication gaps from
    transport failures."""
    privkey, _ = keypair
    httpx_mock.add_response(
        url=f"http://peer-a.example/v1/share-recovery/sig-1/{SELF_ADDR}",
        status_code=404,
    )
    httpx_mock.add_response(
        url=f"http://peer-b.example/v1/share-recovery/sig-1/{SELF_ADDR}",
        status_code=404,
    )
    peers = [
        {"url": "http://peer-a.example", "uid": 1},
        {"url": "http://peer-b.example", "uid": 2},
    ]
    tally = await recover_missing_shares(
        signal_ids=["sig-1"],
        share_store=store,
        peer_validators=peers,
        encryption_privkey=privkey,
        signer_address=SELF_ADDR,
    )
    assert tally.get("peer_404") == 2
    assert tally.get("no_peer_had_it") == 1
    assert tally.get("peer_unreachable", 0) == 0


@pytest.mark.asyncio
async def test_peer_unreachable_bumps_counter(keypair, store, httpx_mock):
    """v1701: when httpx raises, the peer is marked unreachable rather
    than silently rolled into no_peer_had_it. Without this label,
    a network outage looked identical to genuine bundle gaps."""
    import httpx as _httpx

    privkey, _ = keypair
    httpx_mock.add_exception(
        _httpx.ConnectError("connection refused"),
        url=f"http://peer-a.example/v1/share-recovery/sig-1/{SELF_ADDR}",
    )
    httpx_mock.add_exception(
        _httpx.ReadTimeout("timeout"),
        url=f"http://peer-b.example/v1/share-recovery/sig-1/{SELF_ADDR}",
    )
    peers = [
        {"url": "http://peer-a.example", "uid": 1},
        {"url": "http://peer-b.example", "uid": 2},
    ]
    tally = await recover_missing_shares(
        signal_ids=["sig-1"],
        share_store=store,
        peer_validators=peers,
        encryption_privkey=privkey,
        signer_address=SELF_ADDR,
    )
    assert tally.get("peer_unreachable") == 2
    assert tally.get("no_peer_had_it") == 1
    assert tally.get("peer_404", 0) == 0


@pytest.mark.asyncio
async def test_no_peer_had_it_not_suppressed_after_skip_already_stored(
    keypair, store, httpx_mock
):
    """v1701 regression: prior to v1701, after the FIRST signal in a
    batch hit skip_already_stored, EVERY subsequent unrecovered signal
    silently failed to bump no_peer_had_it because the suppression
    check inspected the cumulative tally instead of per-signal state.
    This pinned the bug so the latent metric gap doesn't return."""
    privkey, pubkey = keypair
    share_y_bytes = (12345).to_bytes(32, "big")

    # signal A: peer returns a valid blob, but store already has it
    # (race) -> bumps skip_already_stored, sets per-signal flag.
    from djinn_validator.utils.crypto import Share

    store.store(
        signal_id="sig-already-have",
        genius_address="0x" + "ab" * 20,
        share=Share(x=1, y=42),
        encrypted_key_share=b"\x01" * 32,
    )
    # signal B: both peers 404 -> should bump no_peer_had_it=1
    # despite signal A having tripped skip_present (NOT skip_already_stored
    # — but the test still asserts the suppression bug is dead).
    httpx_mock.add_response(
        url=f"http://peer-a.example/v1/share-recovery/sig-missing/{SELF_ADDR}",
        status_code=404,
    )
    httpx_mock.add_response(
        url=f"http://peer-b.example/v1/share-recovery/sig-missing/{SELF_ADDR}",
        status_code=404,
    )
    peers = [
        {"url": "http://peer-a.example", "uid": 1},
        {"url": "http://peer-b.example", "uid": 2},
    ]
    tally = await recover_missing_shares(
        signal_ids=["sig-already-have", "sig-missing"],
        share_store=store,
        peer_validators=peers,
        encryption_privkey=privkey,
        signer_address=SELF_ADDR,
    )
    assert tally.get("skip_present") == 1
    assert tally.get("peer_404") == 2
    assert tally.get("no_peer_had_it") == 1


@pytest.mark.asyncio
async def test_no_peer_had_it_fires_per_signal_with_skip_already_stored_race(
    keypair, store, httpx_mock, monkeypatch
):
    """v1701: simulate the skip_already_stored race for signal A,
    then verify signal B (all peers 404) still bumps no_peer_had_it.
    Pre-v1701 this case was the classic suppression bug: A's race
    poisoned the cumulative-tally check that gated B's bump."""
    privkey, pubkey = keypair
    share_y_bytes = (12345).to_bytes(32, "big")
    from djinn_validator.utils.crypto import Share

    # peer for sig-A returns a valid blob; we'll force store.store
    # to raise "already stored" to simulate the race ordering.
    httpx_mock.add_response(
        url=f"http://peer-a.example/v1/share-recovery/sig-A/{SELF_ADDR}",
        json={
            "signal_id": "sig-A",
            "target_address": SELF_ADDR,
            "share_x": 7,
            "share_ciphertext": _seal(pubkey, share_y_bytes),
            "index_ciphertext": "",
            "shamir_threshold": 2,
        },
    )
    httpx_mock.add_response(
        url=f"http://peer-a.example/v1/share-recovery/sig-B/{SELF_ADDR}",
        status_code=404,
    )

    real_store = store.store

    def race_store(*args, **kwargs):
        sid = kwargs.get("signal_id") or args[0]
        if sid == "sig-A":
            raise ValueError("already stored")
        return real_store(*args, **kwargs)

    monkeypatch.setattr(store, "store", race_store)

    peers = [{"url": "http://peer-a.example", "uid": 1}]
    tally = await recover_missing_shares(
        signal_ids=["sig-A", "sig-B"],
        share_store=store,
        peer_validators=peers,
        encryption_privkey=privkey,
        signer_address=SELF_ADDR,
    )
    assert tally.get("skip_already_stored") == 1, (
        "sig-A should hit skip_already_stored race"
    )
    assert tally.get("no_peer_had_it") == 1, (
        "sig-B should still bump no_peer_had_it; pre-v1701 was suppressed"
    )
    assert tally.get("peer_404") == 1
