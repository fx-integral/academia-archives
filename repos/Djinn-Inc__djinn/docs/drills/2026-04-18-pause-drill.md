# Emergency pause drill — 2026-04-18

**P0-04 · Emergency pause drill** — first live exercise of the Escrow pause /
timelock-gated unpause flow on Base Sepolia.

**Outcome:** PASS. Pause landed on-chain, unpause was scheduled through the
TimelockController, the 72s minimum delay elapsed, the scheduled operation
was executed, and `paused()` returned to `false` on verification.

## Environment

| Field | Value |
|---|---|
| Chain | Base Sepolia (84532) |
| Escrow proxy | `0xb43BA175a6784973eB3825acF801Cd7920ac692a` |
| Timelock | `0x37f41EFfa8492022afF48B9Ef725008963F14f79` |
| Pauser EOA | `0xD717b5fbA93F123f6ad530ae2Ab327B4DcDa1e37` |
| Timelock min delay | 72s (testnet; mainnet will be 72h) |
| Driver | `scripts/drill-pause-unpause.sh` (tagged v1284) |

## Timeline

| Step | Block | Tx | Timestamp (UTC) |
|---|---|---|---|
| `pause()` sent | 40378485 | `0x06d46b57517c7558fff197988b8c926ffb8e0bcd44ec211f9efb38f49fdfda2b` | 2026-04-18 15:14:17 |
| `paused()` verified `true` | — | (retry after RPC load-balancer lag) | 2026-04-18 15:14:25 |
| Unpause scheduled via timelock | 40378507 | `0x2cc5059677b270e4e0b576a8e137ad5248bc74561339fc7b616dbee8766ebd12` | 2026-04-18 15:15:02 |
| `isOperationReady()` returned `true` | — | — | 2026-04-18 15:16:24 |
| Unpause executed | 40378556 | `0x58d7ab7c120cf2c7ffe43c326d0a42ef63d5163c5aa73f86001b6e6e53017a11` | 2026-04-18 15:16:38 |
| `paused()` verified `false` | — | — | 2026-04-18 15:16:40 |

## Timelock operation details

- `op_id = 0xa4c36ab31a46d83053131f187d0cf5f7d9d25d4bca521d715634ccc7e6518665`
- `salt = 0xee777524e11455459e31c93a832737691be6738bee3cda40d2b7a24da4abeae0`
- `predecessor = 0x0000…0000`
- `target = Escrow proxy`
- `data = unpause()` selector `0x3f4ba83a`

## Basescan links

- pause: https://sepolia.basescan.org/tx/0x06d46b57517c7558fff197988b8c926ffb8e0bcd44ec211f9efb38f49fdfda2b
- schedule: https://sepolia.basescan.org/tx/0x2cc5059677b270e4e0b576a8e137ad5248bc74561339fc7b616dbee8766ebd12
- execute: https://sepolia.basescan.org/tx/0x58d7ab7c120cf2c7ffe43c326d0a42ef63d5163c5aa73f86001b6e6e53017a11

## Observed issues and fixes

1. **RPC load-balancer state lag.** First run after pause landed saw
   `paused() == false` for a single `cast call` even though the receipt showed
   the `Paused` event emitted. Hypothesis: `sepolia.base.org` fronts multiple
   nodes and the follow-up read hit one that was a block behind state-root
   propagation.

   Patched `scripts/drill-pause-unpause.sh` to retry both post-pause and
   post-execute verifications up to 5× with 3s backoff. Follow-up reads all
   converged within the first retry on the second run.

2. **Testnet only; mainnet delay is 72h.** The script hard-rejects when
   `min_delay > 600s` to prevent accidentally scheduling a production
   unpause without the full operator runbook. See `--force` to override
   during a planned mainnet exercise (still requires a comment explaining
   why).

## What we learned about the flow

- Pause fires in a single EOA tx (no timelock), so the "minutes to degrade"
  budget from runbook-emergency-pause.md was honored easily — ~3s from
  decision to `paused() == true` on testnet.
- The symmetric inverse (pause fast, unpause slow) behaves as designed:
  even on a 72s timelock, we couldn't short-circuit it — `execute` reverted
  until `isOperationReady()` flipped.
- Frontend / validator / miner graceful-degrade behaviour under pause was
  NOT exercised in this run (the drill was contract-level only). Follow-up
  drill item: re-run with a live validator+miner pair pointed at a test
  frontend, capture screenshots of the "maintenance" banner and the
  validator's refusal to accept new commits.

## Follow-up work

- [ ] Extend drill to full stack (validator + miner + frontend) — schedule
  before mainnet cutover. Tracked as P0-04 residual in MAINNET_BLOCKERS.md.
- [ ] Add a second drill that pauses `Audit` instead of `Escrow` — the
  symmetric property (pauser EOA fast, unpause via timelock) should hold
  identically, but each contract's pauser set must be verified independently.
- [ ] Add a `--dry-run` CI check that runs the drill against an anvil
  fork so we catch regressions in the script before they land in main.

## Artifacts

- Full drill log: captured inline in timeline table; raw stdout was in
  `/tmp/pause-drill.log` (ephemeral).
- Script: `scripts/drill-pause-unpause.sh`
- Runbook that this drill satisfies: `docs/runbook-emergency-pause.md`
