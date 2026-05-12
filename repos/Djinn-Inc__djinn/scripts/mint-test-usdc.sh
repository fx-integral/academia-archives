#!/usr/bin/env bash
# Mint test USDC to a wallet address on Base Sepolia.
#
# Usage:
#   ./scripts/mint-test-usdc.sh <wallet_address> [amount_usdc]
#
# Examples:
#   ./scripts/mint-test-usdc.sh 0xD5f8...EF81          # mints 10,000 USDC
#   ./scripts/mint-test-usdc.sh 0xD5f8...EF81 100000   # mints 100,000 USDC

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
CONTRACTS_DIR="$(cd "$SCRIPT_DIR/../contracts" && pwd)"
WEB_ENV="$(cd "$SCRIPT_DIR/../web" && pwd)/.env"

if [ -z "${1:-}" ]; then
  echo "Usage: $0 <wallet_address> [amount_usdc]"
  exit 1
fi

RECIPIENT="$1"
AMOUNT="${2:-10000}"
AMOUNT_RAW="${AMOUNT}000000" # USDC has 6 decimals

# Load deployer key
source "$CONTRACTS_DIR/.env"
RPC_URL="${BASE_SEPOLIA_RPC_URL:-https://sepolia.base.org}"

# Get USDC address from web .env
USDC_ADDR=$(grep "NEXT_PUBLIC_USDC_ADDRESS" "$WEB_ENV" | cut -d= -f2)
if [ -z "$USDC_ADDR" ]; then
  echo "ERROR: NEXT_PUBLIC_USDC_ADDRESS not found in $WEB_ENV"
  exit 1
fi

echo "Minting $AMOUNT USDC to $RECIPIENT..."
echo "USDC contract: $USDC_ADDR"
echo "RPC: $RPC_URL"

# MockUSDC.mint(address,uint256) — function selector: 0x40c10f19
cast send "$USDC_ADDR" \
  "mint(address,uint256)" \
  "$RECIPIENT" "$AMOUNT_RAW" \
  --private-key "$DEPLOYER_KEY" \
  --rpc-url "$RPC_URL"

echo "Done! $RECIPIENT now has $AMOUNT test USDC."
