# v1747 — On-chain canonical line outcome registry

A long-term core protocol feature. Not a P0 patch — the verifiability primitive Djinn has implicitly promised since launch and should now deliver on chain.

This is the simplified final design after three independent planning passes (contract-first, validator-ops-first, user-product-first), one external review (Codex), one internal review, one external simplify pass (Codex), and one internal simplify pass.

---

## 0. Framing

The audit-settlement bridge has been broken for six weeks. Validators each have correct ESPN-resolved outcomes; the consensus path (MPC + OutcomeVoting on aggregate quality score) cannot reach 4-of-5 quorum because per-validator polling races create input divergence at MPC time.

**Reframe**: stop treating outcome consensus as plumbing. Treat per-line outcomes on chain as the primary product feature. Settlement falls out for free; verifiable track records become a public chain query; anyone can audit any signal forever.

**v1 trust model**: 4-of-5 honest-supermajority of `OutcomeVoting` signer set. Same as today; we relocate where the agreement happens.

**Privacy preserved**: real pick stays in encrypted blob (decoys mask which line); (idiot ↔ line) mapping stays in encrypted purchase share; per-purchase economics still aggregated via MPC.

**Privacy NOT regressed**: validators must attest every decoy at the same cadence/priority as the real line — see §11. Without this discipline, attestation timing leaks the real pick. This is a hard product rule.

---

## 1. Phase 0: Canonical schema (1-2 days, blocking)

### Canonical line string

```
DJINN_LINE_V1|<sport>|<event_id>|<market>|<side>|<line_value>
```

ASCII only, lowercase, no whitespace, exactly 6 pipe-separated fields. Trailing pipe required for moneyline (empty `line_value`).

| Field | Domain |
|---|---|
| `sport` | one of: `basketball_nba`, `basketball_ncaab`, `americanfootball_nfl`, `americanfootball_ncaaf`, `baseball_mlb`, `icehockey_nhl`, `soccer_epl`, `soccer_usa_mls` |
| `event_id` | ESPN event id (ASCII numeric, ≤16 chars) |
| `market` | `spread` \| `total` \| `moneyline` |
| `side` | `home` \| `away` (spread, moneyline) — `over` \| `under` (total) |
| `line_value` | signed decimal one decimal place: `-3.5`, `+0.0`, `220.5`. Empty for moneyline. |

### lineHash (golden vectors required before code)

```
lineHash = keccak256(abi.encodePacked(
    "DJINN_LINE_V1",                  // schema version
    block.chainid,                    // chain binding (uint256, 32 bytes big-endian)
    address(LineOutcomeRegistry),     // contract binding (20 bytes, no padding via encodePacked)
    canonical_line_string             // exact UTF-8 bytes
))
```

Solidity reference + Python reference + at least 5 golden test vectors checked into the canonical schema doc and verified in CI on both sides. Without golden vectors, "canonical" is a lie.

### Resolution rules

A pure function `canonical_outcome_for_line(sport, market, side, line_value, espn_event)` → `Outcome`. Deterministic; no clock, no env, no private state.

| Sport | Terminal statuses (final) | OT counts in spread/total? | Notes |
|---|---|---|---|
| basketball_nba/ncaab | `STATUS_FINAL` | yes | n/a |
| americanfootball_nfl/ncaaf | `STATUS_FINAL` | yes | n/a |
| baseball_mlb | `STATUS_FINAL`, `STATUS_END_OF_REGULATION` | yes (extra innings) | weather-shortened ≥5 innings = `STATUS_FINAL` |
| icehockey_nhl | `STATUS_FINAL`, `STATUS_AFTER_SHOOTOUT` | regulation+OT only — shootout goal does NOT count toward total (house rule) | moneyline includes shootout |
| soccer_epl/mls | `STATUS_FULL_TIME`, `STATUS_AFTER_EXTRA_TIME`, `STATUS_AFTER_PENALTIES` | full-time only for spread/total; ML includes ET+pens | already in `_map_espn_status` |

ESPN field paths must be pinned per sport. Canonical endpoint: `https://site.api.espn.com/apis/site/v2/sports/{sport}/events/{event_id}`. Score path: `competitions[0].competitors[*].score`. Status path: `competitions[0].status.type.name`. Home/away identification: `competitions[0].competitors[*].homeAway`. Pin these in the schema doc; cite ESPN's published field reference.

### Edge cases

- **Postponed**: `Pending` until played within 7 days of `competitions[0].date`. After 7 days: `Void`.
- **Cancelled / abandoned / forfeited**: `Void`.
- **Doubleheaders (MLB)**: each game has distinct ESPN event_id; no protocol special case.
- **Stat corrections**: read at `event.completion_time + 6h`. Frozen after. Post-finality corrections are a v2 fraud-proof concern.
- **Push on integer spreads**: `Void`.
- **Tie on moneyline (where ESPN reports it, e.g. soccer regular time)**: `Void`.

### Ruleset version

`OUTCOME_RULESET_HASH = keccak256("DJINN_OUTCOMES_V1")`. **Immutable** for v1. Schema changes require a new contract deploy (v2 registry), not a config flip.

---

## 2. Phase 1: LineOutcomeRegistry contract (2 days)

New UUPS contract, deployed via timelock. Storage layout safe by construction (new contract).

```solidity
// SPDX-License-Identifier: MIT
pragma solidity ^0.8.28;

import {OwnableUpgradeable} from "@openzeppelin/contracts-upgradeable/access/OwnableUpgradeable.sol";
import {PausableUpgradeable} from "@openzeppelin/contracts-upgradeable/utils/PausableUpgradeable.sol";
import {UUPSUpgradeable} from "@openzeppelin/contracts-upgradeable/proxy/utils/UUPSUpgradeable.sol";
import {Initializable} from "@openzeppelin/contracts-upgradeable/proxy/utils/Initializable.sol";
import {ECDSA} from "@openzeppelin/contracts/utils/cryptography/ECDSA.sol";
import {EIP712Upgradeable} from "@openzeppelin/contracts-upgradeable/utils/cryptography/EIP712Upgradeable.sol";

interface IValidatorRegistry {
    function isValidator(address) external view returns (bool);
}

enum Outcome { Pending, Favorable, Unfavorable, Void }

contract LineOutcomeRegistry is
    Initializable, OwnableUpgradeable, PausableUpgradeable,
    UUPSUpgradeable, EIP712Upgradeable
{
    string public constant NAME = "DjinnLineOutcomeRegistry";
    string public constant VERSION = "1";

    bytes32 public constant ATTEST_TYPEHASH = keccak256(
        "LineAttestation(bytes32 lineHash,uint8 outcome,bytes32 rulesetHash)"
    );

    bytes32 public constant OUTCOME_RULESET_HASH = keccak256("DJINN_OUTCOMES_V1");
    uint8 public constant THRESHOLD = 4;

    IValidatorRegistry public validatorRegistry;  // = OutcomeVoting proxy

    // Outcome state
    mapping(bytes32 => Outcome) public lineOutcome;            // public; canonical
    mapping(bytes32 => uint64)  public lineFinalizedAt;

    // Per-line per-validator attestation (Outcome.Pending = unattested sentinel).
    // Once accepted, remains counted even if the signer is later removed from
    // the validator set. This is intentional: prevents churn from invalidating
    // already-collected agreement. Trust model = 4-of-5 of signers who attested
    // at the time of attestation, not the current signer set.
    mapping(bytes32 => mapping(address => Outcome)) public attestation;
    mapping(bytes32 => mapping(uint8 => uint8)) private _claimCount; // up to 5 per outcome

    uint256[45] private __gap;

    event LineAttested(bytes32 indexed lineHash, address indexed attestor, Outcome outcome);
    event LineFinalized(bytes32 indexed lineHash, Outcome outcome, uint64 finalizedAt);
    event LineForceVoided(bytes32 indexed lineHash, string reason);

    error AlreadyFinalized();
    error NotInValidatorSet();
    error AlreadyAttested();
    error InvalidOutcome();
    error BadSignature();
    error LengthMismatch();

    function initialize(address _owner, address _validatorRegistry) public initializer {
        __Ownable_init(_owner);
        __Pausable_init();
        __UUPSUpgradeable_init();
        __EIP712_init(NAME, VERSION);
        validatorRegistry = IValidatorRegistry(_validatorRegistry);
    }

    /// @notice Submit one or more (signer, signature) pairs for a single line/outcome.
    ///         Signers must be in the current validator set. Skips already-attested
    ///         signers without reverting (so racing submitters don't poison each other).
    /// @dev    Permissionless; anyone can submit a bundle.
    function submitLineOutcome(
        bytes32 lineHash,
        Outcome outcome,
        address[] calldata signers,
        bytes[] calldata signatures
    ) external whenNotPaused {
        if (signers.length != signatures.length) revert LengthMismatch();
        if (outcome == Outcome.Pending) revert InvalidOutcome();
        if (lineOutcome[lineHash] != Outcome.Pending) revert AlreadyFinalized();

        bytes32 digest = _hashTypedDataV4(keccak256(abi.encode(
            ATTEST_TYPEHASH, lineHash, uint8(outcome), OUTCOME_RULESET_HASH
        )));

        for (uint256 i; i < signers.length; ) {
            address signer = signers[i];
            // Skip if this signer has already attested — let racing submitters
            // submit overlapping bundles without reverting the whole batch.
            if (attestation[lineHash][signer] == Outcome.Pending) {
                if (!validatorRegistry.isValidator(signer)) revert NotInValidatorSet();
                if (ECDSA.recover(digest, signatures[i]) != signer) revert BadSignature();

                attestation[lineHash][signer] = outcome;
                uint8 c = ++_claimCount[lineHash][uint8(outcome)];
                emit LineAttested(lineHash, signer, outcome);

                if (c >= THRESHOLD && lineOutcome[lineHash] == Outcome.Pending) {
                    lineOutcome[lineHash] = outcome;
                    lineFinalizedAt[lineHash] = uint64(block.timestamp);
                    emit LineFinalized(lineHash, outcome, uint64(block.timestamp));
                }
            }
            unchecked { ++i; }
        }
    }

    /// @notice Operator escape hatch for stuck lines (ESPN ambiguity, validator
    ///         churn during attestation window, malformed decoys). Always Voids.
    /// @dev    Owner-only via timelock. Off-chain operator policy SHOULD require
    ///         multi-sig approval before scheduling, but this is policy not
    ///         protocol — the contract enforces only the timelock.
    function forceVoid(bytes32 lineHash, string calldata reason) external onlyOwner {
        if (lineOutcome[lineHash] != Outcome.Pending) revert AlreadyFinalized();
        lineOutcome[lineHash] = Outcome.Void;
        lineFinalizedAt[lineHash] = uint64(block.timestamp);
        emit LineForceVoided(lineHash, reason);
        emit LineFinalized(lineHash, Outcome.Void, uint64(block.timestamp));
    }

    // Reads (used by MPC orchestrator + subgraph + /verify page)
    function isFinalized(bytes32 lineHash) external view returns (bool) {
        return lineOutcome[lineHash] != Outcome.Pending;
    }

    function batchOutcomes(bytes32[] calldata hashes) external view returns (Outcome[] memory out) {
        out = new Outcome[](hashes.length);
        for (uint256 i; i < hashes.length; ++i) out[i] = lineOutcome[hashes[i]];
    }

    function getClaimCount(bytes32 lineHash, Outcome o) external view returns (uint8) {
        return _claimCount[lineHash][uint8(o)];
    }

    function pause() external onlyOwner { _pause(); }
    function unpause() external onlyOwner { _unpause(); }
    function _authorizeUpgrade(address) internal override onlyOwner whenPaused {}
    function renounceOwnership() public pure override { revert("disabled"); }
}
```

**Key design choices, simplified from earlier revs:**

- **No per-validator monotonic nonce**. Per-line `attestation[lineHash][signer] != Pending` already prevents replay; ruleset+chain+contract binding via EIP-712 prevents cross-context replay. Global nonces would create liveness deadlocks.
- **No `OV.syncNonce` binding**. Validator-set churn does NOT invalidate already-counted attestations — they stay valid even if a signer is later removed. Only NEW attestations from now-removed signers fail the `isValidator` check. This is intentional: prevents churn from undoing collected agreement. Trust model = "4-of-5 of signers who attested at the time of attestation," not "4-of-5 of the current signer set." Force-void remains the operator escape for fully stuck lines.

- **No attestation window**. The 7-day countdown in earlier revs added no replay safety (the per-line attestation map already prevents replay) and created a stuck-line path: a premature/mistaken validator attestation could start a countdown that later blocks honest attestations. Removed entirely. Lines stay open indefinitely until threshold or operator force-void. Storage growth is bounded by signal volume (trivial).
- **`THRESHOLD` and `OUTCOME_RULESET_HASH` immutable**. Trust model integrity > governance flexibility. v2 = new contract.
- **Skip-already-attested in batch loop**. Racing submitters can submit overlapping bundles without reverting each other. Inevitable race resolves cheaply.
- **No reserved fraud-proof slot**. Use `__gap`. Fake forward-compat is worse than honest empty space.
- **`forceVoid` always sets `Void`, never economic outcomes**. Operator can stop a stuck line; cannot dictate an economic result.

### OV interface assumption (open question A)

The contract calls `validatorRegistry.isValidator(address)`. Need to verify deployed `OutcomeVoting.sol` exposes this method with this signature. If yes, wire directly. If no, three options:
1. Add an adapter contract (`OVValidatorAdapter`) that translates whatever OV exposes into `IValidatorRegistry`.
2. Modify OV via UUPS upgrade to add the method.
3. Maintain a separate attestor whitelist on `LineOutcomeRegistry` (timelock-managed).

**Pre-implementation check** required. Default plan if missing: option 1 (adapter), zero risk to existing OV.

### Golden test vectors

Required before any code lands. Solidity test + Python test produce same digest from same inputs:

| Input | Expected hex |
|---|---|
| `lineHash("basketball_nba", "401584293", "spread", "home", "-3.5")`, chain 84532, registry 0x... | `0x...` |
| `digest(lineHash above, Outcome.Favorable, OUTCOME_RULESET_HASH)` | `0x...` |
| `signature` (with known private key) | `0x...` |
| `recovered signer` | `0x...` |

5+ vectors covering all three markets, both teams, edge cases. Pinned in `contracts/test/LineOutcomeRegistry.t.sol` and `validator/tests/test_outcome_signer.py`.

---

## 3. Phase 2: Validator-side resolution + signing (2 days)

In `validator/djinn_validator/core/outcomes.py`. Refactor `OutcomeAttestor` so resolutions are line-keyed (not signal-keyed); 100 signals containing "Lakers -3.5" share one resolution row.

```python
@dataclass(frozen=True)
class LineKey:
    sport: str
    event_id: str
    market: str
    side: str
    line_value: str

    def to_canonical_string(self) -> str:
        return f"DJINN_LINE_V1|{self.sport}|{self.event_id}|{self.market}|{self.side}|{self.line_value}"

    def line_hash(self, chain_id: int, registry_addr: str) -> bytes:
        # Matches Solidity abi.encodePacked exactly. See golden vectors.
        ...

@dataclass
class LineResolution:
    line_key: LineKey
    outcome: Outcome      # never PENDING — only set after stability soak
    home_score: int
    away_score: int
    espn_status: str
    resolved_at: float       # first time we saw final
    stable_at: float | None  # second consecutive matching poll, ≥180s later
    sig: bytes | None        # EIP-712 sig over (lineHash, outcome, ruleset)
```

**Stability soak**: 3 minutes between consecutive matching polls before signing. Cheap insurance against ESPN flipping during a live correction.

**Once signed, never re-signed for a different outcome.** Operator-only override via `forceVoid`.

**Indistinguishable scheduling (privacy)**: validators MUST resolve every decoy line in a signal at the same cadence as the real line. Implementation: per-signal poll loop iterates ALL lines (real + decoys) on each tick; signs each independently as it stabilizes. Operators monitor per-validator metric `decoy_to_real_attestation_latency_ratio` — anything >1.5 indicates a bug or compromised validator that's deprioritizing decoys.

### EIP-712 signer

`validator/djinn_validator/chain/outcome_signer.py` (new). Reuses validator's OV signer EOA private key (same key as `submitVote`):

```python
def sign_line_outcome(
    private_key: bytes,
    line_hash: bytes,
    outcome: int,
    chain_id: int,
    registry_address: str,
) -> bytes:
    """65-byte ECDSA suitable for ecrecover. Domain-separated by
    (DjinnLineOutcomeRegistry, "1", chainId, registry_address)."""
```

The domain name `DjinnLineOutcomeRegistry` must match the contract's `NAME` constant exactly. Verified by golden vectors.

**One key per validator, forever.** The validator's OV signer EOA signs every line attestation. Same key as `submitVote`. This is the long-term design, not a v1 simplification:

- Matches every comparable protocol (Bittensor, ETH, Cosmos): one key per validator identity.
- Key separation at small validator counts is theatrical — both keys would live on the same hardware managed by the same team. Two locks on the same door.
- The daemon already needs the key continuously; "hot for attestations, warm for governance" is a fiction.
- One canonical validator identity simplifies subgraph, audit trail, reputation lookup. Receipts everywhere trace back to one address.
- Sophisticated operators who want key separation can register a Safe multisig or smart-account wrapper as their OV signer EOA — internal policy is their concern, not the protocol's.

The contract has no separate attestation-key registry. There's no `setAttestationKey` function. There's no v2 path to two keys. One key.

---

## 4. Phase 3: Gossip + submission (1 day)

Validators sign locally, gossip to peers, any validator with 4 matching signatures submits.

1. **Sign locally** (Phase 3) → `LineResolution.sig` populated.
2. **Gossip via existing `/v1/outcomes/gossip`** with additive `eoa_sig` + `eoa` fields. Receivers ignore unknown fields (back-compat with v1746).
3. **Each peer stores incoming sigs** in a `peer_attestations` SQLite table keyed by `(line_hash, peer_eoa)`. Bounded at 5 sigs per line.
4. **First to threshold submits**. Any validator that holds ≥4 distinct-EOA matching sigs AND its own ESPN view agrees calls `LineOutcomeRegistry.submitLineOutcome(...)` directly. No election; race resolves at the contract via skip-already-attested logic.
5. **Idempotency**: if the line is already finalized when a validator submits, the contract no-ops the attestation and the validator drops it locally.

### Retry on RPC error

Reuse existing chain client retry logic (exponential backoff, max attempts). On hard failure, persist as pending in the validator's local SQLite and retry on next epoch.

**`AlreadyFinalized` revert is terminal-success, not retryable**. When a validator's submit reverts with `AlreadyFinalized`, it means a peer's submit already finalized the line. The validator drops the local pending-submit and marks done. Critical: do not classify this as a retryable error and re-submit forever.

No outbox extension needed; the operation is naturally idempotent at the contract level.

---

## 5. Phase 4: MPC integration (1 day)

In `mpc_orchestrator.try_shadow_distributed_settlement`, before `build_purchase_inputs_from_audit_set`:

```python
# v1747: read canonical line outcomes from chain. Deterministic gate.
line_hashes = []
signal_slices = {}
for sig in audit_set.resolved_signals:
    start = len(line_hashes)
    line_hashes.extend(line.line_hash for line in sig.lines)
    signal_slices[sig.signal_id] = (start, len(line_hashes))

try:
    canonical = await chain_client.batch_line_outcomes(
        line_hashes,
        confirmations=2,  # require 2 Base block confirmations before consuming
    )
except ChainReadError:
    # ABSTAIN — never fall back to local outcomes for consensus input.
    SHADOW_SETTLE_OUTCOME.labels(outcome="abstain_rpc_error").inc()
    return None

if any(o == Outcome.PENDING for o in canonical):
    # Every honest validator reaches the same conclusion: not ready.
    SHADOW_SETTLE_OUTCOME.labels(outcome="abstain_canonical_pending").inc()
    return None

# Honesty gate: refuse to vote if local diverges from canonical.
for sig in audit_set.resolved_signals:
    s, e = signal_slices[sig.signal_id]
    if list(sig.outcomes) != list(canonical[s:e]):
        log.error("local_diverges_from_canonical", signal_id=sig.signal_id, ...)
        ALERT_DIVERGENCE.inc()
        return None

# Inject canonical outcomes into PurchaseInputs.
batch = build_purchase_inputs_from_audit_set(
    audit_set,
    share_store=share_store,
    purchase_odds_ledger=purchase_odds_ledger,
    line_outcomes_override=canonical_by_signal,
)
```

**Critical**: on RPC error, abstain. **Never** fall back to local outcomes for consensus input — that recreates the divergence problem.

`Audit.sol`, `OutcomeVoting.sol`, `Account.sol` unchanged. MPC math is unchanged; consumes deterministic inputs now, so quality scores are byte-identical, so 4-of-5 quorum on `submitVote` forms in one round.

The v1716 abstain counter, v1734 permanent abstain, v1746 600-attempt threshold all become dead paths.

### Chain reorg / finality depth

Base testnet/mainnet finalizes within ~1-2 blocks. Require 2 confirmations on `LineFinalized` events before MPC consumes them. Subgraph indexer waits the same. If a finalized event reorgs out, MPC re-checks on next epoch and abstains if it's now Pending — deterministic recovery.

---

## 6. Phase 5: Subgraph + minimal UI (2 days)

### Subgraph entities

```graphql
type Line @entity {
  id: ID!                    # lineHash hex
  sport: String!
  eventId: String!
  market: String!
  side: String!
  lineValue: String
  outcome: Outcome!
  finalizedAt: BigInt
  finalizedAtBlock: BigInt
  finalizedAtTx: Bytes
  attestations: [LineAttestation!]! @derivedFrom(field: "line")
  signals: [SignalLine!]! @derivedFrom(field: "line")
}

type LineAttestation @entity {
  id: ID!
  line: Line!
  attestor: Bytes!
  outcome: Outcome!
  block: BigInt!
  tx: Bytes!
}

type SignalLine @entity {
  id: ID!
  signal: Signal!
  line: Line!
  index: Int!
}
```

Mappings drive entirely off `LineAttested`, `LineFinalized`, `LineForceVoided`. The string fields (sport, eventId, etc.) are derived from `Signal.decoyLines` (already on chain in `SignalCommitment` events) — content not stored on chain.

### Minimum web UI

Two surfaces only for v1:

1. **`/verify/[lineHash]`** (NEW). Standalone shareable page resolving one canonical line: outcome, attestor list (4 addresses), Basescan tx link, ESPN source URL, plain-English render of the line (e.g. "Lakers -3.5 spread, NBA event 401584293").

2. **`/genius/track-record`** (existing, lights up). Each settled cycle expands to per-line outcome chips. New `LineOutcomeChip` component used here and in `/idiot/signal/[id]` post-game state.

That's it. Defer to v1.1+: homepage ticker, settlement panel, profile feed, certificate downloads, leaderboard column, network attestation stats, full docs/API page.

---

## 7. Phase 6: E2E test on Sepolia (2 days)

1. Deploy `LineOutcomeRegistry` via timelock. Wire `validatorRegistry`. Verify on Basescan.
2. Restart all 5 validators on v1747 with `DJINN_FF_OUTCOME_REGISTRY_WRITE=1`. Verify finalization txs land.
3. Generate 5-10 fresh signals, full lifecycle:
   - commit → buy → expire → ESPN resolve → attestation gossip → 4-of-5 finalize → MPC reads canonical → quorum → AuditSettled → USDC distributes
4. Cross-check ESPN manually for each settled line.
5. Verify each layer: parse, hash, attest, finalize, MPC consume, quorum, settle, distribute.

The first observable win: signals settle via canonical-outcome-driven MPC with 4-of-5 quorum on first try, no force-settle needed.

---

## 8. Phase 7: Migration / rollout (1 day work, 1 week soak)

### Phase 7a: Contract deploy
Day 1. Deploy `LineOutcomeRegistry` via timelock. No validators wired yet.

### Phase 7b: Validator dual-write
Days 2-4. Roll v1747 to validators with `DJINN_FF_OUTCOME_REGISTRY_WRITE=1`. Resolve + sign + gossip + finalize on chain. **MPC still reads from local OutcomeAttestor.**

**Important**: until at least 4 validators are writing, **zero finalizations expected**. This is normal. Don't lower the testnet threshold; that creates a production divergence risk later.

Operator monitor: `lines_signed_local` / `lines_finalized_onchain` rates should converge as more validators come online. Per-validator divergence > 5% triggers alert (likely schema bug).

### Phase 7c: Shadow-read soak
Days 5-11 (week-long soak). MPC reads BOTH local and canonical, computes both quality scores, **alerts on mismatch but submits the legacy local-derived score**. This catches schema-encoding bugs, line-ordering bugs, multicall edge cases before flipping authority. No production risk.

### Phase 7d: MPC read-side flip
Day 12. Flip `DJINN_FF_OUTCOME_REGISTRY_READ=1`. MPC consumes canonical from chain. **No fallback to local on RPC error — abstain instead.**

### Phase 7e: Migration boundary
Pre-registry signals (those committed before Phase 7a) stay on the legacy settlement path. They cannot retroactively use canonical outcomes (lines weren't attested). Operator force-settle remains the path for these. Clear cutover at deployment block.

### Phase 7f: Cleanup
After ~1 month stable (not on critical path). Drop legacy outcomes-gossip path (keep purchase_odds gossip). Retire abstain-counter logic. Local OutcomeAttestor stays as divergence-detection oracle.

---

## 9. Operational visibility (minimum)

Launch-critical metrics only. Defer per-validator dashboards, role labels, network panels.

`/health` extension:
```json
{
  "outcomes": {
    "lines_resolved_local": 14823,
    "lines_signed_local": 14801,
    "lines_finalized_onchain": 14793,
    "lines_pending": 22
  }
}
```

`/v1/audit/summary` extension:
```json
{
  "audit_sets_blocked_canonical_pending": 7,
  "audit_sets_blocked_canonical_divergent": 0,
  "outcome_registry_finalized_count": 14793,
  "outcome_registry_finalize_lag_p50_s": 240
}
```

Prometheus:
- `djinn_lines_resolved_local_total`
- `djinn_lines_finalized_onchain_total`
- `djinn_line_finalize_latency_seconds` (histogram)
- `djinn_decoy_to_real_attestation_latency_ratio` (per-validator gauge — privacy monitoring)
- `djinn_shadow_settle_outcome_total{outcome}` (extended labels: `abstain_canonical_pending`, `abstain_local_divergence`, `abstain_rpc_error`, `settled_with_canonical`)

---

## 10. Failure modes

| Mode | Behavior | Operator action |
|---|---|---|
| One ESPN flake (1/5) | Threshold reachable from 4 others; their abstain stays local | Auto-heal; alert if outage >10min |
| Validator-set churn after some attestations counted | Already-counted attestations stay valid; new attestations from removed signers fail. Line can still finalize from the original cohort. | None unless line stalls; then `forceVoid` |
| Validator removed before threshold reached AND fewer than 4 of original signers can re-attest | Line stuck at Pending | `forceVoid(lineHash, "churn-stuck")` via timelock |
| Bad attestation (malformed line) | Decoy validation at signal-commit time prevents this from reaching chain | n/a (rejected pre-commit) |
| 4 attestors disagree (split vote) | No threshold reached; line stuck | `forceVoid(lineHash, "ESPN ambiguity")` |
| Adversarial 4-of-5 collusion | Wrong outcome finalizes | v1: accepted trust assumption. v2: TLSNotary fraud proof. |
| ESPN goes down | Pending; nothing finalizes; nothing settles wrong | Auto-resume when ESPN returns |
| Stat correction post-6h | Frozen view holds | v2 fraud-proof concern |
| RPC blip on MPC read | Abstain (never local fallback) | Auto-recover next epoch |
| Two validators submit simultaneously | Second tx reverts with `AlreadyFinalized`; submitter classifies as terminal-success and drops | n/a (expected, not retryable) |

The deterministic-by-construction property: nothing settles incorrectly. Stalls instead of producing wrong settlements.

---

## 11. Privacy: indistinguishable attestation scheduling

This is enforced in code, not policy. Validators are structurally blind to which line is real.

**Why validators don't know the real line**: the real pick lives in the encrypted signal blob. Decoy lines live in `SignalCommitment.decoyLines` as plaintext strings. Validators read decoyLines from chain and resolve them all. They do not have the share-threshold needed to decrypt the genius's pick — only buyers (with their purchase share + their wallet key) decrypt and learn which decoy is the real pick.

**Therefore**: a validator iterating its resolution loop literally cannot prioritize the real line, because it doesn't know which one it is. The threat surface is narrower than "compromised validator times the real line first" — it requires a colluding genius leaking their real-line index out-of-band to a colluding validator.

**Code-enforced rules** (Phase 2):
1. **Resolution loop iterates `decoyLines` sorted by `lineHash`** (deterministic, content-addressed, real-blind). No iteration order based on signal-time, line-time, or any other distinguishing axis.
2. **Same stability soak (180s) applied to every line uniformly**. No per-line shortcut.
3. **Submit-on-threshold loop iterates lines in the same `lineHash`-sorted order**. Submitter posts attestations in deterministic order, not "the line my buyer needs first."
4. **Settlement waits until ALL candidate lines in the audit batch are finalized**, not just the real ones. UI shows "X/N lines verified" only when X == N.
5. **Decoy line strings validated at signal-commit time** (web client + on-chain check via `SignalCommitment` v3 if needed) so malformed decoys never make it on chain. Force-voids on malformed lines reveal nothing because malformed decoys can't reach commit.

**Backstop monitoring** (still useful, lower-priority): `decoy_to_real_attestation_latency_ratio` per-validator. With code-enforced ordering, this should be ~1.0 always. Anomalies indicate bugs or out-of-band collusion.

**Honest privacy claim**: "Observers see all candidate lines for a signal. Privacy relies on indistinguishability among those candidates, enforced by validator code that processes them in deterministic content-addressed order. Validators are structurally blind to which line is real."

Settlement latency increases (must wait for the slowest decoy game). That's the trade-off: privacy preserved, latency up. Acceptable for v1.

---

## 12. Trust model (explicit)

**v1**: 4-of-5 honest-supermajority of `OutcomeVoting` signer set. A coalition of 4 attestors can finalize an incorrect line. Contract verifies threshold sigs, not ESPN data correctness. Same trust as existing OV; we relocate where agreement happens.

**v1 governance**: `forceVoid` is `onlyOwner` (timelock). Off-chain operator policy SHOULD require multi-sig approval before scheduling, but that is policy not protocol. Contract enforces only the timelock.

**v2** (post-launch): TLSNotary-backed fraud proof contract. Any party posts a TLSNotary attestation of an ESPN response that contradicts a finalized outcome, slashing dishonest attestors. Deployed as a separate contract that holds slashing authority, not a slot reserved in this contract.

**Privacy preserved**:
- Real pick stays in encrypted blob (decoys mask which line).
- (idiot ↔ line) mapping in encrypted purchase share.
- Per-purchase economics aggregated via MPC.
- Per-line outcomes are public (ESPN data is public; indistinguishable scheduling preserves the decoy mechanism).

---

## 13. What this enables next (briefly)

Track-record-as-collateral, third-party analytics, markets-on-geniuses, composable verification primitive, AI training data. None are v1's job — v1's job is land receipts on chain in a shape where these become buildable.

---

## 14. Effort estimate

| Phase | Days | Critical path |
|---|---|---|
| 0. Schema spec + golden vectors | 1-2 | Yes (blocking) |
| 1. LineOutcomeRegistry contract + tests | 2 | Yes |
| 2. Validator: line-keyed resolution + EIP-712 signer + indistinguishable scheduling | 2 | Yes |
| 3. Gossip + idempotent submit | 1 | Yes |
| 4. MPC orchestrator integration | 1 | Yes |
| 5. Subgraph + minimal UI (`/verify`, track-record chips) | 2 | Parallel |
| 6. E2E Sepolia | 2 | Yes |
| 7. Rollout (1 work day + 1 week soak) | 1 + 7 | Yes |

**Total: ~11 days focused engineering, ~3 weeks calendar with the 1-week soak.** Pre-implementation check on OV interface (open question A) is a same-day spike before Phase 1.

---

## 15. Open questions requiring decision before code

All previously open questions resolved:

| # | Question | Resolution |
|---|---|---|
| A | Does deployed `OutcomeVoting.sol` expose `isValidator(address)`? | YES, line 65 of OutcomeVoting.sol — `mapping(address => bool) public isValidator`. Auto-generated getter matches `IValidatorRegistry.isValidator(address)`. No adapter needed. |
| B | Hot-key reuse vs separate attestation key | One key, forever. Validator's OV signer EOA signs everything. No separate registry, no v2 split path. See Phase 2 §3c. |
| C | Decoy attestation indistinguishability | Code-enforced (§11). Validators are structurally blind to which line is real (real in encrypted blob, decoys in plaintext). Resolution loop iterates by sorted lineHash. |

Implementation can start.

---

## 16. Critical files

- `/home/user/djinn/contracts/src/LineOutcomeRegistry.sol` (NEW)
- `/home/user/djinn/contracts/src/OutcomeVoting.sol` — verify `isValidator` exists; reuse unchanged
- `/home/user/djinn/contracts/script/DeployLineOutcomeRegistry.s.sol` (NEW)
- `/home/user/djinn/validator/djinn_validator/core/outcomes.py` — line-keyed refactor + indistinguishable scheduling
- `/home/user/djinn/validator/djinn_validator/chain/outcome_signer.py` (NEW) — EIP-712 typed-data signer
- `/home/user/djinn/validator/djinn_validator/core/mpc_orchestrator.py` — chain-read gate, no local fallback
- `/home/user/djinn/validator/djinn_validator/chain/contracts.py` — `LineOutcomeRegistry` ABI + helpers
- `/home/user/djinn/subgraph/schema.graphql` — `Line`, `LineAttestation`, `SignalLine` entities
- `/home/user/djinn/web/lib/hooks/useLineOutcomes.ts` (NEW)
- `/home/user/djinn/web/components/LineOutcomeChip.tsx` (NEW)
- `/home/user/djinn/web/app/verify/[lineHash]/page.tsx` (NEW)

---

## 17. What we cut and why

This rev is dramatically smaller than rev2. The cuts:

| Cut | Reason |
|---|---|
| Per-validator monotonic nonce | Per-line attestation map already prevents replay; nonce caused liveness deadlocks |
| `OV.syncNonce` binding | Validator set membership checked at submit time; already-counted attestations stay valid through churn (intentional) |
| Reserved fraud-proof storage slot | Fake forward-compat; use `__gap` |
| Mutable threshold | Trust model integrity > governance flexibility |
| Mutable ruleset | New rules = new contract |
| `setConfig` admin function | Nothing left to configure |
| `forceVoided` mapping | Redundant with `lineOutcome == Void` |
| 7-day attestation window | Adds no replay safety; created stuck-line path on premature attestation |
| Submitter election + 60s rotation | Race resolves cheaply at contract; election adds complexity for marginal gas savings |
| Batched `submitAttestations` (multi-line) | Single line per call; simpler; v2 can batch |
| Outbox extension for chain submits | Existing chain client retry is sufficient |
| Full UI suite (homepage ticker, profile feed, certificates, leaderboard cols) | `/verify/[lineHash]` + track-record chips deliver the verifiability promise |
| Third-party API positioning (markets-on-geniuses, AI training, etc.) | One paragraph in §13; defer the framing until receipts are live |

The cuts preserve everything that matters for the long-term protocol and remove ceremony. Privacy, decentralization, verifiability, and on-chain canonical outcomes are intact. What's gone is governance surface, premature optimization, and product packaging.

---

## 18. Closing

This is the long-term design Djinn should have shipped from the start: per-line outcomes on chain as a public protocol primitive, with MPC providing privacy where it actually adds value (per-purchase economic aggregation) rather than as a load-bearing input layer.

The 11-day engineering estimate is honest. The 1-week shadow-read soak is non-negotiable. After Phase 7d, Djinn is verifiable in a way it currently isn't.

Six weeks of patches stop. The protocol grows from this.
