import { describe, it, expect } from "vitest";
import nacl from "tweetnacl";
import {
  bigIntToBytes32,
  bytes32ToBigInt,
  bytesToHex,
  hexToBytes32,
  isZeroPubkey,
  sealedBoxDecrypt,
  sealedBoxEncrypt,
  ShareCryptoError,
} from "@/lib/share-crypto";

describe("share-crypto", () => {
  it("sealed box round-trips with a fresh keypair", () => {
    const kp = nacl.box.keyPair();
    // Use a plain Uint8Array literal, not TextEncoder().encode(), because
    // jsdom's TextEncoder returns a Uint8Array from a different realm and
    // tweetnacl's `instanceof Uint8Array` check rejects cross-realm arrays.
    const plaintext = new Uint8Array([0x73, 0x68, 0x61, 0x72, 0x65, 0x2d, 0x66, 0x69, 0x78]);
    const ct = sealedBoxEncrypt(kp.publicKey, plaintext);
    const recovered = sealedBoxDecrypt(kp.publicKey, kp.secretKey, ct);
    expect(recovered).toEqual(plaintext);
  });

  it("sealed box ciphertext is unique per call (ephemeral keypair)", () => {
    const kp = nacl.box.keyPair();
    const plaintext = new Uint8Array([1, 2, 3, 4]);
    const ct1 = sealedBoxEncrypt(kp.publicKey, plaintext);
    const ct2 = sealedBoxEncrypt(kp.publicKey, plaintext);
    expect(ct1).not.toEqual(ct2);
  });

  it("decryption with wrong privkey throws", () => {
    const kp1 = nacl.box.keyPair();
    const kp2 = nacl.box.keyPair();
    const ct = sealedBoxEncrypt(kp1.publicKey, new Uint8Array([9, 9, 9]));
    expect(() => sealedBoxDecrypt(kp1.publicKey, kp2.secretKey, ct)).toThrow(ShareCryptoError);
  });

  it("rejects pubkey of wrong length", () => {
    expect(() => sealedBoxEncrypt(new Uint8Array(16), new Uint8Array(4))).toThrow(ShareCryptoError);
  });

  it("hexToBytes32 round-trips", () => {
    const hex = "ab".repeat(32);
    const bytes = hexToBytes32(hex);
    expect(bytes).toHaveLength(32);
    expect(bytesToHex(bytes)).toBe(hex);
  });

  it("hexToBytes32 accepts 0x prefix", () => {
    const hex = "0x" + "cd".repeat(32);
    const bytes = hexToBytes32(hex);
    expect(bytes).toHaveLength(32);
  });

  it("hexToBytes32 rejects wrong length", () => {
    expect(() => hexToBytes32("ab")).toThrow(ShareCryptoError);
  });

  it("bigIntToBytes32 round-trips", () => {
    const value = 0x1234567890abcdefn;
    const bytes = bigIntToBytes32(value);
    expect(bytes).toHaveLength(32);
    expect(bytes32ToBigInt(bytes)).toBe(value);
  });

  it("bigIntToBytes32 handles zero", () => {
    const bytes = bigIntToBytes32(0n);
    expect(bytes).toEqual(new Uint8Array(32));
    expect(bytes32ToBigInt(bytes)).toBe(0n);
  });

  it("bigIntToBytes32 rejects values exceeding 256 bits", () => {
    const tooBig = 1n << 256n;
    expect(() => bigIntToBytes32(tooBig)).toThrow(ShareCryptoError);
  });

  it("isZeroPubkey detects zero", () => {
    expect(isZeroPubkey(new Uint8Array(32))).toBe(true);
    const nonZero = new Uint8Array(32);
    nonZero[31] = 1;
    expect(isZeroPubkey(nonZero)).toBe(false);
  });

  it("isZeroPubkey rejects wrong-length input as 'not zero pubkey'", () => {
    expect(isZeroPubkey(new Uint8Array(16))).toBe(false);
  });
});
