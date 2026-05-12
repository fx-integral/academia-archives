# v1747 — Per-line canonical outcome registry for audit settlement

## Problem

Six weeks of "next architectural fix" have not closed P0-01. The natural-quorum
settlement path (`OutcomeVoting` 4-of-5 on aggregate quality score) cannot reach
quorum because validators disagree on inputs:

- Each signal has ~1 real line + many decoy lines (privacy mechanism: hide the real pick)
- Each validator independently polls ESPN for every game underlying every line
- ESPN polls race independently across validators (timing, RPC flake, cached data)
- At MPC-settlement time, each validator's resolved subset reflects its local arrival
  state — different per validator
- MPC consumes different inputs across validators → different aggregate scores →
  4-of-5 quorum on the same score is mathematically uncertain

v1744-v1746 made gossip transport durable and widened the abstain eviction window.
Helpful for eventual convergence; does not guarantee it within bounded time. Output-
layer patches chase the symptom; the cause is at the input layer.

## Design

Anchor canonical outcomes on chain at the **per-line** granularity. Each unique
`(sport, event_id, market, side, line_value)` gets resolved once. Signals reference
canonical line outcomes via lineHash. MPC reads canonical outcomes from chain →
deterministic input → deterministic aggregate output across validators → 4-of-5
quorum is trivial.

Per-line canonicalization (not per-signal):
- Naturally deduplicates: 100 signals containing "Lakers -3.5" → one attestation
- Smaller atomic unit: one game, one market, one resolution → one attestation
- Privacy-preserving: per-line outcomes are public ESPN data; the (idiot ↔ line)
  mapping stays in the buyer's encrypted purchase share
- Fraud-proof slot reserved (v2): future TLSNotary-backed challenge can override a
  bad attestation without contract redesign

## Phase 0 — Canonical line schema spec (1 day, prereq)

A separate one-pager: `docs/v1747-line-schema.md`. Defines the canonical decoy-line
string format and resolution rules:

### Decoy line string format

```
<sport>|<event_id>|<market>|<side>|<line_value>
```

- `sport`: lowercase ESPN sport key (`basketball_nba`, `americanfootball_nfl`, ...)
- `event_id`: ESPN canonical event id (string, ASCII)
- `market`: enum {`spread`, `total`, `moneyline`}
- `side`: enum {`home`, `away`} for spread/moneyline; {`over`, `under`} for total
- `line_value`: signed decimal with one decimal place for spread/total
  (e.g. `-3.5`, `+220.0`); empty for moneyline

Validation rules: lowercase sport, exact 4 pipes, no whitespace, ASCII only. Strict.

### lineHash

```
lineHash = keccak256(
    "DJINN_LINE_V1" ||
    chainId ||
    signalCommitmentAddr ||
    decoy_line_string  // exact bytes, validated per above
)
```

Domain-separated. Chain-bound. Address-bound. No ambiguity across forks/chains.

### Resolution rules

For each (`market`, `side`, `line_value`):
- **Spread** (`spread`, `home`, `-3.5`): home team's final score minus away team's
  final score must exceed 3.5 for `Favorable`; equal-or-less is `Unfavorable`. Push
  on exact value (impossible with .5 lines) is `Void`.
- **Total** (`total`, `over`, `220.0`): combined final score > 220 → `Favorable`;
  exact match → `Void`; less → `Unfavorable`.
- **Moneyline** (`moneyline`, `home`): home team won regulation+OT (per ESPN's
  STATUS_FINAL or sport-specific terminal status) → `Favorable`.

### Edge cases (must be deterministic)

- **Postponed games**: `Void` if not played within 7 days of original event start;
  otherwise `Pending` until played.
- **Cancelled games**: `Void`.
- **Stat corrections**: ESPN data is canonical at `expiresAt + 6h` for all sports.
  Corrections after that window are NOT reflected in the canonical outcome.
- **Overtime**: included in moneyline; spread/total resolve on full final score
  including overtime per ESPN's published box score.
- **Push on integer spreads**: `Void` if exact match (rare with .5 convention but
  possible with whole-number specials).

This schema is the load-bearing piece. Without it, "validators agree on lineHash"
just relocates ambiguity. With it, `lineHash` deterministically identifies a single
public truth.

## Phase 1 — On-chain per-line outcome registry (1-2 days)

Extend `OutcomeAttestor.sol` (or new contract; both fine):

```solidity
enum Outcome { Pending, Favorable, Unfavorable, Void }

// Canonical outcome per line. Pending until threshold reached.
mapping(bytes32 => Outcome) public lineOutcome;

// Per-line attestation tracking.
mapping(bytes32 => mapping(address => Outcome)) private _lineClaims;
mapping(bytes32 => mapping(Outcome => uint16)) private _lineClaimCounts;
mapping(bytes32 => uint64) public lineFinalizedAt;  // block timestamp of finalization
mapping(bytes32 => uint64) public lineFirstAttestAt; // for window enforcement

// Validator-set snapshot block per line (the block at which the attestor set is
// computed). Set when the FIRST attestation arrives, not at line definition,
// because lineHashes don't have a built-in "expiry" — they're identified by
// content, not signal. Snapshot is sticky for the line's resolution window.
mapping(bytes32 => uint256) public attestorSetBlock;

// Acceptable finalization window after first attestation: 24h on testnet, longer
// on mainnet. Prevents stale-validator-set finalizations.
uint64 public constant ATTEST_WINDOW_S = 24 * 3600;

uint8 public threshold;       // 4-of-5 today; configurable via timelock
uint8 public quorumDenom;     // 5 (current OV signer count)

event LineAttested(bytes32 indexed lineHash, address indexed attestor, Outcome outcome);
event LineFinalized(bytes32 indexed lineHash, Outcome outcome);

function attestLineOutcome(bytes32 lineHash, Outcome outcome) external {
    require(outcome != Outcome.Pending, "outcome=pending invalid");
    require(lineOutcome[lineHash] == Outcome.Pending, "already finalized");

    // Snapshot the attestor set on first attestation.
    uint256 snapshotBlock = attestorSetBlock[lineHash];
    if (snapshotBlock == 0) {
        snapshotBlock = block.number;
        attestorSetBlock[lineHash] = snapshotBlock;
        lineFirstAttestAt[lineHash] = uint64(block.timestamp);
    } else {
        require(block.timestamp <= lineFirstAttestAt[lineHash] + ATTEST_WINDOW_S,
                "attest window expired");
    }

    require(_isValidatorAtBlock(msg.sender, snapshotBlock), "not in attestor set");
    require(_lineClaims[lineHash][msg.sender] == Outcome.Pending, "double attest");

    _lineClaims[lineHash][msg.sender] = outcome;
    _lineClaimCounts[lineHash][outcome]++;
    emit LineAttested(lineHash, msg.sender, outcome);

    if (_lineClaimCounts[lineHash][outcome] >= threshold) {
        lineOutcome[lineHash] = outcome;
        lineFinalizedAt[lineHash] = uint64(block.timestamp);
        emit LineFinalized(lineHash, outcome);
    }
}

// Reserved for v2 fraud-proof override. Not implemented in v1; storage slot
// reserved so the upgrade is forward-compatible.
mapping(bytes32 => bytes) private _reservedFraudProofSlot;
```

### Notes on the contract

- **Validator-set snapshot at first attestation**, not at line creation (lineHashes
  don't have a creation event — they're content-addressed). Snapshot is sticky for
  24h. Late attestations after the window cannot move the count, preventing
  stale-set finalization. If 24h elapses without threshold, the line is genuinely
  ambiguous → operator manual review path.
- **`_isValidatorAtBlock`** reads the OutcomeVoting signer set or Bittensor
  metagraph snapshot at a specific block. Existing chain helpers exist; pick the
  one the rest of OV uses for vote validation.
- **Storage growth is bounded** by the number of distinct lines ever resolved;
  not cleared. Acceptable for the operational lifetime of the protocol on
  testnet+mainnet — we're talking 10s-100s of bytes per line × tens of thousands
  of lines per year. Single-digit MB total state for years.
- **Fraud-proof slot reserved**: `_reservedFraudProofSlot` is a forward-compat
  storage placeholder. v2 will use it for slash-backed challenge data without
  requiring another contract upgrade.
- **`threshold` is mutable via timelock**, not constant. Allows tuning without
  redeploy.
- **No domain check inside the contract** — `lineHash` is opaque. Domain
  separation lives in the off-chain hash construction (Phase 0 schema). The
  contract just trusts that callers compute lineHash correctly per the canonical
  schema. The schema is the trust boundary; mismatches manifest as "no threshold
  ever reached" (different validators compute different hashes for the same
  intent → no agreement → operator review).

### UUPS storage layout safety

Append the new mappings + constants to the END of `OutcomeAttestor` storage. Do
not modify existing slots. Required pre-upgrade verification:

1. Run `forge inspect OutcomeAttestor storageLayout > before.json` against the
   currently-deployed implementation.
2. Apply this PR.
3. Run again → `after.json`.
4. `diff before.json after.json` → must show only appended slots, zero changes
   to existing slots' types, names, or offsets.
5. Block the upgrade unless that diff passes a CI check.

Nothing about this design _requires_ extending OutcomeAttestor; deploying as a
new contract `LineOutcomeRegistry` is also safe and avoids storage diff anxiety.
Recommended: ship as new contract for Phase 1 simplicity, fold into
OutcomeAttestor in v2 if it makes settlement integration cleaner.

## Phase 2 — Validator-side resolution + attestation (2 days)

In `validator/djinn_validator/core/outcomes.py`:

1. **Parse decoy line strings per Phase 0 schema.** Reject malformed lines
   loudly (operator should know if a genius committed an invalid signal).
2. **Compute `lineHash`** per Phase 0 spec.
3. **Resolve each line** via existing ESPN client at `signal.expiresAt + 6h`
   (the canonical resolution time per schema). Use the existing
   `OutcomeAttestor` Python class as the local resolver; feed its output into
   the canonical schema interpretation rules.
4. **Submit attestation** via `LineOutcomeRegistry.attestLineOutcome(lineHash,
   outcome)`. Reuse the v1744 gossip outbox machinery for retry on RPC failure.
5. **Skip attestation** if `lineOutcome[lineHash]` is already non-Pending on
   chain (someone else's attestation already finalized it). Saves gas and avoids
   redundant work.

Idempotency: same lineHash for the same real-world line means later signals
that include the same decoy automatically reuse the prior attestation. No
re-attestation needed.

Crash recovery: validator restarts re-scan resolved lines, attests any that
weren't yet attested. The chain rejects double-attests so this is safe.

## Phase 3 — MPC input gating (1 day)

In `mpc_orchestrator.try_shadow_distributed_settlement`:

```python
# Before initiating MPC for an audit batch, verify all decoy lines for all
# signals in the batch have a finalized canonical outcome on chain.
all_lines_ready = True
for signal_id in audit_set.signal_ids:
    decoy_lines = signal_commitment.get_decoy_lines(signal_id)  # already on chain
    for line_str in decoy_lines:
        line_hash = compute_line_hash(line_str)
        canonical = chain_client.read_line_outcome(line_hash)
        if canonical == Outcome.Pending:
            all_lines_ready = False
            break

if not all_lines_ready:
    # All validators reach the same conclusion: this batch is not ready.
    return None  # deterministic abstain

# Verify our local view matches canonical. If not, refuse to participate;
# raises an operator alert instead of submitting a bad MPC vote.
for signal_id in audit_set.signal_ids:
    for line_str in signal_commitment.get_decoy_lines(signal_id):
        line_hash = compute_line_hash(line_str)
        local = self.local_resolved_outcomes.get(line_hash)
        canonical = chain_client.read_line_outcome(line_hash)
        if local != canonical:
            log.error("local_outcome_diverges_from_canonical",
                      line_hash=line_hash.hex(),
                      local=local, canonical=canonical)
            return None  # refuse to vote with diverging view

# All lines canonical, all match local. Proceed with MPC.
```

Result: every honest validator computes the same MPC inputs → same aggregate
quality score → 4-of-5 quorum on `submitVote(g, i, cycle, score, batchKey)` is
trivial because all 4-5 honest validators submit the same vote.

`batchKey` simplifies to `keccak(g, i, cycle, sortedSignalIdsInBatch)` — no
longer parameterized by per-validator local subsets.

## Phase 4 — Cleanup (1 day)

- Drop v1744-v1745 outcome-gossip outbox path (chain is canonical now). Keep
  for `purchase_odds` (still needed for BPA/WPA delivery).
- Replace mark_abstain on missing-outcome with deterministic-wait via canonical
  pending check. Eliminates the abstain-counter race entirely.
- Local `OutcomeAttestor` Python class: keep as the resolver, but its output is
  no longer the canonical source — chain is. Remove the per-validator outcome
  log if no longer load-bearing.

## Phase 5 — End-to-end test on Sepolia (2 days)

1. Deploy `LineOutcomeRegistry` via timelock (or extend OutcomeAttestor).
2. Restart all 5 validators with new code.
3. Run smoke: 5-10 fresh signals, full lifecycle through canonical outcomes →
   MPC → AuditSettled → USDC distribution.
4. Verify each layer:
   - decoy strings parse cleanly
   - lineHashes match expected derivation
   - 4-of-5 attestation reaches threshold
   - canonical outcome is correct (cross-check ESPN manually)
   - MPC input matches canonical
   - aggregate score matches expected math
   - USDC flows correctly per (g, i) pair

## Phase 6 — UX polish (1-2 days)

- `/genius/track-record` reflects real settled audits, not score=0 force-settles
- Idiot purchase status: pre-game → in-progress → "settled, +X / -X USDC"
- Audit history page links to on-chain settlement events

## Trust model (explicit)

**v1 trust assumption: 4-of-5 honest-majority among the snapshot attestor set.**
A coalition of 4 attestors can finalize an incorrect line outcome. The contract
verifies threshold signatures, not ESPN data correctness. This is the same trust
model as the existing OutcomeVoting; we're not weakening it, just relocating
where the agreement happens.

**v2 (post-launch): TLSNotary-backed fraud proofs**. Any validator can post a
TLSNotary attestation of an ESPN response that contradicts a finalized
canonical outcome, slashing the dishonest attestors. The `_reservedFraudProofSlot`
mapping is the storage placeholder. Not blocking for live launch; the v1 trust
model is acceptable for testnet and early mainnet.

**Genuine ESPN ambiguity** (4 attestors honestly disagree because ESPN has no
clean answer): no threshold reached → line stays Pending → batch can't settle
→ operator manual review path via existing `Audit.forceSettle` (already proven
in production this session).

## Effort estimate

| Phase | What | Days |
|---|---|---|
| 0 | Canonical line schema spec | 1 |
| 1 | LineOutcomeRegistry contract (or OutcomeAttestor extension) | 1-2 |
| 2 | Validator-side parse + resolve + attest | 2 |
| 3 | MPC input gating from on-chain canonical | 1 |
| 4 | Cleanup of redundant gossip layers | 1 |
| 5 | E2E Sepolia test | 2 |
| 6 | UX polish | 1-2 |
| **Total** | | **9-11 days** |

## Privacy properties preserved

- **Real pick stays encrypted.** Pick lives in the encrypted blob; on-chain canonical
  outcomes cover all decoy lines plus the real one indistinguishably.
- **(idiot ↔ line) mapping stays private.** Encrypted in the buyer's purchase share;
  not derivable from per-line outcomes.
- **Aggregate quality score per (g, i) batch** is still computed via MPC; only the
  aggregate (not per-purchase outcomes) reaches chain.

The Merkle root over per-line outcomes (an earlier rev's design) is replaced with
direct per-line canonical entries, which is strictly better: less aggregation
ambiguity, naturally deduplicated across signals, easier to debug.

## Why this finally works

Every previous fix tried to make output-layer consensus more reliable. This pulls
divergence one layer down: anchors canonical inputs on chain so MPC has
deterministic inputs by construction. Output consensus becomes trivial because all
honest validators compute the same output.

The schema spec in Phase 0 is the load-bearing work. With a canonical decoy
format and resolution rules, "ESPN" is no longer ambiguous; without it, no
amount of consensus machinery helps. Codex's earlier critique was correct on this
point and is the central change in this rev.

The MPC privacy properties stay intact. The decentralization stays intact (4-of-5
attestor agreement, snapshot at first attestation). The existing OutcomeVoting +
Audit + Escrow contracts stay intact — we're adding one canonical-input layer
below the existing settlement stack, not replacing any of it.

## Open decisions (need confirm before Phase 1)

1. **New contract vs extend OutcomeAttestor.** Lean new contract
   (`LineOutcomeRegistry`) for v1 simplicity — clean storage layout, easier audit,
   easier rollback. Fold into OutcomeAttestor in v2 if integration warrants.

2. **Threshold value.** Default 4-of-5 (matches existing OV). Is 3-of-5 acceptable
   for stronger liveness given 5 validators are not all reliably online? Lower
   threshold weakens trust model. Recommendation: keep 4-of-5; if liveness becomes
   a problem, raise N (more attestors) before lowering threshold.

3. **24h attestation window**: enough on testnet, possibly too short on mainnet
   if validators drift for >24h. Make it configurable via timelock from the start;
   default 24h, can be raised to 72h on mainnet without redeploy.

4. **Storage layout review**: required CI gate. Foundry `storageLayout` diff
   before/after. Block upgrade if diff is non-additive.

5. **Validator-set query helper**: which existing function returns "validator set
   at block N"? Re-use whatever OV's `submitVote` uses for membership check; do
   not introduce a new mechanism.
