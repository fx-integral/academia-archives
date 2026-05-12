#!/usr/bin/env node
/**
 * UX Timing Test: measures real user-facing latency for signal creation and purchase.
 * Creates N signals, attempts N purchases, logs timing for every step.
 *
 * Usage: node scripts/ux-timing-test.mjs [--signals N] [--purchases N]
 */

import { ethers } from "ethers";
import crypto from "crypto";

// ─── Config ───────────────────────────────────────────────────────────
const RPC_URL = "https://sepolia.base.org";
const BASE_URL = process.env.LIVE_URL ?? "https://djinn.gg";

const ADDRESSES = {
  signalCommitment: "0x4712479Ba57c9ED40405607b2B18967B359209C0",
  escrow: "0xb43BA175a6784973eB3825acF801Cd7920ac692a",
  collateral: "0x71F0a8c6BBFc4C83c5203807fAdd305B0C0F4C88",
  account: "0x4546354Dd32a613B76Abf530F81c8359e7cE440B",
  usdc: "0x00e8293b05dbD3732EF3396ad1483E87e7265054",
};

const PRIVATE_KEY = process.env.E2E_TEST_PRIVATE_KEY || process.env.E2E_GENIUS_KEY || "";
if (!PRIVATE_KEY) {
  console.error("Set E2E_TEST_PRIVATE_KEY or E2E_GENIUS_KEY");
  process.exit(1);
}
const BUYER_KEY = process.env.E2E_BUYER_PRIVATE_KEY || "";

const args = process.argv.slice(2);
const NUM_SIGNALS = parseInt(args.find((a, i) => args[i - 1] === "--signals") || "5");
const NUM_PURCHASES = parseInt(args.find((a, i) => args[i - 1] === "--purchases") || "5");

// ─── ABIs ─────────────────────────────────────────────────────────────
const SIGNAL_ABI = [
  "function commit((uint256 signalId, bytes encryptedBlob, bytes32 commitHash, string sport, uint256 maxPriceBps, uint256 slaMultiplierBps, uint256 maxNotional, uint256 minNotional, uint256 expiresAt, string[] decoyLines, string[] availableSportsbooks, bytes32 linesHash, uint16 lineCount, bool bpaMode)) external",
  "function isActive(uint256 signalId) view returns (bool)",
];
const ESCROW_ABI = [
  "function deposit(uint256 amount) external",
  "function getBalance(address) view returns (uint256)",
  "function purchase(uint256 signalId, uint256 notional, uint256 odds) external",
];
const COLLATERAL_ABI = [
  "function deposit(uint256 amount) external",
  "function getAvailable(address) view returns (uint256)",
];
const USDC_ABI = [
  "function mint(address to, uint256 amount) external",
  "function balanceOf(address) view returns (uint256)",
  "function approve(address spender, uint256 amount) external returns (bool)",
];

// ─── Helpers ──────────────────────────────────────────────────────────
function timer() {
  const start = Date.now();
  return () => Date.now() - start;
}

function randomSignalId() {
  return BigInt("0x" + crypto.randomBytes(32).toString("hex"));
}

function randomBlob() {
  const iv = crypto.randomBytes(12).toString("hex");
  const ct = crypto.randomBytes(64).toString("hex");
  return "0x" + Buffer.from(`${iv}:${ct}`).toString("hex");
}

function randomDecoyLines() {
  const sports = ["NBA", "NFL", "MLB", "NHL"];
  const teams = ["Lakers", "Celtics", "Warriors", "Bulls", "Nets", "Heat", "Bucks", "Sixers", "Suns", "Nuggets"];
  const lines = [];
  for (let i = 0; i < 10; i++) {
    const sport = sports[Math.floor(Math.random() * sports.length)];
    const t1 = teams[Math.floor(Math.random() * teams.length)];
    const t2 = teams[Math.floor(Math.random() * teams.length)];
    const spread = (Math.random() * 10 - 5).toFixed(1);
    lines.push(`${sport}|${t1} vs ${t2}|spreads|${spread}|${t1}`);
  }
  return lines;
}

async function fetchWithTimeout(url, opts = {}, timeoutMs = 30000) {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const res = await fetch(url, { ...opts, signal: controller.signal });
    return res;
  } finally {
    clearTimeout(timeout);
  }
}

// ─── Main ─────────────────────────────────────────────────────────────
async function main() {
  const provider = new ethers.JsonRpcProvider(RPC_URL);
  const wallet = new ethers.Wallet(PRIVATE_KEY, provider);
  console.log(`Wallet: ${wallet.address}`);
  console.log(`RPC: ${RPC_URL}`);
  console.log(`App: ${BASE_URL}`);
  console.log(`Signals to create: ${NUM_SIGNALS}`);
  console.log(`Purchases to attempt: ${NUM_PURCHASES}`);
  console.log();

  // Check wallet balance
  const ethBal = await provider.getBalance(wallet.address);
  console.log(`ETH balance: ${ethers.formatEther(ethBal)}`);
  if (ethBal < ethers.parseEther("0.0002")) {
    console.error("Insufficient ETH. Need at least 0.0002 for gas.");
    process.exit(1);
  }

  const usdc = new ethers.Contract(ADDRESSES.usdc, USDC_ABI, wallet);
  const usdcBal = await usdc.balanceOf(wallet.address);
  console.log(`USDC balance: ${ethers.formatUnits(usdcBal, 6)}`);

  const signal = new ethers.Contract(ADDRESSES.signalCommitment, SIGNAL_ABI, wallet);
  const escrow = new ethers.Contract(ADDRESSES.escrow, ESCROW_ABI, wallet);
  const collateral = new ethers.Contract(ADDRESSES.collateral, COLLATERAL_ABI, wallet);

  // ─── Step 0: Ensure funds ────────────────────────────
  const t0 = timer();
  console.log("\n=== STEP 0: Fund wallet ===");

  // Check existing balances before doing any setup txs
  const availColl = await collateral.getAvailable(wallet.address);
  const escrowBal = await escrow.getBalance(wallet.address);
  console.log(`  Collateral available: ${ethers.formatUnits(availColl, 6)} USDC`);
  console.log(`  Escrow balance: ${ethers.formatUnits(escrowBal, 6)} USDC`);

  // Scale funding based on signal count: each signal needs ~$100 maxNotional collateral
  const neededUsdc = ethers.parseUnits(String(Math.max(10000, NUM_SIGNALS * 150)), 6);
  const neededColl = ethers.parseUnits(String(Math.max(2000, NUM_SIGNALS * 120)), 6);
  const neededEscrow = ethers.parseUnits(String(Math.max(1000, NUM_PURCHASES * 15)), 6);

  const needsSetup = usdcBal < neededUsdc ||
    availColl < neededColl ||
    escrowBal < neededEscrow;

  if (needsSetup) {
    console.log("  Running setup transactions...");
    try {
      if (usdcBal < neededUsdc) {
        const mintAmt = neededUsdc * 2n;
        const mintTx = await usdc.mint(wallet.address, mintAmt);
        await mintTx.wait();
        console.log(`  Minted ${ethers.formatUnits(mintAmt, 6)} USDC`);
      }
      if (availColl < neededColl) {
        const appTx = await usdc.approve(ADDRESSES.collateral, ethers.MaxUint256);
        await appTx.wait();
        const depAmt = neededColl * 2n;
        const depTx = await collateral.deposit(depAmt);
        await depTx.wait();
        console.log(`  Deposited ${ethers.formatUnits(depAmt, 6)} collateral`);
      }
      if (escrowBal < neededEscrow) {
        const appTx = await usdc.approve(ADDRESSES.escrow, ethers.MaxUint256);
        await appTx.wait();
        const depAmt = neededEscrow * 2n;
        const depTx = await escrow.deposit(depAmt);
        await depTx.wait();
        console.log(`  Deposited ${ethers.formatUnits(depAmt, 6)} escrow`);
      }
    } catch (err) {
      console.log(`  Setup tx failed (may already be done): ${err.message?.slice(0, 80)}`);
    }
  } else {
    console.log("  Sufficient funds, skipping setup.");
  }
  console.log(`  Setup total: ${t0()}ms`);

  // ─── Step 1: Create signals ──────────────────────────
  console.log(`\n=== STEP 1: Create ${NUM_SIGNALS} signals ===`);
  const createdSignals = [];
  const createTimings = [];

  // Use explicit nonce management to avoid collisions at high throughput
  let nonce = await provider.getTransactionCount(wallet.address, "pending");
  console.log(`  Starting nonce: ${nonce}`);

  // Fire-and-forget with nonce tracking, then batch-wait for receipts
  const BATCH_SIZE = 10; // send 10 txs, then wait for all receipts
  for (let batch = 0; batch < NUM_SIGNALS; batch += BATCH_SIZE) {
    const batchEnd = Math.min(batch + BATCH_SIZE, NUM_SIGNALS);
    const pending = [];

    for (let i = batch; i < batchEnd; i++) {
      const signalId = randomSignalId();
      const blob = randomBlob();
      const commitHash = ethers.keccak256(ethers.toUtf8Bytes(blob));
      const decoyLines = randomDecoyLines();
      const expiresAt = BigInt(Math.floor(Date.now() / 1000) + 6 * 3600);

      const params = {
        signalId,
        encryptedBlob: blob,
        commitHash,
        sport: "basketball_nba",
        maxPriceBps: 1000n,
        slaMultiplierBps: 10000n,
        maxNotional: ethers.parseUnits("100", 6),
        minNotional: 0n,
        expiresAt,
        decoyLines,
        availableSportsbooks: [],
        linesHash: ethers.ZeroHash,
        lineCount: decoyLines.length,
        bpaMode: false,
      };

      const t = timer();
      const sendNonce = nonce;
      try {
        const tx = await signal.commit(params, { nonce: sendNonce });
        nonce = sendNonce + 1;  // only advance after broadcast succeeded
        const sendMs = t();
        pending.push({ i: i + 1, signalId: signalId.toString(), tx, sendMs, t });
      } catch (err) {
        // Leave `nonce` untouched: the slot was never consumed on chain.
        const elapsed = t();
        createTimings.push({ i: i + 1, sendMs: elapsed, confirmMs: elapsed, status: "error", error: err.message?.slice(0, 100) });
        console.log(`  Signal ${i + 1}/${NUM_SIGNALS}: SEND FAILED at ${elapsed}ms: ${err.message?.slice(0, 80)}`);
      }
    }

    // Wait for all receipts in this batch
    for (const p of pending) {
      try {
        const receipt = await p.tx.wait();
        const confirmMs = p.t();
        createdSignals.push(p.signalId);
        createTimings.push({ i: p.i, sendMs: p.sendMs, confirmMs, status: "ok", gas: Number(receipt.gasUsed) });
        console.log(`  Signal ${p.i}/${NUM_SIGNALS}: send=${p.sendMs}ms confirm=${confirmMs}ms gas=${receipt.gasUsed}`);
      } catch (err) {
        const elapsed = p.t();
        createTimings.push({ i: p.i, sendMs: p.sendMs, confirmMs: elapsed, status: "error", error: err.message?.slice(0, 100) });
        console.log(`  Signal ${p.i}/${NUM_SIGNALS}: CONFIRM FAILED at ${elapsed}ms: ${err.message?.slice(0, 80)}`);
      }
    }

    if (batch + BATCH_SIZE < NUM_SIGNALS) {
      console.log(`  --- Batch ${Math.floor(batch / BATCH_SIZE) + 1} done (${createdSignals.length} created so far) ---`);
      // Unconditionally resync nonce from chain at batch boundaries.
      // Cheap (one RPC call per 10 txs) and robust against both send-phase
      // failures and confirm-phase gaps that can desync our local counter.
      await new Promise((r) => setTimeout(r, 3000));
      nonce = await provider.getTransactionCount(wallet.address, "latest");
    }
  }

  // ─── Step 2: Check line availability via API ─────────
  console.log(`\n=== STEP 2: Line check via API (${createdSignals.length} signals) ===`);
  const lineCheckTimings = [];

  // Cap line checks at 10 for stress tests (they hit same validators, same result)
  const lineCheckCount = Math.min(createdSignals.length, NUM_PURCHASES, 10);
  for (let i = 0; i < lineCheckCount; i++) {
    const t = timer();
    try {
      const res = await fetchWithTimeout(`${BASE_URL}/api/miner/v1/check`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          lines: randomDecoyLines().slice(0, 10).map((line, idx) => {
            const parts = line.split("|");
            return {
              index: idx + 1,
              sport: "basketball_nba",
              event_id: `test-${Date.now()}`,
              home_team: parts[1]?.split(" vs ")[0] || "Home",
              away_team: parts[1]?.split(" vs ")[1] || "Away",
              market: "spreads",
              line: parseFloat(parts[3] || "0"),
              side: parts[4] || "Home",
            };
          }),
        }),
      });
      const elapsed = t();
      const body = await res.json().catch(() => ({}));
      const available = body.available_indices?.length ?? 0;
      lineCheckTimings.push({ i: i + 1, ms: elapsed, status: res.status, available });
      console.log(`  Check ${i + 1}: ${elapsed}ms status=${res.status} available=${available}`);
    } catch (err) {
      const elapsed = t();
      lineCheckTimings.push({ i: i + 1, ms: elapsed, status: "error", error: err.message?.slice(0, 80) });
      console.log(`  Check ${i + 1}: FAILED at ${elapsed}ms: ${err.message?.slice(0, 80)}`);
    }
  }

  // ─── Step 3: Validator discovery ─────────────────────
  console.log("\n=== STEP 3: Validator discovery ===");
  const tDisc = timer();
  let validators = [];
  try {
    const res = await fetchWithTimeout(`${BASE_URL}/api/validators/discover`);
    const body = await res.json();
    validators = body.validators || (Array.isArray(body) ? body : []);
    console.log(`  Discovery: ${tDisc()}ms, found ${validators.length} validators`);
    for (const v of validators.slice(0, 5)) {
      console.log(`    UID ${v.uid}: ${v.ip}:${v.port} stake=${v.stake?.toFixed?.(2) ?? "?"}`);
    }
  } catch (err) {
    console.log(`  Discovery FAILED: ${tDisc()}ms ${err.message?.slice(0, 80)}`);
  }

  // ─── Step 4: Validator health checks ─────────────────
  console.log("\n=== STEP 4: Validator health checks ===");
  const healthTimings = [];
  for (const v of validators.slice(0, 10)) {
    const t = timer();
    try {
      const res = await fetchWithTimeout(`${BASE_URL}/api/validators/${v.uid}/health`, {}, 10000);
      const elapsed = t();
      const body = await res.json().catch(() => ({}));
      healthTimings.push({ uid: v.uid, ms: elapsed, status: body.status || res.status, version: body.version });
      console.log(`  UID ${v.uid}: ${elapsed}ms status=${body.status || res.status} v=${body.version || "?"}`);
    } catch (err) {
      const elapsed = t();
      healthTimings.push({ uid: v.uid, ms: elapsed, status: "error" });
      console.log(`  UID ${v.uid}: FAILED ${elapsed}ms`);
    }
  }

  // ─── Step 5: Purchase attempts ───────────────────────
  console.log(`\n=== STEP 5: Purchase ${NUM_PURCHASES} signals (on-chain only, no MPC) ===`);
  const purchaseTimings = [];

  // Use a separate buyer wallet (self-purchase now allowed, but a distinct buyer is more realistic)
  let buyerWallet = wallet;
  let buyerEscrow = escrow;
  if (BUYER_KEY) {
    buyerWallet = new ethers.Wallet(BUYER_KEY, provider);
    buyerEscrow = new ethers.Contract(ADDRESSES.escrow, ESCROW_ABI, buyerWallet);
    const buyerBal = await escrow.getBalance(buyerWallet.address);
    console.log(`  Buyer wallet: ${buyerWallet.address} (escrow: ${ethers.formatUnits(buyerBal, 6)} USDC)`);

    // Auto-fund buyer if needed (scale for stress test)
    const buyerNeeded = ethers.parseUnits(String(Math.max(100, NUM_PURCHASES * 15)), 6);
    if (buyerBal < buyerNeeded) {
      console.log(`  Funding buyer wallet (need ${ethers.formatUnits(buyerNeeded, 6)} USDC)...`);
      try {
        const ethBuyerBal = await provider.getBalance(buyerWallet.address);
        if (ethBuyerBal < ethers.parseEther("0.001")) {
          const ethTx = await wallet.sendTransaction({ to: buyerWallet.address, value: ethers.parseEther("0.01") });
          await ethTx.wait();
        }
        const mintAmt = buyerNeeded * 3n;
        const mintTx = await usdc.mint(buyerWallet.address, mintAmt);
        await mintTx.wait();
        const buyerUsdc = new ethers.Contract(ADDRESSES.usdc, USDC_ABI, buyerWallet);
        const appTx = await buyerUsdc.approve(ADDRESSES.escrow, ethers.MaxUint256);
        await appTx.wait();
        const depTx = await buyerEscrow.deposit(buyerNeeded * 2n);
        await depTx.wait();
        console.log(`  Buyer funded: ${ethers.formatUnits(buyerNeeded * 2n, 6)} USDC in escrow`);
      } catch (err) {
        console.log(`  Buyer funding failed: ${err.message?.slice(0, 80)}`);
      }
    }
  } else {
    console.log(`  No E2E_BUYER_PRIVATE_KEY set, using same wallet (self-purchase)`);
    console.log(`  Buying with: ${wallet.address} (escrow: ${ethers.formatUnits(escrowBal, 6)} USDC)`);
  }

  // Batch purchases with explicit nonce management
  let buyerNonce = await provider.getTransactionCount(buyerWallet.address, "pending");
  console.log(`  Buyer starting nonce: ${buyerNonce}`);
  const totalPurchases = Math.min(createdSignals.length, NUM_PURCHASES);

  for (let batch = 0; batch < totalPurchases; batch += BATCH_SIZE) {
    const batchEnd = Math.min(batch + BATCH_SIZE, totalPurchases);
    const pending = [];

    for (let i = batch; i < batchEnd; i++) {
      const sigId = BigInt(createdSignals[i]);
      const notional = ethers.parseUnits("10", 6); // $10
      const odds = ethers.parseUnits("1.91", 6); // -110

      const t = timer();
      const sendNonce = buyerNonce;
      try {
        const tx = await buyerEscrow.purchase(sigId, notional, odds, { nonce: sendNonce });
        buyerNonce = sendNonce + 1;  // only advance after broadcast succeeded
        const sendMs = t();
        pending.push({ i: i + 1, tx, sendMs, t });
      } catch (err) {
        // Leave `buyerNonce` untouched: the slot was never consumed on chain.
        const elapsed = t();
        const msg = err.message?.slice(0, 120) || "unknown";
        purchaseTimings.push({ i: i + 1, sendMs: elapsed, confirmMs: elapsed, status: "error", error: msg });
        console.log(`  Purchase ${i + 1}/${totalPurchases}: SEND FAILED at ${elapsed}ms: ${msg.slice(0, 80)}`);
      }
    }

    for (const p of pending) {
      try {
        const receipt = await p.tx.wait();
        const confirmMs = p.t();
        purchaseTimings.push({ i: p.i, sendMs: p.sendMs, confirmMs, status: "ok", gas: Number(receipt.gasUsed) });
        console.log(`  Purchase ${p.i}/${totalPurchases}: send=${p.sendMs}ms confirm=${confirmMs}ms gas=${receipt.gasUsed}`);
      } catch (err) {
        const elapsed = p.t();
        const msg = err.message?.slice(0, 120) || "unknown";
        purchaseTimings.push({ i: p.i, sendMs: p.sendMs, confirmMs: elapsed, status: "error", error: msg });
        console.log(`  Purchase ${p.i}/${totalPurchases}: CONFIRM FAILED at ${elapsed}ms: ${msg.slice(0, 80)}`);
      }
    }

    if (batch + BATCH_SIZE < totalPurchases) {
      console.log(`  --- Purchase batch ${Math.floor(batch / BATCH_SIZE) + 1} done (${purchaseTimings.filter(t => t.status === "ok").length} purchased so far) ---`);
      // Unconditionally resync nonce from chain at batch boundaries.
      // Robust against both send-phase failures (which the previous
      // slice(-pending.length) detector missed when pending.length===0
      // because slice(-0) returns the whole array) and confirm-phase gaps.
      await new Promise((r) => setTimeout(r, 3000));
      buyerNonce = await provider.getTransactionCount(buyerWallet.address, "latest");
    }
  }

  // ─── Step 6: Browse API timing ───────────────────────
  console.log("\n=== STEP 6: API response times ===");
  const apiTimings = [];
  const endpoints = [
    { name: "health", url: `${BASE_URL}/api/health` },
    { name: "browse", url: `${BASE_URL}/api/idiot/browse?limit=20` },
    { name: "odds", url: `${BASE_URL}/api/odds?sport=basketball_nba` },
    { name: "network", url: `${BASE_URL}/api/network/status` },
    { name: "discover", url: `${BASE_URL}/api/validators/discover` },
  ];
  for (const ep of endpoints) {
    const t = timer();
    try {
      const res = await fetchWithTimeout(ep.url, {}, 30000);
      const elapsed = t();
      const size = (await res.text()).length;
      apiTimings.push({ name: ep.name, ms: elapsed, status: res.status, sizeKb: (size / 1024).toFixed(1) });
      console.log(`  ${ep.name}: ${elapsed}ms status=${res.status} size=${(size / 1024).toFixed(1)}KB`);
    } catch (err) {
      const elapsed = t();
      apiTimings.push({ name: ep.name, ms: elapsed, status: "error" });
      console.log(`  ${ep.name}: FAILED ${elapsed}ms`);
    }
  }

  // ─── Summary ─────────────────────────────────────────
  console.log("\n" + "=".repeat(60));
  console.log("SUMMARY");
  console.log("=".repeat(60));

  const avgCreate = createTimings.filter((t) => t.status === "ok");
  const avgPurchase = purchaseTimings.filter((t) => t.status === "ok");

  console.log(`\nSignal Creation (${NUM_SIGNALS} attempted, ${avgCreate.length} succeeded):`);
  if (avgCreate.length > 0) {
    const avgSend = Math.round(avgCreate.reduce((s, t) => s + t.sendMs, 0) / avgCreate.length);
    const avgConfirm = Math.round(avgCreate.reduce((s, t) => s + t.confirmMs, 0) / avgCreate.length);
    const avgGas = Math.round(avgCreate.reduce((s, t) => s + t.gas, 0) / avgCreate.length);
    console.log(`  Avg send: ${avgSend}ms`);
    console.log(`  Avg confirm: ${avgConfirm}ms`);
    console.log(`  Avg gas: ${avgGas}`);
  }
  const failedCreate = createTimings.filter((t) => t.status !== "ok");
  if (failedCreate.length > 0) {
    console.log(`  FAILURES (${failedCreate.length}):`);
    for (const f of failedCreate) console.log(`    #${f.i}: ${f.error}`);
  }

  console.log(`\nPurchase (${NUM_PURCHASES} attempted, ${avgPurchase.length} succeeded):`);
  if (avgPurchase.length > 0) {
    const avgSend = Math.round(avgPurchase.reduce((s, t) => s + t.sendMs, 0) / avgPurchase.length);
    const avgConfirm = Math.round(avgPurchase.reduce((s, t) => s + t.confirmMs, 0) / avgPurchase.length);
    const avgGas = Math.round(avgPurchase.reduce((s, t) => s + t.gas, 0) / avgPurchase.length);
    console.log(`  Avg send: ${avgSend}ms`);
    console.log(`  Avg confirm: ${avgConfirm}ms`);
    console.log(`  Avg gas: ${avgGas}`);
  }
  const failedPurchase = purchaseTimings.filter((t) => t.status !== "ok");
  if (failedPurchase.length > 0) {
    console.log(`  FAILURES (${failedPurchase.length}):`);
    for (const f of failedPurchase) console.log(`    #${f.i}: ${f.error}`);
  }

  console.log(`\nLine Checks (${lineCheckTimings.length}):`);
  if (lineCheckTimings.length > 0) {
    const avg = Math.round(lineCheckTimings.reduce((s, t) => s + t.ms, 0) / lineCheckTimings.length);
    const okCount = lineCheckTimings.filter((t) => t.status === 200).length;
    console.log(`  Avg: ${avg}ms`);
    console.log(`  Success: ${okCount}/${lineCheckTimings.length}`);
  }

  console.log(`\nValidator Health (${healthTimings.length}):`);
  const healthyV = healthTimings.filter((t) => t.status === "ok");
  console.log(`  Healthy: ${healthyV.length}/${healthTimings.length}`);
  if (healthyV.length > 0) {
    const avg = Math.round(healthyV.reduce((s, t) => s + t.ms, 0) / healthyV.length);
    console.log(`  Avg response: ${avg}ms`);
  }

  console.log(`\nAPI Response Times:`);
  for (const t of apiTimings) {
    console.log(`  ${t.name}: ${t.ms}ms (${t.sizeKb}KB)`);
  }

  console.log("\n" + "=".repeat(60));
}

main().catch((err) => {
  console.error("Fatal:", err);
  process.exit(1);
});
