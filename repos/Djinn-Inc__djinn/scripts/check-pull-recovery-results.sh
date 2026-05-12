#!/usr/bin/env bash
# Cross-validator pull-recovery diagnostic counters (v1701/v1702/v1703).
#
# Reads three Prometheus counters from each OV signer's /metrics endpoint:
#   djinn_validator_share_recovery_result_total       (v1701)
#   djinn_validator_purchase_odds_prefetch_result_total (v1702)
#   djinn_validator_outcome_recovery_result_total      (v1703)
#
# Each counter has bounded outcome labels that distinguish:
#   peer_404           — peer responded 404 (upstream gossip gap)
#   peer_unreachable   — httpx error (transport flake)
#   peer_status_4xx/5xx — non-200 non-404 from peer
#   recovered          — successful pull
#   no_peer_had_it     — exhausted peers, none had data
#   ... + per-counter specifics (root_mismatch, replay_disputed, etc)
#
# Use to localize WHICH layer of the recovery pipeline is failing.
# Dominant peer_404 across the fleet = upstream gossip is the gap.
# Dominant peer_unreachable = network/health issue.
# Dominant root_mismatch = peer adversarial / out-of-sync.
# Dominant replay_disputed = peer outcomes != local ESPN.
#
# Usage:
#   bash scripts/check-pull-recovery-results.sh
#
# Requires v1701+ (share recovery), v1702+ (BPA/WPA prefetch),
# v1703+ (outcome recovery) on validators. Older validators will
# show empty per-counter blocks.
set -uo pipefail

_PROTO="${DJINN_VALIDATOR_BASE:-https}"
declare -A VALIDATORS=(
  [0]="v0.djinn.gg"
  [1]="v1.djinn.gg"
  [2]="v2.djinn.gg"
  [86]="v86.djinn.gg"
  [213]="v213.djinn.gg"
)

probe_counter() {
  local body=$1 metric=$2
  # Print "outcome=count" for each label; skip empties so output stays terse.
  # Each line shape: djinn_validator_X{outcome="LABEL"} VALUE
  # awk split on [="}] yields 5 fields; F3 is the label, $NF is the count.
  echo "$body" | grep -E "^${metric}\{outcome=" \
    | awk -F'[="}]' '{printf "%s=%d ", $3, int($NF)}'
}

probe_push_counter() {
  local body=$1 path=$2
  # v1704 push counter has two labels: path + outcome; awk split is more
  # complex so use python for this one.
  echo "$body" | grep -E "^djinn_validator_gossip_push_result_total\{[^}]*path=\"${path}\"" \
    | python3 -c "
import sys, re
for line in sys.stdin:
    m = re.match(r'.*outcome=\"([^\"]+)\".* (\d+(?:\.\d+)?)', line)
    if m:
        print(f'{m.group(1)}={int(float(m.group(2)))}', end=' ')
"
}

probe_uid() {
  local uid=$1 host=${VALIDATORS[$1]}
  local body
  body=$(curl -sS -m 8 "${_PROTO}://${host}/metrics" 2>/dev/null || echo "")
  if [ -z "$body" ]; then
    echo "  UID $uid (${host}): unreachable"
    return
  fi

  local v
  v=$(curl -sS -m 4 "${_PROTO}://${host}/health" 2>/dev/null \
    | python3 -c "import sys,json;print(json.load(sys.stdin).get('version','?'))" 2>/dev/null)
  echo "  UID $uid (${host}, v${v}):"

  local share_line
  share_line=$(probe_counter "$body" "djinn_validator_share_recovery_result_total")
  echo "    share_recovery     (v1701 pull): ${share_line:-(no data)}"

  local prefetch_line
  prefetch_line=$(probe_counter "$body" "djinn_validator_purchase_odds_prefetch_result_total")
  echo "    bpa_wpa_prefetch   (v1702 pull): ${prefetch_line:-(no data)}"

  local outcome_line
  outcome_line=$(probe_counter "$body" "djinn_validator_outcome_recovery_result_total")
  echo "    outcome_recovery   (v1703 pull): ${outcome_line:-(no data)}"

  local push_po_line
  push_po_line=$(probe_push_counter "$body" "purchase_odds")
  echo "    bpa_wpa_gossip     (v1704 push): ${push_po_line:-(no data)}"

  local push_oc_line
  push_oc_line=$(probe_push_counter "$body" "outcomes")
  echo "    outcome_gossip     (v1704 push): ${push_oc_line:-(no data)}"

  local bundle_line
  bundle_line=$(probe_counter "$body" "djinn_validator_bundle_store_result_total")
  echo "    bundle_store      (v1705 recv): ${bundle_line:-(no data)}"

  local settle_abstain_line
  settle_abstain_line=$(echo "$body" | grep -E "^djinn_validator_settle_abstain_reason_total\{reason=" \
    | awk -F'[="}]' '{printf "%s=%d ", $3, int($NF)}')
  echo "    v1_settle_abstain (v1706 v1):   ${settle_abstain_line:-(no data)}"

  local recv_po_line
  recv_po_line=$(probe_push_counter "$body" "purchase_odds" \
    | sed 's/djinn_validator_gossip_push_result_total/djinn_validator_gossip_receive_result_total/g' 2>/dev/null \
    || true)
  recv_po_line=$(echo "$body" | grep -E "^djinn_validator_gossip_receive_result_total\{[^}]*path=\"purchase_odds\"" \
    | python3 -c "
import sys, re
for line in sys.stdin:
    m = re.match(r'.*outcome=\"([^\"]+)\".* (\d+(?:\.\d+)?)', line)
    if m:
        print(f'{m.group(1)}={int(float(m.group(2)))}', end=' ')
")
  echo "    bpa_wpa_recv      (v1707 recv): ${recv_po_line:-(no data)}"

  local recv_oc_line
  recv_oc_line=$(echo "$body" | grep -E "^djinn_validator_gossip_receive_result_total\{[^}]*path=\"outcomes\"" \
    | python3 -c "
import sys, re
for line in sys.stdin:
    m = re.match(r'.*outcome=\"([^\"]+)\".* (\d+(?:\.\d+)?)', line)
    if m:
        print(f'{m.group(1)}={int(float(m.group(2)))}', end=' ')
")
  echo "    outcome_recv      (v1707 recv): ${recv_oc_line:-(no data)}"

  local resolve_line
  resolve_line=$(probe_counter "$body" "djinn_validator_resolve_signal_result_total")
  echo "    resolve_signal    (v1707 espn): ${resolve_line:-(no data)}"
}

echo "=== Cross-validator pull-recovery counters (v1701/v1702/v1703) ==="
echo ""
echo "Dominant outcome guides remediation:"
echo "  peer_404 dominant      -> upstream gossip is the gap (missing bundle/gossip delivery)"
echo "  peer_unreachable       -> transport/network or peer health"
echo "  root_mismatch          -> peer adversarial or out-of-sync (BPA/WPA only)"
echo "  replay_disputed        -> peer outcomes diverge from ESPN (outcomes only)"
echo "  replay_pending_local   -> our own ESPN says game still in progress (outcomes only)"
echo "  recovered              -> recovery is working; pipeline is healthy"
echo ""
for uid in 0 1 2 86 213; do
  probe_uid "$uid"
  echo ""
done
