#!/usr/bin/env node
// Harvest Base Sepolia ETH by running many fresh wallets through CDP faucet
// and sweeping them to a target address.
//
// CDP faucet gives 0.0001 ETH per drip. Rate limit is GLOBAL on the
// API key, ~10 drips/hour across ALL addresses. Horizontal scaling via
// fresh wallets does NOT bypass it — only the first ~10 requests in
// any hour succeed regardless of recipient. Confirmed empirically
// 2026-04-20: 100 fresh wallets × 1 drip yielded 10 ok / 90 rate-limit.
//
// So practical ceiling ≈ 0.001 ETH/hr = 0.024 ETH/day per API key.
// For higher throughput, chain a second/third CDP API key or use
// Coinbase bridge from mainnet.
//
// Usage: node scripts/cdp-harvester.mjs <target> <numWallets> <dripsPerWallet>
//   defaults: target=deployer, numWallets=10, dripsPerWallet=1
//
// Per-wallet sweep cost ≈ 21000 * gasPrice * 2 (safety margin).
// Confirmation wait is 30s so drips settle before balance-check.

import { CdpClient } from "@coinbase/cdp-sdk";
import { Wallet, JsonRpcProvider, formatEther } from "ethers";
import fs from "node:fs";

const env = {};
for (const line of fs.readFileSync(process.env.HOME + "/.cdp-faucet.env", "utf8").split("\n")) {
  const m = line.match(/^([A-Z_]+)=(.*)$/);
  if (m) env[m[1]] = m[2].trim();
}
const cdp = new CdpClient({ apiKeyId: env.CDP_API_KEY, apiKeySecret: env.CDP_API_SECRET });
const rpc = new JsonRpcProvider("https://sepolia.base.org");

const target = process.argv[2] || "0xD717b5fbA93F123f6ad530ae2Ab327B4DcDa1e37";
const numWallets = parseInt(process.argv[3] || "10", 10);
const dripsPerWallet = parseInt(process.argv[4] || "1", 10);

console.log(`Harvesting ${numWallets}×${dripsPerWallet} drips → ${target}`);
const t0 = Date.now();

const wallets = Array.from({ length: numWallets }, () => Wallet.createRandom().connect(rpc));

// Drip phase — concurrent 5 at a time to avoid API-level throttle
let dripsOK = 0, dripsFail = 0;
const CONCURRENCY = 5;
const allTasks = [];
for (const w of wallets) {
  for (let i = 0; i < dripsPerWallet; i++) {
    allTasks.push({ w, i });
  }
}
for (let i = 0; i < allTasks.length; i += CONCURRENCY) {
  const batch = allTasks.slice(i, i + CONCURRENCY);
  await Promise.all(batch.map(async ({ w }) => {
    try {
      await cdp.evm.requestFaucet({ address: w.address, network: "base-sepolia", token: "eth" });
      dripsOK++;
    } catch (e) {
      dripsFail++;
    }
  }));
  if (i % 50 === 0) process.stdout.write(`  drips ${dripsOK}ok/${dripsFail}fail of ${i + CONCURRENCY}/${allTasks.length}\r`);
}
console.log(`\nDrip phase: ${dripsOK}/${allTasks.length} ok, ${dripsFail} failed (${((Date.now() - t0) / 1000).toFixed(1)}s)`);

// Wait for txs to confirm. 10s is too short on Base Sepolia — drips
// landed in wallets after sweep read stale balance=0, stranding ETH
// in ephemeral keys we can't recover. 30s is empirically safer.
await new Promise(r => setTimeout(r, 30000));

// Sweep phase
let sweepOK = 0, sweepFail = 0, totalSwept = 0n;
const feeData = await rpc.getFeeData();
const gasPrice = feeData.gasPrice ?? 1000000000n;
const gasReserve = 21000n * gasPrice * 2n; // 2x safety margin

// Persist ephemeral private keys BEFORE sweeping, so if a wallet's drip
// confirms after the script exits we can recover it with a follow-up
// sweep run instead of stranding the ETH permanently.
const keyPath = process.env.HOME + `/.cdp-harvester-keys-${Date.now()}.json`;
fs.writeFileSync(keyPath, JSON.stringify(wallets.map(w => w.privateKey), null, 2));
console.log(`Saved ${wallets.length} ephemeral keys → ${keyPath}`);

const sweepBatchSize = 20;
const unswept = [];
for (let i = 0; i < wallets.length; i += sweepBatchSize) {
  const batch = wallets.slice(i, i + sweepBatchSize);
  await Promise.all(batch.map(async (w) => {
    try {
      const bal = await rpc.getBalance(w.address);
      if (bal <= gasReserve) {
        sweepFail++;
        unswept.push(w.address);
        return;
      }
      const value = bal - gasReserve;
      const tx = await w.sendTransaction({ to: target, value, gasLimit: 21000n });
      await tx.wait(1);
      sweepOK++;
      totalSwept += value;
    } catch (e) {
      sweepFail++;
      unswept.push(w.address);
    }
  }));
}
if (sweepOK === wallets.length) {
  fs.unlinkSync(keyPath);
  console.log(`All swept cleanly — removed key file.`);
} else if (unswept.length) {
  console.log(`${unswept.length} wallets unswept; keys retained at ${keyPath} for recovery.`);
}

const elapsedMin = ((Date.now() - t0) / 60000).toFixed(1);
console.log(`Sweep phase: ${sweepOK}/${wallets.length} ok, ${sweepFail} skipped`);
console.log(`TOTAL: ${formatEther(totalSwept)} ETH in ${elapsedMin}min to ${target}`);
