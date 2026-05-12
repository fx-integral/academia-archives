#!/usr/bin/env bash
# Nightly feedback triage: fetch user reports, triage, send summary via Telegram
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
LOG="/tmp/feedback-triage.log"
REPORT="/tmp/feedback-triage-report.txt"

# Load Telegram credentials
source ~/telegram-bot/.env

GITHUB_REPO="djinn-inc/error-reports"
TG_API="https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}"
TG_CHAT_ID="${TELEGRAM_AUTHORIZED_USER_ID}"

log() { echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] $*" >> "$LOG"; }

send_telegram() {
  local text="$1"
  # Telegram max message length is 4096; truncate if needed
  if [ ${#text} -gt 4000 ]; then
    text="${text:0:3990}... (truncated)"
  fi
  curl -s -X POST "${TG_API}/sendMessage" \
    -d chat_id="${TG_CHAT_ID}" \
    -d parse_mode=Markdown \
    -d disable_web_page_preview=true \
    --data-urlencode "text=${text}" \
    >> "$LOG" 2>&1
}

log "Starting feedback triage"

# Fetch open issues
OPEN_ISSUES=$(gh issue list --repo "$GITHUB_REPO" --label user-report --state open --limit 50 --json number,title,body,createdAt,labels 2>>"$LOG") || {
  log "Failed to fetch issues"
  send_telegram "Feedback triage failed: could not fetch issues from ${GITHUB_REPO}"
  exit 1
}

OPEN_COUNT=$(echo "$OPEN_ISSUES" | jq 'length')
log "Found ${OPEN_COUNT} open issues"

if [ "$OPEN_COUNT" -eq 0 ]; then
  send_telegram "Feedback triage ($(date +%Y-%m-%d)): No open issues. All clear."
  log "No open issues, done"
  exit 0
fi

# Build report
cat > "$REPORT" <<EOF
*Feedback Triage Report* ($(date +%Y-%m-%d))
Open issues: ${OPEN_COUNT}

EOF

# Process each issue
echo "$OPEN_ISSUES" | jq -c '.[]' | while read -r issue; do
  NUM=$(echo "$issue" | jq -r '.number')
  TITLE=$(echo "$issue" | jq -r '.title' | head -c 100)
  CREATED=$(echo "$issue" | jq -r '.createdAt' | cut -dT -f1)
  BODY=$(echo "$issue" | jq -r '.body' | head -c 300)
  LABELS=$(echo "$issue" | jq -r '[.labels[].name] | join(", ")')

  # Check for suspicious content (prompt injection, social engineering, phishing)
  SUSPICIOUS=""
  BODY_LOWER=$(echo "$BODY" | tr '[:upper:]' '[:lower:]')
  for PATTERN in "delete everything" "email me" "send me" "wallet" "private key" "ignore previous" "ignore instructions" "<script" "onerror=" "onclick=" "javascript:" "../" "etc/passwd" "rm -rf" "drop table"; do
    if echo "$BODY_LOWER" | grep -qi "$PATTERN"; then
      SUSPICIOUS="${SUSPICIOUS} [${PATTERN}]"
    fi
  done

  if [ -n "$SUSPICIOUS" ]; then
    FLAG="SUSPICIOUS:${SUSPICIOUS}"
  elif echo "$LABELS" | grep -q "crash"; then
    FLAG="CRASH"
  else
    FLAG="REVIEW"
  fi

  cat >> "$REPORT" <<EOF
#${NUM} (${CREATED}) [${FLAG}]
_${TITLE}_
Labels: ${LABELS}

EOF
done

# Send via Telegram
REPORT_TEXT=$(cat "$REPORT")

# Add footer
REPORT_TEXT="${REPORT_TEXT}
Run \`/feedback-triage\` to investigate and fix."

send_telegram "$REPORT_TEXT"
log "Report sent to Telegram"
log "Done"
