#!/usr/bin/env bash
# djinn-flow-monitor: surfaces degradation in the signal/purchase/settlement
# pipeline. Runs from cron; silent unless something is off. Alerts via Telegram.
#
# Tracks (by scraping UID 0 validator logs over a rolling WINDOW_MIN window):
#   - POST /v1/check success/failure ratio (was the signal-creation bug that
#     produced the "odds data source experiencing errors" banner)
#   - POST /v1/signal (Shamir share store) success/failure ratio
#   - POST /v1/signal/*/purchase success/failure ratio
#   - check_validation_failed events (any is suspicious, logs body_preview so
#     we can identify misbehaving clients)
#
# Alerts when:
#   - Any check_validation_failed event in the last window
#   - Purchase success rate below PURCHASE_MIN_PCT (with enough sample)
#   - 5xx on signal-store or check over ALERT_5XX_MIN_PCT (with enough sample)
#
# To avoid alert fatigue: state file remembers last-alerted bucket so we don't
# re-fire the same alert on every cron tick.

set -uo pipefail

STATE_DIR="${STATE_DIR:-/opt/monitoring}"
STATE_FILE="$STATE_DIR/djinn-flow-state.json"
LOG_FILE="$STATE_DIR/djinn-flow.log"

# Rolling window for log analysis (minutes). Cron should run every WINDOW_MIN.
WINDOW_MIN="${WINDOW_MIN:-20}"

# Thresholds
MIN_SAMPLE=5              # skip alerts when volume too low (random noise)
PURCHASE_MIN_PCT=90       # purchase success must be at least this
ALERT_5XX_MIN_PCT=10      # alert if >= this % of requests 5xx'd

# Validator source of truth
VALIDATOR_HOST="${VALIDATOR_HOST:-v0.djinn.gg}"
VALIDATOR_SSH="${VALIDATOR_SSH:-root@161.97.138.250}"
VALIDATOR_INNER="${VALIDATOR_INNER:-root@161.97.138.250}"

# Telegram credentials. On the UID 0 box we source /opt/monitoring/.env
# (same pattern as synthetic-test.sh). On the dev box we fall back to the
# send.py wrapper if present.
TELEGRAM_ENV_FILE="${TELEGRAM_ENV_FILE:-/opt/monitoring/.env}"
if [ -z "${TELEGRAM_BOT_TOKEN:-}" ] && [ -f "$TELEGRAM_ENV_FILE" ]; then
  # shellcheck disable=SC1090
  set -a; . "$TELEGRAM_ENV_FILE"; set +a
fi
TELEGRAM_CHAT_ID="${TELEGRAM_CHAT_ID:-1530623518}"  # Djinn chat
TELEGRAM_SCRIPT="${TELEGRAM_SCRIPT:-$HOME/telegram-bot/send.py}"

mkdir -p "$STATE_DIR"
touch "$LOG_FILE"

log() { echo "$(date -u '+%Y-%m-%dT%H:%M:%SZ') $1" >> "$LOG_FILE"; }

alert() {
  local title="$1"
  local body="$2"
  local msg
  msg=$(printf '%s\n\n%s' "$title" "$body")
  local sent=false
  if [ -n "${TELEGRAM_BOT_TOKEN:-}" ]; then
    curl -sS -X POST "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
      --data-urlencode "chat_id=${TELEGRAM_CHAT_ID}" \
      --data-urlencode "text=${msg}" \
      >/dev/null 2>&1 && sent=true || true
  fi
  if ! $sent && { [ -x "$TELEGRAM_SCRIPT" ] || [ -f "$TELEGRAM_SCRIPT" ]; }; then
    TELEGRAM_CHAT_ID="$TELEGRAM_CHAT_ID" python3 "$TELEGRAM_SCRIPT" "$msg" >/dev/null 2>&1 || true
  fi
  log "ALERT $title"
}

# `pm2 logs --lines N` is slow and chatty: miner_in_bootstrap dominates, so a
# 15k-line pull only spans ~5 min of wall time. Reading the pm2 out-log file
# directly and pre-filtering to just the request/validation lines collapses a
# 33 MB file to a few KB per window before awk runs.
PM2_OUT_LOG="${PM2_OUT_LOG:-$HOME/.pm2/logs/djinn-validator-out.log}"
LOG_LINES="${LOG_LINES:-15000}"  # remote-SSH fallback only

# Subset of log lines we care about. Everything else is discarded at fetch.
RELEVANT_RE='path=/v1/(check|signal)|check_validation_failed'

fetch_logs() {
  if [ -r "$PM2_OUT_LOG" ]; then
    sed 's/\x1b\[[0-9;]*m//g' "$PM2_OUT_LOG" | grep -E "$RELEVANT_RE" || true
  elif command -v pm2 >/dev/null 2>&1 && pm2 describe djinn-validator >/dev/null 2>&1; then
    pm2 logs djinn-validator --lines "$LOG_LINES" --nostream --raw 2>&1 \
      | sed 's/\x1b\[[0-9;]*m//g' | grep -E "$RELEVANT_RE" || true
  else
    ssh -o ConnectTimeout=15 -o StrictHostKeyChecking=no \
      -J "$VALIDATOR_SSH" "$VALIDATOR_INNER" \
      "pm2 logs djinn-validator --lines $LOG_LINES --nostream --raw 2>&1" 2>/dev/null \
      | sed 's/\x1b\[[0-9;]*m//g' | grep -E "$RELEVANT_RE" || true
  fi
}
CLEAN_LOG=$(fetch_logs)

# Cutoff timestamp (ISO 8601 UTC, lexical comparison works)
CUTOFF=$(date -u -d "$WINDOW_MIN minutes ago" '+%Y-%m-%dT%H:%M:%S')

# Extract middleware request-log lines, filter by timestamp window.
# Format (after ANSI strip):
#   <ts>Z ... request ... method=POST path=/v1/check ... status=200
WINDOW=$(printf '%s\n' "$CLEAN_LOG" | awk -v c="$CUTOFF" '
  match($0, /[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}/) {
    ts = substr($0, RSTART, RLENGTH)
    if (ts >= c) print
  }
')

# Count by (path, status_bucket) for critical endpoints.
count_path_status() {
  local path="$1"
  local status_re="$2"
  printf '%s\n' "$WINDOW" \
    | grep -E "path=$path(\b| )" \
    | grep -cE "status=$status_re" || true
}

# /v1/check
CHECK_2XX=$(count_path_status "/v1/check" "2..")
CHECK_4XX=$(count_path_status "/v1/check" "4..")
CHECK_5XX=$(count_path_status "/v1/check" "5..")

# /v1/signal (store share): exact path, not /v1/signal/*
SIGNAL_STORE_2XX=$(printf '%s\n' "$WINDOW" | grep -E "path=/v1/signal\b" | grep -cE "status=2.." || true)
SIGNAL_STORE_4XX=$(printf '%s\n' "$WINDOW" | grep -E "path=/v1/signal\b" | grep -cE "status=4.." || true)
SIGNAL_STORE_5XX=$(printf '%s\n' "$WINDOW" | grep -E "path=/v1/signal\b" | grep -cE "status=5.." || true)

# /v1/signal/*/purchase
PURCHASE_2XX=$(printf '%s\n' "$WINDOW" | grep -E "path=/v1/signal/[^ ]+/purchase\b" | grep -cE "status=2.." || true)
PURCHASE_4XX=$(printf '%s\n' "$WINDOW" | grep -E "path=/v1/signal/[^ ]+/purchase\b" | grep -cE "status=4.." || true)
PURCHASE_5XX=$(printf '%s\n' "$WINDOW" | grep -E "path=/v1/signal/[^ ]+/purchase\b" | grep -cE "status=5.." || true)

# check_validation_failed events (new in v1327). Any occurrence is a client bug.
VALIDATION_FAILED=$(printf '%s\n' "$WINDOW" | grep -cE "check_validation_failed" || true)

# Rate helpers (bash integer math, guard div-by-zero)
pct() {
  local num="$1" den="$2"
  if [ "$den" -eq 0 ]; then echo 0; return; fi
  echo $(( num * 100 / den ))
}

CHECK_TOTAL=$((CHECK_2XX + CHECK_4XX + CHECK_5XX))
CHECK_5XX_PCT=$(pct "$CHECK_5XX" "$CHECK_TOTAL")

SIGNAL_STORE_TOTAL=$((SIGNAL_STORE_2XX + SIGNAL_STORE_4XX + SIGNAL_STORE_5XX))
SIGNAL_STORE_5XX_PCT=$(pct "$SIGNAL_STORE_5XX" "$SIGNAL_STORE_TOTAL")

PURCHASE_TOTAL=$((PURCHASE_2XX + PURCHASE_4XX + PURCHASE_5XX))
PURCHASE_SUCCESS_PCT=$(pct "$PURCHASE_2XX" "$PURCHASE_TOTAL")

log "check 2xx=$CHECK_2XX 4xx=$CHECK_4XX 5xx=$CHECK_5XX | signal-store 2xx=$SIGNAL_STORE_2XX 4xx=$SIGNAL_STORE_4XX 5xx=$SIGNAL_STORE_5XX | purchase 2xx=$PURCHASE_2XX 4xx=$PURCHASE_4XX 5xx=$PURCHASE_5XX | validation_failed=$VALIDATION_FAILED"

# Alert de-duplication: bucket by UTC hour. If we already fired X alert this
# hour, don't fire again (noise control).
BUCKET=$(date -u '+%Y-%m-%dT%H')
PREV_BUCKET=""
PREV_FLAGS=""
if [ -f "$STATE_FILE" ]; then
  PREV_BUCKET=$(grep -oE '"bucket":"[^"]*"' "$STATE_FILE" | sed 's/.*"\(.*\)"/\1/' || true)
  PREV_FLAGS=$(grep -oE '"flags":"[^"]*"' "$STATE_FILE" | sed 's/.*"\(.*\)"/\1/' || true)
fi
if [ "$BUCKET" != "$PREV_BUCKET" ]; then
  PREV_FLAGS=""
fi

NEW_FLAGS=""
fire_once() {
  local flag="$1"
  local title="$2"
  local body="$3"
  NEW_FLAGS="${NEW_FLAGS}${flag},"
  case ",$PREV_FLAGS," in
    *",$flag,"*) return ;;
  esac
  alert "$title" "$body"
}

# Rule 1: any check_validation_failed is a client bug. Tell us.
if [ "$VALIDATION_FAILED" -gt 0 ]; then
  PREVIEW=$(printf '%s\n' "$WINDOW" | grep -E "check_validation_failed" | head -1 | grep -oE "body_preview=[^ ]{0,300}" | head -c 300 || true)
  fire_once "validation_failed" \
    "Djinn /v1/check: $VALIDATION_FAILED malformed-payload events in last ${WINDOW_MIN}min" \
    "A client is sending /v1/check requests that fail Pydantic validation. Sample:\n$PREVIEW\n\nCheck validator logs for full body_preview and client IP."
fi

# Rule 2: purchase success rate
if [ "$PURCHASE_TOTAL" -ge "$MIN_SAMPLE" ] && [ "$PURCHASE_SUCCESS_PCT" -lt "$PURCHASE_MIN_PCT" ]; then
  fire_once "purchase_degraded" \
    "Djinn purchase success below $PURCHASE_MIN_PCT% (last ${WINDOW_MIN}min)" \
    "$PURCHASE_2XX / $PURCHASE_TOTAL successful (${PURCHASE_SUCCESS_PCT}%). 4xx=$PURCHASE_4XX, 5xx=$PURCHASE_5XX."
fi

# Rule 3: check endpoint 5xx rate
if [ "$CHECK_TOTAL" -ge "$MIN_SAMPLE" ] && [ "$CHECK_5XX_PCT" -ge "$ALERT_5XX_MIN_PCT" ]; then
  fire_once "check_5xx" \
    "Djinn /v1/check 5xx rate $CHECK_5XX_PCT% (last ${WINDOW_MIN}min)" \
    "$CHECK_5XX / $CHECK_TOTAL requests returned 5xx. Validator may be offline or miner fan-out is failing en masse."
fi

# Rule 4: signal-store 5xx rate
if [ "$SIGNAL_STORE_TOTAL" -ge "$MIN_SAMPLE" ] && [ "$SIGNAL_STORE_5XX_PCT" -ge "$ALERT_5XX_MIN_PCT" ]; then
  fire_once "signal_store_5xx" \
    "Djinn /v1/signal 5xx rate $SIGNAL_STORE_5XX_PCT% (last ${WINDOW_MIN}min)" \
    "$SIGNAL_STORE_5XX / $SIGNAL_STORE_TOTAL store_share requests returned 5xx."
fi

# Persist state (atomic via mv)
tmp="$STATE_FILE.tmp.$$"
cat > "$tmp" <<JSON
{"bucket":"$BUCKET","flags":"$NEW_FLAGS","last_run":"$(date -u '+%Y-%m-%dT%H:%M:%SZ')","check_total":$CHECK_TOTAL,"check_5xx":$CHECK_5XX,"purchase_total":$PURCHASE_TOTAL,"purchase_success_pct":$PURCHASE_SUCCESS_PCT,"validation_failed":$VALIDATION_FAILED}
JSON
mv "$tmp" "$STATE_FILE"
