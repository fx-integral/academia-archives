#!/usr/bin/env bash
# Counts each silent-skip log_key on UID 0 over a rolling window.
# Mirrors docs/runbooks/audit-no-vote-decision-tree.md.
#
# Usage:
#   audit-skip-counts.sh [LINES]
#
# LINES is the pm2 log line count to scan (default 5000).
# Output: TSV with [count, log_key] sorted desc. Top entries are your
# active failure modes RIGHT NOW.

set -euo pipefail

LINES="${1:-5000}"
JUMP="${JUMP_HOST:-161.97.138.250}"
HOST="${VALIDATOR_HOST:-v0.djinn.gg}"

KEYS=(
  build_pi_abstain_missing_outcomes
  build_pi_abstain_missing_share
  build_pi_abstain_no_ledger
  build_pi_abstain_missing_bpa_wpa
  build_pi_vector_length_mismatch
  settle_abstain_missing_outcomes
  settle_abstain_no_shares
  settle_abstain_no_index_shares
  settle_abstain_outcome_selection_failed
  audit_set_no_settable_signals
  audit_record_outcomes_unknown_signal
  shadow_settle_no_batch
  shadow_settle_no_quorum
  shadow_settle_no_local_share
  shadow_settle_no_self_url
  shadow_settle_participant_count_below_threshold
  shadow_settle_protocol_failed
  shadow_settle_score_out_of_range
  shadow_settle_submit_shape_failed
  batch_participants_no_peers
  batch_participants_below_threshold
  batch_participant_xs_inconsistent
  purchase_odds_prefetch_root_rpc_failed
  purchase_odds_prefetch_skip_legacy
  purchase_odds_prefetch_root_mismatch
  settlement_skipped_no_batch_result
  submit_from_shadow_already_voted_awaiting_quorum
  submit_from_shadow_preflight_skip
  submit_from_shadow_reverted
  submit_from_shadow_receipt_timeout
  submit_from_shadow_failed
  skip_settle_below_min_batch_no_request_no_timeout
  skip_audit_vote_below_min_batch_no_request_no_timeout
  audit_vote_preflight_skip
  audit_vote_already_cast_awaiting_quorum
  audit_vote_already_cast_race
  audit_vote_skipped_finalized
  audit_vote_failed
  audit_vote_receipt_timeout
  audit_vote_reverted
  audit_vote_skipped_no_writer
)

REGEX="$(IFS='|'; echo "${KEYS[*]}")"

echo "scanning ${LINES} log lines on UID 0 (${HOST})..."
LOGS=$(ssh -J "root@${JUMP}" -o StrictHostKeyChecking=no -o ConnectTimeout=10 \
  "root@${HOST}" \
  "pm2 logs djinn-validator --lines ${LINES} --nostream 2>&1 | grep -oE '(${REGEX})'" \
  2>/dev/null)

if [ -z "$LOGS" ]; then
  echo "(no skip events in last ${LINES} lines — pipeline may be quiescent or fully healthy)"
  exit 0
fi

echo
echo "count	log_key"
echo "$LOGS" | sort | uniq -c | sort -rn | awk '{printf "%d\t%s\n", $1, $2}'
echo
echo "see docs/runbooks/audit-no-vote-decision-tree.md for what each key means + fix owner"
