#!/usr/bin/env node
// Loop CDP faucet with concurrency, stopping when rate-limited.
// Usage: node scripts/cdp-faucet-loop.mjs <address> <max-attempts>

import { CdpClient } from "@coinbase/cdp-sdk";
import fs from "node:fs";

const envPath = process.env.HOME + "/.cdp-faucet.env";
const env = {};
for (const line of fs.readFileSync(envPath, "utf8").split("\n")) {
  const m = line.match(/^([A-Z_]+)=(.*)$/);
  if (m) env[m[1]] = m[2].trim();
}
const cdp = new CdpClient({ apiKeyId: env.CDP_API_KEY, apiKeySecret: env.CDP_API_SECRET });

const address = process.argv[2];
const maxAttempts = parseInt(process.argv[3] || "20", 10);
let success = 0, fail = 0;

for (let i = 0; i < maxAttempts; i++) {
  try {
    const res = await cdp.evm.requestFaucet({ address, network: "base-sepolia", token: "eth" });
    success++;
    console.log(`[${i+1}/${maxAttempts}] OK tx=${res.transactionHash}`);
  } catch (e) {
    fail++;
    console.log(`[${i+1}/${maxAttempts}] FAIL ${e.message?.slice(0, 200)}`);
    if (e.message?.includes("rate") || e.message?.includes("limit") || e.message?.includes("quota")) {
      console.log("Rate-limited, stopping.");
      break;
    }
  }
  await new Promise(r => setTimeout(r, 200));
}
console.log(`DONE: ${success} ok, ${fail} failed`);
