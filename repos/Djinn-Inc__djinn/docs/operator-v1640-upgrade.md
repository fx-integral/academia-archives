# Operator Upgrade Notice: v1640 (P0-01 fix)

**TL;DR:** The settlement pipeline has been at zero AuditSettled events for the past 28h+ because `OutcomeVoting.proposeSync` is jammed at nonce=11. v1640 fixes the underlying validator_sync logic; once all 5 operators upgrade, owner can bump syncNonce via timelock to clear the jammed state.

## What's broken right now

Run this against the OV proxy on Base Sepolia:

```bash
cast call --rpc-url https://base-sepolia-rpc.publicnode.com \
  0xAD534f4CAB13707BD4d65e4EF086A455e6A643e5 "syncNonce()(uint256)"
# returns: 11
```

All 5 OV signers (UID 0/1/2/86/213) have `hasSyncVoted[11]=true`, but each voted on a DIFFERENT 4-validator subset because each operator's metagraph view transiently excluded a different peer (anti-spam health checks rejecting different validators at the moment of proposal). No proposal hash reached 4/5 quorum. `submitVote` is gated on a stable validator set, so 38–43 ready_for_settlement batches per operator are stalled.

Confirm via `cast run <reverted-tx-hash>` on any recent signer→OV revert: the custom error is `AlreadySyncVoted(0xfb5c46be)`.

## What v1640 changes

**Before (v1639 and earlier):** `validator_sync.sync_once()` proposed `discovered_sorted` verbatim whenever it differed from on-chain. Transient peer-discovery failures could remove peers from any operator's view.

**After (v1640):** Only ADDITIONS are proposed. The proposal is `union(on_chain_sorted, discovered_sorted)`. Removals require explicit owner action via timelock. Fail-closed under network glitches.

Tests: 7 passing in `tests/test_validator_sync.py`. No protocol changes, no contract upgrades — pure validator-side hardening.

## How to upgrade

If your validator is on **v1625 or v1626**, watchtower is wedged on
your box. v1625 had a self-heal regression that wrote `git describe`
back to VERSION on every import, leaving the tree dirty. `git pull
--rebase` then refused to run, blocking every subsequent watchtower
cycle. Reset the tree first:

```bash
cd /root/djinn  # or wherever your validator is
git checkout VERSION   # discard the local self-heal pollution
git status             # should show "nothing to commit, working tree clean"
git pull --rebase origin main
git log --oneline -1   # should show 1863161c or later
pm2 restart djinn-validator
sleep 10
curl -s http://127.0.0.1:8421/health | jq -r '.version'
# should read "1640+" or higher
```

If your validator is **v1627 or later**, just:

```bash
cd /root/djinn
git pull --rebase origin main
pm2 restart djinn-validator
```

Watchtower will pick up v1642+ on the next cycle and self-heal the
upgrade path going forward; the manual checkout above is only needed
once to break out of the v1625 wedge.

## After all 5 are on v1640

Reply in this thread with `upgraded` once you've restarted with v1640. After all 5 confirm, Djinn (UID 0 owner) will run a timelock action to bump syncNonce by removing+re-adding one signer. After ~72s the bump executes; with everyone on v1640, no operator will re-propose (no additions visible) and the new nonce stays stable. Settlement pipeline unblocks immediately for the existing 38-43 ready batches per operator.

## Why this matters

Without this, even with every other settlement-side fix landed (BPA/WPA gossip, batch determinism, MPC HTTP submit, etc.), no on-chain vote can land. The validator-set-sync gate was the actual blocker the entire time. v1637's `resolved_signals` filter, v1635's BPA/WPA propagation, v1634's Node 18 polyfill — all real fixes, but none could move the AuditSettled metric past zero while sync was jammed.

— Djinn (UID 0)
