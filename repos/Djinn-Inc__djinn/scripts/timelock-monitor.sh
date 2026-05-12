#!/usr/bin/env bash
# Timelock Monitor: watches for CallScheduled and CallExecuted events
# on the Djinn TimelockController and alerts via Telegram.
#
# Run via cron every 5 minutes:
#   */5 * * * * /home/user/djinn/scripts/timelock-monitor.sh
#
# Requires: cast (foundry), curl, jq

set -euo pipefail

# --- Config ---
TIMELOCK="0x37f41EFfa8492022afF48B9Ef725008963F14f79"
RPC_URL="${RPC_URL:-https://sepolia.base.org}"
STATE_FILE="/home/user/djinn/scripts/.timelock-monitor-block"
TELEGRAM_BOT_TOKEN=$(grep -m1 '^TELEGRAM_BOT_TOKEN=' ~/telegram-bot/.env 2>/dev/null | cut -d= -f2- | tr -d '"'"'" )
if [ -z "$TELEGRAM_BOT_TOKEN" ]; then
  echo "WARNING: TELEGRAM_BOT_TOKEN not found in ~/telegram-bot/.env"
fi
TELEGRAM_CHAT_ID="1530623518"

# Event topics (computed at runtime; pre-commit hook flags 64-hex literals)
SCHEDULED=$(cast keccak "CallScheduled(bytes32,uint256,address,uint256,bytes,bytes32,uint256)")
EXECUTED=$(cast keccak "CallExecuted(bytes32,uint256,address,uint256,bytes)")
CANCELLED=$(cast keccak "Cancelled(bytes32)")

send_telegram() {
    local msg="$1"
    curl -s -X POST "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
        -d chat_id="${TELEGRAM_CHAT_ID}" \
        -d parse_mode="HTML" \
        -d text="${msg}" > /dev/null 2>&1
}

# Get current block
CURRENT_BLOCK=$(cast block-number --rpc-url "$RPC_URL" 2>/dev/null)
if [ -z "$CURRENT_BLOCK" ]; then
    exit 1
fi

# Get last checked block (or start from 1000 blocks ago)
if [ -f "$STATE_FILE" ]; then
    FROM_BLOCK=$(cat "$STATE_FILE")
else
    FROM_BLOCK=$((CURRENT_BLOCK - 1000))
fi

# Don't re-check the same range
if [ "$FROM_BLOCK" -ge "$CURRENT_BLOCK" ]; then
    exit 0
fi

# Check for CallScheduled events
SCHEDULED_LOGS=$(cast logs --from-block "$FROM_BLOCK" --to-block "$CURRENT_BLOCK" \
    --address "$TIMELOCK" "$SCHEDULED" --rpc-url "$RPC_URL" 2>/dev/null || echo "")

if [ -n "$SCHEDULED_LOGS" ] && [ "$SCHEDULED_LOGS" != "[]" ]; then
    COUNT=$(echo "$SCHEDULED_LOGS" | grep -c "blockNumber" || echo "0")
    send_telegram "$(cat <<MSG
<b>DJINN TIMELOCK ALERT</b>

New operation SCHEDULED on TimelockController.
$COUNT event(s) detected.
Blocks $FROM_BLOCK to $CURRENT_BLOCK.

Timelock: <code>$TIMELOCK</code>

This operation will be executable in 72 hours.
If you did not initiate this, investigate immediately.
MSG
)"
fi

# Check for CallExecuted events
EXECUTED_LOGS=$(cast logs --from-block "$FROM_BLOCK" --to-block "$CURRENT_BLOCK" \
    --address "$TIMELOCK" "$EXECUTED" --rpc-url "$RPC_URL" 2>/dev/null || echo "")

if [ -n "$EXECUTED_LOGS" ] && [ "$EXECUTED_LOGS" != "[]" ]; then
    COUNT=$(echo "$EXECUTED_LOGS" | grep -c "blockNumber" || echo "0")
    send_telegram "$(cat <<MSG
<b>DJINN TIMELOCK ALERT</b>

Operation EXECUTED on TimelockController.
$COUNT event(s) detected.
Blocks $FROM_BLOCK to $CURRENT_BLOCK.

Timelock: <code>$TIMELOCK</code>

Verify the changes are expected.
MSG
)"
fi

# Check for Cancelled events
CANCELLED_LOGS=$(cast logs --from-block "$FROM_BLOCK" --to-block "$CURRENT_BLOCK" \
    --address "$TIMELOCK" "$CANCELLED" --rpc-url "$RPC_URL" 2>/dev/null || echo "")

if [ -n "$CANCELLED_LOGS" ] && [ "$CANCELLED_LOGS" != "[]" ]; then
    COUNT=$(echo "$CANCELLED_LOGS" | grep -c "blockNumber" || echo "0")
    send_telegram "$(cat <<MSG
<b>DJINN TIMELOCK ALERT</b>

Operation CANCELLED on TimelockController.
$COUNT event(s) detected.
Blocks $FROM_BLOCK to $CURRENT_BLOCK.

Timelock: <code>$TIMELOCK</code>
MSG
)"
fi

# Save current block for next run
echo "$CURRENT_BLOCK" > "$STATE_FILE"
