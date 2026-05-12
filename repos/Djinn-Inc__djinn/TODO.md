# Djinn TODO

Comprehensive audit of bugs, improvements, and suggestions across all components.
Generated 2026-04-07 from full codebase scan. Updated after fix pass (commit 307d2a1).

Priority: P0 = fix before mainnet, P1 = fix soon, P2 = nice to have

---

## Bugs

### ~~B-01: Validator .env.example has stale contract addresses~~ FIXED
### ~~B-02: (Verified OK) Not a bug~~
### ~~B-03: Subgraph qualityScore field naming~~ FIXED (added doc comments)
### ~~B-04: Decoy generation can return fewer than requested count~~ (Intentional, documented)
### ~~B-05: Subgraph audit handlers don't create Account entity~~ FIXED
### ~~B-06: SDK shamirK validation~~ FIXED
### ~~B-07: API session secret empty-string fallback~~ FIXED
### ~~B-08: Jigger odds division by zero~~ FIXED

---

## Security

### ~~S-01: CI security scans continue-on-error~~ FIXED
### S-02: Burn gate peer responses are unsigned (P1)
**File:** `validator/djinn_validator/api/burn_gate.py:277-285`
Needs protocol-level hotkey-signed responses. Mitigated by quorum of 2.

### ~~S-03: shell=True in tweet generation~~ FIXED (local, untracked)
### ~~S-04: MPC authenticated mode silently returns None~~ FIXED
### S-05: Dispute resolution not implemented (P0, pre-mainnet)
**Ref:** DEVIATIONS.md DEV-029
Large design task. Staked challenges with 48h finalization, validator re-arbitration.

### ~~S-08: OutcomeVoting validator set is EMPTY on-chain~~ FIXED 2026-04-17
**Found:** 2026-04-16 via fresh-eyes audit on V7.
**Resolution (2026-04-17 13:07 UTC):** `validatorCount() = 5` after timelocked bootstrap registration. Five operator signers registered:
- `0x550A...b15d` (uid=1)
- `0xfae3...cA86` (uid=213)
- `0xD717...1e37` (uid=0, deployer)
- `0x8E77...8eaD` (uid=86)
- `0xDeF8...4A98` (uid=189)
Each confirmed `isValidator=true`. UID 0 `/health` now returns `settlement_registered=True`. The settlement pipeline can function; `submitVote` will no longer revert with `NotValidator` for these EOAs.

Path that got us here:
1. v1176 added `validator_signer` to `/health` (opt-in: requires operator to configure `BASE_VALIDATOR_PRIVATE_KEY`)
2. `scripts/collect-validator-signers.sh` auto-generated the `VALIDATOR_1..5` env block
3. `contracts/script/ScheduleRegisterValidators.s.sol` proposed the batch via timelock (72s delay)
4. `contracts/script/ExecuteRegisterValidators.s.sol` committed it after 72s

### ~~S-06: Hardcoded validator IPs~~ FIXED (metagraph discovery first, env fallback)
### ~~S-07: Cron endpoint unprotected~~ FIXED

---

## Contract Improvements (no contract changes this pass)

### C-01: Account v1-to-v2 migration has no gas bound (P1)
Next upgrade: document limits or add batched migration.

### C-02: SignalCommitment uses staticcall instead of interface (P1)
Next upgrade: import ICollateral.

### C-03: Missing granular events in Audit settlement (P2)
Next upgrade: add per-action events.

### C-04: Signed integer overflow in quality score calculation (P2)
Theoretical. Bounded in practice by USDC amounts and odds ranges.

---

## Web Improvements

### ~~W-01: Update web .env.example~~ FIXED
### ~~W-02: Validator env missing Audit address~~ FIXED (in B-01)
### W-03: SHAMIR_MAX still at 3, should have roadmap to raise (P1)
Monitor validator health. Raise when 7+ have stable MPC.

### ~~W-04: Empty catch blocks~~ FIXED (annotated)
### ~~W-05: JSON.parse validation~~ FIXED (try-catch + clear corrupted data)

---

## Validator/Miner Improvements

### V-01: Broad exception handling in validator main loop (P2)
Large refactor. Lower priority than functional fixes.

### ~~V-02: Validator __init__ swallows errors~~ FIXED (warnings.warn)
### V-03: MPC semi-honest to malicious security (P1)
Major crypto work. Add SPDZ MAC verification.

### ~~V-04: MPC session TTL sweep~~ FIXED
### ~~V-05: Missing MPC negative test cases~~ FIXED (cb5795f)
Added: progressive dropout, peer timeout, concurrent sessions, malformed responses.

---

## Infrastructure/CI

### ~~I-01: SDK tests in CI~~ FIXED
### I-02: Docker integration tests may use stale addresses (P2)
Verify docker-compose.test.yml references current contracts.

### I-03: No Slither baseline for known issues (P2)

---

## Scripts (local, untracked)

### X-01: Hardcoded contract addresses in scripts (P2)
### ~~X-02: Hardcoded RPC URL~~ FIXED (local)
### ~~X-03: Telegram token parsing~~ FIXED (local)

---

## Documentation

### D-01: DEVIATIONS.md is getting long (P2)
Archive superseded entries.

### D-02: Whitepaper needs update pass (P2)
Queue-based audits, blind resolution, ESPN scores.

---

## Remaining Strategic Items

### F-01: Dispute resolution system (P0, pre-mainnet)
### F-02: Raise SHAMIR_MAX back to 7 (P1)
### F-03: SPDZ MAC for malicious-security MPC (P1)
### ~~F-04: Remove CI security scan continue-on-error~~ FIXED
