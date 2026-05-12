#!/usr/bin/env bash
# Health check for Debust, FirmRecord API, ProveAudit, and Djinn.gg
# Runs every 5 minutes via cron. Alerts on failure via Telegram.
set -uo pipefail

# --- Config ---
LOG_DIR="/opt/monitoring"
if [ -f "$LOG_DIR/.env" ]; then source "$LOG_DIR/.env"; fi
LOG_FILE="$LOG_DIR/health.log"
LOCK_FILE="$LOG_DIR/health-check.lock"
TIMEOUT=30  # curl timeout in seconds
ALERT_STATE="$LOG_DIR/.last-alert"

# --- Endpoints ---
declare -A ENDPOINTS=(
  ["Debust"]="http://localhost:3200/api/recent"
  ["FirmRecord"]="http://localhost:3100/health"
  ["ProveAudit"]="http://localhost:3300/api/health"
  ["Djinn.gg"]="https://www.djinn.gg"
  ["Djinn API"]="https://www.djinn.gg/api/odds?sport=basketball_nba"
)

# --- Functions ---
log() {
  echo "$(date '+%Y-%m-%d %H:%M:%S') $1" >> "$LOG_FILE"
}

send_telegram() {
  local message="$1"
  curl -s -X POST "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
    -d "chat_id=${TELEGRAM_CHAT_ID}" \
    -d "text=${message}" \
    -d "parse_mode=HTML" \
    --connect-timeout 10 \
    --max-time 15 > /dev/null 2>&1 || true
}

rotate_log() {
  if [ -f "$LOG_FILE" ]; then
    local size
    size=$(stat -c%s "$LOG_FILE" 2>/dev/null || echo 0)
    # Rotate if > 5MB (safety net; logrotate handles daily rotation)
    if [ "$size" -gt 5242880 ]; then
      mv "$LOG_FILE" "${LOG_FILE}.$(date '+%Y%m%d%H%M%S')"
      # Keep only last 7 rotated files
      ls -1t "${LOG_FILE}".* 2>/dev/null | tail -n +8 | xargs rm -f 2>/dev/null || true
    fi
  fi
}

# --- Setup ---
mkdir -p "$LOG_DIR"
rotate_log

# Prevent overlapping runs
if [ -f "$LOCK_FILE" ]; then
  lock_age=$(( $(date +%s) - $(stat -c%Y "$LOCK_FILE" 2>/dev/null || echo 0) ))
  if [ "$lock_age" -lt 120 ]; then
    log "SKIP: previous run still active (lock age: ${lock_age}s)"
    exit 0
  fi
  rm -f "$LOCK_FILE"
fi
trap 'rm -f "$LOCK_FILE"' EXIT
echo $$ > "$LOCK_FILE"

# --- Check each endpoint ---
failures=""
details=""
total=0
ok=0

for name in "${!ENDPOINTS[@]}"; do
  url="${ENDPOINTS[$name]}"
  total=$((total + 1))

  http_code=$(curl -sL -o /dev/null -w "%{http_code}" --connect-timeout "$TIMEOUT" --max-time "$TIMEOUT" "$url" 2>/dev/null || echo "000")

  if [ "$http_code" = "200" ]; then
    ok=$((ok + 1))
    details="${details}  ${name}: OK (${http_code})\n"
  else
    failures="${failures}${name} (HTTP ${http_code}), "
    details="${details}  ${name}: FAIL (${http_code})\n"
  fi
done

# --- Log results ---
log "Health check: ${ok}/${total} OK"
echo -e "$details" | while read -r line; do
  [ -n "$line" ] && log "  $line"
done
# --- Alert on failure (consecutive-failure gate) ---
# Prevents single-check transients (cold-start 502s, 1-tick RPC hiccups,
# odd Vercel eviction) from paging the user. Only alerts when the SAME
# failure set persists on >= 2 consecutive checks (~10+ minutes sustained).
# Mirrors the pattern in synthetic-test.sh (2026-04-14 incident).

STATE_FILE="$LOG_DIR/.health-state"
# State file has two lines:
#   line 1: md5 of last failure set (empty = last check was healthy)
#   line 2: consecutive-failure count for that hash
read_state() {
  if [ -f "$STATE_FILE" ]; then
    LAST_HASH=$(sed -n '1p' "$STATE_FILE")
    LAST_COUNT=$(sed -n '2p' "$STATE_FILE")
  else
    LAST_HASH=""
    LAST_COUNT=0
  fi
  LAST_COUNT=${LAST_COUNT:-0}
}
write_state() {
  printf "%s\n%s\n" "$1" "$2" > "$STATE_FILE"
}

read_state

if [ -n "$failures" ]; then
  failures="${failures%, }"
  fail_hash=$(echo "$failures" | md5sum | cut -d" " -f1)
  # Strip ":alerted" marker so the consecutive counter keeps growing across
  # alerted runs. Without this the counter reset to 1 after every alert,
  # which caused a persistent failure to re-alert every 10 min (the bug
  # that produced the debust Telegram spam on 2026-04-18).
  LAST_HASH_BASE="${LAST_HASH%:alerted}"
  if [ "$fail_hash" = "$LAST_HASH_BASE" ]; then
    NEW_COUNT=$((LAST_COUNT + 1))
  else
    NEW_COUNT=1
  fi

  if [ "$NEW_COUNT" -ge 2 ] && [ "${fail_hash}:alerted" != "$LAST_HASH" ]; then
    # Persistent failure, first alert for this failure set. The ":alerted"
    # marker on LAST_HASH means we already paged for this exact failure;
    # stay silent until the set changes or recovers.
    alert_msg="<b>HEALTH CHECK FAILURE (persistent)</b>

<b>Down:</b> ${failures}
<b>Consecutive checks failed:</b> ${NEW_COUNT}

<b>Server:</b> 161.97.138.250 (VPS #2)
<b>Time:</b> $(date '+%Y-%m-%d %H:%M:%S UTC')

Check logs: /opt/monitoring/health.log"

    send_telegram "$alert_msg"
    log "ALERT sent (persistent, n=${NEW_COUNT}): ${failures}"
    write_state "${fail_hash}:alerted" "$NEW_COUNT"
  elif [ "$NEW_COUNT" -eq 1 ]; then
    write_state "$fail_hash" "$NEW_COUNT"
    log "SUPPRESSED (first-occurrence, n=1): ${failures}"
  else
    # n>=2 and already alerted: keep ":alerted" marker, just bump count.
    write_state "${fail_hash}:alerted" "$NEW_COUNT"
    log "ALERT already sent for this failure set (n=${NEW_COUNT}): ${failures}"
  fi
else
  # All healthy this check.  If we previously alerted, notify recovery.
  if [[ "$LAST_HASH" == *:alerted ]]; then
    send_telegram "<b>RECOVERED</b> All services healthy."
    log "RECOVERY sent"
  elif [ -n "$LAST_HASH" ] && [ "$LAST_COUNT" -lt 2 ]; then
    log "Transient cleared after n=${LAST_COUNT} (no alert ever sent)"
  fi
  # Reset state.
  rm -f "$STATE_FILE"
fi
