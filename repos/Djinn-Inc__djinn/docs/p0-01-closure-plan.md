# P0-01 Closure Plan (2026-05-05)

A working plan, written after a long session of reactive shipping. The goal is to stop whack-a-mole, capture the full picture, and let any future session resume coherently.

## Status update 2026-05-07 ~05:50Z (post stop-gate, post fleet propagation)

**Verdict: stop-gate elapsed, P0-01 NOT closed, root cause is upstream of v1732.**

Re-checked the full chain + fleet today. Two days post-handoff and the natural-quorum window has closed without an `AuditSettled`. The convergence-layer fixes (v1714-v1732) propagated successfully but the underlying data-availability problem they assumed away is the actual gate.

### What's true now

Fleet on v1732 or v1732+N (commit-count drift only, no behavioral change):
- UID 0 v1732+22, UID 1 v1732+8, UID 2 v1732+21, UID 86 v1732+21, UID 179 v1732, UID 213 v1732. UID 189 (161.97.150.248) ssh up but axon port 8421 connection-refused — process down, not our box.

Chain (Base Sepolia, block 41178581):
- 0 `VoteSubmitted` in last 9000 blocks (~30h)
- 0 `QuorumReached`, 0 `AuditSettled` in last 9000 blocks
- Last `VoteSubmitted` at block 41134796 (~6 days ago); 12 lifetime votes, all on disjoint pairs
- 117 `ValidatorHeartbeat` events in last 9000 blocks (validators alive, not voting)
- Audit, OutcomeVoting, Escrow all unpaused; OV.getValidators() = 6 signers; OV.activeWindow = 1800s; Audit.autoEarlyExitDelay = 86400s (1 day)

Validator metrics (cumulative across uptimes):
- vote_submit_outcomes_total{outcome="submitted"}: UID 0 = 1, UID 1 = 2, UID 213 = 9, UIDs 2/86/179 = 0. Total 12 lifetime. Matches chain exactly.
- vote_submit_outcomes_total{outcome="pregate_skip"}: UID 0 = 3, UID 1 = 51, UID 213 = 103. Sub-MIN_BATCH submits gated on auto-early-exit timeout (24h since last purchase) which doesn't fire because new purchases keep landing in fresh cycles.
- shadow_settle_outcomes_total{outcome="abstain_no_batch"}: UID 0 = 970/1144 (84.8%), UID 1 = 2630/3149 (83.5%), UID 213 = 3815/3979 (95.9%). MPC produces no batch result.
- build_pi_abstain_reason_total: missing_share = 571 (UID 0), missing_bpa_wpa = 369, vector_mismatch = 30. **The dominant blocker is signal-level data availability, not pregate.**
- share_recovery_result_total: 11936 skip_present (51.8%) / 6624 peer_404 (28.7%) / 3079 peer_unreachable (13.4%) / 1386 no_peer_had_it (6.0%). About half of cross-validator share lookups fail.

Local audit_set summary:
- UID 0: 73 ready_for_settlement, 24 marked-settled-locally (most are stale from earlier process lifetimes), 4 waiting_for_outcomes
- UID 179: 29 ready, 0 settled (resolution-only role, no shares)

UID 0 log evidence:
- `shadow_settle_no_batch batch_is_none=true batch_len=0 signal_count=19 resolved_count=19` for (G0, 0x94cf...) — all 19 signals resolved on the audit-set side, but build_pi can't produce inputs because shares/odds are missing per signal.

### What this means

The stop-gate's optimistic path ("fleet at v1732 + cohort 10 PIDs backfilled + chain shows quorum") didn't fire because **v1732 was a convergence-layer fix, not a data-availability fix**. With SHAMIR_MAX=3 and 6 active validators, every signal is split into 3 shares distributed to a random 3-of-6 subset. The validator that wants to settle a 10-purchase batch must, for each of 10 signals, either hold 2-of-3 shares locally (rare) or recover 1+ shares from peers. With ~50% peer-recovery hit rate, the probability of full recovery for a 10-signal batch is approximately 0.5^10 ≈ 0.1%. Empirically: 84-96% abstain_no_batch matches.

The bug chain's layer 11 ("liveness-aware quorum: already enabled, no fix needed") is wrong in a different sense than the closure plan called out. Quorum-on-paper is fine; the gate is *anyone-builds-a-valid-batch-at-all*.

### Real-fix options

1. **Raise SHAMIR_MAX to N (=number of active validators).** Every validator gets a share for every signal. build_pi never needs peer recovery. Bundle size grows ~Nx at commit time (acceptable: SDK already streams). Storage grows linearly. Most aligned with whitepaper intent.
2. **Implement v1734 per-purchase Merkle-verified BPA/WPA fetch.** Surgical, addresses the missing_bpa_wpa half but not the missing_share half. Bigger code change.
3. **Re-replicate shares on the receiving validator's request (gossip-on-demand at settle time).** Existing /v1/share-recovery is this; the recovery is unreliable because peers also lack the share. Improving this requires improving share-distribution at commit time, which loops back to (1).
4. **Lower contract MIN_BATCH_SIZE from 10 to 2 via UUPS upgrade.** Doesn't help: the bottleneck is build_pi returning None, not a small batch reaching submit.

### Recommendation

Ship (1): SHAMIR_MAX=6 (or `len(active_validators)`) on the genius commit path. This is a client-side change in `web/app/genius/signal/new/page.tsx` plus consistency assertion in the validator. Backwards-compatible: legacy 2-of-3 commits still settle the way they always did (unreliably); new commits become reliable. Combine with a /docs note that quorum is now "any 2-of-N validators" rather than "the right 2-of-3".

This is no longer a stop-gate-of-patience situation. The data-distribution geometry is wrong by design at scale; the convergence work was necessary but not sufficient.

---

## Current state (snapshot 2026-05-05 ~04:40Z)

### What's shipped this loop session (v1714-v1732)

Convergence layer (v1714-v1722):
- v1714: deterministic ready_sets sort by (genius, idiot, cycle)
- v1715: head-of-queue settle (drop v1696's per-validator round-robin offset)
- v1716: per-set abstain counter + eviction at threshold
- v1717: reset_abstain on push-gossip arrival
- v1718: default abstain threshold 5 → 2
- v1719: tighten share-recovery peer timeouts 5s → 2s
- v1720: add_signal in /v1/signal/{id}/purchase + audit-set gossip ⚠️ this introduced the v1732 bug
- v1721: retry-until-acked purchase_odds gossip
- v1722: stress-scale retry bundle delivery until 4+ acks

Codex audit fixes (v1723-v1728):
- v1723: buyer_signature mandatory by default
- v1724: lock-on-first-write for signal registration
- v1725: DNS-pinned target IP for attestation SSRF
- v1726: bind scope into wallet challenge nonce
- v1727: admin login hardening (rate limit + HMAC compare + secret separation + bearer fallback removal)
- v1728: next 14.2.25 → 14.2.35 (CVE patches)

Network resilience (v1729):
- Bumped /api/network/config validator-identity probe 5s → 10s

Bootstrap floor (v1730):
- DJINN_BOOTSTRAP_MIN_BLOCK env to skip legacy unsettleable backlog
- Active on UID 0 with floor=41085000
- UID 0 audit_set_store.db wiped, bootstrap rebuilt clean

MPC reliability (v1731):
- Pre-probe peers via /v1/identity, drop slow ones from participant_map BEFORE running MPC
- Addresses 94% of protocol_failed (UID 1 had 16 of 17 = ReadTimeout)

Purchase ID backfill (v1732):
- v1720 silently used purchase_id=0 in audit_set.add_signal because the validator's purchase handler runs BEFORE the on-chain Escrow.purchaseV2 call
- audit_set.add_signal had a dedup guard that short-circuited duplicates, so bootstrap's later add (with the chain-derived purchase_id) was dropped
- Result: build_purchase_inputs produced batches with [0, 0, ..., 0] purchase_ids, OutcomeVoting.submitVote reverted on PurchaseIdsNotSorted (0 <= 0)
- Confirmed: tx 0xd91f9230... at block 41089761 was UID 0's first observed instance
- Fix: when add_signal sees an existing signal with purchase_id=0 AND the new add provides a non-zero purchase_id, backfill (and persist to SQLite). Other fields stay first-writer-wins.

Operational changes:
- Split-brain UID 0 resolved (37.60.251.252 shut down on Contabo, /root/djinn moved to backup dir)
- Audit.autoEarlyExitDelay lowered 45 days → 1 day via timelock (contract floor)

### Fleet state at handoff

- UID 0: v1732 (canonical, 161.97.138.250). Cohort 10 PIDs backfilled to [1525-1534].
- UID 1: v1731 (167.150.153.103). Pending v1732 watchtower pull. Audit_set still has purchase_id=0 for cohort 10.
- UID 2: v1730 (34.58.165.14). Pending v1731 + v1732. Bundle dropped 1 of 10 cohort 10 signals while it was briefly down.
- UID 86: v1729 (192.150.253.122). Pending v1730 + v1731 + v1732.
- UID 213: v1730 (3.150.72.96). Pending v1731 + v1732.

### Chain state

- 8 historical VoteSubmitted (last batch was UID 1 + UID 2 + UID 86 converging on (G0, 0x0680356e) earlier today, never reached 4-of-5)
- 1 reverted submitVote tx from UID 0 (the all-zero PIDs payload that triggered v1732)
- 0 QuorumReached, 0 AuditSettled today

## Bug chain we found this session

In dependency order. Each layer was hidden by the layer above it.

1. **Convergence ordering**: validators iterated audit_set in dict-insertion order, divergent across the fleet. Fixed v1714/1715/1716.
2. **Eviction stickiness**: false-evictions stuck forever. Fixed v1717.
3. **Eviction speed**: legacy backlog took hours to clear at threshold=5. Fixed v1718.
4. **Recovery timeouts**: dead peers consumed full 5s × N attempts. Fixed v1719.
5. **Audit_set never created on purchase**: cohort 9/10 had BPA/WPA but no audit_set entry → invisible to settlement. Fixed v1720 (introduced bug 11).
6. **Gossip drops on 504**: single-shot delivery; UID 1+86 routinely 504. Fixed v1721 + v1722.
7. **Validator discovery dropped UID 0**: 5s probe timeout flaked into 5-min cache → Vercel API returned 4 of 5 validators → stress fanned to incomplete set. Fixed v1729.
8. **Legacy backlog churn**: pre-gossip-era pairs without recoverable shares dominated UID 0's queue. Fixed v1730.
9. **MPC ReadTimeout aborts**: any single peer's slow response aborted the whole batch settle attempt (not just that peer). Fixed v1731.
10. **Reverted submit on bad PIDs**: build_pi assembled batch from audit_set entries that had purchase_id=0 (legacy of bug 5's fix). Fixed v1732.
11. **Liveness-aware quorum**: already enabled (activeWindow=1800), no fix needed. Quorum threshold = ceil(active*2/3).

## Outstanding things

### Pending fleet propagation (no action needed, just wait)

- UID 1, 2, 86, 213 pull v1732 via watchtower (~30 min cycle)
- After pull + bootstrap re-runs, each validator backfills cohort 10 PIDs to [1525-1534]
- Then settle attempts produce valid batches with same batchKey across the fleet

### Open architectural concerns (not blocking quorum but worth knowing)

- **MPC quality_score_out_of_range** (3 instances, UID 1 + UID 2): MPC reconstruction occasionally produces a BN254 field-element artifact instead of a real score. Currently locally rejected. Doesn't block honest votes from settling, but indicates instability in some signal subsets.
- **Bundle commit-time replication is best-effort**: even with v1722 retry, UID 2 missed 1 of 10 cohort 10 signals (it was briefly down). Recovery from peers should self-heal but doesn't always.
- **Wallet challenge replay within TTL**: v1726 closed scope-substitution; replay-with-same-scope still possible until KV-backed nonce blacklist is added (requires Vercel KV or Redis infra).
- **EOA signer = deployer wallet**: same key controls validator votes AND timelock proposals. Filesystem read on any validator gets both. Should migrate to a hardware-wallet signer separated from deployer.

### Decision points needing user input

- **Whether to ship retry-until-acked outcome gossip (v1733)**: same pattern as v1721 (purchase_odds), addresses the "UID 1 lagged 1/10 outcomes" gap. Low-risk extension, but waiting until v1732 settles to avoid more churn during fleet propagation.
- **Whether to ship per-purchase Merkle-verified BPA/WPA fetch (v1734)**: the fundamental data-fragmentation fix proposed earlier in the session. Bigger surgery.
- **Whether to migrate signer EOA off deployer wallet**: operational change, requires new wallet provisioning + timelock setter.

## Stop-condition gate before next ship

**Do nothing more code-wise until ALL of these are observed:**

1. Fleet versions all show v1732 (or higher) on /health
2. Each validator's cohort 10 audit_set detail shows non-zero purchase_ids
3. Either:
   - 4 matching VoteSubmitted events with same batchKey on chain → quorum forms naturally → AuditSettled fires → P0-01 closed
   - OR 1-2 hours pass without UID 1/2/213 reaching cohort 10 in their settle queue → root-cause investigation resumes

**Updated 2026-05-05 03:53Z (downgraded from "3 days" — that was absurd).**
The 3-day window assumed every fix would need a new fleet-propagation cycle.
With v1732 deployed and UID 0 voting on cohort 10 successfully (block
41092269), the actual gating constraint is UIDs 1/2/213 sweeping through
their 102-audit-set backlog at the abstain-eviction rate (threshold=2,
~10 pairs/min). Cohort 10 should be reached within tens of minutes, not
days. Monitoring loop runs every 10-15 min.

The 8 hours of code shipping fixed real bugs but the rate of churn
outpaced the fleet's ability to absorb. Restraint on shipping was right;
patience on monitoring was wrong. Watch the chain, attack at the next
real blocker if convergence doesn't happen on the natural eviction
schedule.

## How to resume in a new chat

- `/work continue P0-01 per docs/p0-01-closure-plan.md` — the explicit handoff
- Or `/work` — I'll discover this doc via git log + MAINNET_BLOCKERS link + memory pointer

A clean-context session should:
1. Read this plan (gives full state without the conversation)
2. Check chain VS/QR/AS to learn what happened since the doc was committed
3. Check fleet versions to see propagation state
4. Honor the stop-condition gate above

## What "done" looks like for P0-01

Single criterion: a non-force-settle `AuditSettled` event on Base Sepolia from any cohort.

When that fires:
- Update MAINNET_BLOCKERS.md P0-01 to **CLOSED**
- Save a memory: `project_p0_01_closed_2026_NN_NN.md` with the tx hash + cohort + which validators voted
- Telegram ship notification

That's the only finish line. Everything else is preparatory.
