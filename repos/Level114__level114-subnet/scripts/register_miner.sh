#!/bin/bash

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MINER_CALLER_NAME="$(basename "$0")" "$SCRIPT_DIR/miner_action.sh" register "$@"
