# Operations SLA

This is the contract between operators and the production network: what we
monitor, when something fires, and how fast a human must respond.

Scope covers mainnet-readiness for the 2026-06-11 World Cup launch. Before that
date the "on-call" is the user, full stop. Post-launch, an explicit rotation
goes here.

## 1. Monitored signals

All production monitoring runs on production VPS (161.97.138.250) under `/opt/monitoring/`
or `/root/djinn/scripts/`. Every script logs to a rotating file; every alert
path is Telegram (chat `${TELEGRAM_CHAT_ID}`).

| Signal | Source | Cadence | Log |
|---|---|---|---|
| Public endpoint uptime (debust, firmrecord, proveaudit, djinn.gg home + odds) | `health-check.sh` | 5 min | `health.log` |
| End-to-end capture flow (debust + firmrecord hourly; proveaudit daily 06:00 UTC) | `synthetic-test.sh` | hourly | `synthetic.log` |
| Network attestation stats (sessions started/finished, avg bytes) | `attestation-stats.sh` | 5 min | `cron-stats.log` |
| Audit scheduler probe (queue depths, oldest waiting age) | `audit-probe.sh` | hourly (:15) | `audit-probe.log` |
| Miner process watchdog (miner1/miner2 pm2 state + port reachability) | `miner-watchdog.sh` | 5 min | `/var/log/miner-watchdog.log` |
| Validator watchtower (remote git pull + restart when behind) | `watchtower.sh` | 30 min | `/var/log/djinn-watchtower.log` |
| Validator-firmrecord discovery (metagraph snapshot → JSON) | `discover-validators.py` | 5 min | `logs/discover.log` (firmrecord) |
| DB snapshots (validator, debust, firmrecord SQLite) | `backup-dbs.sh` | daily 03:00 UTC | `backup.log` |
| Daily attestation graph (PNG) | `daily-attestation-graph.py` | daily 08:00 UTC | `graph.log` |

Validator-local signals (not yet aggregated; each validator exposes its own):

- `GET /health` — `version`, `shares_held`, `pending_outcomes`,
  `settlement_registered`, `validator_signer`, `settlement_contract`,
  `settlement_diagnosis`.
- `GET /metrics` — Prometheus endpoint. Key series:
  - `djinn_attestation_gated_total{reason=...}` — why a session was rejected.
  - `djinn_burn_gate_fail_open_total{reason=...}` — v1274+. Non-zero means
    the burn-gate IP allowlist degraded to legacy behavior.
  - `djinn_audit_settled_total`, `djinn_audit_settle_failed_total` — settlement
    outcome counters.
  - `djinn_proof_complexity_*` — per-session bytes/time; surfaces miner
    anomalies.

## 2. Alert thresholds

Every alert fires to the Telegram group. Not every alert is a page.
"Page" = user is expected to look inside 15 minutes. "Notice" = addressed in
the next working block. "Log-only" = no human action unless pattern emerges.

### Page (SEV-1): take action within 15 minutes

| Condition | Detector | Why it pages |
|---|---|---|
| Any public endpoint (debust / firmrecord / proveaudit / djinn.gg / odds) returns non-200 for **≥ 2 consecutive checks** (≥ 10 min) | `health-check.sh` | External users see the outage |
| Any contract `Paused()` event observed on-chain | subgraph + manual watch | Someone hit the emergency pause; incident by definition |
| Validator quorum `< threshold for settlement` observed for **> 2 hours** | derived from `/health.pending_outcomes` growth without `djinn_audit_settled_total` incrementing | Audits cannot finalize; funds stuck |
| `djinn_burn_gate_fail_open_total{reason=metagraph_read_error}` > 0 on any validator | Prometheus | Burn-gate degraded to legacy behavior; pre-mainnet this is a HIGH alarm |

### Notice (SEV-2): address in the next working block (< 4 h)

| Condition | Detector | Why it's a notice, not a page |
|---|---|---|
| Synthetic capture flow (debust/firmrecord) **fails ≥ 2 consecutive runs** on the same URL | `synthetic-test.sh` | Already gated to 2-run; single-URL failures usually surface TLSNotary compat issues, not site outages |
| Validator `version` drift > 3 tags behind `main` for > 6 h | manual / `/djinn-health` | Eventual consistency concern; watchtower should catch it |
| Validator `settlement_registered=False` on any node | `/health` | Indicates stale env var or missing OV signer registration |
| `djinn_attestation_gated_total{reason=low_honest_peers}` spiking on one UID | Prometheus | Miner-side sybil degradation; incentive mechanism issue not an outage |
| Watchtower restart-in-loop detected (> 3 restarts in 30 min) | `/var/log/djinn-watchtower.log` | Bad commit is landing repeatedly; needs manual revert |

### Log-only (SEV-3): no immediate action

- First-occurrence (n=1) health-check failure (baked into `health-check.sh`
  consecutive-failure gate).
- Odd Vercel 502 on `/api/network/status` (the wildcard-router change is the
  long-term fix; noted under P1-02).
- TLSNotary compat on specific upstream URLs (Cloudflare-proxied, bot-walled
  sites). If a URL persistently fails → remove from synthetic rotation
  rather than alert on it.
- Debust/firmrecord individual proof failures (provers retry; the reaper
  catches abandoned jobs at next server restart).

## 3. Response SLA matrix

|  | Discovery → first human ack | Ack → root-cause identified | RCA → mitigation live |
|---|---|---|---|
| SEV-1 | 15 min | 45 min | 2 h |
| SEV-2 | 2 h (business-hours); by-end-of-day otherwise | 8 h | 24 h |
| SEV-3 | 24 h (triaged in the /djinn loop) | as capacity permits | fix alongside regular work |

Pre-launch (before 2026-06-11 kickoff), SEV-1 paging goes to the user only.
Post-launch, this matrix assumes an explicit on-call rotation; that section
lives in `docs/operations-rotation.md` (TODO, tracked as a P2 follow-up).

## 4. Watchdog-the-watchdog

The biggest single failure mode is "the monitoring silently stopped running."
The same `/opt/monitoring/cron.log` is append-only; a missing entry is the
signal.

- Every script exits with a log line. Absence of that line for its expected
  cadence (e.g., `health-check.sh` not logging for > 15 min) = the monitor is
  wedged.
- `scripts/ops-cron-watchdog.sh` ships this: it reads the mtime of
  `health.log`, `synthetic.log`, and `cron-stats.log` and alerts on the 2nd
  consecutive detection that any of them is older than 3× expected cadence.
  Deployed to the production VPS as `/opt/monitoring/cron-watchdog.sh`, scheduled every
  10 min. Logs to `cron-watchdog.log` and alerts via Telegram using the same
  `.env` as `health-check.sh`.

## 5. Known gaps (follow-ups)

These are the pieces that turn this doc from "written" to "operational." Each
is tracked as a task in the project loop or a P-item in MAINNET_BLOCKERS.md.

1. ~~**Second-level watcher on `/opt/monitoring/cron.log`**~~ — shipped
   2026-04-18 as `scripts/ops-cron-watchdog.sh` + VPS cron `*/10 * * * *`.
2. **Prometheus aggregation** — each validator exposes `/metrics`, but there's
   no Grafana or push-gateway. Today it's ad-hoc curl. Pre-mainnet, the
   burn-gate fail-open counter (v1274) and settlement counters need a
   dashboard with alert rules.
3. ~~**Audit-queue-age paging rule**~~ — shipped 2026-04-18 as
   `scripts/ops-audit-queue-watchdog.sh` + VPS cron `*/15 * * * *`. Polls
   UID 0 `/v1/audit/summary`; alerts SEV-1 when queue non-decreasing and
   `settled` flat across 8 consecutive samples (≈ 2 h). `audit-probe.sh`
   stays as the log-only detector.
4. **Operations rotation doc** — scoped for post-launch. Placeholder above.
5. **P1-08 (incident response runbook)** — complements this SLA doc by
   defining the actual playbooks (who runs `cast pause` in a pinch, where the
   operator key lives, etc.). This SLA defines WHEN; the runbook defines HOW.

## 6. Revision log

- 2026-04-18 · initial draft (v1275 context; P1-11 closes on merge).
