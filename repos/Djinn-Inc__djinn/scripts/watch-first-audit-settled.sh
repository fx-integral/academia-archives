#!/usr/bin/env bash
# Cron-driven poller: alerts via Telegram the first time a NATURAL-QUORUM
# AuditSettled fires on Base Sepolia (i.e. via OV.submitVote → quorum →
# Audit.earlyExitByVote/settleByVote, NOT via owner Audit.forceSettle).
# Self-disables after first hit.
#
# Distinguishing signal: QuorumReached event (only emitted on natural
# quorum, never on forceSettle). The prior state file
# /tmp/first-audit-settled-seen disabled this on the 2026-04-26 forceSettle
# drill; v1672+v1673+v1674 fix the silent NameError/TypeError chain blocking
# natural settlement, so we now want the FIRST quorum-driven event to fire
# the alert.
#
# State file at /tmp/first-natural-quorum-seen — if it exists, exit silently.
set -euo pipefail

STATE=/tmp/first-natural-quorum-seen
[ -f "$STATE" ] && exit 0

export PATH=$PATH:/home/user/.foundry/bin
source /home/user/djinn/contracts/.env 2>/dev/null

AUDIT=0xCa7e642FE31BA83a7a857644E8894c1B93a2a44E
OV=0xAD534f4CAB13707BD4d65e4EF086A455e6A643e5
# Starting block: just after v1674 deployment (block 41018046; first
# natural quorum we care about must occur after the fleet rolls v1674).
FROM=${WATCH_FROM_BLOCK:-41018046}
# 2026-05-03 RPC-indexing-divergence fix: scan BOTH publicnode and sepolia.base.org
# and union via tx hash. Both RPCs have inconsistent log indexing (publicnode
# missed UID 213's first VoteSubmitted at block 41020829; sepolia.base.org caught
# it). Union eliminates single-RPC blind spots. Per feedback_base_sepolia_rpc_logs_broken
# we know sepolia.base.org silently 0s sometimes; union guarantees we see every event
# at least one RPC indexes.
RPC_PRIMARY=${BASE_SEPOLIA_RPC_URL:-https://base-sepolia-rpc.publicnode.com}
RPC_FALLBACK=https://sepolia.base.org
# Use the highest block seen across both RPCs.
TO_PRIMARY=$(cast block-number --rpc-url "$RPC_PRIMARY" 2>/dev/null || echo 0)
TO_FALLBACK=$(cast block-number --rpc-url "$RPC_FALLBACK" 2>/dev/null || echo 0)
TO=$TO_PRIMARY
[ "$TO_FALLBACK" -gt "$TO" ] 2>/dev/null && TO=$TO_FALLBACK
[ "$TO" -le "$FROM" ] && exit 0

QUORUM_TOPIC=$(cast keccak "QuorumReached(address,address,uint256,int256,uint256,uint256)")
VOTE_TOPIC=$(cast keccak "VoteSubmitted(address,address,uint256,address,int256)")

# Collect all transaction hashes for QuorumReached events across both RPCs.
# Bash sets via associative arrays.
declare -A QUORUM_TXS
declare -A AUDIT_TXS
declare -A VOTE_TXS

scan_rpc() {
  local rpc=$1
  local CURSOR=$FROM
  while [ "$CURSOR" -le "$TO" ]; do
    local END=$((CURSOR + 9999))
    [ "$END" -gt "$TO" ] && END=$TO
    # Collect tx hashes with each event type. We dedup via the associative array.
    while IFS= read -r tx; do
      [ -n "$tx" ] && AUDIT_TXS["$tx"]=1
    done < <(cast logs --from-block "$CURSOR" --to-block "$END" --address "$AUDIT" --rpc-url "$rpc" 2>/dev/null | awk '/transactionHash:/{print $2}')
    while IFS= read -r tx; do
      [ -n "$tx" ] && QUORUM_TXS["$tx"]=1
    done < <(cast logs --from-block "$CURSOR" --to-block "$END" --address "$OV" --rpc-url "$rpc" 2>/dev/null | awk -v t="$QUORUM_TOPIC" 'BEGIN{want=0} /^\s+'$QUORUM_TOPIC'/{want=1} /transactionHash:/{if(want){print $2; want=0}}')
    while IFS= read -r tx; do
      [ -n "$tx" ] && VOTE_TXS["$tx"]=1
    done < <(cast logs --from-block "$CURSOR" --to-block "$END" --address "$OV" --rpc-url "$rpc" 2>/dev/null | awk -v t="$VOTE_TOPIC" 'BEGIN{want=0} /^\s+'$VOTE_TOPIC'/{want=1} /transactionHash:/{if(want){print $2; want=0}}')
    CURSOR=$((END + 1))
  done
}

scan_rpc "$RPC_PRIMARY" 2>/dev/null || true
scan_rpc "$RPC_FALLBACK" 2>/dev/null || true

# `set -u` errors on `${#empty_assoc[@]}`. Drop strict-undef just for these.
set +u
QUORUM_COUNT=${#QUORUM_TXS[@]}
AUDIT_COUNT=${#AUDIT_TXS[@]}
VOTE_COUNT=${#VOTE_TXS[@]}
set -u

if [ "$QUORUM_COUNT" -gt 0 ]; then
  MSG="🎉 FIRST natural-quorum AuditSettled on Base Sepolia post-v1674! blocks $FROM..$TO: $QUORUM_COUNT QuorumReached + $AUDIT_COUNT Audit event(s) + $VOTE_COUNT VoteSubmitted (deduped across both RPCs). P0-01 pipeline validated end-to-end."
  TELEGRAM_CHAT_ID=1530623518 python3 /home/user/telegram-bot/send.py "$MSG" 2>&1 | tail -2
  touch "$STATE"
elif [ "$VOTE_COUNT" -gt 0 ]; then
  # Pre-quorum signal: at least one vote has fired post-v1674. Useful for
  # day-to-day diagnostics without spamming Telegram on every vote.
  echo "[$(date -u +%H:%M:%S)] $VOTE_COUNT VoteSubmitted across blocks $FROM..$TO; quorum still pending."
fi
