"""Tests for the BPA/WPA Merkle root computation.

The on-chain contract (Escrow.purchaseV2) commits Merkle roots over
the per-line BPA and WPA vectors. The validator computes the same
roots from its locally-stored vectors at settlement time. Both sides
MUST agree on the leaf format and tree shape exactly, otherwise the
audit MPC will reject the validator's vectors.
"""

from __future__ import annotations

import pytest

from djinn_validator.utils.merkle import (
    compute_proof,
    compute_vector_root,
    verify_proof,
    _encode_leaf,
    _hash_pair,
    _keccak,
)


def test_empty_vector_returns_sentinel():
    root = compute_vector_root([])
    assert len(root) == 32
    assert root == _keccak(b"")


def test_single_leaf_returns_leaf_hash():
    root = compute_vector_root([1_950_000])
    assert root == _encode_leaf(0, 1_950_000)


def test_two_leaves_returns_pair_hash():
    leaves = [1_950_000, 1_850_000]
    root = compute_vector_root(leaves)
    leaf0 = _encode_leaf(0, 1_950_000)
    leaf1 = _encode_leaf(1, 1_850_000)
    expected = _hash_pair(leaf0, leaf1)
    assert root == expected


def test_three_leaves_pads_odd_layer():
    """Odd-count layers pair the last leaf with itself."""
    leaves = [1_910_000, 2_000_000, 1_850_000]
    root = compute_vector_root(leaves)
    leaf0 = _encode_leaf(0, 1_910_000)
    leaf1 = _encode_leaf(1, 2_000_000)
    leaf2 = _encode_leaf(2, 1_850_000)
    pair01 = _hash_pair(leaf0, leaf1)
    pair22 = _hash_pair(leaf2, leaf2)  # padded with self
    expected = _hash_pair(pair01, pair22)
    assert root == expected


def test_root_is_deterministic():
    leaves = [1_950_000, 1_850_000, 2_000_000, 1_910_000, 1_870_000]
    root1 = compute_vector_root(leaves)
    root2 = compute_vector_root(leaves)
    assert root1 == root2


def test_root_changes_when_leaf_value_changes():
    base = [1_950_000, 1_850_000, 2_000_000, 1_910_000]
    root_a = compute_vector_root(base)
    modified = base.copy()
    modified[2] = 2_000_001
    root_b = compute_vector_root(modified)
    assert root_a != root_b


def test_root_changes_when_leaf_order_changes():
    """Each leaf encodes its index, so reordering changes the root."""
    a = [1_950_000, 1_850_000, 2_000_000]
    b = [1_850_000, 1_950_000, 2_000_000]
    assert compute_vector_root(a) != compute_vector_root(b)


def test_root_for_realistic_signal_size():
    """200-line signal with mixed prices. Just verify it computes
    deterministically and produces a 32-byte root."""
    prices = [1_500_000 + (i * 7) % 500_000 for i in range(200)]
    root = compute_vector_root(prices)
    assert len(root) == 32
    # Recomputing produces the same root
    assert compute_vector_root(prices) == root


def test_proof_verifies_for_each_leaf():
    """Generate a proof for each leaf and verify it against the root."""
    prices = [1_500_000, 1_750_000, 1_950_000, 2_100_000, 1_850_000, 2_000_000]
    root = compute_vector_root(prices)
    for i, price in enumerate(prices):
        proof = compute_proof(prices, i)
        assert verify_proof(price, i, proof, root), f"proof failed for leaf {i}"


def test_proof_fails_for_wrong_value():
    prices = [1_500_000, 1_750_000, 1_950_000, 2_100_000]
    root = compute_vector_root(prices)
    proof = compute_proof(prices, 2)
    # Original value verifies
    assert verify_proof(1_950_000, 2, proof, root)
    # Tampered value does NOT verify
    assert not verify_proof(1_950_001, 2, proof, root)


def test_proof_fails_for_wrong_index():
    prices = [1_500_000, 1_750_000, 1_950_000, 2_100_000]
    root = compute_vector_root(prices)
    proof = compute_proof(prices, 2)
    # Right value, wrong index — does not verify
    assert not verify_proof(1_950_000, 1, proof, root)


def test_encode_leaf_rejects_negative():
    with pytest.raises(ValueError):
        _encode_leaf(-1, 100)
    with pytest.raises(ValueError):
        _encode_leaf(0, -100)


def test_encode_leaf_rejects_huge_values():
    with pytest.raises(ValueError):
        _encode_leaf(2**256, 100)
    with pytest.raises(ValueError):
        _encode_leaf(0, 2**256)


def test_compute_proof_rejects_out_of_bounds():
    prices = [1, 2, 3]
    with pytest.raises(ValueError):
        compute_proof(prices, 3)
    with pytest.raises(ValueError):
        compute_proof(prices, -1)
