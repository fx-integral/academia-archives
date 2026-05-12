# v1747 — Canonical line schema

The trust boundary for `LineOutcomeRegistry`. Without byte-identical agreement
between Solidity, Python validators, and any third-party verifier, "canonical"
is meaningless. This document is the authority; golden vectors in
`contracts/test/fixtures/v1747_golden_vectors.json` are the proof.

If you change anything here, regenerate vectors via
`python3 scripts/v1747_golden_vectors.py > contracts/test/fixtures/v1747_golden_vectors.json`
and verify Foundry tests still pass.

---

## 1. Canonical line string

```
DJINN_LINE_V1|<sport>|<event_id>|<market>|<side>|<line_value>
```

Strict format:

- ASCII only. No UTF-8 multi-byte characters.
- Lowercase. No uppercase letters in any field.
- No leading or trailing whitespace anywhere.
- Exactly 5 pipe characters (`|`) producing 6 fields including the leading `DJINN_LINE_V1` literal.
- The 6th field (`line_value`) is empty for moneyline; the canonical string therefore ends with a trailing pipe.
- No internal whitespace within fields.

### Field domains

| Field | Allowed values |
|---|---|
| Literal | exactly `DJINN_LINE_V1` |
| `sport` | `basketball_nba`, `basketball_ncaab`, `americanfootball_nfl`, `americanfootball_ncaaf`, `baseball_mlb`, `icehockey_nhl`, `soccer_epl`, `soccer_usa_mls` |
| `event_id` | ASCII numeric string. ESPN event id from the canonical endpoint. ≤16 characters. |
| `market` | `spread` \| `total` \| `moneyline` |
| `side` | for `spread`/`moneyline`: `home` \| `away`. For `total`: `over` \| `under`. |
| `line_value` | for `spread`/`total`: signed decimal exactly one decimal place, e.g. `-3.5`, `+0.0`, `220.5`, `-7.5`. Sign mandatory for spread (positive sign is `+`); sign optional for total (treat as positive if absent — but generate `+` always to keep canonical form). For `moneyline`: empty string. |

### Decimal canonicalization

For `line_value`:
- Always one decimal place. `-3` is invalid; must be `-3.0`. `220.50` is invalid; must be `220.5`.
- Sign is mandatory for `spread` and for non-zero `total`. The sign character is `+` for non-negative values and `-` for negative.
- `+0.0` is the canonical zero (for spread/total). Never `-0.0`, never just `0.0`.
- No comma separators, no scientific notation, no underscores.

### Examples

| Description | Canonical string |
|---|---|
| Lakers -3.5 spread, home favorite | `DJINN_LINE_V1\|basketball_nba\|401584293\|spread\|home\|-3.5` |
| Same game, away dog | `DJINN_LINE_V1\|basketball_nba\|401584293\|spread\|away\|+3.5` |
| Same game, over 220.5 | `DJINN_LINE_V1\|basketball_nba\|401584293\|total\|over\|220.5` |
| Same game, home moneyline (note trailing pipe) | `DJINN_LINE_V1\|basketball_nba\|401584293\|moneyline\|home\|` |
| EPL home spread, integer push | `DJINN_LINE_V1\|soccer_epl\|654712\|spread\|home\|+0.0` |

---

## 2. lineHash

```
lineHash = keccak256(abi.encodePacked(
    "DJINN_LINE_V1",            // 13 bytes literal (no length prefix in encodePacked)
    block.chainid,              // 32 bytes uint256, big-endian
    address(LineOutcomeRegistry), // 20 bytes (no padding in encodePacked)
    canonical_line_string       // variable bytes UTF-8 (in practice ASCII)
))
```

**Important byte-encoding rules** (these are the failure points if Python ↔ Solidity diverge):

- `abi.encodePacked` for a string literal emits the raw UTF-8 bytes with NO length prefix.
- `abi.encodePacked` for `uint256` emits 32 bytes big-endian.
- `abi.encodePacked` for `address` emits 20 bytes (NOT left-padded to 32 like `abi.encode` would do).
- `abi.encodePacked` for a string variable emits raw UTF-8 bytes with NO length prefix.

The total preimage length is `13 + 32 + 20 + len(canonical_string)` bytes.

Python implementation (`scripts/v1747_golden_vectors.py:line_hash`):

```python
canonical = key.canonical_string().encode("ascii")
addr_bytes = bytes.fromhex(registry_address.lower().removeprefix("0x"))
preimage = (
    b"DJINN_LINE_V1"
    + chain_id.to_bytes(32, "big")
    + addr_bytes
    + canonical
)
return keccak256(preimage)
```

Solidity implementation (in `LineOutcomeRegistry.sol`):

```solidity
function lineHash(string memory canonicalString) public view returns (bytes32) {
    return keccak256(abi.encodePacked(
        "DJINN_LINE_V1",
        block.chainid,
        address(this),
        canonicalString
    ));
}
```

### Why a chain+contract binding inside the preimage

Without the chain id and contract address inside the preimage, the same lineHash would resolve to different on-chain canonical outcomes on different chains or under future contract redeployments. Binding them inside the hash makes lineHashes globally unique to a specific (chain, registry) deployment. Sigs over a lineHash from chain A cannot be replayed against chain B; sigs against `LineOutcomeRegistry@v1` cannot be replayed against `@v2`.

---

## 3. EIP-712 attestation digest

Validators sign the digest below with their OV signer EOA (the same key registered in `OutcomeVoting.isValidator`).

### Domain separator

```
EIP712Domain(string name,string version,uint256 chainId,address verifyingContract)
name = "DjinnLineOutcomeRegistry"
version = "1"
chainId = block.chainid
verifyingContract = address(LineOutcomeRegistry)
```

### Type hash

```
LineAttestation(bytes32 lineHash,uint8 outcome,bytes32 rulesetHash)
```

### Struct hash

```
structHash = keccak256(abi.encode(
    keccak256("LineAttestation(bytes32 lineHash,uint8 outcome,bytes32 rulesetHash)"),
    lineHash,
    uint8(outcome),
    OUTCOME_RULESET_HASH
))
```

Note this uses `abi.encode` (not `encodePacked`): each field is padded to 32 bytes. `outcome` is a `uint8` so it gets left-padded with 31 zero bytes.

### Final digest

```
digest = keccak256("\x19\x01" || domainSeparator || structHash)
```

This is the hash passed to `ECDSA.recover(digest, signature)` on chain.

### OUTCOME_RULESET_HASH

```
OUTCOME_RULESET_HASH = keccak256("DJINN_OUTCOMES_V1")
                    = 0x7f7efd2324077903b3d02386da944792ea0011315004a4919c047db157fc8786
```

Immutable. Schema changes require a new contract deployment with a new ruleset
tag, not a config flip.

---

## 4. Outcome enum

```
enum Outcome { Pending, Favorable, Unfavorable, Void }
                  0         1           2          3
```

Mapping to the bet:

- **Favorable**: the line resolved in favor of the buyer's bet (genius's pick was right).
- **Unfavorable**: the line resolved against the buyer's bet (genius's pick was wrong).
- **Void**: no economic outcome (push, cancelled, postponed-then-voided, abandoned, integer-push, terminal ambiguity).
- **Pending**: not yet resolved. Used as the contract sentinel for "no attestation yet"; validators NEVER sign `Pending`.

---

## 5. Resolution rules per sport

A pure function `canonical_outcome_for_line(sport, market, side, line_value, espn_event)` →
`Outcome`. Deterministic, no clock or env or private state.

ESPN canonical endpoint: `https://site.api.espn.com/apis/site/v2/sports/{sport}/events/{event_id}`.
Field paths:

- Status: `competitions[0].status.type.name`
- Home/away identification: `competitions[0].competitors[*].homeAway`
- Final score: `competitions[0].competitors[*].score` (after status reaches terminal)
- Event start: `competitions[0].date`
- Completion time: `competitions[0].status.type.completed == true && status.type.name in terminal set`

### Terminal status set per sport

| Sport | Terminal statuses |
|---|---|
| `basketball_nba`, `basketball_ncaab` | `STATUS_FINAL` |
| `americanfootball_nfl`, `americanfootball_ncaaf` | `STATUS_FINAL` |
| `baseball_mlb` | `STATUS_FINAL`, `STATUS_END_OF_REGULATION` |
| `icehockey_nhl` | `STATUS_FINAL`, `STATUS_AFTER_SHOOTOUT` |
| `soccer_epl`, `soccer_usa_mls` | `STATUS_FULL_TIME`, `STATUS_AFTER_EXTRA_TIME`, `STATUS_AFTER_PENALTIES` |

### Score interpretation

- **Spread**: home_score − away_score ⇒ HD. If `side=home`, line `L`: HD + L > 0 → Favorable; HD + L < 0 → Unfavorable; HD + L = 0 → Void. If `side=away`, line `L`: -HD + L > 0 → Favorable; etc.
- **Total**: home_score + away_score ⇒ T. If `side=over`, line `L`: T > L → Favorable; T = L → Void; T < L → Unfavorable. If `side=under`, inverse.
- **Moneyline**: home_score vs away_score (after terminal status, including OT/extra time/penalties as listed). If side wins → Favorable; loses → Unfavorable; tie (where ESPN reports a tie status, e.g. soccer regular time without ET) → Void.

### Sport-specific rules

| Sport | Rule |
|---|---|
| `icehockey_nhl` | Shootout goal does NOT count toward `total` or `spread` (regulation+OT only). Moneyline includes shootout result. **House rule, documented.** |
| `soccer_*` | Spread/total settle at full-time (90'+stoppage). Moneyline includes ET and penalties for "winner" determination. |
| `baseball_mlb` | Weather-shortened ≥5 innings completes. `STATUS_END_OF_REGULATION` is treated as final for spread/total. |
| `americanfootball_*` | OT counts toward all markets. |
| `basketball_*` | OT counts toward all markets. |

### Edge cases

- **Postponed**: outcome is `Pending` until the game is played within 7 days of `competitions[0].date`. After 7 days have elapsed: `Void`.
- **Cancelled**, **abandoned**, **forfeited**: `Void`.
- **Doubleheaders (MLB)**: each game has its own ESPN event_id; no protocol special case.
- **Stat corrections**: ESPN data is read once at `event.completion_time + 6h`. Frozen after that. Post-finality corrections are a v2 fraud-proof concern, not v1.
- **Push on integer spreads / totals**: `Void`. Most lines use `.5` by convention; integer pushes are rare.
- **Tie on moneyline** (where ESPN reports it, e.g. soccer regular time without ET): `Void`.

---

## 6. Indistinguishability discipline (privacy)

Validators MUST iterate decoy lines in deterministic, content-addressed order
(sorted by `lineHash`). They MUST apply the same stability soak (180s) to every
line. They MUST NOT prioritize any line based on signal-time, real-vs-decoy
distinction (which they cannot determine), or ordering hints from off-chain
sources.

This makes attestation-timing leakage structurally impossible from honest
validator code. A compromised validator that out-of-band learns the real
line and prioritizes it would deviate from this discipline; the metric
`decoy_to_real_attestation_latency_ratio` per-validator catches this as a
backstop.

The settlement layer ALSO waits for ALL candidate lines in an audit batch to
finalize before MPC, not just enough for the real bet. Without this, the
settlement timing itself leaks "the real line resolved at time T."

---

## 7. Golden vectors

`contracts/test/fixtures/v1747_golden_vectors.json` contains 12 vectors covering:

- All sports (basketball_nba, basketball_ncaab, americanfootball_nfl, americanfootball_ncaaf, baseball_mlb, icehockey_nhl, soccer_epl, soccer_usa_mls)
- All markets (spread, total, moneyline)
- All sides (home, away, over, under)
- All outcomes (Favorable, Unfavorable, Void)
- Edge cases: integer push, moneyline trailing pipe

Each vector pins:

- canonical_string (verbatim bytes)
- line_hash (32 bytes)
- digest (32 bytes; EIP-712 final digest for the attestation)
- signer (recovered EOA address)
- signature (65 bytes)

Foundry tests load this JSON and assert byte-for-byte equivalence between the
contract's computation and the Python-generated values. Any divergence is a
ship-blocker.

To regenerate: `python3 scripts/v1747_golden_vectors.py > contracts/test/fixtures/v1747_golden_vectors.json`.

---

## 8. Versioning

This document defines `DJINN_LINE_V1` and `DJINN_OUTCOMES_V1`. A future schema
revision (new sport, new market, new resolution rule) is a new version
identifier. Old contracts remain canonical for old version's lines. Validators
running new code must continue producing v1-compatible attestations until the
fleet upgrades.

The version tag is bound into the lineHash preimage AND the EIP-712 ruleset
hash. Sigs are not portable between schema versions.
