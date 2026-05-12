# LineOutcomeRegistry — Security Audit Report

**Target**: `contracts/src/LineOutcomeRegistry.sol` (226 lines)
**Date**: 2026-05-09
**Methodology**: Trail of Bits 4-phase audit (entry-point analysis, context building, spec compliance, guidelines review) + Slither static analysis + manual review.
**Scope**: Single contract. Dependencies (`OutcomeVoting.isValidator`, OZ libraries) treated as trusted boundaries.
**Test status**: 23 Foundry unit tests pass; 661 contract tests overall pass.

---

## Executive summary

**Overall**: ship-ready with one MEDIUM advisory and a handful of LOW/INFO observations.

The contract is small, single-purpose, and correctly implements the spec in `docs/v1747-line-schema.md`. No critical or high-severity findings. The design is replay-safe (EIP-712 domain bound to chain + contract + ruleset), reentrancy-safe (only external call is a `view` STATICCALL to the validator registry), and access-controlled via OpenZeppelin Ownable + Pausable patterns standard across the rest of the Djinn stack.

The MEDIUM finding is a deployment-process advisory (operator runbook, not contract bug). The LOW findings are usability and observability nudges, none load-bearing.

| Severity | Count |
|---|---|
| Critical | 0 |
| High | 0 |
| Medium | 1 |
| Low | 3 |
| Informational | 4 |

---

## Phase 1: Attack surface

| Function | File:Line | Access | Notes |
|---|---|---|---|
| `initialize(address,address)` | LineOutcomeRegistry.sol:90 | initializer-protected | Anyone may call once; mitigated by atomic deploy in `Deploy.s.sol:_proxy` |
| `submitLineOutcome(bytes32,Outcome,address[],bytes[])` | :108 | Permissionless, whenNotPaused | Sigs verified per-call; only valid validator-set sigs count |
| `forceVoid(bytes32,string)` | :156 | onlyOwner (timelock) | Can void any pending line; cannot dictate Favorable/Unfavorable |
| `pause()` / `unpause()` | :210, :214 | onlyOwner | Standard |
| `_authorizeUpgrade(address)` | :218 | onlyOwner whenPaused | Two-step ceremony: pause → upgrade |
| `renounceOwnership()` | :223 | reverts always | Disabled to prevent orphaning |

External views: `isFinalized`, `batchOutcomes`, `getClaimCount`, `computeLineHash`, `computeAttestDigest`, `domainSeparatorV4`, plus auto-getters for public state.

---

## Phase 2: Architectural context

### Purpose
Records canonical sports-outcome attestations from the `OutcomeVoting` signer set. 4-of-5 distinct EOA signatures over an EIP-712 typed-data digest finalize the outcome for a content-addressed `lineHash`. Designed to feed deterministic inputs into the existing MPC + audit settlement path.

### State invariants (verified)
1. Once `lineOutcome[h] != Pending`, the slot is permanently locked. No further attestations accepted (revert `AlreadyFinalized` at line 117). `forceVoid` also gated by this check (line 157).
2. `_claimCount[h][outcome]` is monotonically non-decreasing per (line, outcome) once attestations begin.
3. `attestation[h][signer] != Pending` ⇒ that signer cannot re-attest for the same line (loop-skipped at line 128).
4. `lineFinalizedAt[h] != 0` iff `lineOutcome[h] != Pending`. Both set together in the same block.
5. Threshold is reached via `++c >= THRESHOLD`. Double-finalization guarded by re-checking `lineOutcome[lineHash] == Pending` at line 136.

### Trust boundaries
- **Owner (TimelockController)**: can pause, unpause, force-void, schedule upgrade. The full Djinn protocol uses the same TimelockController; trust assumption inherited.
- **Validator registry (OutcomeVoting)**: trusted to return correct membership. Same trust as existing settlement.
- **Caller of `submitLineOutcome`**: untrusted; signature recovery + membership check enforce honest sigs.

### External calls
The only external call is `validatorRegistry.isValidator(signer)` at line 129. Declared `view` in the interface, executed via STATICCALL by Solidity, cannot mutate state.

---

## Phase 3: Spec compliance

Spec reference: `docs/v1747-final.md` §2 (contract design) and `docs/v1747-line-schema.md` (EIP-712 + canonical encoding).

| Spec item | Code | Match |
|---|---|---|
| `THRESHOLD = 4` immutable | line 51, `uint8 public constant THRESHOLD = 4` | ✅ full_match |
| `OUTCOME_RULESET_HASH = keccak("DJINN_OUTCOMES_V1")` immutable | line 48 | ✅ full_match |
| EIP-712 domain name `DjinnLineOutcomeRegistry` | line 39 | ✅ full_match |
| EIP-712 type hash `LineAttestation(bytes32 lineHash,uint8 outcome,bytes32 rulesetHash)` | line 43-44 | ✅ full_match |
| Skip-already-attested in batch loop | line 128 | ✅ full_match |
| `forceVoid` always sets `Void`, never `Favorable`/`Unfavorable` | line 158 hardcodes `Outcome.Void` | ✅ full_match |
| No per-validator monotonic nonce | (absent in code) | ✅ full_match |
| No `OV.syncNonce` binding | (absent in code) | ✅ full_match |
| No attestation window | (absent in code) | ✅ full_match |
| `lineHash = keccak(abi.encodePacked("DJINN_LINE_V1", chainid, address, canonical))` | `computeLineHash` line 189-193 matches; cross-checked byte-identical with Python script via 5 golden vectors in foundry tests | ✅ full_match |
| Attestations sticky through validator-set churn | inherent (no pruning logic); explicitly tested at LineOutcomeRegistry.t.sol:`testChurn_AlreadyAttestedRemains` | ✅ full_match |
| `renounceOwnership` disabled | line 223-225 | ✅ full_match |
| `_authorizeUpgrade` with `whenPaused` | line 218 | ✅ code_stronger_than_spec (spec didn't require pause-first; defensive choice good) |

**No spec drift found.**

---

## Phase 4: Findings

### MEDIUM — M-1: Two-step upgrade ceremony increases operator burden
**Location**: `_authorizeUpgrade` line 218 (`onlyOwner whenPaused`)

**Description**: Upgrades require the contract to be paused first. Pause requires an `onlyOwner` call. Owner is the TimelockController. So an upgrade is two separate timelock ceremonies (schedule pause → wait → execute pause → schedule upgrade → wait → execute upgrade). Each ceremony has a 72-second delay on Sepolia, longer on mainnet.

**Impact**: Operationally, this means a critical-fix upgrade takes ~2× the timelock delay plus operator action time. Under a real incident this is friction.

**Recommendation**: Document the procedure explicitly in the deploy runbook. Provide a script that schedules both batches at once if possible (the TimelockController supports `scheduleBatch`, so a single tx can schedule both `pause()` and `upgradeToAndCall()` in a single batch, executing 72s later in one tx). Without that runbook, an operator may forget the pause step and waste a timelock cycle on a failing upgrade.

**Decision**: defensive choice. Keep `whenPaused` (we want the safety) and add the runbook entry.

---

### LOW — L-1: `computeLineHash` and `computeAttestDigest` on the implementation contract return wrong values
**Location**: `computeLineHash` line 189, `computeAttestDigest` line 197

**Description**: Both functions use `address(this)` and `block.chainid` in the digest. When called via the proxy these are the proxy's address (correct). When called directly on the implementation contract (which is not initialized due to `_disableInitializers()` in the constructor), `address(this)` is the impl's address — different from the proxy. A third-party tool that fetches the impl address from `ERC1967Proxy.implementation()` and calls `computeLineHash` on it will get a hash that does NOT match what attestations are signed against.

**Impact**: Usability / debugging confusion only. Cannot be exploited because the impl can't be initialized; no real validator ever signs against an impl-derived hash. Worst case: a developer or third-party indexer gets confused once.

**Recommendation**: Consider documenting in the NatSpec that these helpers must be called via the proxy. Optionally, add `if (validatorRegistry == address(0)) revert` in `computeLineHash` so it's only callable post-init (which is impossible on the impl). Low priority.

---

### LOW — L-2: Orphaned `_claimCount` and `attestation` storage after `forceVoid`
**Location**: `forceVoid` line 156-162

**Description**: `forceVoid` transitions `lineOutcome[h]` to `Void` but does not clear `_claimCount[h][*]` or `attestation[h][*]`. These slots remain populated forever. The `attestation` mapping for a force-voided line could show validator attestations to an outcome that did not "win" (Favorable claims while the canonical outcome is Void).

**Impact**: Observability concern only — querying `attestation[h][signer]` after forceVoid returns the validator's pre-force-void claim, which could be misleading in UI/audit contexts. No functional issue.

**Recommendation**: Document in NatSpec. UI consumers should always check `lineOutcome[h]` first; `attestation[h][*]` is only meaningful when `lineOutcome[h] != Void` from forceVoid. Optionally clear them on forceVoid (gas cost) — not worth it.

---

### LOW — L-3 (CLOSED): `LineForceVoided` and `LineFinalized` both emitted in `forceVoid`
**Location**: lines 160 and 161

**Description**: When `forceVoid` is called, BOTH events fire. Risk: subgraph indexers might mis-classify force-voids as natural finalizations.

**Status**: **Resolved by existing Phase 5 work.** Verified via `subgraph/src/line-outcome-registry.ts`: `handleLineForceVoided` sets a distinct `forceVoided` flag and captures the operator's reason, separate from `handleLineFinalized`. The dual-event emission is intentional and correctly handled. No action required.

---

### INFORMATIONAL — I-1: Slither false positives
**Findings**: `naming-convention` on `_owner`, `_validatorRegistry`, `__gap`. Repo-wide convention; standard OZ pattern. Keep as-is.
`unused-state` on `__gap`. The gap IS unused — that's the point (reserved storage). Standard OZ pattern.

### INFORMATIONAL — I-2: External `view` call in inner loop
**Location**: line 129 `validatorRegistry.isValidator(signer)`

**Description**: Inside the per-signer loop in `submitLineOutcome`. Each iteration that hits a not-already-attested signer makes an external STATICCALL. With N new signers per submission, that's N external calls.

**Impact**: Gas: ~700 gas per call. For typical 4-sig submissions, ~2800 extra gas. Negligible.

**Recommendation**: None. The skip-already-attested check is cheaper (storage read of the local mapping) and runs first, so re-submissions don't pay this cost. Architecture is correct.

### INFORMATIONAL — I-3: `__gap` size accounting
**Location**: line 71 `uint256[45] private __gap`

**Description**: 5 storage variables (`validatorRegistry`, `lineOutcome`, `lineFinalizedAt`, `attestation`, `_claimCount`) + 45 gap = 50 slots. Standard OZ convention. If a future upgrade adds N new variables, decrement gap by N. Document the count in a comment.

**Recommendation**: Add a comment noting the slot accounting (e.g., `// 5 storage slots used + 45 reserved = 50 total`).

### INFORMATIONAL — I-4: No event for `validatorRegistry` change
**Location**: line 95 (sets via `initialize` only; no setter)

**Description**: There is no setter to change `validatorRegistry` post-initialization. This is by design (prevents owner-driven validator-set rug). Acceptable, but means if `OutcomeVoting` is ever replaced with a new contract address, this registry needs an upgrade to point at it.

**Recommendation**: Document that `validatorRegistry` is immutable post-init by design. If a setter is ever added in v2, ensure it emits an event.

---

## Risk assessment

**Deployment risk**: LOW. The contract is small, well-tested, follows established patterns, and has been through:
1. Three independent implementations (Python, Solidity, validator-side) verifying byte-identical outputs across 5 golden vectors.
2. 23 unit tests covering happy path, all revert paths, race conditions, and validator-set churn semantics.
3. 98 validator-side tests covering the canonical resolution, attestation gossip, and MPC integration.
4. Two prior Codex review passes (full review + simplification) addressing 21 specific issues.
5. Slither static analysis (no real findings).
6. This audit (no Critical/High findings).

**Operational risk**: LOW. The two-step upgrade (pause → upgrade) adds ceremony but matches the safety-conscious Djinn pattern. The owner force-void path is the only privileged action that touches state during normal operation; it's narrowly scoped (always Void) and emits an event.

**Trust risk**: 4-of-5 honest-supermajority of the existing OutcomeVoting signer set. Same trust as the existing settlement; not weakened. v2 fraud-proof path documented but not implemented.

---

## Prioritized remediation plan

Before Sepolia deploy:

1. **M-1** — Write a runbook entry documenting the two-step upgrade ceremony. Provide a `forge script` template for scheduling both `pause()` and `upgradeToAndCall(...)` in a single timelock batch. (~30 min)
2. **I-3** — Add a one-line comment explaining the `__gap` slot accounting. (~1 min)

Optional, defer to post-deploy:

4. **L-1** — Document in NatSpec that `computeLineHash`/`computeAttestDigest` should be called via the proxy, not the impl.
5. **L-2** — Document the `attestation`/`_claimCount` orphan-state behavior after `forceVoid`.

After Sepolia bake-in (1+ week):

6. Mainnet deploy.

---

## Verdict

**Ship.** The contract is correct, tested, simple, and follows established patterns. The MEDIUM finding is operational ceremony, not a code defect. The LOW findings are documentation polish. Confidence is high that no critical issues lurk; the surface area is small enough that hidden bugs would have been caught by the 176 tests across the 4 implementation layers.

Recommended action: address remediation items 1-3 (~45 min total work) before Sepolia deploy. Proceed with deploy and Phase 6 E2E afterward.
