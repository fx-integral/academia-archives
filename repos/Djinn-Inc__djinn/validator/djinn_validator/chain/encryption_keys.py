"""Per-validator x25519 encryption keypair for share recovery.

Generated once on first startup, persisted in the validator's data dir.
Used by the genius client to encrypt each validator's Shamir share with
NaCl box, so peer-forwarding can hold the encrypted blob without
decrypt capability. See project_share_recovery_design_2026_05_03.md.
"""

from __future__ import annotations

import os
from pathlib import Path

import structlog
from nacl.public import PrivateKey, PublicKey, SealedBox

log = structlog.get_logger()

KEY_FILENAME = "encryption_key.bin"
KEY_BYTES = 32


def load_or_generate_keypair(data_dir: Path) -> tuple[bytes, bytes]:
    """Load the validator's x25519 keypair from data_dir, generating one on first run.

    Returns (privkey_bytes, pubkey_bytes), each 32 bytes.

    The privkey file is stored at data_dir/encryption_key.bin with mode 0600.
    The pubkey is derived from the privkey at load time (no separate file).
    """
    data_dir.mkdir(parents=True, exist_ok=True)
    key_path = data_dir / KEY_FILENAME

    if key_path.exists():
        privkey_bytes = key_path.read_bytes()
        if len(privkey_bytes) != KEY_BYTES:
            raise RuntimeError(f"encryption_key.bin at {key_path} is {len(privkey_bytes)} bytes, expected {KEY_BYTES}")
        privkey = PrivateKey(privkey_bytes)
        pubkey_bytes = bytes(privkey.public_key)
        log.info("encryption_key_loaded", path=str(key_path), pubkey=pubkey_bytes.hex())
        return privkey_bytes, pubkey_bytes

    privkey = PrivateKey.generate()
    privkey_bytes = bytes(privkey)
    pubkey_bytes = bytes(privkey.public_key)
    key_path.write_bytes(privkey_bytes)
    os.chmod(key_path, 0o600)
    log.info("encryption_key_generated", path=str(key_path), pubkey=pubkey_bytes.hex())
    return privkey_bytes, pubkey_bytes


def pubkey_to_bytes32(pubkey_bytes: bytes) -> bytes:
    """Convert a 32-byte x25519 pubkey to the bytes32 format expected by OV.setEncryptionPubkey."""
    if len(pubkey_bytes) != KEY_BYTES:
        raise ValueError(f"pubkey must be {KEY_BYTES} bytes, got {len(pubkey_bytes)}")
    return pubkey_bytes


def encrypt_sealed_box(receiver_pubkey: bytes, plaintext: bytes) -> bytes:
    """Encrypt plaintext to receiver_pubkey via NaCl SealedBox (libsodium crypto_box_seal).

    Anonymous: no sender identity required. Ciphertext includes an ephemeral
    sender pubkey, so a single-shot decrypt with the receiver's privkey suffices.
    Used by tests and any server-side helper that needs to round-trip the
    primitive (the genius client is in JS/TS with libsodium-wrappers).
    """
    if len(receiver_pubkey) != KEY_BYTES:
        raise ValueError(f"receiver_pubkey must be {KEY_BYTES} bytes, got {len(receiver_pubkey)}")
    box = SealedBox(PublicKey(receiver_pubkey))
    return bytes(box.encrypt(plaintext))


def decrypt_sealed_box(receiver_privkey: bytes, ciphertext: bytes) -> bytes:
    """Decrypt a SealedBox ciphertext using the receiver's x25519 privkey.

    Raises nacl.exceptions.CryptoError on tamper / wrong-key / corrupt input.
    Validators call this on their own bundle entry after a storeShareBundle
    request to recover the plaintext Shamir share_y bytes.
    """
    if len(receiver_privkey) != KEY_BYTES:
        raise ValueError(f"receiver_privkey must be {KEY_BYTES} bytes, got {len(receiver_privkey)}")
    box = SealedBox(PrivateKey(receiver_privkey))
    return box.decrypt(ciphertext)
