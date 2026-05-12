/**
 * Sealed-box encryption helpers for share recovery (C+F design 2026-05-03).
 *
 * Each genius client per-validator-encrypts a Shamir share with NaCl SealedBox
 * (libsodium crypto_box_seal): anonymous, ephemeral-key encryption to the
 * target validator's published x25519 pubkey. Peer validators can hold the
 * ciphertext as a forwarding blob without decrypting it. The receiving
 * validator decrypts with its own x25519 privkey via pynacl SealedBox on
 * the Python side.
 *
 * See validator/djinn_validator/chain/encryption_keys.py for the Python
 * counterpart and project_share_recovery_design_2026_05_03.md for the
 * full design.
 */

import sealedbox from "tweetnacl-sealedbox-js";

export const X25519_PUBKEY_LEN = 32;

export class ShareCryptoError extends Error {}

/**
 * Encrypt a plaintext byte array to the target's x25519 pubkey via SealedBox.
 * Returns the ciphertext bytes (which include an ephemeral sender pubkey
 * and the encrypted+authenticated payload).
 */
export function sealedBoxEncrypt(receiverPubkey: Uint8Array, plaintext: Uint8Array): Uint8Array {
  if (receiverPubkey.length !== X25519_PUBKEY_LEN) {
    throw new ShareCryptoError(`receiverPubkey must be ${X25519_PUBKEY_LEN} bytes, got ${receiverPubkey.length}`);
  }
  return sealedbox.seal(plaintext, receiverPubkey);
}

/**
 * Decrypt a SealedBox ciphertext using the receiver's x25519 keypair.
 * Returns the recovered plaintext, or throws if tampered/wrong-key.
 *
 * Used only in tests on the JS side (validators decrypt server-side via pynacl).
 */
export function sealedBoxDecrypt(
  receiverPubkey: Uint8Array,
  receiverPrivkey: Uint8Array,
  ciphertext: Uint8Array,
): Uint8Array {
  if (receiverPubkey.length !== X25519_PUBKEY_LEN) {
    throw new ShareCryptoError(`receiverPubkey must be ${X25519_PUBKEY_LEN} bytes`);
  }
  if (receiverPrivkey.length !== X25519_PUBKEY_LEN) {
    throw new ShareCryptoError(`receiverPrivkey must be ${X25519_PUBKEY_LEN} bytes`);
  }
  const plaintext = sealedbox.open(ciphertext, receiverPubkey, receiverPrivkey);
  if (plaintext === null) {
    throw new ShareCryptoError("SealedBox decryption failed (tampered, wrong key, or corrupt ciphertext)");
  }
  return plaintext;
}

/**
 * Convert a hex-encoded bytes32 (with or without 0x prefix) to a 32-byte Uint8Array.
 * Useful for OV.encryptionPubkey() return values, which arrive as hex strings.
 */
export function hexToBytes32(hex: string): Uint8Array {
  const cleaned = hex.startsWith("0x") || hex.startsWith("0X") ? hex.slice(2) : hex;
  if (cleaned.length !== 64) {
    throw new ShareCryptoError(`expected 64 hex chars, got ${cleaned.length}`);
  }
  const out = new Uint8Array(32);
  for (let i = 0; i < 32; i++) {
    out[i] = parseInt(cleaned.slice(i * 2, i * 2 + 2), 16);
  }
  return out;
}

/**
 * Lower-case 0x-prefixed hex encoding of a byte array.
 */
export function bytesToHex(bytes: Uint8Array): string {
  return Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("");
}

/**
 * BN254 field element bigint (from sdk's splitSecret) -> 32-byte big-endian array.
 */
export function bigIntToBytes32(value: bigint): Uint8Array {
  if (value < 0n) throw new ShareCryptoError("bigIntToBytes32: negative not supported");
  const out = new Uint8Array(32);
  let v = value;
  for (let i = 31; i >= 0; i--) {
    out[i] = Number(v & 0xffn);
    v >>= 8n;
  }
  if (v > 0n) throw new ShareCryptoError("bigIntToBytes32: value exceeds 256 bits");
  return out;
}

/**
 * Inverse of bigIntToBytes32.
 */
export function bytes32ToBigInt(bytes: Uint8Array): bigint {
  if (bytes.length !== 32) throw new ShareCryptoError("bytes32ToBigInt requires 32 bytes");
  let out = 0n;
  for (const b of bytes) {
    out = (out << 8n) | BigInt(b);
  }
  return out;
}

/**
 * Treat a 32-byte buffer as "all zero" — i.e., the OV.encryptionPubkey()
 * sentinel value meaning the validator hasn't yet published a pubkey.
 */
export function isZeroPubkey(pubkey: Uint8Array): boolean {
  if (pubkey.length !== X25519_PUBKEY_LEN) return false;
  for (const b of pubkey) {
    if (b !== 0) return false;
  }
  return true;
}
