"""Generate golden test vectors for v1747 LineOutcomeRegistry.

Bytes-identical with Solidity. If Python and Solidity disagree, the schema
is broken. These vectors are the cross-check.

Run:
    python3 scripts/v1747_golden_vectors.py

Output: prints a JSON document with vectors. Foundry tests load the same
JSON and verify byte-for-byte equivalence (see contracts/test/LineOutcomeRegistry.t.sol).
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass

from Crypto.Hash import keccak
from eth_account import Account
from eth_account.messages import encode_typed_data


# ---------------------------------------------------------------------------
# Canonical line schema (matches docs/v1747-line-schema.md)
# ---------------------------------------------------------------------------

DOMAIN_TAG = b"DJINN_LINE_V1"
RULESET_TAG = b"DJINN_OUTCOMES_V1"
EIP712_DOMAIN_NAME = "DjinnLineOutcomeRegistry"
EIP712_DOMAIN_VERSION = "1"

# Outcome enum (matches Solidity Outcome { Pending, Favorable, Unfavorable, Void })
PENDING = 0
FAVORABLE = 1
UNFAVORABLE = 2
VOID = 3


@dataclass(frozen=True)
class LineKey:
    sport: str
    event_id: str
    market: str       # "spread" | "total" | "moneyline"
    side: str         # "home"|"away" or "over"|"under"
    line_value: str   # canonical decimal one decimal place, "" for moneyline

    def canonical_string(self) -> str:
        # ASCII only, lowercase, exact 6-pipe format with trailing pipe always present.
        # Note the 6th field is line_value, which is empty for moneyline so the
        # canonical string ends with a trailing pipe.
        return (
            f"DJINN_LINE_V1|{self.sport}|{self.event_id}|"
            f"{self.market}|{self.side}|{self.line_value}"
        )


def keccak256(data: bytes) -> bytes:
    h = keccak.new(digest_bits=256)
    h.update(data)
    return h.digest()


def line_hash(key: LineKey, chain_id: int, registry_address: str) -> bytes:
    """Computes the lineHash matching Solidity:

        keccak256(abi.encodePacked(
            "DJINN_LINE_V1",            // 13 bytes literal
            block.chainid,              // 32 bytes uint256 big-endian
            address(LineOutcomeRegistry), // 20 bytes
            canonical_line_string       // variable bytes UTF-8
        ))

    abi.encodePacked rules:
      - string literal: raw UTF-8 bytes, no length prefix
      - uint256: 32 bytes big-endian
      - address: 20 bytes (no left-pad to 32)
      - string: raw UTF-8 bytes, no length prefix
    """
    canonical = key.canonical_string().encode("ascii")
    addr_bytes = bytes.fromhex(registry_address.lower().removeprefix("0x"))
    if len(addr_bytes) != 20:
        raise ValueError(f"address must be 20 bytes, got {len(addr_bytes)}")
    preimage = (
        DOMAIN_TAG
        + chain_id.to_bytes(32, "big")
        + addr_bytes
        + canonical
    )
    return keccak256(preimage)


def outcome_ruleset_hash() -> bytes:
    """OUTCOME_RULESET_HASH = keccak256("DJINN_OUTCOMES_V1") matching the contract."""
    return keccak256(RULESET_TAG)


def eip712_domain_separator(chain_id: int, registry_address: str) -> bytes:
    """EIP-712 domain separator matching OZ EIP712Upgradeable with NAME and VERSION."""
    type_hash = keccak256(
        b"EIP712Domain(string name,string version,uint256 chainId,address verifyingContract)"
    )
    name_hash = keccak256(EIP712_DOMAIN_NAME.encode("utf-8"))
    version_hash = keccak256(EIP712_DOMAIN_VERSION.encode("utf-8"))
    addr_bytes = bytes.fromhex(registry_address.lower().removeprefix("0x"))
    encoded = (
        type_hash
        + name_hash
        + version_hash
        + chain_id.to_bytes(32, "big")
        + b"\x00" * 12
        + addr_bytes
    )
    return keccak256(encoded)


def attest_struct_hash(line_hash_bytes: bytes, outcome: int, ruleset_hash: bytes) -> bytes:
    """structHash = keccak(abi.encode(ATTEST_TYPEHASH, lineHash, outcome, rulesetHash))

    abi.encode rules (vs encodePacked):
      - bytes32: 32 bytes verbatim
      - uint8: 32 bytes (left-padded with zeros)
      - bytes32: 32 bytes verbatim
    """
    type_hash = keccak256(
        b"LineAttestation(bytes32 lineHash,uint8 outcome,bytes32 rulesetHash)"
    )
    encoded = (
        type_hash
        + line_hash_bytes
        + outcome.to_bytes(32, "big")
        + ruleset_hash
    )
    return keccak256(encoded)


def eip712_digest(line_hash_bytes: bytes, outcome: int, chain_id: int, registry_address: str) -> bytes:
    """Final digest passed to ECDSA.recover on chain.

        digest = keccak("\x19\x01" || domainSeparator || structHash)
    """
    domain_sep = eip712_domain_separator(chain_id, registry_address)
    struct_hash = attest_struct_hash(line_hash_bytes, outcome, outcome_ruleset_hash())
    return keccak256(b"\x19\x01" + domain_sep + struct_hash)


def sign_attestation(
    privkey_hex: str,
    line_hash_bytes: bytes,
    outcome: int,
    chain_id: int,
    registry_address: str,
) -> tuple[bytes, str]:
    """Sign the EIP-712 digest. Returns (signature_bytes, signer_address)."""
    digest = eip712_digest(line_hash_bytes, outcome, chain_id, registry_address)
    acct = Account.from_key(privkey_hex)
    signed = acct.unsafe_sign_hash(digest)
    return signed.signature, acct.address


# ---------------------------------------------------------------------------
# Test vectors
# ---------------------------------------------------------------------------

# Pinned test environment (Base Sepolia chain id, fake registry address).
TEST_CHAIN_ID = 84532
TEST_REGISTRY_ADDRESS = "0x000000000000000000000000000000000000C0DE"

# Stable private keys for golden signers (DO NOT USE IN PRODUCTION).
# These are deterministic so vectors are reproducible.
TEST_SIGNER_KEYS = [
    "0x0000000000000000000000000000000000000000000000000000000000000a01",
    "0x0000000000000000000000000000000000000000000000000000000000000a02",
    "0x0000000000000000000000000000000000000000000000000000000000000a03",
    "0x0000000000000000000000000000000000000000000000000000000000000a04",
    "0x0000000000000000000000000000000000000000000000000000000000000a05",
]


def make_vectors() -> list[dict]:
    """All vectors must round-trip Solidity → Python and back."""
    cases = [
        # NBA spread, home favorite
        ("nba_spread_home_fav", LineKey("basketball_nba", "401584293", "spread", "home", "-3.5"), FAVORABLE),
        # NBA spread, away dog
        ("nba_spread_away_dog", LineKey("basketball_nba", "401584293", "spread", "away", "+3.5"), UNFAVORABLE),
        # NBA total over
        ("nba_total_over", LineKey("basketball_nba", "401584293", "total", "over", "220.5"), FAVORABLE),
        # NBA moneyline (empty line_value, trailing pipe)
        ("nba_ml_home", LineKey("basketball_nba", "401584293", "moneyline", "home", ""), FAVORABLE),
        # NFL spread
        ("nfl_spread_home_dog", LineKey("americanfootball_nfl", "401547652", "spread", "home", "+7.5"), FAVORABLE),
        # MLB total under
        ("mlb_total_under", LineKey("baseball_mlb", "401472088", "total", "under", "8.5"), UNFAVORABLE),
        # NHL moneyline away
        ("nhl_ml_away", LineKey("icehockey_nhl", "401622193", "moneyline", "away", ""), UNFAVORABLE),
        # Soccer EPL spread
        ("epl_spread_home", LineKey("soccer_epl", "654712", "spread", "home", "-1.5"), FAVORABLE),
        # NCAAB total
        ("ncaab_total_over", LineKey("basketball_ncaab", "401709312", "total", "over", "143.5"), FAVORABLE),
        # NCAAF moneyline (Void outcome — push or cancelled)
        ("ncaaf_ml_void", LineKey("americanfootball_ncaaf", "401628812", "moneyline", "home", ""), VOID),
        # MLS spread, integer push value (rare)
        ("mls_spread_integer", LineKey("soccer_usa_mls", "722104", "spread", "away", "+0.0"), VOID),
        # NBA total integer (push)
        ("nba_total_integer_push", LineKey("basketball_nba", "401584294", "total", "over", "215.0"), VOID),
    ]

    vectors = []
    for name, key, outcome in cases:
        line_h = line_hash(key, TEST_CHAIN_ID, TEST_REGISTRY_ADDRESS)
        digest = eip712_digest(line_h, outcome, TEST_CHAIN_ID, TEST_REGISTRY_ADDRESS)
        # Sign with the first test key for each vector — deterministic.
        sig, signer = sign_attestation(
            TEST_SIGNER_KEYS[0], line_h, outcome, TEST_CHAIN_ID, TEST_REGISTRY_ADDRESS
        )
        vectors.append({
            "name": name,
            "sport": key.sport,
            "event_id": key.event_id,
            "market": key.market,
            "side": key.side,
            "line_value": key.line_value,
            "canonical_string": key.canonical_string(),
            "outcome": outcome,
            "line_hash": "0x" + line_h.hex(),
            "digest": "0x" + digest.hex(),
            "signer": signer,
            "signature": "0x" + sig.hex(),
        })
    return vectors


def env_constants() -> dict:
    return {
        "chain_id": TEST_CHAIN_ID,
        "registry_address": TEST_REGISTRY_ADDRESS,
        "domain_name": EIP712_DOMAIN_NAME,
        "domain_version": EIP712_DOMAIN_VERSION,
        "outcome_ruleset_hash": "0x" + outcome_ruleset_hash().hex(),
        "domain_separator": "0x" + eip712_domain_separator(TEST_CHAIN_ID, TEST_REGISTRY_ADDRESS).hex(),
        "test_signer_keys": TEST_SIGNER_KEYS,
        "test_signer_addresses": [Account.from_key(k).address for k in TEST_SIGNER_KEYS],
    }


def main() -> int:
    out = {
        "env": env_constants(),
        "vectors": make_vectors(),
    }
    json.dump(out, sys.stdout, indent=2)
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
