#!/usr/bin/env node
/**
 * Djinn Testnet Admin Script
 *
 * Exercises the full economic cycle on Base Sepolia:
 *   1. Authorize deployer as caller on Escrow + Account
 *   2. Set outcomes for pending purchases
 *   3. Trigger early exit or full audit settlement
 *
 * Usage:
 *   node scripts/testnet-admin.mjs authorize
 *   node scripts/testnet-admin.mjs set-outcomes
 *   node scripts/testnet-admin.mjs early-exit <genius> <idiot>
 *   node scripts/testnet-admin.mjs status
 */

import { ethers } from "ethers";
import { readFileSync } from "fs";
import { resolve, dirname } from "path";
import { fileURLToPath } from "url";

const __dirname = dirname(fileURLToPath(import.meta.url));
const ROOT = resolve(__dirname, "..");

// ── Load config ─────────────────────────────────────────────────────
function loadEnv(filePath) {
  const content = readFileSync(filePath, "utf8");
  const env = {};
  for (const line of content.split("\n")) {
    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith("#")) continue;
    const eqIdx = trimmed.indexOf("=");
    if (eqIdx < 0) continue;
    env[trimmed.slice(0, eqIdx).trim()] = trimmed.slice(eqIdx + 1).trim();
  }
  return env;
}

const contractsEnv = loadEnv(resolve(ROOT, "djinn/contracts/.env"));
const webEnv = loadEnv(resolve(ROOT, "web/.env"));

const DEPLOYER_KEY = contractsEnv.DEPLOYER_KEY;
const RPC_URL = webEnv.NEXT_PUBLIC_BASE_RPC_URL || "https://sepolia.base.org";

const ADDRESSES = {
  escrow: webEnv.NEXT_PUBLIC_ESCROW_ADDRESS,
  account: webEnv.NEXT_PUBLIC_ACCOUNT_ADDRESS,
  signalCommitment: webEnv.NEXT_PUBLIC_SIGNAL_COMMITMENT_ADDRESS,
  collateral: webEnv.NEXT_PUBLIC_COLLATERAL_ADDRESS,
  creditLedger: webEnv.NEXT_PUBLIC_CREDIT_LEDGER_ADDRESS,
  audit: webEnv.NEXT_PUBLIC_AUDIT_ADDRESS,
  usdc: webEnv.NEXT_PUBLIC_USDC_ADDRESS,
};

const SUBGRAPH_URL = "https://api.studio.thegraph.com/query/1742249/djinn/v2.3.0";

// ── ABIs (minimal) ──────────────────────────────────────────────────
const ESCROW_ABI = [
  "function setAuthorizedCaller(address caller, bool _authorized) external",
  "function authorizedCallers(address) view returns (bool)",
  "function setOutcome(uint256 purchaseId, uint8 outcome) external",
  "function getPurchase(uint256 purchaseId) view returns (tuple(uint256 signalId, address idiot, uint256 notional, uint256 pricePaid, uint256 odds, uint8 outcome, uint256 timestamp))",
  "function nextPurchaseId() view returns (uint256)",
  "function owner() view returns (address)",
];

const ACCOUNT_ABI = [
  "function setAuthorizedCaller(address caller, bool authorized) external",
  "function authorizedCallers(address) view returns (bool)",
  "function recordOutcome(address genius, address idiot, uint256 purchaseId, uint8 outcome) external",
  "function getAccountState(address genius, address idiot) view returns (tuple(uint256 currentCycle, uint256 signalCount, int256 qualityScore, uint256[] purchaseIds, bool settled))",
  "function isAuditReady(address genius, address idiot) view returns (bool)",
  "function getCurrentCycle(address genius, address idiot) view returns (uint256)",
  "function getOutcome(address genius, address idiot, uint256 purchaseId) view returns (uint8)",
  "function owner() view returns (address)",
];

const AUDIT_ABI = [
  "function trigger(address genius, address idiot) external",
  "function settle(address genius, address idiot) external",
  "function earlyExit(address genius, address idiot) external",
  "function computeScore(address genius, address idiot) view returns (int256)",
];

const SIGNAL_ABI = [
  "function getSignal(uint256 signalId) view returns (tuple(address genius, bytes32 commitHash, bytes encryptedBlob, string sport, uint256 maxPriceBps, uint256 slaMultiplierBps, uint256 maxNotional, uint256 minNotional, uint256 expiresAt, uint256 createdAt, uint8 status, string[] decoyLines, string[] availableSportsbooks, uint256 totalPurchased))",
];

const COLLATERAL_ABI = [
  "function deposits(address) view returns (uint256)",
  "function locked(address) view returns (uint256)",
];

// Outcome enum: 0=Pending, 1=Favorable, 2=Unfavorable, 3=Void
const Outcome = { Pending: 0, Favorable: 1, Unfavorable: 2, Void: 3 };
const OutcomeName = ["Pending", "Favorable", "Unfavorable", "Void"];

// ── Setup ───────────────────────────────────────────────────────────
const provider = new ethers.JsonRpcProvider(RPC_URL);
const wallet = new ethers.Wallet(DEPLOYER_KEY, provider);

const escrow = new ethers.Contract(ADDRESSES.escrow, ESCROW_ABI, wallet);
const account = new ethers.Contract(ADDRESSES.account, ACCOUNT_ABI, wallet);
const audit = new ethers.Contract(ADDRESSES.audit, AUDIT_ABI, wallet);
const signalCommitment = new ethers.Contract(ADDRESSES.signalCommitment, SIGNAL_ABI, provider);
const collateral = new ethers.Contract(ADDRESSES.collateral, COLLATERAL_ABI, provider);

// ── Subgraph query ──────────────────────────────────────────────────
async function querySubgraph(query) {
  const resp = await fetch(SUBGRAPH_URL, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ query }),
  });
  const json = await resp.json();
  if (json.errors) throw new Error(JSON.stringify(json.errors));
  return json.data;
}

// ── Commands ────────────────────────────────────────────────────────

async function status() {
  console.log("=== Djinn Testnet Status ===\n");
  console.log("Deployer:", wallet.address);
  console.log("Escrow:", ADDRESSES.escrow);
  console.log("Account:", ADDRESSES.account);
  console.log("Audit:", ADDRESSES.audit);

  // Check authorization
  const escrowAuth = await escrow.authorizedCallers(wallet.address);
  const accountAuth = await account.authorizedCallers(wallet.address);
  console.log(`\nDeployer authorized on Escrow: ${escrowAuth}`);
  console.log(`Deployer authorized on Account: ${accountAuth}`);

  // Query purchases
  const nextId = await escrow.nextPurchaseId();
  console.log(`\nTotal purchases: ${nextId}`);

  for (let i = 0; i < Number(nextId); i++) {
    const p = await escrow.getPurchase(i);
    console.log(`  Purchase #${i}: signal=${p.signalId}, idiot=${p.idiot.slice(0,10)}..., notional=$${Number(p.notional) / 1e6}, outcome=${OutcomeName[Number(p.outcome)]}`);
  }

  // Query subgraph for genius-idiot pairs
  const data = await querySubgraph(`{
    signals(first: 10, orderBy: createdAt, orderDirection: desc) {
      id genius { id } sport status
      purchases { id idiot { id } notional outcome onChainPurchaseId }
    }
  }`);

  const pairs = new Map();
  for (const sig of data.signals) {
    for (const p of sig.purchases) {
      const key = `${sig.genius.id}:${p.idiot.id}`;
      if (!pairs.has(key)) pairs.set(key, { genius: sig.genius.id, idiot: p.idiot.id, purchases: [] });
      pairs.get(key).purchases.push({ id: p.onChainPurchaseId, signal: sig.id, outcome: p.outcome });
    }
  }

  for (const [key, pair] of pairs) {
    console.log(`\nPair: Genius=${pair.genius.slice(0,10)}... Idiot=${pair.idiot.slice(0,10)}...`);
    try {
      const state = await account.getAccountState(pair.genius, pair.idiot);
      console.log(`  Cycle: ${state.currentCycle}, Signal count: ${state.signalCount}, QS: ${state.qualityScore}, Settled: ${state.settled}`);
      console.log(`  Purchase IDs in cycle: [${state.purchaseIds.join(", ")}]`);
      const auditReady = await account.isAuditReady(pair.genius, pair.idiot);
      console.log(`  Audit ready: ${auditReady}`);
    } catch (e) {
      console.log(`  Account state: ${e.message}`);
    }

    // Check collateral
    try {
      const dep = await collateral.deposits(pair.genius);
      const lock = await collateral.locked(pair.genius);
      console.log(`  Genius collateral: deposited=$${Number(dep) / 1e6}, locked=$${Number(lock) / 1e6}`);
    } catch (e) {
      console.log(`  Collateral check: ${e.message}`);
    }
  }
}

async function authorize() {
  console.log("=== Authorizing deployer as caller ===\n");
  console.log("Deployer:", wallet.address);

  // Check if already authorized
  const escrowAuth = await escrow.authorizedCallers(wallet.address);
  if (escrowAuth) {
    console.log("Already authorized on Escrow");
  } else {
    console.log("Authorizing on Escrow...");
    const tx = await escrow.setAuthorizedCaller(wallet.address, true);
    await tx.wait();
    console.log("  Done:", tx.hash);
  }

  const accountAuth = await account.authorizedCallers(wallet.address);
  if (accountAuth) {
    console.log("Already authorized on Account");
  } else {
    console.log("Authorizing on Account...");
    const tx = await account.setAuthorizedCaller(wallet.address, true);
    await tx.wait();
    console.log("  Done:", tx.hash);
  }

  console.log("\nAuthorization complete.");
}

async function setOutcomes() {
  console.log("=== Setting outcomes for pending purchases ===\n");

  // Ensure authorized
  const escrowAuth = await escrow.authorizedCallers(wallet.address);
  const accountAuth = await account.authorizedCallers(wallet.address);
  if (!escrowAuth || !accountAuth) {
    console.log("ERROR: Deployer not authorized. Run: node scripts/testnet-admin.mjs authorize");
    process.exit(1);
  }

  // Get all signals and purchases from subgraph
  const data = await querySubgraph(`{
    signals(first: 50, orderBy: createdAt, orderDirection: desc) {
      id genius { id } sport status
      purchases { id idiot { id } notional outcome onChainPurchaseId }
    }
  }`);

  let settled = 0;
  for (const sig of data.signals) {
    for (const p of sig.purchases) {
      if (p.outcome !== "Pending") {
        console.log(`  Purchase #${p.onChainPurchaseId}: already ${p.outcome}`);
        continue;
      }

      // Voided signals get Void outcomes; others get Favorable (testnet)
      let outcome;
      if (sig.status === "Voided") {
        outcome = Outcome.Void;
      } else {
        // Alternate: first purchase Favorable, second Unfavorable for variety
        outcome = settled % 2 === 0 ? Outcome.Favorable : Outcome.Unfavorable;
      }

      console.log(`  Purchase #${p.onChainPurchaseId} (signal ${sig.id}, ${sig.sport}, ${sig.status}): setting ${OutcomeName[outcome]}`);

      try {
        // Get fresh nonce for each pair of txs
        const nonce = await provider.getTransactionCount(wallet.address, "latest");

        // Set on Escrow
        const tx1 = await escrow.setOutcome(BigInt(p.onChainPurchaseId), outcome, { nonce });
        console.log(`    Escrow.setOutcome tx: ${tx1.hash}`);
        await tx1.wait();

        // Record on Account (nonce+1 since previous confirmed)
        const tx2 = await account.recordOutcome(
          sig.genius.id,
          p.idiot.id,
          BigInt(p.onChainPurchaseId),
          outcome,
        );
        console.log(`    Account.recordOutcome tx: ${tx2.hash}`);
        await tx2.wait();

        settled++;
      } catch (e) {
        const msg = e.shortMessage || e.message;
        if (msg.includes("OutcomeAlreadySet") || msg.includes("OutcomeAlreadyRecorded")) {
          console.log(`    Already set — skipping`);
          settled++;
        } else {
          console.log(`    ERROR: ${msg}`);
        }
      }
    }
  }

  console.log(`\nSettled ${settled} purchases.`);
}

async function earlyExitCmd(genius, idiot) {
  console.log("=== Triggering early exit ===\n");
  console.log(`Genius: ${genius}`);
  console.log(`Idiot:  ${idiot}`);

  // Check state
  const state = await account.getAccountState(genius, idiot);
  console.log(`Cycle: ${state.currentCycle}, Purchases: ${state.purchaseIds.length}, QS: ${state.qualityScore}`);

  const auditReady = await account.isAuditReady(genius, idiot);
  if (auditReady) {
    console.log("Audit ready (10+ purchases) — use 'trigger' instead of early-exit");
    process.exit(1);
  }

  // Check all outcomes are finalized
  for (const pid of state.purchaseIds) {
    const outcome = await account.getOutcome(genius, idiot, pid);
    console.log(`  Purchase #${pid}: ${OutcomeName[Number(outcome)]}`);
    if (Number(outcome) === 0) {
      console.log("ERROR: Purchase has Pending outcome. Run set-outcomes first.");
      process.exit(1);
    }
  }

  // Compute score
  const score = await audit.computeScore(genius, idiot);
  console.log(`\nComputed quality score: ${score}`);

  // Early exit must be called by genius or idiot — use the E2E test key if it matches
  const e2eKey = webEnv.E2E_TEST_PRIVATE_KEY;
  const e2eAddr = webEnv.E2E_TEST_ADDRESS?.toLowerCase();

  let caller;
  if (wallet.address.toLowerCase() === genius.toLowerCase() || wallet.address.toLowerCase() === idiot.toLowerCase()) {
    caller = wallet;
  } else if (e2eKey && (e2eAddr === genius.toLowerCase() || e2eAddr === idiot.toLowerCase())) {
    caller = new ethers.Wallet(e2eKey, provider);
  } else {
    console.log(`\nERROR: earlyExit must be called by genius or idiot.`);
    console.log(`Deployer ${wallet.address} is neither.`);
    console.log(`Genius: ${genius}`);
    console.log(`Idiot:  ${idiot}`);
    console.log(`\nTo proceed, import the genius or idiot private key.`);
    process.exit(1);
  }

  console.log(`\nCalling earlyExit as ${caller.address}...`);
  const auditContract = new ethers.Contract(ADDRESSES.audit, AUDIT_ABI, caller);
  const tx = await auditContract.earlyExit(genius, idiot);
  await tx.wait();
  console.log(`Done: ${tx.hash}`);

  // Check result
  const newState = await account.getAccountState(genius, idiot);
  console.log(`\nNew cycle: ${newState.currentCycle}, Settled: ${newState.settled}`);
}

// ── Main ────────────────────────────────────────────────────────────
const cmd = process.argv[2];

if (!cmd || cmd === "status") {
  await status();
} else if (cmd === "authorize") {
  await authorize();
} else if (cmd === "set-outcomes") {
  await setOutcomes();
} else if (cmd === "early-exit") {
  const genius = process.argv[3];
  const idiot = process.argv[4];
  if (!genius || !idiot) {
    console.log("Usage: node scripts/testnet-admin.mjs early-exit <genius> <idiot>");
    process.exit(1);
  }
  await earlyExitCmd(genius, idiot);
} else {
  console.log("Commands: status, authorize, set-outcomes, early-exit <genius> <idiot>");
  process.exit(1);
}
