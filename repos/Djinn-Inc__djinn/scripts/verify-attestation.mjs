#!/usr/bin/env node
// Verify that the bundle currently being served at djinn.gg matches
// the bundle attested via parallel paths:
//   - DNSLink TXT     `_dnslink.djinn.gg` (via DoH at cloudflare-dns.com)
//   - ENS contenthash `djinn.eth`         (via mainnet RPC)
//   - DNSSEC          AD bit on apex SOA  (via DoH; treated as warn)
//
// Exits 0 when DNSLink and ENS resolve to the same CID; non-zero
// (with a failure summary) when they don't, or when any path errors.
// DNSSEC is reported but not gating until P1-32 (a) is toggled.
//
// Usage: node scripts/verify-attestation.mjs [host] [ens-name]
//   defaults: host=djinn.gg ens-name=djinn.eth
//
// Env:  L1_RPC_URL   Ethereum mainnet RPC (default: cloudflare-eth.com)

import { ethers } from "ethers";
import contentHash from "@ensdomains/content-hash";

const host = process.argv[2] ?? "djinn.gg";
const ensName = process.argv[3] ?? "djinn.eth";
const rpcUrl = process.env.L1_RPC_URL ?? "https://ethereum.publicnode.com";

const result = {
  host,
  ensName,
  dnslink: { ok: false, cid: null, error: null },
  ens: { ok: false, cid: null, error: null },
  dnssec: { ok: false, ad: false, error: null },
  match: null,
};

async function doh(name, type) {
  const url = `https://cloudflare-dns.com/dns-query?name=${name}&type=${type}`;
  const res = await fetch(url, {
    headers: { Accept: "application/dns-json" },
  });
  if (!res.ok) throw new Error(`DoH ${name}/${type} HTTP ${res.status}`);
  return res.json();
}

try {
  const data = await doh(`_dnslink.${host}`, "TXT");
  const txt = (data.Answer ?? [])
    .map((a) => a.data.replace(/^"|"$/g, ""))
    .find((s) => s.startsWith("dnslink="));
  if (!txt) throw new Error("no dnslink= TXT record");
  const m = txt.match(/dnslink=\/ipfs\/([A-Za-z0-9]+)/);
  if (!m) throw new Error(`unexpected dnslink format: ${txt}`);
  result.dnslink.cid = m[1];
  result.dnslink.ok = true;
} catch (e) {
  result.dnslink.error = String(e.message ?? e);
}

try {
  const apex = await doh(host, "SOA");
  result.dnssec.ad = apex.AD === true;
  result.dnssec.ok = apex.AD === true;
} catch (e) {
  result.dnssec.error = String(e.message ?? e);
}

try {
  const provider = new ethers.JsonRpcProvider(rpcUrl);
  const ENS_REGISTRY = "0x00000000000C2E074eC69A0dFb2997BA6C7d2e1e";
  const REGISTRY_ABI = [
    "function resolver(bytes32 node) view returns (address)",
  ];
  const RESOLVER_ABI = [
    "function contenthash(bytes32 node) view returns (bytes)",
  ];
  const node = ethers.namehash(ensName);
  const registry = new ethers.Contract(ENS_REGISTRY, REGISTRY_ABI, provider);
  const resolverAddr = await registry.resolver(node);
  if (resolverAddr === ethers.ZeroAddress) {
    throw new Error(`${ensName} has no resolver (not registered yet?)`);
  }
  const resolver = new ethers.Contract(resolverAddr, RESOLVER_ABI, provider);
  const raw = await resolver.contenthash(node);
  if (!raw || raw === "0x") {
    throw new Error("contenthash empty (set in ENS app first)");
  }
  const codec = contentHash.getCodec(raw.slice(2));
  if (codec !== "ipfs-ns") {
    throw new Error(`expected ipfs-ns codec, got ${codec}`);
  }
  result.ens.cid = contentHash.decode(raw.slice(2));
  result.ens.ok = true;
} catch (e) {
  result.ens.error = String(e.message ?? e);
}

if (result.dnslink.ok && result.ens.ok) {
  result.match = result.dnslink.cid === result.ens.cid;
}

console.log(JSON.stringify(result, null, 2));

const lines = [
  `host=${host}`,
  `ensName=${ensName}`,
  `dnslink: ${result.dnslink.ok ? `OK cid=${result.dnslink.cid}` : `FAIL ${result.dnslink.error}`}`,
  `ens:     ${result.ens.ok ? `OK cid=${result.ens.cid}` : `FAIL ${result.ens.error}`}`,
  `dnssec:  ${result.dnssec.ok ? "OK (AD bit set)" : `WARN ${result.dnssec.error ?? "AD bit not set; enable DNSSEC at registrar"}`}`,
  `match:   ${result.match === true ? "OK both paths agree" : result.match === false ? `MISMATCH dnslink=${result.dnslink.cid} ens=${result.ens.cid}` : "n/a (one or both paths failed)"}`,
];
console.error(lines.join("\n"));

if (!result.dnslink.ok || !result.ens.ok || result.match === false) {
  process.exit(1);
}
process.exit(0);
