"""Merkle tree helpers for BPA/WPA vector commitments.

Used by purchase_odds endpoints and the audit MPC to compute and
verify the Merkle roots that purchaseV2() commits on-chain. The
canonical leaf format and tree shape MUST match the contract side
exactly so the off-chain vector and the on-chain root agree.

Leaf format:
    leaf_i = keccak256(abi.encode(uint256 line_index, uint256 price_x1e6))

Tree shape:
    Standard binary Merkle tree
    Sorted-pair hashing: keccak256(min(L, R), max(L, R))
    Sibling padding for odd-count layers: pair the last leaf with itself

This shape is the same one OpenZeppelin's MerkleProof.sol verifies, so
the contract can use the standard library to verify any individual
leaf if a buyer or auditor produces a per-leaf challenge.
"""

from __future__ import annotations

from collections.abc import Iterable

# Lazy import so that this module can be loaded without pulling in the
# full eth_utils dependency at startup. The validator already pulls
# eth_utils for chain interaction so it's available; this guard just
# makes the module import-safe in test environments without it.
try:
    from eth_utils import keccak as _keccak
except ImportError:
    import hashlib as _hashlib

    def _keccak(data: bytes) -> bytes:
        return _hashlib.sha3_256(data).digest()


def _hash_pair(a: bytes, b: bytes) -> bytes:
    """Sorted-pair hash: keccak256(min || max). Matches OpenZeppelin
    MerkleProof.sol's `_hashPair` exactly so the off-chain root agrees
    with on-chain verification."""
    if a < b:
        return _keccak(a + b)
    return _keccak(b + a)


def _encode_leaf(line_index: int, price_x1e6: int) -> bytes:
    """ABI-encode (uint256 line_index, uint256 price_x1e6) and hash.

    Solidity's `abi.encode(uint256, uint256)` produces 64 bytes of
    big-endian zero-padded values. We mirror that exactly.
    """
    if line_index < 0 or line_index >= 2**256:
        raise ValueError(f"line_index out of range: {line_index}")
    if price_x1e6 < 0 or price_x1e6 >= 2**256:
        raise ValueError(f"price_x1e6 out of range: {price_x1e6}")
    encoded = line_index.to_bytes(32, "big") + price_x1e6.to_bytes(32, "big")
    return _keccak(encoded)


def compute_vector_root(prices_x1e6: Iterable[int]) -> bytes:
    """Compute the Merkle root of a price vector.

    Each entry is a uint256-scaled price (e.g., 1.95 → 1_950_000).
    Returns the 32-byte root suitable for on-chain comparison against
    purchaseBpaRoot[purchaseId] / purchaseWpaRoot[purchaseId].

    Empty input returns the keccak256 of an empty string (a sentinel
    distinct from any plausible vector). Single-leaf input returns
    that leaf's hash.
    """
    prices = list(prices_x1e6)
    if not prices:
        return _keccak(b"")

    # Build the leaf layer.
    layer: list[bytes] = [_encode_leaf(i, price) for i, price in enumerate(prices)]
    if len(layer) == 1:
        return layer[0]

    # Build the tree bottom-up. For odd-count layers, pair the last
    # leaf with itself (the standard OpenZeppelin behavior).
    while len(layer) > 1:
        next_layer: list[bytes] = []
        for i in range(0, len(layer), 2):
            left = layer[i]
            right = layer[i + 1] if i + 1 < len(layer) else left
            next_layer.append(_hash_pair(left, right))
        layer = next_layer

    return layer[0]


def compute_proof(prices_x1e6: Iterable[int], leaf_index: int) -> list[bytes]:
    """Compute the Merkle proof (sibling hashes from leaf to root) for
    a given leaf index. Used by the audit MPC when challenging a
    specific leaf via the contract's MerkleProof.verify().
    """
    prices = list(prices_x1e6)
    if leaf_index < 0 or leaf_index >= len(prices):
        raise ValueError(f"leaf_index {leaf_index} out of bounds for vector of {len(prices)}")

    layer: list[bytes] = [_encode_leaf(i, price) for i, price in enumerate(prices)]
    proof: list[bytes] = []
    idx = leaf_index

    while len(layer) > 1:
        sibling_idx = idx ^ 1  # XOR with 1 = pair partner index
        if sibling_idx >= len(layer):
            # Odd layer; we'd be paired with self. Skip the proof step
            # for this level — verification side knows to handle this.
            sibling_idx = idx
        proof.append(layer[sibling_idx])

        # Compute next layer.
        next_layer: list[bytes] = []
        for i in range(0, len(layer), 2):
            left = layer[i]
            right = layer[i + 1] if i + 1 < len(layer) else left
            next_layer.append(_hash_pair(left, right))
        layer = next_layer
        idx //= 2

    return proof


def verify_proof(
    leaf_value_x1e6: int,
    leaf_index: int,
    proof: list[bytes],
    expected_root: bytes,
) -> bool:
    """Verify a Merkle proof against an expected root. Mirrors the
    contract-side MerkleProof.verify() logic exactly."""
    computed = _encode_leaf(leaf_index, leaf_value_x1e6)
    for sibling in proof:
        computed = _hash_pair(computed, sibling)
    return computed == expected_root
