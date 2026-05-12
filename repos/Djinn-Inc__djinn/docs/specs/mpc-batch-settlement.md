# Spec: MPC Batch Settlement (replaces ZK for audit settlement)

**Status:** Draft, 2026-04-11
**Author:** autonomous nightshift, user-directed
**Supersedes:** `whitepaper.md` sections on ZK audit proof (to be rewritten)

## Motivation

The current Djinn whitepaper commits to a ZK-based audit settlement:
clients generate SNARK proofs (Groth16 over BN254, or PLONK) that a
Quality Score was computed correctly from committed signals and public
game outcomes, and the contract verifies the proof on-chain. This gives
strong privacy (picks are never revealed) and strong verifiability
(scores can't be faked), but it costs:

- A whole ZK circuit build + prover service + trusted setup
- ~250k gas per proof verification on L2
- Client-side proving time (minutes for a 10-signal audit batch on
  consumer hardware)
- A second trust model on top of the MPC one we already have

We don't need it. The Djinn protocol already runs a Bittensor validator
network with t-of-n honest-majority MPC for availability checks and
outcome reveals. The same machinery can do settlement without ever
revealing individual picks — the insight is that batch-level
aggregation inside MPC provides the same privacy guarantee as a ZK
proof does for a single purchase, and the aggregation is literally
free in Shamir secret sharing.

## Core idea

At settlement time, for each purchase in the audit batch the validators
have:

- **Public inputs** per purchase:
  - `notional`, `slaBps`, `bpa_mode`
  - `bpas[i]`, `wpas[i]` for i = 1..k (per-line BPA/WPA vectors at the
    buyer's books, committed at purchase time — see "Required
    on-chain state" below)
  - `outcomes[i]` for i = 1..k (per-line outcome enum, derived from
    the public game result applied to each committed decoy line)
- **Secret input** per purchase:
  - `realIndex` as Shamir shares already held by the validators
    since signal creation

For each purchase the validators precompute a per-line gain vector:

```
gain_vector[i] =
  if outcomes[i] == Favorable:   notional * (odds[i] - 1)
  if outcomes[i] == Unfavorable: -notional * slaBps / 10_000
  if outcomes[i] == Void:        0
```

where `odds[i] = bpas[i]` in BPA mode or a filtered WPA min in WPA
mode. Every element of this vector is a fixed integer computable from
public data only.

The MPC then evaluates a Lagrange interpolation of `gain_vector[]` at
the secret `realIndex` to produce `[gain]` — a Shamir-shared scalar
equal to `gain_vector[realIndex]`. This is exactly the primitive
`mpc_outcome.py::secure_select_outcome` already implements for the
per-purchase outcome enum; we just generalize the input from a length-N
vector of enums to a length-N vector of arbitrary integers.

For a single purchase, revealing that scalar would leak `realIndex`
because a third party can back-match the scalar against the public
`gain_vector[]` and identify which element yielded it. So the batch
never reveals per-purchase gains. Instead:

1. For each purchase p in the batch, MPC computes `[gain_p]` as above.
2. Sum locally: `[total_score_change] = sum over p of [gain_p]`. This
   is a free operation in Shamir — each validator just adds its
   shares.
3. Reveal only `total_score_change` via a single MPC opening.

The revealed sum is a scalar that folds in k = 10 secret indices and
their per-line gain vectors. An observer trying to reverse-engineer
any one `realIndex_p` faces an underdetermined integer constraint
(10 unknowns in [1, N] domains, one equation). For reasonable batch
sizes and decoy counts the problem is statistically infeasible.

The contract receives `total_score_change` via a BLS-aggregated
signature from the validators and applies it to the Genius's Quality
Score. Individual picks are never reconstructed, never stored,
never revealed.

## Required on-chain state

For the batch settlement to have honest inputs, the per-line `bpas[]`
and `wpas[]` vectors for each purchase must be committed on-chain at
purchase time so they cannot be changed at settlement. Options in
order of storage cost:

1. **Inline storage on Purchase record**: `uint256[] bpas; uint256[]
   wpas;`. Cheapest to read at settlement but most expensive to
   write. ~25 kB for a 200-line signal.

2. **Merkle root on Purchase record**: `bytes32 bpaRoot; bytes32
   wpaRoot;`. Write cost is two storage slots. Settlement provides
   the vectors as calldata plus a Merkle proof; contract verifies
   the root matches.

3. **Event-only emission + storage hash**: `bytes32 vectorHash;`
   plus an indexed event containing the vectors. Events are much
   cheaper than storage writes. Settlement reads the vectors from
   the event log off-chain, provides them as calldata, and the
   contract verifies `keccak256` matches.

Recommendation: option 3 for lowest gas, with option 2 as fallback
if the audit settlement path can't reliably re-derive vectors from
events.

## Changes required

### Contract changes (bundled into the next 72s timelock cycle)

1. `Escrow.purchase()`:
   - Remove `uint256 odds` parameter. Buyer no longer controls
     settlement odds.
   - Accept `uint256[] calldata bpas`, `uint256[] calldata wpas`
     (or a single flat array + offset). Compute
     `keccak256(abi.encode(bpas, wpas))`, store as
     `Purchase.vectorHash`.
   - Emit `SignalPurchased` with the vectors inline so settlement can
     recover them off-chain.

2. `Audit.sol`:
   - Delete `_computeScore` (the current per-purchase gain
     calculator).
   - Add `settleBatch(uint256[] purchaseIds, bytes batchData,
     bytes signature)`:
     - `batchData` encodes per-purchase vectors + outcomes
     - `signature` is the BLS-aggregated validator attestation over
       `(batchData, totalScoreChange)`
     - Contract verifies the signature, the vectorHashes, and
       applies `totalScoreChange` to the Genius's quality score.
   - Signature verification uses a precompile or an upgradeable
     BLS verifier.

3. Remove ZK-related scaffolding from contracts and scripts. None of
   it is wired up in production today, so this is cleanup only.

### Validator changes

1. New module `mpc_batch_settlement.py` with the trusted-dealer
   reference implementation. Already implemented in this commit as
   `core/mpc_batch_settlement.py`, with tests.

2. Extend `mpc_outcome.py::secure_select_outcome` to return
   Shamir-shared result instead of opening, so multiple selections
   can be summed before the final reveal. Needed only in the
   distributed version, not the local-simulation version shipping
   in this commit.

3. Distributed version that runs the selection MPC across validators
   over HTTP. The power-tree machinery from `plan_parallel_powers`
   can be reused as-is.

4. BLS aggregation for the final attestation. Use blst or ethcc
   library. One signature per batch.

### Web / client changes

1. Compute per-line `bpas[]` / `wpas[]` from the buyer's configured
   books using the `/check-odds` response at purchase time.

2. Pass both vectors as calldata to the new `Escrow.purchase()`.

3. No more client-side odds picking. `lockedOdds` parameter disappears.

4. Settlement UI just shows the aggregate score change after it
   lands; no per-purchase reveals.

### Whitepaper rewrite

Replace `whitepaper.md` sections on ZK proofs with the MPC batch
settlement design. The privacy claim is preserved ("picks are never
revealed on-chain, even after settlement") and the verifiability claim
is preserved ("Quality Score changes are attested by a t-of-n validator
majority"). The only thing changing is the cryptographic primitive
backing them.

## Privacy analysis

**At purchase time:** observer sees the public per-line `bpas[]` and
`wpas[]` (and their hash/commitment on-chain), plus notional, signal
ID, buyer address. None of these is correlated with `realIndex`.
Same privacy as today.

**At settlement time:** observer sees a single `totalScoreChange`
scalar per audit batch. To recover any individual `realIndex_p` from
the sum, the observer needs to solve:

```
totalScoreChange = gain_vector_1[realIndex_1]
                 + gain_vector_2[realIndex_2]
                 + ...
                 + gain_vector_10[realIndex_10]
```

where each `gain_vector_p` is a known public vector and each
`realIndex_p` is unknown in `{1, 2, ..., k}`. This is an integer
subset-sum variant with k^10 possible solutions for k decoy lines per
signal and 10 purchases per batch. For k = 200 that's 10^23 possible
index tuples — statistically infeasible to solve, especially since
many solutions yield identical sums when per-line gains collide
(outcome=Unfavorable lines all have the same loss value, etc.).

**Observer with partial information** (e.g., knows 9 of 10 `realIndex_p`
from out-of-band sources) can solve for the 10th via one equation one
unknown. This is an irreducible degradation as the audit batch becomes
partially compromised. Same degradation applies to the ZK version and
to any scheme that reveals an aggregate value.

**Active attack by validators** (t+ colluding to pool their Shamir
shares of `realIndex`): they reconstruct `realIndex` and thereby learn
the real pick. Same threat model as every other validator-MPC operation
in the protocol; economic stake via Bittensor is the defense.

## Security analysis

**Integrity of the per-line vectors:** prevents a malicious client
from passing arbitrary odds. The contract stores a hash at purchase
time; settlement providers must supply vectors that match. If the
client lies about odds at purchase time, they can't backtrack at
settlement. If the client is honest, the vectors are fully correct.

**Integrity of the batch sum:** the validators collectively sign the
result; a malicious validator trying to inflate or deflate the sum
cannot do so unless they control t+ shares (the standard MPC trust
model).

**Malicious buyer passing bad `outcomes[]`:** outcomes are derived
from public game results applied to public decoy lines, so validators
can independently compute them and refuse to sign if they disagree.
No client trust required.

## Out of scope for this spec

- Migration path for existing Purchase records created before this
  change (there's no real settlement happening today on testnet, so
  a clean break is fine)
- Gas cost benchmarks for the three on-chain vector-storage options
- BLS library selection and calldata format for batch attestations
- Validator code refactoring to expose Shamir-shared results from
  `mpc_outcome.py` without opening

## Implementation order

1. ✅ **Local-simulation reference** (this commit): `mpc_batch_settlement.py`
   with full test coverage. Not wired to anything. Serves as the
   correctness oracle for the distributed version.

2. **Phase 1** (validator + web, no contract change): collect per-line
   vectors at purchase time, store in a validator-side ledger keyed by
   `(signalId, buyer)`. Client sends the vectors along with the
   existing `purchaseSignal` request. No on-chain change. Lets us
   gather real-world data for the batch settlement without breaking
   anything.

3. **Phase 2** (contract change, 72s timelock cycle): add
   `vectorHash` to Purchase, remove `odds` parameter, add
   `settleBatch()` with BLS verification. Bundle with other pending
   contract improvements (Escrow.depositWithPermit for the wallet
   popup reduction, etc.) so the timelock window is shared.

4. **Phase 3** (validator distributed implementation): extend
   `mpc_outcome.py` to return Shamir-shared results; write the
   distributed batch settlement runner; wire BLS aggregation; flip
   settlement to use it.

5. **Phase 4** (whitepaper rewrite): replace ZK sections with MPC
   batch settlement. Update architecture diagrams. Publish to
   `/docs` site.
