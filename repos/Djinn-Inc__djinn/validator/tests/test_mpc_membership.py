"""Unit tests for the masked polynomial set-membership primitive.

These tests cover three concerns:

1. **Correctness** — the revealed bit matches ``r in A`` on random inputs.
2. **Zero leakage beyond 1 bit** — when ``r not in A`` the revealed field
   element is indistinguishable from uniform over ``F*``.
3. **Freshness** — back-to-back calls on identical ``(r, A)`` produce
   different revealed values when ``r not in A`` (otherwise a single leaked
   value would fingerprint the query).

The tests use the local-simulation entry point ``local_check_membership``
in trusted-dealer mode. Distributed HTTP correctness is verified
separately in the integration tests.
"""

from __future__ import annotations

import math
import random
import secrets

import pytest

from djinn_validator.core.mpc_membership import (
    MembershipResult,
    local_check_membership,
    polynomial_from_roots,
)
from djinn_validator.utils.crypto import BN254_PRIME, Share, split_secret

PRIME = BN254_PRIME


def _shares_of(secret: int, n: int = 3, k: int = 2) -> list[Share]:
    return split_secret(secret, n=n, k=k, prime=PRIME)


class TestPolynomialFromRoots:
    def test_empty_polynomial_is_constant_one(self) -> None:
        assert polynomial_from_roots([]) == [1]

    def test_single_root(self) -> None:
        # p(x) = x - 5 → [-5, 1]
        coeffs = polynomial_from_roots([5])
        assert coeffs[1] == 1
        assert coeffs[0] == (-5) % PRIME

    def test_two_roots(self) -> None:
        # p(x) = (x-3)(x-7) = x^2 - 10x + 21
        coeffs = polynomial_from_roots([3, 7])
        assert coeffs == [21, (-10) % PRIME, 1]

    def test_vanishes_at_roots(self) -> None:
        roots = [2, 5, 11, 17, 23]
        coeffs = polynomial_from_roots(roots)
        for r in roots:
            val = 0
            for j, c in enumerate(coeffs):
                val = (val + c * pow(r, j, PRIME)) % PRIME
            assert val == 0

    def test_nonzero_at_non_roots(self) -> None:
        roots = [2, 5, 11, 17, 23]
        coeffs = polynomial_from_roots(roots)
        for x in [1, 3, 4, 6, 10, 100]:
            val = 0
            for j, c in enumerate(coeffs):
                val = (val + c * pow(x, j, PRIME)) % PRIME
            assert val != 0


class TestLocalCorrectness:
    """Every (r, A) pair must produce the right bit."""

    @pytest.mark.parametrize("r", [1, 2, 3, 5, 7, 10])
    def test_r_in_singleton(self, r: int) -> None:
        shares = _shares_of(r)
        result = local_check_membership(shares, [r], threshold=2)
        assert result.in_set is True
        assert result.revealed == 0

    @pytest.mark.parametrize("r,other", [(1, 2), (5, 6), (10, 11)])
    def test_r_not_in_singleton(self, r: int, other: int) -> None:
        shares = _shares_of(r)
        result = local_check_membership(shares, [other], threshold=2)
        assert result.in_set is False
        assert result.revealed != 0

    def test_r_in_medium_set(self) -> None:
        shares = _shares_of(42)
        result = local_check_membership(shares, list(range(30, 60)), threshold=2)
        assert result.in_set is True

    def test_r_just_outside_medium_set(self) -> None:
        shares = _shares_of(29)
        result = local_check_membership(shares, list(range(30, 60)), threshold=2)
        assert result.in_set is False

    def test_r_in_large_set(self) -> None:
        shares = _shares_of(137)
        result = local_check_membership(shares, list(range(1, 201)), threshold=2)
        assert result.in_set is True

    def test_large_index_outside_large_set(self) -> None:
        shares = _shares_of(201)
        result = local_check_membership(shares, list(range(1, 201)), threshold=2)
        assert result.in_set is False

    @pytest.mark.parametrize("lineCount", [10, 25, 50, 100, 200])
    def test_random_trials(self, lineCount: int) -> None:
        rng = random.Random(0x1337 + lineCount)
        for _ in range(20):
            r = rng.randint(1, lineCount)
            k = rng.randint(1, lineCount)
            subset = sorted(rng.sample(range(1, lineCount + 1), k))
            shares = _shares_of(r)
            result = local_check_membership(shares, subset, threshold=2)
            expected = r in set(subset)
            assert result.in_set == expected, (
                f"r={r} subset={subset} " f"expected={expected} got={result.in_set} " f"revealed={result.revealed}"
            )

    def test_multi_party_threshold(self) -> None:
        """Works with more than threshold=2 shares in play."""
        shares = split_secret(75, n=5, k=3, prime=PRIME)
        result = local_check_membership(shares, list(range(70, 90)), threshold=3)
        assert result.in_set is True


class TestLocalRoundCount:
    """Round counts must match the ~log2(k) + 2 promise."""

    @pytest.mark.parametrize(
        "k,expected_rounds_max",
        [
            (1, 2),  # no power tree, just mask + reveal
            (2, 3),  # 1 round power tree + 2
            (4, 4),  # 2 rounds + 2
            (16, 6),  # 4 rounds + 2
            (200, 10),  # ceil(log2(200)) + 2 ≈ 10
        ],
    )
    def test_round_count_bounded(self, k: int, expected_rounds_max: int) -> None:
        shares = _shares_of(1)
        result = local_check_membership(shares, list(range(1, k + 1)), threshold=2)
        assert (
            result.rounds <= expected_rounds_max
        ), f"k={k}: expected ≤{expected_rounds_max} rounds, got {result.rounds}"


class TestLocalLeakage:
    """The masked output must leak nothing beyond 1 bit."""

    def test_membership_always_reveals_zero(self) -> None:
        """When r ∈ A, revealed must be exactly 0 regardless of mask."""
        for trial in range(50):
            r = (trial % 10) + 1
            shares = _shares_of(r)
            result = local_check_membership(shares, [r] + list(range(20, 30)), threshold=2)
            assert result.in_set is True
            assert result.revealed == 0

    def test_non_membership_never_reveals_zero(self) -> None:
        """When r ∉ A, revealed must be nonzero with probability 1 - 1/p."""
        for trial in range(50):
            shares = _shares_of(500 + trial)
            result = local_check_membership(shares, list(range(1, 11)), threshold=2)
            assert result.in_set is False
            assert result.revealed != 0

    def test_fresh_mask_per_call(self) -> None:
        """Back-to-back calls on identical (r, A) must reveal different values
        when r ∉ A. If the same value came back twice, the mask would be
        static and the binary-search attack on the oracle would work on a
        cached result.
        """
        shares = _shares_of(7)
        seen = set()
        trials = 50
        for _ in range(trials):
            result = local_check_membership(shares, [1, 2, 3, 4, 5], threshold=2)
            assert result.in_set is False
            seen.add(result.revealed)
        # With 50 trials over a 254-bit field, collisions are astronomical.
        assert len(seen) == trials, f"mask collided: only {len(seen)} unique values out of {trials}"

    def test_distinct_queries_distinct_masks(self) -> None:
        """Different queries with r ∉ A must reveal unrelated values."""
        revealed_values = []
        for r in range(100, 200):
            shares = _shares_of(r)
            result = local_check_membership(shares, list(range(1, 50)), threshold=2)
            assert result.in_set is False
            revealed_values.append(result.revealed)
        assert len(set(revealed_values)) == len(revealed_values), "different queries produced duplicate revealed values"

    def test_mask_uniform_chi_squared(self) -> None:
        """Chi-squared uniformity test on the revealed value's low bits.

        If the mask multiplication is correct, the revealed value is uniform
        over F* when r ∉ A. We can't test uniformity over 2^254 directly,
        but we can bucket by the low 6 bits and verify a balanced chi-squared
        across many trials.

        A broken mask (constant, r-dependent, etc.) would fail this test
        because its low bits would have a biased distribution.
        """
        trials = 2000
        buckets = 64  # low 6 bits
        counts = [0] * buckets

        for i in range(trials):
            shares = _shares_of(1 + (i % 10))
            result = local_check_membership(shares, list(range(50, 100)), threshold=2)
            assert result.in_set is False
            counts[result.revealed & (buckets - 1)] += 1

        expected = trials / buckets
        chi_sq = sum((c - expected) ** 2 / expected for c in counts)
        # For 63 degrees of freedom, chi-squared critical value at p=0.001
        # is ≈103.44. We give a generous margin to avoid flakes.
        assert chi_sq < 150, f"revealed value low-bits are not uniform: " f"chi_sq={chi_sq:.2f}, counts={counts}"

    def test_forced_mask_smoke(self) -> None:
        """Sanity: when we force a known mask s, revealed = s * p(r)."""
        shares = _shares_of(5)
        result = local_check_membership(shares, [10, 20, 30], threshold=2, _forced_mask=1)
        # With mask=1, revealed should be p(5) = (5-10)(5-20)(5-30)
        expected = ((5 - 10) * (5 - 20) * (5 - 30)) % PRIME
        assert result.revealed == expected
        assert result.in_set is False


class TestLocalInputValidation:
    def test_empty_indices_rejected(self) -> None:
        with pytest.raises(ValueError, match="non-empty"):
            local_check_membership(_shares_of(1), [], threshold=2)

    def test_too_few_shares_rejected(self) -> None:
        shares = _shares_of(1, n=1, k=1)
        with pytest.raises(ValueError, match="at least"):
            local_check_membership(shares, [1, 2, 3], threshold=3)

    def test_compute_q_share_rejects_empty_coefficients(self) -> None:
        """Defense-in-depth: even if a malformed request reaches the state
        machine, compute_q_share must not IndexError on empty coefficients."""
        from djinn_validator.core.mpc_membership import build_peer_states

        shares = _shares_of(5)
        peer_states, _ = build_peer_states(shares, [1, 2, 3], threshold=2)
        state = next(iter(peer_states.values()))
        with pytest.raises(ValueError, match="non-empty"):
            state.compute_q_share([])
