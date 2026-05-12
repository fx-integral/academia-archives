"""Integration tests for the per-peer state-machine variant of the
masked polynomial membership primitive.

These tests exercise ``distributed_check_membership``, which drives the
full protocol through ``MembershipPeerState`` instances — one per
validator — without ever touching a peer's private data from the
coordinator. This is the exact same code path that the HTTP wire
implementation will run, minus the HTTP layer.

If these tests pass, the distributed state machine is correct. The HTTP
variant is then a straightforward serialization layer on top.
"""

from __future__ import annotations

import random

import pytest

from djinn_validator.core.mpc_membership import (
    MembershipPeerState,
    MembershipRoundOp,
    build_peer_states,
    distributed_check_membership,
    local_check_membership,
    polynomial_from_roots,
    run_distributed_protocol,
)
from djinn_validator.utils.crypto import BN254_PRIME, Share, split_secret

PRIME = BN254_PRIME


def _shares_of(secret: int, n: int = 3, k: int = 2) -> list[Share]:
    return split_secret(secret, n=n, k=k, prime=PRIME)


class TestDistributedCorrectness:
    """The distributed state machine must agree with the reference."""

    @pytest.mark.parametrize(
        "r,indices,expected",
        [
            (1, [1], True),
            (1, [2], False),
            (5, [1, 2, 3, 4, 5], True),
            (6, [1, 2, 3, 4, 5], False),
            (42, list(range(30, 60)), True),
            (29, list(range(30, 60)), False),
            (100, list(range(1, 201)), True),
            (201, list(range(1, 201)), False),
        ],
    )
    def test_simple_cases(
        self,
        r: int,
        indices: list[int],
        expected: bool,
    ) -> None:
        shares = _shares_of(r)
        result = distributed_check_membership(shares, indices, threshold=2)
        assert result.in_set == expected
        if expected:
            assert result.revealed == 0
        else:
            assert result.revealed != 0

    def test_matches_local_reference_on_many_trials(self) -> None:
        """Forced-mask convergence: for the same mask, distributed and
        local must produce bit-identical revealed values."""
        rng = random.Random(0xCAFE)
        for _ in range(100):
            k = rng.randint(1, 50)
            line_count = rng.randint(k, 100)
            r = rng.randint(1, line_count)
            subset = sorted(rng.sample(range(1, line_count + 1), k))
            forced = rng.randrange(1, PRIME - 1)

            shares = _shares_of(r)
            local_result = local_check_membership(
                shares,
                subset,
                threshold=2,
                _forced_mask=forced,
            )
            dist_result = distributed_check_membership(
                shares,
                subset,
                threshold=2,
                _forced_mask=forced,
            )
            assert local_result.in_set == dist_result.in_set, f"disagree on r={r} subset={subset}"
            assert local_result.revealed == dist_result.revealed, (
                f"different revealed values: "
                f"local={local_result.revealed} dist={dist_result.revealed} "
                f"r={r} subset={subset}"
            )

    @pytest.mark.parametrize("k", [1, 5, 10, 50, 100, 200])
    def test_many_random_trials_per_size(self, k: int) -> None:
        """Randomized correctness over varying set sizes."""
        rng = random.Random(0xBEEF + k)
        for _ in range(20):
            line_count = max(k, rng.randint(k, k * 2))
            r = rng.randint(1, line_count)
            subset = sorted(rng.sample(range(1, line_count + 1), k))
            shares = _shares_of(r)
            result = distributed_check_membership(shares, subset, threshold=2)
            expected = r in set(subset)
            assert result.in_set == expected, f"r={r} subset={subset} expected={expected} got={result.in_set}"

    def test_three_party_threshold(self) -> None:
        shares = split_secret(77, n=5, k=3, prime=PRIME)
        result = distributed_check_membership(shares, list(range(70, 90)), threshold=3)
        assert result.in_set is True

    def test_seven_party_threshold(self) -> None:
        """Production mainnet setup."""
        shares = split_secret(137, n=10, k=7, prime=PRIME)
        result = distributed_check_membership(shares, list(range(100, 200)), threshold=7)
        assert result.in_set is True


class TestDistributedIsolation:
    """Verify that per-peer states never share private data.

    These tests inspect the MembershipPeerState objects directly and
    ensure each one holds only what a single validator would possess.
    The security claim rests on each party's state being disjoint from
    the others.
    """

    def test_peer_states_have_disjoint_triple_shares(self) -> None:
        shares = _shares_of(5)
        peer_states, _ = build_peer_states(shares, [1, 2, 3, 4, 5, 6, 7, 8], threshold=2)
        # Collect all a-share values across peers and verify they differ
        # (which they must because each is a distinct polynomial eval point).
        a_values_per_peer = [tuple(state.triple_a) for state in peer_states.values()]
        # All peers must have different triple-a tuples.
        assert len(set(a_values_per_peer)) == len(a_values_per_peer)

    def test_peer_mask_shares_differ(self) -> None:
        shares = _shares_of(5)
        peer_states, _ = build_peer_states(shares, [1, 2, 3], threshold=2)
        mask_values = {s.mask_share for s in peer_states.values()}
        assert len(mask_values) == len(peer_states)  # all distinct

    def test_peer_initial_power_share_is_own_secret_share(self) -> None:
        shares = _shares_of(7)
        peer_states, _ = build_peer_states(shares, [1, 2, 3], threshold=2)
        share_map = {s.x: s.y for s in shares}
        for vx, state in peer_states.items():
            assert state.power_shares[1] == share_map[vx]

    def test_compute_round_rejects_missing_power(self) -> None:
        shares = _shares_of(5)
        peer_states, _ = build_peer_states(shares, [1, 2, 3], threshold=2)
        state = next(iter(peer_states.values()))
        bad_op = MembershipRoundOp(gate_idx=0, a_pow=1, b_pow=99)
        with pytest.raises(ValueError, match="missing power share"):
            state.compute_round([bad_op])

    def test_compute_q_share_requires_all_powers(self) -> None:
        shares = _shares_of(5)
        peer_states, _ = build_peer_states(shares, [1, 2, 3, 4, 5], threshold=2)
        # Drop a power deliberately.
        state = next(iter(peer_states.values()))
        state.power_shares.pop(3, None)
        with pytest.raises(ValueError, match="missing power share"):
            state.compute_q_share([0, 0, 0, 1, 0, 0])

    def test_compute_mask_multiply_requires_q_share(self) -> None:
        shares = _shares_of(5)
        peer_states, _ = build_peer_states(shares, [1, 2, 3], threshold=2)
        state = next(iter(peer_states.values()))
        with pytest.raises(ValueError, match="compute_q_share"):
            state.compute_mask_multiply_shares()


class TestDistributedLeakage:
    """The revealed values must leak exactly 1 bit even via the
    distributed path."""

    def test_membership_reveals_zero(self) -> None:
        for trial in range(30):
            r = (trial % 10) + 1
            shares = _shares_of(r)
            result = distributed_check_membership(shares, [r, r + 100, r + 200], threshold=2)
            assert result.in_set is True
            assert result.revealed == 0

    def test_non_membership_reveals_nonzero(self) -> None:
        for trial in range(30):
            shares = _shares_of(1000 + trial)
            result = distributed_check_membership(shares, list(range(1, 10)), threshold=2)
            assert result.in_set is False
            assert result.revealed != 0

    def test_fresh_mask_per_call(self) -> None:
        shares = _shares_of(42)
        seen = set()
        trials = 50
        for _ in range(trials):
            result = distributed_check_membership(shares, [1, 2, 3, 4, 5], threshold=2)
            assert result.in_set is False
            seen.add(result.revealed)
        assert len(seen) == trials

    def test_chi_squared_uniform_low_bits(self) -> None:
        trials = 1000
        buckets = 32
        counts = [0] * buckets
        for i in range(trials):
            shares = _shares_of(1 + (i % 10))
            result = distributed_check_membership(shares, list(range(50, 100)), threshold=2)
            assert result.in_set is False
            counts[result.revealed & (buckets - 1)] += 1
        expected = trials / buckets
        chi_sq = sum((c - expected) ** 2 / expected for c in counts)
        # Critical value for 31 dof at p=0.001 is ~61.1. Loose bound for stability.
        assert chi_sq < 90, f"chi_sq={chi_sq:.2f}, counts={counts}"


class TestDistributedRoundCount:
    """Round counts must match the ceil(log2(k)) + 2 promise."""

    @pytest.mark.parametrize(
        "k,max_rounds",
        [
            (1, 2),
            (2, 3),
            (4, 4),
            (16, 6),
            (100, 9),
            (200, 10),
        ],
    )
    def test_rounds_bounded(self, k: int, max_rounds: int) -> None:
        shares = _shares_of(1)
        result = distributed_check_membership(shares, list(range(1, k + 1)), threshold=2)
        assert result.rounds <= max_rounds

    def test_round_plan_mentions_each_gate_once(self) -> None:
        shares = _shares_of(1)
        _, plan = build_peer_states(shares, list(range(1, 51)), threshold=2)
        seen_gates: set[int] = set()
        for round_ops in plan:
            for op in round_ops:
                assert op.gate_idx not in seen_gates
                seen_gates.add(op.gate_idx)
        # Gate indices should be contiguous from 0
        assert seen_gates == set(range(len(seen_gates)))
