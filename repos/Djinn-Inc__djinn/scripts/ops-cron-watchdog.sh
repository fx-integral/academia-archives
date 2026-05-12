#!/usr/bin/env bash
# Second-level watcher on /opt/monitoring/cron.log.
#
# Fires a Telegram alert if the monitoring scripts themselves have stopped
# running — the failure mode health-check.sh and synthetic-test.sh cannot
# detect by definition (they would have to be running to notice).
#
# Targets (all deployed on the production VPS /opt/monitoring/):
#   - health-check.sh        expected cadence: every 5 min    → alert if silent for > 15 min
#   - synthetic-test.sh      expected cadence: hourly         → alert if silent for > 3 h
#   - attestation-stats.sh   expected cadence: every 5 min    → alert if silent for > 15 min
#
# Thresholds are 3× expected cadence: enough slack for one missed run and a
# retry before paging. The monitor itself runs every 10 minutes.
#
# State gate: same consecutive-failure pattern as health-check.sh — only
# alerts on the 2nd consecutive detection (prevents a single cron-jitter
# from paging).
#
# Referenced from docs/operations-sla.md §4.

set -uo pipefail

LOG_DIR="/opt/monitoring"
CRON_LOG="$LOG_DIR/cron.log"
WATCHDOG_LOG="$LOG_DIR/cron-watchdog.log"
STATE_FILE="$LOG_DIR/.cron-watchdog-state"
# shellcheck disable=SC1091
[ -f "$LOG_DIR/.env" ] && source "$LOG_DIR/.env"

now=$(date +%s)

log() {
  echo "$(date '+%Y-%m-%d %H:%M:%S') $1" >> "$WATCHDOG_LOG"
}

send_telegram() {
  local message="$1"
  # Leave silent if no telegram config — this is a best-effort watcher.
  [ -z "${TELEGRAM_BOT_TOKEN:-}" ] && return 0
  [ -z "${TELEGRAM_CHAT_ID:-}" ] && return 0
  curl -s -X POST "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
    -d "chat_id=${TELEGRAM_CHAT_ID}" \
    -d "text=${message}" \
    -d "parse_mode=HTML" \
    --connect-timeout 10 --max-time 15 > /dev/null 2>&1 || true
}

# (target_name, grep_pattern_in_cron_log, max_silence_seconds)
# cron.log contains stdout of every cron job; each monitoring script logs to its own
# file *and* gets its cadence timestamp visible indirectly via cron.log's size deltas.
# For reliable detection we read the script's OWN log (health.log, synthetic.log,
# cron-stats.log) where every run ends with a dated summary line.
check_one() {
  local name="$1"
  local target_log="$2"
  local max_silence="$3"

  if [ ! -f "$target_log" ]; then
    echo "MISSING:$name"
    return
  fi

  local mtime
  mtime=$(stat -c%Y "$target_log" 2>/dev/null || echo 0)
  local age=$((now - mtime))
  if [ "$age" -gt "$max_silence" ]; then
    echo "STALE:$name:${age}s"
  fi
}

mapfile -t failures < <(
  check_one "health-check"      "$LOG_DIR/health.log"     900
  check_one "synthetic-test"    "$LOG_DIR/synthetic.log"  10800
  check_one "attestation-stats" "$LOG_DIR/cron-stats.log" 900
)

# Collapse into a deterministic hash so we can gate on consecutive detections.
if [ "${#failures[@]}" -eq 0 ]; then
  fail_summary=""
  fail_hash=""
else
  fail_summary=$(printf '%s\n' "${failures[@]}" | sort)
  fail_hash=$(printf '%s' "$fail_summary" | md5sum | cut -d" " -f1)
fi

# Read prior state: line 1 = hash, line 2 = consecutive-count.
LAST_HASH=""
LAST_COUNT=0
if [ -f "$STATE_FILE" ]; then
  LAST_HASH=$(sed -n '1p' "$STATE_FILE")
  LAST_COUNT=$(sed -n '2p' "$STATE_FILE")
  LAST_COUNT=${LAST_COUNT:-0}
fi

if [ -n "$fail_hash" ]; then
  if [ "$fail_hash" = "$LAST_HASH" ]; then
    NEW_COUNT=$((LAST_COUNT + 1))
  else
    NEW_COUNT=1
  fi
  printf "%s\n%s\n" "$fail_hash" "$NEW_COUNT" > "$STATE_FILE"
  log "DETECT (n=$NEW_COUNT): $(echo "$fail_summary" | tr '\n' ',')"

  # Alert on 2nd consecutive detection; re-alert only if set changes.
  if [ "$NEW_COUNT" -ge 2 ] && [ "$fail_hash" != "${LAST_HASH}:alerted" ]; then
    alert_msg="<b>MONITOR WATCHDOG: monitoring scripts silent</b>

<b>Stale signals:</b>
$(echo "$fail_summary" | sed 's/^/  /')

<b>Consecutive detections:</b> $NEW_COUNT
<b>Server:</b> 161.97.138.250 (VPS #2)
<b>Time:</b> $(date '+%Y-%m-%d %H:%M:%S UTC')

These are the <i>detectors</i>, not the detected services. If this
fires, health-check / synthetic-test are not running — every SEV-1
condition they'd catch is silently invisible right now. Fix the cron
first, then re-audit the last hour of traffic."
    send_telegram "$alert_msg"
    log "ALERT sent (n=$NEW_COUNT)"
    printf "%s\n%s\n" "${fail_hash}:alerted" "$NEW_COUNT" > "$STATE_FILE"
  fi
else
  if [[ "$LAST_HASH" == *:alerted ]]; then
    send_telegram "<b>MONITOR WATCHDOG: recovered.</b> All monitoring scripts logging again."
    log "RECOVERY sent"
  fi
  rm -f "$STATE_FILE"
  log "OK: all monitors fresh"
fi
