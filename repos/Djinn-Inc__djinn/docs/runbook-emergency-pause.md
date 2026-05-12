# Emergency Pause Runbook

This runbook covers pausing live contracts to halt user-facing activity during an incident. Use when:

- A critical bug is found in escrow, settlement, or signal commitment and user funds are at risk.
- A validator quorum failure prevents settlement and stale state accumulates.
- A suspected smart-contract exploit is in progress (front-running observed).

**Do not pause for non-critical issues.** Every pause is a user-visible outage; users lose confidence, and unpausing is a 72h-timelocked operation. Prefer runbook patches that work around the issue.

## Authority model

Every `Pausable` contract (Escrow, SignalCommitment, Audit, OutcomeVoting, Account, Collateral, CreditLedger) exposes:

| Function | Caller | Timelock? | Purpose |
|----------|--------|-----------|---------|
| `pause()` | `pauser` OR `owner()` | **No (fast path via `pauser`)** | Stop user activity |
| `unpause()` | `owner()` only | **Yes — 72h on mainnet** | Resume activity |
| `setPauser(address)` | `owner()` only | Yes — 72h on mainnet | Rotate pauser role |

`pauser` is an EOA or Safe address set at deploy (`_setupPauser` in `contracts/script/Deploy.s.sol`). On mainnet, `Deploy.s.sol:64` requires `PAUSER_ADDRESS != deployer`, so the pauser MUST be a pre-rotated operator key or multisig before deploy completes.

`owner()` is the TimelockController. Every post-deploy config change (unpause, setPauser rotation, impl upgrade) is 72h-delayed on mainnet.

**Implication:** you can pause fast. You cannot unpause fast. Plan accordingly — once paused, you commit to ≥72h of downtime unless the pauser role is also the one fixing it (and even then, the fix itself is timelock-gated).

### Current deployment state (Base Sepolia, 2026-04-18)

Verify before a real incident:

```bash
for c in $ESCROW $SIGNAL_COMMITMENT $AUDIT $OUTCOME_VOTING $ACCOUNT $COLLATERAL $CREDIT_LEDGER; do
  echo -n "$c pauser: "
  cast call $c "pauser()(address)" --rpc-url $BASE_RPC_URL
done
```

**Known gap (2026-04-18, tracked as P1-17 in MAINNET_BLOCKERS.md):** `Deploy.s.sol::_setupPauser` does NOT call `setPauser` on CreditLedger. CL is only pausable via the timelock owner (72h delay). If a credit-mint bug appears, 72h of bleed before pause. Fix before mainnet.

## Pause sequence

### Step 1. Confirm the incident is pause-worthy

Before touching contracts, answer in writing (at least in the ops Telegram):

1. **What is the incident?** One sentence.
2. **What is the user-funds risk?** (Lost? Stuck? Stealable?)
3. **Is pause cheaper than a hotfix?** Hotfix through timelock takes 72h; pause+unpause also takes 72h. If the bug is slow-bleed rather than acute, a pause just locks funds for 72h with no improvement. Pause is correct when the bleed-rate exceeds user tolerance for downtime.
4. **Who is incident commander?** One named human. They own comms.

### Step 2. Pause the affected contracts

For each affected contract, in this order (most user-facing first):

```bash
cast send <ContractAddress> "pause()" \
  --rpc-url $BASE_RPC_URL \
  --private-key $PAUSER_PK \
  --chain-id 8453  # mainnet; use 84532 for Base Sepolia
```

Order of operations for most incidents:

1. **Escrow** — prevents new deposits and new purchases.
2. **SignalCommitment** — prevents new signals.
3. **Audit** — prevents new audits from being initiated.
4. **OutcomeVoting** — (usually last) prevents validators from submitting new votes.

Account / Collateral / CreditLedger are state-tracking only and typically do NOT need pausing; they stop being useful when Escrow is paused. Pause them if the incident is in their own code path.

### Step 3. Verify the pause took

```bash
for contract in $ESCROW $SIGNAL_COMMITMENT $AUDIT $OUTCOME_VOTING; do
  echo -n "$contract paused: "
  cast call $contract "paused()(bool)" --rpc-url $BASE_RPC_URL
done
```

Every line should read `true`.

### Step 4. Degrade the frontend gracefully

The web client reads `paused()` on each contract via the network status endpoints. When any critical contract is paused, the site should display a maintenance banner. Verify within 2 minutes:

1. Load `https://djinn.gg` in an incognito tab.
2. Expect a visible red banner: "System paused for maintenance. No new deposits, purchases, or signals. Funds are safe."
3. Check `/docs/contracts` page shows paused state on each contract.

If the banner doesn't appear, cache may be stale — force-refresh `/api/network/status` by visiting it directly.

(Banner wiring is not yet shipped as of 2026-04-18 — tracked under P1-15 / this runbook's pre-mainnet prereqs.)

### Step 5. Inform users

- Telegram: post incident commander's 1-sentence summary in the user channel.
- Twitter: a single tweet from @djinn_gg.
- Status page (if P1-11 shipped): update.
- Tone: calm, direct, no minimization. Users panic faster when we sound evasive.

Template:

> We've paused Djinn Protocol contracts while we investigate [1-sentence issue]. **Funds are safe and remain recoverable.** Unpause requires a 72h timelock so service will resume no sooner than [DATE]. No action needed from you.

### Step 6. Diagnose and patch

- Reproduce locally (fork mainnet with `anvil --fork-url`).
- Write a test that demonstrates the bug.
- Patch + new impl.
- Schedule impl upgrade via timelock (72h on mainnet).
- Schedule unpause via timelock in the same batch or immediately after.

### Step 7. Test the fix on a fork

Before the unpause fires:

1. Fork mainnet to anvil at the paused block.
2. Apply the impl upgrade as the timelock.
3. Unpause on the fork.
4. Run a sanity-check purchase + settlement.
5. Only proceed to Step 8 if the fork replays cleanly.

### Step 8. Execute the upgrade + unpause

After the 72h timelock delay has expired:

```bash
# Execute the upgrade (anyone can execute once the delay has passed)
cast send $TIMELOCK "execute(address,uint256,bytes,bytes32,bytes32)" \
  $TARGET 0 $DATA $PREDECESSOR $SALT \
  --private-key $EXECUTOR_PK --rpc-url $BASE_RPC_URL

# Verify impl changed (ERC-1967 impl slot = keccak256("eip1967.proxy.implementation") - 1)
IMPL_SLOT=$(cast keccak "eip1967.proxy.implementation" | xargs -I{} python3 -c "print(hex(int('{}', 16) - 1))")
cast storage <ContractAddress> "$IMPL_SLOT" --rpc-url $BASE_RPC_URL

# Unpause (this is a SEPARATE timelock operation; schedule in parallel with the upgrade)
cast send $TIMELOCK "execute(...)" --private-key $EXECUTOR_PK --rpc-url $BASE_RPC_URL
```

Verify via Step 3 that each contract now reports `paused() == false`.

### Step 9. Postmortem

Within 72 hours of resume:

- Root-cause write-up in `docs/postmortems/YYYY-MM-DD-short-name.md`.
- What was the bug? How did it get past reviews / tests? What test would have caught it?
- User communication: a follow-up post explaining what happened and what's now different.
- Process delta: what about our workflow allowed this? (often: "we didn't have a test for this; we added one and gate future deploys on it.")

## Drill schedule

**Before mainnet (P0-04):** a full pause+unpause drill must be completed on Base Sepolia. Include:

1. Pause Escrow mid-purchase (stress test needs a concurrent transaction).
2. Confirm frontend banner appears within 2 min.
3. Confirm validator stops accepting commits.
4. Schedule unpause via timelock; wait the 72s testnet delay.
5. Execute unpause.
6. Confirm happy-path purchase works.
7. Save logs + screenshots to `docs/drills/YYYY-MM-DD-pause-drill.md`.

**After mainnet:** quarterly drills on a staging fork.

## Known gotchas

- **Unpause is 72h on mainnet.** There is no pauser-role equivalent for unpause. Once paused, the minimum outage is 72h. Factor this into the pause-or-hotfix decision.
- **Pausable is not composable with upgradability.** An impl upgrade via timelock can introduce bugs where a pause doesn't stop the vulnerable function. Test the upgrade against the paused state before executing.
- **Unpausing on a clean fix does not rewind history.** If the bug caused losses, those losses persist. Consider a separate refund distribution via a recovery impl.
- **The pauser key is a high-value target.** Rotate it after any incident (even if the key wasn't the vulnerability). Rotation itself is timelock-gated (`setPauser(newPauser)` via `owner()`), so budget 72h.
- **CreditLedger does not have a pauser set in `Deploy.s.sol`.** Until P1-17 is fixed, CL can only be paused by the timelock owner — 72h delay. If a credit-mint bug is the incident, you cannot stop the bleed in under 72h.
