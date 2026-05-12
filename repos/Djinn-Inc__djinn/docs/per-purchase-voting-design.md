# Per-purchase voting (P1-37 reframe)

**Date:** 2026-05-05
**Status:** design-draft, awaiting decision
**Author:** loop session response to "zoom out and rethink how settlement works"

## TL;DR

Replace the per-batch consensus unit (`batchKey = keccak(genius, idiot,
keccak(purchase_ids))`) with per-purchase consensus
(`voteKey = keccak(genius, idiot, signal_id, purchase_id)`).

Each (genius, idiot, signal, purchase) tuple becomes its own consensus
unit. Validators vote on individual purchases as their data is ready;
4-of-5 agreement on a single purchase fires a per-purchase
`PurchaseSettled` event that updates the on-chain track record
incrementally.

Eliminates batchKey divergence by removing batches entirely.

## What's wrong with the current model

The protocol commits a (signal, purchase) tuple per buyer. Settlement
batches all purchases on a (genius, idiot, cycle) pair into a single
`audit_set` entry. Validators each compute MPC over the WHOLE batch at
once, producing one quality-score-sum per batch.

The chain consensus unit is `batchKey = keccak(genius, idiot,
keccak(purchase_ids))`. The trouble:

1. **Each validator's local audit_set is a different subset.** Bootstrap
   timing, gossip drops, share-recovery failures, BPA/WPA prefetch
   misses — all cause divergence in WHICH purchase_ids each validator
   has full data for.
2. **build_pi requires a complete row per signal** (share + BPA + WPA +
   outcome). A validator missing one of those for purchase 5 of 10
   can't include purchase 5 in its batch. Its batchKey for the 9-pid
   subset differs from a peer's 10-pid full set.
3. **Each validator votes once per (genius, idiot) pair.** First vote
   wins the slot; if subsets differ, the 4-of-5 quorum can never form.
4. **Recovery is structural, not transient.** Even with perfect gossip,
   different bootstrap windows guarantee divergence on fresh purchases
   while older legacy pairs sit half-recovered.

We've been fighting this for ~10 days with v1714-v1732, all of which
move the needle on data layer reliability without addressing the
unit-of-consensus mismatch.

## The reframe

Disaggregate. The unit of consensus becomes one purchase, not one
batch.

```text
Old: vote(batchKey, qualityScoreSum, totalNotional)
New: vote(voteKey, qualityScoreDelta, notional)
     where voteKey = keccak(genius, idiot, signal_id, purchase_id)
```

Each purchase is a primitive. Validators vote on a single purchase's
contribution to the genius's track record as soon as they have:
- Their Shamir share for the signal
- BPA + WPA for the purchase
- The signal's outcomes resolved

No batching. No subset divergence. Quorum is "4-of-5 agree on this one
purchase's score delta", which is far easier to converge on than "4-of-5
agree on this batch composition AND the score sum across it."

## How the protocol changes

### Contract layer

`OutcomeVoting.sol`:
- Add `submitVoteV3(genius, idiot, signal_id, purchase_id,
  qualityScoreDelta, totalNotional, scoreHash, sig)` alongside the
  existing `submitVote(batchKey, ...)`. Both routes coexist while we
  migrate.
- New event: `PurchaseVoteSubmitted(voteKey indexed, address indexed
  validator, int256 qualityScoreDelta, uint256 totalNotional)`.
- New event: `PurchaseSettled(genius indexed, idiot indexed, signal_id,
  purchase_id, qualityScoreDelta, settledAtBlock)` — fires when 4-of-5
  validators converge on the same scoreHash for one voteKey.
- `mapping(bytes32 voteKey => mapping(bytes32 scoreHash => uint256
  count))` per-vote tally, mirroring current per-batch structure.
- `mapping(bytes32 voteKey => bool)` settled flag.

`Audit.sol`:
- Add `recordPurchaseSettlement(genius, idiot, signal_id, purchase_id,
  qualityScoreDelta)` callable only by OV. Persists per-purchase
  outcome on chain.
- Aggregate genius track record via the existing
  `Account._effectiveCounts` (already keys on (genius, idiot) and could
  store per-purchase contributions). Sum-on-read or sum-on-write —
  pick.

`Account.sol`:
- Add `recordPurchaseQualityDelta(genius, idiot, signal_id,
  purchase_id, delta)` — appends to per-purchase ledger and updates
  aggregate score for the (genius, idiot) pair.

### Validator layer

Replace the batched `mpc_batch_settlement` path with a per-purchase
runner:

```python
async def settle_purchase(signal_id, purchase_id, genius, idiot):
    # Build single-purchase pi vector
    if not (have_share(signal_id) and have_bpa_wpa(purchase_id)
            and outcomes_resolved(signal_id)):
        return abstain(reason="missing_data")
    pi = build_purchase_inputs([signal_id], [purchase_id])
    score_delta = await mpc_orchestrator.run_single_purchase(pi)
    submit_vote_v3(genius, idiot, signal_id, purchase_id, score_delta)
```

The settle loop iterates `(signal_id, purchase_id)` tuples instead of
audit_set entries:

```python
for purchase in get_unresolved_purchases():
    if not voted_locally(purchase):
        await settle_purchase(*purchase)
```

The current 12s-budgeted head-of-queue sweep maps cleanly onto the
new loop — process one purchase per iteration, evict purchases that
abstain N times in a row (same v1716-v1718 logic, smaller unit).

### MPC layer

Per-purchase MPC is **simpler than per-batch**. Today's
`mpc_batch_settlement.py` runs Lagrange evaluation across all purchases
in the batch, summing share-by-share. The per-purchase variant:

- Inputs: shares of `realIndex` for one signal (from threshold
  validators), one gain_vector (10 lines), public BPA/WPA + outcomes.
- Output: shares of `gain_vector[realIndex]`, opened to give a single
  `score_delta`.

This is essentially `mpc_outcome.secure_select_outcome` already shipped
for outcome-enum selection. Reuse it, swap the gain_vector for the
public per-line aggregate.

No batch summation. No `quality_score_out_of_range` from mixing 10
signals' field-element artifacts. No protocol_failed cascading aborts
from one slow peer.

### Subgraph layer

Add `PurchaseSettlement` entity keyed on (genius, idiot, signal_id,
purchase_id). Aggregate views (`Genius.aggregateQualityScore`) become
sum-of-PurchaseSettlement instead of sum-of-BatchSettlement.

Backward compat: existing batch-settled pairs stay in the
`AuditSettled` event stream; the subgraph reads both event types and
unions them.

## Migration plan

Three-phase rollout, additive (per
`project_additive_upgrade_pattern.md`):

### Phase 1 — opt-in flag (1 week, code only)

- Ship `submitVoteV3` + `PurchaseVoteSubmitted` + `PurchaseSettled`
  events on a UUPS upgrade. Existing `submitVote` path untouched.
- Validator feature flag `DJINN_FF_PURCHASE_VOTING=false` default.
  Operators can flip ON to start dual-voting (votes both per-batch and
  per-purchase). Both paths succeed independently.
- Dashboard reads from BOTH paths; if either has a settled record,
  surface it.

### Phase 2 — fleet enables (1-2 weeks operational)

- Coordinated operator switch to `DJINN_FF_PURCHASE_VOTING=true` (UID 0
  first as canary). Verify per-purchase quorum forms within 1 cycle.
- Once 4-of-5 are flagged on, batch-voting becomes a fallback only.
- New stress-scale traffic exercises per-purchase quorum from day one.
- Track-record on-chain updates start firing per-purchase, not waiting
  for batch settlement.

### Phase 3 — deprecate batch path (1 month after Phase 2)

- Validators stop calling `submitVote`. Code path stays in the binary
  for 1 release cycle, then removed.
- Old `audit_set_store` retained for historical query. New work uses
  the per-purchase `purchase_settlements` table.
- Subgraph migrates fully to PurchaseSettlement entities.

## What it costs

- **More chain transactions**: 10 votes for a 10-purchase signal vs 1
  batch vote. On Base Sepolia ~$0.0001/vote, on Base mainnet
  $0.005-0.05/vote. For 10-purchase signals: ~$0.05-0.50 per signal at
  mainnet, vs $0.005-0.05 today. Acceptable for the protocol's promise
  of public verifiability per purchase.
- **More chain events to index**: subgraph throughput ~10x. Currently
  trivial (we're handling tens per day); 100x at scale is still trivial
  for The Graph.
- **More MPC sessions**: 10x sessions but each is 1/10th the size, so
  total MPC compute is roughly the same. Latency per session drops
  significantly (no waiting for slow peers in 10-signal coordination).
- **Larger audit storage on chain**: per-purchase events take more
  storage. Estimated ~200 bytes/purchase × 1k purchases/day = 200kb/day.
  Acceptable.

## What it gains

- **batchKey divergence eliminated.** No subset, no key, no problem.
- **Per-purchase verification.** Buyers can inspect individual
  purchases of a genius's track record on chain, instead of only batch
  aggregates.
- **Granular settlement.** First valid 4-of-5 vote on purchase X
  settles X immediately; doesn't wait for slow purchases in the same
  batch.
- **Recovery resilience.** A validator missing 1 of 10 purchases
  contributes votes for the 9 they have, instead of being excluded
  from the batch entirely.
- **MPC simpler + smaller surface.** Single-purchase MPC has fewer
  failure modes than 10-purchase batch MPC. Drops the
  `quality_score_out_of_range` and `protocol_failed` issues that have
  blocked stress-scale cohorts.
- **Operator UX simpler.** No more "consent for the exact subset I
  built_pi for" (P1-35). Per-purchase consent is uniform: vote or
  don't.

## What stays the same

- **Privacy guarantees identical.** MPC still hides realIndex via
  Lagrange evaluation. Per-purchase outcome opens only the score
  delta, not realIndex itself, so the privacy invariant is unchanged.
- **Stake gating, slashing, fees, escrow** all stay batch-shaped or
  purchase-shaped as today; no change to economic primitives.
- **Track record semantics**: `aggregateQualityScore` is still
  sum-of-purchase-deltas. Just computed at a finer grain.
- **Decoy / line privacy** unchanged. The genius still commits a
  single signal; the buyer still picks a real line; the gain_vector
  still hides which line was real.

## Why we didn't see this earlier

The whitepaper sketched batched audits as the natural settlement unit
because OUTCOME RESOLUTION operates on whole signals (a game has one
score). But VOTE on a quality_score is independent per purchase — each
purchase's score_delta is a function of (real_line_outcome, notional,
sla_bps). Batching was an optimization, not a privacy or correctness
requirement.

Batch optimization made sense pre-MPC (one audit, lower gas). But
batch quorum requires every validator to commit to the same batch
contents, which empirically diverges. The optimization is causing the
correctness problem.

The right answer is what privacy-preserving distributed systems
literature has been saying for years: smaller consensus units with
weaker coordination requirements. Per-purchase voting is the smallest
useful unit. We over-batched.

## Stop conditions to validate this design

Before shipping Phase 1, confirm:

1. `mpc_outcome.secure_select_outcome` already produces the right shape
   for single-purchase score_delta (Lagrange eval on gain_vector at
   shared realIndex). Read the impl, confirm 1:1 reuse.
2. The on-chain `Account.recordPurchaseQualityDelta` doesn't break the
   existing track-record aggregation. Test with mixed batch + per-purchase
   settled history.
3. Validator stake-weighted scoring still incentivizes correct per-purchase
   votes. Check that voting on the wrong score is slashable as today.

## Decision

Two ways to proceed:

**Path A — full reframe.** Adopt per-purchase voting, ship Phase 1
contract upgrade + validator feature flag. ~3-5 days to get to flagged-on
canary. ~2-3 weeks to deprecate batch path.

**Path B — patch the current model.** Stick with batched, fix P1-37 via
"canonical purchase_id source" (fix candidate (a) in MAINNET_BLOCKERS):
validators read `Account.getPairPurchaseIds` at vote time and vote on
the canonical full list; abstain if they're missing data for any
purchase. This unblocks divergence by forcing a canonical batch
composition, but doesn't address the structural over-batching. We've
been here for 10 days; another 1-2 weeks likely.

I lean A. The code is more upfront work but the fix is permanent and
the protocol becomes more transparent.

Awaiting your call.
