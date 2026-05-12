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

echo "▶ Starting validator with:"
echo "   WALLET_NAME=$WALLET_NAME"
echo "   HOTKEY_NAME=$HOTKEY_NAME"

exec python3 neurons/validator.py \
    --netuid 92 \
    --wallet.name "$WALLET_NAME" \
    --wallet.hotkey "$HOTKEY_NAME" \
    --subtensor.network finney \
    --axon.port 19292 \
    "$log_flag" \
    "$@"
