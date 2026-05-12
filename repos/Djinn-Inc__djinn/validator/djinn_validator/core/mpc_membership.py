"""Secure set-membership test via masked polynomial zero-evaluation.

Problem
-------
Validators jointly hold Shamir shares of a secret index ``r``. A buyer
provides a public set ``A = {a_1, ..., a_k}``. Decide whether ``r in A``
without leaking any information about ``r`` beyond the single bit
"yes / no".

Approach
--------
1. Compute the polynomial ``p(x) = prod_i (x - a_i)`` over the Shamir field.
   Its coefficients are fully public (derived from ``A``) and
   ``p(r) == 0`` iff ``r in A``.
2. Evaluate ``[p(r)]`` in MPC using the parallel power-tree primitive from
   ``mpc_outcome.py``: compute ``[r^2], [r^3], ..., [r^k]`` in ``O(log k)``
   parallel Beaver-triple rounds, then combine linearly with the public
   coefficients (local, free in Shamir).
3. Multiply the result by a fresh shared random ``[s]`` unknown to any
   party, giving ``[s * p(r)]``. Reveal this value.
4. ``revealed == 0`` iff ``p(r) == 0`` iff ``r in A``.

Leakage (exactly 1 bit, same as current sequential-gate protocol)
-----------------------------------------------------------------
- If ``p(r) == 0``: revealed value is ``0``. Confirms membership. Nothing
  else is learned.
- If ``p(r) != 0``: revealed value is ``s * p(r)``. Because ``s`` is
  uniform in ``F*`` and unknown to any party, ``s * p(r)`` is distributed
  uniformly over ``F*`` and reveals **nothing** about ``p(r)``, the
  polynomial coefficients' effect, or ``r``.
- ``r`` itself is never reconstructed. Every intermediate value opened
  during the power tree is of the form ``power - triple_a``, where
  ``triple_a`` is uniformly random, so each open is uniform random and
  leaks nothing.

Round count
-----------
``ceil(log2(k)) + 2`` network rounds:

- ``ceil(log2(k))`` rounds for the power tree ``[r^2]..[r^k]``
- 1 round for the mask multiply ``[s] * [p(r)]``
- 1 round for the final reveal of ``[s * p(r)]``

For ``k = 200`` this is 10 rounds vs. the current 200.

This module
-----------
Pure local-simulation implementation used for unit tests and as the
reference for the distributed HTTP variant in
``mpc_orchestrator._distributed_mpc``. All participants run inside a
single Python process in the trusted-dealer model: one entry point
receives every share, simulates the protocol end-to-end, and returns the
revealed value.
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass, field

import structlog

from djinn_validator.core.mpc import (
    generate_beaver_triples,
    reconstruct_at_zero,
)
from djinn_validator.core.mpc_outcome import plan_parallel_powers
from djinn_validator.utils.crypto import BN254_PRIME, Share

log = structlog.get_logger()


@dataclass(frozen=True)
class MembershipResult:
    """Outcome of a set-membership test.

    ``in_set`` is the decided bit. ``revealed`` is the actual field element
    opened at the end of the protocol; callers typically ignore it but
    leakage tests inspect it directly.
    """

    in_set: bool
    revealed: int
    rounds: int


def polynomial_from_roots(
    roots: list[int],
    prime: int = BN254_PRIME,
) -> list[int]:
    """Expand ``p(x) = prod_i (x - r_i)`` into coefficient form.

    Returns ``[c_0, c_1, ..., c_k]`` such that ``p(x) = sum_j c_j * x^j``
    over the field. Pure public arithmetic, no secrets involved.
    """
    coeffs: list[int] = [1]
    for r in roots:
        new_coeffs = [0] * (len(coeffs) + 1)
        neg_r = (-r) % prime
        for i, c in enumerate(coeffs):
            new_coeffs[i] = (new_coeffs[i] + c * neg_r) % prime
            new_coeffs[i + 1] = (new_coeffs[i + 1] + c) % prime
        coeffs = new_coeffs
    return coeffs


def _triple_shares_for_party(
    triples: list,
    x_coords: list[int],
    party_x: int,
    n_gates: int,
) -> tuple[list[int], list[int], list[int]]:
    """Extract a party's a/b/c share values for gates 0..n_gates-1."""
    idx = x_coords.index(party_x)
    a_shares = [triples[g].a_shares[idx].y for g in range(n_gates)]
    b_shares = [triples[g].b_shares[idx].y for g in range(n_gates)]
    c_shares = [triples[g].c_shares[idx].y for g in range(n_gates)]
    return a_shares, b_shares, c_shares


def local_check_membership(
    shares: list[Share],
    available_indices: list[int],
    threshold: int,
    prime: int = BN254_PRIME,
    _forced_mask: int | None = None,
) -> MembershipResult:
    """Run the membership test in local-simulation (trusted-dealer) mode.

    Every participant runs inside this function. All Beaver triples and
    the random mask ``s`` are generated here as if by a trusted dealer.
    This matches the local-shares mode used on testnet and serves as the
    reference implementation for the distributed HTTP variant.

    Args:
        shares: Shamir shares of the secret index ``r``. Must have at
            least ``threshold`` shares.
        available_indices: Public set ``A``. Must be non-empty.
        threshold: Shamir reconstruction threshold.
        prime: Field prime (default BN254 scalar field).
        _forced_mask: Test-only override to force a specific mask value.
            Production code never sets this.

    Returns:
        ``MembershipResult`` with the decided bit, the actual revealed
        field element, and the round count.
    """
    if not available_indices:
        raise ValueError("available_indices must be non-empty")
    if len(shares) < threshold:
        raise ValueError(f"need at least {threshold} shares, got {len(shares)}")

    x_coords = sorted(s.x for s in shares)
    share_map = {s.x: s.y for s in shares}
    k = len(available_indices)

    coeffs = polynomial_from_roots(list(available_indices), prime)

    # Step 1: compute shared powers [r^2], [r^3], ..., [r^k].
    # Power 1 is the input share, powers 2..k are built via the parallel
    # tree in log k rounds.
    max_power = k
    power_shares: dict[int, dict[int, int]] = {
        1: {vx: share_map[vx] for vx in x_coords},
    }

    if max_power >= 2:
        rounds = plan_parallel_powers(max_power)
    else:
        rounds = []

    power_round_count = len(rounds)
    total_tree_gates = sum(len(r) for r in rounds)

    # Allocate triples: total_tree_gates for the power tree, plus 1 for
    # the mask multiply at the end.
    n_triples = total_tree_gates + 1
    triples = generate_beaver_triples(
        n_triples,
        n=len(shares),
        k=threshold,
        prime=prime,
        x_coords=x_coords,
    )

    # Pre-cache x_coord index for each party to avoid repeated .index() calls.
    x_idx = {vx: i for i, vx in enumerate(x_coords)}

    gate_cursor = 0
    for round_ops in rounds:
        # Phase A: each party locally computes (d_i, e_i) for every op in
        # this round, using the pre-generated triple at gate=gate_cursor+op.
        # The coordinator opens d and e for each op. All ops in one round
        # correspond to one HTTP round in the distributed version.
        opened_de: list[tuple[int, int, int, int]] = []  # (gate, target_pow, d, e)
        for op_i, (a_pow, b_pow) in enumerate(round_ops):
            g = gate_cursor + op_i
            d_shares: dict[int, int] = {}
            e_shares: dict[int, int] = {}
            for vx in x_coords:
                a_y = triples[g].a_shares[x_idx[vx]].y
                b_y = triples[g].b_shares[x_idx[vx]].y
                d_shares[vx] = (power_shares[a_pow][vx] - a_y) % prime
                e_shares[vx] = (power_shares[b_pow][vx] - b_y) % prime
            opened_d = reconstruct_at_zero(d_shares, prime)
            opened_e = reconstruct_at_zero(e_shares, prime)
            opened_de.append((g, a_pow + b_pow, opened_d, opened_e))

        # Phase B: each party computes its share of the product using the
        # opened d, e and its own triple shares. Local arithmetic, no comms.
        for g, target_power, opened_d, opened_e in opened_de:
            new_share_map: dict[int, int] = {}
            for vx in x_coords:
                a_y = triples[g].a_shares[x_idx[vx]].y
                b_y = triples[g].b_shares[x_idx[vx]].y
                c_y = triples[g].c_shares[x_idx[vx]].y
                new_share_map[vx] = (opened_d * opened_e + opened_d * b_y + opened_e * a_y + c_y) % prime
            power_shares[target_power] = new_share_map

        gate_cursor += len(round_ops)

    # Step 2: compute [q] = [p(r)] = sum_j c_j * [r^j] using public
    # coefficients. This is a free local linear combination.
    q_shares: dict[int, int] = {}
    for vx in x_coords:
        q_y = coeffs[0] % prime  # c_0 is public constant, added as-is
        for j in range(1, len(coeffs)):
            q_y = (q_y + coeffs[j] * power_shares[j][vx]) % prime
        q_shares[vx] = q_y

    # NOTE: the c_0 term is a public constant. In Shamir, adding a public
    # constant to every share yields a share of secret+constant. Doing it
    # locally keeps the degree correct. This is the standard "public + secret"
    # rule in Shamir and introduces no communication.

    # Step 3: generate a fresh random mask [s] unknown to any party and
    # multiply by [q] via one Beaver round.
    if _forced_mask is not None:
        s = _forced_mask
    else:
        # In the distributed version, s comes from an unused Beaver triple's
        # a-component (uniformly random, unknown to any party). In local
        # simulation we just sample it.
        s = secrets.randbelow(prime - 1) + 1

    # Split s into Shamir shares at x_coords (trusted dealer in local mode).
    from djinn_validator.core.mpc import _split_secret_at_points

    s_shares_list = _split_secret_at_points(s, x_coords, threshold, prime)
    s_shares = {sh.x: sh.y for sh in s_shares_list}

    # Final triple for the mask multiply.
    g_final = n_triples - 1
    d_shares_final: dict[int, int] = {}
    e_shares_final: dict[int, int] = {}
    for vx in x_coords:
        a_y = triples[g_final].a_shares[x_idx[vx]].y
        b_y = triples[g_final].b_shares[x_idx[vx]].y
        d_shares_final[vx] = (s_shares[vx] - a_y) % prime
        e_shares_final[vx] = (q_shares[vx] - b_y) % prime
    opened_d_final = reconstruct_at_zero(d_shares_final, prime)
    opened_e_final = reconstruct_at_zero(e_shares_final, prime)

    mask_product_shares: dict[int, int] = {}
    for vx in x_coords:
        a_y = triples[g_final].a_shares[x_idx[vx]].y
        b_y = triples[g_final].b_shares[x_idx[vx]].y
        c_y = triples[g_final].c_shares[x_idx[vx]].y
        mask_product_shares[vx] = (
            opened_d_final * opened_e_final + opened_d_final * b_y + opened_e_final * a_y + c_y
        ) % prime

    # Step 4: reveal [s * p(r)] by reconstructing at x=0.
    revealed = reconstruct_at_zero(mask_product_shares, prime)

    in_set = revealed == 0
    total_rounds = power_round_count + 2  # power tree + mask multiply + reveal

    return MembershipResult(
        in_set=in_set,
        revealed=revealed,
        rounds=total_rounds,
    )


# ---------------------------------------------------------------------------
# Distributed per-peer state machine
# ---------------------------------------------------------------------------
#
# The classes below are what each validator runs during a real distributed
# purchase. One validator is the coordinator (the one that received the
# buyer's /purchase request). The others are peers. The wire protocol is:
#
#   1. coordinator → peer   POST /v1/mpc/membership/init
#                           { session_id, threshold, available_indices,
#                             triple_shares, mask_share }
#   2. for each power-tree round:
#        coordinator → peer POST /v1/mpc/membership/round
#                           { session_id, round_idx, ops, prev_opened }
#                        ← { op_shares }   (d_i, e_i per op)
#   3. coordinator → peer   POST /v1/mpc/membership/finalize_mask
#                           { session_id, final_opened_powers, coefficients }
#                        ← { mask_d_share, mask_e_share }
#   4. coordinator → peer   POST /v1/mpc/membership/reveal
#                           { session_id, mask_opened_d, mask_opened_e }
#                        ← { product_share }   (share of [s * p(r)])
#
# Peers are stateless across sessions except for a dict keyed by session_id
# that they wipe after reveal. The coordinator interpolates the final shares
# at x=0 and checks whether the revealed value is zero.


@dataclass
class MembershipRoundOp:
    """One multiplication in a power-tree round: compute [r^(a+b)] = [r^a]*[r^b]."""

    gate_idx: int
    a_pow: int
    b_pow: int


@dataclass
class MembershipOpenedPower:
    """Publicly opened d, e values from a completed power-tree multiplication."""

    gate_idx: int
    target_pow: int
    opened_d: int
    opened_e: int


@dataclass
class MembershipPeerState:
    """Per-session state held by one validator during a distributed membership check.

    The coordinator instantiates one for itself and initializes remote peers
    by POSTing to /v1/mpc/membership/init. Thereafter, each peer updates
    this state as rounds come in.

    Shared values (triples, mask) are always represented as the local
    party's share only — the full value never materializes in this object.
    """

    validator_x: int
    threshold: int
    available_indices: list[int]
    triple_a: list[int]  # len = n_power_gates + 1
    triple_b: list[int]
    triple_c: list[int]
    mask_share: int  # this party's share of s
    power_shares: dict[int, int] = field(default_factory=dict)
    prime: int = BN254_PRIME
    coefficients: list[int] = field(default_factory=list)
    q_share: int | None = None  # local share of [p(r)] after linear combination

    def set_initial_secret_share(self, secret_share_y: int) -> None:
        """Power 1 is the secret share itself; store it as the seed."""
        self.power_shares[1] = secret_share_y

    def compute_round(
        self,
        ops: list[MembershipRoundOp],
    ) -> list[tuple[int, int, int]]:
        """Compute (gate_idx, d_i, e_i) for each op in a power-tree round.

        Called once per round. The caller (coordinator) must have ensured
        that the operands for each op are already in ``power_shares`` —
        either because they were loaded at init (power 1) or finalized
        by the previous round's ``finalize_round`` call.
        """
        p = self.prime
        out: list[tuple[int, int, int]] = []
        for op in ops:
            if op.a_pow not in self.power_shares:
                raise ValueError(
                    f"missing power share for a_pow={op.a_pow} " f"(have {sorted(self.power_shares.keys())})"
                )
            if op.b_pow not in self.power_shares:
                raise ValueError(f"missing power share for b_pow={op.b_pow}")
            x_input = self.power_shares[op.a_pow]
            y_input = self.power_shares[op.b_pow]
            d_i = (x_input - self.triple_a[op.gate_idx]) % p
            e_i = (y_input - self.triple_b[op.gate_idx]) % p
            out.append((op.gate_idx, d_i, e_i))
        return out

    def finalize_round(
        self,
        opened: list[MembershipOpenedPower],
    ) -> None:
        """Incorporate the coordinator's opened d, e for each op and store
        this party's share of the resulting power."""
        p = self.prime
        for o in opened:
            a_y = self.triple_a[o.gate_idx]
            b_y = self.triple_b[o.gate_idx]
            c_y = self.triple_c[o.gate_idx]
            self.power_shares[o.target_pow] = (o.opened_d * o.opened_e + o.opened_d * b_y + o.opened_e * a_y + c_y) % p

    def compute_q_share(self, coefficients: list[int]) -> int:
        """Compute this party's share of [q] = [p(r)] from stored power shares.

        p(x) = sum_j c_j * x^j. Each party computes:
          [q]_i = c_0 + sum_{j>=1} c_j * [r^j]_i

        c_0 is added locally. In Shamir, adding a public constant to every
        party's share is equivalent to adding it to the reconstructed secret.
        """
        if not coefficients:
            raise ValueError("coefficients must be non-empty")
        p = self.prime
        self.coefficients = list(coefficients)
        q_y = coefficients[0] % p
        for j in range(1, len(coefficients)):
            if j not in self.power_shares:
                raise ValueError(f"missing power share for j={j}; " f"have {sorted(self.power_shares.keys())}")
            q_y = (q_y + coefficients[j] * self.power_shares[j]) % p
        self.q_share = q_y
        return q_y

    def compute_mask_multiply_shares(self) -> tuple[int, int]:
        """Compute (d_i, e_i) for the final mask multiplication [s] * [q].

        Uses the last Beaver triple (index -1 in triple_a/b/c). The caller
        must have called ``compute_q_share`` first.
        """
        if self.q_share is None:
            raise ValueError("compute_q_share must be called first")
        p = self.prime
        a_y = self.triple_a[-1]
        b_y = self.triple_b[-1]
        d_i = (self.mask_share - a_y) % p
        e_i = (self.q_share - b_y) % p
        return d_i, e_i

    def compute_product_share(
        self,
        opened_d: int,
        opened_e: int,
    ) -> int:
        """Final step: compute this party's share of [s * q] after the mask
        multiply's d, e are opened. The coordinator interpolates these
        across all parties to get the revealed value."""
        p = self.prime
        a_y = self.triple_a[-1]
        b_y = self.triple_b[-1]
        c_y = self.triple_c[-1]
        return (opened_d * opened_e + opened_d * b_y + opened_e * a_y + c_y) % p


def build_peer_states(
    shares: list[Share],
    available_indices: list[int],
    threshold: int,
    prime: int = BN254_PRIME,
    _forced_mask: int | None = None,
) -> tuple[dict[int, MembershipPeerState], list[list[MembershipRoundOp]]]:
    """Dealer-side setup: generate triples, split the mask, build one
    ``MembershipPeerState`` per party, and return the round plan.

    In production this runs on the coordinator using pre-generated triples
    (stored alongside the share at signal creation time). For testing we
    generate fresh triples here.

    Returns (peer_states_by_x, rounds_plan).
    """
    if not available_indices:
        raise ValueError("available_indices must be non-empty")

    x_coords = sorted(s.x for s in shares)
    share_map = {s.x: s.y for s in shares}
    k = len(available_indices)

    rounds_plan: list[list[MembershipRoundOp]] = []
    max_power = k
    if max_power >= 2:
        raw_plan = plan_parallel_powers(max_power)
        gate_cursor = 0
        for round_ops in raw_plan:
            typed_ops: list[MembershipRoundOp] = []
            for a_pow, b_pow in round_ops:
                typed_ops.append(
                    MembershipRoundOp(
                        gate_idx=gate_cursor,
                        a_pow=a_pow,
                        b_pow=b_pow,
                    )
                )
                gate_cursor += 1
            rounds_plan.append(typed_ops)

    n_power_gates = sum(len(r) for r in rounds_plan)
    n_triples = n_power_gates + 1

    triples = generate_beaver_triples(
        n_triples,
        n=len(shares),
        k=threshold,
        prime=prime,
        x_coords=x_coords,
    )

    if _forced_mask is not None:
        s = _forced_mask
    else:
        s = secrets.randbelow(prime - 1) + 1
    from djinn_validator.core.mpc import _split_secret_at_points

    mask_shares_list = _split_secret_at_points(s, x_coords, threshold, prime)
    mask_share_map = {sh.x: sh.y for sh in mask_shares_list}

    x_idx = {vx: i for i, vx in enumerate(x_coords)}
    peer_states: dict[int, MembershipPeerState] = {}
    for vx in x_coords:
        triple_a = [triples[g].a_shares[x_idx[vx]].y for g in range(n_triples)]
        triple_b = [triples[g].b_shares[x_idx[vx]].y for g in range(n_triples)]
        triple_c = [triples[g].c_shares[x_idx[vx]].y for g in range(n_triples)]
        state = MembershipPeerState(
            validator_x=vx,
            threshold=threshold,
            available_indices=list(available_indices),
            triple_a=triple_a,
            triple_b=triple_b,
            triple_c=triple_c,
            mask_share=mask_share_map[vx],
            prime=prime,
        )
        state.set_initial_secret_share(share_map[vx])
        peer_states[vx] = state

    return peer_states, rounds_plan


def run_distributed_protocol(
    peer_states: dict[int, MembershipPeerState],
    rounds_plan: list[list[MembershipRoundOp]],
    available_indices: list[int],
    prime: int = BN254_PRIME,
) -> MembershipResult:
    """Drive the distributed protocol across pre-built peer states.

    This function simulates the coordinator running the real wire
    protocol against N peers. Each "round" corresponds to exactly one
    network round in the HTTP variant. Replace the direct ``compute_*``
    calls with HTTP POSTs and this is the real distributed implementation.

    Security invariant: no party ever sees another party's triple shares,
    mask share, or power shares. Each party runs only its own
    ``MembershipPeerState``. The coordinator sees only opened (d, e)
    values — which are uniformly random by the Beaver protocol — plus the
    final opened ``s * p(r)`` (masked as designed).
    """
    x_coords = sorted(peer_states.keys())

    # Power tree rounds
    for round_ops in rounds_plan:
        # Phase A: every party computes its (d_i, e_i) for every op.
        # In the HTTP version, the coordinator POSTs round_ops to each peer
        # and gets back this list.
        per_peer_de: dict[int, list[tuple[int, int, int]]] = {}
        for vx, state in peer_states.items():
            per_peer_de[vx] = state.compute_round(round_ops)

        # Phase B: coordinator reconstructs opened d, e for each op.
        opened_list: list[MembershipOpenedPower] = []
        for op_i, op in enumerate(round_ops):
            d_by_v = {vx: per_peer_de[vx][op_i][1] for vx in x_coords}
            e_by_v = {vx: per_peer_de[vx][op_i][2] for vx in x_coords}
            opened_d = reconstruct_at_zero(d_by_v, prime)
            opened_e = reconstruct_at_zero(e_by_v, prime)
            opened_list.append(
                MembershipOpenedPower(
                    gate_idx=op.gate_idx,
                    target_pow=op.a_pow + op.b_pow,
                    opened_d=opened_d,
                    opened_e=opened_e,
                )
            )

        # Phase C: every party finalizes its share for each resulting power.
        # In HTTP, the coordinator sends opened_list to each peer as part
        # of the NEXT round's request (or a standalone /finalize_round call).
        for state in peer_states.values():
            state.finalize_round(opened_list)

    # Compute q share
    coefficients = polynomial_from_roots(list(available_indices), prime)
    for state in peer_states.values():
        state.compute_q_share(coefficients)

    # Mask multiply round: everyone computes (d, e) shares, coordinator
    # opens. One HTTP round.
    mask_d_shares: dict[int, int] = {}
    mask_e_shares: dict[int, int] = {}
    for vx, state in peer_states.items():
        d_i, e_i = state.compute_mask_multiply_shares()
        mask_d_shares[vx] = d_i
        mask_e_shares[vx] = e_i
    mask_opened_d = reconstruct_at_zero(mask_d_shares, prime)
    mask_opened_e = reconstruct_at_zero(mask_e_shares, prime)

    # Reveal round: everyone computes their share of [s * q], coordinator
    # opens. One HTTP round.
    product_shares: dict[int, int] = {}
    for vx, state in peer_states.items():
        product_shares[vx] = state.compute_product_share(mask_opened_d, mask_opened_e)
    revealed = reconstruct_at_zero(product_shares, prime)

    total_rounds = len(rounds_plan) + 2
    return MembershipResult(
        in_set=(revealed == 0),
        revealed=revealed,
        rounds=total_rounds,
    )


def distributed_check_membership(
    shares: list[Share],
    available_indices: list[int],
    threshold: int,
    prime: int = BN254_PRIME,
    _forced_mask: int | None = None,
) -> MembershipResult:
    """End-to-end distributed protocol simulation.

    Convenience wrapper: dealer setup + distributed execution in one call.
    Produces the same answer as ``local_check_membership`` but exercises
    the per-peer state machine, mirroring what the real HTTP deployment
    will do. Used by integration tests.
    """
    peer_states, rounds_plan = build_peer_states(shares, available_indices, threshold, prime, _forced_mask=_forced_mask)
    return run_distributed_protocol(peer_states, rounds_plan, available_indices, prime)
