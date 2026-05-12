#!/bin/bash

set -e

REPO_URL="https://github.com/Rich-Kids-of-TAO/rkt-subnet"
BRANCH="master"
CHECK_INTERVAL=1800

if [ $# -lt 3 ]; then
    echo "Usage: $0 [netuid] [wallet_name] [wallet_hotkey]"
    echo "Example: $0 110 my-validator default"
    exit 1
fi

NETUID="$1"
WALLET_NAME="$2"
WALLET_HOTKEY="$3"

echo "Starting Rich Kids of TAO auto-updater"
echo "NETUID: $NETUID"
echo "WALLET_NAME: $WALLET_NAME"
echo "WALLET_HOTKEY: $WALLET_HOTKEY"

echo "Initial setup - installing dependencies..."
pip install -e .

stop_validator() {
    echo "Stopping validator..."
    pm2 delete rich-kids-validator 2>/dev/null || true
}

start_validator() {
    echo "Starting validator..."
    pm2 start "python validator.py --netuid $NETUID --wallet.name $WALLET_NAME --wallet.hotkey $WALLET_HOTKEY --logging.debug" --name rich-kids-validator
    echo "Validator started"
}

while true; do
    echo "Checking for updates..."
    git fetch origin "$BRANCH"

    LOCAL_COMMIT=$(git rev-parse HEAD)
    REMOTE_COMMIT=$(git rev-parse "origin/$BRANCH")

    if [ "$LOCAL_COMMIT" = "$REMOTE_COMMIT" ]; then
        echo "No updates. Checking if validator is running..."
        if ! pm2 list | grep -q "rich-kids-validator.*online"; then
            echo "Validator not running or crashed, starting..."
            stop_validator
            start_validator
        else
            echo "Validator running. Nothing to do."
        fi
    else
        echo "Updates found! Updating..."
        stop_validator
        git pull origin "$BRANCH"
        pip install -e .
        start_validator
        pm2 save
        echo "Update complete"
    fi

    echo "Sleeping for $CHECK_INTERVAL seconds..."
    sleep "$CHECK_INTERVAL"
done
