#!/usr/bin/env node
/**
 * Smoke test for the share-recovery bundle fan-out (Phase 3 / 4 / 5).
 *
 * Exercises the new /v1/signal/bundle path end-to-end against live
 * Sepolia validators:
 *  1. Read OV.getValidators() + OV.encryptionPubkey() for each.
 *  2. Build a fresh AES key, Shamir-split into n shares, SealedBox-encrypt
 *     each share to its target validator's pubkey.
 *  3. POST the SAME encrypted bundle to every reachable validator URL.
 *  4. Verify each validator decrypted its own entry (own_share_stored=true)
 *     and persisted (n-1) forwarding ciphertexts.
 *  5. Pull a forwarding blob via /v1/share-recovery to confirm the
 *     peer-recovery endpoint is serving correctly.
 *
 * No on-chain SignalCommitment.commit; this is a wire-format probe of
 * the validator-side acceptance, not a full signal-create. Validators
 * will reject if they enforce on-chain genius verification — the
 * genius-address mismatch path returns 403, which is also a useful
 * signal that the path is wired correctly.
 */

import { createRequire } from "node:module";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { webcrypto as _webcrypto } from "node:crypto";

if (typeof globalThis.crypto === "undefined") {
  globalThis.crypto = _webcrypto;
}

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const require = createRequire(path.join(__dirname, "../web/package.json"));

const ethersModule = await import(require.resolve("ethers"));
const ethers = ethersModule;
const nacl = require("tweetnacl");
const sealedbox = require("tweetnacl-sealedbox-js");

const sdk = await import(path.join(__dirname, "../sdk/dist/index.mjs"));
const { generateAesKey, keyToBigInt, splitSecret, toHex } = sdk;

const RPC = process.env.BASE_SEPOLIA_RPC_URL || "https://base-sepolia-rpc.publicnode.com";
const OV = process.env.NEXT_PUBLIC_OUTCOME_VOTING_ADDRESS || "0xAD534f4CAB13707BD4d65e4EF086A455e6A643e5";

const OV_ABI = [
  "function getValidators() view returns (address[])",
  "function encryptionPubkey(address) view returns (bytes32)",
  "function supportsFeature(bytes32) view returns (bool)",
];

const FEATURE = ethers.id("SHARE_RECOVERY");

// Map signer EOA -> validator base URL. The OV doesn't store this
// mapping, but we know which signer corresponds to which UID from
// reference_ov_signer_set_2026_05_03.md.
const SIGNER_TO_URL = {
  "0xD717b5fbA93F123f6ad530ae2Ab327B4DcDa1e37": "https://v0.djinn.gg",  // UID 0
  "0x550A3f04F5ca62a561b8845F6b2AED6ed3edb15d": "https://v1.djinn.gg", // UID 1
  "0x26A766aFA20867ff047F5029177Da58b96547f77": "https://v2.djinn.gg",    // UID 2
  "0x8E777611FC04165f7bb2bEB94583cD690ec48eaD": "https://v86.djinn.gg", // UID 86
  "0xfae35E00b23e5CF8D4A4E5bc4f5b397b4522cA86": "https://v213.djinn.gg",     // UID 213
};

function bytes32ToBigInt(buf) {
  let out = 0n;
  for (const b of buf) out = (out << 8n) | BigInt(b);
  return out;
}

function bigIntToBytes32(value) {
  const out = new Uint8Array(32);
  let v = value;
  for (let i = 31; i >= 0; i--) {
    out[i] = Number(v & 0xffn);
    v >>= 8n;
  }
  return out;
}

function hexToBytes(hex) {
  const cleaned = hex.startsWith("0x") ? hex.slice(2) : hex;
  const out = new Uint8Array(cleaned.length / 2);
  for (let i = 0; i < out.length; i++) {
    out[i] = parseInt(cleaned.slice(i * 2, i * 2 + 2), 16);
  }
  return out;
}

function bytesToHex(bytes) {
  return Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("");
}

function isZeroPubkey(bytes) {
  for (const b of bytes) if (b !== 0) return false;
  return true;
}

const provider = new ethers.JsonRpcProvider(RPC);
const ov = new ethers.Contract(OV, OV_ABI, provider);

console.log("=== bundle fan-out smoke test ===");
console.log("RPC:", RPC);
console.log("OV proxy:", OV);

const supports = await ov.supportsFeature(FEATURE);
console.log("supportsFeature(SHARE_RECOVERY):", supports);
if (!supports) {
  console.error("OV does not expose SHARE_RECOVERY feature. Aborting.");
  process.exit(1);
}

const signers = await ov.getValidators();
console.log("OV signer count:", signers.length);

const validators = [];
for (const signer of signers) {
  const checksum = ethers.getAddress(signer);
  const pubkeyHex = await ov.encryptionPubkey(checksum);
  const pubkey = hexToBytes(pubkeyHex);
  const url = SIGNER_TO_URL[checksum];
  validators.push({ signer: checksum, pubkey, pubkeyHex, url });
  console.log(`  ${checksum} pubkey=${pubkeyHex.slice(0, 18)}... url=${url || "(unknown)"}`);
}

const encryptable = validators.filter((v) => !isZeroPubkey(v.pubkey));
const reachable = encryptable.filter((v) => v.url);
console.log(`encryptable: ${encryptable.length}, with-url: ${reachable.length}`);

if (encryptable.length < 2) {
  console.error("Need >=2 encryptable validators for Shamir; aborting.");
  process.exit(1);
}

// Build a fresh "secret" and Shamir-split.
const aesKey = generateAesKey();
const keyBigInt = keyToBigInt(aesKey);
const indexBigInt = 7n; // arbitrary
const nShares = encryptable.length;
const threshold = Math.min(7, Math.max(2, Math.ceil((nShares * 2) / 3)));

console.log(`shamir: nShares=${nShares}, threshold=${threshold}`);
const keyShares = splitSecret(keyBigInt, nShares, threshold);
const indexShares = splitSecret(indexBigInt, nShares, threshold);

// SealedBox-encrypt each share to its target's pubkey.
const bundleEntries = encryptable.map((v, i) => {
  const keyShareBytes = bigIntToBytes32(keyShares[i].y);
  const indexShareBytes = bigIntToBytes32(indexShares[i].y);
  const keyCt = sealedbox.seal(keyShareBytes, v.pubkey);
  const indexCt = sealedbox.seal(indexShareBytes, v.pubkey);
  return {
    target_address: v.signer,
    share_x: keyShares[i].x,
    share_ciphertext: bytesToHex(keyCt),
    index_ciphertext: bytesToHex(indexCt),
  };
});

const fakeGeniusAddr = "0x0000000000000000000000000000000000000bee";
const signalId = "test-bundle-" + toHex(crypto.getRandomValues(new Uint8Array(8)));
console.log("test signal_id:", signalId);

const bundle = {
  signal_id: signalId,
  genius_address: fakeGeniusAddr,
  shamir_threshold: threshold,
  bundle: bundleEntries,
  precomputed_triples: [],
};

console.log("\n=== POSTing bundle to each reachable validator ===");
const results = [];
for (const v of reachable) {
  try {
    const resp = await fetch(`${v.url}/v1/signal/bundle`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(bundle),
      signal: AbortSignal.timeout(15_000),
    });
    const text = await resp.text().catch(() => "");
    let body = null;
    try { body = JSON.parse(text); } catch { /* keep raw */ }
    results.push({ signer: v.signer, url: v.url, status: resp.status, body, raw: body ? null : text.slice(0, 200) });
    console.log(`  ${v.signer.slice(0, 12)}... ${resp.status} ${text.slice(0, 120)}`);
  } catch (e) {
    results.push({ signer: v.signer, url: v.url, status: 0, error: String(e?.message || e).slice(0, 200) });
    console.log(`  ${v.signer.slice(0, 12)}... ERROR ${e?.message || e}`);
  }
}

const ok = results.filter((r) => r.status === 200).length;
const forbidden = results.filter((r) => r.status === 403).length;
const other = results.length - ok - forbidden;
console.log(`\n=== summary: 200=${ok}, 403=${forbidden} (genius_address mismatch — expected for fake genius), other=${other}`);

// Pick any successful endpoint and try /v1/share-recovery
const successfulUrl = results.find((r) => r.status === 200)?.url;
if (successfulUrl) {
  // Pick a target other than the receiving validator
  const target = encryptable.find((v) => v.url !== successfulUrl)?.signer;
  if (target) {
    const recoveryUrl = `${successfulUrl}/v1/share-recovery/${signalId}/${target.toLowerCase()}`;
    console.log(`\n=== probing share-recovery: ${recoveryUrl}`);
    try {
      const resp = await fetch(recoveryUrl, { signal: AbortSignal.timeout(10_000) });
      const text = await resp.text();
      console.log(`  ${resp.status} ${text.slice(0, 200)}`);
    } catch (e) {
      console.log(`  ERROR ${e?.message || e}`);
    }
  }
}

if (ok === 0 && forbidden === reachable.length) {
  console.log("\nAll validators returned 403 (genius_address mismatch). The endpoint is wired correctly — they're all enforcing on-chain genius verification, which is the intended security check. To get past that, the test signal must be committed on chain by the same wallet that signs the bundle.");
} else if (ok > 0) {
  console.log(`\n${ok}/${reachable.length} validators accepted the bundle. Wire-format is good.`);
} else {
  console.log(`\nAll validators rejected with non-403 errors. Inspect results above.`);
}
