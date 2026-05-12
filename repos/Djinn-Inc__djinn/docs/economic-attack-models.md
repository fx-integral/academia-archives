# Economic Attack Models

Red-team document for mainnet cutover. Enumerates concrete attacker
types, estimates cost-of-attack and expected return, maps each to
existing mitigations (with live code references), and calls out
residual gaps that cap conservative launch bounds.

Paired with [`VULNERABILITY_REPORT.md`](../VULNERABILITY_REPORT.md)
(code-level audit, 2026-03-29) and the `project_incentive_attack_surface`
memory note (game-theory sketch, 2026-04-11). This doc synthesises both,
and is the autonomous portion of **P0-06** in `MAINNET_BLOCKERS.md`.

Last updated: 2026-04-19.

---

## 1. System parameters at launch

Economics only make sense against real numbers. These are the bounds
assumed when scoring each attack below. They are deliberately
*conservative* — the initial mainnet bound should respect them, not
stretch them.

| Parameter | Value at soft-launch | Source |
|-----------|---------------------|--------|
| Chain | Base mainnet, chainId 8453 | `contracts/deploy` |
| Stable asset | Circle USDC (`0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913`) | Coinbase/Circle |
| Subnet | Bittensor SN103, 10 validator permits, ~256 miner slots | metagraph |
| Shamir parameters | `k=3 of n=7` once validator set stabilises (currently 2/3 on testnet) | validator config |
| On-chain per-purchase cap | **$1,000,000 USDC** (hard ceiling, `MAX_NOTIONAL = 1e12`) | `contracts/src/Escrow.sol:146` |
| Per-signal / per-cycle cap (soft-launch) | $500 signal, $2,500 cycle — **policy-level, NOT contract-enforced**; operator-side guard rails + Idiot invite list | ops config |
| On-chain per-batch notional cap | **$20,000,000 USDC** (hard ceiling, `MAX_BATCH_NOTIONAL = 20e12` = `MAX_BATCH_SIZE` (20) × `MAX_NOTIONAL` (1e12)) | `contracts/src/Audit.sol:43` (enforced in `settleByVote`, `earlyExitByVote`, `forceSettle`) |
| Genius collateral ratio | Configurable per signal, enforced in `Collateral.sol` | contract |
| Timelock delay | 72 hours on mainnet (72s on testnet) | `TimelockController` |
| Circuit breaker | CUSUM tracker keyed by hotkey, feature-flagged | `validator/djinn_validator/core/circuit_breaker.py` |
| Emergency pause | 6 of 7 user-facing contracts inherit `PausableUpgradeable` (SignalCommitment, Escrow, Collateral, Account, Audit, CreditLedger). `KeyRecovery` is **NOT yet Pausable** — adding it requires a UUPS upgrade with storage-layout validation (tracked in MAINNET_BLOCKERS P1-27) | governance multisig |

Soft-launch bound: **$500 per-signal cap, $2,500 per-cycle cap,
invite-only Idiot list**, until three independent audits clear. This
doc exists to define what "clear" means.

---

## 2. Actor taxonomy

Every attack collapses to one or a coalition of these actors:

1. **Outsider** — no protocol role, no TAO, no stake. Can only hit
   public HTTP surfaces and submit ordinary txs.
2. **Idiot** (buyer) — has USDC in Escrow, can purchase signals.
   Knows only what they've bought.
3. **Genius** (analyst) — has collateral in `Collateral`, can commit
   signals. Controls the plaintext of their own picks.
4. **Miner** — holds TAO, registered on SN103. Serves odds/TLSN proofs.
   Scored by validator consensus, weighted by Yuma.
5. **Validator** — holds stake, holds a SN103 permit. Runs MPC shares,
   scores miners, votes outcomes on-chain, schedules audits.
6. **Operator** — human with a seat on the governance multisig or
   infra access (RPC, DNS, hosting). Not a protocol role but a human
   one. Compromises here bypass on-chain guards.
7. **Coalition** — any subset above acting together.

Attackers compose. "Genius + miner cluster" is the most dangerous
type because the genius controls the payoff condition and the miner
cluster controls the odds reporting that decides it.

---

## 3. Attack models

Format per entry:

> **A-N · Title**
> *Attacker:* actor type
> *Goal:* what they extract
> *Cost:* gas + TAO registration + USDC at risk + labor
> *Expected return:* optimistic, not adversary-friendly
> *ROI:* cost vs return, with a qualitative verdict
> *Mitigations live:* file paths you can `git blame` today
> *Residual gap:* what would still let the attack work
> *Detection signal:* what should alarm

Attacks are ordered roughly by risk-adjusted impact, not by severity
of any single component.

### A-1 · Genius-miner collusion on outcome odds (oracle poisoning)

*Attacker:* genius + 1–N miners
*Goal:* commit a signal at line X, then have colluding miners report
odds that make the committed side look like the BPA/WPA winner when
consensus closes at settlement, extracting USDC from idiots who
purchased.
*Cost:* collateral for the signal (Genius side), plus bribery or
self-ownership cost of miners. SN103 registration ~0.1 TAO per UID
today; at ~$400/TAO that's $40 per miner.
*Expected return:* per-signal notional cap ($500 soft-launch / $5,000
full-launch). A single successful attack against a full-launch cap
extracts up to $5k gross.
*ROI:* ~50-100x on miner cost alone IF consensus can be shifted; but
shifting median of 10-miner pool requires 5-6 colluders, so real cost
is $200-240 in TAO just for UIDs, before bribery, and scales with how
far from truth the attack is.
*Mitigations live:*
- Consensus uses median, not mean; see `validator/djinn_validator/core/scoring.py`
- CUSUM circuit breaker flags miners whose deviations accumulate beyond
  the tolerance band: `validator/djinn_validator/core/circuit_breaker.py`
  (hotkey-keyed, so UID re-registration doesn't reset trust)
- TLSNotary sampling: on a CUSUM flag, validator requests a notarised
  fetch from a public book; mismatched miners get slashed
- On-chain slash via stake reduction and Yuma weight loss
- Quorum of validators votes outcome; per-call quorum policy lives in
  the OutcomeVoting contract
*Residual gap:*
- **Calibration of CUSUM parameters** — tolerance, decay, flag
  threshold — is not yet tuned against a live adversary. Too tight
  burns TLSNotary cost on normal line drift; too loose lets small
  liars accumulate damage.
- **TLSNotary fetch breadth** — some sportsbooks aggressively block
  automated fetches. A collusion attack on a book with poor TLSN
  coverage has a longer window.
- **Quorum-of-miners for odds publication** is not yet enforced. At
  quiet hours a lone miner can be the only source for a line.
*Detection signal:*
- `circuit_breaker.flagged_count` > 0 during normal operations
- `audit_vote_reverted` or `audit_vote_receipt_timeout` > 0 sustained
- Settlement outcomes skew >60% in favour of a single genius cluster
  over a rolling 500-signal window

### A-2 · Purchase-index oracle extraction (buyer-side)

*Attacker:* idiot
*Goal:* learn the real pick index in the 10-slot decoy array without
actually paying for the full signal, by probing the MPC `available_indices`
path.
*Cost:* per-probe MPC validator call, ~free. Gas for the purchase tx
if the attacker wants a full exchange (~$0.20 at 1 gwei).
*Expected return:* bypasses the economic model; a committed attacker
farms signals for free and resells the plaintext.
*ROI:* asymmetric — each extracted signal is worth its notional to
the attacker at zero marginal cost.
*Mitigations live:*
- Client-side AES-GCM encryption of the pick before Shamir sharing
- Off-chain decoys (DEV-042) hide the real index among 10 slots
- Validators require a real on-chain purchase tx to release shares;
  see `validator/djinn_validator/api/server.py` purchase_signal path
*Residual gap (highest-priority crypto fix):*
- **Cross-check buyer's claimed `available_indices` against
  validator-independent observation**. Right now the buyer supplies
  "which indices my book supports"; the validator trusts it. An
  attacker can supply manipulated vectors to learn index structure.
  This is item #4 in the `project_incentive_attack_surface` memo and
  is the single largest cryptographic gap before mainnet.
- **MPC timing side channel** (M-8 in VULNERABILITY_REPORT): fixed-delay
  padding on MPC responses not yet enforced.
*Detection signal:*
- Rate of MPC calls per signal ID >> 1 per purchase
- Same wallet probing many signal IDs without completing purchase

### A-3 · Sybil miner cluster for score inflation

*Attacker:* outsider → miner
*Goal:* register many miner UIDs under one coldkey, dominate the
odds-reporting pool, extract Yuma emissions regardless of honesty.
*Cost:* ~0.1 TAO per UID registration; at 11-UID cluster (observed in
the wild, coldkey `5HDu6umNUpNCxbrx4h`) ~$440 one-time.
*Expected return:* Yuma emissions share of SN103. At current subnet
price + burn rate, per-UID monthly revenue is ~$0.5-2 (small). But
clusters also block honest miner onboarding by saturating the 256
slots.
*ROI:* weak on emissions alone. The real prize is combining Sybil
with A-1 (oracle poisoning) — sybil gives you the miner count to
shift consensus cheaply.
*Mitigations live:*
- Zero-weight new miners (`DJINN_FF_NEW_MINER_ZERO_WEIGHT`) until
  sample count threshold passed
- Same-coldkey peer notary exclusion (v1169, see
  `project_v1169_sybil_impact`): validators cannot serve as peer
  notaries for miners sharing their coldkey
- Singleton lift (v1171) measurably gives honest singleton miners
  1.6-2.2x the duty per UID vs a sybil cluster's members
- Burn-gate peer-IP allowlist on `/v1/burn/verify`
  (`validator/djinn_validator/api/burn_gate.py::is_allowed_peer_ip`)
  so sybil clusters can't self-verify each other
*Residual gap:*
- **Stake gates on miner registration**. Under flat rewards, a stake
  gate is just a linear capital tax; attackers with more capital
  still win. Real defence is concentrated emissions — top-N miners
  by reliability get disproportionate rewards, driving honest miners
  toward the top and starving sybils — not yet fully wired.
- **Cross-coldkey sybil** (attacker rotates coldkeys per UID) defeats
  the coldkey-based defences. Needs IP/ASN heuristics and TLSN
  fingerprinting.
*Detection signal:*
- `metagraph` audit: >5 miners sharing an IP or /24, with recent
  registration timestamps
- Hotkey cluster where the CUSUM tracker for all members is either
  uniformly quiet (well-coordinated) or uniformly noisy (uncoordinated)

### A-4 · Validator collusion on outcome voting

*Attacker:* 2+ validators with enough combined stake to meet quorum
*Goal:* force-vote the wrong outcome on an audit batch, extracting
USDC from Escrow to the wrong side.
*Cost:* stake acquisition to reach quorum share. SN103 has 10 permit
slots; quorum is currently a configurable majority in OutcomeVoting.
At current stake distribution ~$50k-200k of stake to have decisive
weight on any one vote (rough order-of-magnitude).
*Expected return:* per-batch notional. The on-chain hard cap is
`MAX_BATCH_NOTIONAL = 20e12` ($20M, i.e. `MAX_BATCH_SIZE` × per-purchase
`MAX_NOTIONAL`). During soft-launch the policy-layer per-cycle cap
binds tighter — a single (genius, idiot) batch cannot exceed the
buyer's per-cycle exposure ($2,500 soft-launch, $50,000 full-launch),
so the realistic marginal gain per manipulated batch is ≤ the
per-cycle cap. If the operator layer is bypassed (RPC exploit, admin
key leak, policy-cap regression) the on-chain $20M ceiling binds
instead; stake is also at risk of slash.
*ROI:* bounded by whichever layer is tighter. Under policy caps, ROI
is deeply negative against $50k–200k stake cost. If policy caps are
bypassed, ROI flips positive per batch and mitigation depends on
slash + vtrust loss catching the colluders before they exit.
*Mitigations live:*
- Yuma vtrust: validators whose weights disagree with stake-weighted
  consensus lose their permit
- `MAX_BATCH_NOTIONAL = 20e12` cap (P1-20, enforced in every
  `Audit.sol` settlement path) caps per-batch damage at $20M on-chain;
  policy caps bind tighter in practice
- OutcomeVoting contract requires registered signers, not just anyone
  with stake
- Settlement tx receipt polling (P0-09, v1254) prevents "silent
  settle" where a validator thinks it voted but its tx was dropped
- Canonical OV address pinned in code, not env (P0-07, v1248) — no
  drift to a rogue OV instance
- Shamir k-of-n on signal reconstruction: even a malicious quorum of
  validators cannot decrypt a signal unilaterally if k >= majority
*Residual gap:*
- **Signer set bootstrap** — under-registered signer set means small
  numerical quorums. Currently 5 signers registered; at 3-of-5 a
  2-validator collusion is enough. Need more signers before mainnet.
- **Per-signal-size quorum policy** not yet enforced. A $5k signal
  and a $100 signal currently get the same quorum.
- **UID 201 signer** not yet registered (task #18, human-blocked).
*Detection signal:*
- Outcome vote divergence ratio between `Audit` events and
  `OutcomeVoting` vote logs
- CUSUM-equivalent for validators: which validators' votes deviate
  from eventual settled outcome over rolling window?

### A-5 · Oracle-poisoning via TLSN-unfriendly books

*Attacker:* miner or miner coalition
*Goal:* report odds for a book that TLSNotary cannot verify (bot-walled,
session-gated, or using non-standard TLS), making the miner's report
authoritative by default.
*Cost:* near zero.
*Expected return:* same as A-1 on books without a second source.
*ROI:* very high when combined with A-1.
*Mitigations live:*
- Canonical odds schema (`project_canonical_odds_schema`) — miners
  adapt source to a common format; validators can cross-check even
  when different miners fetch different books
- Per-URL TLSNotary compatibility tracking in synthetic monitor
  (`/opt/monitoring/synthetic.log` on the production VPS)
- Miner score favours URLs that successfully notarise
*Residual gap:*
- **Known-flaky book list** is not formally enforced yet. A miner
  reporting from a known-flaky book should have its report weighted
  down or fully excluded from consensus.
- **Canonical-source mandate** for settlement: settlement should
  require at least one notarisable source per outcome, not just
  consensus across possibly-unverifiable reports.
*Detection signal:*
- Rolling `synthetic-state.json` with same URL failing ≥3 runs
- Settlement outcome determined by odds from a URL never successfully
  notarised in the last 30 days

### A-6 · Front-running signal commits

*Attacker:* outsider watching mempool / API / miner gossip
*Goal:* see a genius submit signal at line X, race them to commit at
the same line before publication, splitting the alpha.
*Cost:* gas + collateral.
*Expected return:* half the alpha of the front-run signal, minus
collateral risk on the racing signal.
*ROI:* depends on alpha size. On Base with sequencer-ordered
transactions, no public mempool, so extraction window is miner/
validator-layer only.
*Mitigations live:*
- Client-side encryption before submission — the plaintext never
  hits the wire
- Off-chain decoys — even an attacker who sees the commit can't tell
  which of 10 lines is real
- Base sequencer-ordered txs — no public mempool front-run surface
*Residual gap:*
- **Decoy statistical distinguishability**. If decoys' price
  distribution, timing, or slot distribution differs from real
  signals, an attacker can filter. Decoy jiggering in DEV-042
  addresses this but has not been adversarially tested against a
  motivated filter.
- **Miner-layer timing leak**: the moment a genius calls a miner to
  verify line availability, a colluding miner learns "someone is
  about to commit near this line." Commit-reveal on the miner side
  is not yet implemented.
*Detection signal:*
- Signal-commit clustering: >1 signal at the same sportbook/event/line
  within 5 seconds from distinct wallets
- Post-settlement distribution of per-genius PnL: outliers who
  mirror a high-alpha genius consistently

### A-7 · Purchase-state griefing / user fund loss

*Attacker:* environment (not strictly malicious); also a DoS vector
*Goal:* an idiot pays USDC, refreshes mid-purchase, loses recovery.
An attacker can amplify this by crafting UI conditions that cause
refreshes.
*Cost:* zero for the environment case; a DoS attacker's cost is
whatever it takes to throttle/crash the user's connection after the
tx but before share collection.
*Expected return:* attacker doesn't directly gain, but the user
loses their notional and the protocol loses trust.
*ROI:* negative reputation — highest strategic damage even at zero
revenue extraction.
*Mitigations live:*
- Purchase-state persistence to localStorage (C-1 fix in Phase 1)
- On-page-load recovery: check for incomplete purchases, attempt
  share re-collection
- KeyRecovery contract stores an encrypted blob per signal for the
  genius (buyer-side recovery is in M-7, deferred)
- Maintenance banner + mutation-button pre-checks
  (`web/lib/hooks.ts::useProtocolPaused`, `useMutationGate`) surface
  protocol pauses BEFORE the wallet popup, eliminating "paused
  tx submitted and then reverted" paths
*Residual gap:*
- **Idiot-side key recovery** (M-7): if the buyer loses browser
  session before the pick is displayed, they need to re-collect
  shares from validators. The recovery endpoint exists but the UX
  does not.
- **Purchase-state TTL**: old localStorage entries accumulate; not
  yet cleaned up.
*Detection signal:*
- Ratio of Escrow `PurchaseRecorded` events to SignalCommitment
  `SharesRetrieved` events. A growing gap is users losing access.
- Support-channel volume mentioning "I paid but didn't get the pick."

### A-8 · Governance / operator key compromise

*Attacker:* outsider → operator (phishing, malware, insider)
*Goal:* hijack the governance multisig, schedule a timelock tx that
drains a contract balance or disables pause, wait out the delay,
execute.
*Cost:* depends entirely on operator security hygiene. A
sophisticated phishing campaign against one operator is $10-100k.
*Expected return:* if `Escrow.sweep` or equivalent is reachable via
the attacked proxy's owner — unbounded. Capped in practice by
Escrow balance at the moment of execution.
*ROI:* asymmetrically catastrophic. Worst-case scenario in the whole
model.
*Mitigations live:*
- Every proxy owned by `TimelockController` (0x37f41E... on testnet),
  not an EOA
- 72-hour timelock delay on mainnet — any scheduled malicious tx is
  observable for 3 days
- `PausableUpgradeable` on every user-facing contract — pause first,
  investigate second
- Monitoring: cron on the production VPS watches for `CallScheduled` events on
  the Timelock and alerts within minutes
- Runbooks: `docs/runbook-emergency-pause.md`,
  `docs/runbook-suspicious-withdrawal.md`
- Verified-ownership assertion script (`scripts/verify-ownership.sh`)
  pins expected owners of every proxy
*Residual gap:*
- **Multisig signer set** for the mainnet timelock is not yet
  finalised (human task). Until N-of-M with N >= 3 geographically
  distributed signers, this is the single largest risk.
- **Bastion hardening** on RPC and hosting: operator must connect
  from a hardware-wallet-signed session only.
- **Incident fire drill**: pause/unpause drill ran on testnet
  (P0-04); mainnet equivalent not yet scheduled.
*Detection signal:*
- Any `CallScheduled` event whose target is a known Djinn contract
  and whose calldata is not in the public operator runbook
- Deviations from `scripts/verify-ownership.sh` invariants

### A-9 · Admin panel brute force

*Attacker:* outsider
*Goal:* guess the admin password via repeated POSTs to
`/api/admin/auth`.
*Cost:* ~zero, bandwidth only.
*Expected return:* read/write on all admin endpoints, which surface
network topology and (for some endpoints) operator-grade data.
*ROI:* near-free attempt, reasonable return if a weak password slips
through.
*Mitigations live:*
- Beta password rotation (manual)
- Global 200-req/min rate limit in `web/middleware.ts`
*Residual gap (M-3 in VULNERABILITY_REPORT):*
- **Per-endpoint rate limit** on `POST /api/admin/auth` with
  exponential backoff after 5 failures. At 200 req/min a 6-digit
  PIN is cracked in hours.
- **2FA on admin** not implemented.
*Detection signal:*
- `admin_auth_failed` count per IP over 5-min window
- Distribution of `x-forwarded-for` on `/api/admin/*`

### A-10 · Network-topology reconnaissance + targeted DoS

*Attacker:* outsider (or a competing subnet)
*Goal:* scrape `/api/miners/discover`, `/api/validators/discover`,
map every IP+stake, then target high-stake nodes with DoS to shift
consensus (A-4 adjunct) or starve specific geniuses of their share
distribution (A-7 adjunct).
*Cost:* scrape ~free; DoS bandwidth depends on target. Base-level L4
amplification can rent for $100/hour.
*Expected return:* time-limited; consensus degrades while the target
is offline. Combined with a planned A-4 or A-1, this unlocks the
real attack.
*ROI:* only meaningful as a step in a bigger attack.
*Mitigations live:*
- SSRF filter + IP-literal block on `/api/miners/discover` and
  `/api/validators/discover`
- Wildcard router (`*.djinn.gg`) so validators get HTTPS without
  exposing raw IPs in the UI
- Watchtower propagation and notary sidecar failover reduce the
  impact of a single node going offline
*Residual gap (H-5 in VULNERABILITY_REPORT):*
- **IPs removed from public endpoints**: replace with DNS names or
  opaque identifiers. Today's `/api/validators/discover` still
  returns raw IPs.
- **Validator rate-limit from outside SN103**: burn-gate closes the
  peer-to-peer path but public HTTP is still open.
*Detection signal:*
- Sustained 5xx rate on a validator with no corresponding local cause
- Correlation between `/api/*/discover` scrape volume and subsequent
  node unavailability

---

## 4. Economic bounds for soft-launch

These bounds exist so that even if *one* residual gap above is
exploited end-to-end during the first 30 days of mainnet, the loss
is bounded and recoverable from Djinn's own reserves. They should
hold until the P0 list is empty, three independent audits concur
the list is empty, and a two-week live run with no new P0 findings
confirms stability.

**Enforcement layer:** every row in the table below is a
**policy-level bound** enforced at the operator layer (API
middleware, invite-list gating, circuit-breaker mode), *not* a
smart-contract invariant. The only on-chain numeric caps are
`MAX_NOTIONAL = 1e12` ($1M / purchase) in `Escrow.sol:146` and
`MAX_BATCH_NOTIONAL = 20e12` ($20M / batch, = `MAX_BATCH_SIZE` ×
`MAX_NOTIONAL`) in `Audit.sol:43`, enforced in every settlement path
(`settleByVote`, `earlyExitByVote`, `forceSettle`). If
the operator layer is bypassed (compromised ops, RPC bypass, admin
key leak) the caps below do **not** bind; the on-chain cap does.

| Bound | Soft-launch | Full launch | Rationale |
|-------|-------------|-------------|-----------|
| Max signal notional | $500 | $5,000 | A-1/A-2 cap per exploit |
| Max cycle notional | $2,500 | $50,000 | A-4 cap per manipulated batch |
| Max buyer per-cycle | 5 purchases | unlimited | A-2 probing surface |
| Max genius per-week signals | 20 | unlimited | A-1 collusion velocity |
| Idiot list | invite-only | open | reputational A-7 blast radius |
| Genius list | operator-reviewed | open | A-1/A-6 baseline trust |
| Circuit breaker | enforce-mode | enforce-mode | A-1 live defence |
| TLSN sampling rate | 5% | 1% | A-5 coverage during calibration |
| Timelock delay | 72h (unchanged) | 72h | A-8 response window |

Soft-launch runs until all three of:

1. MAINNET_BLOCKERS.md contains zero P0 items (currently 3 open: P0-02
   and P0-03 are human-owned, P0-06 closes when this doc merges).
2. Three independent audits (`/codex-audit` + two fresh-eyes Claude
   subagents with no session context) independently conclude the P0
   list is empty.
3. Two weeks of live mainnet operation under the soft-launch bounds
   with no new P0 finding, no settlement failure, and no circuit-
   breaker enforce-trip that required manual intervention.

Any violation of a bound during soft-launch is itself a P0 finding.

---

## 5. Ongoing monitoring invariants

The following invariants must be alarmable (Prometheus or
equivalent) before mainnet opens to general traffic. Each one maps
back to a detection signal above.

1. `circuit_breaker_flag_count_5m > 0` → A-1
2. `audit_vote_reverted_total + audit_vote_receipt_timeout_total > 0`
   in any 1-hour window → A-4
3. `signal_commit_clustering_count > 1 per 5s per event` → A-6
4. `purchase_recorded_total - shares_retrieved_total > N` rolling → A-7
5. `admin_auth_failed_total per IP > 5 per 5m` → A-9
6. `verify-ownership.sh exit != 0` on scheduled run → A-8
7. `synthetic-monitor_state.failed_urls >= 3 consecutive runs` → A-5
8. `metagraph_coldkey_ratio > 0.3` (fraction of UIDs on one coldkey)
   → A-3
9. `outcome_vote_divergence > 10%` over trailing 500-audit window
   → A-4

These live in `docs/operations-sla.md` (paging thresholds) and
`docs/runbooks.md` (what to do when they fire). This doc is the
*why* behind those thresholds; violating the invariant means an
attack model above may be live.

---

## 6. Open questions requiring human decision

Outside the autonomous scope of P0-06. Logged here to close the loop
on the "mixed owner" aspect of the blocker.

1. **Final multisig signer set and custody arrangement.** Needed
   before P0-02 and P0-03 close. Affects A-8 blast radius.
2. **Go/no-go threshold on TLSN coverage.** What fraction of
   settled-outcome-determining fetches must be successfully
   notarisable before we're comfortable lifting the soft-launch
   notional caps? A-1 and A-5 both depend on this.
3. **Stake-gate calibration.** Does Djinn want Bittensor-level
   Sybil resistance (TAO registration cost) or protocol-level
   (operator-reviewed genius/idiot lists) during early mainnet?
   Affects A-3.
4. **Insurance or reserve fund?** A $10k-$50k treasury reserve that
   can make whole a user hit by A-7 or A-8 during soft-launch would
   materially reduce reputational blast radius. Outside protocol
   scope but inside business scope.
5. **Public bug bounty scope + bounds.** Should launch alongside
   mainnet. Affects all residual-gap items.

---

## 7. Verification links

- `/home/user/djinn/VULNERABILITY_REPORT.md` — underlying code audit
- `/home/user/djinn/validator/djinn_validator/core/circuit_breaker.py`
  — live CUSUM tracker
- `/home/user/djinn/validator/djinn_validator/api/server.py` —
  `_MIN_SHAMIR_THRESHOLD`, pause gate, purchase flow
- `/home/user/djinn/validator/djinn_validator/config.py` —
  `CANONICAL_OUTCOME_VOTING_ADDRESSES` (chain-aware)
- `/home/user/djinn/validator/djinn_validator/api/burn_gate.py` —
  `is_allowed_peer_ip`
- `/home/user/djinn/web/lib/hooks.ts` — `useProtocolPaused`,
  `useMutationGate`
- `/home/user/djinn/docs/operations-sla.md` — paging thresholds
- `/home/user/djinn/docs/runbooks.md` — incident responses
- `/home/user/djinn/docs/governance.md` — timelock + multisig design
- `~/.claude/projects/-home-user-djinn/memory/project_incentive_attack_surface.md`
  — 2026-04-11 threat sketch (input to this doc)
