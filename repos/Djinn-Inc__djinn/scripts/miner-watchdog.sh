#!/usr/bin/env bash
# Validator/miner health watchdog. Run via cron every 5 minutes.
# Checks bt_connected + status of our infrastructure and alerts on
# regression.
#
# Crontab entry:
#   */5 * * * * /root/djinn/scripts/miner-watchdog.sh
#
# History: 2026-04-17 we deregistered miner2 (UID 240); earlier miner1
# (UID 0) was also deregistered. Both pm2 processes still respawn but
# earn nothing. Watchdog now focuses on the validator (UID 0) which is
# our active production node. Re-add a MINERS entry if we re-register.

set -euo pipefail

TELEGRAM_SCRIPT="$HOME/telegram-bot/send.py"
CHAT_ID="1530623518"
STATE_FILE="/tmp/.miner-watchdog-state"

# No registered miners as of 2026-05-04. Leave the loop in place so we
# can re-add an entry without restructuring.
declare -A MINERS=()

declare -A VALIDATORS=(
  ["UID 0 (validator)"]="https://v0.djinn.gg/health"
)

alerts=""
recoveries=""

for name in "${!MINERS[@]}"; do
  url="${MINERS[$name]}"
  response=$(curl -s --max-time 10 "$url" 2>/dev/null || echo '{"status":"unreachable"}')

  bt_connected=$(echo "$response" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('bt_connected', 'unknown'))" 2>/dev/null || echo "parse_error")
  status=$(echo "$response" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('status', 'unknown'))" 2>/dev/null || echo "unreachable")
  uid=$(echo "$response" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('uid', 'null'))" 2>/dev/null || echo "null")

  state_key=$(echo "$name" | tr ' ()' '___')
  prev_state=$(grep "^$state_key=" "$STATE_FILE" 2>/dev/null | cut -d= -f2 || echo "unknown")

  if [ "$bt_connected" != "True" ] && [ "$bt_connected" != "true" ]; then
    # Alert on transition to unhealthy, or first check
    if [ "$prev_state" != "unhealthy" ]; then
      alerts="${alerts}$name: bt_connected=$bt_connected, status=$status, uid=$uid\n"
    fi
    echo "$state_key=unhealthy" >> "${STATE_FILE}.tmp"
  else
    # Recovery notification
    if [ "$prev_state" = "unhealthy" ]; then
      recoveries="${recoveries}$name: recovered (bt_connected=true, uid=$uid)\n"
    fi
    echo "$state_key=healthy" >> "${STATE_FILE}.tmp"
  fi
done

for name in "${!VALIDATORS[@]}"; do
  url="${VALIDATORS[$name]}"
  response=$(curl -s --max-time 10 "$url" 2>/dev/null || echo '{"status":"unreachable"}')
  status=$(echo "$response" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('status', 'unknown'))" 2>/dev/null || echo "unreachable")

  state_key=$(echo "$name" | tr ' ()' '___')
  prev_state=$(grep "^$state_key=" "$STATE_FILE" 2>/dev/null | cut -d= -f2 || echo "unknown")

  if [ "$status" != "ok" ] && [ "$status" != "degraded" ]; then
    if [ "$prev_state" != "unhealthy" ]; then
      alerts="${alerts}$name: status=$status (expected ok/degraded)\n"
    fi
    echo "$state_key=unhealthy" >> "${STATE_FILE}.tmp"
  else
    if [ "$prev_state" = "unhealthy" ]; then
      recoveries="${recoveries}$name: recovered (status=$status)\n"
    fi
    echo "$state_key=healthy" >> "${STATE_FILE}.tmp"
  fi
done

# Update state file
mv "${STATE_FILE}.tmp" "$STATE_FILE" 2>/dev/null || true

# Send alerts
if [ -n "$alerts" ]; then
  python3 "$TELEGRAM_SCRIPT" --chat-id "$CHAT_ID" "$(printf "Miner Watchdog ALERT\n\n%b\nCheck and restart affected services." "$alerts")" 2>/dev/null || true
fi

if [ -n "$recoveries" ]; then
  python3 "$TELEGRAM_SCRIPT" --chat-id "$CHAT_ID" "$(printf "Miner Watchdog Recovery\n\n%b" "$recoveries")" 2>/dev/null || true
fi
