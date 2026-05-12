import { describe, it, expect } from "vitest";
import nacl from "tweetnacl";
import { buildShareBundle } from "@/lib/share-bundle";
import {
  bigIntToBytes32,
  bytes32ToBigInt,
  hexToBytes32,
  sealedBoxDecrypt,
} from "@/lib/share-crypto";
import type { OVValidatorPubkey } from "@/lib/encryption-pubkeys";

function fakeValidator(addrSuffix: string, pubkey: Uint8Array): OVValidatorPubkey {
  return {
    address: "0x" + addrSuffix.padStart(40, "0"),
    pubkey,
  };
}

function makeValidators(n: number): { entries: OVValidatorPubkey[]; keypairs: nacl.BoxKeyPair[] } {
  const keypairs = Array.from({ length: n }, () => nacl.box.keyPair());
  const entries = keypairs.map((kp, i) => fakeValidator((i + 1).toString(16).padStart(2, "0"), kp.publicKey));
  return { entries, keypairs };
}

describe("buildShareBundle", () => {
  it("produces one entry per validator with non-zero pubkey", () => {
    const { entries, keypairs } = makeValidators(5);
    const result = buildShareBundle({
      signalId: "s1",
      geniusAddress: "0xgenius",
      keyBigInt: 0xdeadbeefn,
      indexBigInt: 3n,
      validators: entries,
      shamirMin: 2,
      shamirMax: 7,
    });
    expect(result.bundle.bundle).toHaveLength(5);
    expect(result.skippedValidators).toHaveLength(0);
    expect(result.encryptableValidators).toHaveLength(5);
    expect(result.nShares).toBe(5);
    expect(result.effectiveThreshold).toBe(4);
    // Keep keypairs referenced so TypeScript doesn't elide makeValidators's tuple.
    expect(keypairs.length).toBe(5);
  });

  it("each validator can decrypt its own entry to recover its share_y", () => {
    const { entries, keypairs } = makeValidators(3);
    const keyBigInt = 0xcafe00n;
    const indexBigInt = 7n;
    const result = buildShareBundle({
      signalId: "s1",
      geniusAddress: "0xgenius",
      keyBigInt,
      indexBigInt,
      validators: entries,
      shamirMin: 2,
      shamirMax: 7,
    });
    for (let i = 0; i < entries.length; i++) {
      const entry = result.bundle.bundle[i];
      expect(entry.target_address).toBe(entries[i].address);
      const ct = hexToBytes32Hex(entry.share_ciphertext);
      const recoveredShareYBytes = sealedBoxDecrypt(keypairs[i].publicKey, keypairs[i].secretKey, ct);
      const recoveredShareY = bytes32ToBigInt(recoveredShareYBytes);
      // Validators only see their own share, not the secret. Sanity: the
      // recovered y is non-zero for a non-zero secret.
      expect(recoveredShareY > 0n).toBe(true);
    }
  });

  it("skips validators with zero pubkey but still builds a bundle if enough remain", () => {
    const { entries, keypairs } = makeValidators(4);
    // Zero out one validator's pubkey
    entries[1] = { ...entries[1], pubkey: new Uint8Array(32) };
    const result = buildShareBundle({
      signalId: "s1",
      geniusAddress: "0xgenius",
      keyBigInt: 100n,
      indexBigInt: 1n,
      validators: entries,
      shamirMin: 2,
      shamirMax: 7,
    });
    expect(result.encryptableValidators).toHaveLength(3);
    expect(result.skippedValidators).toHaveLength(1);
    expect(result.bundle.bundle).toHaveLength(3);
    expect(keypairs.length).toBe(4);
  });

  it("throws if too few validators have pubkeys", () => {
    const { entries } = makeValidators(2);
    entries[0] = { ...entries[0], pubkey: new Uint8Array(32) };
    entries[1] = { ...entries[1], pubkey: new Uint8Array(32) };
    expect(() =>
      buildShareBundle({
        signalId: "s1",
        geniusAddress: "0xgenius",
        keyBigInt: 1n,
        indexBigInt: 1n,
        validators: entries,
        shamirMin: 2,
        shamirMax: 7,
      }),
    ).toThrow(/below SHAMIR_MIN/);
  });

  it("computes threshold via clamp(ceil(2/3 n), MIN, MAX)", () => {
    const cases: Array<[n: number, want: number]> = [
      [3, 2],
      [4, 3],
      [6, 4],
      [9, 6],
      [10, 7], // capped at SHAMIR_MAX
    ];
    for (const [n, want] of cases) {
      const { entries } = makeValidators(n);
      const result = buildShareBundle({
        signalId: "s1",
        geniusAddress: "0xgenius",
        keyBigInt: 42n,
        indexBigInt: 1n,
        validators: entries,
        shamirMin: 2,
        shamirMax: 7,
      });
      expect(result.effectiveThreshold).toBe(want);
    }
  });
});

// Helper: hex string to Uint8Array (length-flexible, used for ciphertext).
function hexToBytes32Hex(hex: string): Uint8Array {
  const cleaned = hex.startsWith("0x") || hex.startsWith("0X") ? hex.slice(2) : hex;
  const out = new Uint8Array(cleaned.length / 2);
  for (let i = 0; i < out.length; i++) {
    out[i] = parseInt(cleaned.slice(i * 2, i * 2 + 2), 16);
  }
  return out;
}

// Silence unused-import warnings for re-exported helpers.
void bigIntToBytes32;
void hexToBytes32;
