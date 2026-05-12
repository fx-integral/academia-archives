"""Shamir Secret Sharing and related cryptographic primitives."""

from __future__ import annotations

import secrets
from dataclasses import dataclass

# BN254 scalar field prime (same field as our ZK circuits)
BN254_PRIME = 21888242871839275222246405745257275088548364400416034343698204186575808495617


@dataclass(frozen=True)
class Share:
    """A single Shamir share: (x, y) where y = f(x) for secret polynomial f."""

    x: int
    y: int


def _mod_inv(a: int, p: int) -> int:
    """Modular multiplicative inverse using extended Euclidean algorithm."""
    if a < 0:
        a = a % p
    g, x, _ = _extended_gcd(a, p)
    if g != 1:
        raise ValueError("Modular inverse does not exist")
    return x % p


def _extended_gcd(a: int, b: int) -> tuple[int, int, int]:
    if a == 0:
        return b, 0, 1
    g, x, y = _extended_gcd(b % a, a)
    return g, y - (b // a) * x, x


def split_secret(
    secret: int,
    n: int = 10,
    k: int = 7,
    prime: int = BN254_PRIME,
) -> list[Share]:
    """Split a secret integer into n Shamir shares with threshold k.

    Args:
        secret: The secret value to split (must be < prime).
        n: Total number of shares to generate.
        k: Minimum shares needed for reconstruction.
        prime: The prime field modulus.

    Returns:
        List of n Share objects.
    """
    if secret >= prime:
        raise ValueError(f"Secret must be < {prime}")

    # Random polynomial coefficients: a_0 = secret, a_1..a_{k-1} random
    coeffs = [secret] + [secrets.randbelow(prime) for _ in range(k - 1)]

    shares = []
    for i in range(1, n + 1):
        y = 0
        for j, c in enumerate(coeffs):
            y = (y + c * pow(i, j, prime)) % prime
        shares.append(Share(x=i, y=y))

    return shares


def reconstruct_secret(
    shares: list[Share],
    prime: int = BN254_PRIME,
) -> int:
    """Reconstruct the secret from k or more Shamir shares using Lagrange interpolation.

    Args:
        shares: At least k shares from the same polynomial.
        prime: The prime field modulus.

    Returns:
        The original secret value.
    """
    k = len(shares)
    secret = 0

    for i in range(k):
        xi, yi = shares[i].x, shares[i].y
        numerator = 1
        denominator = 1

        for j in range(k):
            if i == j:
                continue
            xj = shares[j].x
            numerator = (numerator * (0 - xj)) % prime
            denominator = (denominator * (xi - xj)) % prime

        lagrange_coeff = (numerator * _mod_inv(denominator, prime)) % prime
        secret = (secret + yi * lagrange_coeff) % prime

    return secret


def generate_signal_index_shares(
    real_index: int,
    n: int = 10,
    k: int = 7,
) -> list[Share]:
    """Generate Shamir shares of a signal's real index.

    Args:
        real_index: The true index (1-10) of the signal among decoys.
        n: Total number of validator shares.
        k: Threshold for reconstruction.

    Returns:
        List of n shares encoding the real index.
    """
    if not 1 <= real_index <= 10:
        raise ValueError(f"Index must be in [1, 10], got {real_index}")
    return split_secret(real_index, n, k)
