# Deployment & signing-key custody

This document covers the operational story for the Djinn Protocol deployer
key and related signing material: where keys live, what each one can do,
how we rotate them, and what to do if one is suspected compromised.

Scope: deploy-time and governance-time signing keys only. User wallet keys
are out of scope (Djinn is non-custodial; users hold their own keys).

**Audience:** operators with the deployer-key in their possession, and
auditors verifying the operational story before mainnet launch.

## Summary

| Key | Role | Testnet custody | Mainnet custody (required before launch) |
| --- | --- | --- | --- |
| `DEPLOYER_KEY` | Proposes upgrades via TimelockController; deploys initial contracts; funds faucets | Env var on dev box | Hardware wallet (Ledger) OR AWS KMS signer |
| `VALIDATOR_HOTKEY` | Signs validator settlement & attestation transactions from each validator box | Env var on each validator | Env var on each validator (validator boxes are single-purpose, low-blast-radius) |
| `MINER_HOTKEY` | Signs miner attestations from each miner box | Env var on each miner | Same as validator |
| `FEE_RECIPIENT` | Receives protocol fees from Escrow (0.5% of notional) | EOA | Safe multisig (documented in `governance.md`; tracked separately under P1-13) |

The TimelockController is the outer safety net: even if `DEPLOYER_KEY` is
compromised, an attacker cannot execute a contract upgrade for at least the
configured timelock delay (testnet: 72s · mainnet target: 72h), giving
operators time to pause contracts and rotate before damage lands.

## Blast radius

### What `DEPLOYER_KEY` can do
- Propose new upgrades to UUPS proxies (requires timelock delay before execution).
- Execute already-queued timelock operations (this role is `anyone`, so the deployer executing is incidental, not required).
- Call owner-only admin functions on contracts it still owns directly (NOTE: on mainnet, all contract proxies must be owned by the TimelockController, not the deployer EOA — verified by `scripts/verify-ownership.sh`).
- Spend any ETH or USDC held on its address. We keep this balance as low as possible (gas budget only).

### What `DEPLOYER_KEY` cannot do
- Drain user funds. User balances live in the Escrow and Collateral contracts; only `msg.sender` or the settlement path can move them.
- Invoke a settlement that doesn't reach the quorum threshold on OutcomeVoting.
- Bypass the timelock. Every admin-sensitive state change has to wait out the delay, unless the contract is paused (which the Pauser role can do, but the Pauser does not have the ability to upgrade — it can only freeze).

### What `FEE_RECIPIENT` can do
- Withdraw accumulated protocol fees. On mainnet this is the Safe multisig; signer set documented in `governance.md`.

## Current state (testnet)

- `DEPLOYER_KEY` is a private key in a `.env` file on the operator dev box. It is never committed to git; `.env` is gitignored and a `.env.example` ships with placeholder.
- Deployer address (Base Sepolia): `0xD717b5fbA93F123f6ad530ae2Ab327B4DcDa1e37`.
- The deployer is the timelock proposer; executor is `anyone`. Delay is 72 seconds (testnet convenience, not a security posture).
- `scripts/deploy_base.sh` reads `DEPLOYER_KEY` from env, runs `forge script Deploy.s.sol --broadcast --verify`. All transactions are signed locally on the deployer box.
- No HSM, no multisig, no air-gapping. **This is testnet-only and must change before mainnet.**

## Required before mainnet launch

The following is the minimum acceptable custody posture for the mainnet deployer key. It is **gating** on P1-14.

### Option A (preferred): hardware wallet

1. Provision a dedicated Ledger (Nano S+ or Nano X) for the mainnet deployer. Buy from the manufacturer directly; do not use any Ledger that has been out of sight.
2. Generate a fresh seed on the Ledger itself. Seed never touches a computer. Write the 24 words onto the supplied metal backup; store the metal backup in a safe separate from the daily-use operator box.
3. Record the Ledger's derived address. This is the new mainnet deployer address. It will be funded with a minimal gas budget (≤ 0.05 ETH at any time).
4. Migrate `scripts/deploy_base.sh` to support `--ledger` mode:
   ```bash
   forge script Deploy.s.sol --ledger --sender $DEPLOYER_ADDRESS --mnemonic-indexes 0 --rpc-url $BASE_RPC_URL --broadcast
   ```
   (Open TODO: the script currently assumes `DEPLOYER_KEY` env var. Add a `--ledger` flag that swaps in the hardware-wallet path.)
5. Every deploy and every governance propose requires the Ledger to be physically connected and the operator to press both buttons. No key material ever leaves the device.

### Option B: AWS KMS signer

1. Provision a KMS key (asymmetric, SECP256K1, signing) in a dedicated AWS account with SCP-enforced access limits. Only two named IAM roles can use it.
2. Use `kms-ethereum-signer` or `eth-keystore`-compatible wrapper to perform `eth_signTransaction` against the KMS key. The private key never leaves AWS.
3. Audit trail: every signature operation is in CloudTrail. Alerts fire on any unexpected invocation (CloudWatch + PagerDuty).
4. Adapt `scripts/deploy_base.sh` to support a `--kms` flag that routes signing through the KMS adapter.

Option A is preferred because it's self-custodied and doesn't introduce AWS as a dependency of the protocol. Option B is acceptable if we have a reason (e.g., multi-operator team that needs 24/7 on-call access without physical Ledger handoff).

## Rotation

Rotation is triggered by: (a) a scheduled rotation (annual, whichever comes first), (b) a suspected compromise, (c) a change in the operator team (someone with device access leaves).

Procedure:

1. Generate a new deployer keypair using the chosen custody method (new Ledger or new KMS key).
2. From the **current** deployer, submit a `TimelockController.schedule` operation that updates the deployer address everywhere it's referenced (none today, but scripts pin it; see `scripts/transfer-ownership.sh`).
3. Wait out the timelock delay.
4. Execute the rotation. Verify the new address is recognized by the timelock (`timelock.hasRole(PROPOSER_ROLE, newDeployer)` returns true; old deployer revoked).
5. Drain residual gas balance from the old deployer to the new deployer.
6. Destroy the old device:
   - Ledger: factory reset, then physically destroy the device (snip the USB controller).
   - KMS: `aws kms schedule-key-deletion --key-id <old> --pending-window-in-days 7`; verify tombstone in CloudTrail.
7. Document the rotation in `docs/security/rotation-log.md` (create if absent) with date, reason, new address.

## Incident response

### Suspected leak of `DEPLOYER_KEY`

**Assume compromise. Act as if the attacker has the key.**

T+0: Pause pauseable contracts immediately. Any operator with a separate `PAUSER_ROLE` key can do this. See `docs/runbook-emergency-pause.md` for the exact commands.

T+5min: Drain residual ETH/USDC from the compromised deployer address to a safe EOA. Even if the attacker sees the mempool, a high-gas-price drain typically wins the race for small balances.

T+15min: Begin rotation (see above). Schedule an `updateDelay` or `cancel` timelock op if the attacker has already queued something malicious.

T+30min: Communicate. Post to the @djinn_gg X, Discord, and `security@djinn.gg` mailing list. Say what happened, what's paused, what the ETA is for re-enabling.

T+24h: Post-incident writeup in `docs/incidents/` with timeline, blast radius, root cause, mitigation.

### Lost device (Ledger)

The metal backup is the recovery material. If the Ledger is lost but the seed phrase is intact, restore onto a new Ledger and proceed normally. If the seed phrase is also lost, treat as a suspected compromise (the device is now in someone else's hands) and rotate.

### Compromised operator workstation

Even if `DEPLOYER_KEY` itself is held on a Ledger, an attacker with a compromised workstation can:

- Watch which transactions the operator signs.
- Potentially trick the operator into signing a different transaction than the one the UI shows (ledger blind-signing risk).

Mitigation:
- All mainnet-signing transactions must be verified on the Ledger's own screen (no blind-signing mode).
- Use `forge script --slow --resume` style to pause and re-verify at each step.
- The operator workstation should be a dedicated box or an isolated VM with no other purpose, reimaged on a cadence.

## Validator & miner hotkey custody

Hotkeys on validator and miner boxes are lower-risk than the deployer key because:

- They cannot propose upgrades or execute admin actions.
- They can only sign within the bounds of their registered UID on the Bittensor metagraph.
- A compromised validator hotkey lets an attacker take over that one validator; other validators' quorum continues to protect settlement.

That said:
- Rotate validator/miner hotkeys annually or when a team member with box access leaves.
- Store the hotkey in a `.env` file with `0600` permissions, owned by the service user.
- Never copy a validator hotkey to a laptop. If needed for rotation, regenerate on the target box.

## Verification checklist (pre-mainnet gate)

Before the mainnet deployer can hold the key, all must be true:

- [ ] Deployer is a Ledger or KMS-backed address, verified by `cast wallet address --ledger` or KMS CLI.
- [ ] `scripts/deploy_base.sh mainnet` signs via hardware-wallet or KMS path, not via `DEPLOYER_KEY` env var.
- [ ] Timelock minimum delay is at least 72h (not 72s).
- [ ] All 7 contract proxies are owned by the TimelockController, not the deployer directly. Verified by `scripts/verify-ownership.sh` (create if absent).
- [ ] At least one documented rotation drill has been performed on Base Sepolia.
- [ ] This document has been reviewed by at least one external auditor.

## References

- `scripts/deploy_base.sh` — deploy entry point.
- `scripts/transfer-ownership.sh` — hand contract ownership to TimelockController.
- `docs/runbook-emergency-pause.md` — pause procedure for compromise scenarios.
- `docs/governance.md` — (planned, P1-07) multisig signer set and timelock policy.
- [MAINNET_BLOCKERS.md](../../MAINNET_BLOCKERS.md) P1-07, P1-14 — related blockers.
