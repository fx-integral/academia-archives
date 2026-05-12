# Suspicious Withdrawal Runbook

Handles: an anomalous on-chain movement out of Escrow, Account, or CreditLedger
that is not the expected outcome of a settled audit. This is the highest-stakes
runbook in the set — by the time you're reading it, user funds may already be
leaving.

Two possible causes:

1. **Exploit.** Someone found a contract bug and is draining. Act within minutes.
2. **Operator error.** A script was run with the wrong arguments, or a legit
   withdrawal looks suspicious because monitoring was noisy. Confirm before
   pausing — a false pause is expensive.

## Decision tree (first 5 minutes)

The alert surface:

- Subgraph: `Escrow.Withdrawal`, `Escrow.Transfer`, `Account.Debit` events above
  a notional threshold.
- On-chain: Basescan "Large Transactions" view for each proxy.
- Off-chain: Telegram user channel — users tend to notice before we do.

### Confirm it's real

```bash
# Get the exact tx
cast tx <TX_HASH> --rpc-url $BASE_RPC_URL
cast receipt <TX_HASH> --rpc-url $BASE_RPC_URL
# Decode the calldata
cast 4byte-decode <CALLDATA>
```

Branch:

| Evidence | Interpretation |
|---|---|
| Function is `settleAudit(...)` or `forceSettle(...)` and from a known validator operator | Legitimate audit settlement. Not an incident. |
| Function is `transferFrom(...)` from Escrow with no corresponding audit | Possible exploit. Escalate. |
| Function is unknown to the ABI | Proxy called the wrong impl — implies upgrade went wrong. Check ERC-1967 impl slot. |
| Sender is our operator EOA (deployer, pauser, timelock) | Operator action. Ask the operator directly before pausing. |

## Exploit confirmed

**Minutes matter.** Skip the perfect diagnosis; pause and then investigate.

### Step 1. Pause everything affected

Start with Escrow — it's the fund-custodial contract. See
`runbook-emergency-pause.md` Step 2.

```bash
cast send $ESCROW "pause()" \
  --rpc-url $BASE_RPC_URL \
  --private-key $PAUSER_PK
```

Then SignalCommitment, Audit, OutcomeVoting in that order.

### Step 2. Assess the bleed

```bash
# Current Escrow USDC balance
cast call $USDC "balanceOf(address)(uint256)" $ESCROW --rpc-url $BASE_RPC_URL

# Compare to pre-incident snapshot
# (The subgraph or a recent backup of the /api/network/status
#  endpoint will have the last known-good number.)
```

Record:
- Starting Escrow balance (last known good).
- Current balance.
- Delta = amount taken.
- Recipients (one address or many? look up in Basescan).

### Step 3. Inform

Per `runbook-emergency-pause.md` Step 5:

- Telegram user channel: neutral, factual.
- Twitter from @djinn_gg: one post. Do NOT speculate on the bug publicly —
  attackers read Twitter too.

**Template:**

> We've paused Djinn Protocol contracts due to an irregular withdrawal from
> Escrow. Investigation is live. **No user action is required.** Further
> updates in this channel as we learn more.

### Step 4. Trace the attacker

```bash
# Every event the attacker triggered
cast logs --from-block <BLOCK-10> --to-block latest \
  --address $ESCROW \
  --rpc-url $BASE_RPC_URL | jq

# Follow the money
# Use Basescan's "Token Transfers" view on the recipient address to see
# where the funds went next.
```

Common attacker patterns:

- Centralized-exchange deposit address: report to the CEX's abuse contact
  (Coinbase, Binance, etc.). Some CEXs will freeze incoming funds if reported
  within hours.
- Tornado Cash or similar mixer: funds likely gone.
- New EOA with zero history: attacker is naive. Basescan's tagging + exchange
  monitors may catch them later.

### Step 5. Reproduce the bug

On a local anvil fork:

```bash
anvil --fork-url $BASE_RPC_URL --fork-block-number <BLOCK_BEFORE_ATTACK>
# Replay the attacker's exact tx. Confirm it succeeds on the fork.
# Then write a unit test that exhibits the same vulnerability.
```

The test becomes the regression case; the fix is whatever patches the
contract.

### Step 6. Patch + refund plan

The patch is a new impl scheduled via timelock (72 h on mainnet). In the
same batch, schedule:

- The impl upgrade.
- Unpause of each paused contract.
- Optionally, a "refund" impl method that rebalances losses from reserves
  (if reserves exist — confirm with operator before announcing).

### Step 7. Execute after timelock

See `runbook-emergency-pause.md` Step 8.

### Step 8. Postmortem

`docs/postmortems/YYYY-MM-DD-suspicious-withdrawal.md`:

- The bug, in prose a user can understand.
- How it got past audits (external + our test suite + fresh-eyes).
- The regression test that now guards against it.
- Delta to losses refunded vs. lost forever.
- Process change to prevent the class of issue.

## Operator error (not an exploit)

If the tx was signed by our EOA / pauser / timelock-executor:

- Don't pause contracts unilaterally. Ask the operator who signed it what
  they intended. Incidents caused by operator confusion don't need contract
  pauses to resolve.
- If the operator confirms it was a mistake (wrong argument, fat-finger), the
  recovery path is through a second tx (refund, re-call with correct args),
  not a pause.
- If you cannot reach the operator within 15 min AND the tx keeps signing
  more outgoing movements, pause and wake them up via whatever side channel
  works. Pause is reversible; leaked funds are not.

## Known gotchas

- **The `Paused` gate does NOT cover every function.** Verify what functions
  have `whenNotPaused`. A pause halts deposits/withdrawals but may not stop
  `claimFees()` or other fee accounting.
- **A pause does NOT rewind state.** If tokens already left Escrow, they're
  gone from Escrow; pause only prevents further losses.
- **If the exploit touched the upgradable impl slot**, a pause is insufficient —
  the impl needs to be replaced. This is the only scenario where you pause
  AND simultaneously schedule a non-72h recovery (using OpenZeppelin's
  emergency-upgrade-without-timelock pattern, if deployed). Confirm the
  TimelockController `execute` constraints before assuming this path.
