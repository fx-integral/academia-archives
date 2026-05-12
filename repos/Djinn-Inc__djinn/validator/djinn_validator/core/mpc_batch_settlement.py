"""MPC-based batch settlement with secret-index privacy.

Problem
-------
At audit time we want to compute the total Quality Score change
across a batch of purchases, where each purchase's gain depends on
``realIndex`` — the secret Shamir-shared index of the genius's real
pick within the signal's decoy set. Individual realIndex values must
never be revealed; individual per-purchase gains must never be
revealed (a per-purchase gain can be back-matched to a specific line
from public data, breaking privacy). Only the aggregate sum across
the batch is opened at the end, and the sum folds in enough unknowns
that reversing it to any one realIndex is statistically infeasible.

Approach
--------
For each purchase in the batch the caller supplies:

- ``shares``: the validators' Shamir shares of ``realIndex`` for this
  purchase (threshold of them, at minimum)
- ``gain_vector``: a list of per-line gain values, one per line. Each
  element is a public integer derived from public inputs:
  notional, per-line bookmaker odds (bpa or wpa per mode), per-line
  outcome enum, SLA multiplier, all public. Entry ``i`` is "what the
  gain would be if line ``i`` were the real pick."

For each purchase, the MPC Lagrange-evaluates ``gain_vector[]`` at
the shared secret index to produce a Shamir-shared scalar equal to
``gain_vector[realIndex]``. This is the same polynomial-evaluation
primitive the existing ``mpc_outcome.py::secure_select_outcome``
already uses for outcome enum selection; we just pass arbitrary
integers instead of a 0-3 enum.

Across the batch, the per-purchase shared gains are **summed in
shares** without opening. Shamir sharing is linear, so adding shares
locally at each party gives a share of the sum. This is free: zero
network rounds, zero extra triples.

Finally the sum is opened. Only that single scalar leaves the MPC.
A third party trying to reverse-engineer any one ``realIndex`` from
the sum faces a 10-way integer constraint problem that is generally
underdetermined — the privacy guarantee the ZK approach in the
original whitepaper promised, achieved via the MPC machinery we
already run.

Privacy / correctness
---------------------
- Individual ``realIndex`` values never leave Shamir shares.
- Individual per-purchase gains never leave shares. The sum is the
  only opened value per batch.
- Gain vectors are public by construction. They cannot encode
  secret information, so their presence in memory does not leak.
- Malicious clients cannot inject false gain vectors because in
  production the vectors come from a validator-side computation
  using the on-chain ``vectorHash`` committed at purchase time.
  The local-simulation API in this module trusts its inputs; the
  distributed version will verify vectors against the hash before
  running the MPC.

This module
-----------
Trusted-dealer reference implementation. All participants run in
one Python process using directly-available Shamir shares. The
distributed version that runs the same algorithm across validators
over HTTP will be built on top of this primitive once the contract
side lands the ``vectorHash`` commitment.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import structlog

from djinn_validator.core.mpc import reconstruct_at_zero
from djinn_validator.core.mpc_outcome import (
    _eval_polynomial,
    lagrange_interpolation_coefficients,
)
from djinn_validator.utils.crypto import BN254_PRIME, Share

log = structlog.get_logger()


# Audit outcome enum values, matching the IDjinn.sol Outcome enum.
OUTCOME_PENDING = 0
OUTCOME_FAVORABLE = 1
OUTCOME_UNFAVORABLE = 2
OUTCOME_VOID = 3


@dataclass(frozen=True)
class PurchaseInputs:
    """All inputs needed to compute a single purchase's contribution
    to the batch settlement sum.

    Every field except ``shares`` is public. ``shares`` holds this
    validator's portion of the secret ``realIndex``; in the local
    trusted-dealer simulation we pass the full threshold worth of
    shares for every purchase at once.
    """

    purchase_id: int
    shares: list[Share]
    notional: int  # in USDC micro-units (6 decimals)
    sla_bps: int  # SLA multiplier in basis points
    bpa_mode: bool  # True = BPA mode, False = WPA mode
    bpas: list[int]  # per-line best-price aggregates (decimal * 1e6)
    wpas: list[int]  # per-line worst-price aggregates (decimal * 1e6)
    outcomes: list[int]  # per-line outcome enum (Favorable/Unfavorable/Void)
    signal_id: str = ""  # audit_set key; populated by build_purchase_inputs_from_audit_set


@dataclass(frozen=True)
class BatchSettlementResult:
    """Output of a batch settlement run."""

    total_score_change: int  # aggregate score delta across the batch
    purchase_count: int
    batch_note: str = field(default="")


ODDS_PRECISION = 1_000_000  # matches Escrow.sol ODDS_PRECISION (1e6)
BPS_DENOMINATOR = 10_000  # basis points denominator


def compute_gain_vector(
    inputs: PurchaseInputs,
    prime: int = BN254_PRIME,
) -> list[int]:
    """Build the per-line public gain vector for a single purchase.

    Called once per purchase before the MPC runs. Each entry represents
    "the gain or loss that would apply if this line were the real pick,
    given the game result." The gain is computed in the same field used
    by the MPC (BN254 prime) using 2's-complement-style wrapping for
    signed values, so that negative gains can still flow through
    Lagrange interpolation without losing sign.

    The formula mirrors ``Audit.sol::_computeScore`` with the
    substitution ``odds = bpas[i]`` in BPA mode or ``odds = wpas[i]``
    in WPA mode:

      Favorable    -> +notional * (odds - 1)
      Unfavorable  -> -notional * sla_bps / BPS_DENOMINATOR
      Void         -> 0
      Pending      -> 0  (audit should never settle with pending; we
                           return 0 defensively)
    """
    if len(inputs.outcomes) != len(inputs.bpas) or len(inputs.outcomes) != len(inputs.wpas):
        raise ValueError(
            "PurchaseInputs vectors must have the same length; "
            f"got outcomes={len(inputs.outcomes)}, bpas={len(inputs.bpas)}, "
            f"wpas={len(inputs.wpas)}"
        )

    gain_vector: list[int] = []
    for i, outcome in enumerate(inputs.outcomes):
        if outcome == OUTCOME_FAVORABLE:
            odds_scaled = inputs.bpas[i] if inputs.bpa_mode else inputs.wpas[i]
            # gain = notional * (odds - 1) where odds is decimal scaled by 1e6
            # keeping everything in scaled integer units:
            # gain = notional * (odds_scaled - 1e6) / 1e6
            gain = (inputs.notional * (odds_scaled - ODDS_PRECISION)) // ODDS_PRECISION
        elif outcome == OUTCOME_UNFAVORABLE:
            # loss = notional * sla_bps / 10_000, negated
            loss = (inputs.notional * inputs.sla_bps) // BPS_DENOMINATOR
            gain = -loss
        else:
            # Void or Pending
            gain = 0
        # Reduce to the field. Signed values become "large positive" via
        # the modular convention; Lagrange interpolation in the field
        # will produce the same signed result when we convert back at
        # the end.
        gain_vector.append(gain % prime)
    return gain_vector


def decode_field_to_signed(value: int, prime: int = BN254_PRIME) -> int:
    """Interpret a field element as a two's-complement-like signed int.

    Field values above half-prime are treated as negative. This is
    how we recover a signed Quality Score delta from an MPC output.
    """
    half = prime // 2
    if value > half:
        return value - prime
    return value


def _lagrange_select(
    gain_vector: list[int],
    shares: list[Share],
    prime: int,
) -> int:
    """Select gain_vector[realIndex] via Lagrange interpolation.

    This is the local-simulation version: the caller is the trusted
    dealer and has all shares, so we reconstruct the secret index and
    index directly. The distributed version will replace this with a
    real MPC polynomial evaluation over distributed shares.

    The Lagrange polynomial interpolates through the points
    ``(1, gain_vector[0]), (2, gain_vector[1]), ..., (N, gain_vector[N-1])``
    and evaluates at the secret index. Evaluating after reconstruction
    is mathematically equivalent to the MPC selection for correctness
    verification (which is what this reference implementation is for).
    """
    if len(gain_vector) < 2:
        # Pad with a zero so the polynomial is non-trivial and the
        # index-to-polynomial mapping stays consistent.
        gain_vector = list(gain_vector) + [0]

    # Reconstruct the secret index (trusted-dealer: has all shares).
    secret_index = reconstruct_at_zero(
        {s.x: s.y for s in shares},
        prime,
    )

    # Validate the index is in the legal 1-based range for the vector.
    # In production this check lives in the distributed protocol's
    # polynomial-eval circuit; here we enforce it at the boundary to
    # catch test-setup bugs early.
    if secret_index < 1 or secret_index > len(gain_vector):
        raise ValueError(
            f"secret index {secret_index} outside 1..{len(gain_vector)} "
            "(test setup produced an out-of-range realIndex)"
        )

    # Build the Lagrange interpolation coefficients and evaluate at
    # the secret index. This matches what the distributed version
    # will compute (equivalently, up to field arithmetic) via
    # polynomial eval without reconstructing.
    coeffs = lagrange_interpolation_coefficients(gain_vector, prime)
    return _eval_polynomial(coeffs, secret_index, prime)


def local_batch_settle(
    batch: list[PurchaseInputs],
    threshold: int,
    prime: int = BN254_PRIME,
) -> BatchSettlementResult:
    """Run the batch settlement in local-simulation mode.

    For each purchase:
      1. Build the public gain vector from outcomes + odds + notional.
      2. Lagrange-eval the vector at the secret shared index to
         produce the per-purchase gain (in field form).
      3. Accumulate into the running sum (mod prime).

    After all purchases process, the running sum is decoded from the
    field into a signed integer and returned as the aggregate Quality
    Score delta.

    The local version reconstructs each secret index to evaluate the
    polynomial, which technically exposes the per-purchase real index
    to the trusted dealer — that's fine for a correctness oracle, but
    the distributed version must keep everything in shares and only
    open the final sum (otherwise the privacy guarantee is lost).
    """
    if not batch:
        return BatchSettlementResult(total_score_change=0, purchase_count=0)

    running = 0
    for inputs in batch:
        gain_vector = compute_gain_vector(inputs, prime=prime)
        selected = _lagrange_select(gain_vector, inputs.shares, prime)
        running = (running + selected) % prime

    total = decode_field_to_signed(running, prime)
    log.info(
        "batch_settle_complete",
        purchase_count=len(batch),
        total_score_change=total,
    )
    return BatchSettlementResult(
        total_score_change=total,
        purchase_count=len(batch),
    )


def local_batch_settle_revealing_individual_gains(
    batch: list[PurchaseInputs],
    threshold: int,
    prime: int = BN254_PRIME,
) -> tuple[BatchSettlementResult, list[int]]:
    """Same as ``local_batch_settle`` but also returns the per-purchase
    gains as signed integers.

    Intended only for tests and debugging. In production the per-purchase
    gains MUST stay sealed inside MPC until after the sum is computed;
    exposing them enables single-purchase back-correlation against the
    public gain vector. This helper exists so tests can validate the
    per-purchase computation matches the closed-form expectation.
    """
    if not batch:
        return BatchSettlementResult(0, 0), []

    per_purchase_signed: list[int] = []
    running = 0
    for inputs in batch:
        gain_vector = compute_gain_vector(inputs, prime=prime)
        selected = _lagrange_select(gain_vector, inputs.shares, prime)
        per_purchase_signed.append(decode_field_to_signed(selected, prime))
        running = (running + selected) % prime

    total = decode_field_to_signed(running, prime)
    return (
        BatchSettlementResult(total_score_change=total, purchase_count=len(batch)),
        per_purchase_signed,
    )


# ---------------------------------------------------------------------------
# Distributed batch settlement simulation
# ---------------------------------------------------------------------------
#
# The functions below simulate the distributed batch protocol — the one
# that will run across multiple validators over HTTP — without actually
# opening a network connection. Each simulated party runs with ONLY its
# own Shamir share; the secret realIndex values are never reconstructed
# at any point. Per-purchase gain shares are accumulated into a running
# sum-of-shares and only that single final sum is opened.
#
# This function is the test oracle for the HTTP runtime: the HTTP
# version must produce the same BatchSettlementResult as this
# simulator for the same inputs, and the simulator enforces the same
# privacy invariants (no intermediate per-purchase opens, no
# reconstruction of realIndex) so any leak in the HTTP runtime shows
# up as a divergence from this reference.


@dataclass
class _BatchPartyState:
    """Simulated per-party state during a distributed batch settlement run.

    Tracks the running "sum of q_minus_c0 shares" — each purchase's
    polynomial evaluation contributes one share of Q_p(s_p) - c_0_p,
    and Shamir linearity lets us add them locally at each party with
    zero network rounds. The public c_0_p terms accumulate in a
    separate public register (they are the constant terms of each
    gain polynomial and are derivable from public inputs, so they do
    not need to stay inside shares).
    """

    validator_x: int
    running_q_minus_c0_share: int = 0


def simulate_distributed_batch_settle(
    batch: list[PurchaseInputs],
    threshold: int,
    prime: int = BN254_PRIME,
) -> BatchSettlementResult:
    """Distributed-protocol simulation of batch settlement.

    For each purchase in the batch:
      1. Each participating validator independently computes the
         public gain vector from the public inputs (notional,
         sla_bps, bpa_mode, bpas, wpas, outcomes).
      2. All participants run the standard sequential polynomial
         evaluation MPC (same wire protocol as ``_secure_select_sequential``
         in mpc_outcome.py) to obtain a SHARE of Q_p(s_p) - c_0_p.
         No party reconstructs the secret index or the individual
         per-purchase gain.
      3. Each participant adds their share to a running sum share
         kept locally, and the public c_0_p constant is added to a
         separate running public register.

    After all purchases process, the running sum shares are
    reconstructed once to get ``sum(Q_p(s_p) - c_0_p)``, and the
    public c_0 register is added to recover
    ``sum(Q_p(s_p)) = total_score_change``.

    The simulation uses ``PolyEvalParticipantState`` from
    mpc_outcome.py, which is the same state machine the real HTTP
    participants will use. This function therefore exercises exactly
    the data shapes and accumulation semantics the HTTP runtime
    needs to implement.
    """
    from djinn_validator.core.mpc import generate_beaver_triples
    from djinn_validator.core.mpc_outcome import (
        PolyEvalParticipantState,
        _triple_indices,
    )

    if not batch:
        return BatchSettlementResult(total_score_change=0, purchase_count=0)

    # Take the participant set from the first purchase. In production
    # every purchase in the batch must use the same (genius, idiot)
    # pair's participant set; the contract-side queue that builds the
    # batch already enforces this.
    ref_shares = batch[0].shares
    x_coords = sorted(s.x for s in ref_shares)
    if len(x_coords) < threshold:
        raise ValueError(f"batch has {len(x_coords)} participants, need at least {threshold}")

    party_states: dict[int, _BatchPartyState] = {vx: _BatchPartyState(validator_x=vx) for vx in x_coords}
    running_public_c_0 = 0

    for purchase_idx, inputs in enumerate(batch):
        # Every purchase MUST reuse the same participant set: the
        # audit batch is for ONE (genius, idiot) pair so all
        # purchases share the same signal-level validator set.
        purchase_xs = sorted(s.x for s in inputs.shares)
        if purchase_xs != x_coords:
            raise ValueError(
                f"purchase {purchase_idx} participant set {purchase_xs} "
                f"does not match batch participant set {x_coords}"
            )

        gain_vector = compute_gain_vector(inputs, prime=prime)
        coeffs = lagrange_interpolation_coefficients(gain_vector, prime)
        c_0 = coeffs[0]

        n_lines = len(gain_vector)
        n_power_gates = n_lines - 2  # gates for s^2..s^(N-1)

        share_map = {s.x: s.y for s in inputs.shares}

        if n_power_gates <= 0:
            # Very small gain vectors: Q(s) = c_0 + c_1*s — no
            # multiplications required. Each party contributes
            # coeffs[1] * s_i to the q_minus_c0 share.
            for vx in x_coords:
                contribution = (coeffs[1] * share_map[vx]) % prime
                party_states[vx].running_q_minus_c0_share = (
                    party_states[vx].running_q_minus_c0_share + contribution
                ) % prime
            running_public_c_0 = (running_public_c_0 + c_0) % prime
            continue

        # Beaver triples for this purchase's gate chain. In the HTTP
        # runtime these come from OT-based distributed generation;
        # the simulator uses the local trusted-dealer version since
        # correctness of the gate math is what matters here.
        triples = generate_beaver_triples(
            n_power_gates,
            n=len(x_coords),
            k=threshold,
            prime=prime,
            x_coords=x_coords,
        )

        participants: dict[int, PolyEvalParticipantState] = {}
        for vx in x_coords:
            participants[vx] = PolyEvalParticipantState(
                validator_x=vx,
                secret_share_y=share_map[vx],
                triple_a=[triples[g].a_shares[i].y for g, i in _triple_indices(vx, x_coords, n_power_gates)],
                triple_b=[triples[g].b_shares[i].y for g, i in _triple_indices(vx, x_coords, n_power_gates)],
                triple_c=[triples[g].c_shares[i].y for g, i in _triple_indices(vx, x_coords, n_power_gates)],
                prime=prime,
            )

        # Run the gate chain. Each gate opens (d, e) publicly — that
        # is a HTTP round-trip in the real protocol and a simulated
        # reconstruct here. The secret index stays in shares.
        prev_d: int | None = None
        prev_e: int | None = None
        for gate_idx in range(n_power_gates):
            d_by_v: dict[int, int] = {}
            e_by_v: dict[int, int] = {}
            for vx in x_coords:
                d_i, e_i = participants[vx].compute_gate(gate_idx, prev_d, prev_e)
                d_by_v[vx] = d_i
                e_by_v[vx] = e_i
            prev_d = reconstruct_at_zero(d_by_v, prime)
            prev_e = reconstruct_at_zero(e_by_v, prime)

        assert prev_d is not None and prev_e is not None
        for vx in x_coords:
            participants[vx].finalize_last_gate(prev_d, prev_e)

        # Each party's share of Q_p(s_p) - c_0_p. Accumulate locally
        # into the running batch sum share. NO reconstruction here —
        # that is the load-bearing privacy invariant.
        for vx in x_coords:
            share = participants[vx].get_outcome_share(coeffs)
            party_states[vx].running_q_minus_c0_share = (party_states[vx].running_q_minus_c0_share + share) % prime

        running_public_c_0 = (running_public_c_0 + c_0) % prime

    # Single open: reconstruct the running sum of (Q_p(s_p) - c_0_p)
    # shares, add the public c_0 register back.
    final_share_map = {st.validator_x: st.running_q_minus_c0_share for st in party_states.values()}
    q_minus_c0_total = reconstruct_at_zero(final_share_map, prime)
    total_field = (q_minus_c0_total + running_public_c_0) % prime
    total_signed = decode_field_to_signed(total_field, prime)

    log.info(
        "distributed_batch_settle_simulated",
        purchase_count=len(batch),
        participants=len(x_coords),
        threshold=threshold,
        total_score_change=total_signed,
    )
    return BatchSettlementResult(
        total_score_change=total_signed,
        purchase_count=len(batch),
    )


# ---------------------------------------------------------------------------
# Peer-side state machine for the HTTP batch settlement runtime
# ---------------------------------------------------------------------------
#
# Each peer running the /v1/mpc/batch/* endpoints keeps one of these
# objects per live session. The state machine is the authoritative
# owner of the per-purchase polynomial-eval state AND the running
# batch sum share. It enforces the protocol's privacy invariant
# (per-purchase gain shares are never exposed to callers) structurally:
# the only way out of the state machine is ``open()``, which returns
# the accumulated sum share — never the individual shares that fed it.
#
# The state machine is deliberately pure Python with no HTTP imports
# so it can be unit-tested in isolation and reused by the endpoint
# handlers without circular dependencies.


class BatchSessionError(Exception):
    """Protocol violation detected in a BatchSession method call.

    Wraps ValueError-style bugs that should produce 4xx-style errors
    in the HTTP runtime rather than crashing the session.
    """


@dataclass
class _PurchaseState:
    """Per-purchase state tracked by a peer inside a batch session.

    Holds the local polynomial-eval participant and a flag marking
    whether this purchase has already been folded into the batch sum
    (accumulation is idempotent by design; calling accumulate twice
    on the same purchase is a protocol violation).

    v1693: ``gate_results`` caches per-gate (d, e) outputs so a retried
    compute_gate call with the same (purchase_idx, gate_idx) returns the
    cached result instead of erroring. Same idempotency story as v1692
    init: _peer_request retries on transport blips and the second call
    must not abort the protocol.
    ``accumulate_done`` mirrors ``accumulated`` but lets a retried
    accumulate succeed silently when state is already correct.
    """

    signal_id: str
    gain_vector: list[int]
    coeffs: list[int]
    c_0: int
    participant: Any  # PolyEvalParticipantState; forward-reference to avoid import cycle
    n_gates: int
    gates_done: int = 0
    accumulated: bool = False
    gate_results: dict[int, tuple[int, int]] = field(default_factory=dict)


class BatchSession:
    """Peer-side state machine for one distributed batch settlement.

    Lifecycle:
      1. ``accept_init(...)`` — seeds the session with this peer's
         Shamir share for each purchase's signal plus the Beaver
         triples supplied by the coordinator. After this call the
         per-purchase polynomial-eval participant states are ready.
      2. Repeated calls to ``compute_gate(purchase_idx, gate_idx,
         prev_d, prev_e)`` to advance each purchase's power chain.
      3. ``accumulate(purchase_idx, last_d, last_e)`` — closes out a
         purchase's gate chain, computes the local share of
         ``Q_p(s_p) - c_0_p``, adds it to the running sum share, and
         adds ``c_0_p`` to the running public register. The
         per-purchase share is discarded after the add (it is NEVER
         stored beyond this method).
      4. ``open()`` — returns the running sum share plus the
         accumulated public c_0 register. The coordinator collects
         threshold such shares and reconstructs the final total.

    Privacy invariant (enforced by construction):
      - ``_running_q_minus_c0_share`` is private; no method returns it
        except ``open()``, which runs only after all purchases are
        accumulated.
      - Per-purchase shares are transient locals inside ``accumulate``
        and are overwritten before the method returns.
    """

    def __init__(
        self,
        session_id: str,
        validator_x: int,
        participant_xs: list[int],
        threshold: int,
        prime: int = BN254_PRIME,
    ) -> None:
        self.session_id = session_id
        self.validator_x = validator_x
        self.participant_xs = sorted(participant_xs)
        self.threshold = threshold
        self.prime = prime
        self._purchases: list[_PurchaseState] = []
        self._running_q_minus_c0_share: int = 0
        self._running_public_c_0: int = 0
        self._purchases_accumulated: int = 0
        self._opened: bool = False
        # Per-session set of (a, b, c) triple hashes seen so far. Beaver
        # triples MUST be one-time-use across multiplications: reusing the
        # same (a, b, c) for two gates leaks the linear relationship and
        # weakens the Beaver protocol's privacy. Codex audit H#4.
        self._used_triple_hashes: set[bytes] = set()

        if validator_x not in self.participant_xs:
            raise BatchSessionError(f"validator_x {validator_x} not in participant set {self.participant_xs}")
        if len(self.participant_xs) < threshold:
            raise BatchSessionError(f"participant count {len(self.participant_xs)} < threshold {threshold}")

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def accept_init(
        self,
        purchases: list[tuple[str, list[int], int, list[tuple[int, int, int]]]],
        share_lookup: Any,
    ) -> None:
        """Seed per-purchase participant states.

        Args:
            purchases: list of (signal_id, gain_vector, purchase_id,
                triple_shares) tuples. ``triple_shares`` is a list of
                (a_share_y, b_share_y, c_share_y) int triples — one
                per gate for this purchase's power chain. The
                coordinator is responsible for handing the peer the
                triple shares keyed to its own validator_x.
            share_lookup: callable signal_id -> int mapping a signal
                to this peer's local Shamir y-coordinate of
                realIndex. In production this wraps share_store.get;
                tests pass a plain dict.
        """
        from djinn_validator.core.mpc_outcome import PolyEvalParticipantState

        if self._purchases:
            raise BatchSessionError("accept_init called twice on same session")
        if not purchases:
            raise BatchSessionError("batch has no purchases")

        for spec in purchases:
            signal_id, gain_vector, _pid, triple_tuples = spec
            if len(gain_vector) < 2:
                raise BatchSessionError(f"gain_vector for {signal_id} has < 2 entries")

            share_y = share_lookup(signal_id)
            if share_y is None:
                raise BatchSessionError(f"no local Shamir share for signal {signal_id}")

            coeffs = lagrange_interpolation_coefficients(gain_vector, self.prime)
            c_0 = coeffs[0]
            n_lines = len(gain_vector)
            n_gates = max(0, n_lines - 2)

            if len(triple_tuples) < n_gates:
                raise BatchSessionError(
                    f"signal {signal_id}: got {len(triple_tuples)} triple shares, " f"need {n_gates}"
                )

            # Reject any (a, b, c) triple we've already seen this session.
            # Reuse breaks Beaver-multiplication privacy by leaking
            # linear relations. Hash deterministically so coordinator
            # mistakes (same triple set passed to two purchases) and
            # adversarial reuse are both caught at init time, not
            # silently accepted. Codex audit 2026-04-15 H#4.
            import hashlib as _hashlib

            for triple in triple_tuples[:n_gates]:
                if len(triple) < 3:
                    raise BatchSessionError(f"signal {signal_id}: malformed triple, expected (a,b,c)")
                a, b, c = int(triple[0]), int(triple[1]), int(triple[2])
                # Field-reduce so equivalent representations hash the same.
                key = b"%d|%d|%d" % (a % self.prime, b % self.prime, c % self.prime)
                h = _hashlib.sha256(key).digest()
                if h in self._used_triple_hashes:
                    raise BatchSessionError(
                        f"signal {signal_id}: beaver triple reused within session "
                        f"(a={hex(a)[:16]}...) — one-time-use violation"
                    )
                self._used_triple_hashes.add(h)

            participant = PolyEvalParticipantState(
                validator_x=self.validator_x,
                secret_share_y=share_y,
                triple_a=[t[0] for t in triple_tuples[:n_gates]],
                triple_b=[t[1] for t in triple_tuples[:n_gates]],
                triple_c=[t[2] for t in triple_tuples[:n_gates]],
                prime=self.prime,
            )

            self._purchases.append(
                _PurchaseState(
                    signal_id=signal_id,
                    gain_vector=list(gain_vector),
                    coeffs=coeffs,
                    c_0=c_0,
                    participant=participant,
                    n_gates=n_gates,
                )
            )

    # ------------------------------------------------------------------
    # Gate chain
    # ------------------------------------------------------------------

    def compute_gate(
        self,
        purchase_idx: int,
        gate_idx: int,
        prev_opened_d: int | None,
        prev_opened_e: int | None,
    ) -> tuple[int, int]:
        """Advance a purchase's power chain by one gate.

        Returns the peer's ``(d_i, e_i)`` shares for the requested
        gate so the coordinator can reconstruct opened (d, e) and
        drive the next gate.

        v1693: idempotent on retry. If the same ``(purchase_idx, gate_idx)``
        was already computed (cached in ``pstate.gate_results``), return
        the cached result. Pre-fix, a coordinator-side _peer_request retry
        on transport blip caused this to raise BatchSessionError ("expected
        gate N+1, got N"), aborting the whole shadow_settle. Same root
        cause as v1692 init idempotency.
        """
        self._require_init()
        self._check_purchase_idx(purchase_idx)

        pstate = self._purchases[purchase_idx]
        if pstate.accumulated:
            raise BatchSessionError(f"purchase {purchase_idx} already accumulated — cannot compute more gates")
        if pstate.n_gates == 0:
            raise BatchSessionError(f"purchase {purchase_idx} has no gates (n_lines={len(pstate.gain_vector)})")

        # v1693: idempotent retry — return cached result if this gate was
        # already processed.
        cached = pstate.gate_results.get(gate_idx)
        if cached is not None:
            return cached

        if gate_idx != pstate.gates_done:
            raise BatchSessionError(f"purchase {purchase_idx}: expected gate {pstate.gates_done}, got {gate_idx}")

        d_i, e_i = pstate.participant.compute_gate(gate_idx, prev_opened_d, prev_opened_e)
        pstate.gates_done += 1
        pstate.gate_results[gate_idx] = (d_i, e_i)
        return d_i, e_i

    def accumulate(
        self,
        purchase_idx: int,
        last_opened_d: int | None,
        last_opened_e: int | None,
    ) -> None:
        """Fold a completed purchase's output share into the running sum.

        For gated purchases (n_gates > 0) the caller must supply the
        last opened (d, e) from the final gate round. For the
        trivial 2-line case (n_gates == 0) both arguments must be
        None because no multiplication ran.

        v1693: idempotent on retry. If the purchase is already
        accumulated, return silently (no error). The sum_share is
        already correct; double-folding would corrupt it, but a no-op
        is safe and matches the v1692 init / v1693 compute_gate idempotency.
        """
        self._require_init()
        self._check_purchase_idx(purchase_idx)

        pstate = self._purchases[purchase_idx]
        if pstate.accumulated:
            # v1693: silent no-op on retry (was BatchSessionError pre-fix).
            return
        if pstate.n_gates == 0:
            # 2-line special case: share of Q(s) - c_0 = c_1 * s_i.
            if last_opened_d is not None or last_opened_e is not None:
                raise BatchSessionError("2-line purchase has no final gate — last_opened_d/e must be None")
            share = (pstate.coeffs[1] * pstate.participant.secret_share_y) % self.prime
        else:
            if last_opened_d is None or last_opened_e is None:
                raise BatchSessionError(f"purchase {purchase_idx}: last_opened_d/e required for gated accumulation")
            if pstate.gates_done != pstate.n_gates:
                raise BatchSessionError(
                    f"purchase {purchase_idx}: expected {pstate.n_gates} gates done, " f"got {pstate.gates_done}"
                )
            pstate.participant.finalize_last_gate(last_opened_d, last_opened_e)
            share = pstate.participant.get_outcome_share(pstate.coeffs)

        # Fold into running sum. Local variable ``share`` goes out of
        # scope at return — per-purchase shares are never stored on
        # the instance.
        self._running_q_minus_c0_share = (self._running_q_minus_c0_share + share) % self.prime
        self._running_public_c_0 = (self._running_public_c_0 + pstate.c_0) % self.prime
        pstate.accumulated = True
        self._purchases_accumulated += 1

    def open(self) -> tuple[int, int]:
        """Return the running sum share + public c_0 register.

        This is the ONLY method that exposes the accumulated share.
        It may only be called after every purchase in the batch has
        been accumulated; calling it early is a protocol violation
        and raises BatchSessionError.

        Returns:
            (sum_share, public_c_0_sum) where:
              - ``sum_share`` is this peer's Shamir share of
                ``sum_p (Q_p(s_p) - c_0_p)`` across the batch
              - ``public_c_0_sum`` is the public constant accumulator
                ``sum_p c_0_p`` — identical across all peers, echoed
                so the coordinator can sanity-check consistency
        """
        self._require_init()
        if self._purchases_accumulated != len(self._purchases):
            raise BatchSessionError(
                f"open called with {self._purchases_accumulated}/" f"{len(self._purchases)} purchases accumulated"
            )
        self._opened = True
        return self._running_q_minus_c0_share, self._running_public_c_0

    @property
    def purchases_accumulated(self) -> int:
        return self._purchases_accumulated

    @property
    def purchase_count(self) -> int:
        return len(self._purchases)

    @property
    def opened(self) -> bool:
        return self._opened

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _require_init(self) -> None:
        if not self._purchases:
            raise BatchSessionError("session has not been initialized")

    def _check_purchase_idx(self, idx: int) -> None:
        if idx < 0 or idx >= len(self._purchases):
            raise BatchSessionError(f"purchase_idx {idx} out of range [0, {len(self._purchases)})")


# ---------------------------------------------------------------------------
# Coordinator driver
# ---------------------------------------------------------------------------
#
# Drives the full init -> compute_gate -> accumulate -> open protocol
# across N peers using an injectable RPC callable. Production wires
# this to the existing httpx client in MPCOrchestrator; tests inject a
# direct-dispatch callable that talks to FastAPI TestClient instances
# so the protocol can run in-process without real sockets.


def build_purchase_inputs_from_audit_set(
    audit_set: Any,
    *,
    share_store: Any,
    purchase_odds_ledger: Any,
    line_outcomes_override: dict[str, list[Any]] | None = None,
) -> list[PurchaseInputs] | None:
    """Assemble ``PurchaseInputs`` for every signal in an ``AuditSet``.

    Pulls the local Shamir index share from ``share_store`` (one entry
    in the ``shares`` list — the protocol looks up y-values on each
    peer independently, so the other peers' shares are never needed
    here) and the BPA/WPA vectors from ``purchase_odds_ledger`` keyed
    by (signal_id, idiot_address).

    **Determinism contract (P0-01 Stage B, v1576):** iterates
    ``audit_set.signals`` in ascending ``purchase_id`` order so the
    resulting ``[p.purchase_id for p in batch]`` is byte-identical
    across validators. OutcomeVoting.sol derives
    ``batchKey = keccak256(genius, idiot, keccak256(purchase_ids))``
    and scoreHash depends on batch membership, so any per-validator
    filtering breaks quorum: voters end up on different batchKeys or
    different scoreHashes and the 4-of-6 threshold never coalesces.

    Returns None if ANY signal in the canonical set is missing its
    outcomes, its local share, or its BPA/WPA vectors — the validator
    abstains from this whole batch rather than submitting a partial
    vote that diverges from peers. This used to branch on ``version``:
    v1 abstained, v2 silently skipped, which was itself the direct
    cause of the observed on-chain "8 votes, 0 quorum" pattern in the
    last 5k Sepolia blocks (see MAINNET_BLOCKERS.md P0-01).

    On each abstain, increments ``BUILD_PI_ABSTAIN_REASON{reason=...}``
    so operators can localize the missing data layer remotely via
    ``/metrics`` without SSH (v1698).
    """
    # v1698: per-cause abstain reason. Best-effort import via the shared
    # safe_label_inc helper so test paths that bypass the metrics module
    # continue to work.
    from djinn_validator.api.metrics import (
        BUILD_PI_ABSTAIN_REASON,
        safe_label_inc,
    )

    def _tick(reason: str) -> None:
        safe_label_inc(BUILD_PI_ABSTAIN_REASON, reason=reason)

    if audit_set is None or not audit_set.signals:
        _tick("no_audit_set")
        return None

    # P0-01 root cause (v1637, 2026-05-01): under v2 audit sets,
    # ``ready_for_settlement`` only requires ``len(resolved_signals) >=
    # MIN_BATCH_SIZE``, so a set of 10 resolved + 1 pending is "ready" but
    # the first pending signal hits ``signal.outcomes is None`` and
    # ``build_pi_abstain_missing_outcomes`` abstains the whole batch. This
    # was the dominant ``shadow_settle_no_batch`` cause across the fleet.
    # Fix: iterate ONLY ``resolved_signals``. Two validators that converge
    # on the same on-chain outcome set produce byte-identical purchase_ids
    # and scoreHash; the unresolved tail (newer purchases whose games
    # haven't ended) stays in the audit_set for the next settle cycle.
    resolved = [s for s in audit_set.signals.values() if s.outcomes is not None]
    if not resolved:
        _tick("no_resolved")
        return None
    signal_list = sorted(
        resolved,
        key=lambda s: (int(s.purchase_id), s.signal_id),
    )

    batch: list[PurchaseInputs] = []
    for signal in signal_list:
        signal_id = signal.signal_id
        if signal.outcomes is None:
            log.info(
                "build_pi_abstain_missing_outcomes",
                signal_id=signal_id[:20],
            )
            _tick("missing_outcomes")
            return None

        # Local Shamir share of realIndex for this signal.
        # v1700: split the abstain reason between "no record at all"
        # (validator never received the share OR recovery never found
        # a peer with it) and "record exists but encrypted_index_share
        # is empty bytes" (commit path stored a record without the
        # index share — different bug class). Operators reading
        # /metrics see which one is dominant before ascribing missing
        # data to gossip vs to commit-side validation.
        rec = share_store.get(signal_id)
        if rec is None:
            log.info(
                "build_pi_abstain_missing_share",
                signal_id=signal_id[:20],
                reason="no_record",
            )
            _tick("missing_share")
            return None
        if not rec.encrypted_index_share:
            log.info(
                "build_pi_abstain_missing_share",
                signal_id=signal_id[:20],
                reason="empty_index_share",
                share_x=getattr(getattr(rec, "share", None), "x", None),
            )
            _tick("empty_index_share")
            return None
        local_share = Share(
            x=rec.share.x,
            y=int.from_bytes(rec.encrypted_index_share, "big"),
        )

        # BPA/WPA vectors committed at purchase time. Keyed by the
        # idiot address on the audit set — one buyer per (genius,
        # idiot) pair inside a batch.
        if purchase_odds_ledger is None:
            log.info("build_pi_abstain_no_ledger", signal_id=signal_id[:20])
            _tick("no_ledger")
            return None
        po_rec = purchase_odds_ledger.get(
            signal_id=signal_id,
            buyer_address=audit_set.idiot_address,
        )
        if po_rec is None:
            log.info(
                "build_pi_abstain_missing_bpa_wpa",
                signal_id=signal_id[:20],
                idiot=audit_set.idiot_address[:10],
            )
            _tick("missing_bpa_wpa")
            return None

        if len(po_rec.bpas) != len(po_rec.wpas) or len(po_rec.bpas) != len(signal.outcomes):
            log.warning(
                "build_pi_vector_length_mismatch",
                signal_id=signal_id[:20],
                n_bpas=len(po_rec.bpas),
                n_wpas=len(po_rec.wpas),
                n_outcomes=len(signal.outcomes),
            )
            _tick("vector_mismatch")
            return None

        # v1747 Phase 4: when ``line_outcomes_override`` is provided, the
        # canonical chain-read outcomes win over local. Caller (MPC
        # orchestrator) is responsible for the honesty gate (rejecting
        # batches where local diverges from canonical) BEFORE building
        # PurchaseInputs, so by the time we read the override here the
        # values are already vetted to match local. The override exists
        # solely to make the deterministic-input contract explicit: every
        # validator builds purchase inputs from the same chain-read
        # values, not from per-validator ESPN polls.
        outcomes_for_inputs = signal.outcomes
        if line_outcomes_override is not None and signal_id in line_outcomes_override:
            outcomes_for_inputs = line_outcomes_override[signal_id]
            if len(outcomes_for_inputs) != len(signal.outcomes):
                log.warning(
                    "build_pi_canonical_override_length_mismatch",
                    signal_id=signal_id[:20],
                    canonical_len=len(outcomes_for_inputs),
                    local_len=len(signal.outcomes),
                )
                _tick("canonical_override_length_mismatch")
                return None

        batch.append(
            PurchaseInputs(
                purchase_id=signal.purchase_id,
                shares=[local_share],
                notional=signal.notional,
                sla_bps=signal.sla_bps,
                bpa_mode=po_rec.bpa_mode,
                bpas=list(po_rec.bpas),
                wpas=list(po_rec.wpas),
                outcomes=[
                    o.value if hasattr(o, "value") else int(o)
                    for o in outcomes_for_inputs
                ],
                signal_id=signal_id,
            )
        )

    if not batch:
        _tick("empty_batch")
        return None
    return batch


def generate_batch_beaver_triples(
    batch: list[PurchaseInputs],
    *,
    participant_xs: list[int],
    threshold: int,
    prime: int = BN254_PRIME,
) -> list[list[Any]]:
    """Generate the full set of Beaver triples a batch settlement needs.

    One triple list per purchase, each list containing ``n_gates``
    triples where ``n_gates = len(gain_vector) - 2`` (the number of
    sequential power-chain multiplications a sequential
    polynomial evaluation needs for that purchase). Purchases with
    n_lines <= 2 get an empty list and run without multiplications.

    Uses the existing trusted-dealer
    ``djinn_validator.core.mpc.generate_beaver_triples`` — the same
    helper ``_secure_select_sequential`` already uses for single-
    purchase polynomial evaluation. OT-based distributed triple
    generation is orthogonal and can replace this helper later; for
    MVP a trusted-dealer fallback has the same trust model as the
    existing precompute_triples_for_signal fallback path.

    Returns a list aligned with ``batch`` so the coordinator can
    pass it directly as ``beaver_triples_per_purchase`` to
    ``drive_http_batch_settlement`` or
    ``MPCOrchestrator.run_batch_settlement``.
    """
    from djinn_validator.core.mpc import generate_beaver_triples as _gen

    triples_per_purchase: list[list[Any]] = []
    for inputs in batch:
        gain_vector = compute_gain_vector(inputs, prime=prime)
        n_lines = len(gain_vector)
        n_gates = max(0, n_lines - 2)
        if n_gates == 0:
            triples_per_purchase.append([])
            continue
        triples_per_purchase.append(
            _gen(
                n_gates,
                n=len(participant_xs),
                k=threshold,
                prime=prime,
                x_coords=sorted(participant_xs),
            )
        )
    return triples_per_purchase


async def drive_http_batch_settlement(
    *,
    session_id: str,
    participant_xs: list[int],
    threshold: int,
    batch: list[PurchaseInputs],
    beaver_triples_per_purchase: list[list[Any]],
    peer_rpc: Any,
    prime: int = BN254_PRIME,
) -> BatchSettlementResult:
    """Run a distributed batch settlement as the coordinator.

    Args:
        session_id: unique session identifier (e.g. "batch-{genius}-{idiot}-{cycle}")
        participant_xs: Shamir x-coords of the peers participating in
            the batch. Order must match the peer_rpc dispatch keys.
        threshold: minimum peers whose sum shares must agree for
            reconstruction. Must be <= len(participant_xs).
        batch: list of PurchaseInputs. Only the ``notional``,
            ``sla_bps``, ``bpa_mode``, ``bpas``, ``wpas``, ``outcomes``,
            and ``purchase_id`` fields are used — the ``shares`` field
            on each PurchaseInputs is NOT transmitted (each peer looks
            up its own Shamir share locally).
        beaver_triples_per_purchase: one list of BeaverTriple objects
            per purchase, with length equal to ``len(gain_vector) - 2``
            (the number of sequential power gates). Empty list for
            2-line purchases.
        peer_rpc: async callable with signature
            ``async def(validator_x: int, endpoint: str, payload: dict) -> dict``.
            Must return the JSON body of the response or raise on
            failure. The coordinator does not know or care how the
            RPC is transported.
        prime: field prime (defaults to BN254).

    Returns:
        BatchSettlementResult with the reconstructed batch total.

    Raises:
        BatchSessionError on protocol violations.
        Whatever peer_rpc raises on transport failures.
    """
    if not batch:
        return BatchSettlementResult(total_score_change=0, purchase_count=0)
    if len(beaver_triples_per_purchase) != len(batch):
        raise BatchSessionError(
            f"beaver_triples_per_purchase length {len(beaver_triples_per_purchase)} "
            f"does not match batch length {len(batch)}"
        )
    if len(participant_xs) < threshold:
        raise BatchSessionError(f"participant count {len(participant_xs)} < threshold {threshold}")

    gain_vectors: list[list[int]] = [compute_gain_vector(p, prime=prime) for p in batch]

    # Build per-peer init payloads. Each peer gets its own slice of
    # every purchase's Beaver triples.
    for vx in participant_xs:
        purchases_payload = []
        x_idx = participant_xs.index(vx)
        for p_idx, purchase in enumerate(batch):
            gv = gain_vectors[p_idx]
            triples = beaver_triples_per_purchase[p_idx]
            peer_triples = []
            for t in triples:
                peer_triples.append(
                    {
                        "a": hex(t.a_shares[x_idx].y),
                        "b": hex(t.b_shares[x_idx].y),
                        "c": hex(t.c_shares[x_idx].y),
                    }
                )
            # v1560: signal_id MUST be the real ShareStore key so each peer
            # can look up its own share via _resolve_my_validator_x. The
            # prior placeholder "sig-{purchase_id}" shipped in bad6bd25
            # (first MPC HTTP driver) was never updated when PurchaseInputs
            # gained a real signal_id field — it silently made /v1/mpc/batch/init
            # 404 on every peer because no share_store has a "sig-<pid>" key.
            # Diagnosed 2026-04-21 after v1559 fix unblocked first shadow
            # attempt on UID 0. Falls back to the legacy form if signal_id
            # is empty (paid tests construct PurchaseInputs without it).
            purchases_payload.append(
                {
                    "purchase_id": purchase.purchase_id,
                    "signal_id": purchase.signal_id or f"sig-{purchase.purchase_id}",
                    "gain_vector": [hex(g) for g in gv],
                    "triple_shares": peer_triples,
                }
            )

        init_body = await peer_rpc(
            vx,
            "init",
            {
                "session_id": session_id,
                "coordinator_x": participant_xs[0],
                "participant_xs": participant_xs,
                "threshold": threshold,
                "purchases": purchases_payload,
            },
        )
        if not init_body.get("accepted"):
            raise BatchSessionError(f"peer {vx} rejected batch init: {init_body}")

    # Drive per-purchase gate chain.
    from djinn_validator.core.mpc import reconstruct_at_zero

    for p_idx, purchase in enumerate(batch):
        gv = gain_vectors[p_idx]
        n_gates = max(0, len(gv) - 2)

        prev_d: str | None = None
        prev_e: str | None = None
        for g_idx in range(n_gates):
            d_shares: dict[int, int] = {}
            e_shares: dict[int, int] = {}
            for vx in participant_xs:
                body = await peer_rpc(
                    vx,
                    "compute_gate",
                    {
                        "session_id": session_id,
                        "purchase_idx": p_idx,
                        "gate_idx": g_idx,
                        "prev_opened_d": prev_d,
                        "prev_opened_e": prev_e,
                    },
                )
                d_shares[vx] = int(body["d_value"], 16)
                e_shares[vx] = int(body["e_value"], 16)
            prev_d = hex(reconstruct_at_zero(d_shares, prime))
            prev_e = hex(reconstruct_at_zero(e_shares, prime))

        # For 2-line purchases (n_gates == 0) the gate loop above never
        # runs and prev_d/prev_e stay None.  Forward that None through
        # to the peer's accumulate() — `BatchSession.accumulate` requires
        # None (not 0 or "0x0") for the trivial path.  Sending hex(0) used
        # to silently break every 2-line purchase end-to-end (codex audit
        # 2026-04-15).
        for vx in participant_xs:
            await peer_rpc(
                vx,
                "accumulate",
                {
                    "session_id": session_id,
                    "purchase_idx": p_idx,
                    "last_opened_d": prev_d,
                    "last_opened_e": prev_e,
                },
            )

    # Open every peer, collect sum shares, reconstruct.
    sum_shares: dict[int, int] = {}
    public_c0_values: set[int] = set()
    for vx in participant_xs:
        body = await peer_rpc(vx, "open", {"session_id": session_id})
        sum_shares[vx] = int(body["sum_share"], 16)
        public_c0_values.add(int(body["public_c_0_sum"], 16))

    if len(public_c0_values) != 1:
        raise BatchSessionError(f"peers disagree on public c_0 sum: {sorted(public_c0_values)}")
    public_c_0 = public_c0_values.pop()

    q_minus_c0_total = reconstruct_at_zero(sum_shares, prime)
    total_field = (q_minus_c0_total + public_c_0) % prime
    total_signed = decode_field_to_signed(total_field, prime)

    log.info(
        "distributed_batch_settle_http_complete",
        session_id=session_id,
        participants=len(participant_xs),
        purchase_count=len(batch),
        total_score_change=total_signed,
    )
    return BatchSettlementResult(
        total_score_change=total_signed,
        purchase_count=len(batch),
    )
