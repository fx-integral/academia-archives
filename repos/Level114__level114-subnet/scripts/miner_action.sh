#!/bin/bash

set -e

ACTION_RAW="$1"
if [[ -z "$ACTION_RAW" ]]; then
    echo "Usage: miner_action.sh <register|unregister> [OPTIONS]"
    exit 1
fi

shift
ACTION="${ACTION_RAW,,}"
if [[ "$ACTION" != "register" && "$ACTION" != "unregister" ]]; then
    echo "Unknown action: $ACTION_RAW"
    echo "Expected 'register' or 'unregister'"
    exit 1
fi

CALLER_NAME="${MINER_CALLER_NAME:-$(basename "$0")}"  # Show friendly name in help/output

# Default values
WALLET_NAME=""
WALLET_HOTKEY=""
COLLECTOR_URL="https://collector.level114.io"
MINECRAFT_HOSTNAME=""
MINECRAFT_PORT=25565
INTERACTIVE_MODE=true

ACTION_TITLE="${ACTION^}"

show_help() {
    echo "🎮 Level114 Subnet Miner ${ACTION_TITLE}"
    echo ""
    if [[ "$ACTION" == "register" ]]; then
        echo "This tool registers your Minecraft server with the Level114 subnet"
        echo "by connecting to the collector-center-main service."
    else
        echo "This tool unregisters your Minecraft server from the Level114 subnet"
        echo "by notifying the collector-center-main service."
    fi
    echo ""
    echo "Usage: $CALLER_NAME [OPTIONS]"
    echo ""
    echo "Options:"
    echo "  -h, --help                      Show this help message"
    echo "  --non-interactive               Run in non-interactive mode with all parameters"
    echo ""
    echo "In non-interactive mode, you can use:"
    echo "  --minecraft_hostname HOST       Minecraft server hostname (e.g., play.myserver.com)"
    echo "  --minecraft_port PORT           Minecraft server port (default: 25565)"
    echo "  --wallet.name NAME              Your Bittensor wallet name"
    echo "  --wallet.hotkey HOTKEY          Your Bittensor wallet hotkey"
    echo ""
}

# Early help check (without consuming action argument)
if [[ "$1" == "-h" ]] || [[ "$1" == "--help" ]]; then
    show_help
    exit 0
fi

# Parse command line arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --non-interactive)
            INTERACTIVE_MODE=false
            shift
            ;;
        --minecraft_hostname)
            MINECRAFT_HOSTNAME="$2"
            shift 2
            ;;
        --minecraft_port)
            MINECRAFT_PORT="$2"
            shift 2
            ;;
        --wallet.name)
            WALLET_NAME="$2"
            shift 2
            ;;
        --wallet.hotkey)
            WALLET_HOTKEY="$2"
            shift 2
            ;;
        -h|--help)
            show_help
            exit 0
            ;;
        *)
            echo "Unknown option: $1"
            echo "Use -h or --help for usage information"
            exit 1
            ;;
    esac
done

if [[ "$INTERACTIVE_MODE" == "true" ]]; then
    echo "🎮 Level114 Subnet Miner ${ACTION_TITLE} - Interactive Mode"
    echo ""
    if [[ "$ACTION" == "register" ]]; then
        echo "I will register your Minecraft server with the Level114 subnet"
        echo "through the collector-center-main service."
    else
        echo "I will unregister your Minecraft server from the Level114 subnet"
        echo "by notifying the collector-center-main service."
    fi
    echo ""

    echo "🎮 Minecraft Server Information:"
    read -p "Minecraft server hostname (e.g., play.myserver.com): " MINECRAFT_HOSTNAME
    read -p "Minecraft server port (default 25565): " input_mc_port
    if [[ -n "$input_mc_port" ]]; then
        MINECRAFT_PORT="$input_mc_port"
    fi
    echo ""

    echo "🔑 Bittensor Wallet Information:"
    read -p "Wallet name: " WALLET_NAME
    read -p "Hotkey name: " WALLET_HOTKEY
    echo ""
fi

if [[ -z "$MINECRAFT_HOSTNAME" ]]; then
    echo "❌ Error: Minecraft server hostname is required"
    echo "Please enter the Minecraft server hostname"
    exit 1
fi

if [[ -z "$WALLET_NAME" ]]; then
    echo "❌ Error: Wallet name is required"
    echo "Please enter the Bittensor wallet name"
    exit 1
fi

if [[ -z "$WALLET_HOTKEY" ]]; then
    echo "❌ Error: Hotkey name is required"
    echo "Please enter the Bittensor hotkey name"
    exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

if [[ ! -f "${PROJECT_ROOT}/neurons/miner.py" ]]; then
    echo "❌ Error: Cannot find Level114 subnet project structure"
    echo "Script location: $SCRIPT_DIR"
    echo "Project root: $PROJECT_ROOT"
    echo "Expected file: ${PROJECT_ROOT}/neurons/miner.py"
    echo ""
    echo "Please ensure this script is in the scripts/ directory of the Level114 subnet project."
    exit 1
fi

cd "$PROJECT_ROOT"

PYTHON_CMD=""
if command -v python3 &> /dev/null; then
    PYTHON_CMD="python3"
elif command -v python &> /dev/null; then
    PYTHON_CMD="python"
else
    echo "❌ Error: Neither 'python' nor 'python3' command found"
    echo "Please install Python 3.8+ and ensure it's in your PATH"
    exit 1
fi

echo "✅ Using Python command: $PYTHON_CMD"

if [[ -z "${VIRTUAL_ENV}" ]]; then
    echo "⚠️  Warning: No virtual environment detected. Consider activating a virtual environment first."
    read -p "Continue anyway? (y/N): " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        exit 1
    fi
fi

if [[ "$ACTION" == "register" ]]; then
    echo "🎮 Registering Minecraft Server with Level114 Subnet..."
else
    echo "🎮 Unregistering Minecraft Server from Level114 Subnet..."
fi
echo ""
echo "📋 Configuration:"
echo "  - Bittensor Wallet: $WALLET_NAME.$WALLET_HOTKEY"
echo "  - Collector-Center: $COLLECTOR_URL"
echo "  - Minecraft Server: $MINECRAFT_HOSTNAME:$MINECRAFT_PORT"
echo ""

if [[ "$ACTION" == "register" ]]; then
    echo "🔄 What the registration will do:"
    echo "  1. Connect your Minecraft server to the Level114 subnet"
    echo "  2. Register server details with collector-center-main"
    echo "  3. Make your server available for validator evaluation"
    echo "  4. Enable earning TAO rewards based on server performance"
else
    echo "🔄 What the unregistration will do:"
    echo "  1. Notify collector-center-main to unregister your server"
    echo "  2. Remove server details from validator evaluation"
    echo "  3. Stop new scoring cycles for your server"
    echo "  4. Prevent further TAO rewards from this server"
fi
echo ""
echo "================================================================"
echo ""

export PYTHONPATH="${PROJECT_ROOT}:${PYTHONPATH}"

MINECRAFT_ARGS=(--minecraft_hostname "$MINECRAFT_HOSTNAME")
if [[ "$MINECRAFT_PORT" != "25565" ]]; then
    MINECRAFT_ARGS+=(--minecraft_port "$MINECRAFT_PORT")
fi

PYTHON_ARGS=(
    neurons/miner.py
    --wallet.name "$WALLET_NAME"
    --wallet.hotkey "$WALLET_HOTKEY"
    --action "$ACTION"
)

PYTHON_ARGS+=("${MINECRAFT_ARGS[@]}")
PYTHON_ARGS+=(--logging.debug)

$PYTHON_CMD "${PYTHON_ARGS[@]}"
