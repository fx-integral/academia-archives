#!/usr/bin/env node
// Pin a CID to Crust Network via W3Auth-style Bearer token.
//
// Usage: node scripts/pin-crust.mjs <cid> <name>
//
// Env:  CRUST_PRIVATE_KEY (required) — hex ETH private key; sign wallet
//       address (lowercased) with it, base64(eth-<addr>:<sig>) is the token
//
// Output: stdout = JSON response from Crust PSA; stderr = progress log

import { Wallet } from "ethers";

const [, , cid, name] = process.argv;
if (!cid || !name) {
  console.error("usage: pin-crust.mjs <cid> <name>");
  process.exit(64);
}
const pk = process.env.CRUST_PRIVATE_KEY;
if (!pk) {
  console.error("CRUST_PRIVATE_KEY not set");
  process.exit(65);
}

const wallet = new Wallet(pk);
const address = wallet.address.toLowerCase();
const signature = await wallet.signMessage(address);
const token = Buffer.from(`eth-${address}:${signature}`).toString("base64");
console.error(`[crust] wallet=${address} cid=${cid} name=${name}`);

const res = await fetch("https://pin.crustcode.com/psa/pins", {
  method: "POST",
  headers: {
    Authorization: `Bearer ${token}`,
    "Content-Type": "application/json",
  },
  body: JSON.stringify({ cid, name }),
});
const body = await res.text();
console.error(`[crust] HTTP ${res.status}`);
console.log(body);
if (!res.ok && res.status !== 202) process.exit(66);
