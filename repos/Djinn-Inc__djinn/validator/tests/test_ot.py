"""Tests for OT-based Beaver triple generation.

Verifies:
1. Gilboa multiplication correctness
2. Distributed triple generation (additive shares sum to a*b)
3. Additive-to-Shamir conversion
4. Integration with existing MPC protocol (OT triples work with SecureMPCSession)
5. Edge cases and security properties
"""

import secrets

import pytest

from djinn_validator.core.mpc import (
    BeaverTriple,
    SecureMPCSession,
    generate_beaver_triples,
    generate_ot_beaver_triples,
    secure_check_availability,
)
from djinn_validator.core.ot import (
    AdditiveShare,
    DistributedTriple,
    GilboaShare,
    additive_to_shamir,
    generate_distributed_triple,
    generate_ot_beaver_triples as ot_triples_raw,
    gilboa_multiply,
    verify_distributed_triple,
)
from djinn_validator.utils.crypto import BN254_PRIME, Share, reconstruct_secret

P = BN254_PRIME


# ---------------------------------------------------------------------------
# Gilboa Multiplication
# ---------------------------------------------------------------------------


class TestGilboaMultiply:
    def test_basic_multiplication(self):
        x, y = 42, 17
        result = gilboa_multiply(x, y, sender_id=1, receiver_id=2)
        assert (result.sender_share + result.receiver_share) % P == (x * y) % P

    def test_large_values(self):
        x = secrets.randbelow(P)
        y = secrets.randbelow(P)
        result = gilboa_multiply(x, y, sender_id=1, receiver_id=2)
        assert (result.sender_share + result.receiver_share) % P == (x * y) % P

    def test_zero_inputs(self):
        result = gilboa_multiply(0, 123, sender_id=1, receiver_id=2)
        assert (result.sender_share + result.receiver_share) % P == 0

        result = gilboa_multiply(123, 0, sender_id=1, receiver_id=2)
        assert (result.sender_share + result.receiver_share) % P == 0

    def test_one_input(self):
        x = secrets.randbelow(P)
        result = gilboa_multiply(x, 1, sender_id=1, receiver_id=2)
        assert (result.sender_share + result.receiver_share) % P == x

    def test_shares_are_randomized(self):
        """Each run should produce different shares (same product)."""
        x, y = 100, 200
        r1 = gilboa_multiply(x, y, sender_id=1, receiver_id=2)
        r2 = gilboa_multiply(x, y, sender_id=1, receiver_id=2)
        # Same product
        assert (r1.sender_share + r1.receiver_share) % P == (x * y) % P
        assert (r2.sender_share + r2.receiver_share) % P == (x * y) % P
        # Different shares (with overwhelming probability)
        assert r1.sender_share != r2.sender_share

    def test_sender_receiver_ids_preserved(self):
        result = gilboa_multiply(1, 1, sender_id=5, receiver_id=9)
        assert result.sender_id == 5
        assert result.receiver_id == 9

    @pytest.mark.parametrize("_", range(10))
    def test_random_multiplication(self, _: int):
        x = secrets.randbelow(P)
        y = secrets.randbelow(P)
        result = gilboa_multiply(x, y, sender_id=1, receiver_id=2)
        assert (result.sender_share + result.receiver_share) % P == (x * y) % P


# ---------------------------------------------------------------------------
# Distributed Triple Generation
# ---------------------------------------------------------------------------


class TestDistributedTriple:
    def test_two_party_triple(self):
        triple = generate_distributed_triple([1, 2])
        assert verify_distributed_triple(triple)

    def test_three_party_triple(self):
        triple = generate_distributed_triple([1, 2, 3])
        assert verify_distributed_triple(triple)

    def test_ten_party_triple(self):
        triple = generate_distributed_triple(list(range(1, 11)))
        assert verify_distributed_triple(triple)

    def test_correct_party_count(self):
        ids = [3, 7, 11, 15]
        triple = generate_distributed_triple(ids)
        assert len(triple.a_shares) == 4
        assert len(triple.b_shares) == 4
        assert len(triple.c_shares) == 4
        assert {s.party_id for s in triple.a_shares} == set(ids)

    def test_single_party_raises(self):
        with pytest.raises(ValueError, match="at least 2"):
            generate_distributed_triple([1])

    def test_additive_shares_are_random(self):
        """No single party's shares should reveal the secret."""
        t1 = generate_distributed_triple([1, 2, 3])
        t2 = generate_distributed_triple([1, 2, 3])
        # Both should verify
        assert verify_distributed_triple(t1)
        assert verify_distributed_triple(t2)
        # Party 1's a-share should differ between runs
        a1_t1 = next(s.value for s in t1.a_shares if s.party_id == 1)
        a1_t2 = next(s.value for s in t2.a_shares if s.party_id == 1)
        assert a1_t1 != a1_t2  # overwhelmingly likely

    @pytest.mark.parametrize("n_parties", [2, 3, 5, 7, 10])
    def test_various_party_counts(self, n_parties: int):
        ids = list(range(1, n_parties + 1))
        triple = generate_distributed_triple(ids)
        assert verify_distributed_triple(triple)


# ---------------------------------------------------------------------------
# Additive-to-Shamir Conversion
# ---------------------------------------------------------------------------


class TestAdditiveToShamir:
    def test_basic_conversion(self):
        """Additive shares convert to valid Shamir shares of the same secret."""
        secret = 12345
        shares_additive = [
            AdditiveShare(1, secret - 9999),
            AdditiveShare(2, 9999),
        ]
        x_coords = [1, 2, 3, 4, 5]
        shamir = additive_to_shamir(tuple(shares_additive), x_coords, threshold=3)

        reconstructed = reconstruct_secret(shamir[:3])
        assert reconstructed == secret % P

    def test_random_secret(self):
        secret = secrets.randbelow(P)
        # Split into 3 additive shares
        s1 = secrets.randbelow(P)
        s2 = secrets.randbelow(P)
        s3 = (secret - s1 - s2) % P
        additive = (
            AdditiveShare(1, s1),
            AdditiveShare(2, s2),
            AdditiveShare(3, s3),
        )
        x_coords = [1, 2, 3, 4, 5, 6, 7]
        shamir = additive_to_shamir(additive, x_coords, threshold=4)
        reconstructed = reconstruct_secret(shamir[:4])
        assert reconstructed == secret

    def test_threshold_respected(self):
        """k-1 shares should NOT reconstruct correctly (with high probability)."""
        secret = 42
        additive = (AdditiveShare(1, 20), AdditiveShare(2, 22))
        x_coords = [1, 2, 3, 4, 5]
        shamir = additive_to_shamir(additive, x_coords, threshold=3)

        # 3 shares should work
        correct = reconstruct_secret(shamir[:3])
        assert correct == secret

        # 2 shares should NOT give the correct answer (with overwhelming probability)
        wrong = reconstruct_secret(shamir[:2])
        assert wrong != secret


# ---------------------------------------------------------------------------
# OT-Based Beaver Triples (Integration with MPC)
# ---------------------------------------------------------------------------


class TestOTBeaverTriples:
    def test_generates_correct_count(self):
        triples = generate_ot_beaver_triples(
            count=5,
            n=3,
            k=2,
            x_coords=[1, 2, 3],
            party_ids=[1, 2, 3],
        )
        assert len(triples) == 5

    def test_triple_structure(self):
        triples = generate_ot_beaver_triples(
            count=1,
            n=3,
            k=2,
            x_coords=[1, 2, 3],
        )
        triple = triples[0]
        assert isinstance(triple, BeaverTriple)
        assert len(triple.a_shares) == 3
        assert len(triple.b_shares) == 3
        assert len(triple.c_shares) == 3

    def test_triple_verifies(self):
        """a * b = c when reconstructed from Shamir shares."""
        triples = generate_ot_beaver_triples(
            count=1,
            n=5,
            k=3,
            x_coords=[1, 2, 3, 4, 5],
        )
        triple = triples[0]
        a = reconstruct_secret(list(triple.a_shares)[:3])
        b = reconstruct_secret(list(triple.b_shares)[:3])
        c = reconstruct_secret(list(triple.c_shares)[:3])
        assert c == (a * b) % P

    @pytest.mark.parametrize("_", range(5))
    def test_multiple_triples_verify(self, _: int):
        triples = generate_ot_beaver_triples(
            count=3,
            n=4,
            k=3,
            x_coords=[1, 2, 3, 4],
        )
        for triple in triples:
            a = reconstruct_secret(list(triple.a_shares)[:3])
            b = reconstruct_secret(list(triple.b_shares)[:3])
            c = reconstruct_secret(list(triple.c_shares)[:3])
            assert c == (a * b) % P

    def test_ot_triples_work_with_secure_mpc(self):
        """OT-generated triples produce correct MPC results."""
        from djinn_validator.utils.crypto import split_secret

        real_index = 5
        shares = split_secret(real_index, n=7, k=5)
        x_coords = [s.x for s in shares]

        # Available set that contains the real index
        available = {3, 5, 7}
        n_mults = len(available)

        triples = generate_ot_beaver_triples(
            count=n_mults,
            n=7,
            k=5,
            x_coords=x_coords,
        )

        session = SecureMPCSession(
            available_indices=available,
            shares=shares,
            triples=triples,
            threshold=5,
        )
        result = session.run()
        assert result.available is True

    def test_ot_triples_work_with_unavailable(self):
        """OT triples correctly detect when secret is NOT in available set."""
        from djinn_validator.utils.crypto import split_secret

        real_index = 5
        shares = split_secret(real_index, n=7, k=5)
        x_coords = [s.x for s in shares]

        available = {1, 2, 3}  # Does NOT contain 5
        n_mults = len(available)

        triples = generate_ot_beaver_triples(
            count=n_mults,
            n=7,
            k=5,
            x_coords=x_coords,
        )

        session = SecureMPCSession(
            available_indices=available,
            shares=shares,
            triples=triples,
            threshold=5,
        )
        result = session.run()
        assert result.available is False

    def test_ot_matches_trusted_dealer(self):
        """OT and trusted dealer produce equivalent MPC results for all 10 indices."""
        from djinn_validator.utils.crypto import split_secret

        for real_index in range(1, 11):
            shares = split_secret(real_index, n=7, k=5)
            x_coords = [s.x for s in shares]
            available = {2, 5, 8}

            # Trusted dealer
            td_triples = generate_beaver_triples(
                count=len(available),
                n=7,
                k=5,
                x_coords=x_coords,
            )
            td_session = SecureMPCSession(
                available_indices=available,
                shares=shares,
                triples=td_triples,
                threshold=5,
            )
            td_result = td_session.run()

            # OT-based
            ot_triples = generate_ot_beaver_triples(
                count=len(available),
                n=7,
                k=5,
                x_coords=x_coords,
            )
            ot_session = SecureMPCSession(
                available_indices=available,
                shares=shares,
                triples=ot_triples,
                threshold=5,
            )
            ot_result = ot_session.run()

            assert td_result.available == ot_result.available, (
                f"Mismatch at index {real_index}: " f"trusted_dealer={td_result.available}, ot={ot_result.available}"
            )


# ---------------------------------------------------------------------------
# Edge Cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_minimum_parties(self):
        """Two parties is the minimum for OT."""
        triple = generate_distributed_triple([1, 2])
        assert verify_distributed_triple(triple)

    def test_non_sequential_party_ids(self):
        triple = generate_distributed_triple([3, 7, 15, 42])
        assert verify_distributed_triple(triple)

    def test_large_party_ids(self):
        triple = generate_distributed_triple([100, 200, 255])
        assert verify_distributed_triple(triple)

    def test_ot_triples_with_custom_x_coords(self):
        triples = generate_ot_beaver_triples(
            count=2,
            n=4,
            k=3,
            x_coords=[2, 5, 8, 11],
            party_ids=[2, 5, 8, 11],
        )
        for triple in triples:
            assert all(s.x in {2, 5, 8, 11} for s in triple.a_shares)
            a = reconstruct_secret(list(triple.a_shares)[:3])
            b = reconstruct_secret(list(triple.b_shares)[:3])
            c = reconstruct_secret(list(triple.c_shares)[:3])
            assert c == (a * b) % P

    def test_threshold_validation(self):
        with pytest.raises(ValueError):
            generate_ot_beaver_triples(count=1, n=2, k=5, x_coords=[1, 2])

    def test_single_party_ot_raises(self):
        with pytest.raises(ValueError, match="at least 2"):
            generate_ot_beaver_triples(count=1, n=1, k=1, x_coords=[1])
