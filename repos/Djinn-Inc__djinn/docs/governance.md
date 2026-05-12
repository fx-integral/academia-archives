# Djinn Protocol Governance

This document describes the governance surface of Djinn Protocol: who can
change what, under which time constraints, and how the protocol treasury
receives and disburses the 0.5% protocol fee.

**Audience:** operators with signing authority, external reviewers, and
users who want to verify on-chain that governance matches what is
documented here.

**Scope:** on-chain control surface only. Editorial / off-chain decisions
(branding, website content, Discord moderation) are not governed by this
document.

Cross-references:
- `docs/security/key-custody.md` — where each signing key lives and how it
  is rotated.
- `docs/runbook-emergency-pause.md` — emergency freeze procedure.
- `docs/runbook-emergency-recovery.md` — post-freeze upgrade / refund flow.
- `MAINNET_BLOCKERS.md` P1-07, P1-13 — pre-launch gates this doc closes.

## TL;DR

| Role | Testnet (Base Sepolia) | Mainnet target (required before launch) |
|---|---|---|
| Contract proxy owner | `TimelockController` (`0x37f41EFf…`) | New `TimelockController` on Base mainnet |
| Timelock proposer | Deployer EOA (`0xD717b5fb…`) | Safe multisig, ≥3-of-5 |
| Timelock executor | `anyone` (`0x0000…0000`) | `anyone` (still open, timelock delay is the brake) |
| Timelock canceller | Deployer EOA | Safe multisig, same as proposer |
| Timelock min delay | 72 seconds | 72 hours |
| `Audit.protocolTreasury()` (fee recipient) | Placeholder EOA (`0xE4c7Dc9F…`) | Safe multisig, ≥2-of-3 (may be same multisig as proposer) |
| Pauser (Escrow, Audit, CreditLedger) | Deployer EOA | Safe multisig OR dedicated on-call key |

Everything below expands each row with rationale, verification command,
and the upgrade path from the testnet state to the mainnet state.

## 1. TimelockController

The `TimelockController` at `0x37f41EFfa8492022afF48B9Ef725008963F14f79`
(Base Sepolia) owns every UUPS proxy in the system. A contract upgrade or
any admin-function call on a proxy must flow through this contract: a
proposer calls `schedule(...)` with a target + calldata, the timelock
enforces `minDelay` before anyone can call `execute(...)`. This is the
outer safety net against a compromised deployer key.

### Roles

- **PROPOSER_ROLE**: can schedule operations. On testnet held by the
  deployer EOA `0xD717b5fbA93F123f6ad530ae2Ab327B4DcDa1e37`. On mainnet
  this role **must** be held by a Safe multisig — a single-key
  proposer on mainnet means a compromised dev box can schedule any
  upgrade, and the 72h delay is the only thing standing between that
  compromise and contract-level damage.
- **EXECUTOR_ROLE**: can execute an already-scheduled operation after
  its delay elapses. Granted to `address(0)` so anyone can execute —
  this is intentional. The security property is the delay; who calls
  `execute(...)` doesn't change what happens, and restricting
  execution can actually deadlock a pause/unpause if the restricted
  party is unavailable.
- **CANCELLER_ROLE**: can cancel a scheduled-but-not-yet-executed
  operation. On testnet held by the deployer EOA. On mainnet held by
  the same Safe multisig as proposer — this means a "scheduled-then-
  reviewed-bad" upgrade can be cancelled by the same signers who
  proposed it, without waiting for the delay to elapse on a bad op.
- **TIMELOCK_ADMIN_ROLE**: administers the other roles. On a standard
  OpenZeppelin deployment this is held by the timelock itself, and
  role changes must flow through a scheduled timelock operation
  (recursive). `verify-ownership.sh` asserts this.

### Minimum delay policy

| Network | `getMinDelay()` | Rationale |
|---|---|---|
| Base Sepolia | 72s | Testnet iteration speed. Not a security posture. |
| Base mainnet (required) | 72h (≥259200s) | Matches FEE_CLAIM_DELAY budget (96h) with 24h operational slack. Enough time for operators to pause + users to read the governance notice + external reviewers to flag a bad upgrade. |

**Deploy-time invariant:** the floor is encoded as a chain-ID branch in
`contracts/script/Deploy.s.sol:212` (`minDelay = (chainid == 8453) ? 259200 : 72`).
`Deploy.s.sol::_verify()` then re-asserts
`timelock.getMinDelay() >= expectedMinDelay` as defense-in-depth, so a
regression that ships mainnet with a short delay fails the deploy loudly
rather than silently. `scripts/verify-ownership.sh` repeats the same
check post-deploy against the live chain.

**Change-management of the delay itself:** calling
`TimelockController.updateDelay(uint256)` requires a scheduled timelock
operation targeting the timelock itself. That is, shortening the delay
from 72h requires waiting out 72h. This is the desired property.

### Verification

Role identifiers are the standard OpenZeppelin
`keccak256("PROPOSER_ROLE")` / `keccak256("EXECUTOR_ROLE")` / etc.;
compute them fresh with `cast keccak` rather than pasting the hash
bytes literally (avoids typo risk and keeps this doc readable).

```bash
TIMELOCK=0x37f41EFfa8492022afF48B9Ef725008963F14f79
DEPLOYER=0xD717b5fbA93F123f6ad530ae2Ab327B4DcDa1e37
PROPOSER_ROLE=$(cast keccak "PROPOSER_ROLE")
EXECUTOR_ROLE=$(cast keccak "EXECUTOR_ROLE")
RPC=https://sepolia.base.org

# minDelay check
cast call --rpc-url $RPC $TIMELOCK "getMinDelay()(uint256)"
# Expected: 72

# Proposer check (deployer EOA on testnet)
cast call --rpc-url $RPC $TIMELOCK \
  "hasRole(bytes32,address)(bool)" $PROPOSER_ROLE $DEPLOYER
# Expected: true

# Executor-open check (address(0) holding EXECUTOR_ROLE means anyone)
cast call --rpc-url $RPC $TIMELOCK \
  "hasRole(bytes32,address)(bool)" $EXECUTOR_ROLE \
  0x0000000000000000000000000000000000000000
# Expected: true
```

The mainnet equivalents of these commands go into `scripts/verify-ownership.sh`
at deploy time; the deploy fails if any of them mismatch.

## 2. Multisig policy (mainnet)

Djinn uses a Gnosis Safe (`safe.global`) deployed on Base mainnet as the
proposer multisig. The same Safe holds `PROPOSER_ROLE`, `CANCELLER_ROLE`,
and `Audit.protocolTreasury()`.

### Signers

Pre-launch, the signer set is finalized by Djinn Inc. leadership.
Individual signer identities and hardware-wallet fingerprints are
recorded in `docs/security/key-custody.md` **after** the Safe is
deployed; that document is the source of truth for who holds which
hardware device. This file describes only the policy.

**Signer target:** ≥3-of-5. Signers are drawn from:

1. Founder / primary operator (hardware wallet, cold storage)
2. Secondary operator / on-call (hardware wallet, hot path for pause
   ops)
3. External reviewer / auditor (hardware wallet, cold)
4. Legal / entity officer (hardware wallet, cold)
5. Emergency-only signer (hardware wallet, physically separated
   location, used only for incident response)

**Why 3-of-5 and not 2-of-3:**
- 2-of-3 would deadlock on a single signer loss until recovery
- 3-of-5 tolerates loss or compromise of one signer without rush
- 5-signer quorum is still sign-able in hours, not days
- The executor role is open so pause ops don't require multisig
  signatures — only upgrades do.

### Treasury multisig

`Audit.protocolTreasury()` receives the 0.5% protocol fee (see §3).
It holds accumulated protocol fees in USDC until they are withdrawn
by a multisig-signed transaction.

**Signer target:** ≥2-of-3. Can be the same Safe as the proposer, in
which case all governance is consolidated to one signer set; or a
separate Safe with a lower quorum so treasury operations don't require
the full governance set. Current plan: **single combined Safe with
3-of-5 threshold**, because treasury withdrawal is not more sensitive
than a contract upgrade and consolidating reduces key-management
surface.

### How to rotate a signer

Signer changes on the Safe are themselves Safe transactions:
`addOwnerWithThreshold(address, uint256)` or
`removeOwner(address, address, uint256)`. A signer rotation requires
the current quorum (3-of-5). Rotation procedure:

1. New signer generates keys on a fresh hardware wallet.
2. New signer's address is proposed as a Safe transaction by any
   current signer.
3. Other signers review (physical call, not just email) and sign.
4. On confirmation, outgoing signer signs `removeOwner` (if leaving)
   or the current threshold signs `addOwnerWithThreshold` (if adding).
5. `docs/security/key-custody.md` is updated in the same commit as
   the on-chain change. PR merge and on-chain tx must land together or
   the doc/chain divergence is a P0 incident.

## 3. Protocol treasury (fee flow)

### On-chain mechanics

`Audit.sol` charges a `PROTOCOL_FEE_BPS = 50` (0.5%) fee on every
settled signal. The fee is slashed from the genius's collateral at
settlement time and forwarded to the address stored in
`Audit.protocolTreasury()`.

Relevant code paths:
- `contracts/src/Audit.sol:429` — compute fee at settlement
- `contracts/src/Audit.sol:453` — `collateral.slash(genius, fee, protocolTreasury)`
- `contracts/src/Audit.sol:147` — `setProtocolTreasury(address)` (owner-only)

`setProtocolTreasury` is `onlyOwner`, and the owner is the
TimelockController. So changing the treasury address requires a
scheduled timelock operation, the same delay as any upgrade.

### Current state (testnet)

```bash
cast call --rpc-url https://sepolia.base.org \
  0xCa7e642FE31BA83a7a857644E8894c1B93a2a44E \
  "protocolTreasury()(address)"
# Returns: 0xE4c7Dc9F1B8c44000D2E5E720b0117A5242F2382
```

This EOA (`0xE4c7Dc9F…`) is a placeholder for testnet — no-code, nonce
zero. It is a test sink that receives testnet USDC fees; control of its
private key is not load-bearing because testnet USDC has no cash value.
This address **must not** be used on mainnet.

### Mainnet target

1. Deploy a Gnosis Safe on Base mainnet with the signer set from §2.
2. Record its address.
3. Initial deployment (`Deploy.s.sol`) passes the Safe address as the
   `_treasury` parameter to `Audit.initialize(...)`.
4. `verify-ownership.sh` asserts `Audit.protocolTreasury()` returns
   the documented Safe address.
5. Any change to the treasury address requires a scheduled timelock
   operation (72h delay). The upgrade procedure will be documented in
   `docs/runbook-treasury-rotation.md`; per §8 this runbook is a
   pre-launch hygiene item rather than a launch gate — the generic
   timelock-upgrade procedure in §6 covers the on-chain mechanics.

### Reconciliation

Protocol fees paid on-chain are logged via `AuditSettled(..., protocolFee)`
events (see `contracts/src/Audit.sol:472`). The treasury's USDC balance
should equal the sum of all `protocolFee` fields across `AuditSettled`
events since inception, minus treasury withdrawals.

A weekly reconciliation script (`scripts/reconcile-treasury.sh`, a
pre-launch hygiene item per §8; manual reconciliation against the
subgraph covers the interim) compares:
- on-chain: `sum(protocolFee) from AuditSettled events`
- on-chain: `USDC.balanceOf(treasury) + sum(withdrawals)`

Any divergence beyond rounding suggests either a missed event, a
settlement bug, or an unauthorized withdrawal. Once the reconciliation
script exists, a post-launch divergence is cause for an emergency
pause per `runbook-emergency-pause.md`. Pre-launch, while
`reconcile-treasury.sh` is still unwritten, this reconciliation is
performed manually against the subgraph and is not a launch gate (§8).

### Treasury withdrawal policy

The treasury Safe is free to withdraw fees to cover operational costs
(infrastructure, audits, legal, validator incentives beyond emissions,
etc.). There is **no on-chain constraint** on what the treasury does
with withdrawn USDC — this is intentional; encoding a spending policy
on-chain would couple protocol upgrades to treasury ops and add
attack surface without adding security. The Safe multisig's signers
are the policy.

Djinn Inc. publishes a quarterly transparency report listing:
- Total fees accrued (from `AuditSettled` events)
- Treasury balance at quarter-end
- Withdrawals during the quarter, with counterparty and purpose

The first transparency report covers the mainnet launch quarter and
is a post-launch deliverable, not a pre-launch gate.

## 4. Contract proxy ownership

Every upgradeable contract is a UUPS proxy whose `owner()` is the
TimelockController. The full list:

| Contract | Proxy address (Base Sepolia) | Owner |
|---|---|---|
| SignalCommitment | `0x4712479B…` | `TimelockController` |
| Escrow | `0xb43BA175…` | `TimelockController` |
| Collateral | `0x71F0a8c6…` | `TimelockController` |
| Account | `0x4546354D…` | `TimelockController` |
| Audit | `0xCa7e642F…` | `TimelockController` |
| CreditLedger | `0xA65296cd…` | `TimelockController` |
| OutcomeVoting | `0xAD534f4C…` | `TimelockController` |
| KeyRecovery | `0x496919DB…` | `TimelockController` (non-proxy; see P1-18) |

On mainnet the owner is the new mainnet `TimelockController`. The
deploy script asserts this before broadcasting.

## 5. Pauser role

Separate from timelock governance, each of Escrow, Audit, CreditLedger,
and SignalCommitment has a `pauser` address that can call `pause()` /
`unpause()` with immediate effect (no timelock). This is the emergency
freeze surface.

- **Testnet:** pauser is the deployer EOA.
- **Mainnet target:** pauser is either the same Safe multisig OR a
  dedicated on-call hot wallet (hardware wallet, physically held by
  the primary on-call operator). Decision deferred to launch — a hot
  wallet lets a single operator pause instantly without gathering
  quorum; a multisig requires quorum but reduces blast radius of
  operator-key theft. Trade-off:
  - Hot wallet → pause in seconds, one-person-compromise = false-pause
    (recoverable via timelock-gated `unpause`).
  - Multisig → pause in minutes, quorum-of-N-compromise required for
    false-pause (much harder for attacker).
  **Current mechanism:** each pausable contract exposes a single
  `pauser` address slot (see `contracts/src/Audit.sol:64`, `setPauser`
  at `:517`). That slot can hold either a hot-wallet EOA (fast pause,
  single-key risk) or a Safe multisig (quorum-gated pause). A
  multi-pauser registry that lets both a hot wallet and a multisig
  pause independently would require a contract upgrade and is tracked
  as a post-launch enhancement, not a launch gate. Launch decision is
  a single address per contract; current preference is the same Safe
  multisig as the proposer, on the grounds that on-call pause is rare
  and quorum reduces blast radius of a stolen operator key.

Unpause always flows through the timelock: even the pauser cannot
unilaterally unpause. This is load-bearing — it means a false pause is
a minor incident (wait out the timelock), but an attacker who steals
the pauser key cannot immediately unpause to drain funds.

Verification of pauser role per contract is in
`scripts/verify-ownership.sh`.

## 6. Change-management flowchart

```
Upgrade request
    │
    ├── Routine upgrade (new impl, non-emergency)
    │       │
    │       ▼
    │   1. Proposer multisig signs schedule(target, calldata, delay=72h)
    │   2. 72h delay elapses
    │   3. Anyone calls execute(id)
    │   4. verify-ownership.sh + smoke tests
    │
    ├── Emergency freeze (something is wrong, pause now)
    │       │
    │       ▼
    │   1. Pauser key signs pause() (immediate)
    │   2. Incident response begins (see runbook-emergency-pause.md)
    │   3. If cause found: prepare upgrade → schedule → wait 72h → execute → unpause
    │   4. If no cause: unpause via scheduled timelock op after investigation
    │
    └── Treasury action (withdraw accumulated fees)
            │
            ▼
        1. Treasury multisig signs ERC20.transfer(recipient, amount)
        2. No timelock (this is a Safe transaction, not a protocol upgrade)
        3. Transparency report logs the withdrawal
```

## 7. What this document does NOT govern

- **User funds in Escrow / Collateral.** These are user-owned; the
  protocol cannot unilaterally move them. Only the user's signature or
  the settlement path can.
- **Validator / miner emissions.** These flow from Bittensor Subnet
  103 via the standard Yuma consensus mechanism. Djinn governance has
  no on-chain hook into subnet emissions.
- **Off-chain content.** Website, documentation, support, social — not
  governed by this document.
- **Bittensor subnet governance.** Subnet 103 has its own governance
  via Bittensor root (owner hotkey), orthogonal to the Base contract
  governance described here.

## 8. Pre-mainnet checklist

Before declaring P1-07 and P1-13 **closed**:

- [ ] Safe deployed on Base mainnet with ≥3-of-5 signer set.
- [ ] `docs/security/key-custody.md` updated with signer hardware-wallet
      fingerprints and physical-location policy.
- [ ] New `TimelockController` deployed on Base mainnet with `minDelay =
      72h`; proposer = Safe; canceller = Safe; executor = `anyone`.
- [ ] All seven UUPS proxies initialized with owner = new timelock.
- [ ] `Audit.protocolTreasury()` returns the Safe address.
- [ ] Pauser role on all pausable contracts set per §5.
- [ ] `scripts/verify-ownership.sh` passes on mainnet.
- [ ] One rehearsal pause/unpause drill completed on Base Sepolia with
      the full signer set (per `MAINNET_BLOCKERS.md` P0-04). A mainnet
      rehearsal is not required because (a) it would cost ≥72h of
      real-funds downtime by design, and (b) the Sepolia rehearsal
      exercises the same contract code and the same signer set.
- [ ] Quarterly transparency-report template published.

Items that do **not** block launch but are pre-launch good hygiene:

- [ ] `scripts/reconcile-treasury.sh` cron-scheduled.
- [ ] `docs/runbook-treasury-rotation.md` written (covers rotating the
      treasury address via timelock).

## 9. Changelog

- **2026-04-18** — initial draft. Closes autonomous portion of P1-07
  and P1-13. Human sign-off (Safe deploy, signer set, hardware wallet
  distribution) still required before either can move to `closed`.
