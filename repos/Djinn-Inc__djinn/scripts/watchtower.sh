#!/usr/bin/env bash
# Watchtower: auto-pull and restart djinn services when new commits land.
# Usage: pm2 start scripts/watchtower.sh --name watchtower --cron "*/30 * * * *" --no-autorestart
#
# Multi-remote support (P1-04):
#   AUTO_UPDATE_REMOTES     — comma-separated remote names, tried in order.
#                             Default: "origin"
#   AUTO_UPDATE_REMOTE_URLS — semicolon-separated "name=url" pairs; the watchtower
#                             will `git remote add` / `set-url` to match on startup.
#                             Default: empty (assume every remote named in
#                             AUTO_UPDATE_REMOTES already exists locally)
#
# Fallthrough logic: each cycle tries `git ls-remote <name> main` against every
# listed remote in order; the first one that responds wins. If the pull against
# that remote fails, we fall through to the next. Every skip is logged so
# persistently-failing remotes are visible in the operator's journal.
#
# Backwards-compatible: if neither env var is set, behavior matches the
# previous single-remote-origin script exactly.

set -uo pipefail
cd "$(dirname "$0")/.."

REMOTES_CSV="${AUTO_UPDATE_REMOTES:-origin}"
REMOTE_URLS_SEMI="${AUTO_UPDATE_REMOTE_URLS:-}"

ts() { date -Iseconds; }
log() { echo "$(ts) $*"; }

IFS=',' read -ra REMOTES <<< "$REMOTES_CSV"

# Ensure declared remote URLs match. Parse "name=url;name=url" into an assoc
# array. Any remote mentioned in AUTO_UPDATE_REMOTE_URLS is either created or
# has its URL updated to the declared value. Remotes in AUTO_UPDATE_REMOTES
# but not in the URLs map are expected to already exist (and are skipped with
# a warning if they don't).
declare -A URL_MAP=()
if [ -n "$REMOTE_URLS_SEMI" ]; then
  IFS=';' read -ra URL_PAIRS <<< "$REMOTE_URLS_SEMI"
  for pair in "${URL_PAIRS[@]}"; do
    name="${pair%%=*}"
    url="${pair#*=}"
    if [ -n "$name" ] && [ -n "$url" ] && [ "$name" != "$pair" ]; then
      URL_MAP["$name"]="$url"
    fi
  done
fi

for remote in "${REMOTES[@]}"; do
  declared_url="${URL_MAP[$remote]:-}"
  current_url="$(git remote get-url "$remote" 2>/dev/null || echo "")"
  if [ -n "$declared_url" ]; then
    if [ -z "$current_url" ]; then
      git remote add "$remote" "$declared_url"
      log "watchtower_remote_added name=$remote url=$declared_url"
    elif [ "$current_url" != "$declared_url" ]; then
      git remote set-url "$remote" "$declared_url"
      log "watchtower_remote_url_updated name=$remote url=$declared_url"
    fi
  elif [ -z "$current_url" ]; then
    log "watchtower_remote_missing name=$remote (declared in AUTO_UPDATE_REMOTES but no URL configured and not in git config — skipping)"
  fi
done

LOCAL=$(git rev-parse HEAD)

# Try each remote in order. First successful `ls-remote main` wins.
chosen_remote=""
chosen_sha=""
for remote in "${REMOTES[@]}"; do
  if ! git remote get-url "$remote" >/dev/null 2>&1; then
    continue
  fi
  if sha=$(git ls-remote --exit-code "$remote" refs/heads/main 2>/dev/null | awk 'NR==1{print $1}'); then
    if [ -n "$sha" ]; then
      chosen_remote="$remote"
      chosen_sha="$sha"
      break
    fi
  fi
  log "watchtower_remote_skip remote=$remote reason=ls-remote-failed"
done

if [ -z "$chosen_remote" ]; then
  log "watchtower_all_remotes_unreachable remotes=$REMOTES_CSV"
  exit 1
fi

log "watchtower_started branch=main remotes=[$REMOTES_CSV] chosen=$chosen_remote"

# State file: SHA the validator was last restarted at. Set on every successful
# restart below. Compared at the end of every run against current HEAD so an
# out-of-band pull (someone else ran `git pull --rebase`) ALSO triggers a
# restart on the next watchtower cycle. Without this, the watchtower's
# "LOCAL == remote" check returns true after an out-of-band pull, no
# restart fires, and the running pm2 process keeps executing the previous
# code indefinitely. Found 2026-04-27 — 32h gap between v1615 deploy and
# v1618 actually running on UID 0 because v1616/v1617/v1618 each landed
# via an out-of-band pull and watchtower silently agreed "up to date".
LAST_RESTART_FILE=/var/lib/djinn/watchtower-last-restart-sha
mkdir -p "$(dirname "$LAST_RESTART_FILE")" 2>/dev/null
LAST_RESTART_SHA=$(cat "$LAST_RESTART_FILE" 2>/dev/null || echo "")

if [ "$LOCAL" = "$chosen_sha" ]; then
  log "Up to date at $(git rev-parse --short HEAD) via $chosen_remote"
else
  log "Updating via $chosen_remote: $(git rev-parse --short HEAD) -> ${chosen_sha:0:7}"

  # Fetch + ff-only merge from the chosen remote. If it fails (rare but possible
  # if the remote drifted between ls-remote and fetch, or the local tree has
  # uncommitted changes), fall through to the next remote.
  pull_ok=false
  for remote in "$chosen_remote" "${REMOTES[@]}"; do
    if ! git remote get-url "$remote" >/dev/null 2>&1; then
      continue
    fi
    if git fetch --quiet --tags "$remote" main && git merge --ff-only "$remote/main"; then
      pull_ok=true
      log "watchtower_pulled remote=$remote sha=$(git rev-parse --short HEAD)"
      break
    else
      log "watchtower_pull_failed remote=$remote"
    fi
  done

  if [ "$pull_ok" = false ]; then
    log "watchtower_pull_failed_all remotes=$REMOTES_CSV"
    exit 1
  fi
fi

# Restart-needed check: HEAD is what's currently checked out; LAST_RESTART_SHA
# is what's actually running in the pm2 process. If they differ — for ANY
# reason (this watchtower cycle pulled, OR an out-of-band pull moved HEAD) —
# restart. First-ever run (no state file) also triggers a restart so the
# state file gets seeded.
CURRENT_HEAD=$(git rev-parse HEAD)
if [ "$CURRENT_HEAD" != "$LAST_RESTART_SHA" ]; then
  log "head_changed last_restart=${LAST_RESTART_SHA:0:7} current=${CURRENT_HEAD:0:7} — restarting services"
  for svc in djinn-validator djinn-miner; do
    if pm2 describe "$svc" > /dev/null 2>&1; then
      log "Restarting $svc"
      pm2 restart "$svc" --update-env
    fi
  done
  echo "$CURRENT_HEAD" > "$LAST_RESTART_FILE"
  log "Done. Now at ${CURRENT_HEAD:0:7}"
else
  log "Done. No restart needed (running ${CURRENT_HEAD:0:7})"
fi
