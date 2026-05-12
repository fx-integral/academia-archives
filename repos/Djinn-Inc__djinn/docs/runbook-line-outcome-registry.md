# LineOutcomeRegistry — Operator Runbook

How to deploy and upgrade the v1747 `LineOutcomeRegistry` proxy.

## Background

`LineOutcomeRegistry` records canonical sports-outcome attestations. Validators
sign EIP-712 typed data with their `OutcomeVoting` signer EOA; 4-of-5 distinct
attestations finalize a line's outcome on chain. Owner is the
`TimelockController` (same one that owns Audit, Escrow, OutcomeVoting, etc.).

Spec: `docs/v1747-final.md` and `docs/v1747-line-schema.md`.
Audit: `contracts/AUDIT_REPORT_LineOutcomeRegistry.md`.

---

## 1. Deploy (one-time)

### Prerequisites

| Variable | Source |
|---|---|
| `DEPLOYER_KEY` | `~/djinn/contracts/.env` |
| `TIMELOCK_ADDRESS` | `0x37f41EFfa8492022afF48B9Ef725008963F14f79` (Base Sepolia + Mainnet) |
| `OUTCOME_VOTING_ADDRESS` | `0xAD534f4CAB13707BD4d65e4EF086A455e6A643e5` (Sepolia; mainnet differs) |
| `BASE_RPC_URL` | `https://sepolia.base.org` (or mainnet) |
| `BASESCAN_API_KEY` | for `--verify` |

### Run

```bash
cd contracts

DEPLOYER_KEY=0x... \
TIMELOCK_ADDRESS=0x37f41EFfa8492022afF48B9Ef725008963F14f79 \
OUTCOME_VOTING_ADDRESS=0xAD534f4CAB13707BD4d65e4EF086A455e6A643e5 \
forge script script/DeployLineOutcomeRegistry.s.sol \
  --rpc-url https://sepolia.base.org \
  --broadcast \
  --verify
```

Output prints both impl and proxy addresses. **Save the proxy address** — that
is what validators, the subgraph, and the web app point at.

### Post-deploy verification

```bash
PROXY=0x...  # from deploy output
cast call $PROXY "owner()(address)" --rpc-url $BASE_RPC_URL
# -> 0x37f41EFfa8492022afF48B9Ef725008963F14f79

cast call $PROXY "validatorRegistry()(address)" --rpc-url $BASE_RPC_URL
# -> 0xAD534f4CAB13707BD4d65e4EF086A455e6A643e5

cast call $PROXY "THRESHOLD()(uint8)" --rpc-url $BASE_RPC_URL
# -> 4

cast call $PROXY "OUTCOME_RULESET_HASH()(bytes32)" --rpc-url $BASE_RPC_URL
# -> 0x7f7efd2324077903b3d02386da944792ea0011315004a4919c047db157fc8786

cast call $PROXY "domainSeparatorV4()(bytes32)" --rpc-url $BASE_RPC_URL
# -> use this to cross-check off-chain signers
```

### Wire dependents

After verification, update:

1. **Validator config**: set `LINE_OUTCOME_REGISTRY=$PROXY` in each validator's
   environment, restart so the chain client picks it up.
2. **Subgraph**: edit `subgraph/subgraph.yaml`'s `LineOutcomeRegistry` data
   source to use `$PROXY` for `address` and the deploy block for `startBlock`,
   then `graph deploy`.
3. **Web app**: set `NEXT_PUBLIC_LINE_OUTCOME_REGISTRY=$PROXY` in the Vercel
   env so `useLineOutcomes` and `/verify/[lineHash]` resolve correctly.

---

## 2. Upgrade ceremony

`_authorizeUpgrade` is gated on `whenPaused`. The upgrade is a three-call
atomic batch executed by `TimelockController.scheduleBatch` →
`executeBatch`:

1. `proxy.pause()`
2. `proxy.upgradeToAndCall(newImpl, "")`
3. `proxy.unpause()`

All three execute in the SAME transaction once the timelock delay passes.
The contract is paused only for the duration of one block; no ongoing
attestations fail.

### Steps

**Step 1: deploy the new implementation** (no init data needed; the proxy is
already initialized).

```bash
DEPLOYER_KEY=0x... \
forge create src/LineOutcomeRegistry.sol:LineOutcomeRegistry \
  --rpc-url $BASE_RPC_URL \
  --broadcast \
  --verify
# -> Save new impl address as NEW_IMPL_ADDRESS
```

**Step 2: schedule the batch**.

```bash
DEPLOYER_KEY=0x... \
TIMELOCK_ADDRESS=0x37f41EFfa8492022afF48B9Ef725008963F14f79 \
REGISTRY_PROXY_ADDRESS=$PROXY \
NEW_IMPL_ADDRESS=$NEW_IMPL_ADDRESS \
PHASE=schedule \
SALT_TAG="lor-upgrade-$(date +%s)" \
forge script script/UpgradeLineOutcomeRegistry.s.sol \
  --rpc-url $BASE_RPC_URL \
  --broadcast
# Note the SALT_TAG that prints; you'll need it for execute.
```

**Step 3: wait for the timelock delay**. 72 seconds on testnet; verify
mainnet via `cast call $TIMELOCK_ADDRESS "getMinDelay()(uint256)"`.

**Step 4: execute the batch** (use the SAME `SALT_TAG` from step 2).

```bash
DEPLOYER_KEY=0x... \
TIMELOCK_ADDRESS=0x37f41EFfa8492022afF48B9Ef725008963F14f79 \
REGISTRY_PROXY_ADDRESS=$PROXY \
NEW_IMPL_ADDRESS=$NEW_IMPL_ADDRESS \
PHASE=execute \
SALT_TAG="lor-upgrade-..."  # same value from step 2 \
forge script script/UpgradeLineOutcomeRegistry.s.sol \
  --rpc-url $BASE_RPC_URL \
  --broadcast
```

**Step 5: verify post-upgrade**.

```bash
# Read the EIP-1967 implementation slot
cast storage $PROXY 0x360894a13ba1a3210667c828492db98dcef82caa57a01eaf42b5fa2a87c0aa --rpc-url $BASE_RPC_URL
# Last 20 bytes should equal NEW_IMPL_ADDRESS

# Confirm contract is not stuck paused
cast call $PROXY "paused()(bool)" --rpc-url $BASE_RPC_URL
# -> false

# Confirm pinned constants survived
cast call $PROXY "THRESHOLD()(uint8)" --rpc-url $BASE_RPC_URL  # -> 4
cast call $PROXY "OUTCOME_RULESET_HASH()(bytes32)" --rpc-url $BASE_RPC_URL
# -> 0x7f7efd2324077903b3d02386da944792ea0011315004a4919c047db157fc8786
```

### Why the three-call batch (not three separate ceremonies)?

`scheduleBatch` lets us atomically pause + upgrade + unpause. If we ran them
as three separate timelock operations:

- 3× the timelock delay (3 × 72s on testnet, 3 × 72h on mainnet).
- The contract would be paused for the full duration between schedule and
  execute of the unpause op — minutes on testnet, days on mainnet. New
  attestations would fail during that window.
- Three opportunities to fat-finger the salt, the wrong impl address, etc.

The batch is one schedule + one execute. Same delay as a single op. Pause
window is one block.

---

## 3. Routine operations (non-upgrade)

### Force-void a stuck line

When a line is genuinely stuck (4-of-5 validators honestly disagree, ESPN
ambiguity, malformed decoy that never reaches threshold), the operator can
void it via timelock. This sets `lineOutcome[lineHash] = Void`; never
`Favorable`/`Unfavorable`.

```bash
LINEHASH=0x...  # the stuck line's hash
REASON="ESPN ambiguity: Lakers/Celtics game played 2026-XX-XX, ESPN reported \
inconsistent scores between scoreboard and box-score endpoints"

# Schedule
cast send $TIMELOCK_ADDRESS \
  "schedule(address,uint256,bytes,bytes32,bytes32,uint256)" \
  $PROXY 0 \
  $(cast calldata "forceVoid(bytes32,string)" $LINEHASH "$REASON") \
  $(cast hz) \
  $(cast keccak "force-void-$(date +%s)") \
  $(cast call $TIMELOCK_ADDRESS "getMinDelay()(uint256)") \
  --rpc-url $BASE_RPC_URL --private-key $DEPLOYER_KEY

# wait for delay, then execute with the same salt
```

Off-chain operator policy: this should require multi-sig approval before
scheduling (the contract enforces only the timelock; multi-sig is policy).

### Pause / unpause

In response to a critical bug, the pauser (= owner = timelock) can pause
attestation submissions. Existing finalized lines remain queryable. Standard
pattern; same as Audit, Escrow, etc.

---

## 4. Rollback

If a deployed implementation has a critical bug, the rollback is the same as
any UUPS upgrade — schedule + execute a batch that points the proxy back at
the previous implementation. The same script (`UpgradeLineOutcomeRegistry`)
works with `NEW_IMPL_ADDRESS` set to the prior impl. The two-step ceremony
applies.

The prior implementation address is in the deploy log. Save it.

---

## 5. Common mistakes

- **Forgot to pause before scheduling upgrade**: `_authorizeUpgrade` reverts
  with `EnforcedPause` on execute. Solution: use the batched
  `UpgradeLineOutcomeRegistry` script — it pauses inside the batch.
- **Reused `SALT_TAG` between schedule and execute**: ensure the SAME tag is
  passed to both phases. The script defaults to a timestamp-keyed tag
  generated AT SCRIPT RUN — but if you re-run with a new timestamp between
  schedule and execute, you'll get `TimelockUnexpectedOperationState`.
- **Wrong proxy address in deploy step**: validators sign against
  `address(this)` of the registry. If validators have an old address while
  the subgraph indexes a new one, attestations won't verify. Always update
  validator and subgraph configs together.
- **Used `setOutcomeVoting` to change validator source**: that function
  doesn't exist. `validatorRegistry` is set once in `initialize` and is
  immutable thereafter (by design — prevents owner-driven validator-set
  rug). If `OutcomeVoting` is ever migrated to a new proxy address, you
  must deploy a new `LineOutcomeRegistry` and migrate.

---

## 6. Quick reference

| Address | Sepolia | Mainnet |
|---|---|---|
| TimelockController | `0x37f41EFfa8492022afF48B9Ef725008963F14f79` | TBD |
| OutcomeVoting | `0xAD534f4CAB13707BD4d65e4EF086A455e6A643e5` | TBD |
| LineOutcomeRegistry (proxy) | `0x2AB6ef76464D25713dfc3b9613f6AD2d07218352` | TBD |
| LineOutcomeRegistry (impl @ deploy) | `0xA6ea74C64d77Dd080c5713eC42506Db6a8Cc3A20` | TBD |

| Constant | Value |
|---|---|
| `THRESHOLD` | 4 |
| `OUTCOME_RULESET_HASH` | `keccak256("DJINN_OUTCOMES_V1")` = `0x7f7efd2324077903b3d02386da944792ea0011315004a4919c047db157fc8786` |
| EIP-712 domain name | `DjinnLineOutcomeRegistry` |
| EIP-712 version | `1` |
| Timelock min delay (Sepolia) | 72 seconds |
| Timelock min delay (Mainnet) | TBD |
