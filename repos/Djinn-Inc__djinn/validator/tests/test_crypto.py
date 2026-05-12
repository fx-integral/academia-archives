"""Tests for Shamir Secret Sharing."""

import pytest

from djinn_validator.utils.crypto import (
    BN254_PRIME,
    Share,
    generate_signal_index_shares,
    reconstruct_secret,
    split_secret,
)


class TestSplitAndReconstruct:
    def test_basic_roundtrip(self) -> None:
        secret = 42
        shares = split_secret(secret, n=10, k=7)
        assert len(shares) == 10
        recovered = reconstruct_secret(shares[:7])
        assert recovered == secret

    def test_any_k_shares_work(self) -> None:
        secret = 12345
        shares = split_secret(secret, n=10, k=7)
        # Try different subsets of 7 shares
        for start in range(4):
            subset = shares[start : start + 7]
            assert reconstruct_secret(subset) == secret

    def test_fewer_than_k_shares_fail(self) -> None:
        secret = 99
        shares = split_secret(secret, n=10, k=7)
        # 6 shares should not reconstruct correctly
        result = reconstruct_secret(shares[:6])
        assert result != secret

    def test_all_shares_work(self) -> None:
        secret = 777
        shares = split_secret(secret, n=10, k=7)
        assert reconstruct_secret(shares) == secret

    def test_secret_zero(self) -> None:
        shares = split_secret(0, n=5, k=3)
        assert reconstruct_secret(shares[:3]) == 0

    def test_large_secret(self) -> None:
        secret = BN254_PRIME - 1
        shares = split_secret(secret, n=10, k=7)
        assert reconstruct_secret(shares[:7]) == secret

    def test_secret_exceeds_prime_raises(self) -> None:
        with pytest.raises(ValueError, match="must be <"):
            split_secret(BN254_PRIME, n=5, k=3)

    def test_different_n_k(self) -> None:
        secret = 500
        shares = split_secret(secret, n=5, k=3)
        assert len(shares) == 5
        assert reconstruct_secret(shares[:3]) == secret

    def test_shares_are_unique(self) -> None:
        shares = split_secret(42, n=10, k=7)
        x_values = [s.x for s in shares]
        assert len(set(x_values)) == 10


class TestSignalIndexShares:
    def test_valid_index(self) -> None:
        for idx in range(1, 11):
            shares = generate_signal_index_shares(idx)
            assert len(shares) == 10
            assert reconstruct_secret(shares[:7]) == idx

    def test_index_zero_raises(self) -> None:
        with pytest.raises(ValueError, match="must be in"):
            generate_signal_index_shares(0)

    def test_index_eleven_raises(self) -> None:
        with pytest.raises(ValueError, match="must be in"):
            generate_signal_index_shares(11)
