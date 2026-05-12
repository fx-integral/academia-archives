# Emergency Recovery Runbook

Worst-case recovery procedures per contract — what to do when `pause()` alone
isn't enough and user funds are locked in a state the shipped code cannot exit.

**Audience:** incident commander during a SEV-1 where the pause is in place and
`runbook-emergency-pause.md` has been followed, but the paused state itself is
the problem (funds can't be withdrawn, settlement can't finalize, an impl bug
locked something).

**Rule of thumb:** this runbook is *procedural*, not mechanical. Every path
described below requires writing new impl code, scheduling it via timelock, and
waiting 72h on mainnet. The value of documenting it in advance is that the
72-hour window is *reserved for code review + communication*, not for figuring
out what to do.

## Governance sequencing (the 72h constraint)

Every recovery path below composes these primitives:

1. **Pause (instant, via `pauser` EOA)** — stops further bleed. Already done if
   you're reading this; if not, see `runbook-emergency-pause.md` first.
2. **Deploy a new recovery impl (off-chain, minutes)** — new Solidity file,
   `forge build`, `forge test`, `forge create`.
3. **Schedule `upgradeToAndCall` via `TimelockController` (72h)** — on mainnet,
   `minDelay = 72h` (`Deploy.s.sol:210`). Testnet is 72s.
4. **Execute after the delay (instant, anyone can call `execute()`)**.
5. **Schedule `unpause()` via timelock (72h)** — a **separate** timelock
   operation; **schedule this in parallel with the upgrade in step 3** so both
   mature at the same time. Forgetting this turns recovery into a 144h outage.

Because step 3 requires `whenPaused` for Escrow's `_authorizeUpgrade`
(`Escrow.sol:571`), you MUST pause before scheduling. On contracts without that
constraint (Audit, OutcomeVoting, etc.), pause is still usually correct — it
prevents further user actions from mutating state while the fix is in flight.

**During the 72h window:** communicate daily on Telegram + Twitter. Silence
during a 3-day pause produces the kind of runs that kill trust permanently. A
template lives at the bottom of `runbook-emergency-pause.md`.

## Native recovery surfaces (no new impl needed)

Before drafting a recovery impl, check whether the stuck state can be resolved
via code that already exists:

| Contract | Native recovery | Governance | When to use |
|---|---|---|---|
| Audit | `forceSettle(genius, idiot, purchaseIds, qualityScore)` (`Audit.sol:276`, `onlyOwner`) | 72h timelock | Settlement stalled because quorum failed or OV is misconfigured, but the batch is deterministic given the qualityScore operator picks. |
| Escrow | `rescueToken(address token, uint256 amount)` (`Escrow.sol:543`, `onlyOwner`, **cannot rescue USDC**) | 72h timelock | Wrong-token deposits only. Does NOT help with stuck USDC. |
| Collateral | `rescueToken(...)` (`Collateral.sol:244`, same semantics) | 72h timelock | Same as Escrow rescueToken. |
| Any Pausable | `_authorizeUpgrade` (UUPS) to a new impl with a recovery function | 72h timelock | Anything not covered by native recovery. |

`forceSettle` is the main pre-built recovery path. Its existence means Audit
stuck-state is a *procedural* incident (incident commander picks qualityScore,
schedules via timelock) rather than a code incident. The flow:

```bash
# 1. Pause (if not already)
cast send $AUDIT "pause()" --private-key $PAUSER_PK --rpc-url $BASE_RPC_URL

# 2. Build the forceSettle calldata for the stuck batch
DATA=$(cast calldata \
  "forceSettle(address,address,uint256[],int256)" \
  $GENIUS $IDIOT '[42,43,44]' $QUALITY_SCORE)

# 3. Schedule via timelock
cast send $TIMELOCK \
  "schedule(address,uint256,bytes,bytes32,bytes32,uint256)" \
  $AUDIT 0 $DATA 0x0 $SALT 259200 \
  --private-key $PROPOSER_PK --rpc-url $BASE_RPC_URL

# 4. Wait 72h. Execute.
cast send $TIMELOCK \
  "execute(address,uint256,bytes,bytes32,bytes32)" \
  $AUDIT 0 $DATA 0x0 $SALT \
  --private-key $EXECUTOR_PK --rpc-url $BASE_RPC_URL

# 5. Unpause (separately scheduled in parallel)
```

If `forceSettle` itself is broken (buggy math, reverts on this specific batch),
you fall through to the Audit-stuck impl-upgrade path below.

## Per-contract recovery patterns

### Escrow stuck — user balances locked

**Symptom:** USDC sits in `Escrow.balances[user]` but `withdraw()` reverts or
mis-accounts. Purchase flows reverted mid-transaction and left state
inconsistent.

**Why pause-alone doesn't help:** pausing freezes the bad state; it doesn't let
users retrieve their deposits. `rescueToken` explicitly cannot rescue USDC
(`Escrow.sol:544`).

**Recovery impl pattern — `EscrowRecovery.sol`:**

```solidity
// Extends EscrowV6 storage layout; adds emergency withdraw.
contract EscrowRecovery is Escrow {
    event EmergencyWithdrawn(address indexed user, uint256 amount);

    /// @notice One-shot emergency refund path. Owner-only, whenPaused only,
    /// respects the stored balance mapping, emits a clear event for off-chain
    /// reconciliation. Deliberately does NOT touch purchase/audit state —
    /// those paths use their own recovery impls.
    function emergencyWithdraw(address user) external onlyOwner whenPaused {
        uint256 bal = balances[user];
        if (bal == 0) revert ZeroAmount();
        balances[user] = 0;
        usdc.safeTransfer(user, bal);
        emit EmergencyWithdrawn(user, bal);
    }

    /// @notice Batched variant for mass-refund after an exploit.
    function emergencyWithdrawBatch(address[] calldata users)
        external onlyOwner whenPaused
    {
        for (uint256 i; i < users.length; ++i) {
            uint256 bal = balances[users[i]];
            if (bal == 0) continue;
            balances[users[i]] = 0;
            usdc.safeTransfer(users[i], bal);
            emit EmergencyWithdrawn(users[i], bal);
        }
    }
}
```

**Sequencing:**

1. Pause Escrow (instant).
2. Deploy `EscrowRecovery` impl. Verify storage layout on Base Sepolia fork
   before scheduling on mainnet (`forge inspect Escrow storage` vs
   `forge inspect EscrowRecovery storage` — must be a clean superset).
3. Schedule `upgradeToAndCall(newImpl, "")` via timelock.
4. 72h wait. Daily comms.
5. Execute upgrade. **Escrow stays paused.** Call `emergencyWithdrawBatch` for
   affected users.
6. Schedule a second upgrade back to a clean impl without the recovery
   function, or leave the recovery function in place guarded by
   `whenPaused + onlyOwner` for future use. (Recommendation: leave it.
   Dead-code cost is zero; next-incident value is large.)
7. Schedule unpause if normal operations should resume.

**Replay protection:** `balances[users[i]] = 0` before transfer ensures each
user can be refunded exactly once per `emergencyWithdraw` call.

### Audit stuck — settlement won't finalize

**Symptom (first):** queue grows, `settled` counter flat for >2 h. See
`runbook-stuck-audit.md`. Most of the time the fix there is operational
(start the scheduler, unblock Odds API), not contract-level.

**Symptom (this runbook):** operational fixes fail; the stall is the contract
itself. Example: OV quorum can't be reached due to dereg'd signers, or a bug in
`_settleCommon` reverts on specific batch shapes.

**First try: `forceSettle` (see above).** It's owner-only + timelock, but it
exists and has been tested. Ship the schedule immediately; you can cancel it
within 72h if operational fixes land first.

**If `forceSettle` itself reverts (bug in the common path):** recovery impl
pattern — `AuditRecovery.sol`:

```solidity
contract AuditRecovery is Audit {
    event ManualSettled(uint256 indexed batchId, int256 qualityScore);

    /// @notice Bypasses _settleCommon; writes settlement state directly.
    /// Use only when the normal settlement path reverts on a stuck batch.
    /// Operator MUST reconcile off-chain and verify the values by hand.
    function manualSettle(
        address genius,
        address idiot,
        uint256[] calldata purchaseIds,
        int256 qualityScore,
        uint256 onChainNotional,
        uint256 usdcFeesPaid
    ) external onlyOwner whenPaused {
        uint256 batchId = account.markBatchAudited(genius, idiot, purchaseIds);
        // Direct state write — skip the common path that's buggy.
        _writeSettlementState(batchId, qualityScore, onChainNotional, usdcFeesPaid);
        emit ManualSettled(batchId, qualityScore);
    }
}
```

**Sequencing:** same 1–7 as Escrow. Critical difference: `whenPaused` on
Audit does not prevent Escrow reads, so Escrow should also be paused while
`manualSettle` runs to prevent concurrent purchases from racing with manual
settlement.

### OutcomeVoting stuck — votes won't land

**Symptom:** validators submit, tx reverts (storage slot mismatch, signer-set
corruption). See also `project_outcomevoting_validator_set_empty.md` memory.

**Recovery:** usually not an impl upgrade. The fix is registering the correct
signer set via the existing `addSigner/removeSigner` path (timelock-gated).
Only upgrade the impl if the problem is in the vote-counting logic itself.

If an impl upgrade is needed, pattern matches the Escrow one: subclass
`OutcomeVoting`, add a `manualRecordOutcome(signalId, outcome)` function, pause
OV during the recovery, execute, unpause.

### KeyRecovery stuck — blobs unretrievable

**Symptom:** user's recovery blob is on-chain but `getBlob(user)` returns empty
or wrong data, so the user cannot recover their client-side master seed.

**Recovery:** P1-18 closed 2026-04-18 when KeyRecovery became a UUPS proxy.
That means the recovery path exists: deploy `KeyRecoveryRecovery` with a
one-shot `forceSetBlob(user, blob)` or `rebuildIndex()` function, upgrade via
timelock.

**Data-loss case:** if the blob data is genuinely gone (storage was never
written correctly), the recovery blob is lost. Users must re-register their
master seed. There is no on-chain recovery. Communicate clearly: "users whose
blobs were stored between blocks X and Y must re-register; older and newer
blobs are intact."

### CreditLedger stuck — credit accounting corrupted

**Symptom:** `creditOf(user)` disagrees with expected balances; credits mint in
wrong amounts; spend path reverts.

**Recovery:** P1-17 closed the fast-pause gap on 2026-04-18. Pause via
`pauser`, deploy `CreditLedgerRecovery` with `forceSetCredit(user, amount)` and
`forceMint(user, amount) onlyOwner whenPaused`, upgrade via timelock, execute
the corrections from an off-chain reconciliation spreadsheet, unpause.

**Reconciliation source:** subgraph `CreditMinted` / `CreditSpent` events from
before the bug was introduced. Off-chain script computes the correct
`creditOf(user)` for each affected user; the recovery impl writes those values
in a batch.

### SignalCommitment stuck — signals uncommittable

**Symptom:** `commit()` reverts for all callers (or a subset); signal metadata
storage corrupted.

**Recovery:** pause SignalCommitment. Because SC is commit-time only (not
custodial), user funds are not at risk; the incident is UX-severity, not
economic. Recovery impl adds a `forceCommit(genius, commitmentHash, metadata)
onlyOwner whenPaused` bypass for already-paid-collateral signals that got
stuck. Same sequencing as others.

### Account / Collateral stuck

Account is derivable state (batches, relationships). Collateral custodial but
simple.

- Account: impl-upgrade with `forceMarkBatchAudited`, `forceClearRelationship`.
- Collateral: same pattern as Escrow (`emergencyWithdraw(genius)` against
  the collateral mapping), respecting locked-vs-free accounting.

## Drill requirements

Before mainnet (P1-15 verification):

1. Fresh Base Sepolia deploy.
2. Write `EscrowRecovery.sol` + `AuditRecovery.sol` in `contracts/test/` as
   test fixtures, not shipped code.
3. Foundry integration test per contract:
   - pause → simulate stuck state → deploy recovery impl →
     `forge script` via the testnet TimelockController (72s delay) →
     execute upgrade → call recovery function → assert state → unpause.
4. Save the recovery-impl Solidity file + the forge script to
   `docs/drills/YYYY-MM-DD-emergency-recovery.md` with the trace output.
5. Cross-reference from this runbook.

Drill cadence: quarterly on a staging fork once mainnet is live.

## Comms during the 72h window

The operator-facing content is in `runbook-emergency-pause.md` Step 5. For a
*recovery* (not just a pause), the user-facing message must add:

- What was broken (one sentence, plain English — no jargon).
- What we're doing (upgrading via timelock; funds are safe).
- When we expect service to resume (ISO date).
- What users should do in the meantime (usually: nothing).

Post every 24h during the window, even if the post is "no change from
yesterday." Silence is the enemy.

## Known gotchas

- **`Escrow._authorizeUpgrade` requires `whenPaused`.** You cannot upgrade
  Escrow without first pausing it. Planned by design to prevent upgrades
  while balances are being mutated.
- **Storage layout is load-bearing.** Every recovery impl must be a clean
  superset of the shipped impl's storage. Run `forge inspect Escrow storage`
  before and after and diff. A misaligned slot corrupts every user's balance.
- **UUPS `_authorizeUpgrade` cannot be skipped.** Even in an emergency, you
  cannot bypass the timelock on an upgrade. Plan for the 72h.
- **`rescueToken` cannot rescue USDC.** Escrow's rescue path (`Escrow.sol:544`)
  explicitly excludes USDC. This is correct — USDC belongs to users, not
  operators. Do not propose a "fix" that lets operators transfer USDC at will.
- **Recovery impls are high-value targets.** Anything with `onlyOwner` +
  `whenPaused` that transfers USDC is a blast-radius-unlimited function. Keep
  these impls short, audited, and ship them only when needed (or ship them
  with a one-shot `_disableEmergency()` flag that burns the privilege after
  first use, to be decided per incident).
- **Never emergency-refund a user the protocol owes money TO.** Use case: user
  is mid-purchase, Escrow paused, user's balance appears stuck. If the
  purchase settled successfully on-chain but the UI shows it as stuck, an
  emergency withdraw double-pays the user. Reconcile every single address
  against subgraph events before running any batch.
