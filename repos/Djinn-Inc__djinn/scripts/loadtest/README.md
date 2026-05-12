# Djinn Load Tests

Load-testing harness to find concurrency / rate-limit / scale bugs before mainnet. Existing Playwright suites are single-worker happy-path and won't surface Cup-day failure modes (1000+ concurrent users). These tests do.

## What's here

- `k6-api.js` — ramp 100→500→1000 RPS against the public `/api/*` surface. Measures p95 latency, error rate, and per-endpoint breakdown. Enforces thresholds so the run FAILS if the system degrades. Supports `SMOKE=1` for a 10-RPS / 50s harness-verification pass that won't itself trip rate limits.

## Known gotcha: Vercel bot challenge

`https://djinn.gg/api/*` returns `HTTP 403 + x-vercel-challenge-token` for **any** request that lacks the bypass secret, even a single curl with a real-browser UA. This is not rate-related — it's first-contact challenge enforcement. Consequences:

- `SMOKE=1 TARGET=https://djinn.gg k6 run ...` will show 100% error rate (Vercel-challenge bodies), regardless of RPS.
- Real calibration requires `VERCEL_BYPASS_SECRET` OR running against a local Next build OR a staging env with the WAF disabled.
- If we ever ship public API access for integrators, this bot challenge needs to be selectively disabled on `/api/*`. Filed as a product follow-up.

## Running

### k6 (preferred, native)

```bash
# Install once (Linux):
sudo apt-get install k6 || curl -s https://dl.k6.io/key.gpg | sudo gpg --dearmor -o /usr/share/keyrings/k6-archive-keyring.gpg

# Smoke check (10 RPS for 30s, no bypass secret needed, safe vs Vercel WAF):
SMOKE=1 TARGET=https://djinn.gg k6 run scripts/loadtest/k6-api.js

# Full ramp against production (needs Vercel bypass):
VERCEL_BYPASS_SECRET=<from Vercel project settings> TARGET=https://djinn.gg \
  k6 run scripts/loadtest/k6-api.js

# Against local dev server:
TARGET=http://localhost:3000 k6 run scripts/loadtest/k6-api.js

# Against staging:
TARGET=https://staging.djinn.gg k6 run scripts/loadtest/k6-api.js
```

### k6 via Docker (no local install)

```bash
docker run --rm -i \
  -e VERCEL_BYPASS_SECRET \
  -e TARGET=https://djinn.gg \
  grafana/k6 run - < scripts/loadtest/k6-api.js
```

## Thresholds

The run fails if:

- p95 HTTP duration on read endpoints > 1500ms
- HTTP failure rate > 2%
- Check-pass rate < 98%

Tune these in `k6-api.js` `options.thresholds` after establishing a baseline.

## Output

- Stdout: summary table (total req, avg/p50/p95/p99 latency, error rate)
- `scripts/loadtest/last-run-summary.json`: full k6 metrics blob for diffing across runs

## Next steps (not yet implemented)

- `k6-purchase.js` — drive the full purchase flow at 10/50/100 concurrent buyers
- `k6-signal-create.js` — concurrent signal creation to stress MPC
- Playwright concurrency spec — 20-50 parallel browsers running visitor/idiot journeys (must target staging or localhost; prod Vercel WAF will trip)
