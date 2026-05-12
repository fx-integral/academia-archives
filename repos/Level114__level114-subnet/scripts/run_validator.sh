#!/bin/bash

# Level114 Subnet Validator Runner Script

set -euo pipefail

# Resolve project root (directory of this script's parent)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "$PROJECT_ROOT"

# Defaults
NETUID=114
NETWORK=finney
WALLET_NAME=default
WALLET_HOTKEY=default
SAMPLE_SIZE=10
LOG_LEVEL=INFO
COLLECTOR_URL="https://collector.level114.io"
COLLECTOR_TIMEOUT=10.0
COLLECTOR_API_KEY=""
COLLECTOR_REPORTS_LIMIT=25
WEIGHT_UPDATE_INTERVAL=1200
VALIDATION_INTERVAL=1440

# Collect extra/unknown args to forward to Python
EXTRA_ARGS=()

# Parse args
while [[ $# -gt 0 ]]; do
  case "$1" in
    --netuid) NETUID="$2"; shift 2;;
    --network) NETWORK="$2"; shift 2;;
    --wallet.name) WALLET_NAME="$2"; shift 2;;
    --wallet.hotkey) WALLET_HOTKEY="$2"; shift 2;;
    --neuron.sample_size) SAMPLE_SIZE="$2"; shift 2;;
    --log_level) LOG_LEVEL="$2"; shift 2;;
    --collector.url) COLLECTOR_URL="$2"; shift 2;;
    --collector.timeout) COLLECTOR_TIMEOUT="$2"; shift 2;;
    --collector.api_key) COLLECTOR_API_KEY="$2"; shift 2;;
    --collector.reports_limit) COLLECTOR_REPORTS_LIMIT="$2"; shift 2;;
    --validator.weight_update_interval) WEIGHT_UPDATE_INTERVAL="$2"; shift 2;;
    --validator.validation_interval) VALIDATION_INTERVAL="$2"; shift 2;;
    -h|--help)
      echo "Level114 Subnet Validator Runner"
      echo
      echo "Usage: $0 [OPTIONS] [-- any extra bittensor/logging flags]"
      echo
      echo "Options:"
      echo "  --netuid NETUID                   Subnet netuid (default: 114)"
      echo "  --network NETWORK                 Bittensor network (default: finney)"
      echo "  --wallet.name NAME                Wallet name (default: default)"
      echo "  --wallet.hotkey HOTKEY            Wallet hotkey (default: default)"
      echo "  --neuron.sample_size SIZE         Number of nodes to query (default: 10)"
      echo "  --collector.url URL               Collector base URL (required)"
      echo "  --collector.timeout SECONDS       Collector timeout (default: 10.0)"
      echo "  --collector.api_key KEY           Collector API key (required)"
      echo "  --collector.reports_limit N       Default reports limit (default: 25)"
      echo "  --validator.weight_update_interval SEC  Weight update interval (default: 300)"
      echo "  --validator.validation_interval SEC     Validation cycle interval (default: 1440, minimum enforced)"
      echo "  --log_level LEVEL                 Log level (default: INFO)"
      echo "  -h, --help                        Show this help"
      exit 0
      ;;
    *) EXTRA_ARGS+=("$1"); shift 1;;
  esac
done

# Ensure running from project root
if [[ ! -f "neurons/validator.py" ]]; then
  echo "Error: Run this script from the project root: $PROJECT_ROOT"
  echo "Missing file: neurons/validator.py"
  exit 1
fi

# Require mandatory collector config
if [[ -z "$COLLECTOR_URL" ]]; then
  echo "❌ --collector.url is required"
  exit 1
fi
if [[ -z "$COLLECTOR_API_KEY" ]]; then
  echo "❌ --collector.api_key is required"
  exit 1
fi

# Locate Python 3
if command -v python3 >/dev/null 2>&1; then
  SYS_PY=python3
elif command -v python >/dev/null 2>&1; then
  SYS_PY=python
else
  echo "❌ Python 3 not found in PATH. Please install Python 3.8+." >&2
  exit 1
fi

# Create/activate venv
VENV_DIR="$PROJECT_ROOT/.venv"
if [[ ! -d "$VENV_DIR" ]]; then
  echo "Creating virtual environment at $VENV_DIR"
  "$SYS_PY" -m venv "$VENV_DIR"
fi

VENV_PY="$VENV_DIR/bin/python"
VENV_PIP="$VENV_DIR/bin/pip"

"$VENV_PY" -V >/dev/null 2>&1 || { echo "❌ Failed to initialize venv"; exit 1; }

# Upgrade pip and install deps
echo "Setting up Python environment..."
"$VENV_PY" -m pip install --upgrade pip wheel >/dev/null 2>&1

if [[ -f "$PROJECT_ROOT/requirements.txt" ]]; then
  echo "Installing requirements.txt..."
  "$VENV_PIP" install -r "$PROJECT_ROOT/requirements.txt" --no-warn-script-location
else
  echo "Installing package in editable mode..."
  "$VENV_PIP" install -e "$PROJECT_ROOT" --no-warn-script-location
fi

export PYTHONPATH="$PROJECT_ROOT:${PYTHONPATH:-}"
export PYTHONUNBUFFERED=1

echo "🚀 Starting Level114 Validator..."
echo "   Network: $NETWORK (netuid: $NETUID)"
echo "   Wallet: $WALLET_NAME/$WALLET_HOTKEY"
echo "   Collector: $COLLECTOR_URL"
echo "   Validation interval: ${VALIDATION_INTERVAL}s"
echo "   Weight update interval: ${WEIGHT_UPDATE_INTERVAL}s"
echo ""

CMD=("$VENV_PY" -u "$PROJECT_ROOT/neurons/validator.py"
  --netuid "$NETUID"
  --subtensor.network "$NETWORK"
  --wallet.name "$WALLET_NAME"
  --wallet.hotkey "$WALLET_HOTKEY"
  --neuron.sample_size "$SAMPLE_SIZE"
  --logging.info
)

# Append collector flags if provided
if [[ -n "$COLLECTOR_URL" ]]; then CMD+=(--collector.url "$COLLECTOR_URL"); fi
if [[ -n "$COLLECTOR_TIMEOUT" ]]; then CMD+=(--collector.timeout "$COLLECTOR_TIMEOUT"); fi
if [[ -n "$COLLECTOR_API_KEY" ]]; then CMD+=(--collector.api_key "$COLLECTOR_API_KEY"); fi
if [[ -n "$COLLECTOR_REPORTS_LIMIT" ]]; then CMD+=(--collector.reports_limit "$COLLECTOR_REPORTS_LIMIT"); fi

# Append validator scoring flags
if [[ -n "$WEIGHT_UPDATE_INTERVAL" ]]; then CMD+=(--validator.weight_update_interval "$WEIGHT_UPDATE_INTERVAL"); fi
if [[ -n "$VALIDATION_INTERVAL" ]]; then CMD+=(--validator.validation_interval "$VALIDATION_INTERVAL"); fi

# Forward extra args (logging, bittensor flags, etc.)
CMD+=("${EXTRA_ARGS[@]}")

exec "${CMD[@]}"
