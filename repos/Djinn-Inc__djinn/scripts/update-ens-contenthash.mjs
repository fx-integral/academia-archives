#!/usr/bin/env node
// Update djinn.eth ENS contenthash to <cid>, providing a parallel
// attestation path to the Namecheap DNSLink TXT. EIP-1577 contenthash
// is decoded by ENS-aware browsers (Brave, Status, MetaMask via IPFS
// companion) so users can verify the bundle source on-chain.
//
// Usage: node scripts/update-ens-contenthash.mjs <ens-name> <cid>
//   <ens-name>   e.g. "djinn.eth"
//   <cid>        Qm... (CIDv0) or bafy... (CIDv1 base32)
//
// Env:  ENS_PRIVATE_KEY   hex 0x-prefixed key controlling <ens-name>
//       L1_RPC_URL        Ethereum mainnet RPC (default: cloudflare)
//
// The script reads the current contenthash, compares to the target,
// and only sends a tx if they differ. Writes the tx hash to stdout
// as JSON. If the contenthash already matches, no tx is sent and
// {skipped: "already-matching"} is logged.
//
// Encoding (EIP-1577):
//   contenthash = 0xe3010170 + multihash(sha2-256, 32 bytes)
//   = ipfs-ns codec + cidv1 + dag-pb + sha256
// CIDv0 (Qm...) is converted by stripping the 0x1220 multihash prefix
// and re-prefixing with the EIP-1577 wrapper.

import { ethers } from "ethers";
import contentHash from "@ensdomains/content-hash";

const [, , ensName, cid] = process.argv;
if (!ensName || !cid) {
  console.error("usage: update-ens-contenthash.mjs <ens-name> <cid>");
  process.exit(64);
}

const privateKey = process.env.ENS_PRIVATE_KEY;
const rpcUrl = process.env.L1_RPC_URL ?? "https://ethereum.publicnode.com";

if (!privateKey) {
  console.error("ENS_PRIVATE_KEY not set");
  process.exit(65);
}

const targetEncoded = `0x${contentHash.encode("ipfs-ns", cid)}`;
console.error(`[ens] target contenthash: ${targetEncoded}`);

const provider = new ethers.JsonRpcProvider(rpcUrl);
const wallet = new ethers.Wallet(privateKey, provider);

// ENS Public Resolver supports setContenthash(node, hash); we resolve
// the resolver address through the registry, so this works even if
// the name uses a custom resolver instead of the default Public Resolver.
const ENS_REGISTRY = "0x00000000000C2E074eC69A0dFb2997BA6C7d2e1e";
const REGISTRY_ABI = ["function resolver(bytes32 node) view returns (address)"];
const RESOLVER_ABI = [
  "function contenthash(bytes32 node) view returns (bytes)",
  "function setContenthash(bytes32 node, bytes hash)",
];

const node = ethers.namehash(ensName);
const registry = new ethers.Contract(ENS_REGISTRY, REGISTRY_ABI, provider);
const resolverAddr = await registry.resolver(node);
if (resolverAddr === ethers.ZeroAddress) {
  console.error(`[ens] ${ensName} has no resolver set; aborting`);
  process.exit(66);
}
console.error(`[ens] resolver: ${resolverAddr}`);

const resolver = new ethers.Contract(resolverAddr, RESOLVER_ABI, wallet);

const current = await resolver.contenthash(node);
console.error(`[ens] current contenthash: ${current}`);

if (current.toLowerCase() === targetEncoded.toLowerCase()) {
  console.log(JSON.stringify({ skipped: "already-matching", ensName, cid }));
  process.exit(0);
}

console.error(`[ens] sending setContenthash tx…`);
const tx = await resolver.setContenthash(node, targetEncoded);
console.error(`[ens] tx hash: ${tx.hash}`);
const receipt = await tx.wait();
console.error(`[ens] confirmed in block ${receipt.blockNumber}`);

console.log(
  JSON.stringify({
    ensName,
    cid,
    contenthash: targetEncoded,
    txHash: tx.hash,
    blockNumber: receipt.blockNumber,
  }),
);
