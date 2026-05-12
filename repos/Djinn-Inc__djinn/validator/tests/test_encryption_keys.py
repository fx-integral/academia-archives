"""Tests for djinn_validator.chain.encryption_keys."""

from __future__ import annotations

import os

import pytest
from nacl.public import PrivateKey, PublicKey

from djinn_validator.chain.encryption_keys import (
    KEY_BYTES,
    KEY_FILENAME,
    load_or_generate_keypair,
    pubkey_to_bytes32,
)


def test_first_call_generates_new_keypair(tmp_path):
    privkey, pubkey = load_or_generate_keypair(tmp_path)
    assert len(privkey) == KEY_BYTES
    assert len(pubkey) == KEY_BYTES
    assert (tmp_path / KEY_FILENAME).exists()


def test_pubkey_derives_from_privkey(tmp_path):
    privkey, pubkey = load_or_generate_keypair(tmp_path)
    derived = bytes(PrivateKey(privkey).public_key)
    assert derived == pubkey


def test_second_call_loads_same_keypair(tmp_path):
    privkey1, pubkey1 = load_or_generate_keypair(tmp_path)
    privkey2, pubkey2 = load_or_generate_keypair(tmp_path)
    assert privkey1 == privkey2
    assert pubkey1 == pubkey2


def test_keypair_persists_across_separate_dirs(tmp_path):
    a = tmp_path / "a"
    b = tmp_path / "b"
    pk_a, pub_a = load_or_generate_keypair(a)
    pk_b, pub_b = load_or_generate_keypair(b)
    # Different data dirs => different keypairs
    assert pk_a != pk_b
    assert pub_a != pub_b


def test_key_file_has_restricted_permissions(tmp_path):
    load_or_generate_keypair(tmp_path)
    mode = (tmp_path / KEY_FILENAME).stat().st_mode & 0o777
    assert mode == 0o600, f"expected 0600, got {oct(mode)}"


def test_corrupt_key_file_raises(tmp_path):
    (tmp_path / KEY_FILENAME).write_bytes(b"\x00" * 16)  # wrong length
    with pytest.raises(RuntimeError, match="bytes, expected"):
        load_or_generate_keypair(tmp_path)


def test_pubkey_to_bytes32_roundtrip(tmp_path):
    _, pubkey = load_or_generate_keypair(tmp_path)
    encoded = pubkey_to_bytes32(pubkey)
    assert encoded == pubkey
    assert len(encoded) == 32


def test_pubkey_to_bytes32_rejects_wrong_length():
    with pytest.raises(ValueError, match="32 bytes"):
        pubkey_to_bytes32(b"\x00" * 16)


def test_keypair_is_valid_x25519(tmp_path):
    """Sanity: the saved privkey must be usable for NaCl box decryption."""
    from nacl.public import Box

    privkey_bytes, pubkey_bytes = load_or_generate_keypair(tmp_path)

    # Simulate a sender (genius) encrypting to our pubkey, then we decrypt.
    sender_priv = PrivateKey.generate()
    receiver_priv = PrivateKey(privkey_bytes)
    receiver_pub = PublicKey(pubkey_bytes)

    encrypt_box = Box(sender_priv, receiver_pub)
    plaintext = b"share fixture"
    ciphertext = encrypt_box.encrypt(plaintext)

    decrypt_box = Box(receiver_priv, sender_priv.public_key)
    recovered = decrypt_box.decrypt(ciphertext)
    assert recovered == plaintext
