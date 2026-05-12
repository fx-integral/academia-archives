#!/usr/bin/env bash
# Cross-validator SHADOW_SETTLE_STAGE diagnostic (v1686+).
#
# Reads Prometheus counters from each OV signer's /metrics endpoint and
# prints stage progression per validator. Reveals which stage of
# try_shadow_distributed_settlement each validator hangs in.
#
# Stage order:
#   pre_recovery -> post_bpa_wpa -> post_outcome_recv -> post_recovery
#     -> pre_build_pi -> post_build_pi -> pre_resolve_peers
#     -> post_resolve_peers -> pre_run_mpc -> post_run_mpc
#
# A stage with a HIGHER count than its successor means N attempts are
# blocked between those two stages. The largest gap localizes the hang.
#
# Outcome distribution shows which abstain branches dominate. Look for:
#   abstain_no_batch         -> validator missing local share/BPA/outcome data
#   abstain_subset_divergence -> local PIDs diverge from chain canonical
#   abstain_pregate_min_batch -> local batch < MIN with no consent/timeout
#   protocol_failed          -> MPC threw an exception
#   completed                -> got past MPC; check vote_submit counters
#
# Usage:
#   bash scripts/check-shadow-stage-progress.sh
#
# Requires v1686+ on validators (older respond with empty stage block).
set -uo pipefail
# No `set -e` because the bash arithmetic test `[ "$n" -gt 0 ]` returns
# exit 1 when n=0, which would abort the loop under errexit.

# v1698: use wildcard DNS (v$UID.djinn.gg) routed by nginx wildcard router
# instead of hardcoded IPs. Eliminates per-IP-migration code churn — when a
# validator's box moves, only Namecheap DNS + nginx routing-map need update.
# Hostname → port comes from /etc/nginx/conf.d/uid-routing-map.conf on the
# bootstrap validator. The router proxies to the actual axon over HTTP.
# Set DJINN_VALIDATOR_BASE=http to use plain HTTP (default), or
# DJINN_VALIDATOR_BASE=https to go through the nginx + LE TLS path.
_PROTO="${DJINN_VALIDATOR_BASE:-https}"
declare -A VALIDATORS=(
  [0]="v0.djinn.gg"
  [1]="v1.djinn.gg"
  [2]="v2.djinn.gg"
  [86]="v86.djinn.gg"
  [213]="v213.djinn.gg"
)

STAGES=(
  "pre_recovery"
  "post_bpa_wpa"
  "post_outcome_recv"
  "post_recovery"
  "pre_build_pi"
  "post_build_pi"
  "post_canonical_pid"
  "post_postbuild_pregate"
  "pre_resolve_peers"
  "post_resolve_peers"
  "pre_run_mpc"
  "post_run_mpc"
)

OUTCOMES=(
  "attempt"
  "abstain_no_batch"
  "abstain_no_share"
  "abstain_no_peers"
  "abstain_below_threshold"
  "abstain_subset_divergence"
  "abstain_pregate_min_batch"
  "abstain_no_self_url"
  "protocol_failed"
  "quality_score_out_of_range"
  "completed"
)

VOTE_OUTCOMES=(
  "attempted"
  "submitted"
  "confirmed"
  "reverted"
  "receipt_timeout"
  "already_voted"
  "cycle_finalized"
  "network_error"
  "pregate_skip"
  "preflight_finalized"
  "preflight_already_voted"
  "skipped_flag_off"
  "skipped_no_chain_client"
  "skipped_no_write"
)

extract_metric() {
  local body=$1 metric=$2 label=$3
  echo "$body" | grep -E "^${metric}\{outcome|^${metric}\{stage" | awk -F'[="}]' -v t="$label" '$3==t {print int($6); exit}'
}

probe_uid() {
  local uid=$1 ip=${VALIDATORS[$1]}
  local body
  body=$(curl -sS -m 6 "${_PROTO}://${ip}/metrics" 2>/dev/null || echo "")
  if [ -z "$body" ]; then
    echo "  UID $uid (${ip}): unreachable"
    return
  fi

  local v
  v=$(curl -sS -m 4 "${_PROTO}://${ip}/health" 2>/dev/null | python3 -c "import sys,json;print(json.load(sys.stdin).get('version','?'))" 2>/dev/null)
  echo "  UID $uid (${ip}, v${v}):"

  echo -n "    stages: "
  for s in "${STAGES[@]}"; do
    n=$(echo "$body" | grep -E "^djinn_validator_shadow_settle_stages_total\{stage=\"${s}\"\}" | awk '{print int($2)}')
    [ -z "$n" ] && n=0
    printf "%s=%d " "$s" "$n"
  done
  echo ""

  echo -n "    outcomes: "
  for o in "${OUTCOMES[@]}"; do
    n=$(echo "$body" | grep -E "^djinn_validator_shadow_settle_outcomes_total\{outcome=\"${o}\"\}" | awk '{print int($2)}')
    [ -z "$n" ] && n=0
    [ "$n" -gt 0 ] && printf "%s=%d " "$o" "$n"
  done
  echo ""

  echo -n "    votes: "
  for vo in "${VOTE_OUTCOMES[@]}"; do
    n=$(echo "$body" | grep -E "^djinn_validator_vote_submit_outcomes_total\{outcome=\"${vo}\"\}" | awk '{print int($2)}')
    [ -z "$n" ] && n=0
    [ "$n" -gt 0 ] && printf "%s=%d " "$vo" "$n"
  done
  echo ""
}

echo "=== Cross-validator SHADOW_SETTLE_STAGE + outcomes (v1686+) ==="
echo "Compare adjacent stage counts: a high pre_X with low post_X means N attempts hung at that step."
echo ""
for uid in 0 1 2 86 213; do
  probe_uid "$uid"
  echo ""
done
