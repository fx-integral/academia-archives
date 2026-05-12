#!/bin/bash
set -e

required_vars=("WALLET_NAME" "HOTKEY_NAME")
for var in "${required_vars[@]}"; do
    if [ -z "${!var}" ]; then
        echo "❌ Error: Required environment variable '$var' is not set."
        exit 1
    fi
done

log_flag="--logging.debug"

echo "▶ Starting miner with:"
echo "   WALLET_NAME=$WALLET_NAME"
echo "   HOTKEY_NAME=$HOTKEY_NAME"

EIP=$(curl -s eth0.me)

exec python3 neurons/miner.py \
    --netuid 92 \
    --wallet.name "$WALLET_NAME" \
    --wallet.hotkey "$HOTKEY_NAME" \
    --subtensor.network finney \
    --axon.port 9292 \
    --axon.external_ip $EIP \
    --axon.external_port 9292 \
    "$log_flag" \
    "$@"