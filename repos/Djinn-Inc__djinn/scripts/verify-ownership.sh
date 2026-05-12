#!/usr/bin/env bash
# verify-ownership.sh
#
# Read-only on-chain assertion that the contract set matches what
# docs/governance.md says it is: every proxy owned by the right
# TimelockController, the timelock's minDelay meets the per-chain
# floor, the pauser address is wired on every pausable contract, and
# the protocol treasury is the documented Safe.
#
# Runs against the chain derived from $RPC_URL. Fails loudly on any
# mismatch so that a mainnet deploy cannot silently diverge from
# policy.
#
# Required env vars:
#   RPC_URL                   - Base mainnet or Base Sepolia RPC
#   TIMELOCK                  - TimelockController proxy address
#   SIGNAL_COMMITMENT         - SignalCommitment proxy address
#   ESCROW                    - Escrow proxy address
#   COLLATERAL                - Collateral proxy address
#   ACCOUNT                   - Account proxy address
#   AUDIT                     - Audit proxy address
#   CREDIT_LEDGER             - CreditLedger proxy address
#   OUTCOME_VOTING            - OutcomeVoting proxy address
#   EXPECTED_PAUSER           - pauser address (EOA or Safe)
#   EXPECTED_TREASURY         - Audit.protocolTreasury() address
#   EXPECTED_PROPOSER         - TimelockController proposer (Safe on mainnet)
#   EXPECTED_USDC             - canonical USDC ERC20 address for the chain.
#                               On Base mainnet this is
#                               0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913; on
#                               Sepolia this is the bridge-compatible MockUSDC.
#                               Guards against a deploy wiring the protocol to
#                               a fake ERC20.
#
# Optional env vars:
#   KEY_RECOVERY              - KeyRecovery address. Only exercised if
#                               KR_IS_PROXY=1 is also set. Governance
#                               docs §4 flag KeyRecovery as non-proxy
#                               on Sepolia until P1-18 redeploy lands,
#                               so the ownership check must be opt-in.
#
# Optional:
#   EXPECT_MAINNET            - set to "1" to assert chain_id == 8453
#                               and minDelay >= 259200 (72h)
#
# Usage:
#   RPC_URL=https://mainnet.base.org \
#   EXPECT_MAINNET=1 \
#   source mainnet.env && ./scripts/verify-ownership.sh

set -euo pipefail

need() {
  if [ -z "${!1:-}" ]; then
    echo "ERROR: $1 not set" >&2
    exit 1
  fi
}

for v in RPC_URL TIMELOCK SIGNAL_COMMITMENT ESCROW COLLATERAL ACCOUNT \
         AUDIT CREDIT_LEDGER OUTCOME_VOTING \
         EXPECTED_PAUSER EXPECTED_TREASURY EXPECTED_PROPOSER EXPECTED_USDC; do
  need "$v"
done

if [ "${KR_IS_PROXY:-0}" = "1" ]; then
  need KEY_RECOVERY
fi

fail=0
fail() {
  echo "FAIL: $*" >&2
  fail=1
}

lc() { echo "$1" | tr 'A-Z' 'a-z'; }

call() {
  cast call --rpc-url "$RPC_URL" "$@"
}

echo "=== Djinn ownership verification ==="
echo "RPC:      $RPC_URL"

# Chain id and expected minimum delay
chain_id=$(cast chain-id --rpc-url "$RPC_URL")
echo "chain_id: $chain_id"

if [ "${EXPECT_MAINNET:-0}" = "1" ]; then
  if [ "$chain_id" != "8453" ]; then
    fail "EXPECT_MAINNET=1 but chain_id=$chain_id (want 8453)"
  fi
  expected_min_delay=259200
  canonical_base_usdc=0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913
  if [ "$(lc "$EXPECTED_USDC")" != "$(lc "$canonical_base_usdc")" ]; then
    fail "EXPECT_MAINNET=1 but EXPECTED_USDC=$EXPECTED_USDC (want $canonical_base_usdc)"
  fi
else
  expected_min_delay=72
fi

# Newer cast (1.5+) appends scientific-notation annotations to numeric
# returns, e.g. "259200 [2.592e5]". Strip anything after the first token so
# the integer comparison below doesn't choke.
min_delay=$(call "$TIMELOCK" "getMinDelay()(uint256)" | awk '{print $1}')
echo "minDelay: $min_delay"
if [ "$min_delay" -lt "$expected_min_delay" ]; then
  fail "TimelockController.minDelay=$min_delay < floor $expected_min_delay"
fi

# Proposer role
proposer_role=$(cast keccak "PROPOSER_ROLE")
has_proposer=$(call "$TIMELOCK" "hasRole(bytes32,address)(bool)" \
  "$proposer_role" "$EXPECTED_PROPOSER")
if [ "$has_proposer" != "true" ]; then
  fail "TimelockController proposer_role: expected $EXPECTED_PROPOSER does not hold PROPOSER_ROLE"
fi

# Executor role open (address(0) holds EXECUTOR_ROLE = anyone can execute)
executor_role=$(cast keccak "EXECUTOR_ROLE")
open_executor=$(call "$TIMELOCK" "hasRole(bytes32,address)(bool)" \
  "$executor_role" "0x0000000000000000000000000000000000000000")
if [ "$open_executor" != "true" ]; then
  fail "TimelockController executor_role: address(0) not granted (executor not open-anyone)"
fi

# Ownership of every proxy is the timelock. KeyRecovery is excluded by
# default because it ships as a non-proxy on Sepolia (see governance.md
# §4) and owner() reverts; pass KR_IS_PROXY=1 once P1-18 redeploys it as
# a UUPS proxy on the target chain.
want_owner=$(lc "$TIMELOCK")
proxy_pairs=(
  "SignalCommitment $SIGNAL_COMMITMENT"
  "Escrow           $ESCROW"
  "Collateral       $COLLATERAL"
  "Account          $ACCOUNT"
  "Audit            $AUDIT"
  "CreditLedger     $CREDIT_LEDGER"
  "OutcomeVoting    $OUTCOME_VOTING"
)
if [ "${KR_IS_PROXY:-0}" = "1" ]; then
  proxy_pairs+=("KeyRecovery      $KEY_RECOVERY")
fi
for pair in "${proxy_pairs[@]}"; do
  name=$(echo "$pair" | awk '{print $1}')
  addr=$(echo "$pair" | awk '{print $2}')
  owner=$(lc "$(call "$addr" "owner()(address)")")
  if [ "$owner" != "$want_owner" ]; then
    fail "$name.owner()=$owner (want $want_owner)"
  fi
done

# Pauser wired on every pausable contract
want_pauser=$(lc "$EXPECTED_PAUSER")
for pair in \
  "Audit            $AUDIT" \
  "Escrow           $ESCROW" \
  "Collateral       $COLLATERAL" \
  "SignalCommitment $SIGNAL_COMMITMENT" \
  "OutcomeVoting    $OUTCOME_VOTING" \
  "Account          $ACCOUNT" \
  "CreditLedger     $CREDIT_LEDGER"; do
  name=$(echo "$pair" | awk '{print $1}')
  addr=$(echo "$pair" | awk '{print $2}')
  pauser=$(lc "$(call "$addr" "pauser()(address)")")
  if [ "$pauser" != "$want_pauser" ]; then
    fail "$name.pauser()=$pauser (want $want_pauser)"
  fi
done

# Audit.protocolTreasury() is the documented Safe
treasury=$(lc "$(call "$AUDIT" "protocolTreasury()(address)")")
want_treasury=$(lc "$EXPECTED_TREASURY")
if [ "$treasury" != "$want_treasury" ]; then
  fail "Audit.protocolTreasury()=$treasury (want $want_treasury)"
fi

# Cross-contract wiring mirrors Deploy.s.sol::_verify() (lines 240-259).
# Each tuple is (label, callee-addr, getter-fn, expected-addr) — any setter
# skipped by _wireContracts leaves a zero address and surfaces here. Catches
# P1-17/P1-19-class regressions.
wiring_checks=(
  "aud->esc|$AUDIT|escrow()(address)|$ESCROW"
  "aud->coll|$AUDIT|collateral()(address)|$COLLATERAL"
  "aud->cl|$AUDIT|creditLedger()(address)|$CREDIT_LEDGER"
  "aud->acct|$AUDIT|account()(address)|$ACCOUNT"
  "aud->sc|$AUDIT|signalCommitment()(address)|$SIGNAL_COMMITMENT"
  "aud->ov|$AUDIT|outcomeVoting()(address)|$OUTCOME_VOTING"
  "ov->aud|$OUTCOME_VOTING|audit()(address)|$AUDIT"
  "ov->acct|$OUTCOME_VOTING|account()(address)|$ACCOUNT"
  "esc->sc|$ESCROW|signalCommitment()(address)|$SIGNAL_COMMITMENT"
  "esc->coll|$ESCROW|collateral()(address)|$COLLATERAL"
  "esc->cl|$ESCROW|creditLedger()(address)|$CREDIT_LEDGER"
  "esc->acct|$ESCROW|account()(address)|$ACCOUNT"
  "sc->coll|$SIGNAL_COMMITMENT|collateral()(address)|$COLLATERAL"
  "esc->usdc|$ESCROW|usdc()(address)|$EXPECTED_USDC"
  "coll->usdc|$COLLATERAL|usdc()(address)|$EXPECTED_USDC"
)
for row in "${wiring_checks[@]}"; do
  IFS='|' read -r label callee sig want <<< "$row"
  got=$(lc "$(call "$callee" "$sig")")
  want=$(lc "$want")
  if [ "$got" != "$want" ]; then
    fail "$label: got=$got want=$want"
  fi
done

if [ "$fail" -eq 0 ]; then
  echo "=== PASS ==="
  exit 0
else
  echo "=== FAIL ==="
  exit 1
fi
