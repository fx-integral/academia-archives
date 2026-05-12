#!/usr/bin/env bash
# fleet-version-monitor.sh — pings OV signers, alerts when their /health.version
# falls behind main HEAD or stops moving (watchtower wedged).
#
# Designed to run as a cron job on UID 0 (or any box with the Djinn repo + a
# Telegram bot installed). Output: a single Telegram DM per stale operator
# per stale-window, throttled by a state file at /tmp/fleet-version-monitor.state
# so we don't spam.
#
# Usage:
#   * * * * *  /root/djinn/scripts/fleet-version-monitor.sh >> /tmp/fleet-version-monitor.log 2>&1
#
# Why: 2026-05-01 P0-01 trace found 3 of 5 OV signers stuck 5–17 versions
# behind because their watchtower silently wedged on the v1625 self-heal
# regression. There was no pager. Operators only learned via Discord
# outreach. v1642 prevents future wedges; THIS prevents future silence.

set -euo pipefail

REPO="${REPO:-/root/djinn}"
STATE_FILE="${STATE_FILE:-/tmp/fleet-version-monitor.state}"
TELEGRAM_ENV="${TELEGRAM_ENV:-/home/user/telegram-bot/.env}"
TELEGRAM_SEND="${TELEGRAM_SEND:-/home/user/telegram-bot/send.py}"

# Operator chat IDs. -1 means "log only, no DM" (use for ones we don't have
# direct contact for yet). Replace with real chat IDs as we collect them.
# Default DM target falls back to OWNER_CHAT_ID for any unmapped UID.
OWNER_CHAT_ID="${OWNER_CHAT_ID:-1530623518}"

# Map of UID → {name, ip, chat_id}. Edit as operator chat IDs are confirmed.
declare -A SIGNER_NAMES=(
  [0]="Djinn"
  [1]="GeneralTensor"
  [2]="Yuma"
  [86]="Rizzo"
  [213]="TAOcom"
)
declare -A SIGNER_IPS=(
  [0]="v0.djinn.gg"
  [1]="v1.djinn.gg"
  [2]="v2.djinn.gg"
  [86]="v86.djinn.gg"
  [213]="v213.djinn.gg"
)
# Operator-direct chat IDs. Default to owner if unset.
declare -A SIGNER_CHATS=(
  [0]="$OWNER_CHAT_ID"
  [1]="$OWNER_CHAT_ID"
  [2]="$OWNER_CHAT_ID"
  [86]="$OWNER_CHAT_ID"
  [213]="$OWNER_CHAT_ID"
)

# Thresholds
LAG_THRESHOLD="${LAG_THRESHOLD:-3}"        # alert when behind by ≥ this many versions
WEDGE_HOURS="${WEDGE_HOURS:-2}"            # alert when version unchanged for ≥ this long
ALERT_COOLDOWN_HOURS="${ALERT_COOLDOWN_HOURS:-12}"  # don't re-alert same UID within window

now_epoch="$(date -u +%s)"

# Refresh tags + parse current main HEAD version
cd "$REPO"
git fetch --tags origin main >/dev/null 2>&1 || true
current_tag="$(git describe --tags --abbrev=0 origin/main 2>/dev/null | sed 's/^v//')"
current_n="${current_tag:-0}"

# Load prior state (per-UID: last_version, first_seen_at, last_alert_at)
declare -A LAST_VERSION LAST_SEEN LAST_ALERT
if [ -f "$STATE_FILE" ]; then
  while IFS=$'\t' read -r uid k v; do
    case "$k" in
      version)    LAST_VERSION[$uid]="$v" ;;
      seen_at)    LAST_SEEN[$uid]="$v" ;;
      alert_at)   LAST_ALERT[$uid]="$v" ;;
    esac
  done < "$STATE_FILE"
fi

send_alert() {
  local uid="$1" name="$2" version="$3" reason="$4"
  local chat_id="${SIGNER_CHATS[$uid]}"

  # Cooldown check
  local last_alert="${LAST_ALERT[$uid]:-0}"
  local cooldown_s=$((ALERT_COOLDOWN_HOURS * 3600))
  if [ "$((now_epoch - last_alert))" -lt "$cooldown_s" ]; then
    echo "[skip-cooldown] uid=$uid last_alert=$last_alert now=$now_epoch"
    return
  fi

  if [ ! -f "$TELEGRAM_ENV" ] || [ ! -f "$TELEGRAM_SEND" ]; then
    echo "[no-telegram] would alert uid=$uid name=$name reason=$reason"
    LAST_ALERT[$uid]="$now_epoch"
    return
  fi

  local msg
  msg="$(cat <<EOF
Djinn validator UID $uid ($name) needs attention.
version=v$version (main is v$current_n) — $reason

One-time unwedge (works for v1625/v1626 self-heal wedge):
  cd /root/djinn
  git checkout VERSION
  git pull --rebase origin main
  pm2 restart djinn-validator

Otherwise check: pm2 list | grep djinn, AUTO_UPDATE_INTERVAL env, watchtower logs.
This blocks AuditSettled across fleet (proposeSync jammed at nonce=11).
EOF
  )"

  source "$TELEGRAM_ENV"
  if python3 "$TELEGRAM_SEND" --chat-id "$chat_id" "$msg" >/dev/null 2>&1; then
    echo "[alert-sent] uid=$uid chat=$chat_id reason=$reason"
    LAST_ALERT[$uid]="$now_epoch"
  else
    echo "[alert-fail] uid=$uid chat=$chat_id"
  fi
}

# Probe each signer
for uid in "${!SIGNER_IPS[@]}"; do
  ip="${SIGNER_IPS[$uid]}"
  name="${SIGNER_NAMES[$uid]}"

  health_json="$(curl -sL -m 6 "http://$ip:8421/health" 2>/dev/null || echo '{}')"
  v_raw="$(echo "$health_json" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('version','?'))" 2>/dev/null || echo "down")"
  # Capability detection (v1647 lesson): the version string is unreliable
  # for non-git container installs (TAO.com 2026-05-01: their /health
  # reported v1626 for hours after their pipeline rebuilt to v1645,
  # because the committed VERSION fallback was stale). Instead probe for
  # a v1644+ schema field. Key PRESENT (regardless of value) means they
  # are running v1644+ code. Key ABSENT means pre-v1644. This survives
  # stale VERSION fallbacks because the field's existence is encoded by
  # Pydantic from the running code, not by /git.
  cap_v1644="$(echo "$health_json" | python3 -c "import json,sys; d=json.load(sys.stdin); print('yes' if 'git_dirty' in d else 'no')" 2>/dev/null || echo "unknown")"
  dirty_flag="$(echo "$health_json" | python3 -c "import json,sys; d=json.load(sys.stdin); v=d.get('git_dirty'); print('true' if v is True else ('false' if v is False else 'unknown'))" 2>/dev/null || echo "unknown")"
  dirty_files="$(echo "$health_json" | python3 -c "import json,sys; d=json.load(sys.stdin); print(','.join(d.get('git_dirty_files',[])[:3]))" 2>/dev/null || echo "")"

  # Strip leading "v" and "+N" suffix; we just want the integer release number
  v_num="${v_raw#v}"
  v_num="${v_num%%+*}"
  if ! [[ "$v_num" =~ ^[0-9]+$ ]]; then
    echo "[unparseable] uid=$uid raw=$v_raw"
    continue
  fi

  echo "[probe] uid=$uid name=$name version=$v_raw current=$current_n"

  # Detect lag
  lag=$((current_n - v_num))
  prior_version="${LAST_VERSION[$uid]:-}"
  prior_seen="${LAST_SEEN[$uid]:-$now_epoch}"

  if [ "$prior_version" = "$v_num" ]; then
    # Version unchanged since last poll. Keep first_seen_at as-is.
    seen_at="$prior_seen"
  else
    # Version moved (or first observation). Reset first_seen_at.
    seen_at="$now_epoch"
  fi

  hours_stuck=$(( (now_epoch - seen_at) / 3600 ))

  reason=""
  # Decision rules ordered by certainty:
  # 1) cap_v1644=no AND lag>=threshold: actually running pre-v1644 code.
  #    Genuine version lag, regardless of what the version string says.
  # 2) cap_v1644=yes AND dirty=true AND lag: confirmed git-wedge on a
  #    v1644+ box (their tree blocks pull). Alert immediately.
  # 3) cap_v1644=yes AND lag>=threshold: version string says behind but
  #    the running code is actually v1644+. Most likely a stale VERSION
  #    fallback in a no-.git container. NOT an alert — they may be fine.
  if [ "$cap_v1644" = "no" ] && [ "$lag" -ge "$LAG_THRESHOLD" ] && [ "$hours_stuck" -ge "$WEDGE_HOURS" ]; then
    reason="$lag versions behind (CONFIRMED pre-v1644 by capability probe), unchanged ${hours_stuck}h"
  elif [ "$cap_v1644" = "yes" ] && [ "$dirty_flag" = "true" ] && [ "$lag" -ge "$LAG_THRESHOLD" ]; then
    reason="$lag versions behind, git_dirty=true on [$dirty_files] (v1644+ box with wedged tree — needs git checkout)"
  fi
  # Note: cap_v1644=yes + lag-only is intentionally NOT alerted. Such
  # operators are running new code; their version string is stale only
  # because their build does not bump validator/djinn_validator/VERSION.
  # Treating that as "wedged" produces false alarms (TAO.com 2026-05-01).

  if [ -n "$reason" ]; then
    send_alert "$uid" "$name" "$v_num" "$reason"
  fi

  # Persist updated state
  LAST_VERSION[$uid]="$v_num"
  LAST_SEEN[$uid]="$seen_at"
done

# Write state file (atomic rewrite)
tmp_state="$(mktemp)"
for uid in "${!SIGNER_IPS[@]}"; do
  printf "%s\tversion\t%s\n" "$uid" "${LAST_VERSION[$uid]:-}" >> "$tmp_state"
  printf "%s\tseen_at\t%s\n"  "$uid" "${LAST_SEEN[$uid]:-$now_epoch}" >> "$tmp_state"
  printf "%s\talert_at\t%s\n" "$uid" "${LAST_ALERT[$uid]:-0}" >> "$tmp_state"
done
mv "$tmp_state" "$STATE_FILE"

echo "[done] current=v$current_n probed=${#SIGNER_IPS[@]}"
