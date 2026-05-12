#!/usr/bin/env bash
# staging-up.sh
#
# Bring up a Base mainnet fork for pre-launch staging:
#   1. anvil --fork-url $BASE_MAINNET_RPC --chain-id 8453 on port 8545
#   2. Fund the deployer with ETH via anvil_setBalance
#   3. Transfer real USDC from a whale (via anvil_impersonateAccount) to the
#      deployer so Playwright journeys can exercise the full mainnet path
#      without needing real money
#   4. Hand off to scripts/deploy_local.sh — Deploy.s.sol already branches on
#      chain.id == 8453 to wire against real USDC (Deploy.s.sol:88)
#
# What this closes for P1-06: the operator can dry-run a full mainnet deploy +
# wallet flow end-to-end before the actual mainnet cutover, without spending
# gas or risking a misconfigured deploy.
#
# Usage:
#   BASE_MAINNET_RPC=https://mainnet.base.org ./scripts/staging-up.sh
#   # Then in another shell:
#   #   curl http://localhost:8545   # fork is live
#   #   ./scripts/staging-up.sh deploy   # run Deploy.s.sol against the fork
#
# Stop the fork:
#   ./scripts/staging-up.sh down    # kills the anvil process recorded in .anvil.pid
#
# Time-warp past timelock:
#   cast rpc --rpc-url http://localhost:8545 evm_increaseTime 259200
#   cast rpc --rpc-url http://localhost:8545 evm_mine
#
# Required:
#   BASE_MAINNET_RPC - an Base-mainnet-capable RPC (Alchemy/Infura/public)
#
# Optional:
#   STAGING_PORT     - anvil port, default 8545
#   FORK_BLOCK       - pin a specific block for reproducibility
#   USDC_WHALE       - address to impersonate for test-USDC transfers.
#                      Defaults to Coinbase 10, a known Base-mainnet USDC
#                      holder at the time of writing.
#   DEPLOYER_KEY     - private key for the deployer (defaults to anvil acct 0)
#   TEST_USDC_AMOUNT - microUSDC to give the deployer; default 10M (10 USDC)
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

export PATH="$HOME/.foundry/bin:$PATH"

PORT="${STAGING_PORT:-8545}"
RPC_URL="http://localhost:${PORT}"
PID_FILE="$PROJECT_ROOT/.anvil.pid"
LOG_FILE="$PROJECT_ROOT/.anvil.log"

BASE_MAINNET_USDC="0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"
USDC_WHALE="${USDC_WHALE:-0x3304E22DDaa22bCdC5fCa2269b418046aE7b566A}" # Coinbase 10
TEST_USDC_AMOUNT="${TEST_USDC_AMOUNT:-10000000}"                        # 10 USDC

# Anvil default acct 0
DEPLOYER_KEY="${DEPLOYER_KEY:-0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80}"
DEPLOYER_ADDR="0xf39Fd6e51aad88F6F4ce6aB8827279cfFFb92266"

cmd="${1:-up}"

case "$cmd" in
  up)
    if [ -f "$PID_FILE" ] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
      echo "anvil already running (PID $(cat "$PID_FILE"))"
      exit 0
    fi

    : "${BASE_MAINNET_RPC:?BASE_MAINNET_RPC must be set (Alchemy / Infura / public endpoint)}"

    echo "=== Starting Base mainnet fork on :${PORT} ==="
    echo "RPC upstream: $BASE_MAINNET_RPC"

    anvil_args=(
      --fork-url "$BASE_MAINNET_RPC"
      --chain-id 8453
      --port "$PORT"
      --host 0.0.0.0
      --accounts 10
      --balance 1000
      --gas-limit 30000000
    )
    if [ -n "${FORK_BLOCK:-}" ]; then
      anvil_args+=(--fork-block-number "$FORK_BLOCK")
      echo "Pinned to block: $FORK_BLOCK"
    fi

    nohup anvil "${anvil_args[@]}" > "$LOG_FILE" 2>&1 &
    echo $! > "$PID_FILE"

    # Wait for anvil to accept connections (up to 30s)
    for i in {1..30}; do
      if cast chain-id --rpc-url "$RPC_URL" >/dev/null 2>&1; then
        break
      fi
      sleep 1
    done
    if ! cast chain-id --rpc-url "$RPC_URL" >/dev/null 2>&1; then
      echo "ERROR: anvil did not come up in 30s; see $LOG_FILE" >&2
      exit 1
    fi

    block=$(cast block-number --rpc-url "$RPC_URL")
    echo "Fork live: chain_id=$(cast chain-id --rpc-url "$RPC_URL"), block=$block"
    echo "PID: $(cat "$PID_FILE") · log: $LOG_FILE"
    echo ""
    echo "Next steps:"
    echo "  ./scripts/staging-up.sh fund       # give deployer 10 USDC via whale impersonation"
    echo "  ./scripts/staging-up.sh deploy     # run Deploy.s.sol against the fork"
    echo "  ./scripts/staging-up.sh down       # stop the fork"
    ;;

  down)
    if [ -f "$PID_FILE" ]; then
      pid=$(cat "$PID_FILE")
      if kill -0 "$pid" 2>/dev/null; then
        kill "$pid"
        echo "Stopped anvil PID $pid"
      fi
      rm -f "$PID_FILE"
    else
      echo "No anvil PID file; is the fork already down?"
    fi
    ;;

  fund)
    if ! cast chain-id --rpc-url "$RPC_URL" >/dev/null 2>&1; then
      echo "ERROR: anvil not reachable at $RPC_URL; run './scripts/staging-up.sh up' first" >&2
      exit 1
    fi

    echo "=== Funding deployer $DEPLOYER_ADDR ==="

    # Impersonate the whale, ensure they have gas, transfer USDC
    cast rpc --rpc-url "$RPC_URL" anvil_impersonateAccount "$USDC_WHALE" >/dev/null
    cast rpc --rpc-url "$RPC_URL" anvil_setBalance "$USDC_WHALE" 0xde0b6b3a7640000 >/dev/null # 1 ETH

    before=$(cast call --rpc-url "$RPC_URL" "$BASE_MAINNET_USDC" \
      "balanceOf(address)(uint256)" "$DEPLOYER_ADDR" | awk '{print $1}')
    echo "Deployer USDC before: $before"

    cast send --rpc-url "$RPC_URL" --from "$USDC_WHALE" --unlocked \
      "$BASE_MAINNET_USDC" "transfer(address,uint256)" \
      "$DEPLOYER_ADDR" "$TEST_USDC_AMOUNT" >/dev/null

    after=$(cast call --rpc-url "$RPC_URL" "$BASE_MAINNET_USDC" \
      "balanceOf(address)(uint256)" "$DEPLOYER_ADDR" | awk '{print $1}')
    echo "Deployer USDC after:  $after (delta $TEST_USDC_AMOUNT microUSDC)"

    cast rpc --rpc-url "$RPC_URL" anvil_stopImpersonatingAccount "$USDC_WHALE" >/dev/null
    ;;

  deploy)
    if ! cast chain-id --rpc-url "$RPC_URL" >/dev/null 2>&1; then
      echo "ERROR: anvil not reachable at $RPC_URL; run './scripts/staging-up.sh up' first" >&2
      exit 1
    fi
    # Deploy.s.sol enforces MULTISIG_ADDRESS on mainnet (chain_id 8453) as a
    # guardrail against accidental "deployer is sole proposer" deploys. The
    # fork inherits chain_id 8453, so we need a placeholder. Default to anvil
    # account 1 for MULTISIG (simulates a Safe) and account 2 for PAUSER.
    STAGING_MULTISIG="${MULTISIG_ADDRESS:-0x70997970C51812dc3A010C7d01b50e0d17dc79C8}"
    STAGING_PAUSER="${PAUSER_ADDRESS:-0x3C44CdDdB6a900fa2b585dd299e03d12FA4293BC}"
    cd "$PROJECT_ROOT/contracts"
    DEPLOYER_KEY="$DEPLOYER_KEY" \
      MULTISIG_ADDRESS="$STAGING_MULTISIG" \
      PAUSER_ADDRESS="$STAGING_PAUSER" \
      forge script script/Deploy.s.sol:Deploy \
      --rpc-url "$RPC_URL" --broadcast --skip-simulation
    ;;

  verify)
    # Run verify-ownership.sh against the fork. Expects that 'deploy' has
    # already run and that the seven proxy addresses are known (read from
    # web/.env after deploy populates them).
    env_file="$PROJECT_ROOT/web/.env"
    [ -f "$env_file" ] || { echo "ERROR: $env_file missing" >&2; exit 1; }
    set -a; . "$env_file"; set +a

    EXPECT_MAINNET=1 \
      RPC_URL="$RPC_URL" \
      TIMELOCK="${NEXT_PUBLIC_TIMELOCK_ADDRESS:-}" \
      SIGNAL_COMMITMENT="$NEXT_PUBLIC_SIGNAL_COMMITMENT_ADDRESS" \
      ESCROW="$NEXT_PUBLIC_ESCROW_ADDRESS" \
      COLLATERAL="$NEXT_PUBLIC_COLLATERAL_ADDRESS" \
      ACCOUNT="$NEXT_PUBLIC_ACCOUNT_ADDRESS" \
      AUDIT="$NEXT_PUBLIC_AUDIT_ADDRESS" \
      CREDIT_LEDGER="$NEXT_PUBLIC_CREDIT_LEDGER_ADDRESS" \
      OUTCOME_VOTING="${NEXT_PUBLIC_OUTCOME_VOTING_ADDRESS:-}" \
      EXPECTED_PAUSER="${NEXT_PUBLIC_PAUSER_ADDRESS:-$DEPLOYER_ADDR}" \
      EXPECTED_TREASURY="${NEXT_PUBLIC_PROTOCOL_TREASURY_ADDRESS:-$DEPLOYER_ADDR}" \
      EXPECTED_PROPOSER="${NEXT_PUBLIC_MULTISIG_ADDRESS:-$DEPLOYER_ADDR}" \
      EXPECTED_USDC="$BASE_MAINNET_USDC" \
      "$SCRIPT_DIR/verify-ownership.sh"
    ;;

  logs)
    [ -f "$LOG_FILE" ] || { echo "No log at $LOG_FILE"; exit 1; }
    tail -f "$LOG_FILE"
    ;;

  *)
    echo "Usage: $0 {up|down|fund|deploy|verify|logs}" >&2
    exit 2
    ;;
esac
