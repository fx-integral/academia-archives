#!/usr/bin/env bash
# djinn-e2e-loop.sh — background E2E + UX sweep.
#
# Runs /djinn-e2e in headless claude -p mode, which:
#   1. git pull --rebase origin main
#   2. runs regression + heuristic sweeps
#   3. appends findings to UX_FINDINGS.md
#   4. commits + pushes UX_FINDINGS.md (nothing else)
#   5. exits clean
#
# Concurrency: only touches UX_FINDINGS.md + e2e-screenshots/, never product code.
# /djinn loop does `git pull --rebase` at Phase 0 to absorb findings pushed here.
#
# Called from crontab every 45 min. Logs to /tmp/djinn-e2e-loop.log (rotated weekly).

set -euo pipefail

LOG=/tmp/djinn-e2e-loop.log
LOCK=/tmp/djinn-e2e-loop.lock
STAMP=$(date -u +%Y-%m-%dT%H:%M:%SZ)

# Single-instance lock — if a previous run is still going, skip this slot.
exec 9>"$LOCK"
if ! flock -n 9; then
  echo "[$STAMP] skip: previous run still holding lock" >> "$LOG"
  exit 0
fi

# Rotate log weekly if > 5MB
if [ -f "$LOG" ] && [ "$(stat -c%s "$LOG")" -gt 5242880 ]; then
  mv "$LOG" "${LOG}.1"
  : > "$LOG"
fi

echo "===== [$STAMP] djinn-e2e-loop start =====" >> "$LOG"

cd /home/user/djinn

# Safety: require clean working tree. If dirty, the user (or /djinn) is mid-edit.
# Bail out rather than risk a rebase conflict.
if [ -n "$(git status --porcelain | grep -v '^?? ')" ]; then
  echo "[$STAMP] skip: working tree has unstaged/staged changes" >> "$LOG"
  git status --porcelain | head -10 >> "$LOG"
  exit 0
fi

# Invoke claude headless with the skill. Timeout long enough for full suite
# (regression ~10min + heuristic walk ~5min + git ops), but bounded.
TIMEOUT_SECONDS=1500  # 25 min

timeout "$TIMEOUT_SECONDS" /home/user/.local/bin/claude \
  -p "/djinn-e2e background" \
  --model claude-sonnet-4-6 \
  --permission-mode bypassPermissions \
  --add-dir /home/user/djinn \
  >> "$LOG" 2>&1 || echo "[$STAMP] claude exited non-zero or timed out" >> "$LOG"

echo "===== [$STAMP] djinn-e2e-loop end =====" >> "$LOG"
