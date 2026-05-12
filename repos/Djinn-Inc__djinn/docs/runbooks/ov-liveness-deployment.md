# OutcomeVoting Liveness-Aware Quorum Upgrade Runbook

Operator steps to deploy the P0-11 liveness fix to Base Sepolia (or mainnet).

The upgrade is two steps: (1) deploy new implementation via timelock, (2) activate via `setActiveWindow`. Simple.

## History

This runbook was originally scoped for three-phase M1+M2+M3 (liveness + vote bonding + oracle fraud proofs). M2+M3 were reverted in v1603 as speculative — SN103 validators already have TAO stake at risk via Yuma consensus, so redundant USDC-bond slashing added complexity without marginal security. Only M1 (liveness-aware quorum) ships, because it solves a real current problem (bootstrap deadlock when signers go offline).

## Step 1 — Deploy new implementation

Adds the M1 state + functions. Post-upgrade behavior is byte-for-byte legacy until step 2.

```bash
cd /home/user/djinn/contracts
source .env

# Schedule
forge script script/ScheduleUpgradeOVLiveness.s.sol \
  --rpc-url $BASE_SEPOLIA_RPC_URL \
  --broadcast

# Record OV_IMPL_LIVENESS from logs, add to .env
export OV_IMPL_LIVENESS=<logged address>

# Wait 72 seconds (testnet delay; 72h on mainnet)
sleep 80

# Execute
forge script script/ExecuteUpgradeOVLiveness.s.sol \
  --rpc-url $BASE_SEPOLIA_RPC_URL \
  --broadcast
```

Verify post-upgrade:
```bash
# Liveness state accessible but default-off
cast call $OUTCOME_VOTING_PROXY 'activeWindow()(uint256)' --rpc-url $BASE_SEPOLIA_RPC_URL
# → 0 (legacy behavior, as expected)

# New functions exist and callable
cast call $OUTCOME_VOTING_PROXY 'activeCount()(uint256)' --rpc-url $BASE_SEPOLIA_RPC_URL
# → returns current validator count (because liveness is off)

# Existing state still good
cast call $OUTCOME_VOTING_PROXY 'getValidators()(address[])' --rpc-url $BASE_SEPOLIA_RPC_URL
# → same 6 addresses as before upgrade
```

If any verification fails, the upgrade didn't complete correctly — investigate before activating.

## Step 2 — Activate liveness-aware quorum

One `setActiveWindow` call via timelock flips M1 from dormant to active. After this, the quorum denominator auto-shrinks around offline validators.

```bash
# Pick window size. Base blocks are ~2s, so:
#   1800 blocks = ~1 hour (tight — validators must heartbeat/vote at least hourly)
#   3600 blocks = ~2 hours (more forgiving)
#   7200 blocks = ~4 hours (very forgiving)
# Recommendation: 1800 for active periods, 7200 for low-activity phases.
export OV_ACTIVE_WINDOW=1800

# Schedule
cast send $TIMELOCK \
  "schedule(address,uint256,bytes,bytes32,bytes32,uint256)" \
  $OUTCOME_VOTING_PROXY 0 \
  $(cast calldata "setActiveWindow(uint256)" $OV_ACTIVE_WINDOW) \
  0x0000000000000000000000000000000000000000000000000000000000000000 \
  $(cast keccak "outcome-voting-set-active-window") \
  72 \
  --rpc-url $BASE_SEPOLIA_RPC_URL --private-key $DEPLOYER_KEY

# Wait 72s
sleep 80

# Execute
cast send $TIMELOCK \
  "execute(address,uint256,bytes,bytes32,bytes32)" \
  $OUTCOME_VOTING_PROXY 0 \
  $(cast calldata "setActiveWindow(uint256)" $OV_ACTIVE_WINDOW) \
  0x0000000000000000000000000000000000000000000000000000000000000000 \
  $(cast keccak "outcome-voting-set-active-window") \
  --rpc-url $BASE_SEPOLIA_RPC_URL --private-key $DEPLOYER_KEY
```

Verify activation:
```bash
cast call $OUTCOME_VOTING_PROXY 'activeWindow()(uint256)' --rpc-url $BASE_SEPOLIA_RPC_URL
# → 1800 (or whatever value you set)

cast call $OUTCOME_VOTING_PROXY 'quorumThreshold()(uint256)' --rpc-url $BASE_SEPOLIA_RPC_URL
# → ceil(activeCount * 2/3), floored at MIN_VALIDATORS (3)
```

## Validator-side requirements

Validators must run v1597+ to participate in liveness tracking. v1597 adds:
- `ChainClient.heartbeat()` — posts `OutcomeVoting.heartbeat()` tx
- `heartbeat_loop` background task — auto-fires when `block.number - lastActiveBlock > activeWindow/4`
- OV ABI additions: `activeWindow`, `activeCount`, `isActive`, `lastActiveBlock`

If a validator is on pre-v1597 code when step 2 executes, their `lastActiveBlock` stays 0 and they'll drop out of the active denominator on their first stale check. Remediation: pull v1597+, restart, first heartbeat ticks them back in.

Submitting any vote also ticks liveness, so validators with normal audit activity don't strictly need heartbeat — it's insurance for dry spells.

## Behavior after activation

- Kooltek (UID 189) offline → misses heartbeat window → drops out of `activeCount` → quorum among remaining 5 validators is `ceil(5*2/3) = 4`, reachable with 0/1/2/86/213.
- Kooltek comes back → heartbeat → rejoins active count → quorum recomputes.
- All 6 offline → `activeCount = 0`, floor MIN_VALIDATORS=3 kicks in → `quorumThreshold() = 2` but no one can vote to reach it (all inactive). Settlement stalls until enough recover.

This is the entirety of P0-11. No USDC bonds, no oracle, no challenge windows. Just: if you're not active, you don't count toward the denominator.

## Rollback

```bash
# Schedule + execute setActiveWindow(0) to revert to legacy behavior
cast send $TIMELOCK "schedule(...)" \
  $OUTCOME_VOTING_PROXY 0 \
  $(cast calldata "setActiveWindow(uint256)" 0) ...
```

## Emergency pause

```bash
cast send $OUTCOME_VOTING_PROXY 'pause()' --rpc-url $BASE_SEPOLIA_RPC_URL --private-key $PAUSER_KEY
```
