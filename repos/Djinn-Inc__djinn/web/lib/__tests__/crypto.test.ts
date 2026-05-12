import { describe, it, expect, beforeEach } from "vitest";
import {
  BN254_PRIME,
  splitSecret,
  reconstructSecret,
  generateAesKey,
  encrypt,
  decrypt,
  keyToBigInt,
  bigIntToKey,
  toHex,
  fromHex,
  deriveMasterSeed,
  deriveMasterSeedTyped,
  deriveSignalKey,
  clearMasterSeedCache,
  KEY_DERIVATION_DOMAIN,
  KEY_DERIVATION_TYPES,
  KEY_DERIVATION_MESSAGE,
} from "../crypto";
import type { ShamirShare } from "../crypto";

// ---------------------------------------------------------------------------
// Shamir Secret Sharing tests
// ---------------------------------------------------------------------------

describe("Shamir Secret Sharing", () => {
  it("splits and reconstructs with all 10 shares", () => {
    const secret = 42n;
    const shares = splitSecret(secret, 10, 7);
    expect(shares.length).toBe(10);

    const recovered = reconstructSecret(shares);
    expect(recovered).toBe(secret);
  });

  it("reconstructs with exactly k=7 shares", () => {
    const secret = 123456789n;
    const shares = splitSecret(secret, 10, 7);

    // Use first 7
    const recovered = reconstructSecret(shares.slice(0, 7));
    expect(recovered).toBe(secret);
  });

  it("any 7-of-10 shares reconstruct correctly", () => {
    const secret = 999999n;
    const shares = splitSecret(secret, 10, 7);

    // Try several random 7-subsets
    const subsets = [
      [0, 1, 2, 3, 4, 5, 6],
      [3, 4, 5, 6, 7, 8, 9],
      [0, 2, 4, 5, 7, 8, 9],
      [1, 3, 5, 6, 7, 8, 9],
      [0, 1, 3, 4, 6, 8, 9],
    ];

    for (const subset of subsets) {
      const subShares = subset.map((i) => shares[i]);
      expect(reconstructSecret(subShares)).toBe(secret);
    }
  });

  it("6 shares do NOT reconstruct correctly (below threshold)", () => {
    const secret = 42n;
    const shares = splitSecret(secret, 10, 7);
    const recovered = reconstructSecret(shares.slice(0, 6));
    // With only 6 of 7 needed shares, the result should not match
    expect(recovered).not.toBe(secret);
  });

  it("works with BN254 prime-sized secrets", () => {
    const secret = BN254_PRIME - 1n;
    const shares = splitSecret(secret, 10, 7);
    const recovered = reconstructSecret(shares.slice(0, 7));
    expect(recovered).toBe(secret);
  });

  it("works with secret = 0", () => {
    const shares = splitSecret(0n, 10, 7);
    const recovered = reconstructSecret(shares.slice(0, 7));
    expect(recovered).toBe(0n);
  });

  it("works with secret = 1 (signal index encoding)", () => {
    const shares = splitSecret(1n, 10, 7);
    const recovered = reconstructSecret(shares.slice(0, 7));
    expect(recovered).toBe(1n);
  });

  it("throws if secret >= prime", () => {
    expect(() => splitSecret(BN254_PRIME, 10, 7)).toThrow();
    expect(() => splitSecret(BN254_PRIME + 1n, 10, 7)).toThrow();
  });

  it("shares have x values 1 through n", () => {
    const shares = splitSecret(42n, 10, 7);
    for (let i = 0; i < 10; i++) {
      expect(shares[i].x).toBe(i + 1);
    }
  });

  it("share y values are in [0, prime)", () => {
    const shares = splitSecret(42n, 10, 7);
    for (const s of shares) {
      expect(s.y).toBeGreaterThanOrEqual(0n);
      expect(s.y).toBeLessThan(BN254_PRIME);
    }
  });

  it("cross-validates with known Python output", () => {
    // A fixed polynomial f(x) = 5 + 3x + 7x^2 (mod BN254_PRIME) with k=3, n=5
    // f(0) = 5, f(1) = 15, f(2) = 39, f(3) = 77, f(4) = 129, f(5) = 195
    const knownShares: ShamirShare[] = [
      { x: 1, y: 15n },
      { x: 2, y: 39n },
      { x: 3, y: 77n },
    ];
    const recovered = reconstructSecret(knownShares);
    expect(recovered).toBe(5n);
  });
});

// ---------------------------------------------------------------------------
// AES-256-GCM tests
// ---------------------------------------------------------------------------

describe("AES-256-GCM", () => {
  it("generates a 32-byte key", () => {
    const key = generateAesKey();
    expect(key.length).toBe(32);
    expect(key).toBeInstanceOf(Uint8Array);
  });

  it("generated key is always within BN254 field", () => {
    // Run multiple times to exercise rejection sampling
    for (let i = 0; i < 20; i++) {
      const key = generateAesKey();
      const val = keyToBigInt(key);
      expect(val).toBeGreaterThanOrEqual(0n);
      expect(val).toBeLessThan(BN254_PRIME);
    }
  });

  it("encrypts and decrypts a string roundtrip", async () => {
    const key = generateAesKey();
    const plaintext = "Lakers -3.5 (-110)";
    const { ciphertext, iv } = await encrypt(plaintext, key);

    expect(typeof ciphertext).toBe("string");
    expect(typeof iv).toBe("string");
    expect(iv.length).toBe(24); // 12 bytes = 24 hex chars

    const decrypted = await decrypt(ciphertext, iv, key);
    expect(decrypted).toBe(plaintext);
  });

  it("encrypts JSON payload roundtrip", async () => {
    const key = generateAesKey();
    const payload = JSON.stringify({ realIndex: 3, pick: "Lakers -3.5 (-110)" });
    const { ciphertext, iv } = await encrypt(payload, key);
    const decrypted = await decrypt(ciphertext, iv, key);
    expect(JSON.parse(decrypted)).toEqual({ realIndex: 3, pick: "Lakers -3.5 (-110)" });
  });

  it("fails to decrypt with wrong key", async () => {
    const key1 = generateAesKey();
    const key2 = generateAesKey();
    const { ciphertext, iv } = await encrypt("secret", key1);

    await expect(decrypt(ciphertext, iv, key2)).rejects.toThrow("Decryption failed");
  });

  it("normalizes decrypt errors to generic message", async () => {
    const key = generateAesKey();
    // Tampered ciphertext
    await expect(decrypt("deadbeef", "aabbccdd11223344aabbccdd", key)).rejects.toThrow(
      "Decryption failed",
    );
  });

  it("different encryptions of same plaintext produce different ciphertext", async () => {
    const key = generateAesKey();
    const { ciphertext: c1, iv: iv1 } = await encrypt("hello", key);
    const { ciphertext: c2, iv: iv2 } = await encrypt("hello", key);

    // IVs should differ (random)
    expect(iv1).not.toBe(iv2);
    // Ciphertexts should also differ
    expect(c1).not.toBe(c2);
  });
});

// ---------------------------------------------------------------------------
// Key <-> bigint conversion tests
// ---------------------------------------------------------------------------

describe("Key conversion", () => {
  it("roundtrips key through bigint", () => {
    const key = generateAesKey();
    const asInt = keyToBigInt(key);
    expect(asInt).toBeGreaterThanOrEqual(0n);
    expect(asInt).toBeLessThan(BN254_PRIME);

    const back = bigIntToKey(asInt);
    expect(back).toEqual(key);
  });

  it("bigIntToKey produces 32 bytes", () => {
    const key = bigIntToKey(42n);
    expect(key.length).toBe(32);
    expect(key[31]).toBe(42);
  });

  it("keyToBigInt throws if key value exceeds BN254 field", () => {
    // A 32-byte key with all 0xFF bytes = 2^256 - 1, which exceeds BN254_PRIME
    const oversizedKey = new Uint8Array(32).fill(0xff);
    expect(() => keyToBigInt(oversizedKey)).toThrow("exceeds BN254 field");
  });

  it("keyToBigInt accepts key just below prime", () => {
    // BN254_PRIME - 1 should be accepted
    const val = BN254_PRIME - 1n;
    const key = bigIntToKey(val);
    expect(keyToBigInt(key)).toBe(val);
  });
});

// ---------------------------------------------------------------------------
// Hex helpers
// ---------------------------------------------------------------------------

describe("Hex helpers", () => {
  it("toHex converts bytes to hex string", () => {
    expect(toHex(new Uint8Array([0, 1, 255, 16]))).toBe("0001ff10");
  });

  it("fromHex converts hex string to bytes", () => {
    const bytes = fromHex("0001ff10");
    expect(Array.from(bytes)).toEqual([0, 1, 255, 16]);
  });

  it("roundtrips", () => {
    const original = new Uint8Array([10, 20, 30, 40, 50]);
    expect(fromHex(toHex(original))).toEqual(original);
  });

  it("fromHex rejects odd-length strings", () => {
    expect(() => fromHex("abc")).toThrow("even length");
  });

  it("fromHex rejects non-hex characters", () => {
    expect(() => fromHex("ghij")).toThrow("Invalid hex");
  });

  it("fromHex accepts empty string", () => {
    expect(fromHex("")).toEqual(new Uint8Array(0));
  });

  it("fromHex accepts uppercase hex", () => {
    const bytes = fromHex("AABB");
    expect(Array.from(bytes)).toEqual([0xaa, 0xbb]);
  });

  it("fromHex rejects oversized input", () => {
    const huge = "ab".repeat(70_000); // 140,000 chars > 131,072 limit
    expect(() => fromHex(huge)).toThrow("too large");
  });

  it("fromHex accepts input at max size boundary", () => {
    const atLimit = "ab".repeat(65_536); // 131,072 chars = exactly at limit
    const bytes = fromHex(atLimit);
    expect(bytes.length).toBe(65_536);
  });
});

// ---------------------------------------------------------------------------
// Full flow: AES key -> Shamir split -> reconstruct -> AES decrypt
// ---------------------------------------------------------------------------

describe("Full Shamir + AES flow", () => {
  it("encrypts with AES, splits key via Shamir, reconstructs and decrypts", async () => {
    const aesKey = generateAesKey();
    const plaintext = JSON.stringify({ realIndex: 5, pick: "Celtics +4.5" });

    // Encrypt
    const { ciphertext, iv } = await encrypt(plaintext, aesKey);

    // Split key
    const keyBigInt = keyToBigInt(aesKey);
    const shares = splitSecret(keyBigInt, 10, 7);

    // Take 7 shares and reconstruct
    const recovered = reconstructSecret(shares.slice(2, 9));
    const recoveredKey = bigIntToKey(recovered);

    // Decrypt
    const decrypted = await decrypt(ciphertext, iv, recoveredKey);
    expect(JSON.parse(decrypted)).toEqual({ realIndex: 5, pick: "Celtics +4.5" });
  });
});

// ---------------------------------------------------------------------------
// Deterministic wallet-derived signal keys
// ---------------------------------------------------------------------------

describe("deriveMasterSeed", () => {
  beforeEach(() => clearMasterSeedCache());
  const fakeSignature = "0x" + "ab".repeat(65); // 65-byte eth signature

  it("returns a 32-byte Uint8Array", async () => {
    const seed = await deriveMasterSeed(async () => fakeSignature);
    expect(seed).toBeInstanceOf(Uint8Array);
    expect(seed.length).toBe(32);
  });

  it("is deterministic — same signature produces same seed", async () => {
    const seed1 = await deriveMasterSeed(async () => fakeSignature);
    const seed2 = await deriveMasterSeed(async () => fakeSignature);
    expect(seed1).toEqual(seed2);
  });

  it("different signatures produce different seeds", async () => {
    const sigA = "0x" + "aa".repeat(65);
    const sigB = "0x" + "bb".repeat(65);
    const seedA = await deriveMasterSeed(async () => sigA);
    clearMasterSeedCache(); // clear so second call uses sigB
    const seedB = await deriveMasterSeed(async () => sigB);
    expect(seedA).not.toEqual(seedB);
  });

  it("calls signMessage with the correct fixed message", async () => {
    let capturedMsg = "";
    await deriveMasterSeed(async (msg) => {
      capturedMsg = msg;
      return fakeSignature;
    });
    expect(capturedMsg).toBe("djinn:signal-keys:v1");
  });
});

describe("deriveMasterSeedTyped (EIP-712)", () => {
  beforeEach(() => clearMasterSeedCache());
  const fakeSignature = "0x" + "cc".repeat(65);

  it("returns a 32-byte Uint8Array", async () => {
    const seed = await deriveMasterSeedTyped(async () => fakeSignature);
    expect(seed).toBeInstanceOf(Uint8Array);
    expect(seed.length).toBe(32);
  });

  it("is deterministic — same signature produces same seed", async () => {
    const seed1 = await deriveMasterSeedTyped(async () => fakeSignature);
    const seed2 = await deriveMasterSeedTyped(async () => fakeSignature);
    expect(seed1).toEqual(seed2);
  });

  it("different signatures produce different seeds", async () => {
    const sigA = "0x" + "dd".repeat(65);
    const sigB = "0x" + "ee".repeat(65);
    const seedA = await deriveMasterSeedTyped(async () => sigA);
    clearMasterSeedCache();
    const seedB = await deriveMasterSeedTyped(async () => sigB);
    expect(seedA).not.toEqual(seedB);
  });

  it("passes correct EIP-712 params to sign function", async () => {
    let capturedParams: any = null;
    await deriveMasterSeedTyped(async (params) => {
      capturedParams = params;
      return fakeSignature;
    });
    expect(capturedParams.domain).toEqual(KEY_DERIVATION_DOMAIN);
    expect(capturedParams.types).toEqual(KEY_DERIVATION_TYPES);
    expect(capturedParams.primaryType).toBe("KeyDerivation");
    expect(capturedParams.message).toEqual(KEY_DERIVATION_MESSAGE);
  });

  it("produces same seed as deriveMasterSeed when given same raw signature", async () => {
    const sig = "0x" + "ff".repeat(65);
    const seedTyped = await deriveMasterSeedTyped(async () => sig);
    clearMasterSeedCache();
    const seedLegacy = await deriveMasterSeed(async () => sig);
    // Both hash the same signature bytes, so seeds should match
    expect(seedTyped).toEqual(seedLegacy);
  });
});

describe("deriveSignalKey", () => {
  // Use a fixed seed for deterministic tests
  const fixedSeed = new Uint8Array(32);
  fixedSeed[0] = 42;
  fixedSeed[31] = 99;

  it("returns a 32-byte key", async () => {
    const key = await deriveSignalKey(fixedSeed, 1n);
    expect(key).toBeInstanceOf(Uint8Array);
    expect(key.length).toBe(32);
  });

  it("is deterministic — same seed + signalId produces same key", async () => {
    const key1 = await deriveSignalKey(fixedSeed, 123n);
    const key2 = await deriveSignalKey(fixedSeed, 123n);
    expect(key1).toEqual(key2);
  });

  it("different signalIds produce different keys", async () => {
    const keyA = await deriveSignalKey(fixedSeed, 1n);
    const keyB = await deriveSignalKey(fixedSeed, 2n);
    expect(keyA).not.toEqual(keyB);
  });

  it("different seeds produce different keys for same signalId", async () => {
    const seedB = new Uint8Array(32);
    seedB[0] = 99;
    const keyA = await deriveSignalKey(fixedSeed, 1n);
    const keyB = await deriveSignalKey(seedB, 1n);
    expect(keyA).not.toEqual(keyB);
  });

  it("derived key is always within BN254 field", async () => {
    for (let i = 0; i < 20; i++) {
      const key = await deriveSignalKey(fixedSeed, BigInt(i));
      const val = keyToBigInt(key);
      expect(val).toBeGreaterThanOrEqual(0n);
      expect(val).toBeLessThan(BN254_PRIME);
    }
  });

  it("works with large signalIds", async () => {
    const largeId = 2n ** 200n + 12345n;
    const key = await deriveSignalKey(fixedSeed, largeId);
    expect(key.length).toBe(32);
    const val = keyToBigInt(key);
    expect(val).toBeLessThan(BN254_PRIME);
  });
});

describe("Derived key encrypt/decrypt roundtrip", () => {
  beforeEach(() => clearMasterSeedCache());
  it("encrypts with derived key, decrypts with same derived key", async () => {
    const fakeSignature = "0x" + "cd".repeat(65);
    const seed = await deriveMasterSeed(async () => fakeSignature);
    const signalId = 42n;
    const key = await deriveSignalKey(seed, signalId);

    const payload = JSON.stringify({ realIndex: 3, pick: "Lakers -3.5 (-110)" });
    const { ciphertext, iv } = await encrypt(payload, key);

    // Re-derive the same key and decrypt
    const seed2 = await deriveMasterSeed(async () => fakeSignature);
    const key2 = await deriveSignalKey(seed2, signalId);
    const decrypted = await decrypt(ciphertext, iv, key2);
    expect(JSON.parse(decrypted)).toEqual({ realIndex: 3, pick: "Lakers -3.5 (-110)" });
  });

  it("different signalId cannot decrypt", async () => {
    const fakeSignature = "0x" + "cd".repeat(65);
    const seed = await deriveMasterSeed(async () => fakeSignature);
    const key1 = await deriveSignalKey(seed, 1n);
    const key2 = await deriveSignalKey(seed, 2n);

    const { ciphertext, iv } = await encrypt("secret data", key1);
    await expect(decrypt(ciphertext, iv, key2)).rejects.toThrow("Decryption failed");
  });

  it("derived key works with Shamir split/reconstruct", async () => {
    const fakeSignature = "0x" + "ef".repeat(65);
    const seed = await deriveMasterSeed(async () => fakeSignature);
    const key = await deriveSignalKey(seed, 100n);

    // Encrypt
    const { ciphertext, iv } = await encrypt("test payload", key);

    // Split key via Shamir
    const keyInt = keyToBigInt(key);
    const shares = splitSecret(keyInt, 10, 7);

    // Reconstruct from 7 shares
    const recovered = reconstructSecret(shares.slice(1, 8));
    const recoveredKey = bigIntToKey(recovered);

    // Decrypt with reconstructed key
    const decrypted = await decrypt(ciphertext, iv, recoveredKey);
    expect(decrypted).toBe("test payload");
  });
});
