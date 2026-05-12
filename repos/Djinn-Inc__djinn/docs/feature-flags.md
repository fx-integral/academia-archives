# Feature Flag Inventory

Every active feature flag in the Djinn protocol lives here. When you add a flag, add a row. When you remove a flag, delete the row. **Dead flags accumulate; this file is the discipline that prevents that.**

## Conventions

- Validator flags: env var `DJINN_FF_<UPPER_NAME>=true`. Read once at startup.
- Web client flags: build-time env var `NEXT_PUBLIC_DJINN_FF_<UPPER_NAME>=true`, with runtime override via `localStorage.setItem("djinn_ff_<lower_name>", "true")` for QA.
- All flags default to OFF.
- Flags should have a planned removal date. If the date passes and the flag is still here, schedule its removal in the next sprint.

## Active flags

### `circuit_breaker` / `circuitBreaker`

- **Added:** 2026-04-11
- **Owners:** validator, web client
- **Default:** OFF
- **What it controls:** CUSUM-based miner deviation tracking and the on-flag TLSNotary appeal mechanism. When OFF, validators score miners only by current consensus agreement. When ON, per-miner CUSUM scores are tracked and flagged miners are notified.
- **On where:** none yet (will land first on UID 0 once shadow mode is implemented)
- **Removal plan:** remove the OFF code path once the new mechanism has run on all validators for 30 days without regression.
- **Reference:** `~/.claude/projects/-home-user-djinn/memory/project_consensus_circuit_breaker.md`

### `canonical_odds` / `canonicalOdds`

- **Added:** 2026-04-11
- **Owners:** validator, miner, web client
- **Default:** OFF
- **What it controls:** Canonical internal odds schema with miner-side adapters. When OFF, validator uses Odds API shape directly. When ON, validator queries miners for canonical-schema responses and runs consensus over those.
- **On where:** none yet
- **Removal plan:** remove the OFF code path once miner adapters are deployed network-wide.
- **Reference:** `~/.claude/projects/-home-user-djinn/memory/project_canonical_odds_schema.md`

### `appeal_mechanism` / `appealMechanism`

- **Added:** 2026-04-11
- **Owners:** validator, miner
- **Default:** OFF
- **Depends on:** `circuit_breaker`
- **What it controls:** TLSNotary-backed appeal endpoint for flagged miners. When ON, validator accepts appeal submissions and resolves them. When OFF, flagged miners can only accept the slash, not appeal.
- **On where:** none yet
- **Removal plan:** remove the OFF code path once the appeal mechanism has run on all validators for 30 days.
- **Reference:** `~/.claude/projects/-home-user-djinn/memory/project_consensus_circuit_breaker.md`

### `purchase_v2` / `purchaseV2`

- **Added:** 2026-04-11
- **Owners:** contracts, validator, web client
- **Default:** OFF
- **What it controls:** Phase 2 purchase flow with oracle attack mitigation, vectorHash field, batch settlement support. Calls `purchaseV2()` contract function instead of `purchase()`. Cross-checks buyer-claimed availability against independent miner consensus.
- **On where:** none yet
- **Removal plan:** keep `purchase()` (V1) live indefinitely for old clients. Pause it via `Pausable` once usage drops to zero. Remove this flag (and unconditionally use V2) once all known clients have migrated.
- **Reference:** task #8, task #10

### `new_miner_zero_weight` / `newMinerZeroWeight`

- **Added:** 2026-04-11
- **Owners:** validator
- **Default:** OFF
- **What it controls:** Bootstrap delay for newly-registered miner hotkeys. New miners start at zero weight until they pass a minimum sample count.
- **On where:** none yet
- **Removal plan:** make permanent (remove flag, always on) once it has run on all validators for 30 days.
- **Reference:** task #19, `~/.claude/projects/-home-user-djinn/memory/project_incentive_attack_surface.md`

### `quorum_strict` / `quorumStrict` (umbrella)

- **Added:** 2026-04-11
- **Owners:** web client
- **Default:** OFF
- **What it controls:** Umbrella ON-flips-everything switch. When ON, the client uses 3-of-N validator agreement for ALL high-stakes calls. Adds ~400ms latency per call. Use the per-call flags below if you only want strict mode for some calls.
- **On where:** none yet
- **Removal plan:** make permanent for high-stakes calls once the per-call defaults are tuned. Remove flag once stable.
- **Reference:** task #18

### `quorum_strict_check_odds` / `quorumStrictCheckOdds`

- **Added:** 2026-04-12
- **Owners:** web client
- **Default:** OFF
- **What it controls:** Strict 3-of-N quorum for the buyer's check-odds call only. Other call types stay in race mode. ~400ms cost per check-odds call. Recommended for first rollout because check-odds is the most common high-stakes call.
- **On where:** none yet
- **Removal plan:** make permanent once the latency cost is verified acceptable in production.

### `quorum_strict_purchase` / `quorumStrictPurchase`

- **Added:** 2026-04-12
- **Owners:** web client
- **Default:** OFF
- **What it controls:** Strict 3-of-N quorum for the purchase MPC call only. The MPC dominates the total time of a purchase, so the incremental cost of strict quorum is small (a few hundred ms on top of seconds of MPC).
- **On where:** none yet
- **Removal plan:** make permanent once verified.

### `reliability_weight`

- **Added:** 2026-04-17
- **Owners:** validator
- **Default:** OFF
- **What it controls:** Amplifies `notary_reliability` and `shield_installed` in the scoring formula to break the linear-per-UID scaling sybils enjoy today. Once a miner has `lifetime_notary_duties_assigned >= 5` (evidence threshold), raw score is multiplied by `max(0.20, notary_reliability)`. Miners with `shield_installed=true` get an unconditional `+20%` score bonus. Goal: sub-linear sybil scaling without penalizing genuinely new miners who haven't been picked to notarize yet.
- **On where:** none yet (will land first on UID 0)
- **Removal plan:** once validated on UID 0 for ~7 days without zeroing honest miners or breaking emissions distribution, ratchet the reliability floor down (0.20 → 0.10 → 0.05) across releases and eventually bake into the default scorer.
- **Reference:** `~/.claude/projects/-home-user-djinn/memory/project_stake_gate_sequencing.md`

### `proof_complexity_weight`

- **Added:** 2026-04-17
- **Owners:** validator
- **Default:** OFF
- **What it controls:** Multiplies the miner's final weight by a proof-complexity factor derived from `max(avg_prover_bytes, avg_notary_bytes)`. Factor is log-scaled with a 1 KB reference point: 1 KB → 1.0x, 8 KB → ~1.3x, 64 KB → ~1.6x, 1 MB+ → 2.0x (capped). Depends on the `lifetime_{attestation,notary}_{proof_bytes,duration_ms}` counters (instrumented in v1173). Only applied once a miner has at least 3 successful sessions on whichever side (prover or notary) is being measured, so it doesn't punish cold-start miners. Goal: a sybil cluster with one sidecar serving 30 UIDs shows the same avg-bytes as a single honest miner with one sidecar, so the 30-UID amplifier is capped at 1x per session — killing the linear-per-UID payoff for tiny-session spray attacks. Honest miners serving heavy sites (debust, firmrecord) get rewarded proportionally.
- **On where:** none yet (will land first on UID 0 once we've measured dynamic range)
- **Removal plan:** once the curve is validated and byte-size distributions stabilize, bake into the default scorer.
- **Reference:** `~/.claude/projects/-home-user-djinn/memory/project_stake_gate_sequencing.md`

## Removed flags

(none yet)

## How to use

### Adding a new flag

1. Add the constant to `validator/djinn_validator/feature_flags.py` and/or `web/lib/featureFlags.ts`.
2. Add the corresponding test in `validator/tests/test_feature_flags.py` and/or `web/lib/__tests__/featureFlags.test.ts`.
3. Add a row above with all required fields.
4. Wire the flag into the code path.
5. Default state is OFF. Always ship the OFF path first, then enable on UID 0, then expand.

### Removing a flag

1. Confirm the new code path has been ON for the agreed window without regression.
2. Delete the OFF code path.
3. Delete the flag from `feature_flags.py` / `featureFlags.ts` and the tests.
4. Move the flag's row from "Active flags" to "Removed flags" with the removal date.
5. Audit `.env.example` and any deployment docs for stale references.
