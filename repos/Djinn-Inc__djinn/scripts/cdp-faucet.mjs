#!/usr/bin/env node
// Request Base Sepolia ETH from Coinbase CDP faucet via API.
// Uses CDP v2 SDK with API key ID + base64-encoded EC private key.
// Usage: node scripts/cdp-faucet.mjs <address>

import { CdpClient } from "@coinbase/cdp-sdk";
import fs from "node:fs";

const envPath = process.env.HOME + "/.cdp-faucet.env";
const envContent = fs.readFileSync(envPath, "utf8");
const env = {};
for (const line of envContent.split("\n")) {
  const m = line.match(/^([A-Z_]+)=(.*)$/);
  if (m) env[m[1]] = m[2].trim();
}

const apiKeyId = env.CDP_API_KEY;
const apiKeySecret = env.CDP_API_SECRET;
if (!apiKeyId || !apiKeySecret) {
  console.error("Missing CDP_API_KEY or CDP_API_SECRET in ~/.cdp-faucet.env");
  process.exit(1);
}

const address = process.argv[2];
if (!address || !/^0x[0-9a-fA-F]{40}$/.test(address)) {
  console.error("Usage: node cdp-faucet.mjs <0x-address>");
  process.exit(1);
}

const cdp = new CdpClient({ apiKeyId, apiKeySecret });

try {
  const res = await cdp.evm.requestFaucet({
    address,
    network: "base-sepolia",
    token: "eth",
  });
  console.log(JSON.stringify({ ok: true, address, ...res }, null, 2));
} catch (e) {
  console.error(JSON.stringify({ ok: false, address, error: e.message, name: e.name }, null, 2));
  process.exit(1);
}
