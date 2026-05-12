#!/usr/bin/env bash
set -euo pipefail

# Deploy Djinn Protocol contracts to Base (Sepolia testnet or mainnet).
#
# Prerequisites:
#   - DEPLOYER_KEY env var set (private key with ETH for gas)
#   - forge installed (Foundry)
#
# Usage:
#   DEPLOYER_KEY=0x... ./scripts/deploy_base.sh sepolia
#   DEPLOYER_KEY=0x... ./scripts/deploy_base.sh mainnet

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
CONTRACTS_DIR="$PROJECT_ROOT/contracts"

NETWORK="${1:-sepolia}"

case "$NETWORK" in
    sepolia)
        RPC_URL="${BASE_SEPOLIA_RPC_URL:-https://sepolia.base.org}"
        CHAIN_ID=84532
        ETHERSCAN_URL="https://api-sepolia.basescan.org/api"
        echo "=== Deploying to Base Sepolia ==="
        ;;
    mainnet)
        RPC_URL="${BASE_RPC_URL:-https://mainnet.base.org}"
        CHAIN_ID=8453
        ETHERSCAN_URL="https://api.basescan.org/api"
        echo "=== Deploying to Base Mainnet ==="
        echo ""
        echo "WARNING: This is a mainnet deployment. Contracts are immutable."
        read -p "Continue? (y/N) " -n 1 -r
        echo
        if [[ ! $REPLY =~ ^[Yy]$ ]]; then
            echo "Aborted."
            exit 0
        fi
        ;;
    *)
        echo "Usage: $0 [sepolia|mainnet]"
        exit 1
        ;;
esac

if [ -z "${DEPLOYER_KEY:-}" ]; then
    echo "ERROR: DEPLOYER_KEY not set"
    echo "Export your deployer private key: export DEPLOYER_KEY=0x..."
    exit 1
fi

# --- Pre-flight checks ---
echo "Running pre-flight checks..."

# Check forge is installed
if ! command -v forge &> /dev/null; then
    echo "ERROR: forge (Foundry) not found. Install: https://getfoundry.sh"
    exit 1
fi

# Check cast is installed
if ! command -v cast &> /dev/null; then
    echo "ERROR: cast (Foundry) not found. Install: https://getfoundry.sh"
    exit 1
fi

# Check RPC connectivity
echo -n "  RPC connectivity... "
if ! cast chain-id --rpc-url "$RPC_URL" &>/dev/null; then
    echo "FAILED"
    echo "ERROR: Cannot connect to RPC endpoint: $RPC_URL"
    exit 1
fi
ACTUAL_CHAIN_ID=$(cast chain-id --rpc-url "$RPC_URL")
if [ "$ACTUAL_CHAIN_ID" != "$CHAIN_ID" ]; then
    echo "FAILED"
    echo "ERROR: Chain ID mismatch. Expected $CHAIN_ID, got $ACTUAL_CHAIN_ID"
    exit 1
fi
echo "OK (chain $ACTUAL_CHAIN_ID)"

# Check deployer balance
DEPLOYER=$(cast wallet address "$DEPLOYER_KEY")
BALANCE=$(cast balance "$DEPLOYER" --rpc-url "$RPC_URL" --ether)
echo -n "  Deployer balance... "
# Warn if balance seems low (< 0.01 ETH)
BALANCE_WEI=$(cast balance "$DEPLOYER" --rpc-url "$RPC_URL")
if [ "$BALANCE_WEI" = "0" ]; then
    echo "FAILED"
    echo "ERROR: Deployer has 0 ETH. Fund $DEPLOYER before deploying."
    exit 1
fi
echo "OK ($BALANCE ETH)"

# Check contracts compile
echo -n "  Contracts compile... "
if ! forge build --root "$CONTRACTS_DIR" --silent 2>/dev/null; then
    echo "FAILED"
    echo "ERROR: Contract compilation failed. Run 'forge build' in $CONTRACTS_DIR"
    exit 1
fi
echo "OK"

echo "Pre-flight checks passed."
echo ""
echo "Deployer: $DEPLOYER"
echo "Balance:  $BALANCE ETH"
echo "RPC:      $RPC_URL"
echo "Chain ID: $CHAIN_ID"
if [ "$NETWORK" = "mainnet" ]; then
    echo "USDC:     0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913 (Base mainnet)"
fi
echo ""

# Deploy
cd "$CONTRACTS_DIR"

FORGE_ARGS=(
    script/Deploy.s.sol:Deploy
    --rpc-url "$RPC_URL"
    --broadcast
    --verify
)

# Add etherscan API key if available
if [ -n "${BASESCAN_API_KEY:-}" ]; then
    FORGE_ARGS+=(--etherscan-api-key "$BASESCAN_API_KEY")
fi

DEPLOYER_KEY="$DEPLOYER_KEY" forge script "${FORGE_ARGS[@]}" 2>&1 | tee /tmp/djinn-deploy-output.txt

echo ""
echo "=== Deployment complete ==="
echo "Output saved to /tmp/djinn-deploy-output.txt"
echo ""
echo "Next steps:"
echo "  1. Copy contract addresses to .env files (including AUDIT_ADDRESS)"
echo "  2. Update subgraph/networks.json with deployed addresses"
echo "  3. Deploy subgraph: cd subgraph && graph deploy --network $NETWORK"
if [ "$NETWORK" = "mainnet" ]; then
    echo "  4. Transfer ownership to multisig: ./scripts/transfer-ownership.sh"
    echo "  5. Verify contracts on Basescan"
fi
echo "  6. Push updated configs to the repo"
