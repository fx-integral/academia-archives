# Validator Down Runbook

Handles: a single validator's `/health` endpoint returning non-200 for ≥ 2 consecutive
`health-check.sh` runs (≥ 10 min of user-visible outage). SEV-1 per `docs/operations-sla.md`.

## Decision tree (first 5 minutes)

1. **Which UID is down?** The Telegram alert names the URL. Map URL → UID from the
   network inventory in `MEMORY.md` or `https://djinn.gg/network`.
2. **Is it ours, or a third party?** Ours (UID 0 on the production VPS) you fix directly. A
   third-party validator (UIDs 1, 2, 86, 189, 213, 201, …) you cannot restart — the
   best you can do is confirm quorum still holds and message the operator.
3. **Does the subnet still have quorum?** Run
   `curl -s https://v0.djinn.gg/v1/audit/summary` and verify `settled` is
   incrementing over a 15-min window. If it is, the subnet is healthy despite the
   missing UID; this becomes a SEV-2 "miner capacity" concern, not a SEV-1 outage.

## Our validator (UID 0 on 161.97.138.250)

### Diagnose

```bash
ssh root@161.97.138.250
pm2 list | grep djinn-validator      # online? unstable_restarts?
pm2 logs djinn-validator --lines 80  # last words
curl -sS http://127.0.0.1:8421/health  # bypasses nginx/router
```

Typical patterns:

| Symptom | Root cause | Mitigation |
|---|---|---|
| `pm2 list` shows validator missing or `errored` | Process crashed and didn't respawn | `pm2 restart djinn-validator` |
| `unstable_restarts > 0` climbing | Crash loop (likely bad commit from watchtower) | See "Bad commit" below |
| `/health` returns 502 via `https://v0.djinn.gg/health` but 200 on localhost | nginx / wildcard router issue | `systemctl reload nginx` then `/opt/monitoring/health-check.sh` |
| `/health` 200 but `pending_outcomes` monotonically growing | Settlement stall; switch to `runbook-stuck-audit.md` | |
| `/health` 200 but `settlement_registered=False` | Stale OV address in `.env` | See `project_outcomevoting_stale_address_2026_04_17` in memory |

### Bad commit from watchtower

If `/var/log/djinn-watchtower.log` shows a rapid restart loop after a recent `git pull`:

```bash
cd /root/djinn
git log --oneline -5              # which commit landed last
git reset --hard HEAD~1           # back to the previous version
pm2 restart djinn-validator --update-env
pm2 logs djinn-validator --lines 40
```

**Then:** add the bad commit to `scripts/watchtower.sh`'s skip-list AND push a
fix to `main`. Don't pin forever — other validators are running the same
watchtower script and will fetch whatever is on `main`.

### Full restart (last resort)

```bash
pm2 delete djinn-validator
cd /root/djinn && git pull --rebase origin main
pm2 start scripts/run-validator.sh --name djinn-validator --update-env
pm2 save
```

Wait 30 s, curl `/health`, confirm `shares_held` is populated (non-zero
means the cached Shamir shares are loaded and the node is live for
attestation requests).

## Third-party validator down

### Your actions

1. Open their `/network` row and confirm `status=offline`, `last_seen` > 10 min.
2. Check `https://djinn.gg/network` publicly — if it's also showing them offline,
   the problem is real, not a local probe issue.
3. Confirm quorum. As of 2026-04-18 the subnet has 7 validators with axons
   published; quorum threshold is 4. Losing one drops you to 6 — still healthy.
   Losing 4 drops you to 3 — below threshold; this escalates to a SEV-1
   `runbook-stuck-audit.md`.
4. Message the operator. Known contacts in `MEMORY.md`. Use Telegram, not Twitter.

### Do NOT

- Attempt to SSH into a third-party box. You don't have keys and even asking
  implies trust-theatre.
- Re-weight the metagraph to "compensate" — that's governance, not incident response.
- Public-tweet their outage. It makes them defensive and us petty.

## Escalation to SEV-1 outage

If three or more validators are down simultaneously, or if quorum goes below 4:

1. Pause acceptance of new signals (UI-only, via feature flag if available).
2. Telegram the user channel: "service degraded, investigating".
3. Read `runbook-emergency-pause.md`. Most multi-validator outages do NOT need
   contract pause — paused contracts amplify the outage. Only pause if there's
   evidence of an active exploit, not just unavailability.

## Postmortem

If the outage exceeded 15 min (SEV-1 ack window):

- Root-cause write-up in `docs/postmortems/YYYY-MM-DD-validator-down-<uid>.md`.
- If the cause was a bad commit: add a regression test that would have caught it.
- If the cause was infrastructure: update `MEMORY.md` with the operator's
  contact + their preferred comm channel + how long they took to respond.
