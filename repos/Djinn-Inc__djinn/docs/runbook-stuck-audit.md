# Stuck Audit Runbook

Handles: audit settlement pipeline not finalizing. SEV-1 from
`/opt/monitoring/audit-queue-watchdog.sh` when queue depth is non-decreasing and
`settled` counter is flat across 8 consecutive samples (~2 h).

This is a funds-stuck, not a funds-at-risk, condition. Escrow holds user money
until the audit settles. Every hour of stall increases user frustration but
the money remains recoverable.

## Decision tree (first 15 minutes)

```bash
# 1. Snapshot the queue state
curl -sS http://161.97.138.250:8421/v1/audit/summary | jq
```

```
{
  "waiting_for_outcomes": N1,
  "ready_for_settlement": N2,
  "settled": S,
  "oldest_pending_age_seconds": X
}
```

Branch on what's growing:

| `waiting_for_outcomes` ↑ but `ready_for_settlement` flat | Outcomes missing — see **Outcome data gap** |
| `ready_for_settlement` ↑ but `settled` flat | OV quorum or tx lifecycle problem — see **Settlement failure** |
| Both flat but alert fires anyway | False alarm; queue was non-decreasing but low-volume. Ack + investigate later. |

## Outcome data gap

Outcomes come from the Odds API (`web/lib/odds.ts`) and are pushed by the
scheduler in `validator/queue.py`.

```bash
# On UID 0
pm2 logs djinn-validator --lines 200 | grep -iE "outcome|odds|schedule"
```

Common causes:

- **Odds API quota exhausted.** `429` or `403` in the log. Key rotation via
  `reference_odds_api_key` memory; update `ODDS_API_KEY` in `/root/djinn/.env`
  and `pm2 restart djinn-validator --update-env`.
- **Game not yet played.** `oldest_pending_age_seconds` compared to event
  start — if the event hasn't kicked off, waiting is correct. Not an
  incident.
- **Scheduler paused.** `djinn_audit_scheduler_runs_total` in Prometheus
  stopped incrementing. Restart the validator; the scheduler is process-local.

## Settlement failure (the common SEV-1 case)

The audit made it to `ready_for_settlement` but `forceSettle` never confirms.

### Step 1. Is the OV quorum set?

```bash
cast call $OUTCOME_VOTING "signerCount()(uint256)" --rpc-url $BASE_RPC_URL
```

Must be ≥ quorum threshold (`3` on testnet as of 2026-04-18). If `0`, OV was
never bootstrapped — see `project_outcomevoting_validator_set_empty` in memory
and schedule `addSigner` via timelock.

### Step 2. Are validators actually voting?

Each validator must have `settlement_registered=True` at `/health`.

```bash
for uid in 0 1 2 86 189 213; do
  port=8421
  echo -n "UID $uid: "
  curl -sS --max-time 5 http://<IP>:$port/health | jq -r '.settlement_registered'
done
```

If any are `False`, the validator's env has a stale `OUTCOME_VOTING_ADDRESS`
or is missing the operator-signer private key. Check `settlement_diagnosis`
on the same `/health`; it names the specific env variable.

### Step 3. Is `forceSettle` failing on-chain?

```bash
pm2 logs djinn-validator --lines 400 | grep -iE "forceSettle|settle.*fail|settlement.*error"
```

Typical failures + fixes:

| Error | Meaning | Fix |
|---|---|---|
| `AccessControl: ... missing role SIGNER_ROLE` | Signer not registered on OV | `addSigner` via timelock |
| `Audit: already settled` | Idempotency; look for duplicate scheduling | Benign; settled counter should reflect |
| `execution reverted: StalePrice` | Odds oracle stale | Refresh odds, retry |
| Tx sent but never confirms | Low gas or RPC provider dropping | Re-nonce and resend from `scripts/settle_retry.py` |

### Step 4. Manual forceSettle (break-glass)

If the automated settle is broken and users are bleeding trust:

```bash
cd /root/djinn
uv run python scripts/settle_retry.py --audit-id <ID> --dry-run
# Review the output, then:
uv run python scripts/settle_retry.py --audit-id <ID> --execute
```

This runs against UID 0's private key; by construction it requires OV quorum
so it doesn't bypass governance.

## Postmortem

Always run, even on a soft recovery:

- Record in `docs/postmortems/YYYY-MM-DD-stuck-audit-<cause>.md`:
  - How many audits were stuck, for how long, carrying what notional.
  - Which of the 4 branches above (Outcome gap / Quorum / Voting / Tx lifecycle) was the real cause.
  - What monitoring caught it vs. what should have caught it sooner.
- If the cause was Odds-API related, file a P1 for oracle redundancy
  (beyond the single key tracked as P1-03).
- If the cause was tx lifecycle, confirm P0-09 (fire-and-forget) actually
  closed and didn't regress.
