#!/usr/bin/env bash
# Audit-queue-age watchdog.
#
# Polls /v1/audit/summary on UID 0 and alerts when the audit pipeline is
# stalling: queue depth (waiting_for_outcomes + ready_for_settlement) grows
# monotonically while settled count stays flat for > 2 hours. That's the
# signature of a stuck OV quorum or a failing forceSettle — either way the
# settlement pipeline is not finalizing and user funds are accumulating in
# escrow unresolved.
#
# Cadence: every 15 min (96 samples/day, state file ~2KB). Alert fires on
# 8 consecutive stall samples (= 2 h sustained stall).
#
# Referenced from docs/operations-sla.md §5 item 3.
# Complements /opt/monitoring/audit-probe.sh which LOGS but does not page.

set -uo pipefail

LOG_DIR="${LOG_DIR:-/opt/monitoring}"
LOG_FILE="$LOG_DIR/audit-queue-watchdog.log"
STATE_FILE="$LOG_DIR/.audit-queue-state"
# shellcheck disable=SC1091
[ -f "$LOG_DIR/.env" ] && source "$LOG_DIR/.env"

TARGET_URL="${AUDIT_QUEUE_TARGET:-https://v0.djinn.gg/v1/audit/summary}"
STALL_THRESHOLD="${AUDIT_QUEUE_STALL_SAMPLES:-8}"

log() {
  echo "$(date '+%Y-%m-%d %H:%M:%S') $1" >> "$LOG_FILE"
}

send_telegram() {
  local message="$1"
  [ -z "${TELEGRAM_BOT_TOKEN:-}" ] && return 0
  [ -z "${TELEGRAM_CHAT_ID:-}" ] && return 0
  curl -s -X POST "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
    -d "chat_id=${TELEGRAM_CHAT_ID}" \
    -d "text=${message}" \
    -d "parse_mode=HTML" \
    --connect-timeout 10 --max-time 15 > /dev/null 2>&1 || true
}

resp=$(curl -sS --max-time 10 "$TARGET_URL" 2>/dev/null)
if [ -z "$resp" ]; then
  log "SKIP: target unreachable ($TARGET_URL)"
  exit 0
fi

# Parse — any parse failure skips the sample rather than false-negatives.
parsed=$(printf '%s' "$resp" | python3 -c '
import json, sys
try:
    d = json.load(sys.stdin)
    q = int(d.get("waiting_for_outcomes", 0)) + int(d.get("ready_for_settlement", 0))
    s = int(d.get("settled", 0))
    print(f"{q} {s}")
except Exception:
    sys.exit(1)
' 2>/dev/null) || { log "SKIP: parse error"; exit 0; }

queue_depth=$(echo "$parsed" | cut -d' ' -f1)
settled=$(echo "$parsed" | cut -d' ' -f2)

# State file layout (one sample per line, oldest first):
#   <epoch> <queue_depth> <settled>
# At each run: append current sample, evict older than STALL_THRESHOLD entries,
# then evaluate the stall condition on the retained window.
now=$(date +%s)
printf "%s %s %s\n" "$now" "$queue_depth" "$settled" >> "$STATE_FILE"

# Keep only the last STALL_THRESHOLD lines.
tail -n "$STALL_THRESHOLD" "$STATE_FILE" > "${STATE_FILE}.tmp" && mv "${STATE_FILE}.tmp" "$STATE_FILE"

sample_count=$(wc -l < "$STATE_FILE")
if [ "$sample_count" -lt "$STALL_THRESHOLD" ]; then
  log "WARMUP: $sample_count/$STALL_THRESHOLD samples (queue=$queue_depth settled=$settled)"
  exit 0
fi

# Stall criteria (all must hold across the window):
#   - minimum queue_depth in window > 0 (we're not in idle zero state)
#   - queue_depth non-decreasing across the window
#   - settled unchanged across the window
stall_reason=""
prev_q=-1
prev_s=-1
min_q=999999999
max_q=0
min_s=999999999
max_s=0
stall=true
while read -r _ts q s; do
  [ "$q" -lt "$min_q" ] && min_q="$q"
  [ "$q" -gt "$max_q" ] && max_q="$q"
  [ "$s" -lt "$min_s" ] && min_s="$s"
  [ "$s" -gt "$max_s" ] && max_s="$s"
  if [ "$prev_q" -ge 0 ] && [ "$q" -lt "$prev_q" ]; then
    stall=false
    stall_reason="queue shrank"
  fi
  prev_q=$q
  prev_s=$s
done < "$STATE_FILE"

if [ "$min_q" -eq 0 ]; then
  stall=false
  stall_reason="queue idle (zero)"
fi
if [ "$min_s" -ne "$max_s" ]; then
  stall=false
  stall_reason="settled incremented"
fi

# Tracker for alert-once behavior — the state file doesn't include the
# alerted bit, so use a sidecar marker.
ALERTED_MARKER="$LOG_DIR/.audit-queue-alerted"
if [ "$stall" = "true" ]; then
  if [ ! -f "$ALERTED_MARKER" ]; then
    alert_msg="<b>AUDIT QUEUE STALL (SEV-1)</b>

Audit settlement pipeline is not finalizing.

<b>Window:</b> last $STALL_THRESHOLD samples (~$(( STALL_THRESHOLD * 15 )) min)
<b>Queue depth:</b> min=$min_q max=$max_q (non-decreasing)
<b>Settled count:</b> $min_s (flat across window)
<b>Source:</b> $TARGET_URL

This is the SEV-1 condition from docs/operations-sla.md §2: pending
outcomes growing without settled incrementing. Likely causes:
  1. OV quorum can't be reached (check UIDs voting into the right contract)
  2. forceSettle tx lifecycle stuck (P0-09 area)
  3. Outcome data missing / oracle stalled

Investigate on UID 0: check /health.settlement_diagnosis, tail
validator logs for settle failures, verify OV signer set on-chain."
    send_telegram "$alert_msg"
    touch "$ALERTED_MARKER"
    log "ALERT sent (queue=$min_q..$max_q settled=$min_s across $STALL_THRESHOLD samples)"
  else
    log "STALL continues (already alerted) queue=$min_q..$max_q settled=$min_s"
  fi
else
  if [ -f "$ALERTED_MARKER" ]; then
    send_telegram "<b>AUDIT QUEUE: recovered.</b> Reason: $stall_reason. queue=$queue_depth settled=$settled"
    rm -f "$ALERTED_MARKER"
    log "RECOVERY sent (reason: $stall_reason)"
  else
    log "OK: $stall_reason (queue=$queue_depth settled=$settled)"
  fi
fi
