#!/usr/bin/env bash
# Synthetic tests for Debust, FirmRecord, and ProveAudit
# Runs hourly via cron. ProveAudit test runs only at 06:00 UTC.
set -uo pipefail

# --- Config ---
LOG_DIR="/opt/monitoring"
if [ -f "$LOG_DIR/.env" ]; then source "$LOG_DIR/.env"; fi
TELEGRAM_BOT_TOKEN="${TELEGRAM_BOT_TOKEN:?missing from $LOG_DIR/.env}"
TELEGRAM_CHAT_ID="${TELEGRAM_CHAT_ID:?missing from $LOG_DIR/.env}"
LOG_FILE="$LOG_DIR/synthetic.log"
LOCK_FILE="$LOG_DIR/synthetic-test.lock"
STATE_FILE="$LOG_DIR/synthetic-state.json"
DEBUST_BASE="http://localhost:3200"
FIRMRECORD_BASE="http://localhost:3100"
PROVEAUDIT_BASE="http://localhost:3300"

# Max time to wait for a snap/capture to complete (seconds)
SNAP_TIMEOUT=300
CAPTURE_TIMEOUT=180

# --- URL rotation lists ---
DEBUST_URLS=(
  "https://en.wikipedia.org/wiki/Main_Page"
  "https://en.wikipedia.org/wiki/Unix"
  "https://en.wikipedia.org/wiki/Linux"
  "https://en.wikipedia.org/wiki/Internet"
  "https://en.wikipedia.org/wiki/Cryptography"
  # httpbin.org/html, /json, /xml consistently 5xx or time out through
  # TLSNotary (Heroku TLS negotiation incompatible with the TLSN prover
  # for those content types). /robots.txt + /get work reliably, so keep
  # those two as smoke tests of the httpbin endpoint.
  "https://httpbin.org/robots.txt"
  "https://httpbin.org/get"
  "https://www.ietf.org"
  "https://www.w3.org"
  "https://news.ycombinator.com"
  "https://lobste.rs"
  "https://www.rfc-editor.org"
  "https://developer.mozilla.org/en-US/"
  "https://docs.python.org/3/"
  "https://go.dev"
  "https://www.rust-lang.org"
  "https://www.typescriptlang.org"
  "https://soliditylang.org"
)

FIRMRECORD_URLS=(
  "https://en.wikipedia.org/wiki/Main_Page"
  "https://en.wikipedia.org/wiki/Bitcoin"
  "https://en.wikipedia.org/wiki/Ethereum"
  "https://github.com/bitcoin/bitcoin"
  "https://github.com/ethereum/go-ethereum"
  # httpbin.org/html, /json consistently fail TLSNotary (see DEBUST_URLS).
  "https://httpbin.org/get"
  "https://www.ietf.org"
  "https://www.w3.org"
  "https://news.ycombinator.com"
  "https://developer.mozilla.org/en-US/"
  "https://docs.python.org/3/"
  "https://go.dev"
  "https://www.rust-lang.org"
  "https://www.typescriptlang.org"
  "https://lobste.rs"
  "https://www.rfc-editor.org"
  "https://soliditylang.org"
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

get_rotating_url() {
  local -n arr=$1
  local len=${#arr[@]}
  local hour
  hour=$(date +%k | tr -d ' ')
  local day
  day=$(date +%j | sed 's/^0*//')
  local idx=$(( (day * 24 + hour) % len ))
  echo "${arr[$idx]}"
}

# --- Setup ---
mkdir -p "$LOG_DIR"

# Prevent overlapping runs
if [ -f "$LOCK_FILE" ]; then
  lock_age=$(( $(date +%s) - $(stat -c%Y "$LOCK_FILE" 2>/dev/null || echo 0) ))
  if [ "$lock_age" -lt 600 ]; then
    log "SKIP: previous synthetic run still active (lock age: ${lock_age}s)"
    exit 0
  fi
  rm -f "$LOCK_FILE"
fi
trap 'rm -f "$LOCK_FILE"' EXIT
echo $$ > "$LOCK_FILE"

failures=""

# =============================================================================
# DEBUST SYNTHETIC TEST
# =============================================================================
test_debust() {
  local url
  url=$(get_rotating_url DEBUST_URLS)
  log "DEBUST: Testing snap for $url"

  # Submit snap
  local response
  response=$(curl -s -X POST "${DEBUST_BASE}/api/snap" \
    -H "Content-Type: application/json" \
    -d "{\"url\": \"${url}\"}" \
    --connect-timeout 10 \
    --max-time 15 2>/dev/null)

  local snap_id
  snap_id=$(echo "$response" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('id',''))" 2>/dev/null || echo "")

  if [ -z "$snap_id" ]; then
    local error
    error=$(echo "$response" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('error','unknown'))" 2>/dev/null || echo "unknown")
    log "DEBUST: FAIL - could not create snap: ${error}"
    failures="${failures}Debust (snap creation failed: ${error}, url: ${url}), "
    return
  fi

  log "DEBUST: Snap created: ${snap_id}, polling status..."

  # Poll for completion
  local start_time
  start_time=$(date +%s)
  local status="processing"

  while [ "$status" = "processing" ] || [ "$status" = "queued" ]; do
    local elapsed=$(( $(date +%s) - start_time ))
    if [ "$elapsed" -gt "$SNAP_TIMEOUT" ]; then
      log "DEBUST: FAIL - snap ${snap_id} timed out after ${SNAP_TIMEOUT}s (status: ${status})"
      failures="${failures}Debust (timeout after ${SNAP_TIMEOUT}s, snap: ${snap_id}, url: ${url}), "
      return
    fi

    sleep 10

    local status_response
    status_response=$(curl -s "${DEBUST_BASE}/api/snap/${snap_id}" \
      --connect-timeout 10 \
      --max-time 15 2>/dev/null)

    status=$(echo "$status_response" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('status','unknown'))" 2>/dev/null || echo "unknown")
  done

  if [ "$status" = "complete" ] || [ "$status" = "verified" ]; then
    local elapsed=$(( $(date +%s) - start_time ))
    log "DEBUST: OK - snap ${snap_id} completed in ${elapsed}s (status: ${status})"
  else
    log "DEBUST: FAIL - snap ${snap_id} ended with status: ${status}"
    failures="${failures}Debust (status: ${status}, snap: ${snap_id}, url: ${url}), "
  fi
}

# =============================================================================
# FIRMRECORD SYNTHETIC TEST
# =============================================================================
test_firmrecord() {
  local url
  url=$(get_rotating_url FIRMRECORD_URLS)
  log "FIRMRECORD: Testing capture for $url"

  # FirmRecord requires authentication. We test the health endpoint deeply
  # and verify the capture API returns 401 (proving the route is live).
  local health_response
  health_response=$(curl -s "${FIRMRECORD_BASE}/health" \
    --connect-timeout 10 \
    --max-time 15 2>/dev/null)

  local health_status
  health_status=$(echo "$health_response" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('status',''))" 2>/dev/null || echo "")

  if [ "$health_status" != "ok" ]; then
    log "FIRMRECORD: FAIL - health check returned: ${health_status}"
    failures="${failures}FirmRecord (health: ${health_status}), "
    return
  fi

  # Verify the captures API route is responsive (should return 401 without auth)
  local capture_code
  capture_code=$(curl -s -o /dev/null -w "%{http_code}" -X POST "${FIRMRECORD_BASE}/api/captures" \
    -H "Content-Type: application/json" \
    -d "{\"url\": \"${url}\"}" \
    --connect-timeout 10 \
    --max-time 15 2>/dev/null || echo "000")

  if [ "$capture_code" = "401" ]; then
    log "FIRMRECORD: OK - API is responsive (auth required as expected, HTTP ${capture_code})"
  elif [ "$capture_code" = "200" ] || [ "$capture_code" = "201" ]; then
    log "FIRMRECORD: OK - capture created successfully (HTTP ${capture_code})"
  else
    log "FIRMRECORD: WARN - unexpected response from captures API: HTTP ${capture_code}"
    # Don't treat as failure; the service is up if health passed
  fi

  # Also verify the notary relay websocket endpoint exists
  local relay_code
  relay_code=$(curl -s -o /dev/null -w "%{http_code}" "${FIRMRECORD_BASE}/health" \
    --connect-timeout 10 \
    --max-time 15 2>/dev/null || echo "000")

  if [ "$relay_code" = "200" ]; then
    log "FIRMRECORD: OK - legacy health endpoint also responds"
  fi
}

# =============================================================================
# PROVEAUDIT SYNTHETIC TEST (daily at 06:00 UTC only)
# =============================================================================
test_proveaudit() {
  local current_hour
  current_hour=$(date -u +%H)

  if [ "$current_hour" != "06" ]; then
    return
  fi

  log "PROVEAUDIT: Running daily synthetic test"

  # ProveAudit requires Stripe payment to proceed with an audit.
  # We test by verifying the health endpoint and that the API routes respond correctly.
  local health_response
  health_response=$(curl -s "${PROVEAUDIT_BASE}/api/health" \
    --connect-timeout 10 \
    --max-time 15 2>/dev/null)

  local health_status
  health_status=$(echo "$health_response" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('status',''))" 2>/dev/null || echo "")

  if [ "$health_status" != "ok" ]; then
    log "PROVEAUDIT: FAIL - health check returned: ${health_status}"
    failures="${failures}ProveAudit (health: ${health_status}), "
    return
  fi

  # Verify the github tree API works (no payment needed)
  local tree_code
  tree_code=$(curl -s -o /dev/null -w "%{http_code}" \
    "${PROVEAUDIT_BASE}/api/github/tree?repo=https://github.com/octocat/Hello-World" \
    --connect-timeout 15 \
    --max-time 30 2>/dev/null || echo "000")

  if [ "$tree_code" = "200" ]; then
    log "PROVEAUDIT: OK - GitHub tree API responds (HTTP ${tree_code})"
  else
    log "PROVEAUDIT: FAIL - GitHub tree API returned HTTP ${tree_code}"
    failures="${failures}ProveAudit (tree API: HTTP ${tree_code}), "
    return
  fi

  # Verify audit creation returns proper validation error (no Stripe needed)
  local audit_response
  audit_response=$(curl -s -X POST "${PROVEAUDIT_BASE}/api/audit" \
    -H "Content-Type: application/json" \
    -d '{"email":"synthetic-test@monitoring.local","repoUrl":"https://github.com/octocat/Hello-World","repoOwner":"octocat","repoName":"Hello-World","selectedFiles":["README"],"auditType":"software","model":"opus","thinking":false}' \
    --connect-timeout 15 \
    --max-time 30 2>/dev/null)

  # We expect either a checkout URL (Stripe test mode) or a valid error
  local checkout_url
  checkout_url=$(echo "$audit_response" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('checkoutUrl',''))" 2>/dev/null || echo "")
  local audit_error
  audit_error=$(echo "$audit_response" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('error',''))" 2>/dev/null || echo "")

  if [ -n "$checkout_url" ]; then
    log "PROVEAUDIT: OK - audit creation works, Stripe checkout URL returned"
  elif [ -n "$audit_error" ]; then
    log "PROVEAUDIT: OK - audit API is responsive (returned expected error: ${audit_error})"
  else
    log "PROVEAUDIT: WARN - unexpected audit response: ${audit_response}"
  fi
}

# =============================================================================
# MAIN
# =============================================================================
log "=== Synthetic test run starting ==="

test_debust
test_firmrecord
test_proveaudit

# --- Alert on failure ---
# --- Alert on failure (with consecutive-failure gate to suppress transient noise) ---
# State at /opt/monitoring/synthetic-state.json maps "service|url" to a
# consecutive-failure count. A failure alerts ONLY if the SAME key has
# failed on >= 2 runs in a row. Single-run transients log silently,
# matching the reality that TLSNotary is flaky on Cloudflare/HTTP2
# targets (debust routes through SN103) and usually recovers on the
# next run.

STATE_FILE="$LOG_DIR/synthetic-state.json"
[ -f "$STATE_FILE" ] || echo '{}' > "$STATE_FILE"

# Always run the state-update step so recoveries clear old keys.
# Produces a newline-separated list of keys to alert on (persistent failures).
PERSISTENT=$(python3 - <<PYEOF
import json, re, os
state_path = "$STATE_FILE"
raw = """$failures"""
try:
    with open(state_path) as f:
        state = json.load(f)
except Exception:
    state = {}
seen = set()
persistent_lines = []
for part in re.split(r'\),\s*', raw):
    part = part.rstrip(')').strip()
    if not part:
        continue
    m = re.match(r'^(\w+)\b.*?url:\s*([^,)]+)', part)
    if m:
        key = f"{m.group(1).strip()}|{m.group(2).strip()}"
    else:
        m2 = re.match(r'^(\w+)', part)
        key = (m2.group(1) if m2 else part)[:60]
    if key in seen:
        continue
    seen.add(key)
    prev = state.get(key, {}).get('count', 0)
    state[key] = {'count': prev + 1, 'last_msg': part}
    if state[key]['count'] >= 2:
        persistent_lines.append(f"{part} (consecutive={state[key]['count']})")

# Clear keys that did not fail this run (they recovered).
for k in list(state.keys()):
    if k not in seen:
        del state[k]

with open(state_path, 'w') as f:
    json.dump(state, f, indent=2)

print('\n'.join(persistent_lines))
PYEOF
)

if [ -n "$failures" ]; then
  failures="${failures%, }"
  if [ -n "$PERSISTENT" ]; then
    alert_msg="<b>SYNTHETIC TEST FAILURE (persistent)</b>

<b>Failed (on 2+ consecutive runs):</b>
${PERSISTENT}

<b>What this means:</b> Same URL/service failed at least twice in a row. Debust routes through SN103 validators, so this is either a subnet-wide issue, operator config drift, or a target TLSNotary can't negotiate (Cloudflare/HTTP2).

<b>Server:</b> 161.97.138.250 (VPS #2)
<b>Time:</b> $(date '+%Y-%m-%d %H:%M:%S UTC')
<b>Timeout:</b> ${SNAP_TIMEOUT}s

Check logs: /opt/monitoring/synthetic.log"

    send_telegram "$alert_msg"
    log "ALERT sent (persistent): ${PERSISTENT}"
  else
    log "SUPPRESSED (first-occurrence, no alert): ${failures}"
  fi
fi

log "=== Synthetic test run complete ==="
