# Djinn Protocol v2

### Buy intelligence you can trust. Sell analysis you can prove.
### Signals stay secret forever, even from us.

Bittensor Subnet 103 · Base Chain · USDC

---

## What Djinn is

Djinn unbundles **information** from **execution** in betting markets.

Skilled analysts (**Geniuses**) sell encrypted predictions. Buyers (**Idiots**) purchase access. What buyers do with the information is their business: bet, hedge, fade, or ignore. Djinn never sees the content, never takes a position, never executes a bet.

Two guarantees:

1. **Signals stay secret forever.** Not until kickoff, not until settlement: forever. No party (including Djinn) ever sees signal content. Decryption happens locally in the buyer's browser.
2. **Track records are publicly verifiable forever.** Every signal is committed on-chain before the event. Settlements are immutable. Performance can be checked by anyone, against public outcomes, without revealing individual picks.

---

## Why this is the right shape

Existing prediction markets either reveal the prediction (destroying the analyst's edge) or rely on screenshots and trust (destroying accountability). Djinn separates the two.

- **Geniuses scale edge across thousands of buyers without moving any line.** Their predictions never leak.
- **Idiots buy methodology, not execution risk.** They make their own betting decisions with the information.
- **Djinn operates an information service, not a casino.** Cleaner regulatory positioning. No custody of bets. No house.

---

## How a signal lives

1. **Genius creates a signal locally.** They pick an event, a market, a side, and a committed price. The committed price is a *limit order*: payout will use whatever price is at-or-better-than committed across the buyer's preferred sportsbooks at purchase time.

2. **Client-side encryption.** The signal is encrypted in the genius's browser. The decryption key is split via Shamir's Secret Sharing across SN103 validators. No single validator can decrypt; a threshold must collaborate.

3. **Off-chain decoys.** The real signal is hidden among decoy lines drawn from the same sport, same time window, same general price range. Decoys are statistically indistinguishable from the real signal until purchase. The number of decoys is configurable per signal.

4. **On-chain commitment.** A commitment to the encrypted signal (and its decoys) is posted on Base. The commitment is timestamped and immutable.

5. **Idiot purchases.** When a buyer wants to access the signal, they pay USDC into the Escrow contract. Validators run an MPC protocol to compute purchase-time aggregate odds (BPA / WPA) across the buyer's preferred sportsbooks, without revealing which line is real. The buyer's browser receives the key shares, reconstructs the decryption key locally, and decrypts.

6. **Event resolves.** The genius and the buyer both know the outcome. So does anyone watching the public sportsbooks.

7. **Audit settles.** After 10 signals (or queue depth, depending on the variant), an MPC batch settlement runs. Validators jointly compute per-line gain vectors and select the real index via secure computation, producing a public, signed settlement attestation. The genius's collateral covers any owed damages. The settlement is on-chain and immutable.

---

## Aggregate pricing (BPA / WPA)

The committed price is a limit order, not a fixed quote. At purchase time:

- **BPA (Best Price Aggregation):** payout uses the *highest* price at-or-above committed across the buyer's preferred books. Buyer captures the best available odds.
- **WPA (Worst Price Aggregation):** payout uses the *lowest* price at-or-above committed across the buyer's preferred books. More conservative, lower variance.

A line is *executable* if at least one of the buyer's books offers a price at-or-above the genius's committed limit. Geniuses never cover spread; they only bear outcome variance. If no book is at-or-above committed at purchase time, the buyer cannot purchase that line and the signal does not become accessible.

---

## How accountability is enforced

### Cryptographic timestamps

Every signal is committed on-chain before the event. Encrypted before commitment, so the content is hidden, but the existence and timing of the prediction are provable forever. Commitments are immutable.

### Collateral-backed SLAs

Geniuses post USDC collateral. After each batch of signals to a given buyer, an audit settles. If the genius underperformed against the agreed SLA (a quality-score floor), damages are paid from collateral. This is a normal service-level agreement, not a gambling instrument.

### MPC batch settlement

Settlement runs as multi-party computation across validators. Validators jointly compute the per-line gain vector for every line (real and decoy) and securely select the value at the real index. The output is a single signed attestation: the genius's quality score for the batch, and the damages owed. The intermediate computation reveals nothing about which line was real.

### True blindness

Signal creation is end-to-end encrypted. Validators see ciphertexts and key shares, never plaintext. Decoys hide which line is real. Decryption happens only in the buyer's browser. The protocol enforces by construction that no one but the genius and the paying buyers ever see the signal.

---

## How miners produce odds

Sports odds come from miners on Subnet 103, not from Djinn-controlled APIs.

- **Miners pick their own data sources.** Each miner ships an adapter that maps its provider's response into a canonical internal odds schema (sport, event, market, outcome, bookmaker, price, timestamp). New providers = new adapter files. Miners compete on speed, cost, and coverage of their chosen sources.
- **Validators run consensus across miners.** For each odds query, validators query multiple miners in parallel and run Yuma consensus on the results. Median or trimmed mean of agreeing miners determines the canonical answer. The buyer sees a single price, derived from many independent sources.
- **Miners are scored on sustained agreement, not per-query agreement.** A circuit breaker (CUSUM-based) tracks each miner's deviation from consensus over time. Individual disagreements (cache jitter, upstream hiccup, line just moved) are absorbed without consequence. Sustained deviation triggers a flag.
- **Flagged miners can appeal with TLSNotary proofs.** A flagged miner can submit a TLSNotary proof of their declared source for the disputed queries. If the proof checks out and contradicts consensus, the flag clears, the miner gets a bonus, and the colluders who pushed false consensus get penalized instead. If the proof doesn't check out (or none is submitted), the miner is slashed (forward Yuma weights set to zero) and the score resets.
- **Bonuses come entirely from slashes.** No fresh tokens, no validator subsidy. Zero-sum value transfer from liars to honest appellants. Makes collusion strictly negative-EV in every configuration where at least one honest non-colluding miner exists.

This is the only known mechanism that catches sustained lies, tolerates honest minorities, and survives a colluding minority of miners, without burning TLSNotary cost on every query.

---

## How validators are selected

- **Validators are SN103 validator-permit holders.** Stake-gated entry per Bittensor's existing mechanism.
- **The web client races validators directly over HTTPS.** No proxy. No central gateway. Browsers hit validator URLs straight from the user's wallet session.
- **Quorum policy varies by call type.** Low-stakes queries (UI display) race the first responder. High-stakes operations (purchase verification, settlement, key recovery) require Q-of-N agreement, where Q is large enough that a colluding minority cannot meet quorum.
- **New miners and new validators start at zero weight.** A bootstrap window must be cleared before they earn weight, regardless of stake. Closes the registration-window Sybil hole.

---

## What lives on-chain

- **`SignalCommitment`** stores commitments to encrypted signals.
- **`Escrow`** holds USDC for purchases and routes payments.
- **`Collateral`** tracks genius collateral and damages.
- **`Account`** maps geniuses, idiots, and SLA terms.
- **`Audit`** records batch settlement attestations.
- **`CreditLedger`** tracks earned credits and payouts.
- **`OutcomeVoting`** tallies outcome consensus when needed.
- **`KeyRecovery`** allows late buyers to reconstruct keys after the buyer threshold is met.

All seven contracts are UUPS proxies behind a `TimelockController`. Upgrades are scheduled with delay (72h on mainnet, 72s on testnet via chain-conditional `minDelay`). Every upgrade is **additive only**: new functions, new events, new storage at the end, never modifying or removing what exists. This allows multiple protocol versions to live on a single set of mainnet addresses, with callers self-selecting via runtime feature flags.

---

## What lives off-chain

- **MPC batch settlement** runs on the validator network, anchored on-chain only by the signed attestation that names the result.
- **Odds production** runs on the miner network, with consensus and circuit-breaker scoring at the validator layer.
- **Encryption and decryption** run in the user's browser. Validators only see ciphertext.
- **The web client itself** is a static HTML/JS bundle that ships from IPFS via ENS. There is no Djinn-operated server in the data path.

---

## Threat model and defenses

- **Genius lies about a signal.** Cannot. Signals are committed on-chain before the event; commitments are immutable; outcomes are public.
- **Genius colludes with miners to manufacture wins.** Mitigated. Miners are scored on consensus agreement, not on individual genius outcomes. Bribing requires shifting consensus, which is more expensive than the per-signal payout.
- **Validator collusion to push false consensus.** Mitigated by Bittensor vtrust at the protocol layer and by Q-of-N quorum at the application layer. Tunable per call type.
- **Miner Sybil.** Stake-gated registration plus zero-weight bootstrap window. New miners cannot extract value before being scored.
- **Miner collusion to push false odds.** Honest minorities catch them via the CUSUM circuit breaker plus TLSNotary appeal. Bonuses funded entirely from slashes make collusion strictly negative-EV unless the entire network is captured.
- **Oracle attack on purchase MPC.** Validators cross-check the buyer's claimed available_indices against independent miner consensus before allowing the purchase. A buyer cannot probe to learn the real index without paying.
- **Front-running signal creation.** Signals are encrypted client-side before submission. Decoys hide the real line. Front-running requires breaking the encryption.
- **100% network capture.** Out of scope. No decentralized oracle network defends against this; Djinn doesn't either.

---

## Economics

- **Geniuses earn** purchase fees and credit accruals. They pay damages from collateral if they underperform their SLA.
- **Idiots pay** USDC per purchase. Their cost is the genius's quoted purchase price plus a small Djinn protocol fee. They pay no execution costs because Djinn does no execution.
- **Validators earn** Bittensor emissions weighted by their honest performance of the MPC and consensus duties.
- **Miners earn** Bittensor emissions weighted by their odds-source quality, scored via the consensus circuit breaker.
- **Djinn protocol fees** are gas-like: small, configurable per contract, with the genius and idiot each paying a side. Defends the platform by making spam expensive without dominating user economics.

There is no token. There is no pre-sale. There is no Djinn equity in the protocol. The value flows are USDC for the application layer and TAO/Alpha for the consensus layer, both pre-existing.

---

## Governance

- **Contracts** are owned by `TimelockController`. The deployer can propose upgrades; anyone can execute after the delay. No single party can unilaterally alter the protocol.
- **Validators** are independent operators. Djinn does not run a majority of validators and cannot dictate consensus.
- **Miners** are independent operators with independent data sources. Djinn does not pick winners.
- **The web client** is a static build. Anyone can fork it, host it, or hit the validators directly without it.
- **Source of truth** is this document. When implementation diverges from this document, the deviation is logged in `DEVIATIONS.md` and reviewed.

---

## What is *not* here (and why)

- **No token.** No need. USDC for payments, TAO for incentives.
- **No DAO.** Governance is the timelock plus the open-source repo. Decisions happen in code, not in votes.
- **No KYC.** Djinn is an information service. Buyers and sellers transact in pseudonymous USDC. Local laws apply to the parties, not to the protocol.
- **No house.** Djinn never takes the other side of any prediction. It is a marketplace for analysis, not a counterparty.
- **No custody of bets.** Buyers bet (or don't) at sportsbooks of their choosing. Djinn never touches the wager.
- **No central data plane.** Odds come from the miner network. Validators serve over HTTPS directly. The client ships from IPFS. There is no Djinn-operated API in the path between user and chain.

---

## Status (2026-04-11)

Djinn is live on Base Sepolia testnet with seven UUPS proxies, ten validator permits on SN103, and an active miner network. The pre-launch decentralization roadmap is captured in `project_prelaunch_priorities_2026_04_11.md`. The MPC batch settlement primitive replaces the original ZK approach (DEVIATION). The CUSUM circuit breaker for miner honesty is the current design (`project_consensus_circuit_breaker.md`). The additive upgrade pattern is the load-bearing rule for shipping protocol changes alongside live network operation.

---

## The shape, in one sentence

**Djinn is a marketplace where analysts sell sealed predictions to buyers, validators verify the analysts' track records via cryptographic settlement on a network the analysts don't control, and no one (including Djinn) ever sees what was predicted.**
