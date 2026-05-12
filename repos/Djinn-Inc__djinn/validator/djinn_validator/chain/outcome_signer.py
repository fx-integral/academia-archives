"""EIP-712 signer for v1747 LineOutcomeRegistry attestations.

The validator's OV signer EOA (the same key registered in OutcomeVoting.isValidator
and used for submitVote) signs line outcome attestations. The signature is verifiable
on chain via ECDSA.recover; the payload is EIP-712 typed-data so it's domain-separated
by chain, contract, and ruleset version.

This module is pure: no network, no clock, no validator-private state. Same inputs
yield byte-identical outputs across runs and across machines. Cross-checked against
contracts/test/fixtures/v1747_golden_vectors.json.

See docs/v1747-line-schema.md for the canonical schema.
"""

from __future__ import annotations

from dataclasses import dataclass

from Crypto.Hash import keccak
from eth_account import Account


# Schema constants. MUST match LineOutcomeRegistry.sol bytewise.
DOMAIN_TAG = b"DJINN_LINE_V1"
RULESET_TAG = b"DJINN_OUTCOMES_V1"
EIP712_DOMAIN_NAME = "DjinnLineOutcomeRegistry"
EIP712_DOMAIN_VERSION = "1"


def _keccak256(data: bytes) -> bytes:
    h = keccak.new(digest_bits=256)
    h.update(data)
    return h.digest()


def outcome_ruleset_hash() -> bytes:
    """OUTCOME_RULESET_HASH = keccak256("DJINN_OUTCOMES_V1"). Matches the contract constant."""
    return _keccak256(RULESET_TAG)


@dataclass(frozen=True)
class LineKey:
    """A single resolvable line: one ESPN event + market + side + line value.

    Hashable; same value across all validators given the same canonical inputs.
    See docs/v1747-line-schema.md §1 for the canonical string format.
    """

    sport: str
    event_id: str
    market: str       # "spread" | "total" | "moneyline"
    side: str         # "home"/"away" for spread/moneyline; "over"/"under" for total
    line_value: str   # canonical decimal one decimal place; "" for moneyline

    def canonical_string(self) -> str:
        """The exact ASCII string hashed into lineHash. Trailing pipe for moneyline.

        See schema doc §1 for strict format rules. Validators MUST NOT manipulate
        this string (no whitespace strip, no case fold, etc.) — the genius's
        committed decoy strings are the source of truth.
        """
        return (
            f"DJINN_LINE_V1|{self.sport}|{self.event_id}|"
            f"{self.market}|{self.side}|{self.line_value}"
        )


def line_hash(key: LineKey, chain_id: int, registry_address: str) -> bytes:
    """Computes lineHash matching Solidity's

        keccak256(abi.encodePacked(
            "DJINN_LINE_V1", chainId, address(this), canonicalString
        ))

    Byte encoding rules (matching abi.encodePacked):
      - "DJINN_LINE_V1" string literal: 13 raw UTF-8 bytes, no length prefix
      - chainId uint256: 32 bytes big-endian
      - address: 20 bytes (NOT padded to 32 like abi.encode would)
      - canonicalString: raw UTF-8 bytes, no length prefix

    Total preimage = 13 + 32 + 20 + len(canonicalString) bytes.

    Cross-checked: see tests/test_outcome_signer.py.
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
    return _keccak256(preimage)


def eip712_domain_separator(chain_id: int, registry_address: str) -> bytes:
    """EIP-712 domain separator matching OZ EIP712Upgradeable for this contract."""
    type_hash = _keccak256(
        b"EIP712Domain(string name,string version,uint256 chainId,address verifyingContract)"
    )
    name_hash = _keccak256(EIP712_DOMAIN_NAME.encode("utf-8"))
    version_hash = _keccak256(EIP712_DOMAIN_VERSION.encode("utf-8"))
    addr_bytes = bytes.fromhex(registry_address.lower().removeprefix("0x"))
    encoded = (
        type_hash
        + name_hash
        + version_hash
        + chain_id.to_bytes(32, "big")
        + b"\x00" * 12
        + addr_bytes
    )
    return _keccak256(encoded)


def attest_struct_hash(line_hash_bytes: bytes, outcome: int, ruleset_hash: bytes) -> bytes:
    """structHash = keccak(abi.encode(ATTEST_TYPEHASH, lineHash, outcome, rulesetHash)).

    abi.encode rules: each field padded to 32 bytes. uint8 outcome left-padded with 31 zero bytes.
    """
    type_hash = _keccak256(
        b"LineAttestation(bytes32 lineHash,uint8 outcome,bytes32 rulesetHash)"
    )
    encoded = (
        type_hash
        + line_hash_bytes
        + outcome.to_bytes(32, "big")
        + ruleset_hash
    )
    return _keccak256(encoded)


def eip712_digest(
    line_hash_bytes: bytes, outcome: int, chain_id: int, registry_address: str
) -> bytes:
    """Final digest passed to ECDSA.recover on chain.

        digest = keccak("\\x19\\x01" || domainSeparator || structHash)
    """
    domain_sep = eip712_domain_separator(chain_id, registry_address)
    struct_hash = attest_struct_hash(line_hash_bytes, outcome, outcome_ruleset_hash())
    return _keccak256(b"\x19\x01" + domain_sep + struct_hash)


def sign_line_outcome(
    private_key_hex: str,
    line_hash_bytes: bytes,
    outcome: int,
    chain_id: int,
    registry_address: str,
) -> bytes:
    """Sign a v1747 line attestation. Returns the 65-byte ECDSA signature.

    Args:
        private_key_hex: validator's OV signer EOA private key (0x-prefixed hex).
            Same key registered in OutcomeVoting.isValidator.
        line_hash_bytes: 32-byte lineHash from `line_hash(LineKey, ...)`.
        outcome: 1=Favorable, 2=Unfavorable, 3=Void. NEVER 0=Pending.
        chain_id: target chain id (e.g. 84532 for Base Sepolia).
        registry_address: deployed LineOutcomeRegistry proxy address.

    Returns:
        65 bytes (r || s || v), suitable for the contract's ECDSA.recover.
    """
    if outcome not in (1, 2, 3):
        raise ValueError(f"outcome must be Favorable/Unfavorable/Void (1/2/3), got {outcome}")
    digest = eip712_digest(line_hash_bytes, outcome, chain_id, registry_address)
    acct = Account.from_key(private_key_hex)
    signed = acct.unsafe_sign_hash(digest)
    return signed.signature


def signer_from_signature(
    signature_bytes: bytes,
    line_hash_bytes: bytes,
    outcome: int,
    chain_id: int,
    registry_address: str,
) -> str:
    """Recover the signer EOA from a v1747 attestation signature.

    Used to verify peer-gossiped attestations before counting them locally.
    Returns the 0x-prefixed lowercase EOA address.
    """
    digest = eip712_digest(line_hash_bytes, outcome, chain_id, registry_address)
    return Account._recover_hash(digest, signature=signature_bytes)
