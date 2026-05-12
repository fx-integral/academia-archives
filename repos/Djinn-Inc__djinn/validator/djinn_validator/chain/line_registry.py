"""v1747 Phase 3: LineOutcomeRegistry on-chain client.

Thin wrapper around the contract's ``submitLineOutcome(bytes32, uint8,
address[], bytes[])`` function. Handles the AlreadyFinalized terminal-
success classification: when a peer's submit beats us to threshold and
the contract reverts AlreadyFinalized, we treat that as success and
evict our local pending bundle. Any other revert is transient (RPC
flake, gas underestimate) and the caller retries next loop.

v1763: revert classification matches both the human-readable contract
error name (``"AlreadyFinalized"``) and the 4-byte EIP-712 selector hex
(``"0x475a2535"``). Pre-fix, operator diag showed thousands of
"transient" entries that were actually AlreadyFinalized — the selector
form is what web3.py surfaces in production. Same fix applies to
permanent-error markers (InvalidOutcome, BadSignature, etc.) and to
AlreadyAttested (own-EOA already on chain → terminal-success, not
retry-forever).

Until ``LineOutcomeRegistry`` is deployed (Phase 8a), construction with
``registry_address=None`` yields a no-op submitter for tests.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

import structlog

log = structlog.get_logger()


# Minimal ABI: only the functions Phase 3 actually calls. Matches
# contracts/src/LineOutcomeRegistry.sol exactly.
LINE_OUTCOME_REGISTRY_ABI = [
    {
        "inputs": [
            {"name": "lineHash", "type": "bytes32"},
            {"name": "outcome", "type": "uint8"},
            {"name": "signers", "type": "address[]"},
            {"name": "signatures", "type": "bytes[]"},
        ],
        "name": "submitLineOutcome",
        "outputs": [],
        "stateMutability": "nonpayable",
        "type": "function",
    },
    {
        "inputs": [{"name": "lineHash", "type": "bytes32"}],
        "name": "isFinalized",
        "outputs": [{"name": "", "type": "bool"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [{"name": "lineHash", "type": "bytes32"}],
        "name": "lineOutcome",
        "outputs": [{"name": "", "type": "uint8"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [{"name": "hashes", "type": "bytes32[]"}],
        "name": "batchOutcomes",
        "outputs": [{"name": "", "type": "uint8[]"}],
        "stateMutability": "view",
        "type": "function",
    },
]


# Selectors come from `cast sig "Error()"` and match contracts/src/
# LineOutcomeRegistry.sol. Web3.py surfaces these as hex strings in the
# exception message (e.g. "execution reverted: 0x475a2535"); Foundry
# traces and some local tooling surface the human-readable error name.
# Match both forms so the classification works in every environment.
TERMINAL_SUCCESS_MARKERS = (
    "AlreadyFinalized", "0x475a2535",
    "AlreadyAttested", "0x35d90805",
)
PERMANENT_REVERT_MARKERS = (
    "InvalidOutcome", "0xc74a206d",
    "BadSignature", "0x5cd5d233",
    "NotInValidatorSet", "0xf162cce5",
    "LengthMismatch", "0xff633a38",
    "ZeroAddress", "0xd92e233d",
)


@dataclass(frozen=True)
class SubmitResult:
    """Outcome of a submit attempt."""

    status: str  # "submitted" | "already_finalized" | "transient" | "permanent"
    tx_hash: str | None = None
    error: str | None = None

    @property
    def is_terminal(self) -> bool:
        """True if the local pending bundle should be evicted (success
        or peer-finalized). False if caller should retry."""
        return self.status in ("submitted", "already_finalized")


class LineOutcomeSubmitter:
    """Submits attestation bundles to LineOutcomeRegistry.submitLineOutcome.

    Implementation note: this wraps a web3.py contract call but lives
    behind the same interface as a unit-test fake. Tests inject a
    ``DummySubmitter`` with the same ``submit`` signature.
    """

    def __init__(
        self,
        w3: Any = None,
        registry_address: str | None = None,
        private_key_hex: str | None = None,
        chain_id: int | None = None,
        nonce_lock: Any = None,
    ) -> None:
        self._w3 = w3
        self._registry_address = registry_address
        self._private_key_hex = private_key_hex
        self._chain_id = chain_id
        # Optional shared nonce lock. Production validators pass
        # chain_client._nonce_lock so submitLineOutcome and submitVote
        # can't race on the same EOA's nonce. When None (unit tests),
        # we fall back to a lock-less path which is fine because tests
        # don't have a competing tx source.
        self._nonce_lock = nonce_lock
        self._contract: Any = None
        if w3 is not None and registry_address is not None:
            self._contract = w3.eth.contract(
                address=w3.to_checksum_address(registry_address),
                abi=LINE_OUTCOME_REGISTRY_ABI,
            )

    @property
    def configured(self) -> bool:
        return self._contract is not None and self._private_key_hex is not None

    async def submit(
        self,
        line_hash: bytes,
        outcome: int,
        signers: list[str],
        signatures: list[bytes],
    ) -> SubmitResult:
        """Submit a threshold attestation bundle.

        Args:
            line_hash: 32-byte canonical lineHash.
            outcome: 1=Favorable, 2=Unfavorable, 3=Void (NEVER 0).
            signers: validator EOA addresses, distinct, ≥4.
            signatures: 65-byte EIP-712 sigs aligned with signers.

        Returns:
            SubmitResult. ``is_terminal`` indicates whether the caller
            should evict the pending bundle (success or peer-finalized).
        """
        if not self.configured:
            return SubmitResult(status="permanent", error="submitter_not_configured")
        if outcome not in (1, 2, 3):
            return SubmitResult(status="permanent", error="invalid_outcome")
        if len(signers) != len(signatures):
            return SubmitResult(status="permanent", error="length_mismatch")
        if len(signers) < 1:
            return SubmitResult(status="permanent", error="empty_bundle")
        # NOTE: pre-v1755 this guard required len(signers) >= 4. The v1747
        # contract does NOT need that — it accumulates attestations across
        # transactions and emits LineFinalized once 4 distinct signers have
        # attested in any combination of bundle sizes. Relaxed so
        # submit_own_attestations (Phase 7b) can post 1-element bundles
        # before the fleet reaches threshold.

        from eth_account import Account

        try:
            account = Account.from_key(self._private_key_hex)
            checksummed = [self._w3.to_checksum_address(s) for s in signers]

            # Serialize tx-build / sign / send under the chain client's
            # nonce lock. Without this, back-to-back submits in the
            # OutcomeAttestor loop pull the same "pending" nonce and all
            # but the first revert with "nonce too low".
            #
            # v1761: every awaited RPC call inside the lock has a hard
            # timeout (matches chain/contracts.py:_send_tx). Pre-fix, a
            # slow build_transaction or send held the lock indefinitely
            # under heavy stress, queuing every subsequent submit forever.
            async def _send_inside_lock() -> Any:
                nonce = await asyncio.wait_for(
                    self._w3.eth.get_transaction_count(account.address, "pending"),
                    timeout=10.0,
                )
                tx = await asyncio.wait_for(
                    self._contract.functions.submitLineOutcome(
                        line_hash, outcome, checksummed, signatures
                    ).build_transaction(
                        {
                            "from": account.address,
                            "nonce": nonce,
                            "chainId": self._chain_id,
                        }
                    ),
                    timeout=10.0,
                )
                signed = account.sign_transaction(tx)
                return await asyncio.wait_for(
                    self._w3.eth.send_raw_transaction(signed.raw_transaction),
                    timeout=15.0,
                )

            if self._nonce_lock is not None:
                async with self._nonce_lock:
                    tx_hash = await _send_inside_lock()
            else:
                tx_hash = await _send_inside_lock()

            # Receipt-wait happens OUTSIDE the lock so other callers
            # (submitVote, etc.) aren't blocked while we wait for a block.
            receipt = await self._w3.eth.wait_for_transaction_receipt(tx_hash, timeout=60)
            if receipt.status == 1:
                return SubmitResult(status="submitted", tx_hash=tx_hash.hex())
            return SubmitResult(
                status="transient", tx_hash=tx_hash.hex(), error="receipt_status_0"
            )
        except Exception as e:
            err_str = str(e)
            # Production reverts surface as the 4-byte selector hex
            # (e.g. "0x475a2535"); local Foundry / unit-test traces show the
            # human name. Match both.
            #
            # AlreadyFinalized: peer beat us to threshold → line locked in.
            # AlreadyAttested: this signer already attested this lineHash on
            # chain (re-send after a lost-receipt). Both are terminal-success
            # for our retry loop — bundle has done its job, no more action.
            if any(m in err_str for m in TERMINAL_SUCCESS_MARKERS):
                return SubmitResult(status="already_finalized", error=err_str[:200])
            if any(m in err_str for m in PERMANENT_REVERT_MARKERS):
                log.error("line_submit_permanent_revert", err=err_str[:200])
                return SubmitResult(status="permanent", error=err_str[:200])
            log.warning("line_submit_transient", err=err_str[:200])
            return SubmitResult(status="transient", error=err_str[:200])


class _NullSubmitter:
    """No-op submitter used when chain context is missing.

    Returns "permanent" + "submitter_not_configured" so callers
    consistently skip attempts without raising.
    """

    @property
    def configured(self) -> bool:
        return False

    async def submit(
        self,
        line_hash: bytes,
        outcome: int,
        signers: list[str],
        signatures: list[bytes],
    ) -> SubmitResult:
        return SubmitResult(status="permanent", error="submitter_not_configured")


def make_submitter(
    w3: Any = None,
    registry_address: str | None = None,
    private_key_hex: str | None = None,
    chain_id: int | None = None,
) -> LineOutcomeSubmitter | _NullSubmitter:
    """Construct a submitter, falling back to a null impl if context is missing."""
    if w3 is None or registry_address is None or private_key_hex is None:
        return _NullSubmitter()
    return LineOutcomeSubmitter(
        w3=w3,
        registry_address=registry_address,
        private_key_hex=private_key_hex,
        chain_id=chain_id,
    )
