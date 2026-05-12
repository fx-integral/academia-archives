#!/usr/bin/env bash
# Cross-validator settlement-readiness diagnostic.
#
# For a given (genius, idiot) pair OR all (G0, *) pairs, query each OV signer's
# /v1/audit/{g}/{i}/detail endpoint and produce a readiness table:
#   pair → UID → signals_count / outcomes_resolved / has_local_share
#
# Quorum-readiness rule: a pair is "naturally settleable" when >= quorumThreshold
# (4 of 5 today) validators have full data (signals == resolved == has_share).
#
# Usage:
#   bash scripts/check-settlement-readiness.sh                      # check all (G0, *)
#   bash scripts/check-settlement-readiness.sh <genius> <idiot>     # single pair
#
# 2026-05-03: built when stress-scale + EarlyExitRequested verification surfaced
# the per-validator readiness gap (P1-33 BPA/WPA, P1-34 bootstrap latency).
set -euo pipefail

# v1698: route via wildcard DNS (v$UID.djinn.gg) instead of hardcoded IPs.
# nginx wildcard router on bootstrap proxies to current axon IP.
_PROTO="${DJINN_VALIDATOR_BASE:-https}"
declare -A VALIDATORS=(
  [0]="v0.djinn.gg"
  [1]="v1.djinn.gg"
  [2]="v2.djinn.gg"
  [86]="v86.djinn.gg"
  [213]="v213.djinn.gg"
)

QUORUM_THRESHOLD=4
G0=0x68fc8eec9e5551d4c93a89b6d861f0a05e0a2a1d

probe_pair() {
  local genius=$1 idiot=$2
  local row="${idiot:0:10}"
  local ready_count=0
  for uid in 0 1 2 86 213; do
    local ip=${VALIDATORS[$uid]}
    local r=$(curl -s -m 5 "${_PROTO}://${ip}/v1/audit/${genius}/${idiot}/detail" 2>/dev/null | python3 -c "
import sys, json
try:
  d=json.load(sys.stdin)
  sigs=d.get('signals',[])
  s=sum(1 for x in sigs if x.get('has_local_share'))
  r=sum(1 for x in sigs if x.get('outcomes_resolved'))
  b=sum(1 for x in sigs if x.get('has_bpa_wpa'))
  total=len(sigs)
  # 'full' = build_pi will succeed for all signals: signals == resolved == has_share == has_bpa_wpa
  # If has_bpa_wpa missing from response (older validator), don't enforce.
  has_bpa_field = total > 0 and 'has_bpa_wpa' in sigs[0]
  full = total>0 and s==total and r==total and (b==total if has_bpa_field else True)
  if has_bpa_field:
    print(f\"{total}/{r}/{s}/{b}\", 'F' if full else '.')
  else:
    print(f\"{total}/{r}/{s}\", 'F' if full else '.')
except: print('-/-/-', '.')
" 2>/dev/null)
    local count=${r% *}
    local full=${r##* }
    if [ "$full" = "F" ]; then
      ready_count=$((ready_count + 1))
      row="${row}  UID${uid}:${count}*"
    else
      row="${row}  UID${uid}:${count} "
    fi
  done
  local status=""
  if [ $ready_count -ge $QUORUM_THRESHOLD ]; then
    status="QUORUM-READY (${ready_count}/5)"
  elif [ $ready_count -gt 0 ]; then
    status="partial (${ready_count}/5)"
  fi
  echo "${row}  -> ${status}"
}

# Discover all (G0, idiot) pairs from the most-current validator (UID 213).
discover_pairs() {
  local genius=$1
  # The /v1/audit/summary endpoint reports counts but not pair list.
  # We probe a known-superset address discovery via UID 213's likely-fullest view.
  # As a fallback, accept idiot list from stdin or the second positional arg.
  echo "Pair discovery via per-validator audit detail endpoint not directly available;"
  echo "supply (genius, idiot) pairs explicitly via positional args or one per line on stdin."
  return 1
}

if [ $# -eq 2 ]; then
  echo "=== Single pair check ==="
  echo "Cell format: signals/resolved/has_share/has_bpa_wpa. '*' = full data on this validator."
  echo "Quorum threshold: ${QUORUM_THRESHOLD} of 5"
  echo
  probe_pair "$1" "$2"
elif [ $# -eq 0 ]; then
  echo "=== Cross-validator readiness for (G0, *) pairs ==="
  echo "Cell format: signals/resolved/has_share/has_bpa_wpa (older validators omit BPA). '*' = full data on this validator."
  echo "Quorum threshold: ${QUORUM_THRESHOLD} of 5"
  echo
  echo "Pass idiot addresses on stdin (one per line) to check each pair:"
  echo "  echo 0xIDIOT1 0xIDIOT2 | tr ' ' '\\n' | bash $0"
  echo
  while IFS= read -r idiot; do
    [ -z "$idiot" ] && continue
    probe_pair "$G0" "$idiot"
  done
else
  echo "Usage: $0 [<genius> <idiot>]" >&2
  echo "  No args: read idiot addresses from stdin (one per line, genius=G0)" >&2
  echo "  Two args: probe a single (genius, idiot) pair" >&2
  exit 1
fi
