#!/usr/bin/env bash
set -euo pipefail

# Update subgraph.yaml with deployed contract addresses.
#
# Usage:
#   ./scripts/update_subgraph.sh \
#     --signal 0x... \
#     --escrow 0x... \
#     --collateral 0x... \
#     --account 0x... \
#     --audit 0x... \
#     --credit-ledger 0x... \
#     [--start-block 12345] \
#     [--network base-sepolia]

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
SUBGRAPH="$PROJECT_ROOT/subgraph/subgraph.yaml"

# Defaults
START_BLOCK=0
NETWORK="base"

# Parse args
while [[ $# -gt 0 ]]; do
    case "$1" in
        --signal)       SIGNAL="$2"; shift 2 ;;
        --escrow)       ESCROW="$2"; shift 2 ;;
        --collateral)   COLLATERAL="$2"; shift 2 ;;
        --account)      ACCOUNT="$2"; shift 2 ;;
        --audit)        AUDIT="$2"; shift 2 ;;
        --credit-ledger) CREDIT_LEDGER="$2"; shift 2 ;;
        --start-block)  START_BLOCK="$2"; shift 2 ;;
        --network)      NETWORK="$2"; shift 2 ;;
        *) echo "Unknown arg: $1"; exit 1 ;;
    esac
done

# Validate required args
for var in SIGNAL ESCROW COLLATERAL ACCOUNT AUDIT CREDIT_LEDGER; do
    if [ -z "${!var:-}" ]; then
        echo "ERROR: --$(echo $var | tr '[:upper:]' '[:lower:]' | tr '_' '-') is required"
        echo ""
        echo "Usage: $0 --signal 0x... --escrow 0x... --collateral 0x... --account 0x... --audit 0x... --credit-ledger 0x..."
        exit 1
    fi
done

echo "=== Updating subgraph.yaml ==="
echo "Network:      $NETWORK"
echo "Start block:  $START_BLOCK"
echo "Signal:       $SIGNAL"
echo "Escrow:       $ESCROW"
echo "Collateral:   $COLLATERAL"
echo "Account:      $ACCOUNT"
echo "Audit:        $AUDIT"
echo "CreditLedger: $CREDIT_LEDGER"
echo ""

# Use sed to update addresses and start blocks
# Each data source has a unique name so we can target them specifically

update_datasource() {
    local name="$1"
    local address="$2"

    # Update address (find the line after "name: $name" that contains "address:")
    sed -i "/$name/,/address:/ s|address: \"0x[0-9a-fA-F]*\"|address: \"$address\"|" "$SUBGRAPH"

    # Update startBlock
    sed -i "/$name/,/startBlock:/ s|startBlock: [0-9]*|startBlock: $START_BLOCK|" "$SUBGRAPH"
}

# Update network
sed -i "s|network: .*|network: $NETWORK|g" "$SUBGRAPH"

update_datasource "SignalCommitment" "$SIGNAL"
update_datasource "Escrow" "$ESCROW"
update_datasource "Collateral" "$COLLATERAL"
update_datasource "Account" "$ACCOUNT"
update_datasource "Audit" "$AUDIT"
update_datasource "CreditLedger" "$CREDIT_LEDGER"

echo "Done! Review changes:"
echo "  git diff subgraph/subgraph.yaml"
echo ""
echo "Deploy subgraph:"
echo "  cd subgraph && graph deploy --studio djinn-protocol"
