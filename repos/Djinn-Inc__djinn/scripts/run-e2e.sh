#!/usr/bin/env bash
# Run the multi-user E2E test suite and report results.
set -euo pipefail

cd /home/user/djinn/web

# 2026-05-03: cron doesn't inherit a shell with .env loaded, so source the
# env files explicitly. Without this, E2E_GENIUS_KEY is empty and
# signal-lifecycle.spec.ts fails to even parse (TypeError: invalid BytesLike).
# Silently ignore missing files (`.env.local` may be absent on some boxes).
set -a
[ -f .env ] && . .env
[ -f .env.local ] && . .env.local
set +a

# Fund wallets if needed
node ../scripts/fund-test-wallets.mjs 2>&1 | tail -5

# Run tests. signal-lifecycle.spec.ts actually commits + purchases a signal
# on-chain; multi-user-e2e only walks the UI. Both are required for the green
# bar to mean "feature works," not "pages load" — learned from the v1327
# outage where /v1/check broke in prod while cron reported green (see
# ~/.claude/commands/djinn-notes.md "green cron is not feature works").
RESULT=$(npx playwright test e2e/live/multi-user-e2e.spec.ts e2e/live/signal-lifecycle.spec.ts --reporter=list --timeout=90000 2>&1)
PASSED=$(echo "$RESULT" | grep -c "✓" || true)
FAILED=$(echo "$RESULT" | grep -c "✘" || true)
TOTAL=$((PASSED + FAILED))

echo "$RESULT" | tail -3

# Alert on failure
if [ "$FAILED" -gt 0 ] && [ -f /home/user/telegram-bot/.env ]; then
  source /home/user/telegram-bot/.env
  FAILURES=$(echo "$RESULT" | grep "✘" | head -5)
  python3 ~/telegram-bot/send.py --chat-id 1530623518 "E2E FAILED: $PASSED/$TOTAL passed
$FAILURES"
fi

echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] passed=$PASSED failed=$FAILED" >> /home/user/djinn/scripts/e2e-results.log
