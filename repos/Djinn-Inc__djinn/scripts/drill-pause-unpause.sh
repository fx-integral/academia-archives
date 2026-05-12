#!/usr/bin/env bash
# drill-pause-unpause.sh — Emergency pause drill (P0-04).
#
# Exercises the full pause → schedule unpause → execute unpause cycle against
# a live contract on Base Sepolia. By default targets Escrow because it is
# the most user-facing pausable; pass --contract <addr> to target another
# Pausable proxy.
#
# This is the drill referenced by `docs/runbook-emergency-pause.md` as the
# mainnet-blocker (P0-04) requirement: prove we can actually pause a live
# contract, watch the state propagate, and unpause cleanly under the
# governance path we'd use in production.
#
# Requirements:
#   - $PAUSER_KEY: EOA private key authorized as pauser() on the target
#     contract. On Sepolia this is typically the deployer key.
#   - $DEPLOYER_KEY: Same key, used as timelock proposer/executor to schedule
#     and execute the unpause. (Sepolia timelock is open-executor; mainnet
#     needs an executor with the EXECUTOR_ROLE.)
#   - $BASE_SEPOLIA_RPC_URL (preferred) or $BASE_RPC_URL.
#   - cast (foundry) on PATH.
#
# What this script does:
#   1. Reads pauser(), owner(), paused() off the target contract.
#   2. Refuses to run if already paused, if pauser mismatch, or if owner is
#      not the timelock.
#   3. Calls pause() from the pauser EOA.
#   4. Verifies paused() == true.
#   5. Schedules unpause() via the timelock with a random salt, computing
#      the operation id off-chain via hashOperation().
#   6. Waits the timelock's minDelay (72s on Sepolia, 72h on mainnet — the
#      mainnet path would require a --no-wait flag, not shipped).
#   7. Executes the scheduled unpause.
#   8. Verifies paused() == false.
#   9. Appends a markdown evidence block to
#      docs/drills/YYYY-MM-DD-pause-drill.md.
#
# Exit codes:
#   0  full drill succeeded
#   1  preflight failed (already paused, key mismatch, etc.)
#   2  pause step failed
#   3  schedule unpause step failed
#   4  execute unpause step failed
#   5  final verification failed

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(dirname "$SCRIPT_DIR")"

# --- Parse args -------------------------------------------------------------
CONTRACT="0xb43BA175a6784973eB3825acF801Cd7920ac692a" # Escrow
TIMELOCK="0x37f41EFfa8492022afF48B9Ef725008963F14f79"
CONTRACT_LABEL="Escrow"
DRY_RUN=0
EVIDENCE_DIR="$REPO_DIR/docs/drills"

while [[ $# -gt 0 ]]; do
    case "$1" in
        --contract) CONTRACT="$2"; shift 2;;
        --contract-label) CONTRACT_LABEL="$2"; shift 2;;
        --timelock) TIMELOCK="$2"; shift 2;;
        --dry-run) DRY_RUN=1; shift;;
        --evidence-dir) EVIDENCE_DIR="$2"; shift 2;;
        -h|--help)
            sed -n '1,50p' "$0"
            exit 0;;
        *) echo "unknown arg: $1" >&2; exit 1;;
    esac
done

# --- Load env ---------------------------------------------------------------
if [[ -f "$REPO_DIR/contracts/.env" ]]; then
    set -a
    # shellcheck disable=SC1091
    source "$REPO_DIR/contracts/.env"
    set +a
fi

RPC="${BASE_SEPOLIA_RPC_URL:-${BASE_RPC_URL:-https://sepolia.base.org}}"
PAUSER_KEY="${PAUSER_KEY:-${DEPLOYER_KEY:-}}"
DEPLOYER_KEY="${DEPLOYER_KEY:-}"

if [[ -z "$PAUSER_KEY" || -z "$DEPLOYER_KEY" ]]; then
    echo "ERROR: set PAUSER_KEY (or DEPLOYER_KEY) and DEPLOYER_KEY in env or contracts/.env" >&2
    exit 1
fi

export PATH="$HOME/.foundry/bin:$PATH"
if ! command -v cast >/dev/null 2>&1; then
    echo "ERROR: cast not on PATH (install foundry)" >&2
    exit 1
fi

ts() { date -u +%Y-%m-%dT%H:%M:%SZ; }
log() { echo "[$(ts)] $*"; }

log "drill_start contract=$CONTRACT_LABEL@$CONTRACT timelock=$TIMELOCK rpc=$RPC dry_run=$DRY_RUN"

# --- Preflight --------------------------------------------------------------
DEPLOYER_ADDR=$(cast wallet address --private-key "$DEPLOYER_KEY")
PAUSER_ADDR=$(cast wallet address --private-key "$PAUSER_KEY")
log "deployer=$DEPLOYER_ADDR pauser_eoa=$PAUSER_ADDR"

CHAIN_ID=$(cast chain-id --rpc-url "$RPC")
log "chain_id=$CHAIN_ID"

ON_CHAIN_PAUSER=$(cast call "$CONTRACT" "pauser()(address)" --rpc-url "$RPC")
ON_CHAIN_OWNER=$(cast call "$CONTRACT" "owner()(address)" --rpc-url "$RPC")
ALREADY_PAUSED=$(cast call "$CONTRACT" "paused()(bool)" --rpc-url "$RPC")
MIN_DELAY=$(cast call "$TIMELOCK" "getMinDelay()(uint256)" --rpc-url "$RPC")
log "on_chain_pauser=$ON_CHAIN_PAUSER on_chain_owner=$ON_CHAIN_OWNER already_paused=$ALREADY_PAUSED min_delay=${MIN_DELAY}s"

if [[ "${ALREADY_PAUSED,,}" == "true" ]]; then
    echo "ERROR: contract already paused; refusing to run drill. Unpause first." >&2
    exit 1
fi

# Case-fold both sides for comparison; cast returns checksum, wallet address also.
if [[ "${ON_CHAIN_PAUSER,,}" != "${PAUSER_ADDR,,}" ]]; then
    echo "ERROR: pauser mismatch. On-chain pauser=$ON_CHAIN_PAUSER but PAUSER_KEY=$PAUSER_ADDR." >&2
    exit 1
fi

if [[ "${ON_CHAIN_OWNER,,}" != "${TIMELOCK,,}" ]]; then
    echo "ERROR: owner is $ON_CHAIN_OWNER, expected timelock $TIMELOCK. Refusing to run." >&2
    exit 1
fi

# Guard: minDelay must be small enough to run in a single invocation. On
# mainnet (72h = 259200s) we'd need a --no-wait flag to split into schedule
# + resume phases. For now, cap at 10 minutes.
if (( MIN_DELAY > 600 )); then
    echo "ERROR: timelock minDelay=${MIN_DELAY}s exceeds 600s. Won't wait this long in a single run." >&2
    echo "       This drill is sized for Sepolia (72s). For mainnet, split into schedule + resume." >&2
    exit 1
fi

if [[ "$DRY_RUN" -eq 1 ]]; then
    log "dry_run_complete: preflight green; would proceed to pause+schedule+execute"
    exit 0
fi

# --- Step 1: Pause ----------------------------------------------------------
log "step1_pause: sending pause() from $PAUSER_ADDR"
PAUSE_TX_OUTPUT=$(cast send "$CONTRACT" "pause()" \
    --private-key "$PAUSER_KEY" \
    --rpc-url "$RPC" 2>&1) || {
    echo "ERROR: pause() failed" >&2
    echo "$PAUSE_TX_OUTPUT" >&2
    exit 2
}
PAUSE_TX=$(echo "$PAUSE_TX_OUTPUT" | grep -oE 'transactionHash\s+0x[0-9a-fA-F]{64}' | awk '{print $2}')
PAUSE_BLOCK=$(echo "$PAUSE_TX_OUTPUT" | grep -oE 'blockNumber\s+[0-9]+' | awk '{print $2}')
log "pause_tx=$PAUSE_TX block=$PAUSE_BLOCK"

# Public RPC load-balancers sometimes route our follow-up read to a node that
# is a block behind `cast send`'s receipt view. Retry with bounded backoff.
POST_PAUSE="false"
for attempt in 1 2 3 4 5; do
    POST_PAUSE=$(cast call "$CONTRACT" "paused()(bool)" --rpc-url "$RPC" 2>/dev/null || echo "false")
    if [[ "${POST_PAUSE,,}" == "true" ]]; then
        break
    fi
    log "post_pause_paused=$POST_PAUSE attempt=$attempt (retrying in 3s)"
    sleep 3
done
log "post_pause_paused=$POST_PAUSE"
if [[ "${POST_PAUSE,,}" != "true" ]]; then
    echo "ERROR: paused() still false after pause tx confirmed and 5 retries" >&2
    exit 2
fi

# --- Step 2: Schedule unpause via timelock ----------------------------------
# OpenZeppelin TimelockController.schedule(target, value, data, predecessor, salt, delay)
SALT=$(cast keccak "drill-pause-unpause-$(ts)-$RANDOM")
UNPAUSE_CALLDATA=$(cast calldata "unpause()")
PREDECESSOR="0x0000000000000000000000000000000000000000000000000000000000000000"

log "step2_schedule_unpause: salt=$SALT calldata=$UNPAUSE_CALLDATA delay=${MIN_DELAY}s"

# Compute the operation id off-chain so we can watch for CallExecuted.
OP_ID=$(cast call "$TIMELOCK" \
    "hashOperation(address,uint256,bytes,bytes32,bytes32)(bytes32)" \
    "$CONTRACT" 0 "$UNPAUSE_CALLDATA" "$PREDECESSOR" "$SALT" \
    --rpc-url "$RPC")
log "operation_id=$OP_ID"

SCHEDULE_TX_OUTPUT=$(cast send "$TIMELOCK" \
    "schedule(address,uint256,bytes,bytes32,bytes32,uint256)" \
    "$CONTRACT" 0 "$UNPAUSE_CALLDATA" "$PREDECESSOR" "$SALT" "$MIN_DELAY" \
    --private-key "$DEPLOYER_KEY" \
    --rpc-url "$RPC" 2>&1) || {
    echo "ERROR: schedule() failed" >&2
    echo "$SCHEDULE_TX_OUTPUT" >&2
    exit 3
}
SCHEDULE_TX=$(echo "$SCHEDULE_TX_OUTPUT" | grep -oE 'transactionHash\s+0x[0-9a-fA-F]{64}' | awk '{print $2}')
SCHEDULE_BLOCK=$(echo "$SCHEDULE_TX_OUTPUT" | grep -oE 'blockNumber\s+[0-9]+' | awk '{print $2}')
log "schedule_tx=$SCHEDULE_TX block=$SCHEDULE_BLOCK"

READY_TS=$(cast call "$TIMELOCK" "getTimestamp(bytes32)(uint256)" "$OP_ID" --rpc-url "$RPC")
log "unpause_ready_at_unix=$READY_TS"

# --- Step 3: Wait for the delay ---------------------------------------------
log "step3_wait: sleeping ${MIN_DELAY}s + 3s buffer"
sleep $((MIN_DELAY + 3))

IS_READY=$(cast call "$TIMELOCK" "isOperationReady(bytes32)(bool)" "$OP_ID" --rpc-url "$RPC")
log "is_ready=$IS_READY"
if [[ "${IS_READY,,}" != "true" ]]; then
    # Some nodes are a block behind; one more slice.
    log "not yet ready, sleeping 12s"
    sleep 12
    IS_READY=$(cast call "$TIMELOCK" "isOperationReady(bytes32)(bool)" "$OP_ID" --rpc-url "$RPC")
    log "is_ready_retry=$IS_READY"
    if [[ "${IS_READY,,}" != "true" ]]; then
        echo "ERROR: operation not ready after delay + 15s buffer" >&2
        exit 4
    fi
fi

# --- Step 4: Execute unpause ------------------------------------------------
log "step4_execute"
EXEC_TX_OUTPUT=$(cast send "$TIMELOCK" \
    "execute(address,uint256,bytes,bytes32,bytes32)" \
    "$CONTRACT" 0 "$UNPAUSE_CALLDATA" "$PREDECESSOR" "$SALT" \
    --private-key "$DEPLOYER_KEY" \
    --rpc-url "$RPC" 2>&1) || {
    echo "ERROR: execute() failed" >&2
    echo "$EXEC_TX_OUTPUT" >&2
    exit 4
}
EXEC_TX=$(echo "$EXEC_TX_OUTPUT" | grep -oE 'transactionHash\s+0x[0-9a-fA-F]{64}' | awk '{print $2}')
EXEC_BLOCK=$(echo "$EXEC_TX_OUTPUT" | grep -oE 'blockNumber\s+[0-9]+' | awk '{print $2}')
log "exec_tx=$EXEC_TX block=$EXEC_BLOCK"

POST_EXEC="true"
for attempt in 1 2 3 4 5; do
    POST_EXEC=$(cast call "$CONTRACT" "paused()(bool)" --rpc-url "$RPC" 2>/dev/null || echo "true")
    if [[ "${POST_EXEC,,}" == "false" ]]; then
        break
    fi
    log "post_exec_paused=$POST_EXEC attempt=$attempt (retrying in 3s)"
    sleep 3
done
log "post_exec_paused=$POST_EXEC"
if [[ "${POST_EXEC,,}" != "false" ]]; then
    echo "ERROR: paused() still true after execute; drill failed" >&2
    exit 5
fi

# --- Step 5: Evidence -------------------------------------------------------
mkdir -p "$EVIDENCE_DIR"
DATE=$(date -u +%Y-%m-%d)
EVIDENCE="$EVIDENCE_DIR/${DATE}-pause-drill.md"

# If file exists, append a new section; otherwise create with header.
if [[ ! -f "$EVIDENCE" ]]; then
    cat > "$EVIDENCE" <<MD
# Pause drill — $DATE

Evidence for P0-04 pause drill runs. Each section is one invocation of
\`scripts/drill-pause-unpause.sh\`. Append-only.

MD
fi

cat >> "$EVIDENCE" <<MD
## Run — $(ts)

| Field | Value |
|---|---|
| Contract | $CONTRACT_LABEL @ \`$CONTRACT\` |
| Chain | $CHAIN_ID |
| Pauser EOA | \`$PAUSER_ADDR\` |
| Timelock | \`$TIMELOCK\` |
| Timelock minDelay | ${MIN_DELAY}s |
| Pause tx | [\`$PAUSE_TX\`](https://sepolia.basescan.org/tx/$PAUSE_TX) (block $PAUSE_BLOCK) |
| Schedule tx | [\`$SCHEDULE_TX\`](https://sepolia.basescan.org/tx/$SCHEDULE_TX) (block $SCHEDULE_BLOCK) |
| Operation id | \`$OP_ID\` |
| Salt | \`$SALT\` |
| Unpause ready at (unix) | $READY_TS |
| Execute tx | [\`$EXEC_TX\`](https://sepolia.basescan.org/tx/$EXEC_TX) (block $EXEC_BLOCK) |
| paused() before | false |
| paused() after pause | true |
| paused() after execute | false |

Drill outcome: **pass**.

MD

log "evidence_appended_to=$EVIDENCE"
log "drill_complete"
