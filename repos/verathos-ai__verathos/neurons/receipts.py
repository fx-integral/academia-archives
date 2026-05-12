"""Service receipts — validator-signed proof of verified inference.

After a validator verifies miner inference (POST /inference + proof check),
it pushes a signed receipt to the miner via POST /epoch/receipt.  The receipt
includes performance metrics (ttft, tok/s, tokens generated) measured by the
validator and signed with its **Sr25519 hotkey** — the same key the metagraph
publishes.  This anchors every receipt to a real, currently-active validator
on the subnet.

Miners accumulate receipts from ALL validators throughout an epoch.  At epoch
boundary, validators pull the complete receipt batch from each miner via
GET /epoch/{n}/receipts.  Every validator receives the SAME receipt set,
computes the SAME scores, and produces IDENTICAL weights (Yuma consensus).

Verification is anchored to on-chain identity (single path, no fallback):

1. The 32-byte ``validator_hotkey`` field is the raw Sr25519 public key
   (== the bytes underlying the SS58 address).
2. ``verify_service_receipt`` resolves SS58 → UID against a fresh metagraph
   snapshot (``ValidatorAuthority``), checks ``validator_permit=True`` and
   ``stake >= ValidatorRegistry.minValidatorStake()``, then verifies the
   Sr25519 signature.
3. Receipts whose embedded pubkey is not a registered+permitted validator
   with sufficient stake are rejected outright — closes the cross-validator
   forgery hole where a miner could mint receipts with freshly-generated
   keypairs.

There is intentionally no Ed25519 fallback path: keeping one would let a
miner forge receipts with locally-generated keys (no identity binding) and
the whole on-chain anchor would be moot.
"""

from __future__ import annotations

import struct
import time
from dataclasses import dataclass


@dataclass
class ServiceReceipt:
    """A validator-signed receipt proving verified inference occurred."""

    miner_address: str
    model_id: str
    model_index: int
    epoch_number: int  # epoch this receipt belongs to
    commitment_hash: bytes  # SHA256 of inference commitment (proves real work)
    timestamp: int

    # Performance metrics (measured by validator, signed -> unforgeable)
    ttft_ms: float  # time to first token
    tokens_generated: int  # output tokens produced
    generation_time_ms: float  # total generation wall time
    tokens_per_sec: float  # measured tok/s

    # Additional metrics
    prompt_tokens: int = 0  # input token count (for throughput budget accounting)
    proof_verified: bool = False  # did validator verify ZK proof for this request?
    proof_requested: bool = False  # was proof verification ATTEMPTED? (distinguishes "not tested" from "failed")
    tee_attestation_verified: object = None  # None = not tested, True = passed, False = failed
    is_canary: bool = False  # was this a canary test (vs organic user traffic)?

    # Validator identity
    validator_hotkey: bytes = b""  # 32-byte Sr25519 public key (same bytes underlying the SS58 address)
    validator_signature: bytes = b""  # 64-byte Sr25519 signature over encode_receipt_message


@dataclass
class ValidatorAuthority:
    """Snapshot of who counts as a registered validator at a point in time.

    Built once per epoch close from a fresh metagraph + a single
    ``ValidatorRegistry.minValidatorStake()`` read.  Passed into
    ``verify_service_receipt`` so the per-receipt loop never touches the
    network — only dict and array lookups.

    The stake gate uses **total stake** (``mg.S`` = ``alpha_stake +
    tao_stake``), which is *broader* than the on-chain contract's alpha-only
    register gate (``STAKING.getTotalAlphaStaked``).  Reasoning: the
    contract's alpha gate is a one-time ceremony at registration to require
    subnet-specific skin.  Receipt verification is a different question —
    "is this signer a real economic actor that the chain permits?" — and a
    validator earning purely via root TAO delegation is still chain-permitted
    (``validator_permit=True``) and economically aligned.  Cutting them off
    here because their stake is root-delegated rather than alpha-bought
    would silently exclude legitimate measurements.

    The threshold comes from the same contract field for convenience (one
    knob the SN owner can turn).  If you want strict alpha-only semantics,
    swap ``mg.S`` → ``mg.alpha_stake`` in the validator builder.

    Attributes:
        ss58_to_uid:
            ``{ss58_address: uid}`` built from ``mg.hotkeys`` once at epoch
            close.  O(1) replacement for ``mg.hotkeys.index(ss58)``.
        validator_permit:
            ``mg.validator_permit`` (boolean per UID).  Receipts from UIDs
            without permit are rejected.
        stakes:
            Per-UID total stake on this subnet (float, alpha-equivalent
            units = ``alpha_stake + tao_stake``).  Read via
            ``float(mg.S[uid])``.
        min_stake:
            Threshold from ``ValidatorRegistry.minValidatorStake()`` divided
            by 1e9 (RAO → whole units).  Same alpha-equivalent unit as
            ``stakes`` so the comparison is unit-consistent; only the
            *interpretation* differs from the contract's alpha-only register
            gate.  Updated once per epoch close.
    """

    ss58_to_uid: dict
    validator_permit: list
    stakes: list
    min_stake: float = 0.0

    def lookup(self, ss58: str):
        """Return UID iff the SS58 is a permitted, sufficiently-staked validator.

        Returns ``None`` for: not on metagraph, no validator permit, stake
        below threshold, or any indexing error.  Never raises.
        """
        uid = self.ss58_to_uid.get(ss58)
        if uid is None:
            return None
        try:
            if not self.validator_permit[uid]:
                return None
            if float(self.stakes[uid]) < self.min_stake:
                return None
        except (IndexError, TypeError, ValueError):
            return None
        return uid


def encode_receipt_message(receipt: ServiceReceipt) -> bytes:
    """Encode receipt fields into a canonical byte string for signing/verification.

    Field order is fixed and unambiguous.  All strings are length-prefixed,
    all integers are big-endian 8-byte, all floats are big-endian double.
    """
    parts = []

    # String fields: length-prefixed UTF-8
    for s in (receipt.miner_address, receipt.model_id):
        encoded = s.encode("utf-8")
        parts.append(struct.pack(">I", len(encoded)))
        parts.append(encoded)

    # Integer fields
    parts.append(struct.pack(">q", receipt.model_index))
    parts.append(struct.pack(">q", receipt.epoch_number))

    # Fixed-length bytes
    parts.append(receipt.commitment_hash)

    # Timestamp
    parts.append(struct.pack(">q", receipt.timestamp))

    # Float metrics
    parts.append(struct.pack(">d", receipt.ttft_ms))
    parts.append(struct.pack(">q", receipt.tokens_generated))
    parts.append(struct.pack(">d", receipt.generation_time_ms))
    parts.append(struct.pack(">d", receipt.tokens_per_sec))

    # Additional metrics
    parts.append(struct.pack(">q", receipt.prompt_tokens))
    parts.append(struct.pack(">?", receipt.proof_verified))
    parts.append(struct.pack(">?", receipt.proof_requested))
    parts.append(struct.pack(">?", receipt.is_canary))

    # TEE attestation: encode as -1 (None/not tested), 0 (False), 1 (True)
    _tee_val = -1 if receipt.tee_attestation_verified is None else (1 if receipt.tee_attestation_verified else 0)
    parts.append(struct.pack(">b", _tee_val))

    # Validator hotkey
    parts.append(receipt.validator_hotkey)

    return b"".join(parts)


def sign_receipt(receipt: ServiceReceipt, hotkey_seed: bytes) -> ServiceReceipt:
    """Sign a receipt with the validator's Sr25519 hotkey.

    Args:
        receipt: with all fields populated except ``validator_signature``.
            ``validator_hotkey`` must already be the 32-byte Sr25519 public
            key (== the bytes underlying the SS58 address).
        hotkey_seed: 32-byte Bittensor hotkey seed (mini secret key).

    Returns:
        A new ServiceReceipt with ``validator_signature`` populated.
    """
    from substrateinterface import Keypair

    message = encode_receipt_message(receipt)
    keypair = Keypair.create_from_seed(hotkey_seed[:32].hex())
    signature = keypair.sign(message)
    if not isinstance(signature, bytes):
        signature = bytes.fromhex(signature[2:] if signature.startswith("0x") else signature)

    return ServiceReceipt(
        miner_address=receipt.miner_address,
        model_id=receipt.model_id,
        model_index=receipt.model_index,
        epoch_number=receipt.epoch_number,
        commitment_hash=receipt.commitment_hash,
        timestamp=receipt.timestamp,
        ttft_ms=receipt.ttft_ms,
        tokens_generated=receipt.tokens_generated,
        generation_time_ms=receipt.generation_time_ms,
        tokens_per_sec=receipt.tokens_per_sec,
        prompt_tokens=receipt.prompt_tokens,
        proof_verified=receipt.proof_verified,
        proof_requested=receipt.proof_requested,
        tee_attestation_verified=receipt.tee_attestation_verified,
        is_canary=receipt.is_canary,
        validator_hotkey=receipt.validator_hotkey,
        validator_signature=signature,
    )


def verify_service_receipt(
    receipt: ServiceReceipt,
    epoch_number: int,
    authority: ValidatorAuthority | None = None,
    receipt_window_sec: float = 4500.0,
) -> bool:
    """Verify a service receipt's signature, freshness, and validator identity.

    Single-path verification — Sr25519 anchored to the on-chain validator set:

    1. Treat ``validator_hotkey`` as a 32-byte Sr25519 public key, encode to
       SS58, look up against ``authority`` (must be on metagraph,
       ``validator_permit=True``, ``stake >= min_stake_tao``), then verify
       Sr25519 signature.  Receipts from random keypairs fail because their
       pubkey is not on the metagraph.

    There is no Ed25519 fallback.  A fallback that accepted any Ed25519 sig
    against the embedded pubkey would let a miner forge receipts with
    locally-generated keys and bypass the on-chain identity anchor entirely.

    Args:
        receipt: deserialized receipt to verify.
        epoch_number: expected epoch (rejects out-of-epoch hoarding).
        authority: snapshot of registered validators.  Required — receipts
            cannot be verified without a metagraph context.  Returns False
            if None.
        receipt_window_sec: max wall-clock skew between receipt timestamp
            and now.  Default 4500s ≈ 75 min, slightly larger than an epoch
            so receipts pulled at epoch close are still fresh.

    Returns:
        True iff the receipt is fresh, the epoch matches, the embedded
        Sr25519 pubkey resolves to a permitted+staked validator on the
        metagraph snapshot, AND the Sr25519 signature verifies.
    """
    # Cheap rejects first
    if receipt.epoch_number != epoch_number:
        return False
    now = int(time.time())
    if abs(now - receipt.timestamp) > receipt_window_sec:
        return False
    if len(receipt.validator_hotkey) != 32 or len(receipt.validator_signature) != 64:
        return False
    if authority is None:
        return False

    message = encode_receipt_message(receipt)

    try:
        from scalecodec.utils.ss58 import ss58_encode
        from substrateinterface import Keypair

        ss58 = ss58_encode(receipt.validator_hotkey)
        if authority.lookup(ss58) is None:
            return False
        kp = Keypair(ss58_address=ss58)
        return bool(kp.verify(message, receipt.validator_signature))
    except Exception:
        return False


def create_receipt(
    miner_address: str,
    model_id: str,
    model_index: int,
    epoch_number: int,
    commitment_hash: bytes,
    ttft_ms: float,
    tokens_generated: int,
    generation_time_ms: float,
    tokens_per_sec: float,
    validator_hotkey: bytes,
    validator_private_key: bytes,
    prompt_tokens: int = 0,
    proof_verified: bool = False,
    proof_requested: bool = False,
    tee_attestation_verified: object = None,
    is_canary: bool = False,
) -> ServiceReceipt:
    """Convenience: build and sign a receipt in one call.

    ``validator_hotkey`` is the 32-byte Sr25519 public key (the bytes
    underlying the validator's SS58 address).  ``validator_private_key`` is
    the 32-byte hotkey seed.  Both are derived from the Bittensor wallet at
    validator startup.
    """
    receipt = ServiceReceipt(
        miner_address=miner_address,
        model_id=model_id,
        model_index=model_index,
        epoch_number=epoch_number,
        commitment_hash=commitment_hash,
        timestamp=int(time.time()),
        ttft_ms=ttft_ms,
        tokens_generated=tokens_generated,
        generation_time_ms=generation_time_ms,
        tokens_per_sec=tokens_per_sec,
        prompt_tokens=prompt_tokens,
        proof_verified=proof_verified,
        proof_requested=proof_requested,
        tee_attestation_verified=tee_attestation_verified,
        is_canary=is_canary,
        validator_hotkey=validator_hotkey,
    )
    return sign_receipt(receipt, validator_private_key)


def receipt_to_dict(receipt: ServiceReceipt) -> dict:
    """Serialize a receipt to a JSON-safe dict (for HTTP transport)."""
    return {
        "miner_address": receipt.miner_address,
        "model_id": receipt.model_id,
        "model_index": receipt.model_index,
        "epoch_number": receipt.epoch_number,
        "commitment_hash": receipt.commitment_hash.hex(),
        "timestamp": receipt.timestamp,
        "ttft_ms": receipt.ttft_ms,
        "tokens_generated": receipt.tokens_generated,
        "generation_time_ms": receipt.generation_time_ms,
        "tokens_per_sec": receipt.tokens_per_sec,
        "prompt_tokens": receipt.prompt_tokens,
        "proof_verified": receipt.proof_verified,
        "proof_requested": receipt.proof_requested,
        "tee_attestation_verified": receipt.tee_attestation_verified,
        "is_canary": receipt.is_canary,
        "validator_hotkey": receipt.validator_hotkey.hex(),
        "validator_signature": receipt.validator_signature.hex(),
    }


def receipt_from_dict(d: dict) -> ServiceReceipt:
    """Deserialize a receipt from a JSON dict."""
    return ServiceReceipt(
        miner_address=d["miner_address"],
        model_id=d["model_id"],
        model_index=d["model_index"],
        epoch_number=d.get("epoch_number", d.get("poi_block", 0)),
        commitment_hash=bytes.fromhex(d["commitment_hash"]),
        timestamp=d["timestamp"],
        ttft_ms=d["ttft_ms"],
        tokens_generated=d["tokens_generated"],
        generation_time_ms=d["generation_time_ms"],
        tokens_per_sec=d["tokens_per_sec"],
        prompt_tokens=d.get("prompt_tokens", 0),
        proof_verified=d.get("proof_verified", False),
        proof_requested=d.get("proof_requested", False),
        tee_attestation_verified=d.get("tee_attestation_verified"),
        is_canary=d.get("is_canary", False),
        validator_hotkey=bytes.fromhex(d["validator_hotkey"]),
        validator_signature=bytes.fromhex(d["validator_signature"]),
    )
