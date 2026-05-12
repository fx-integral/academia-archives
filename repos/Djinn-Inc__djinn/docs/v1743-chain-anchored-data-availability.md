# v1743 design: chain-anchored data-availability proof

**Status:** design proposal, not shipped. Companion to v1736 (drain),
v1740 (bootstrap-time BPA/WPA backfill), v1741 (skip permanent-abstain
sets in the bootstrap pull), and v1742 (`permanently_abstained` bucket
on /v1/audit/summary so operators can see the eligible-to-settle slice
at a glance). The drain prevents the queue from getting stuck on
legacy unsettleable data; the backfill catches gossip misses at boot;
the skip stops wasting work on already-evicted sets; the visibility
fix makes the eviction count auditable. None of these help when the
originating validator's gossip never reached any peer (e.g., originator
restarted before the v1721 retry queue completed) — that data is
effectively lost off-chain and audit settlement deadlocks until manual
intervention.

## Problem

Settlement requires every voting validator to hold three classes of
per-purchase data:
1. **Shamir share** of the AES key (decryptable per-validator via
   SealedBox; recovered from peers via `/v1/share-recovery`).
2. **BPA/WPA vectors** committed at purchase time (Merkle-rooted on
   chain via `Escrow.purchaseV2`; recovered from peers via
   `/v1/purchase_odds/{signal_id}/{buyer}`).
3. **Outcome** for each signal in the batch (resolved per-validator
   via ESPN polling; recovered from peers via outcome gossip).

For each, the validator may not hold the data locally if it was
offline / down / 5xx-ing during the originating fan-out. Currently
the only recovery mechanism is **peer-poll**: ask other validators
who might have it. Three failure modes are unmitigated:

- **Gossip-failed-everywhere**: originator restarted mid-fan-out,
  retry queue (v1721 best-effort) lost the work, no peer has the
  data. peer_404 across the entire fleet. Audit deadlocks.
- **Slow peer-discovery**: a recovering validator doesn't know which
  peers to ask, so it polls all and races. With 6 peers × 5s timeout,
  bootstrap-time backfill takes minutes per missing record.
- **Offline-then-rejoin**: a validator misses 12h of gossip, comes
  back, has no signal that data is missing. Discovery only happens at
  settle-time, by which point the abstain counter may have evicted.

## Design

Add an on-chain availability attestation. After a validator records
BPA/WPA + Shamir share for a purchase (the existing
`_gossip_purchase_odds_to_peers` + share-bundle delivery), it submits
a cheap on-chain transaction:

```solidity
// New on Audit (or new AvailabilityRegistry contract)
event PurchaseDataAvailable(
    uint256 indexed purchaseId,
    address indexed validator,  // EOA = signer
    uint256 timestamp
);

function attestAvailable(uint256 purchaseId) external {
    require(isOVValidator(msg.sender), "not validator");
    emit PurchaseDataAvailable(purchaseId, msg.sender, block.timestamp);
}
```

Cost: one `LOG3` opcode, ~1500 gas on Base ≈ $0.001 per attestation.
Per-purchase × N validators × Y purchases/day. At 100 purchases/day
× 6 validators = 600 attestations/day = ~$0.60/day fleet-wide.

A recovering validator queries the chain (or subgraph) for
`PurchaseDataAvailable` events filtered by `purchaseId` and pulls
directly from the validator(s) attesting availability. No more blind
fan-out.

### Validator-side flow

1. Validator A records purchase locally (BPA/WPA + Shamir share).
2. Validator A submits `attestAvailable(purchaseId)` on Audit.
3. Validator B comes online, sees `purchaseId 1234` in its audit_set
   but no local BPA/WPA.
4. B queries chain for `PurchaseDataAvailable(1234)` → finds A.
5. B GETs `/v1/purchase_odds/1234/buyer_addr` from A's axon URL only.
6. A returns the data; B Merkle-verifies against
   `Escrow.purchaseBpaRoot(1234)`; B writes locally.

### Why this is durable

- **Chain is the canonical "who-has-what" index.** No off-chain
  metagraph poll, no peer rotation, no fan-out. One RPC call gives
  the recovering validator the exact source addresses.
- **Subgraph-friendly**: `PurchaseDataAvailable` is a one-line
  AssemblyScript handler that maintains a `(purchaseId → validator[])`
  inverse index for sub-second queries.
- **Adversarial-safe**: a malicious validator can lie ("I have it!")
  but the recovering validator Merkle-verifies the response against
  the on-chain commitment from `Escrow.purchaseV2`. A lie is
  detectable; the recovering validator falls back to polling other
  attestors.
- **Idempotent**: an already-attested validator can re-attest if
  needed (e.g., after a chain reorg eats the prior event); cost is
  only the gas.

### Bootstrap-time use

When a validator boots with N audit_sets in `ready_for_settlement`
state but missing BPA/WPA for some signals:
- Pull `PurchaseDataAvailable` events for the relevant `purchaseId`s
  in one `eth_getLogs` call (filterable by topic1).
- For each missing record, GET from any one attestor (fan-out to all
  attestors only on first failure).
- v1740's existing `_bootstrap_pull_missing_purchase_odds()` becomes
  the consumer; only the source-discovery step changes.

## Alternatives considered

### A. Persistent retry queue for outbound gossip (cheaper)
Convert `_gossip_purchase_odds_to_peers` from fire-and-forget to
SQLite-backed queue with exponential backoff. Catches the "originator
restarted mid-fan-out" case directly without on-chain cost. Doesn't
help the recovery side: a validator that comes online late still has
to blind-poll. **Verdict:** ship as separate fix; doesn't replace
the chain-anchor design.

### B. Always replicate to N=fleet at commit time (no eviction)
Force `_post_one` to retry until ALL peers ack, blocking the response.
Worst-case latency is dominated by the slowest peer. Operator-hostile
(a slow peer DoS-degrades every purchase) and doesn't catch the
post-commit offline case. **Verdict:** rejected.

### C. Per-validator share index in metagraph commit
Use Bittensor's `commit()` to publish a 128-byte digest of "what I
have" per epoch. Cheaper than chain (no gas) but eventually
consistent (epoch cadence, ~12 min) and limited by the 128-byte
ceiling. **Verdict:** acceptable as a coarse fallback if chain
attestation cost becomes a problem; not strictly needed at fleet
sizes <100.

### D. IPFS-pinned canonical store
Genius pins the BPA/WPA blob to IPFS at commit time; CID stored
in `Escrow.purchaseV2` payload. Validators always fetch from IPFS.
Adds a hard external dependency (per project_ipfs_gateway_decay
2026-04-21: public DNSLink gateways are unreliable; only the
pinner's own gateway is sound). **Verdict:** rejected — re-introduces
the SPOF that decentralized settlement is designed to avoid.

## Implementation surface

- `contracts/src/Audit.sol` (or new `AvailabilityRegistry.sol`):
  add `attestAvailable` + event. ~30 LOC + tests.
- `validator/djinn_validator/api/server.py`: emit attestation after
  successful local record + gossip. ~10 LOC.
- `validator/djinn_validator/core/mpc_orchestrator.py`: extend
  `_prefetch_missing_purchase_odds_from_peers` to query
  `PurchaseDataAvailable` first, only fan-out to attestors. ~40 LOC.
- `subgraph/`: `handlePurchaseDataAvailable` + new entity
  `PurchaseAvailability { id: purchaseId, validators: [Bytes!] }`.
  ~20 LOC AssemblyScript + schema bump.
- `MAINNET_BLOCKERS.md`: link from P0-01 once shipped.

Estimate: 1-2 days for contract + tests + validator wiring. Subgraph
deploy adds dependency on Graph Studio.

## Decision

**Defer until v1740 + v1722-style retry queue land and the metric
record proves the off-chain paths can't reach >95% recovery alone.**
Currently `purchase_odds_prefetch_result_total{outcome="recovered"} = 0`
on UID 0, meaning even the simple peer-poll never recovers anything.
That's strong evidence the source-side gossip is the bug, not the
recovery side. Fix the source first; chain-anchor is the safety net
when the source-side is provably reliable but transport is still lossy.

Ship order:
1. v1740 (shipped) — bootstrap-time peer-pull.
2. v1741 (shipped) — skip `permanent_abstain >= threshold` sets in
   the bootstrap pull so we don't burn cycles re-probing the legacy
   backlog whose data is empirically lost. Saves ~7 min per bootstrap
   cycle on UID 0 once the queue is drained.
3. v1742 (shipped) — surface `permanently_abstained` on
   /v1/audit/summary so operators can see eligible-to-settle =
   ready_for_settlement - permanently_abstained at a glance.
4. v1744+ (next) — persistent retry queue for outbound gossip
   (alternative A in this doc). Source-side fix; ship before this
   chain-anchored design.
5. v1743 (this design) — chain-anchored availability, only if
   v1740–v1742 + the retry-queue fix leave a measurable gap.
