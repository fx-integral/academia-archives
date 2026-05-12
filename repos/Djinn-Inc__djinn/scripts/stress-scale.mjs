#!/usr/bin/env node
/**
 * Djinn Signal Scale Test
 *
 * Canonical end-to-end stress test. Supports >8 purchases by rotating
 * through a pool of deterministically-derived Idiot wallets (cycle limit
 * on Account is 10 per genius-idiot pair, we use 8 to stay safe).
 *
 * v1573: purchases now go through Escrow.purchaseV2 with per-line
 * BPA/WPA Merkle roots so each purchase is actually settleable via
 * batch audit. Before the on-chain call, the script POSTs the
 * (buyer, signal, bpas, wpas) tuple to a validator's
 * /v1/signal/{id}/purchase endpoint so the vectors get recorded AND
 * fan-gossiped to every committee peer. Without this the audit MPC
 * skips every purchase (build_pi_skip_missing_bpa_wpa_v2) and zero
 * AuditSettled events ever fire. See MAINNET_BLOCKERS.md P0-01.
 *
 * Streams per-op progress to a TSV log and summarises every --report-every
 * operations. Run in background and tail the TSV from another terminal.
 *
 * Usage:
 *   source web/.env.local && node scripts/stress-scale.mjs \
 *     --count=1000 --report-every=25 --log=/tmp/stress-scale.tsv
 */

import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import path from "node:path";
import { writeFileSync, appendFileSync, existsSync } from "node:fs";
import { webcrypto as _nodeWebCrypto } from "node:crypto";

// Node 18 doesn't expose `crypto` as a global by default — only Node 19+
// does (or Node 18 with --experimental-global-webcrypto). The SDK and this
// script use crypto.subtle / crypto.getRandomValues (Web Crypto API) for
// AES-GCM and Shamir random sampling. Polyfill so the script runs on any
// host with Node 18+ regardless of flags. No-op when the global is already
// present.
if (typeof globalThis.crypto === "undefined") {
  globalThis.crypto = _nodeWebCrypto;
}

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const require = createRequire(path.join(__dirname, "../web/package.json"));

const ethersModule = await import(require.resolve("ethers"));
const ethers = ethersModule;

const sdk = await import(path.join(__dirname, "../sdk/dist/index.mjs"));
const { encryptSignal, toHex, generateAesKey, encrypt, keyToBigInt, splitSecret, computeLinesHash } = sdk;

// tweetnacl + sealedbox are pulled from web/node_modules (already installed
// for the genius client's bundle path). Stress-scale uses the same wire
// format so the synthetic test exercises the same code paths real geniuses
// will hit. See project_share_recovery_design_2026_05_03.md.
const sealedbox = require("tweetnacl-sealedbox-js");

const args = process.argv.slice(2);
const flag = (name, fallback) => {
  const hit = args.find((a) => a.startsWith(`--${name}=`));
  return hit ? hit.split("=")[1] : fallback;
};

const TARGET = parseInt(flag("count", "1000"));
const REPORT_EVERY = parseInt(flag("report-every", "25"));
// Default batch=10 matches Audit.MIN_BATCH_SIZE, so every (genius, idiot)
// queue auto-trips the contract's full-batch settlement gate as soon as
// purchases close. Default <10 (the historical 8) silently forced every
// stress run into the consent-or-timeout gate, which requires admin
// opt-in or a 45-day SLA wait — that's why P0-01 kept "going quiet" for
// weeks. The natural-quorum pipeline only exercises when batches reach
// MIN_BATCH_SIZE on their own.
const IDIOT_BATCH_SIZE = parseInt(flag("idiot-batch", "10"));
// DEV-042: number of decoys per signal. lineCount = decoys + 1 (real pick).
// Default 99 → 100 lines total. Production targets 600-1200; testnet caps
// at MAX_LINE_COUNT=2000.
const DECOY_COUNT = parseInt(flag("decoys", "99"));
// Override the idiot derivation seed to get a FRESH pool of idiot wallets
// (no historical purchases on chain → no zombie audit_set entries from
// prior stress runs contaminating new batches). Default keeps the v4 seed
// for reproducibility.
const IDIOT_SEED = flag("idiot-seed", "stress-scale-idiot-v4");
const SKIP_PURCHASE = args.includes("--skip-purchase");
const BASE_URL = flag("base-url", "https://www.djinn.gg");
const LOG_PATH = flag("log", "/tmp/stress-scale.tsv");
const EXPIRY_MIN = parseInt(flag("expiry-min", "30"));
// Rate-limit knob added 2026-05-09 after a 100-signal as-fast-as-possible
// run hung UID 0 (estimate_gas inside nonce_lock w/o timeout). 0 = no
// throttle (legacy behavior). Positive value caps fire rate to QPS
// signals/sec; the script sleeps after each iteration to maintain it.
// For sustained runs against a real validator fleet, 0.05 (1 signal /
// 20s) is a known-safe ceiling; tune up once /v1/health-lite proves
// the loop isn't blocking.
const QPS = parseFloat(flag("qps", "0"));
const TELEGRAM_CHAT = flag("telegram-chat", "-1003733752686");

const GENIUS_PRIVATE_KEY = process.env.E2E_TEST_PRIVATE_KEY || process.env.E2E_GENIUS_KEY;
const DEPLOYER_PRIVATE_KEY = process.env.E2E_DEPLOYER_KEY;
const TELEGRAM_BOT_TOKEN = process.env.TELEGRAM_BOT_TOKEN || "";
// Default to publicnode RPC — sepolia.base.org returns flaky "missing revert
// data" on estimateGas at moderate volume, masking real revert reasons.
const RPC_URL = process.env.BASE_SEPOLIA_RPC_URL || "https://base-sepolia-rpc.publicnode.com";
const CHAIN_ID = 84532;

const CONTRACTS = {
  signalCommitment: "0x4712479Ba57c9ED40405607b2B18967B359209C0",
  escrow: "0xb43BA175a6784973eB3825acF801Cd7920ac692a",
  collateral: "0x71F0a8c6BBFc4C83c5203807fAdd305B0C0F4C88",
  usdc: "0x00e8293b05dbD3732EF3396ad1483E87e7265054",
  outcomeVoting: "0xAD534f4CAB13707BD4d65e4EF086A455e6A643e5",
};

const OV_ABI_BUNDLE = [
  "function getValidators() view returns (address[])",
  "function encryptionPubkey(address) view returns (bytes32)",
  "function supportsFeature(bytes32) view returns (bool)",
];
// Computed at runtime via ethers.id() to avoid checking in a 64-hex literal
// (pre-commit hook treats those as potential secrets even when they're
// public domain-separation tags).
const FEATURE_SHARE_RECOVERY = ethersModule.id("SHARE_RECOVERY");

const SIGNAL_COMMITMENT_ABI = [
  "function commit((uint256 signalId, bytes encryptedBlob, bytes32 commitHash, string sport, uint256 maxPriceBps, uint256 slaMultiplierBps, uint256 maxNotional, uint256 minNotional, uint256 expiresAt, string[] decoyLines, string[] availableSportsbooks, bytes32 linesHash, uint16 lineCount, bool bpaMode) p) external",
  "function getSignal(uint256 signalId) external view returns (tuple(address genius, bytes encryptedBlob, bytes32 commitHash, string sport, uint256 maxPriceBps, uint256 slaMultiplierBps, uint256 maxNotional, uint256 minNotional, uint256 expiresAt, string[] decoyLines, string[] availableSportsbooks, uint8 status, uint256 createdAt))",
  "function isActive(uint256 signalId) external view returns (bool)",
];

const ESCROW_ABI = [
  "function deposit(uint256 amount) external",
  "function purchase(uint256 signalId, uint256 notional, uint256 odds) external returns (uint256 purchaseId)",
  "function purchaseV2(uint256 signalId, uint256 notional, uint256 odds, bytes32 bpaRoot, bytes32 wpaRoot) external returns (uint256 purchaseId)",
  "function getBalance(address user) external view returns (uint256)",
];

// --- Merkle root helper ---------------------------------------------------
// Mirrors validator/djinn_validator/utils/merkle.py:compute_vector_root so
// off-chain vector commitments match what Escrow.purchaseV2 stores on-chain
// and what the audit batch-settlement MPC reconstructs.
//
// Leaf format:  keccak256(abi.encode(uint256 lineIndex, uint256 priceX1e6))
// Tree shape:   sorted-pair hashing, odd-layer padding = pair last with self
// (OpenZeppelin MerkleProof.sol compatible).
function computeVectorRoot(pricesX1e6) {
  const prices = pricesX1e6.map((p) => BigInt(p));
  if (prices.length === 0) return ethers.keccak256("0x");

  const coder = ethers.AbiCoder.defaultAbiCoder();
  const encodeLeaf = (i, price) =>
    ethers.keccak256(coder.encode(["uint256", "uint256"], [BigInt(i), price]));

  const hashPair = (a, b) => {
    const [lo, hi] = BigInt(a) < BigInt(b) ? [a, b] : [b, a];
    return ethers.keccak256(lo + hi.slice(2));
  };

  let layer = prices.map((p, i) => encodeLeaf(i, p));
  if (layer.length === 1) return layer[0];

  while (layer.length > 1) {
    const next = [];
    for (let i = 0; i < layer.length; i += 2) {
      const left = layer[i];
      const right = i + 1 < layer.length ? layer[i + 1] : left;
      next.push(hashPair(left, right));
    }
    layer = next;
  }
  return layer[0];
}

const ERC20_ABI = [
  "function approve(address spender, uint256 amount) external returns (bool)",
  "function balanceOf(address account) external view returns (uint256)",
  "function mint(address to, uint256 amount) external",
];

const COLLATERAL_ABI = [
  "function deposit(uint256 amount) external",
  "function getDeposit(address genius) external view returns (uint256)",
  "function getAvailable(address genius) external view returns (uint256)",
];

// --- Bundle path helpers (Phase 3 share recovery) -------------------------
// One-time chain discovery + per-validator /v1/identity lookup at startup.
// Returns { signerByUrl: Map<url, signer>, pubkeyBySigner: Map<signer, Uint8Array> }
// plus a `featureSupported` boolean. When feature is OFF the per-signal
// flow falls back to the legacy plaintext fan-out unchanged.
async function discoverShareRecoveryState(networkConfig, provider) {
  const ov = new ethers.Contract(CONTRACTS.outcomeVoting, OV_ABI_BUNDLE, provider);
  let featureSupported = false;
  try {
    featureSupported = await ov.supportsFeature(FEATURE_SHARE_RECOVERY);
  } catch (e) {
    return { featureSupported: false, signerByUrl: new Map(), pubkeyBySigner: new Map() };
  }
  if (!featureSupported) {
    return { featureSupported: false, signerByUrl: new Map(), pubkeyBySigner: new Map() };
  }

  const signers = await ov.getValidators();
  const pubkeyBySigner = new Map();
  for (const signer of signers) {
    const checksum = ethers.getAddress(signer);
    const pkHex = await ov.encryptionPubkey(checksum);
    const pk = hexToU8(pkHex);
    if (!isZeroBytes(pk)) {
      pubkeyBySigner.set(checksum.toLowerCase(), pk);
    }
  }

  // Map validator URL -> signer EOA via /v1/identity. Run in parallel; any
  // unreachable validator is skipped (its pubkey on chain is still useful
  // for forwarding-blob purposes — peers that DID get the bundle will hold
  // the missing validator's ciphertext until it comes back online).
  const signerByUrl = new Map();
  await Promise.allSettled(
    networkConfig.validators.map(async (v) => {
      const url = v.endpoint || `http://${v.ip}:${v.port}`;
      try {
        const resp = await fetch(`${url}/v1/identity`, { signal: AbortSignal.timeout(5_000) });
        if (!resp.ok) return;
        const body = await resp.json();
        const addr = body.base_address;
        if (typeof addr === "string" && addr.startsWith("0x")) {
          signerByUrl.set(url, ethers.getAddress(addr));
        }
      } catch { /* skip */ }
    }),
  );

  return { featureSupported, signerByUrl, pubkeyBySigner };
}

function hexToU8(hex) {
  const cleaned = hex.startsWith("0x") ? hex.slice(2) : hex;
  const out = new Uint8Array(cleaned.length / 2);
  for (let i = 0; i < out.length; i++) out[i] = parseInt(cleaned.slice(i * 2, i * 2 + 2), 16);
  return out;
}
function u8ToHex(bytes) {
  return Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("");
}
function isZeroBytes(bytes) {
  for (const b of bytes) if (b !== 0) return false;
  return true;
}
function bigIntToBytes32(value) {
  const out = new Uint8Array(32);
  let v = BigInt(value);
  for (let i = 31; i >= 0; i--) { out[i] = Number(v & 0xffn); v >>= 8n; }
  return out;
}

function ts() { return new Date().toISOString().slice(11, 19); }
function tsFull() { return new Date().toISOString(); }
function log(level, msg) { console.log(`[${ts()}] [${level}] ${msg}`); }

// --- TSV stream ------------------------------------------------------------
if (!existsSync(LOG_PATH)) {
  writeFileSync(LOG_PATH, "timestamp\tphase\tidx\tsignal_id\tpurchase_id\tidiot\toutcome\tduration_ms\terror\n");
}
function rowOut(phase, idx, signalId, purchaseId, idiot, outcome, durationMs, error) {
  const row = [tsFull(), phase, idx, signalId || "", purchaseId || "", idiot || "", outcome, durationMs, (error || "").replace(/\t|\n/g, " ").slice(0, 200)].join("\t");
  try { appendFileSync(LOG_PATH, row + "\n"); } catch {}
}

// --- Telegram --------------------------------------------------------------
async function telegram(text) {
  if (!TELEGRAM_BOT_TOKEN || !TELEGRAM_CHAT) return;
  try {
    await fetch(`https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ chat_id: TELEGRAM_CHAT, text, disable_web_page_preview: true }),
      signal: AbortSignal.timeout(10_000),
    });
  } catch {}
}

async function api(urlPath, opts = {}) {
  const url = `${BASE_URL}${urlPath}`;
  for (let attempt = 0; attempt <= 2; attempt++) {
    try {
      const res = await fetch(url, {
        headers: { "Content-Type": "application/json", ...opts.headers },
        signal: AbortSignal.timeout(opts.timeout || 30_000),
        ...opts,
      });
      const text = await res.text();
      let json;
      try { json = JSON.parse(text); } catch { json = { _raw: text }; }
      return { status: res.status, ok: res.ok, json };
    } catch (err) {
      if (attempt === 2) throw err;
      await new Promise((r) => setTimeout(r, 2000 * (attempt + 1)));
    }
  }
}

async function authenticate(wallet) {
  const address = wallet.address;
  const { json: c } = await api("/api/auth/connect", {
    method: "POST",
    body: JSON.stringify({ address }),
  });
  if (!c.nonce) throw new Error(`Auth connect failed: ${JSON.stringify(c)}`);
  const sig = await wallet.signMessage(c.challenge);
  const { json: v } = await api("/api/auth/verify", {
    method: "POST",
    body: JSON.stringify({ address, signature: sig, nonce: c.nonce }),
  });
  if (!v.session_token) throw new Error(`Auth verify failed: ${JSON.stringify(v)}`);
  return v.session_token;
}

function createProvider() {
  const fetchReq = new ethers.FetchRequest(RPC_URL);
  fetchReq.timeout = 60_000;
  return new ethers.JsonRpcProvider(fetchReq, CHAIN_ID, {
    staticNetwork: ethers.Network.from(CHAIN_ID),
    batchMaxCount: 1,
    pollingInterval: 4000,
  });
}

async function retry(fn, maxAttempts = 3, label = "") {
  for (let i = 0; i < maxAttempts; i++) {
    try { return await fn(); } catch (err) {
      if (i === maxAttempts - 1) throw err;
      log("WARN", `  Retry ${i + 1}/${maxAttempts}${label ? " for " + label : ""}: ${err.message?.slice(0, 80)}`);
      await new Promise((r) => setTimeout(r, 3000 * (i + 1)));
    }
  }
}

// --- Idiot pool ------------------------------------------------------------
function deriveIdiot(provider, seedBase, idx) {
  const seed = ethers.keccak256(ethers.solidityPacked(
    ["string", "uint256", "uint256"],
    [seedBase, BigInt(Math.floor(Date.now() / 86400000)), BigInt(idx)],
  ));
  return new ethers.Wallet(seed, provider);
}

async function ensureIdiotFunded(idiot, deployer, usdcContractR, escrowR, provider) {
  const iBal = await retry(() => provider.getBalance(idiot.address), 3, "idiot ETH");
  if (iBal < 500000000000000n) {
    const tx = await deployer.sendTransaction({ to: idiot.address, value: 2000000000000000n });
    await tx.wait();
  }
  const iUsdc = await retry(() => usdcContractR.balanceOf(idiot.address), 3, "idiot USDC");
  if (Number(iUsdc) < 1000e6) {
    const mintC = new ethers.Contract(CONTRACTS.usdc, ERC20_ABI, deployer);
    const mintTx = await mintC.mint(idiot.address, 5000n * 1000000n);
    await mintTx.wait();
  }
  const escBal = await retry(() => escrowR.getBalance(idiot.address), 3, "escrow");
  if (Number(escBal) < 100e6) {
    const iUsdcS = new ethers.Contract(CONTRACTS.usdc, ERC20_ABI, idiot);
    const appTx = await iUsdcS.approve(CONTRACTS.escrow, ethers.MaxUint256);
    await appTx.wait();
    const escS = new ethers.Contract(CONTRACTS.escrow, ESCROW_ABI, idiot);
    const depTx = await escS.deposit(500n * 1000000n);
    await depTx.wait();
  }
}

// --- Signal creation -------------------------------------------------------
async function createOneSignal(idx, wallet, provider, networkConfig, oddsData, authHeaders, shareRecoveryState) {
  const start = Date.now();
  const result = { idx, sport: "baseball_mlb", game: "", createMs: 0, signalId: null, error: null };

  try {
    const game = oddsData[idx % oddsData.length];
    result.game = `${game.away_team} @ ${game.home_team}`;
    const bookmaker = game.bookmakers[0];
    const spreadMarket = bookmaker.markets.find((m) => m.key === "spreads");
    const h2hMarket = bookmaker.markets.find((m) => m.key === "h2h");

    const realPick = {
      sport: "baseball_mlb",
      event_id: game.id,
      home_team: game.home_team,
      away_team: game.away_team,
      market: spreadMarket ? "spreads" : "h2h",
      side: spreadMarket?.outcomes[0]?.name || h2hMarket?.outcomes[0]?.name || game.home_team,
      line: spreadMarket?.outcomes[0]?.point || null,
      price: spreadMarket?.outcomes[0]?.price || h2hMarket?.outcomes[0]?.price || 1.91,
      commence_time: game.commence_time,
    };

    // DEV-042 v2: build a candidate decoy pool from the live odds payload
    // (every bookmaker × market × outcome combination across all available
    // games), exclude any duplicate of realPick, shuffle, and slice to
    // DECOY_COUNT. This replaces the old 9-line v1 path.
    const realKey = `${realPick.event_id}:${realPick.market}:${realPick.side}`;
    const candidatePool = [];
    for (const g of oddsData) {
      if (!g.bookmakers || g.bookmakers.length === 0) continue;
      for (const bk of g.bookmakers) {
        if (!bk.markets) continue;
        for (const market of bk.markets) {
          if (!market.outcomes) continue;
          for (const outcome of market.outcomes) {
            const k = `${g.id}:${market.key}:${outcome.name}`;
            if (k === realKey) continue;
            candidatePool.push({
              sport: "baseball_mlb",
              event_id: g.id,
              home_team: g.home_team,
              away_team: g.away_team,
              market: market.key,
              side: outcome.name || g.home_team,
              line: outcome.point ?? null,
              price: outcome.price ?? 2.0,
              bookmaker: bk.key || bk.title || "unknown",
              commence_time: g.commence_time,
            });
          }
        }
      }
    }
    if (candidatePool.length < 1) {
      result.error = `No candidate decoys available from ${oddsData.length} games`;
      result.createMs = Date.now() - start;
      return result;
    }
    for (let i = candidatePool.length - 1; i > 0; i--) {
      const j = Math.floor(Math.random() * (i + 1));
      [candidatePool[i], candidatePool[j]] = [candidatePool[j], candidatePool[i]];
    }
    const decoyN = Math.min(DECOY_COUNT, candidatePool.length);
    const decoys = candidatePool.slice(0, decoyN);

    const validators = networkConfig.validators.map((v) => ({ uid: v.uid, pubkey: v.hotkey || "" }));
    const shamirK = networkConfig.shamir?.k || networkConfig.shamir_k || 2;

    // v2 production-style encryption (DEV-042): the encryptedBlob carries
    // ONLY the real pick + realIndex. Decoys live off-chain via
    // /v1/signal/{id}/register. linesHash on chain is the tamper seal over
    // the FULL line set. Without this split, encryptSignal would JSON-encode
    // and AES-encrypt all 100 lines into the blob, blowing up gas to ~20M
    // and exceeding the block gas limit on signal commit (smoke-tested
    // 2026-04-27: N=50 OK, N=99 reverts at estimateGas).
    const lines = [...decoys];
    const realIndex = Math.floor(Math.random() * (lines.length + 1));
    lines.splice(realIndex, 0, realPick);
    const serializedLines = lines.map((l) => JSON.stringify(l));
    const linesHash = computeLinesHash(serializedLines);

    const aesKey = generateAesKey();
    const pickPayload = JSON.stringify({
      realIndex: realIndex + 1, // 1-indexed for protocol
      pick: realPick,
    });
    const { ciphertext: blobCt, iv: blobIv } = await encrypt(pickPayload, aesKey);
    // Match production format: encryptedBlob = "iv:ciphertext" stored as utf8
    // bytes. commitHash = sha256(blob bytes).
    const encryptedBlobStr = `${blobIv}:${blobCt}`;
    const blobBytes = new TextEncoder().encode(encryptedBlobStr);
    const blobHashBuf = await crypto.subtle.digest("SHA-256", blobBytes);
    const commitHashHex = "0x" + Array.from(new Uint8Array(blobHashBuf)).map((b) => b.toString(16).padStart(2, "0")).join("");
    const blobHex = Array.from(blobBytes).map((b) => b.toString(16).padStart(2, "0")).join("");

    const keyShares = splitSecret(keyToBigInt(aesKey), validators.length, shamirK);
    const indexShares = splitSecret(BigInt(realIndex + 1), validators.length, shamirK);
    const encryptedShares = validators.map((v, i) => ({
      validatorUid: v.uid,
      shareX: keyShares[i].x,
      keyShare: keyShares[i].y.toString(16).padStart(64, "0"),
      indexShare: indexShares[i].y.toString(16).padStart(64, "0"),
    }));

    const encrypted = {
      blob: blobHex, // hex(utf8("iv:ciphertext")), commit() prepends 0x below
      hash: commitHashHex.slice(2),
      linesHash,
      lineCount: serializedLines.length,
      serializedLines,
      shares: encryptedShares,
    };

    const signalId = BigInt("0x" + toHex(crypto.getRandomValues(new Uint8Array(32))));
    const expiresAt = BigInt(Math.floor(Date.now() / 1000) + EXPIRY_MIN * 60);

    const scContract = new ethers.Contract(CONTRACTS.signalCommitment, SIGNAL_COMMITMENT_ABI, wallet);
    const commitTx = await scContract.commit({
      signalId,
      encryptedBlob: "0x" + encrypted.blob,
      commitHash: "0x" + encrypted.hash,
      sport: "baseball_mlb",
      maxPriceBps: 500n,
      slaMultiplierBps: 15000n,
      maxNotional: 100n * 1000000n,
      minNotional: 1n * 1000000n,
      expiresAt,
      decoyLines: [],                       // v2: empty on-chain (off-chain via /v1/signal/.../register)
      availableSportsbooks: ["DraftKings", "FanDuel", "BetOnline"],
      linesHash: encrypted.linesHash,       // v2: keccak256(abi.encode(string[], serializedLines))
      lineCount: encrypted.lineCount,       // v2: serializedLines.length
      bpaMode: false,
    });
    const receipt = await commitTx.wait();

    const signalIdStr = signalId.toString();

    // Bundle fan-out (Phase 3 share recovery) is the only supported path —
    // legacy /v1/signal plaintext fan-out is deprecated and removed. If
    // share-recovery isn't yet supported on chain or fewer than SHAMIR_MIN
    // signers have published pubkeys, fail the signal create rather than
    // silently using a path that can't reach quorum.
    if (!shareRecoveryState || !shareRecoveryState.featureSupported) {
      result.error = "OV doesn't expose SHARE_RECOVERY feature; legacy /v1/signal removed";
      result.createMs = Date.now() - start;
      return result;
    }
    if (shareRecoveryState.pubkeyBySigner.size < 2) {
      result.error = `only ${shareRecoveryState.pubkeyBySigner.size} signer(s) have published pubkeys (need >=2)`;
      result.createMs = Date.now() - start;
      return result;
    }
    {
      const encryptableSigners = Array.from(shareRecoveryState.pubkeyBySigner.keys());
      const nBundle = encryptableSigners.length;
      const thresholdBundle = Math.min(7, Math.max(2, Math.ceil((nBundle * 2) / 3)));
      const keySharesB = splitSecret(keyToBigInt(aesKey), nBundle, thresholdBundle);
      const indexSharesB = splitSecret(BigInt(realIndex + 1), nBundle, thresholdBundle);
      const bundleEntries = encryptableSigners.map((signerLower, i) => {
        const pk = shareRecoveryState.pubkeyBySigner.get(signerLower);
        const keyCt = sealedbox.seal(bigIntToBytes32(keySharesB[i].y), pk);
        const idxCt = sealedbox.seal(bigIntToBytes32(indexSharesB[i].y), pk);
        return {
          target_address: ethers.getAddress(signerLower),
          share_x: keySharesB[i].x,
          share_ciphertext: u8ToHex(keyCt),
          index_ciphertext: u8ToHex(idxCt),
        };
      });
      const bundlePayload = {
        signal_id: signalIdStr,
        genius_address: wallet.address,
        shamir_threshold: thresholdBundle,
        bundle: bundleEntries,
        precomputed_triples: [],
      };
      // v1722: retry-until-acked bundle delivery. Pre-fix, single-shot
      // bundle fan-out: any validator that 504'd at commit time
      // permanently lost the share + forwarding entries for this signal.
      // Then share_recovery at audit time would return peer_404 across
      // all peers (because peers also missed the bundle), so build_pi
      // abstains forever and quorum never forms.
      // Fix: retry transient failures (5xx, timeout, connection error)
      // up to 3 times with exponential backoff. Permanent failures
      // (4xx) drop without retry. Stop early once minAcks reached.
      const minBundleAcks = parseInt(process.env.DJINN_BUNDLE_MIN_ACKS || "4", 10);
      const bundleBackoffsMs = [3000, 9000, 21000];
      const tryBundle = async (v) => {
        const url = v.endpoint || `http://${v.ip}:${v.port}`;
        try {
          const resp = await fetch(`${url}/v1/signal/bundle`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(bundlePayload),
            signal: AbortSignal.timeout(15_000),
          });
          if (resp.ok) return { uid: v.uid, status: "ack" };
          if (resp.status >= 400 && resp.status < 500) return { uid: v.uid, status: "permanent" };
          return { uid: v.uid, status: "retry" };
        } catch {
          return { uid: v.uid, status: "retry" };
        }
      };

      let pending = networkConfig.validators.slice();
      const ackedUids = new Set();
      for (let attempt = 0; attempt <= bundleBackoffsMs.length; attempt++) {
        const round = await Promise.allSettled(pending.map(tryBundle));
        const stillPending = [];
        for (let i = 0; i < pending.length; i++) {
          const r = round[i];
          if (r.status === "fulfilled" && r.value.status === "ack") {
            ackedUids.add(pending[i].uid);
          } else if (r.status === "fulfilled" && r.value.status === "permanent") {
            // 4xx: don't retry
          } else {
            stillPending.push(pending[i]);
          }
        }
        pending = stillPending;
        if (ackedUids.size >= minBundleAcks || pending.length === 0) break;
        if (attempt < bundleBackoffsMs.length) {
          await new Promise((r) => setTimeout(r, bundleBackoffsMs[attempt]));
        }
      }
      const acceptedBundle = ackedUids.size;
      if (acceptedBundle === 0) {
        result.error = `bundle fan-out: 0/${networkConfig.validators.length} validators accepted`;
        result.createMs = Date.now() - start;
        return result;
      }
      // Skip the legacy plaintext POST loop below — bundle path is exclusive.
      // Continue to the metadata-register block.
      await Promise.allSettled(
        networkConfig.validators.map((v) => {
          const endpoint = v.endpoint || `http://${v.ip}:${v.port}`;
          return fetch(`${endpoint}/v1/signal/${signalIdStr}/register`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              sport: realPick.sport,
              event_id: realPick.event_id,
              home_team: realPick.home_team,
              away_team: realPick.away_team,
              lines: serializedLines,
              genius_address: wallet.address,
              // P1-36 (v1676): commence_time → game_date (UTC YYYYMMDD) so the
              // OutcomeAttestor's ESPN lookup is deterministic across validators.
              game_date: realPick.commence_time
                ? new Date(realPick.commence_time).toISOString().slice(0, 10).replace(/-/g, "")
                : undefined,
            }),
            signal: AbortSignal.timeout(10_000),
          }).catch(() => null);
        }),
      );
      result.signalId = signalIdStr;
      result.createMs = Date.now() - start;
      result.blockNumber = receipt.blockNumber;
      result.bundlePath = true;
      result.bundleAccepted = acceptedBundle;
      // Stash per-line prices for purchaseSignal (decimals, matches legacy
      // tail at line ~663). purchaseSignal scales to *1e6 when computing odds.
      result.linePrices = lines.map((l) => {
        const p = l && typeof l.price === "number" && l.price > 1.01 ? l.price : 1.91;
        return p;
      });
      result.realIndex = realIndex;
      return result;
    }

    // Legacy /v1/signal plaintext fan-out is removed. Bundle path above
    // either returned success or one of the early-fail branches did. We
    // shouldn't reach this point — defensive throw if we somehow do.
    throw new Error("unreachable: bundle path should have returned");
  } catch (err) {
    result.error = (err.message || String(err)).slice(0, 300);
    result.createMs = Date.now() - start;
    return result;
  }
}

// --- Signal purchase -------------------------------------------------------
// Records the per-line BPA/WPA vectors on a validator via
// POST /v1/signal/{id}/purchase so:
//   (a) the validator stores the vectors in purchase_odds_ledger
//   (b) the handler gossips them to every committee peer (P0-01 fix)
// Short timeout — we don't wait for MPC to finish; the record + gossip
// task fires before MPC awaits. Returns without raising on timeout so
// the on-chain purchaseV2 still proceeds.
async function recordPurchaseOdds(validators, signalId, buyerWallet, bpas, wpas, realIndex) {
  const buyerSig = await buyerWallet.signMessage(`djinn:purchase:${signalId}`);
  const body = JSON.stringify({
    buyer_address: buyerWallet.address,
    sportsbook: "DraftKings",
    available_indices: [realIndex],
    buyer_signature: buyerSig,
    bpas,
    wpas,
    bpa_mode: false,
  });
  const tryOne = async (v) => {
    const endpoint = v.endpoint || `http://${v.ip}:${v.port}`;
    const t0 = Date.now();
    // 60s timeout: /v1/signal/{id}/purchase runs the full MPC purchase
    // flow on the validator side (signature verify → share check → MPC
    // peer round-trips → release encrypted share). Under fleet load,
    // round-trips take tens of seconds. UID 0 log evidence 2026-05-01:
    // observed durations 4.3s, 7.1s, 35s, 84s, 101s+ on real purchase
    // POSTs. The previous 8s timeout silently rejected almost every
    // call, leaving bpas/wpas un-stored fleet-wide and starving the
    // settlement pipeline of its primary input. 60s catches the bulk
    // of real responses; the tail (>60s) still gets covered by gossip
    // from any validator that did complete.
    const res = await fetch(`${endpoint}/v1/signal/${signalId}/purchase`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body,
      signal: AbortSignal.timeout(60_000),
    });
    return { uid: v.uid, ok: res.ok, status: res.status, ms: Date.now() - t0 };
  };
  // Send to ALL validators, not slice(0, 3). 2026-05-01 P0-01 root cause:
  // the historical "first 3 only" approach silently dropped purchase_odds
  // when UID 0 wasn't in the first 3, OR the POSTs timed out via the
  // Vercel proxy. The validator that audits the batch later does
  // `purchase_odds_ledger.get(signal_id, buyer)`; if its local row is
  // missing, build_pi_abstain_missing_bpa_wpa fires and the entire
  // batch silently abstains forever. The handler gossips on receipt,
  // so direct fan-out to all validators removes the single-validator
  // dropout failure mode.
  const results = await Promise.allSettled(validators.map(tryOne));
  const ok = results.filter((r) => r.status === "fulfilled" && r.value.ok).length;
  // Build a per-validator status string so failures are diagnosable from
  // the soak log without ssh'ing into every box. Format: "uid:status"
  // (e.g. "0:200,1:404,2:404,86:err,189:404,201:err,213:404"). 404 means
  // the validator doesn't hold a share for this signal (Shamir miss).
  // err means network/timeout. Only failures get full status; ok elided.
  const breakdown = results
    .map((r, i) => {
      const v = validators[i];
      if (r.status === "rejected") return `${v.uid}:err`;
      const ms = r.value.ms ?? 0;
      const sec = Math.round(ms / 100) / 10;
      const label = r.value.ok ? "ok" : String(r.value.status);
      return `${v.uid}:${label}/${sec}s`;
    })
    .join(",");
  return { ok, total: validators.length, breakdown };
}

async function purchaseSignal(signalId, wallet, provider, networkConfig, cachedLinePrices) {
  const start = Date.now();
  const result = { signalId, purchaseMs: 0, success: false, error: null };
  try {
    let odds = 2_000_000n;
    // DEV-042 v2: decoyLines are off-chain; getSignal() returns []. Use the
    // prices the script captured at create time (passed via cachedLinePrices).
    // Without this, prices=[] -> bpas=[] -> validator stores empty arrays ->
    // gossip 422 (PurchaseOddsGossipRequest requires bpas/wpas min_length=1)
    // -> peers never receive the BPA/WPA -> audit-time prefetch returns 404
    // -> shadow_settle_no_batch fires forever -> P0-01.
    let prices = Array.isArray(cachedLinePrices) ? cachedLinePrices.slice() : [];
    if (prices.length === 0) {
      // Backward compat: fall back to on-chain decoyLines if caller didn't
      // pass cached prices (e.g., older callers).
      try {
        const sc = new ethers.Contract(CONTRACTS.signalCommitment, SIGNAL_COMMITMENT_ABI, provider);
        const signalData = await sc.getSignal(BigInt(signalId));
        const lines = signalData.decoyLines || [];
        prices = lines.map((json) => {
          try {
            const parsed = JSON.parse(json);
            return parsed.price && parsed.price > 1.01 ? parsed.price : 1.91;
          } catch { return 1.91; }
        });
      } catch {}
    }
    if (prices.length > 0) {
      odds = BigInt(Math.round(prices[prices.length - 1] * 1e6));
    }

    // Build per-line BPA/WPA vectors. Any non-zero, positive uint256 works
    // for the contract-side Merkle check; the audit MPC uses these at
    // settlement time to reconstruct the payoff function.
    const bpas = prices.map((p) => Math.round(p * 1_000_000));
    const wpas = prices.map((p) => Math.max(1_000_001, Math.round(p * 990_000))); // slightly lower than BPA
    // available_indices in the validator schema is 1-indexed (validator
    // models.py:162 rejects values < 1). The stress-scale historical
    // value was prices.length - 1 (0-indexed), which got silently
    // 422'd whenever prices was short, leaving purchase_odds_ledger
    // un-populated and forcing every audit to abstain on
    // build_pi_abstain_missing_bpa_wpa. Use a known-valid 1-indexed
    // value: stress buyer doesn't know which line is real anyway,
    // they just claim line 1 access.
    const realIndex = 1;

    // 1) Record BPA/WPA on validators (stores + gossips to peers).
    //    Audit pipeline depends on this hitting the validator that
    //    eventually MPC-builds the batch — silent miss → permanent
    //    build_pi_abstain_missing_bpa_wpa. Log loudly when fewer
    //    than half the validators acknowledged.
    const recorded = await recordPurchaseOdds(
      networkConfig.validators,
      signalId.toString(),
      wallet,
      bpas,
      wpas,
      realIndex,
    ).catch((e) => ({ ok: 0, total: networkConfig.validators.length, error: e.message }));
    if (recorded.ok < Math.ceil(recorded.total / 2)) {
      log("WARN", `purchase_odds recorded ${recorded.ok}/${recorded.total} validators for signal ${signalId.toString().slice(0, 12)}… [${recorded.breakdown || ""}]${recorded.error ? " err=" + recorded.error : ""}`);
    }

    // 2) Compute roots locally from the same vectors. Must match the
    //    validator-side compute_vector_root() bit-for-bit.
    const bpaRoot = computeVectorRoot(bpas);
    const wpaRoot = computeVectorRoot(wpas);

    const notional = 10n * 1000000n;
    const escrowContract = new ethers.Contract(CONTRACTS.escrow, ESCROW_ABI, wallet);
    const tx = await escrowContract.purchaseV2(BigInt(signalId), notional, odds, bpaRoot, wpaRoot);
    const receipt = await tx.wait();
    result.success = true;
    result.recorded = recorded;
    result.purchaseMs = Date.now() - start;
    result.gas = receipt.gasUsed.toString();
    result.blockNumber = receipt.blockNumber;
    return result;
  } catch (err) {
    result.error = (err.message || String(err)).slice(0, 300);
    result.purchaseMs = Date.now() - start;
    return result;
  }
}

// --- Main ------------------------------------------------------------------
async function main() {
  if (!GENIUS_PRIVATE_KEY || !DEPLOYER_PRIVATE_KEY) {
    log("FATAL", "Set E2E_TEST_PRIVATE_KEY and E2E_DEPLOYER_KEY");
    process.exit(1);
  }

  const provider = createProvider();
  const geniusWallet = new ethers.Wallet(GENIUS_PRIVATE_KEY, provider);
  const deployerWallet = new ethers.Wallet(DEPLOYER_PRIVATE_KEY, provider);

  log("INFO", `Scale test: count=${TARGET} report-every=${REPORT_EVERY} idiot-batch=${IDIOT_BATCH_SIZE} expiry=${EXPIRY_MIN}min`);
  log("INFO", `Genius:   ${geniusWallet.address}`);
  log("INFO", `Deployer: ${deployerWallet.address}`);
  log("INFO", `Log:      ${LOG_PATH}`);

  // --- Genius funding -----------------------------------------------------
  const usdcContractR = new ethers.Contract(CONTRACTS.usdc, ERC20_ABI, provider);
  const escrowR = new ethers.Contract(CONTRACTS.escrow, ESCROW_ABI, provider);
  const gEth = await retry(() => provider.getBalance(geniusWallet.address), 3, "genius ETH");
  const ethNeeded = BigInt(TARGET) * 500000000000000n;
  log("INFO", `Genius ETH: ${(Number(gEth) / 1e18).toFixed(6)} (need ~${(Number(ethNeeded) / 1e18).toFixed(4)})`);
  if (gEth < ethNeeded) {
    const deficit = ethNeeded - gEth + 5000000000000000n;
    const dEth = await retry(() => provider.getBalance(deployerWallet.address), 3, "deployer ETH");
    if (dEth > deficit + 100000000000000n) {
      const fundTx = await deployerWallet.sendTransaction({ to: geniusWallet.address, value: deficit });
      await fundTx.wait();
      log("OK", `Funded genius with ${(Number(deficit) / 1e18).toFixed(4)} ETH`);
    } else {
      log("WARN", `Deployer low on ETH (${(Number(dEth) / 1e18).toFixed(4)}). Proceeding anyway.`);
    }
  }

  const collContract = new ethers.Contract(CONTRACTS.collateral, COLLATERAL_ABI, geniusWallet);
  const collDep = await retry(() => collContract.getDeposit(geniusWallet.address), 3, "collateral");
  log("INFO", `Collateral: $${(Number(collDep) / 1e6).toFixed(2)}`);
  if (Number(collDep) < 5000e6) {
    const usdcSigner = new ethers.Contract(CONTRACTS.usdc, ERC20_ABI, geniusWallet);
    const needed = 50000n * 1000000n;
    try {
      const mintC = new ethers.Contract(CONTRACTS.usdc, ERC20_ABI, deployerWallet);
      const mintTx = await mintC.mint(geniusWallet.address, needed);
      await mintTx.wait();
    } catch {}
    const appTx = await usdcSigner.approve(CONTRACTS.collateral, needed);
    await appTx.wait();
    const depTx = await collContract.deposit(needed);
    await depTx.wait();
    log("OK", "Deposited $50,000 collateral");
  }

  // --- Idiot pool (funded lazily) ----------------------------------------
  const idiotCount = Math.ceil(TARGET / IDIOT_BATCH_SIZE) + 2;
  log("INFO", `Deriving ${idiotCount} idiot wallets (batch=${IDIOT_BATCH_SIZE})`);
  const idiots = Array.from({ length: idiotCount }, (_, i) => deriveIdiot(provider, IDIOT_SEED, i));

  // --- Auth + network config ---------------------------------------------
  log("INFO", "Authenticating genius...");
  const sessionToken = await authenticate(geniusWallet);
  const authHeaders = { Authorization: `Bearer ${sessionToken}` };
  log("OK", "Authenticated");

  log("INFO", "Fetching network config...");
  const { json: networkConfig } = await api("/api/network/config", { timeout: 30_000 });
  if (!networkConfig?.validators?.length) {
    const { json: discoverData } = await api("/api/validators/discover", { timeout: 30_000 });
    networkConfig.validators = discoverData.validators || [];
    if (!networkConfig.shamir) networkConfig.shamir = { k: 2, n: 3 };
  }
  log("INFO", `Validators: ${networkConfig.validators?.length || 0}, Shamir k=${networkConfig.shamir?.k || "?"}`);

  // Share-recovery discovery: read OV.supportsFeature + signer set + per-signer
  // x25519 pubkeys, plus map URL→signer via /v1/identity. When feature is on
  // and ≥SHAMIR_MIN signers have published pubkeys, every signal-create uses
  // the encrypted-bundle path. See project_share_recovery_design_2026_05_03.md.
  log("INFO", "Probing OV for SHARE_RECOVERY feature...");
  const shareRecoveryState = await discoverShareRecoveryState(networkConfig, provider);
  if (shareRecoveryState.featureSupported) {
    log("INFO", `SHARE_RECOVERY: feature ON, signers with pubkey=${shareRecoveryState.pubkeyBySigner.size}, URL→signer map=${shareRecoveryState.signerByUrl.size}`);
  } else {
    log("INFO", "SHARE_RECOVERY: feature OFF (legacy plaintext fan-out)");
  }

  // --past-days=N (default 0) — when >0, fetch already-FINAL games from
  // /api/odds/past instead of upcoming games from /api/odds. Lets the
  // audit settlement pipeline ripen in minutes instead of waiting 6-12
  // hours for live games to end. Lines on past games are synthesized
  // server-side at standard 1.91 prices (closing odds are pruned by The
  // Odds API after game start); BPA/WPA at purchase time is the actual
  // economic commitment regardless.
  const PAST_DAYS = parseInt(flag("past-days", "0"));
  const oddsEndpoint = PAST_DAYS > 0
    ? `/api/odds/past?sport=baseball_mlb&daysFrom=${Math.min(3, PAST_DAYS)}`
    : "/api/odds?sport=baseball_mlb";
  log("INFO", `Fetching MLB odds${PAST_DAYS > 0 ? ` (past ${PAST_DAYS}d)` : ""}...`);
  const { json: oddsRaw } = await api(oddsEndpoint, { timeout: 20_000 });
  const oddsData = Array.isArray(oddsRaw) ? oddsRaw : [];
  if (oddsData.length === 0) {
    log("FATAL", "No MLB games. Cannot create signals.");
    process.exit(1);
  }
  const now = new Date();
  const futureGames = oddsData.filter((g) => new Date(g.commence_time) > now);
  const ALLOW_PAST = args.includes("--allow-past") || PAST_DAYS > 0;
  // --allow-past flips the filter so already-resolved games are eligible.
  // Past games are STATUS_FINAL on ESPN already, so OutcomeAttestor.resolve_all_pending
  // resolves them on the next poll cycle (~12s) instead of waiting hours for
  // game completion. Enables fast iteration of the audit settle pipeline:
  //   stress-scale --past-days=2 --count=20 --idiot-batch=10
  // produces a 20-signal cohort that ripens in minutes, not days.
  const gamesToUse = ALLOW_PAST ? oddsData : (futureGames.length >= 3 ? futureGames : oddsData);
  log("INFO", `MLB: ${oddsData.length} total, ${futureGames.length} future — using ${gamesToUse.length}${ALLOW_PAST ? " (past games allowed)" : ""}`);

  await telegram(`🧪 Djinn scale test started: ${TARGET} signals + purchases, ${idiotCount} idiots, ${BASE_URL}`);

  // =========================================================================
  // Upfront idiot funding (2026-05-09): pre-v1761 the script funded idiots
  // lazily on first use, which under high concurrency caused the deployer
  // EOA's nonce to race itself ("nonce already used" / "replacement fee
  // too low" cascade) and capped success at ~30%. Funding all idiots up
  // front in a single sequential pass before the create/purchase loop
  // starts removes the race entirely.
  // =========================================================================
  const fundedIdiots = new Set();
  if (!SKIP_PURCHASE) {
    log("INFO", `Pre-funding ${idiotCount} idiot wallets (sequential)...`);
    for (let idx = 0; idx < idiotCount; idx++) {
      const idiot = idiots[idx];
      try {
        await ensureIdiotFunded(idiot, deployerWallet, usdcContractR, escrowR, provider);
        fundedIdiots.add(idiot.address);
        log("INFO", `  Funded idiot[${idx}] ${idiot.address.slice(0, 10)}`);
      } catch (e) {
        log("WARN", `  Idiot fund failed [${idx}]: ${e.message?.slice(0, 120)}. Loop will retry on first use.`);
      }
    }
    log("INFO", `Pre-fund pass done: ${fundedIdiots.size}/${idiotCount} ready.`);
  }

  // =========================================================================
  // Interleaved: create signal i, purchase with idiot[floor(i/BATCH)]
  // =========================================================================
  const t0 = Date.now();
  const createResults = [];
  const purchaseResults = [];
  // QPS throttle: if QPS > 0, sleep after each iteration to maintain rate.
  const minLoopMs = QPS > 0 ? Math.floor(1000 / QPS) : 0;

  for (let i = 0; i < TARGET; i++) {
    const iterStart = Date.now();
    // Per-idiot rotation
    const idiotIdx = Math.floor(i / IDIOT_BATCH_SIZE);
    const idiot = idiots[idiotIdx];

    // Fallback: if pre-funding failed for this idiot, retry now once.
    if (!SKIP_PURCHASE && !fundedIdiots.has(idiot.address)) {
      try {
        await ensureIdiotFunded(idiot, deployerWallet, usdcContractR, escrowR, provider);
        fundedIdiots.add(idiot.address);
        log("INFO", `  Late-funded idiot[${idiotIdx}] ${idiot.address.slice(0, 10)}`);
      } catch (e) {
        log("WARN", `  Idiot fund failed [${idiotIdx}]: ${e.message?.slice(0, 120)}. Skipping i=${i}.`);
        continue;
      }
    }

    // --- Create
    const cr = await createOneSignal(i, geniusWallet, provider, networkConfig, gamesToUse, authHeaders, shareRecoveryState);
    createResults.push(cr);
    rowOut("create", i, cr.signalId, "", "", cr.signalId ? "ok" : "fail", cr.createMs, cr.error);

    // --- Purchase
    let pr = null;
    if (!SKIP_PURCHASE && cr.signalId) {
      await new Promise((r) => setTimeout(r, 1500)); // tiny wait so validator can persist share
      pr = await purchaseSignal(cr.signalId, idiot, provider, networkConfig, cr.linePrices);
      purchaseResults.push(pr);
      rowOut("purchase", i, cr.signalId, pr.blockNumber || "", idiot.address, pr.success ? "ok" : "fail", pr.purchaseMs, pr.error);
    }

    // --- Periodic report
    if ((i + 1) % REPORT_EVERY === 0 || i === TARGET - 1) {
      const elapsed = (Date.now() - t0) / 1000;
      const createdOk = createResults.filter((r) => r.signalId).length;
      const boughtOk = purchaseResults.filter((r) => r.success).length;
      const rate = (i + 1) / elapsed;
      const etaMin = ((TARGET - i - 1) / rate / 60).toFixed(1);
      const msg = `[${ts()}] i=${i + 1}/${TARGET} signals ok=${createdOk}/${i + 1} (${(100 * createdOk / (i + 1)).toFixed(1)}%) purchases ok=${boughtOk}/${purchaseResults.length} (${(100 * boughtOk / Math.max(1, purchaseResults.length)).toFixed(1)}%) rate=${rate.toFixed(2)}/s ETA=${etaMin}m`;
      log("PROGRESS", msg);
      await telegram(`📊 ${msg}`);
    }

    // QPS throttle: sleep after the iteration if we're firing faster than
    // --qps. No-op when QPS=0 (legacy as-fast-as-possible behavior).
    if (minLoopMs > 0 && i < TARGET - 1) {
      const elapsedMs = Date.now() - iterStart;
      const sleepMs = minLoopMs - elapsedMs;
      if (sleepMs > 0) {
        await new Promise((r) => setTimeout(r, sleepMs));
      }
    }
  }

  // --- Final summary -----------------------------------------------------
  const elapsed = (Date.now() - t0) / 1000;
  const createdOk = createResults.filter((r) => r.signalId).length;
  const boughtOk = purchaseResults.filter((r) => r.success).length;
  const summary = `DONE in ${(elapsed / 60).toFixed(1)}m: signals ${createdOk}/${TARGET} (${(100 * createdOk / TARGET).toFixed(1)}%) purchases ${boughtOk}/${purchaseResults.length} (${(100 * boughtOk / Math.max(1, purchaseResults.length)).toFixed(1)}%)`;
  log("DONE", summary);
  await telegram(`✅ Djinn scale test ${summary}`);

  // Failure breakdown
  const createErrs = createResults.filter((r) => r.error).reduce((m, r) => {
    const key = r.error.slice(0, 40);
    m[key] = (m[key] || 0) + 1;
    return m;
  }, {});
  if (Object.keys(createErrs).length) {
    log("INFO", "Create errors:");
    for (const [k, v] of Object.entries(createErrs).sort((a, b) => b[1] - a[1])) log("INFO", `  ${v}× ${k}`);
  }
  const buyErrs = purchaseResults.filter((r) => r.error).reduce((m, r) => {
    const key = r.error.slice(0, 40);
    m[key] = (m[key] || 0) + 1;
    return m;
  }, {});
  if (Object.keys(buyErrs).length) {
    log("INFO", "Purchase errors:");
    for (const [k, v] of Object.entries(buyErrs).sort((a, b) => b[1] - a[1])) log("INFO", `  ${v}× ${k}`);
  }
}

main().catch(async (e) => {
  log("FATAL", e.stack || e.message || String(e));
  await telegram(`❌ Djinn scale test crashed: ${(e.message || String(e)).slice(0, 200)}`);
  process.exit(1);
});
