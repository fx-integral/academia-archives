"""Tests for MPC set-membership protocol."""

import pytest

from djinn_validator.core.mpc import (
    MPCContribution,
    SecureMPCSession,
    _lagrange_coefficient,
    check_availability,
    compute_local_contribution,
    generate_beaver_triples,
    secure_check_availability,
)
from djinn_validator.utils.crypto import BN254_PRIME, Share, generate_signal_index_shares


class TestMPCProtocol:
    def _run_mpc(
        self,
        real_index: int,
        available: set[int],
        n_validators: int = 7,
    ) -> bool:
        """Helper: run full MPC protocol and return availability."""
        shares = generate_signal_index_shares(real_index)
        participating = shares[:n_validators]
        all_xs = [s.x for s in participating]

        contributions = [compute_local_contribution(s, all_xs) for s in participating]
        result = check_availability(contributions, available, threshold=7)
        return result.available

    def test_available_signal(self) -> None:
        """When real index is in available set, MPC reports available."""
        assert self._run_mpc(5, {1, 3, 5, 7, 9}) is True

    def test_unavailable_signal(self) -> None:
        """When real index is NOT in available set, MPC reports unavailable."""
        assert self._run_mpc(5, {1, 2, 3, 4}) is False

    def test_all_indices_available(self) -> None:
        """When all 10 lines are available, any real index should work."""
        available = set(range(1, 11))
        for real_index in range(1, 11):
            assert self._run_mpc(real_index, available) is True

    def test_single_index_available_match(self) -> None:
        """Signal available when only the matching index is in the set."""
        assert self._run_mpc(3, {3}) is True

    def test_single_index_available_no_match(self) -> None:
        """Signal unavailable when only a non-matching index is in the set."""
        assert self._run_mpc(3, {7}) is False

    def test_all_ten_indices(self) -> None:
        """Test each possible real index against various subsets."""
        for real_idx in range(1, 11):
            # Available in even-only set
            evens = {2, 4, 6, 8, 10}
            expected = real_idx in evens
            assert self._run_mpc(real_idx, evens) is expected

    def test_insufficient_validators(self) -> None:
        """MPC fails with fewer than threshold validators."""
        shares = generate_signal_index_shares(3)
        participating = shares[:5]  # Only 5, need 7
        all_xs = [s.x for s in participating]

        contributions = [compute_local_contribution(s, all_xs) for s in participating]
        result = check_availability(contributions, {1, 2, 3}, threshold=7)
        assert result.available is False
        assert result.participating_validators == 5

    def test_exactly_threshold_validators(self) -> None:
        """MPC succeeds with exactly threshold validators."""
        assert self._run_mpc(7, {5, 6, 7, 8}, n_validators=7) is True

    def test_more_than_threshold_validators(self) -> None:
        """MPC succeeds with more than threshold validators."""
        shares = generate_signal_index_shares(4)
        participating = shares[:9]  # 9 of 10
        all_xs = [s.x for s in participating]

        contributions = [compute_local_contribution(s, all_xs) for s in participating]
        result = check_availability(contributions, {1, 4, 7}, threshold=7)
        assert result.available is True


class TestSecureMPC:
    """Tests for the Beaver triple-based secure MPC protocol."""

    def test_secure_available(self) -> None:
        shares = generate_signal_index_shares(5)
        result = secure_check_availability(shares, {1, 3, 5, 7, 9}, threshold=7)
        assert result.available is True
        assert result.participating_validators == 10

    def test_secure_unavailable(self) -> None:
        shares = generate_signal_index_shares(5)
        result = secure_check_availability(shares, {1, 2, 3, 4}, threshold=7)
        assert result.available is False

    def test_secure_empty_available_set(self) -> None:
        shares = generate_signal_index_shares(5)
        result = secure_check_availability(shares, set(), threshold=7)
        assert result.available is False

    def test_secure_single_element_match(self) -> None:
        shares = generate_signal_index_shares(3)
        result = secure_check_availability(shares, {3}, threshold=7)
        assert result.available is True

    def test_secure_insufficient_shares(self) -> None:
        shares = generate_signal_index_shares(5)[:5]
        result = secure_check_availability(shares, {5}, threshold=7)
        assert result.available is False
        assert result.participating_validators == 5

    def test_beaver_triple_exhaustion(self) -> None:
        """Session raises ValueError if more multiplications than triples."""
        shares = generate_signal_index_shares(5)
        x_coords = [s.x for s in shares]
        # Generate only 1 triple, but need 3 (for 3 available indices)
        triples = generate_beaver_triples(1, n=10, k=7, x_coords=x_coords)
        session = SecureMPCSession(
            available_indices={1, 3, 5},
            shares=shares,
            triples=triples,
            threshold=7,
        )
        with pytest.raises(ValueError, match="Not enough Beaver triples"):
            session.run()

    def test_all_ten_indices_secure(self) -> None:
        """Each possible real index against the full set."""
        for real_idx in range(1, 11):
            shares = generate_signal_index_shares(real_idx)
            result = secure_check_availability(
                shares,
                set(range(1, 11)),
                threshold=7,
            )
            assert result.available is True


class TestLagrangeCoefficient:
    """Edge cases for Lagrange coefficient computation."""

    def test_single_point(self) -> None:
        """With a single x-coordinate, L_1(0) = 1."""
        coeff = _lagrange_coefficient(1, [1])
        # L_1(0) for the only point = 1 (the polynomial is constant)
        assert coeff == 1

    def test_two_points(self) -> None:
        """Verify Lagrange coefficients for 2 points."""
        xs = [1, 2]
        c1 = _lagrange_coefficient(1, xs)
        c2 = _lagrange_coefficient(2, xs)
        # L_1(0) = (0 - 2)/(1 - 2) = -2/-1 = 2 mod p
        assert c1 == 2
        # L_2(0) = (0 - 1)/(2 - 1) = -1/1 = p-1
        assert c2 == BN254_PRIME - 1

    def test_reconstruction_correctness(self) -> None:
        """Verify that Lagrange interpolation reconstructs the secret."""
        from djinn_validator.utils.crypto import split_secret

        secret = 42
        shares = split_secret(secret, n=5, k=3)
        xs = [s.x for s in shares[:3]]
        reconstructed = 0
        for s in shares[:3]:
            coeff = _lagrange_coefficient(s.x, xs)
            reconstructed = (reconstructed + coeff * s.y) % BN254_PRIME
        assert reconstructed == secret


class TestSecureMPCEdgeCases:
    """Edge cases for the secure MPC protocol."""

    def test_single_index_available(self) -> None:
        """Single element in available set that matches."""
        shares = generate_signal_index_shares(5)
        result = secure_check_availability(shares, {5}, threshold=7)
        assert result.available is True

    def test_single_index_unavailable(self) -> None:
        """Single element in available set that doesn't match."""
        shares = generate_signal_index_shares(5)
        result = secure_check_availability(shares, {3}, threshold=7)
        assert result.available is False

    def test_boundary_index_1(self) -> None:
        """Real index at lower boundary (1)."""
        shares = generate_signal_index_shares(1)
        result = secure_check_availability(shares, {1, 2, 3}, threshold=7)
        assert result.available is True

    def test_boundary_index_10(self) -> None:
        """Real index at upper boundary (10)."""
        shares = generate_signal_index_shares(10)
        result = secure_check_availability(shares, {8, 9, 10}, threshold=7)
        assert result.available is True

    def test_all_indices_available(self) -> None:
        """All 10 indices available — always succeeds."""
        for idx in range(1, 11):
            shares = generate_signal_index_shares(idx)
            result = secure_check_availability(shares, set(range(1, 11)), threshold=7)
            assert result.available is True, f"Failed for index {idx}"

    def test_participating_validators_count(self) -> None:
        """Result should report correct participant count."""
        shares = generate_signal_index_shares(5)
        result = secure_check_availability(shares, {5}, threshold=7)
        assert result.participating_validators == len(shares)


class TestBeaverTripleBoundsCheck:
    """generate_beaver_triples must reject invalid n/k combinations."""

    def test_k_greater_than_n_raises(self) -> None:
        with pytest.raises(ValueError, match="threshold k=8 exceeds number of shares n=5"):
            generate_beaver_triples(1, n=5, k=8)

    def test_n_zero_raises(self) -> None:
        with pytest.raises(ValueError, match="n and k must be >= 1"):
            generate_beaver_triples(1, n=0, k=0)

    def test_k_zero_raises(self) -> None:
        with pytest.raises(ValueError, match="n and k must be >= 1"):
            generate_beaver_triples(1, n=5, k=0)

    def test_valid_parameters_succeeds(self) -> None:
        triples = generate_beaver_triples(1, n=5, k=3)
        assert len(triples) == 1
        assert len(triples[0].a_shares) == 5
