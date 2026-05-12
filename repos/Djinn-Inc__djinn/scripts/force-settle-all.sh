#!/bin/bash
# scripts/force-settle-all.sh
#
# Owner-only routine settlement: discover every (g, i) pair with pending
# purchases on Account, schedule + execute Audit.forceSettle for each.
#
# This is the brutal-pragmatic alternative to multi-validator MPC quorum:
# the deployer reads on-chain state directly and writes settlement
# results, sidestepping the Layer-2 batchKey divergence problem. The
# 2026-05-03 drill (tx 0x6a2d25fe...e6016ca) proved the path works for
# a single batch; this script does it for every pair.
#
# Trade-off: centralized at the owner. Acceptable as a routine path on
# Base Sepolia testnet while the multi-validator quorum protocol is
# stabilized. The contract path stays unchanged (forceSettle was already
# owner-only emergency settlement); we're just running it routinely.
#
# Usage:
#   DEPLOYER_KEY=0x... BASE_RPC_URL=https://sepolia.base.org \
#     ./scripts/force-settle-all.sh
#
# Optional env:
#   QUALITY_SCORE     — default 0 (neutral, no economic settlement).
#                       Pass a real score to deliver economic settlement.
#                       For correct economic settlement, run
#                       force-settle-with-scores.sh instead, which queries
#                       Audit.computeScore() per pair.
#   FROM_BLOCK        — default LATEST-100000 (~14 days back on Base).
#   DRY_RUN           — set to 1 to print pairs but not submit txs.
#   PAIR_FILTER       — 'genius:0xABC...' or 'idiot:0xABC...' to limit to
#                       pairs containing the given address.
#   PER_PAIR_DELAY_S  — default 80 (= 72s timelock + 8s buffer). Lower if
#                       timelock is reduced.
#
# Exit codes:
#   0  — all pairs processed (some may have skipped if no pending)
#   1  — fatal error (missing env, RPC failure)

set -e -o pipefail

ACCOUNT=0x4546354Dd32a613B76Abf530F81c8359e7cE440B
RPC_URL="${BASE_RPC_URL:-https://sepolia.base.org}"
QUALITY_SCORE="${QUALITY_SCORE:-0}"
PER_PAIR_DELAY_S="${PER_PAIR_DELAY_S:-80}"

if [ -z "${DEPLOYER_KEY:-}" ] && [ -z "${DRY_RUN:-}" ]; then
    echo "FATAL: DEPLOYER_KEY env required (or set DRY_RUN=1)" >&2
    exit 1
fi

if ! command -v cast >/dev/null 2>&1; then
    echo "FATAL: cast not found in PATH (foundry)" >&2
    exit 1
fi

if ! command -v forge >/dev/null 2>&1; then
    echo "FATAL: forge not found in PATH (foundry)" >&2
    exit 1
fi

cd "$(dirname "$0")/.."

LATEST=$(cast block-number --rpc-url "$RPC_URL")
FROM_BLOCK="${FROM_BLOCK:-$((LATEST - 100000))}"

echo "scanning PurchaseRecorded on $ACCOUNT, blocks $FROM_BLOCK..$LATEST"

# Use cast logs with the event signature; it returns one log per line in JSON.
# Topic[0] = event sig; topic[1] = genius (indexed); topic[2] = idiot (indexed).
LOGS=$(cast logs \
    --rpc-url "$RPC_URL" \
    --from-block "$FROM_BLOCK" \
    --to-block "$LATEST" \
    --address "$ACCOUNT" \
    "PurchaseRecorded(address,address,uint256,uint256)" \
    --json 2>/dev/null || echo "[]")

if [ "$LOGS" = "[]" ] || [ -z "$LOGS" ]; then
    echo "no PurchaseRecorded events in window — nothing to settle"
    exit 0
fi

# Extract unique (genius, idiot) pairs. cast logs returns padded 32-byte
# topics, so strip the leading 24 bytes of zeros to recover the address.
PAIRS=$(echo "$LOGS" | jq -r '.[] | "\(.topics[1])|\(.topics[2])"' | \
    awk -F'|' '{
        g = "0x" substr($1, 27);
        i = "0x" substr($2, 27);
        print g "|" i
    }' | sort -u)

PAIR_COUNT=$(echo "$PAIRS" | wc -l)
echo "found $PAIR_COUNT unique (genius, idiot) pairs"

# Filter if PAIR_FILTER is set.
if [ -n "${PAIR_FILTER:-}" ]; then
    KIND="${PAIR_FILTER%%:*}"  # genius | idiot
    ADDR="${PAIR_FILTER##*:}"
    ADDR_LOWER=$(echo "$ADDR" | tr A-F a-f)
    if [ "$KIND" = "genius" ]; then
        PAIRS=$(echo "$PAIRS" | awk -F'|' -v g="$ADDR_LOWER" '
            { gl = tolower($1); if (gl == g) print $0 }')
    elif [ "$KIND" = "idiot" ]; then
        PAIRS=$(echo "$PAIRS" | awk -F'|' -v i="$ADDR_LOWER" '
            { il = tolower($2); if (il == i) print $0 }')
    fi
fi

processed=0
skipped=0
settled=0
errors=0

for pair in $PAIRS; do
    g=$(echo "$pair" | cut -d'|' -f1)
    i=$(echo "$pair" | cut -d'|' -f2)
    processed=$((processed + 1))

    # Read current cycle's pids.
    PIDS_RAW=$(cast call --rpc-url "$RPC_URL" "$ACCOUNT" \
        "getPairPurchaseIds(address,address)(uint256[])" "$g" "$i" 2>/dev/null || echo "")

    if [ -z "$PIDS_RAW" ] || [ "$PIDS_RAW" = "[]" ]; then
        echo "  [skip] $g / $i — empty pids (already settled this cycle)"
        skipped=$((skipped + 1))
        continue
    fi

    PID_COUNT=$(echo "$PIDS_RAW" | tr -d '[]' | tr ',' '\n' | grep -v '^$' | wc -l)
    if [ "$PID_COUNT" -eq 0 ]; then
        echo "  [skip] $g / $i — no pids"
        skipped=$((skipped + 1))
        continue
    fi

    if [ -n "${DRY_RUN:-}" ]; then
        echo "  [dry-run] $g / $i — would force-settle $PID_COUNT purchase(s) at score=$QUALITY_SCORE"
        continue
    fi

    echo "  [run] $g / $i — $PID_COUNT purchase(s), score=$QUALITY_SCORE"

    # Phase 1: schedule via timelock.
    if ! GENIUS="$g" IDIOT="$i" PHASE=schedule QUALITY_SCORE="$QUALITY_SCORE" \
            forge script contracts/script/ForceSettleNew.s.sol \
            --rpc-url "$RPC_URL" --broadcast --silent 2>&1 | grep -E "scheduled|error" >&2; then
        echo "    [error] schedule failed — pair likely already scheduled or invalid; skipping"
        errors=$((errors + 1))
        continue
    fi

    # Wait for the timelock min-delay window to open.
    sleep "$PER_PAIR_DELAY_S"

    # Phase 2: execute.
    if GENIUS="$g" IDIOT="$i" PHASE=execute QUALITY_SCORE="$QUALITY_SCORE" \
            forge script contracts/script/ForceSettleNew.s.sol \
            --rpc-url "$RPC_URL" --broadcast --silent 2>&1 | grep -E "executed|error" >&2; then
        echo "    [ok] settled $g / $i"
        settled=$((settled + 1))
    else
        echo "    [error] execute failed for $g / $i"
        errors=$((errors + 1))
    fi
done

echo ""
echo "summary: processed=$processed settled=$settled skipped=$skipped errors=$errors"
exit 0
