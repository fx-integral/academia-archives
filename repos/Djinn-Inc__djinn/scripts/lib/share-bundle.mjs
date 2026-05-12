/**
 * Shared helper for .mjs test scripts: build + post the encrypted-share
 * bundle to /v1/signal/bundle on each OV signer.
 *
 * Migrates test scripts off the deprecated /v1/signal plaintext fan-out.
 * Mirrors web/lib/share-bundle.ts + share-crypto.ts + encryption-pubkeys.ts
 * but with no Next.js / React dependencies — pure node ESM + ethers + tweetnacl.
 *
 * Usage:
 *   import { buildAndDistributeBundle } from "./lib/share-bundle.mjs";
 *   const result = await buildAndDistributeBundle({
 *     provider, ovAddress, signalIdStr, geniusAddress,
 *     keyBigInt, indexBigInt, validators,
 *     shamirMin: 2, shamirMax: 7,
 *   });
 */

import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import path from "node:path";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const require = createRequire(path.join(__dirname, "../../web/package.json"));

const ethers = await import(require.resolve("ethers"));
const sealedboxMod = await import(require.resolve("tweetnacl-sealedbox-js"));
const sealedbox = sealedboxMod.default ?? sealedboxMod;

const OV_SHARE_RECOVERY_ABI = [
  "function getValidators() view returns (address[])",
  "function encryptionPubkey(address) view returns (bytes32)",
  "function supportsFeature(bytes32) view returns (bool)",
];

const FEATURE_SHARE_RECOVERY = ethers.id("SHARE_RECOVERY");

function hexToBytes32(hex) {
  const cleaned = hex.startsWith("0x") || hex.startsWith("0X") ? hex.slice(2) : hex;
  if (cleaned.length !== 64) {
    throw new Error(`expected 64 hex chars, got ${cleaned.length}`);
  }
  const out = new Uint8Array(32);
  for (let i = 0; i < 32; i++) {
    out[i] = parseInt(cleaned.slice(i * 2, i * 2 + 2), 16);
  }
  return out;
}

function bytesToHex(bytes) {
  return Array.from(bytes)
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");
}

function isZeroPubkey(bytes) {
  return bytes.every((b) => b === 0);
}

function bigIntToBytes32(n) {
  const out = new Uint8Array(32);
  let x = BigInt(n);
  for (let i = 31; i >= 0; i--) {
    out[i] = Number(x & 0xffn);
    x >>= 8n;
  }
  return out;
}

/**
 * Read OV signer set + their published x25519 encryption pubkeys.
 * Returns one entry per validator; pubkey is all-zero if unpublished.
 */
export async function fetchOVValidatorPubkeys(provider, ovAddress) {
  const ov = new ethers.Contract(ovAddress, OV_SHARE_RECOVERY_ABI, provider);
  const validators = await ov.getValidators();
  return Promise.all(
    validators.map(async (addr) => {
      const checksum = ethers.getAddress(addr);
      try {
        const hex = await ov.encryptionPubkey(checksum);
        return { address: checksum, pubkey: hexToBytes32(hex) };
      } catch {
        return { address: checksum, pubkey: new Uint8Array(32) };
      }
    }),
  );
}

/**
 * Returns true if the deployed OV implementation exposes share recovery.
 * False if reverted (older impl).
 */
export async function ovSupportsShareRecovery(provider, ovAddress) {
  const ov = new ethers.Contract(ovAddress, OV_SHARE_RECOVERY_ABI, provider);
  try {
    const value = await ov.supportsFeature(FEATURE_SHARE_RECOVERY);
    return !!value;
  } catch {
    return false;
  }
}

/**
 * Shamir secret share split. Mirrors sdk/src/crypto.ts splitSecret using
 * BN254 field prime. Requires shamirK >= 2.
 */
const BN254_PRIME = 21888242871839275222246405745257275088548364400416034343698204186575808495617n;

function modPow(base, exp, mod) {
  let result = 1n;
  base = ((base % mod) + mod) % mod;
  while (exp > 0n) {
    if (exp & 1n) result = (result * base) % mod;
    exp >>= 1n;
    base = (base * base) % mod;
  }
  return result;
}

function modInverse(a, mod) {
  return modPow(((a % mod) + mod) % mod, mod - 2n, mod);
}

function randBigInt(modulus) {
  const bytes = new Uint8Array(32);
  // Use crypto.getRandomValues if available, else node:crypto
  if (typeof crypto !== "undefined" && crypto.getRandomValues) {
    crypto.getRandomValues(bytes);
  } else {
    const nodeCrypto = require("node:crypto");
    nodeCrypto.randomFillSync(bytes);
  }
  let n = 0n;
  for (const b of bytes) n = (n << 8n) | BigInt(b);
  return n % modulus;
}

/**
 * Split a secret into n shares such that any k can reconstruct it.
 * Returns [{x, y}] where x is 1..n and y is in BN254 field.
 */
export function splitSecret(secret, n, k) {
  if (k < 2) throw new Error("Shamir threshold must be >= 2");
  if (k > n) throw new Error("Threshold cannot exceed share count");
  const coeffs = [BigInt(secret) % BN254_PRIME];
  for (let i = 1; i < k; i++) coeffs.push(randBigInt(BN254_PRIME));
  const shares = [];
  for (let x = 1; x <= n; x++) {
    let y = 0n;
    let xPow = 1n;
    const xBig = BigInt(x);
    for (const coeff of coeffs) {
      y = (y + coeff * xPow) % BN254_PRIME;
      xPow = (xPow * xBig) % BN254_PRIME;
    }
    shares.push({ x, y });
  }
  return shares;
}

/**
 * Build the encrypted-share bundle. For each OV signer with a published
 * pubkey, generate a Shamir share + SealedBox-encrypt to that signer's
 * pubkey. Returns the same bundle object that gets POSTed to every
 * validator (each finds its own entry by signer EOA).
 */
export function buildShareBundle(args) {
  const { signalId, geniusAddress, keyBigInt, indexBigInt, validators, shamirMin = 2, shamirMax = 7 } = args;

  const encryptable = validators.filter((v) => !isZeroPubkey(v.pubkey));
  const skipped = validators.filter((v) => isZeroPubkey(v.pubkey));

  const nShares = encryptable.length;
  if (nShares < shamirMin) {
    throw new Error(
      `Cannot build bundle: only ${nShares} validator(s) have published encryption pubkeys, ` +
        `below SHAMIR_MIN=${shamirMin}.`,
    );
  }

  const effectiveThreshold = Math.min(shamirMax, Math.max(shamirMin, Math.ceil((nShares * 2) / 3)));

  const keyShares = splitSecret(keyBigInt, nShares, effectiveThreshold);
  const indexShares = splitSecret(indexBigInt, nShares, effectiveThreshold);

  const entries = encryptable.map((v, i) => {
    const keyShareBytes = bigIntToBytes32(keyShares[i].y);
    const indexShareBytes = bigIntToBytes32(indexShares[i].y);
    const keyCiphertext = sealedbox.seal(keyShareBytes, v.pubkey);
    const indexCiphertext = sealedbox.seal(indexShareBytes, v.pubkey);
    return {
      target_address: v.address,
      share_x: keyShares[i].x,
      share_ciphertext: bytesToHex(keyCiphertext),
      index_ciphertext: bytesToHex(indexCiphertext),
    };
  });

  return {
    bundle: {
      signal_id: signalId,
      genius_address: geniusAddress,
      shamir_threshold: effectiveThreshold,
      bundle: entries,
    },
    encryptableValidators: encryptable,
    skippedValidators: skipped,
    effectiveThreshold,
    nShares,
  };
}

/**
 * Convenience: fetch pubkeys, build bundle, POST to every validator's
 * /v1/signal/bundle. Returns a per-validator result tally.
 *
 * `validators` is an array of {uid, endpoint} (HTTP base URL) entries
 * matching cfg.validators in the test scripts. Pubkeys are fetched from
 * chain via OV.encryptionPubkey() so the array doesn't need them inline.
 */
export async function buildAndDistributeBundle({
  provider,
  ovAddress,
  signalIdStr,
  geniusAddress,
  keyBigInt,
  indexBigInt,
  endpoints,
  shamirMin = 2,
  shamirMax = 7,
  precomputedTriples = [],
  fetchTimeoutMs = 20000,
}) {
  const validatorPubkeys = await fetchOVValidatorPubkeys(provider, ovAddress);
  const { bundle, effectiveThreshold, nShares, skippedValidators } = buildShareBundle({
    signalId: signalIdStr,
    geniusAddress,
    keyBigInt,
    indexBigInt,
    validators: validatorPubkeys,
    shamirMin,
    shamirMax,
  });

  const payload = { ...bundle, precomputed_triples: precomputedTriples };

  // POST the SAME bundle to every validator HTTP endpoint. Each finds
  // its own entry by matching its signer EOA and persists the rest as
  // forwarding blobs.
  const results = await Promise.allSettled(
    endpoints.map(async (ep) => {
      try {
        const resp = await fetch(`${ep.endpoint || ep.url || ep}/v1/signal/bundle`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
          signal: AbortSignal.timeout(fetchTimeoutMs),
        });
        if (!resp.ok) {
          const text = await resp.text().catch(() => "");
          return {
            uid: ep.uid ?? -1,
            success: false,
            reason: `${resp.status}: ${text.slice(0, 120)}`,
          };
        }
        const body = await resp.json().catch(() => ({}));
        return {
          uid: ep.uid ?? -1,
          success: true,
          ownStored: body.own_share_stored,
          forwardingCount: body.forwarding_count,
        };
      } catch (e) {
        return { uid: ep.uid ?? -1, success: false, reason: e.message?.slice(0, 120) ?? String(e) };
      }
    }),
  );

  return {
    payload,
    effectiveThreshold,
    nShares,
    skippedValidators,
    results: results.map((r) => (r.status === "fulfilled" ? r.value : { uid: -1, success: false, reason: r.reason?.message ?? "unknown" })),
  };
}
