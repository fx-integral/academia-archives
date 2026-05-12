# Runbooks

Operational playbooks for running and responding to incidents on the Djinn
Protocol. Each runbook stands alone — skip the index and go directly to the
scenario that matches your alert.

Severity tiers and response SLAs live in `docs/operations-sla.md`. This doc
answers *how*; the SLA answers *when*.

## Incident response

Use when an alert has fired and you have minutes, not hours, to act.

| Runbook | Triggering alert | Severity |
|---|---|---|
| [runbook-validator-down.md](runbook-validator-down.md) | `health-check.sh` fails ≥ 2 consecutive runs on a validator | SEV-1 |
| [runbook-stuck-audit.md](runbook-stuck-audit.md) | `audit-queue-watchdog.sh` detects queue growing + settled flat ≥ 2 h | SEV-1 |
| [runbook-miner-offline.md](runbook-miner-offline.md) | `miner-watchdog.sh` fails pm2 + port probe | SEV-2 (SEV-1 if systemic) |
| [runbook-suspicious-withdrawal.md](runbook-suspicious-withdrawal.md) | Anomalous on-chain movement out of Escrow / Account / CreditLedger | SEV-1 |
| [runbook-emergency-pause.md](runbook-emergency-pause.md) | Confirmed exploit or systemic failure warranting contract pause | SEV-1 |
| [runbook-emergency-recovery.md](runbook-emergency-recovery.md) | Paused state is the problem (funds locked, settlement unable to finalize) | SEV-1 |
| [runbooks/vercel-break-glass.md](runbooks/vercel-break-glass.md) | Vercel suspended/terminated djinn.gg; cut apex DNS to IPFS gateway | SEV-1 |

## Operations

Use during planned changes, setup, or post-incident recovery. No urgency by
default.

| Runbook | When to use |
|---|---|
| [runbook-watchtower-mirror.md](runbook-watchtower-mirror.md) | Standing up a second git remote for the validator watchtower |
| [runbook-validator-https.md](runbook-validator-https.md) | Provisioning HTTPS on a validator axon (nginx + Let's Encrypt) |
| [runbook-wildcard-router.md](runbook-wildcard-router.md) | Wildcard `*.djinn.gg` HTTPS router that fronts validators |
| [runbook-validator-backup.md](runbook-validator-backup.md) | Scheduled DB snapshots + restore procedure |
| [runbook-ipfs-deploy.md](runbook-ipfs-deploy.md) | Publishing the frontend to IPFS as a censorship-resistant mirror |

## Response flow

A SEV-1 usually flows:

```
alert → confirm (< 5 min) → mitigate (< 15 min) → diagnose (< 45 min) → patch (< 2 h)
```

The runbook covers *confirm* and *mitigate*. *Diagnose* and *patch* often spill
into hours or days; those live in the postmortem (`docs/postmortems/`).

## Postmortem template

Every SEV-1, and any SEV-2 that took > 4 h to recover, gets a postmortem:

```markdown
# YYYY-MM-DD — <short-name>

**Severity:** SEV-N
**Impact:** <e.g., 45 min outage of /network; no user funds affected>
**Detected by:** <watchdog / user report / operator>

## Timeline
- HH:MM UTC — alert fires
- HH:MM UTC — on-call acknowledges
- HH:MM UTC — mitigation applied
- HH:MM UTC — resolved

## Root cause
<what broke, and why>

## What didn't work
<false leads; useful for the next person>

## Fix
<link to commit / PR>

## Prevention
<specific test, monitor, or process change — each becomes a tracked task>
```

Drop in `docs/postmortems/YYYY-MM-DD-<short-name>.md`. Reference from the
runbook that was triggered if the postmortem teaches a lesson worth
codifying.
