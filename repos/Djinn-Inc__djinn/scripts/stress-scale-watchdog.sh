#!/usr/bin/env bash
# Watchdog wrapper for stress-scale.mjs. Re-runs the script if it exits
# nonzero or dies silently, until either the target count is reached or
# a stop file is touched. Resilient to network blips, RPC hiccups, and
# parent-shell death (use nohup or pm2 to launch this).
#
# Usage:
#   stress-scale-watchdog.sh [stress-scale args...]
# Stop:
#   touch /tmp/stress-scale-watchdog.stop
#
# Reads E2E_TEST_PRIVATE_KEY + E2E_DEPLOYER_KEY from env (caller must export).

set -uo pipefail

REPO=/home/user/djinn
LOG=/tmp/stress-scale-watchdog.log
STOP=/tmp/stress-scale-watchdog.stop
TSV=${TSV:-/tmp/stress-scale.tsv}
MAX_RESTARTS=${MAX_RESTARTS:-50}
BACKOFF_SEC=${BACKOFF_SEC:-30}

log() {
  echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] $*" | tee -a "$LOG"
}

if [ -z "${E2E_TEST_PRIVATE_KEY:-}" ] || [ -z "${E2E_DEPLOYER_KEY:-}" ]; then
  log "FATAL: Set E2E_TEST_PRIVATE_KEY and E2E_DEPLOYER_KEY before running"
  exit 1
fi

rm -f "$STOP"
log "watchdog starting; tsv=$TSV; child args: $*"

n=0
while [ "$n" -lt "$MAX_RESTARTS" ]; do
  if [ -f "$STOP" ]; then
    log "stop file present, exiting"
    rm -f "$STOP"
    exit 0
  fi
  n=$((n + 1))
  log "restart #$n: launching stress-scale.mjs"
  cd "$REPO"
  set +e
  node scripts/stress-scale.mjs --log="$TSV" "$@" 2>&1 | tee -a "$LOG"
  rc=${PIPESTATUS[0]}
  set -e
  log "restart #$n: child exited rc=$rc"
  if [ "$rc" = 0 ]; then
    log "child exited cleanly, watchdog done"
    exit 0
  fi
  log "backing off ${BACKOFF_SEC}s before retry"
  sleep "$BACKOFF_SEC"
done

log "max restarts ($MAX_RESTARTS) reached, giving up"
exit 1
