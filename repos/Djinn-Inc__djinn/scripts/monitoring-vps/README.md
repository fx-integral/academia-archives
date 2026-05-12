# Production VPS monitoring scripts

Canonical source for the monitoring scripts that run via cron on the production VPS
(`161.97.138.250`). Live copies are at `/opt/monitoring/` on that box.

**Secrets live in `/opt/monitoring/.env` on the VPS, not in the repo.**
Both scripts source that file early. Required keys:

```
TELEGRAM_BOT_TOKEN=...
TELEGRAM_CHAT_ID=...
```

## health-check.sh

Runs every 5 min (`*/5 * * * *`). Probes five endpoints; alerts via
Telegram only after two consecutive identical failures, then stays silent
until the failure set changes or recovers.

Consecutive-failure gate uses a hash of the failure set with a suffix
marker (`:alerted`) to dedupe repeat alerts. When editing the gate, keep
the invariant that **stripping the marker must restore hash equality**
with the current failure hash — otherwise the counter will reset on
every alert and the script will page every 10 min (the 2026-04-18
debust-spam bug).

## djinn-flow-monitor.sh

Runs every 20 min (`*/20 * * * *`). Scrapes the last 20 minutes of
`~/.pm2/logs/djinn-validator-out.log` (falls back to `pm2 logs` over SSH
for dev-box runs) and tracks the signal/purchase/settlement pipeline:

- `POST /v1/check` status distribution (the 2026-04-19 malformed-payload
  outage that motivated this monitor)
- `POST /v1/signal` share-store status distribution
- `POST /v1/signal/{id}/purchase` success rate
- `check_validation_failed` structured log events (any one is a client bug)

Alerts (hour-bucketed dedup via `/opt/monitoring/djinn-flow-state.json`):

- any `check_validation_failed` event in the window
- purchase success below 90% (MIN_SAMPLE=5)
- /v1/check 5xx rate >= 10%
- /v1/signal 5xx rate >= 10%

State/log live at `/opt/monitoring/djinn-flow-state.json` and
`/opt/monitoring/djinn-flow.log`.

## synthetic-test.sh

Runs hourly (`0 * * * *`). Picks one rotating URL per service and drives
a full snap/capture flow end-to-end. Same suppression pattern.

`httpbin.org/html`, `/json`, `/xml` were removed from the rotation list
because TLSNotary can't negotiate their Heroku TLS config reliably.
`/robots.txt` and `/get` stay as working smoke tests of the httpbin host.

## Updating a live script

```
scp -J root@161.97.138.250 scripts/monitoring-vps/health-check.sh \
  root@161.97.138.250:/opt/monitoring/health-check.sh
ssh root@161.97.138.250 \
  "chmod +x /opt/monitoring/health-check.sh && bash -n /opt/monitoring/health-check.sh"
```

Keep a `.bak-YYYYMMDD-HHMM` copy on the VPS before replacing.
