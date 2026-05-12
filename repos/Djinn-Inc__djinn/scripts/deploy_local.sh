#!/usr/bin/env bash
set -euo pipefail

# Deploy Djinn Protocol contracts to local Anvil chain.
# Prerequisite: anvil running on port 8545 (docker compose up anvil)
#
# Usage:
#   ./scripts/deploy_local.sh
#   ./scripts/deploy_local.sh --rpc-url http://custom-rpc:8545

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
CONTRACTS_DIR="$PROJECT_ROOT/contracts"

# Default Anvil private key (account 0)
DEPLOYER_KEY="${DEPLOYER_KEY:-0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80}"
RPC_URL="${1:-http://localhost:8545}"

echo "=== Djinn Protocol Local Deployment ==="
echo "RPC:      $RPC_URL"
echo "Contracts: $CONTRACTS_DIR"
echo ""

# Check forge is available
if ! command -v forge &> /dev/null; then
    echo "ERROR: forge not found. Install Foundry: https://getfoundry.sh"
    exit 1
fi

# Check chain is reachable
if ! cast block-number --rpc-url "$RPC_URL" &> /dev/null; then
    echo "ERROR: Cannot connect to $RPC_URL"
    echo "Start Anvil with: anvil --host 0.0.0.0"
    exit 1
fi

CHAIN_ID=$(cast chain-id --rpc-url "$RPC_URL")
echo "Chain ID: $CHAIN_ID"
echo ""

# Deploy
cd "$CONTRACTS_DIR"
OUTPUT=$(DEPLOYER_KEY="$DEPLOYER_KEY" forge script script/Deploy.s.sol:Deploy \
    --rpc-url "$RPC_URL" \
    --broadcast \
    --skip-simulation 2>&1)

echo "$OUTPUT"

# Parse deployed addresses from forge output
echo ""
echo "=== Updating .env files ==="

parse_address() {
    local label="$1"
    echo "$OUTPUT" | grep -oP "$label:\s*\K0x[0-9a-fA-F]+" | head -1
}

USDC=$(parse_address "MockUSDC")
ACCOUNT=$(parse_address "Account")
CREDIT_LEDGER=$(parse_address "CreditLedger")
SIGNAL=$(parse_address "SignalCommitment")
COLLATERAL=$(parse_address "Collateral")
ESCROW=$(parse_address "Escrow")
AUDIT=$(parse_address "Audit")

if [ -z "$USDC" ]; then
    echo "WARNING: Could not parse addresses from forge output."
    echo "Check the output above and update .env files manually."
    exit 0
fi

# Update web .env
WEB_ENV="$PROJECT_ROOT/web/.env"
if [ -f "$WEB_ENV" ]; then
    echo "Updating $WEB_ENV"
    sed -i "s|NEXT_PUBLIC_USDC_ADDRESS=.*|NEXT_PUBLIC_USDC_ADDRESS=$USDC|" "$WEB_ENV"
    sed -i "s|NEXT_PUBLIC_SIGNAL_COMMITMENT_ADDRESS=.*|NEXT_PUBLIC_SIGNAL_COMMITMENT_ADDRESS=$SIGNAL|" "$WEB_ENV"
    sed -i "s|NEXT_PUBLIC_ESCROW_ADDRESS=.*|NEXT_PUBLIC_ESCROW_ADDRESS=$ESCROW|" "$WEB_ENV"
    sed -i "s|NEXT_PUBLIC_COLLATERAL_ADDRESS=.*|NEXT_PUBLIC_COLLATERAL_ADDRESS=$COLLATERAL|" "$WEB_ENV"
    sed -i "s|NEXT_PUBLIC_CREDIT_LEDGER_ADDRESS=.*|NEXT_PUBLIC_CREDIT_LEDGER_ADDRESS=$CREDIT_LEDGER|" "$WEB_ENV"
    sed -i "s|NEXT_PUBLIC_ACCOUNT_ADDRESS=.*|NEXT_PUBLIC_ACCOUNT_ADDRESS=$ACCOUNT|" "$WEB_ENV"
    sed -i "s|NEXT_PUBLIC_AUDIT_ADDRESS=.*|NEXT_PUBLIC_AUDIT_ADDRESS=$AUDIT|" "$WEB_ENV"
    sed -i "s|NEXT_PUBLIC_BASE_RPC_URL=.*|NEXT_PUBLIC_BASE_RPC_URL=$RPC_URL|" "$WEB_ENV"
fi

# Update validator .env
VAL_ENV="$PROJECT_ROOT/validator/.env"
if [ -f "$VAL_ENV" ]; then
    echo "Updating $VAL_ENV"
    sed -i "s|ESCROW_ADDRESS=.*|ESCROW_ADDRESS=$ESCROW|" "$VAL_ENV"
    sed -i "s|SIGNAL_COMMITMENT_ADDRESS=.*|SIGNAL_COMMITMENT_ADDRESS=$SIGNAL|" "$VAL_ENV"
    sed -i "s|ACCOUNT_ADDRESS=.*|ACCOUNT_ADDRESS=$ACCOUNT|" "$VAL_ENV"
    sed -i "s|COLLATERAL_ADDRESS=.*|COLLATERAL_ADDRESS=$COLLATERAL|" "$VAL_ENV"
    sed -i "s|BASE_RPC_URL=.*|BASE_RPC_URL=$RPC_URL|" "$VAL_ENV"
fi

echo ""
echo "=== Deployed Addresses ==="
echo "USDC:             $USDC"
echo "Account:          $ACCOUNT"
echo "CreditLedger:     $CREDIT_LEDGER"
echo "SignalCommitment: $SIGNAL"
echo "Collateral:       $COLLATERAL"
echo "Escrow:           $ESCROW"
echo "Audit:            $AUDIT"
echo ""
echo "Done! Start services with: docker compose up"
