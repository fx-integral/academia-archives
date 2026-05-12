"""On-chain interaction layer for Base chain smart contracts.

Provides typed wrappers around contract calls used by the validator:
- Escrow.getPurchase/getPurchasesBySignal — read purchase data
- SignalCommitment.getSignal() — read signal metadata
- Account.recordOutcome() — write attested outcomes
- Escrow.setOutcome() — write purchase outcomes

Supports multiple RPC URLs with automatic failover on connection errors.
Optionally supports transaction signing when a private key is provided.
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import Awaitable, Callable
from typing import Any

import structlog
from eth_account import Account as EthAccount
from web3 import AsyncWeb3
from web3.contract import AsyncContract

from djinn_validator.utils.circuit_breaker import CircuitBreaker

log = structlog.get_logger()


# Public Base RPC (sepolia.base.org, mainnet.base.org) hard-caps eth_getLogs
# at a 2000-block range; queries past that revert with -32602 / "query
# exceeds max block range 2000". Pre-v1764 the scan helpers below defaulted
# to 9_999, so EVERY chunk failed silently (the helpers swallow the error
# and return []), causing audit_bootstrap to find zero SignalCommitted /
# SignalPurchased / AuditSettled events. That left signals added via the
# live purchase path stuck at purchase_id=0 forever (v1732's backfill never
# fires without a chain-sourced add_signal call). The downstream effect was
# 48-of-49 vote submissions reverting with PurchaseIdsNotSorted() because
# the batch was built from all-zero purchaseIds. Operators on RPC providers
# with larger windows (Alchemy, QuickNode) can widen via env var.
_DEFAULT_EVENT_SCAN_CHUNK_SIZE = max(
    1, int(os.environ.get("DJINN_EVENT_SCAN_CHUNK_SIZE", "1999"))
)


def _sanitize_url(url: str) -> str:
    """Strip credentials and path from URL for safe logging."""
    from urllib.parse import urlparse

    try:
        parsed = urlparse(url)
        return f"{parsed.scheme}://{parsed.hostname}:{parsed.port or 443}"
    except Exception:
        return "<unparseable>"


# Minimal ABIs — only the functions the validator needs
_PAUSED_ABI_ENTRY = {
    "inputs": [],
    "name": "paused",
    "outputs": [{"name": "", "type": "bool"}],
    "stateMutability": "view",
    "type": "function",
}

ESCROW_ABI = [
    _PAUSED_ABI_ENTRY,
    {
        "inputs": [{"name": "user", "type": "address"}],
        "name": "getBalance",
        "outputs": [{"name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [{"name": "signalId", "type": "uint256"}],
        "name": "getPurchasesBySignal",
        "outputs": [{"name": "", "type": "uint256[]"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [{"name": "purchaseId", "type": "uint256"}],
        "name": "getPurchase",
        "outputs": [
            {
                "components": [
                    {"name": "idiot", "type": "address"},
                    {"name": "signalId", "type": "uint256"},
                    {"name": "notional", "type": "uint256"},
                    {"name": "feePaid", "type": "uint256"},
                    {"name": "creditUsed", "type": "uint256"},
                    {"name": "usdcPaid", "type": "uint256"},
                    {"name": "odds", "type": "uint256"},
                    {"name": "outcome", "type": "uint8"},
                    {"name": "purchasedAt", "type": "uint256"},
                    # v2 field (appended in V5 upgrade)
                    {"name": "lockedOdds", "type": "uint256"},
                ],
                "name": "",
                "type": "tuple",
            },
        ],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [
            {"name": "purchaseId", "type": "uint256"},
            {"name": "outcome", "type": "uint8"},
        ],
        "name": "setOutcome",
        "outputs": [],
        "stateMutability": "nonpayable",
        "type": "function",
    },
    {
        "anonymous": False,
        "inputs": [
            {"indexed": True, "name": "signalId", "type": "uint256"},
            {"indexed": True, "name": "buyer", "type": "address"},
            {"indexed": False, "name": "purchaseId", "type": "uint256"},
            {"indexed": False, "name": "notional", "type": "uint256"},
            {"indexed": False, "name": "feePaid", "type": "uint256"},
            {"indexed": False, "name": "creditUsed", "type": "uint256"},
            {"indexed": False, "name": "usdcPaid", "type": "uint256"},
        ],
        "name": "SignalPurchased",
        "type": "event",
    },
    # V6 public mapping getters for per-purchase Merkle commitments of
    # the BPA / WPA vectors. Zero bytes32 means the purchase predates V6
    # (no on-chain vector commitment) — callers must treat that as
    # "cannot verify peer data, reject peer backfill for this purchase".
    {
        "inputs": [{"name": "purchaseId", "type": "uint256"}],
        "name": "purchaseBpaRoot",
        "outputs": [{"name": "", "type": "bytes32"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [{"name": "purchaseId", "type": "uint256"}],
        "name": "purchaseWpaRoot",
        "outputs": [{"name": "", "type": "bytes32"}],
        "stateMutability": "view",
        "type": "function",
    },
]

# Pre-V6 Escrow impl (deployed 2026-03-22, upgraded 2026-04-14) emitted
# SignalPurchased without purchaseId. The proxy address is unchanged,
# but the event topic0 differs because the canonical signature differs:
#   old: SignalPurchased(uint256,address,uint256,uint256,uint256,uint256)
#   new: SignalPurchased(uint256,address,uint256,uint256,uint256,uint256,uint256)
# web3.py filters by the loaded ABI's topic0, so historical events are
# invisible to a current-ABI scan. Bootstrap scans both shapes.
ESCROW_LEGACY_EVENT_ABI = [
    {
        "anonymous": False,
        "inputs": [
            {"indexed": True, "name": "signalId", "type": "uint256"},
            {"indexed": True, "name": "buyer", "type": "address"},
            {"indexed": False, "name": "notional", "type": "uint256"},
            {"indexed": False, "name": "feePaid", "type": "uint256"},
            {"indexed": False, "name": "creditUsed", "type": "uint256"},
            {"indexed": False, "name": "usdcPaid", "type": "uint256"},
        ],
        "name": "SignalPurchased",
        "type": "event",
    },
]

SIGNAL_COMMITMENT_ABI = [
    _PAUSED_ABI_ENTRY,
    {
        "inputs": [{"name": "signalId", "type": "uint256"}],
        "name": "getSignal",
        "outputs": [
            {
                "components": [
                    {"name": "genius", "type": "address"},
                    {"name": "encryptedBlob", "type": "bytes"},
                    {"name": "commitHash", "type": "bytes32"},
                    {"name": "sport", "type": "string"},
                    {"name": "maxPriceBps", "type": "uint256"},
                    {"name": "slaMultiplierBps", "type": "uint256"},
                    {"name": "maxNotional", "type": "uint256"},
                    {"name": "minNotional", "type": "uint256"},
                    {"name": "expiresAt", "type": "uint256"},
                    {"name": "decoyLines", "type": "string[]"},
                    {"name": "availableSportsbooks", "type": "string[]"},
                    {"name": "status", "type": "uint8"},
                    {"name": "createdAt", "type": "uint256"},
                    # v2 fields (appended in V5 upgrade)
                    {"name": "linesHash", "type": "bytes32"},
                    {"name": "lineCount", "type": "uint16"},
                    {"name": "bpaMode", "type": "bool"},
                ],
                "name": "",
                "type": "tuple",
            },
        ],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [{"name": "signalId", "type": "uint256"}],
        "name": "isActive",
        "outputs": [{"name": "", "type": "bool"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "anonymous": False,
        "inputs": [
            {"indexed": True, "name": "signalId", "type": "uint256"},
            {"indexed": True, "name": "genius", "type": "address"},
            {"indexed": False, "name": "sport", "type": "string"},
            {"indexed": False, "name": "maxPriceBps", "type": "uint256"},
            {"indexed": False, "name": "slaMultiplierBps", "type": "uint256"},
            {"indexed": False, "name": "maxNotional", "type": "uint256"},
            {"indexed": False, "name": "expiresAt", "type": "uint256"},
        ],
        "name": "SignalCommitted",
        "type": "event",
    },
]

ACCOUNT_ABI = [
    _PAUSED_ABI_ENTRY,
    {
        "inputs": [
            {"name": "genius", "type": "address"},
            {"name": "idiot", "type": "address"},
            {"name": "purchaseId", "type": "uint256"},
            {"name": "outcome", "type": "uint8"},
        ],
        "name": "recordOutcome",
        "outputs": [],
        "stateMutability": "nonpayable",
        "type": "function",
    },
    {
        "inputs": [
            {"name": "genius", "type": "address"},
            {"name": "idiot", "type": "address"},
        ],
        "name": "isAuditReady",
        "outputs": [{"name": "", "type": "bool"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [
            {"name": "genius", "type": "address"},
            {"name": "idiot", "type": "address"},
        ],
        "name": "getCurrentCycle",
        "outputs": [{"name": "cycle", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [
            {"name": "genius", "type": "address"},
            {"name": "idiot", "type": "address"},
        ],
        "name": "getSignalCount",
        "outputs": [{"name": "count", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [
            {"name": "genius", "type": "address"},
            {"name": "idiot", "type": "address"},
        ],
        "name": "getPurchaseIds",
        "outputs": [{"name": "ids", "type": "uint256[]"}],
        "stateMutability": "view",
        "type": "function",
    },
    # --- v2 queue-based functions ---
    {
        "inputs": [
            {"name": "genius", "type": "address"},
            {"name": "idiot", "type": "address"},
        ],
        "name": "getAuditBatchCount",
        "outputs": [{"name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [
            {"name": "genius", "type": "address"},
            {"name": "idiot", "type": "address"},
        ],
        "name": "getPairPurchaseIds",
        "outputs": [{"name": "", "type": "uint256[]"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [
            {"name": "genius", "type": "address"},
            {"name": "idiot", "type": "address"},
        ],
        "name": "getQueueState",
        "outputs": [
            {"name": "totalPurchases", "type": "uint256"},
            {"name": "resolvedCount", "type": "uint256"},
            {"name": "auditedCount", "type": "uint256"},
            {"name": "auditBatchCount", "type": "uint256"},
        ],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [{"name": "purchaseId", "type": "uint256"}],
        "name": "isPurchaseAudited",
        "outputs": [{"name": "", "type": "bool"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [
            {"name": "genius", "type": "address"},
            {"name": "idiot", "type": "address"},
            {"name": "purchaseIds", "type": "uint256[]"},
        ],
        "name": "markBatchAudited",
        "outputs": [{"name": "batchId", "type": "uint256"}],
        "stateMutability": "nonpayable",
        "type": "function",
    },
]

OUTCOME_VOTING_ABI_V1 = [
    {
        "inputs": [
            {"name": "genius", "type": "address"},
            {"name": "idiot", "type": "address"},
            {"name": "qualityScore", "type": "int256"},
            {"name": "totalNotional", "type": "uint256"},
        ],
        "name": "submitVote",
        "outputs": [],
        "stateMutability": "nonpayable",
        "type": "function",
    },
]

OUTCOME_VOTING_ABI_V2 = [
    {
        "inputs": [
            {"name": "genius", "type": "address"},
            {"name": "idiot", "type": "address"},
            {"name": "purchaseIds", "type": "uint256[]"},
            {"name": "qualityScore", "type": "int256"},
            {"name": "totalNotional", "type": "uint256"},
            {"name": "isEarlyExit", "type": "bool"},
        ],
        "name": "submitVote",
        "outputs": [],
        "stateMutability": "nonpayable",
        "type": "function",
    },
]

OUTCOME_VOTING_ABI = OUTCOME_VOTING_ABI_V1 + [
    {
        "inputs": [
            {"name": "genius", "type": "address"},
            {"name": "idiot", "type": "address"},
            {"name": "cycle", "type": "uint256"},
        ],
        "name": "isCycleFinalized",
        "outputs": [{"name": "", "type": "bool"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [
            {"name": "genius", "type": "address"},
            {"name": "idiot", "type": "address"},
            {"name": "cycle", "type": "uint256"},
            {"name": "qualityScore", "type": "int256"},
            {"name": "totalNotional", "type": "uint256"},
        ],
        "name": "getVoteCount",
        "outputs": [{"name": "count", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [{"name": "validator", "type": "address"}],
        "name": "isValidator",
        "outputs": [{"name": "", "type": "bool"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [],
        "name": "getValidators",
        "outputs": [{"name": "", "type": "address[]"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [],
        "name": "syncNonce",
        "outputs": [{"name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [
            {"name": "newValidators", "type": "address[]"},
            {"name": "nonce", "type": "uint256"},
        ],
        "name": "proposeSync",
        "outputs": [],
        "stateMutability": "nonpayable",
        "type": "function",
    },
    {
        "inputs": [
            {"name": "", "type": "bytes32"},
            {"name": "", "type": "address"},
        ],
        "name": "hasVoted",
        "outputs": [{"name": "", "type": "bool"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [{"name": "", "type": "bytes32"}],
        "name": "finalized",
        "outputs": [{"name": "", "type": "bool"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [{"name": "", "type": "bytes32"}],
        "name": "earlyExitRequested",
        "outputs": [{"name": "", "type": "bool"}],
        "stateMutability": "view",
        "type": "function",
    },
    # P0-11 liveness-aware quorum (v1596+)
    {
        "inputs": [],
        "name": "heartbeat",
        "outputs": [],
        "stateMutability": "nonpayable",
        "type": "function",
    },
    {
        "inputs": [],
        "name": "activeWindow",
        "outputs": [{"name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [],
        "name": "activeCount",
        "outputs": [{"name": "count", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [{"name": "v", "type": "address"}],
        "name": "isActive",
        "outputs": [{"name": "", "type": "bool"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [{"name": "", "type": "address"}],
        "name": "lastActiveBlock",
        "outputs": [{"name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function",
    },
    # Share recovery (v1668+ — additive UUPS upgrade 2026-05-03)
    {
        "inputs": [{"name": "pubkey", "type": "bytes32"}],
        "name": "setEncryptionPubkey",
        "outputs": [],
        "stateMutability": "nonpayable",
        "type": "function",
    },
    {
        "inputs": [{"name": "", "type": "address"}],
        "name": "encryptionPubkey",
        "outputs": [{"name": "", "type": "bytes32"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [{"name": "featureId", "type": "bytes32"}],
        "name": "supportsFeature",
        "outputs": [{"name": "", "type": "bool"}],
        "stateMutability": "view",
        "type": "function",
    },
]

# Minimal ERC20 ABI — only balanceOf is needed for idiot balance reads.
ERC20_ABI = [
    {
        "inputs": [{"name": "account", "type": "address"}],
        "name": "balanceOf",
        "outputs": [{"name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function",
    },
]

# CreditLedger exposes the same balanceOf(address) -> uint256 shape as ERC20,
# but keep a separate name so the contract wiring stays explicit.
CREDIT_LEDGER_ABI = [
    {
        "inputs": [{"name": "account", "type": "address"}],
        "name": "balanceOf",
        "outputs": [{"name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function",
    },
]

# Collateral: deposits + locked are auto-generated mapping getters.
COLLATERAL_ABI = [
    _PAUSED_ABI_ENTRY,
    {
        "inputs": [{"name": "genius", "type": "address"}],
        "name": "deposits",
        "outputs": [{"name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [{"name": "genius", "type": "address"}],
        "name": "locked",
        "outputs": [{"name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function",
    },
]

# Audit contract: only the settlement event is needed for track-record reads.
AUDIT_ABI = [
    _PAUSED_ABI_ENTRY,
    {
        "anonymous": False,
        "inputs": [
            {"indexed": True, "name": "genius", "type": "address"},
            {"indexed": True, "name": "idiot", "type": "address"},
            {"indexed": False, "name": "batchId", "type": "uint256"},
            {"indexed": False, "name": "qualityScore", "type": "int256"},
            {"indexed": False, "name": "trancheA", "type": "uint256"},
            {"indexed": False, "name": "trancheB", "type": "uint256"},
            {"indexed": False, "name": "protocolFee", "type": "uint256"},
        ],
        "name": "AuditSettled",
        "type": "event",
    },
    # V2: 45-day SLA auto-early-exit timeout. Returns 0 pre-V2-init.
    {
        "inputs": [],
        "name": "autoEarlyExitDelay",
        "outputs": [{"name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function",
    },
]

# Connection-type errors that indicate the RPC endpoint is unreachable
_FAILOVER_ERRORS = (ConnectionError, OSError, TimeoutError)


class ChainClient:
    """Async client for interacting with Djinn contracts on Base.

    Supports multiple RPC URLs with automatic failover. Pass a comma-separated
    string or a list of URLs. On connection failure, the client rotates to the
    next available RPC endpoint and retries.
    """

    def __init__(
        self,
        rpc_url: str | list[str],
        escrow_address: str = "",
        signal_address: str = "",
        account_address: str = "",
        outcome_voting_address: str = "",
        usdc_address: str = "",
        credit_ledger_address: str = "",
        audit_address: str = "",
        collateral_address: str = "",
        line_outcome_registry_address: str = "",
        private_key: str = "",
        chain_id: int = 8453,
    ) -> None:
        if isinstance(rpc_url, str):
            self._rpc_urls = [u.strip() for u in rpc_url.split(",") if u.strip()]
        else:
            self._rpc_urls = list(rpc_url)
        if not self._rpc_urls:
            self._rpc_urls = ["https://mainnet.base.org"]
        self._rpc_index = 0
        self._escrow_address = escrow_address
        self._signal_address = signal_address
        self._account_address = account_address
        self._outcome_voting_address = outcome_voting_address
        self._usdc_address = usdc_address
        self._credit_ledger_address = credit_ledger_address
        self._audit_address = audit_address
        self._collateral_address = collateral_address
        self._line_outcome_registry_address = line_outcome_registry_address
        self._chain_id = chain_id
        self._circuit_breaker = CircuitBreaker(
            name="rpc",
            failure_threshold=3,
            recovery_timeout=30.0,
        )
        self._w3 = self._create_provider(self._rpc_urls[0])
        self._setup_contracts()

        # Contract version: 1 = cycle-based, 2 = queue-based
        # Detected lazily on first relevant call (see detect_contract_version)
        self._contract_version: int = 0  # 0 = unknown/not yet detected
        self._version_detect_epoch: int = 0  # epoch at last detection
        self._VERSION_RECHECK_INTERVAL: int = 100  # re-detect every N epochs

        # Transaction signing (optional — required for settlement writes)
        self._private_key = private_key
        self._validator_address: str | None = None
        self._nonce_lock = asyncio.Lock()
        if private_key:
            try:
                acct = EthAccount.from_key(private_key)
                self._validator_address = acct.address
                log.info("chain_client_signer_configured", address=acct.address)
            except Exception as e:
                log.error("invalid_validator_private_key", err_type=type(e).__name__)
                self._private_key = ""

    def _create_provider(self, url: str) -> AsyncWeb3:
        return AsyncWeb3(
            AsyncWeb3.AsyncHTTPProvider(
                url,
                request_kwargs={"timeout": 30},
            )
        )

    def _setup_contracts(self) -> None:
        from djinn_validator.chain.line_registry import LINE_OUTCOME_REGISTRY_ABI

        self._escrow: AsyncContract | None = None
        self._escrow_legacy_events: AsyncContract | None = None
        self._signal: AsyncContract | None = None
        self._account: AsyncContract | None = None
        self._outcome_voting: AsyncContract | None = None
        self._outcome_voting_v2: AsyncContract | None = None
        self._usdc: AsyncContract | None = None
        self._credit_ledger: AsyncContract | None = None
        self._audit: AsyncContract | None = None
        self._collateral: AsyncContract | None = None
        self._line_outcome_registry: AsyncContract | None = None
        for label, addr, abi, attr in [
            ("escrow", self._escrow_address, ESCROW_ABI, "_escrow"),
            ("signal", self._signal_address, SIGNAL_COMMITMENT_ABI, "_signal"),
            ("account", self._account_address, ACCOUNT_ABI, "_account"),
            ("outcome_voting", self._outcome_voting_address, OUTCOME_VOTING_ABI, "_outcome_voting"),
            ("usdc", self._usdc_address, ERC20_ABI, "_usdc"),
            ("credit_ledger", self._credit_ledger_address, CREDIT_LEDGER_ABI, "_credit_ledger"),
            ("audit", self._audit_address, AUDIT_ABI, "_audit"),
            ("collateral", self._collateral_address, COLLATERAL_ABI, "_collateral"),
            (
                "line_outcome_registry",
                self._line_outcome_registry_address,
                LINE_OUTCOME_REGISTRY_ABI,
                "_line_outcome_registry",
            ),
        ]:
            if addr:
                try:
                    setattr(
                        self,
                        attr,
                        self._w3.eth.contract(
                            address=self._w3.to_checksum_address(addr),
                            abi=abi,
                        ),
                    )
                except ValueError:
                    log.error("invalid_contract_address", contract=label, address=addr)

        # Build the v2 OutcomeVoting contract reference (different submitVote ABI)
        if self._outcome_voting_address:
            try:
                self._outcome_voting_v2 = self._w3.eth.contract(
                    address=self._w3.to_checksum_address(self._outcome_voting_address),
                    abi=OUTCOME_VOTING_ABI_V2
                    + [entry for entry in OUTCOME_VOTING_ABI if entry.get("name") != "submitVote"],
                )
            except ValueError:
                pass

        # Shadow contract on the same Escrow proxy address but wired to the
        # pre-V6 SignalPurchased event ABI (no purchaseId). The proxy has been
        # upgraded in place on 2026-04-14; events emitted before that are
        # unreachable via the current ABI's topic0.
        if self._escrow_address:
            try:
                self._escrow_legacy_events = self._w3.eth.contract(
                    address=self._w3.to_checksum_address(self._escrow_address),
                    abi=ESCROW_LEGACY_EVENT_ABI,
                )
            except ValueError:
                pass

    def _rotate_rpc(self) -> bool:
        """Switch to the next RPC URL. Returns True if a different URL was selected."""
        if len(self._rpc_urls) <= 1:
            return False
        old_index = self._rpc_index
        self._rpc_index = (self._rpc_index + 1) % len(self._rpc_urls)
        if self._rpc_index == old_index:
            return False
        new_url = self._rpc_urls[self._rpc_index]
        log.warning("rpc_failover", new_url=_sanitize_url(new_url), old_index=old_index, new_index=self._rpc_index)
        self._w3 = self._create_provider(new_url)
        self._setup_contracts()
        return True

    async def _with_failover(self, make_call: Callable[[], Awaitable[Any]]) -> Any:
        """Execute a contract call with circuit breaker and RPC failover.

        The circuit breaker prevents hammering endpoints that are consistently
        failing. The make_call callable is re-invoked after each rotation so
        it picks up the freshly-created contract references.
        """
        if not self._circuit_breaker.allow_request():
            raise ConnectionError(
                f"RPC circuit breaker open — all endpoints unhealthy (recovery in {self._circuit_breaker._recovery_timeout}s)"
            )

        tried = 0
        total = len(self._rpc_urls)
        last_exc: Exception | None = None
        while tried < total:
            try:
                result = await make_call()
                self._circuit_breaker.record_success()
                return result
            except _FAILOVER_ERRORS as e:
                last_exc = e
                tried += 1
                if tried < total and self._rotate_rpc():
                    from djinn_validator.api.metrics import RPC_FAILOVERS

                    RPC_FAILOVERS.inc()
                    log.warning("rpc_call_failed_retrying", err=str(e), tried=tried)
                    continue
                self._circuit_breaker.record_failure()
                raise
        self._circuit_breaker.record_failure()
        raise last_exc or ConnectionError("All RPC endpoints exhausted")

    async def is_paused(self, subsystem: str) -> bool:
        """Return True if the named contract's OpenZeppelin Pausable flag is set.

        Fail-open: returns False when the contract isn't configured (dev), when
        the paused() call fails (RPC error, ABI mismatch), or when the name is
        unknown. The validator uses this to short-circuit user-facing endpoints
        BEFORE expensive MPC work; a false negative here means "do the work, let
        the on-chain tx revert," which is the status quo and no worse. A false
        positive (claiming paused when it isn't) would be a DoS, so we prefer
        False on any uncertainty.

        subsystem ∈ {"escrow", "signal", "account"}. Audit and CreditLedger
        don't have a ChainClient reference yet; add them when endpoints that
        transitively depend on them ship.
        """
        contract = {
            "escrow": self._escrow,
            "signal": self._signal,
            "account": self._account,
        }.get(subsystem)
        if contract is None:
            return False
        try:
            return bool(
                await self._with_failover(
                    lambda: contract.functions.paused().call()  # type: ignore[union-attr]
                )
            )
        except Exception as e:
            log.warning("is_paused_read_failed", subsystem=subsystem, err=str(e))
            return False

    async def is_signal_active(self, signal_id: int) -> bool:
        """Check if a signal is still active on-chain.

        Returns False on error (fail-safe: don't release shares if chain is unreachable).
        Returns True only when contract is unconfigured (dev mode).
        """
        if self._signal is None:
            log.warning("signal_contract_not_configured")
            return True  # Permissive in dev mode (no contract)
        try:
            return await self._with_failover(
                lambda: self._signal.functions.isActive(signal_id).call()  # type: ignore[union-attr]
            )
        except Exception as e:
            log.error("is_signal_active_failed", signal_id=signal_id, err=str(e))
            return False  # Fail-safe: don't release shares when chain is unreachable

    async def get_signal(self, signal_id: int) -> dict[str, Any]:
        """Read signal metadata from SignalCommitment contract."""
        if self._signal is None:
            return {}
        try:
            result = await self._with_failover(
                lambda: self._signal.functions.getSignal(signal_id).call()  # type: ignore[union-attr]
            )
            # Tuple order matches Signal struct (v2): genius, encryptedBlob,
            # commitHash, sport, maxPriceBps, slaMultiplierBps, maxNotional,
            # minNotional, expiresAt, decoyLines, availableSportsbooks, status,
            # createdAt, linesHash, lineCount, bpaMode
            return {
                "genius": result[0],
                "encryptedBlob": result[1],
                "commitHash": result[2],
                "sport": result[3],
                "maxPriceBps": result[4],
                "slaMultiplierBps": result[5],
                "maxNotional": result[6],
                "minNotional": result[7],
                "expiresAt": result[8],
                "decoyLines": list(result[9]),
                "availableSportsbooks": list(result[10]),
                "status": result[11],
                "createdAt": result[12],
                "linesHash": result[13],
                "lineCount": result[14],
                "bpaMode": result[15],
            }
        except Exception as e:
            log.error("get_signal_failed", signal_id=signal_id, err=str(e))
            return {}

    async def get_current_block(self) -> int:
        """Return the latest block number on the primary RPC (with failover)."""
        return int(await self._with_failover(lambda: self._w3.eth.block_number))

    async def get_genius_collateral(self, address: str) -> dict[str, int]:
        """Read a genius's collateral deposit and locked amounts.

        Returns {"deposited": int, "locked": int} in raw USDC wei. Each
        read is wrapped in its own try/except so a single RPC hiccup
        degrades to 0 rather than blowing up the whole response, matching
        the Vercel route's `.catch(() => 0n)` semantics.
        """
        deposited = 0
        locked_amt = 0

        if self._collateral is not None:
            try:
                deposited = int(
                    await self._with_failover(
                        lambda: self._collateral.functions.deposits(address).call()  # type: ignore[union-attr]
                    )
                )
            except Exception as e:
                log.warning("collateral_deposits_read_failed", err=str(e)[:200])
                deposited = 0
            try:
                locked_amt = int(
                    await self._with_failover(
                        lambda: self._collateral.functions.locked(address).call()  # type: ignore[union-attr]
                    )
                )
            except Exception as e:
                log.warning("collateral_locked_read_failed", err=str(e)[:200])
                locked_amt = 0

        return {"deposited": deposited, "locked": locked_amt}

    async def get_idiot_balances(self, address: str) -> dict[str, int]:
        """Read escrow deposit, USDC wallet, and credit-ledger balances for an
        idiot. Returns raw integer wei values (no decimal scaling). Each of
        the three reads is bounded-time RPC call wrapped in its own try/except
        so a single contract being unconfigured or unreachable degrades to 0
        rather than failing the whole response.

        Used by /v1/idiot/{address}/balance — mirrors the legacy Vercel
        route /api/idiot/balance so static IPFS clients can read balances
        via a single validator hop.
        """
        escrow_bal = 0
        wallet_bal = 0
        credit_bal = 0

        if self._escrow is not None:
            try:
                escrow_bal = int(
                    await self._with_failover(
                        lambda: self._escrow.functions.getBalance(address).call()  # type: ignore[union-attr]
                    )
                )
            except Exception as e:
                log.warning("escrow_balance_read_failed", err=str(e)[:200])
                escrow_bal = 0

        if self._usdc is not None:
            try:
                wallet_bal = int(
                    await self._with_failover(
                        lambda: self._usdc.functions.balanceOf(address).call()  # type: ignore[union-attr]
                    )
                )
            except Exception as e:
                log.warning("usdc_balance_read_failed", err=str(e)[:200])
                wallet_bal = 0

        if self._credit_ledger is not None:
            try:
                credit_bal = int(
                    await self._with_failover(
                        lambda: self._credit_ledger.functions.balanceOf(address).call()  # type: ignore[union-attr]
                    )
                )
            except Exception as e:
                log.warning("credit_balance_read_failed", err=str(e)[:200])
                credit_bal = 0

        return {
            "escrow": escrow_bal,
            "wallet_usdc": wallet_bal,
            "credits": credit_bal,
        }

    async def get_recent_signal_events(
        self,
        from_block: int,
        to_block: int,
        genius_filter: str | None = None,
        chunk_size: int = _DEFAULT_EVENT_SCAN_CHUNK_SIZE,
        concurrency: int = 20,
    ) -> list[dict[str, Any]]:
        """Scan SignalCommitted events in [from_block, to_block] inclusive.

        Mirrors the shape of the Next /api/idiot/browse route: chunks the
        block range, fires up to `concurrency` chunks in parallel, drops
        chunks whose queryFilter call failed (RPC transient), and returns
        a flat list of event-arg dicts. The caller is responsible for
        filtering expired / inactive signals and for enriching with
        isActive reads.

        Returns an empty list if the signal contract is unconfigured. The
        helper is used by /v1/idiot/browse; callers that need the full
        indexed history should paginate themselves rather than widening
        the block range here.
        """
        if self._signal is None or to_block < from_block:
            return []
        ranges: list[tuple[int, int]] = []
        start = from_block
        while start <= to_block:
            end = min(start + chunk_size - 1, to_block)
            ranges.append((start, end))
            start = end + 1

        events: list[dict[str, Any]] = []
        argument_filters: dict[str, Any] = {}
        if genius_filter:
            try:
                argument_filters["genius"] = self._w3.to_checksum_address(genius_filter)
            except ValueError:
                log.warning("get_recent_signal_events_bad_genius", genius=genius_filter)
                return []

        async def _fetch(a: int, b: int) -> list[Any]:
            try:
                return await self._with_failover(
                    lambda: self._signal.events.SignalCommitted.get_logs(  # type: ignore[union-attr]
                        from_block=a,
                        to_block=b,
                        argument_filters=argument_filters or None,
                    )
                )
            except Exception as e:
                log.warning("get_recent_signal_events_chunk_failed", from_block=a, to_block=b, err=str(e))
                return []

        for i in range(0, len(ranges), concurrency):
            batch = ranges[i : i + concurrency]
            results = await asyncio.gather(*[_fetch(a, b) for a, b in batch], return_exceptions=True)
            for r in results:
                if isinstance(r, BaseException):
                    continue
                for entry in r:
                    args = getattr(entry, "args", None) or entry.get("args")
                    if not args:
                        continue
                    events.append(
                        {
                            "signal_id": int(args["signalId"]),
                            "genius": str(args["genius"]),
                            "sport": str(args["sport"]),
                            "max_price_bps": int(args["maxPriceBps"]),
                            "sla_multiplier_bps": int(args["slaMultiplierBps"]),
                            "max_notional": int(args["maxNotional"]),
                            "expires_at": int(args["expiresAt"]),
                            "block_number": int(getattr(entry, "blockNumber", 0) or entry.get("blockNumber", 0)),
                        }
                    )
        return events

    async def get_recent_audit_settlements(
        self,
        from_block: int,
        to_block: int,
        genius_filter: str | None = None,
        chunk_size: int = _DEFAULT_EVENT_SCAN_CHUNK_SIZE,
        concurrency: int = 20,
    ) -> list[dict[str, Any]]:
        """Scan Audit.AuditSettled events in [from_block, to_block] inclusive.

        Mirrors the shape of the Next /api/idiot/genius/[address] route used
        on the web side. Returns one dict per settlement with the event-arg
        fields plus blockNumber. Caller is responsible for aggregation.

        Returns an empty list if the audit contract is unconfigured.
        """
        if self._audit is None or to_block < from_block:
            return []
        ranges: list[tuple[int, int]] = []
        start = from_block
        while start <= to_block:
            end = min(start + chunk_size - 1, to_block)
            ranges.append((start, end))
            start = end + 1

        events: list[dict[str, Any]] = []
        argument_filters: dict[str, Any] = {}
        if genius_filter:
            try:
                argument_filters["genius"] = self._w3.to_checksum_address(genius_filter)
            except ValueError:
                log.warning("get_recent_audit_settlements_bad_genius", genius=genius_filter)
                return []

        async def _fetch(a: int, b: int) -> list[Any]:
            try:
                return await self._with_failover(
                    lambda: self._audit.events.AuditSettled.get_logs(  # type: ignore[union-attr]
                        from_block=a,
                        to_block=b,
                        argument_filters=argument_filters or None,
                    )
                )
            except Exception as e:
                log.warning("get_recent_audit_settlements_chunk_failed", from_block=a, to_block=b, err=str(e))
                return []

        for i in range(0, len(ranges), concurrency):
            batch = ranges[i : i + concurrency]
            results = await asyncio.gather(*[_fetch(a, b) for a, b in batch], return_exceptions=True)
            for r in results:
                if isinstance(r, BaseException):
                    continue
                for entry in r:
                    args = getattr(entry, "args", None) or entry.get("args")
                    if not args:
                        continue
                    events.append(
                        {
                            "genius": str(args["genius"]),
                            "idiot": str(args["idiot"]),
                            "batch_id": int(args["batchId"]),
                            "quality_score": int(args["qualityScore"]),
                            "tranche_a": int(args["trancheA"]),
                            "tranche_b": int(args["trancheB"]),
                            "protocol_fee": int(args["protocolFee"]),
                            "block_number": int(getattr(entry, "blockNumber", 0) or entry.get("blockNumber", 0)),
                        }
                    )
        return events

    async def get_recent_signal_purchases(
        self,
        from_block: int,
        to_block: int,
        buyer_filter: str | None = None,
        chunk_size: int = _DEFAULT_EVENT_SCAN_CHUNK_SIZE,
        concurrency: int = 5,
    ) -> list[dict[str, Any]]:
        """Scan Escrow.SignalPurchased events in [from_block, to_block] inclusive.

        Mirrors the legacy /api/idiot/purchases Vercel route filter
        semantics (buyer = authenticated idiot). Returns one dict per
        purchase with the event-arg fields plus blockNumber.

        Scans BOTH the current V6 event shape (with purchaseId) and the
        pre-V6 shape (without). The Escrow proxy was deployed 2026-03-22
        and upgraded in place to V6 on 2026-04-14; events from the 23-day
        pre-V6 window have a different topic0 and would be invisible to a
        single-ABI scan.
        """
        if self._escrow is None or to_block < from_block:
            return []
        ranges: list[tuple[int, int]] = []
        start = from_block
        while start <= to_block:
            end = min(start + chunk_size - 1, to_block)
            ranges.append((start, end))
            start = end + 1

        argument_filters: dict[str, Any] = {}
        if buyer_filter:
            try:
                argument_filters["buyer"] = self._w3.to_checksum_address(buyer_filter)
            except ValueError:
                log.warning("get_recent_signal_purchases_bad_buyer", buyer=buyer_filter)
                return []

        def _make_fetch(event_ref, label: str):
            async def _fetch(a: int, b: int) -> list[Any]:
                try:
                    return await self._with_failover(
                        lambda: event_ref.get_logs(
                            from_block=a,
                            to_block=b,
                            argument_filters=argument_filters or None,
                        )
                    )
                except Exception as e:
                    log.warning(
                        "get_recent_signal_purchases_chunk_failed",
                        from_block=a,
                        to_block=b,
                        shape=label,
                        err=str(e),
                    )
                    return []

            return _fetch

        # Current V6 shape (has purchaseId).
        fetch_v6 = _make_fetch(
            self._escrow.events.SignalPurchased,  # type: ignore[union-attr]
            "v6",
        )
        # Pre-V6 shape (no purchaseId). Same proxy address, different topic0.
        fetch_legacy = None
        if self._escrow_legacy_events is not None:
            fetch_legacy = _make_fetch(
                self._escrow_legacy_events.events.SignalPurchased,
                "pre_v6",
            )

        events: list[dict[str, Any]] = []
        seen_tx_log: set[tuple[str, int]] = set()
        for i in range(0, len(ranges), concurrency):
            batch = ranges[i : i + concurrency]
            tasks = []
            for a, b in batch:
                tasks.append(fetch_v6(a, b))
                if fetch_legacy is not None:
                    tasks.append(fetch_legacy(a, b))
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for r in results:
                if isinstance(r, BaseException):
                    continue
                for entry in r:
                    args = getattr(entry, "args", None) or entry.get("args")
                    if not args:
                        continue
                    # Dedup on (tx_hash, log_index) so both ABIs decoding
                    # the same physical log only count once. (They can't,
                    # because topic0 differs, but belt-and-suspenders.)
                    tx_hash = getattr(entry, "transactionHash", None) or entry.get("transactionHash")
                    log_idx = getattr(entry, "logIndex", 0) or entry.get("logIndex", 0)
                    key = (str(tx_hash), int(log_idx))
                    if key in seen_tx_log:
                        continue
                    seen_tx_log.add(key)
                    events.append(
                        {
                            "signal_id": str(args["signalId"]),
                            "buyer": str(args["buyer"]),
                            # Pre-V6 events have no purchaseId; legacy probe
                            # will resolve it via getPurchaseIds if needed.
                            "purchase_id": int(args["purchaseId"]) if "purchaseId" in args else 0,
                            "notional": int(args["notional"]),
                            "fee_paid": int(args["feePaid"]),
                            "credit_used": int(args["creditUsed"]),
                            "usdc_paid": int(args["usdcPaid"]),
                            "block_number": int(getattr(entry, "blockNumber", 0) or entry.get("blockNumber", 0)),
                        }
                    )
        return events

    async def get_block_timestamp(self, block_number: int) -> int:
        """Return the unix timestamp for a given block, or 0 on failure."""
        if self._w3 is None:
            return 0
        try:
            block = await self._with_failover(
                lambda: self._w3.eth.get_block(block_number)  # type: ignore[union-attr]
            )
            return int(block.get("timestamp", 0)) if isinstance(block, dict) else int(getattr(block, "timestamp", 0))
        except Exception as e:
            log.warning("get_block_timestamp_failed", block_number=block_number, err=str(e)[:200])
            return 0

    async def verify_purchase(self, signal_id: int, buyer: str) -> dict[str, Any]:
        """Verify a purchase exists on-chain for the given signal and buyer.

        Queries getPurchasesBySignal to find purchase IDs, then checks each
        via getPurchase to find one where idiot == buyer.
        """
        empty = {"notional": 0, "pricePaid": 0, "sportsbook": ""}
        if self._escrow is None:
            log.warning("escrow_contract_not_configured")
            return empty
        try:
            buyer_addr = self._w3.to_checksum_address(buyer)
        except ValueError:
            log.error("invalid_buyer_address", buyer=buyer)
            return empty
        try:
            purchase_ids: list[int] = await self._with_failover(
                lambda: self._escrow.functions.getPurchasesBySignal(  # type: ignore[union-attr]
                    signal_id,
                ).call()
            )
            for pid in purchase_ids:
                p = await self._with_failover(
                    lambda pid=pid: self._escrow.functions.getPurchase(  # type: ignore[union-attr]
                        pid,
                    ).call()
                )
                # Purchase tuple: (idiot, signalId, notional, feePaid, creditUsed, usdcPaid, odds, outcome, purchasedAt, lockedOdds)
                if p[0].lower() == buyer_addr.lower():
                    return {
                        "notional": p[2],
                        "pricePaid": p[4] + p[5],  # creditUsed + usdcPaid
                        "sportsbook": "",
                    }
            return empty
        except Exception as e:
            log.error("verify_purchase_failed", signal_id=signal_id, buyer=buyer, err=str(e))
            return empty

    async def is_audit_ready(self, genius: str, idiot: str) -> bool:
        """Check if a Genius-Idiot pair has completed a cycle."""
        if self._account is None:
            return False
        try:
            genius_addr = self._w3.to_checksum_address(genius)
            idiot_addr = self._w3.to_checksum_address(idiot)
        except ValueError:
            log.error("invalid_address_for_audit", genius=genius, idiot=idiot)
            return False
        try:
            return await self._with_failover(
                lambda: self._account.functions.isAuditReady(  # type: ignore[union-attr]
                    genius_addr,
                    idiot_addr,
                ).call()
            )
        except Exception as e:
            log.error("is_audit_ready_failed", genius=genius, idiot=idiot, err=str(e))
            return False

    # ------------------------------------------------------------------
    # Read helpers for settlement
    # ------------------------------------------------------------------

    async def get_purchases_by_signal(self, signal_id: int) -> list[int]:
        """Return all purchase IDs for a given signal."""
        if self._escrow is None:
            return []
        try:
            return await self._with_failover(
                lambda: self._escrow.functions.getPurchasesBySignal(signal_id).call()  # type: ignore[union-attr]
            )
        except Exception as e:
            log.error("get_purchases_by_signal_failed", signal_id=signal_id, err=str(e))
            return []

    async def get_purchase(self, purchase_id: int) -> dict[str, Any]:
        """Read a single Purchase struct from Escrow."""
        if self._escrow is None:
            return {}
        try:
            p = await self._with_failover(
                lambda: self._escrow.functions.getPurchase(purchase_id).call()  # type: ignore[union-attr]
            )
            # Purchase tuple (v2): (idiot, signalId, notional, feePaid, creditUsed, usdcPaid, odds, outcome, purchasedAt, lockedOdds)
            return {
                "idiot": p[0],
                "signalId": p[1],
                "notional": p[2],
                "feePaid": p[3],
                "creditUsed": p[4],
                "usdcPaid": p[5],
                "odds": p[6],
                "outcome": p[7],  # 0=Pending, 1=Favorable, 2=Unfavorable, 3=Void
                "purchasedAt": p[8],
                "lockedOdds": p[9],
            }
        except Exception as e:
            log.error("get_purchase_failed", purchase_id=purchase_id, err=str(e))
            return {}

    async def get_purchase_vector_roots(self, purchase_id: int) -> tuple[bytes, bytes] | None:
        """Read the on-chain BPA + WPA Merkle roots for a V6 purchase.

        Returns ``(bpa_root, wpa_root)`` as 32-byte values, or ``None`` on
        RPC failure. Both roots are zero for pre-V6 purchases (no
        on-chain commitment to compare against). Callers that use this
        for authenticating peer-supplied vectors MUST treat the
        zero-bytes case as "cannot authenticate" and refuse to write the
        peer data to the local ledger.
        """
        if self._escrow is None:
            return None
        try:
            bpa, wpa = await asyncio.gather(
                self._with_failover(
                    lambda: self._escrow.functions.purchaseBpaRoot(purchase_id).call()  # type: ignore[union-attr]
                ),
                self._with_failover(
                    lambda: self._escrow.functions.purchaseWpaRoot(purchase_id).call()  # type: ignore[union-attr]
                ),
            )
            return (bytes(bpa), bytes(wpa))
        except Exception as e:
            log.error(
                "get_purchase_vector_roots_failed",
                purchase_id=purchase_id,
                err=str(e),
            )
            return None

    # ------------------------------------------------------------------
    # Write methods for settlement (require private key)
    # ------------------------------------------------------------------

    @property
    def can_write(self) -> bool:
        """True if the client has a private key configured for signing transactions."""
        return bool(self._private_key and self._validator_address)

    @property
    def validator_address(self) -> str | None:
        """The Base address derived from the configured private key."""
        return self._validator_address

    async def _send_tx(
        self,
        contract: AsyncContract,
        fn_name: str,
        *args: Any,
        gas_limit: int = 300_000,
    ) -> str:
        """Build, sign, and send a contract transaction. Returns tx hash hex.

        Uses a nonce lock to prevent nonce collisions when multiple txs are
        sent concurrently within the same epoch.
        """
        if not self.can_write:
            raise RuntimeError("No private key configured — cannot send transactions")

        fn = getattr(contract.functions, fn_name)(*args)

        # v1761: every awaited RPC call inside the nonce_lock has a hard
        # timeout. Pre-fix, a single slow estimate_gas under load held the
        # lock indefinitely, queuing every other submitVote and
        # submitLineOutcome behind it -- the production deadlock observed
        # 2026-05-09 afternoon under heavy stress. Each operation falls
        # back gracefully on TimeoutError so the tx still goes out with
        # sensible defaults instead of stalling the whole submitter.
        async with self._nonce_lock:
            try:
                nonce = await asyncio.wait_for(
                    self._with_failover(
                        lambda: self._w3.eth.get_transaction_count(self._validator_address, "pending")  # type: ignore[arg-type]
                    ),
                    timeout=10.0,
                )
            except asyncio.TimeoutError:
                log.warning("send_tx_nonce_fetch_timeout", fn=fn_name)
                raise

            # Estimate gas with fallback (timeout + exception both fall back).
            try:
                gas = await asyncio.wait_for(
                    fn.estimate_gas({"from": self._validator_address}),
                    timeout=5.0,
                )
                gas = int(gas * 1.3)  # 30% buffer
            except (Exception, asyncio.TimeoutError):
                gas = gas_limit

            try:
                gas_price = await asyncio.wait_for(
                    self._with_failover(lambda: self._w3.eth.gas_price),
                    timeout=5.0,
                )
            except asyncio.TimeoutError:
                log.warning("send_tx_gas_price_timeout", fn=fn_name)
                gas_price = 1_000_000_000  # 1 gwei fallback
            # Cap gas price at 100 gwei to prevent runaway spend during spikes
            max_gas_price = 100 * 10**9  # 100 gwei
            if gas_price > max_gas_price:
                log.warning("gas_price_capped", actual_gwei=gas_price / 10**9, cap_gwei=100)
                gas_price = max_gas_price

            try:
                tx = await asyncio.wait_for(
                    fn.build_transaction(
                        {
                            "from": self._validator_address,
                            "gas": gas,
                            "gasPrice": gas_price,
                            "nonce": nonce,
                            "chainId": self._chain_id,
                        }
                    ),
                    timeout=10.0,
                )
            except asyncio.TimeoutError:
                log.warning("send_tx_build_timeout", fn=fn_name)
                raise

            signed = EthAccount.sign_transaction(tx, self._private_key)
            try:
                tx_hash = await asyncio.wait_for(
                    self._with_failover(lambda: self._w3.eth.send_raw_transaction(signed.raw_transaction)),
                    timeout=15.0,
                )
            except asyncio.TimeoutError:
                log.warning("send_tx_broadcast_timeout", fn=fn_name)
                raise

        return tx_hash.hex()

    async def record_outcome(
        self,
        genius: str,
        idiot: str,
        purchase_id: int,
        outcome: int,
    ) -> str:
        """Write an outcome to Account.recordOutcome(). Returns tx hash."""
        if self._account is None:
            raise RuntimeError("Account contract not configured")

        genius_addr = self._w3.to_checksum_address(genius)
        idiot_addr = self._w3.to_checksum_address(idiot)

        return await self._send_tx(
            self._account,
            "recordOutcome",
            genius_addr,
            idiot_addr,
            purchase_id,
            outcome,
        )

    async def set_escrow_outcome(
        self,
        purchase_id: int,
        outcome: int,
    ) -> str:
        """Write an outcome to Escrow.setOutcome(). Returns tx hash."""
        if self._escrow is None:
            raise RuntimeError("Escrow contract not configured")

        return await self._send_tx(
            self._escrow,
            "setOutcome",
            purchase_id,
            outcome,
        )

    async def settle_purchase(
        self,
        genius: str,
        idiot: str,
        purchase_id: int,
        outcome: int,
    ) -> dict[str, str | None]:
        """Settle a single purchase: write outcome to both Account and Escrow.

        Returns dict with 'account_tx' and 'escrow_tx' hashes (None on error).
        Skips purchases whose on-chain outcome is already set.
        """
        result: dict[str, str | None] = {"account_tx": None, "escrow_tx": None}

        # Check if already settled on-chain
        purchase = await self.get_purchase(purchase_id)
        if purchase and purchase.get("outcome", 0) != 0:
            log.debug(
                "purchase_already_settled",
                purchase_id=purchase_id,
                on_chain_outcome=purchase["outcome"],
            )
            return result

        # Write to Account.recordOutcome
        try:
            tx = await self.record_outcome(genius, idiot, purchase_id, outcome)
            result["account_tx"] = tx
            log.info(
                "account_outcome_recorded",
                purchase_id=purchase_id,
                outcome=outcome,
                tx_hash=tx,
            )
        except Exception as e:
            err_str = str(e)
            if "OutcomeAlreadyRecorded" in err_str:
                log.debug("account_outcome_already_recorded", purchase_id=purchase_id)
            else:
                log.error("account_record_outcome_failed", purchase_id=purchase_id, err=err_str)
                return result

        # Write to Escrow.setOutcome
        try:
            tx = await self.set_escrow_outcome(purchase_id, outcome)
            result["escrow_tx"] = tx
            log.info(
                "escrow_outcome_set",
                purchase_id=purchase_id,
                outcome=outcome,
                tx_hash=tx,
            )
        except Exception as e:
            err_str = str(e)
            if "OutcomeAlreadySet" in err_str:
                log.debug("escrow_outcome_already_set", purchase_id=purchase_id)
            else:
                log.error("escrow_set_outcome_failed", purchase_id=purchase_id, err=err_str)

        return result

    # ------------------------------------------------------------------
    # Contract version detection
    # ------------------------------------------------------------------

    @property
    def contract_version(self) -> int:
        """Current detected contract version (0 = not yet detected)."""
        return self._contract_version

    def signer_address(self) -> str | None:
        """The validator's signer EOA derived from the configured private key.

        Returns None if no private key was configured (read-only client).
        """
        return self._validator_address

    async def detect_contract_version(self, epoch: int = 0) -> int:
        """Detect whether contracts are v1 (cycle-based) or v2 (queue-based).

        Tries calling Account.getAuditBatchCount(ZERO, ZERO). If it succeeds,
        the contract is v2. If it reverts, the contract is v1.

        Re-detects every _VERSION_RECHECK_INTERVAL epochs so a mid-run
        proxy upgrade is picked up without a restart.
        """
        if self._contract_version != 0 and epoch - self._version_detect_epoch < self._VERSION_RECHECK_INTERVAL:
            return self._contract_version

        if self._account is None:
            log.warning("version_detect_no_account_contract")
            self._contract_version = 1
            return 1

        zero = "0x" + "0" * 40
        try:
            zero_addr = self._w3.to_checksum_address(zero)
            await self._with_failover(
                lambda: self._account.functions.getAuditBatchCount(  # type: ignore[union-attr]
                    zero_addr,
                    zero_addr,
                ).call()
            )
            # Call succeeded: v2 contract
            if self._contract_version != 2:
                log.info("contract_version_detected", version=2, epoch=epoch)
            self._contract_version = 2
        except Exception:
            # Reverted or function not found: v1 contract
            if self._contract_version != 1:
                log.info("contract_version_detected", version=1, epoch=epoch)
            self._contract_version = 1

        self._version_detect_epoch = epoch
        return self._contract_version

    # ------------------------------------------------------------------
    # Account read helpers for quality score computation
    # ------------------------------------------------------------------

    async def get_current_cycle(self, genius: str, idiot: str) -> int:
        """Get the current audit cycle for a Genius-Idiot pair (v1 only)."""
        if self._account is None:
            return 0
        try:
            genius_addr = self._w3.to_checksum_address(genius)
            idiot_addr = self._w3.to_checksum_address(idiot)
            return await self._with_failover(
                lambda: self._account.functions.getCurrentCycle(genius_addr, idiot_addr).call()  # type: ignore[union-attr]
            )
        except Exception as e:
            log.error("get_current_cycle_failed", genius=genius, idiot=idiot, err=str(e))
            return 0

    async def get_signal_count(self, genius: str, idiot: str) -> int:
        """Get the signal count in the current cycle for a Genius-Idiot pair (v1 only)."""
        if self._account is None:
            return 0
        try:
            genius_addr = self._w3.to_checksum_address(genius)
            idiot_addr = self._w3.to_checksum_address(idiot)
            return await self._with_failover(
                lambda: self._account.functions.getSignalCount(genius_addr, idiot_addr).call()  # type: ignore[union-attr]
            )
        except Exception as e:
            log.error("get_signal_count_failed", genius=genius, idiot=idiot, err=str(e))
            return 0

    async def get_purchase_ids(self, genius: str, idiot: str) -> list[int]:
        """Get all purchase IDs for the current cycle of a Genius-Idiot pair (v1 only)."""
        if self._account is None:
            return []
        try:
            genius_addr = self._w3.to_checksum_address(genius)
            idiot_addr = self._w3.to_checksum_address(idiot)
            return await self._with_failover(
                lambda: self._account.functions.getPurchaseIds(genius_addr, idiot_addr).call()  # type: ignore[union-attr]
            )
        except Exception as e:
            log.error("get_purchase_ids_failed", genius=genius, idiot=idiot, err=str(e))
            return []

    # ------------------------------------------------------------------
    # Account v2 queue-based read helpers
    # ------------------------------------------------------------------

    async def get_audit_batch_count(self, genius: str, idiot: str) -> int:
        """Get the number of completed audit batches for a pair (v2 only)."""
        if self._account is None:
            return 0
        try:
            genius_addr = self._w3.to_checksum_address(genius)
            idiot_addr = self._w3.to_checksum_address(idiot)
            return await self._with_failover(
                lambda: self._account.functions.getAuditBatchCount(  # type: ignore[union-attr]
                    genius_addr,
                    idiot_addr,
                ).call()
            )
        except Exception as e:
            log.error("get_audit_batch_count_failed", genius=genius, idiot=idiot, err=str(e))
            return 0

    async def get_pair_purchase_ids(self, genius: str, idiot: str) -> list[int]:
        """Get all purchase IDs for a genius-idiot pair (v2 only, full queue)."""
        if self._account is None:
            return []
        try:
            genius_addr = self._w3.to_checksum_address(genius)
            idiot_addr = self._w3.to_checksum_address(idiot)
            return await self._with_failover(
                lambda: self._account.functions.getPairPurchaseIds(  # type: ignore[union-attr]
                    genius_addr,
                    idiot_addr,
                ).call()
            )
        except Exception as e:
            log.error("get_pair_purchase_ids_failed", genius=genius, idiot=idiot, err=str(e))
            return []

    async def get_queue_state(
        self,
        genius: str,
        idiot: str,
    ) -> tuple[int, int, int, int]:
        """Get queue state for a pair (v2 only).

        Returns (totalPurchases, resolvedCount, auditedCount, auditBatchCount).
        """
        if self._account is None:
            return (0, 0, 0, 0)
        try:
            genius_addr = self._w3.to_checksum_address(genius)
            idiot_addr = self._w3.to_checksum_address(idiot)
            result = await self._with_failover(
                lambda: self._account.functions.getQueueState(  # type: ignore[union-attr]
                    genius_addr,
                    idiot_addr,
                ).call()
            )
            return (int(result[0]), int(result[1]), int(result[2]), int(result[3]))
        except Exception as e:
            log.error("get_queue_state_failed", genius=genius, idiot=idiot, err=str(e))
            return (0, 0, 0, 0)

    async def is_purchase_audited(self, purchase_id: int) -> bool:
        """Check if a purchase has already been audited (v2 only)."""
        if self._account is None:
            return False
        try:
            return await self._with_failover(
                lambda: self._account.functions.isPurchaseAudited(  # type: ignore[union-attr]
                    purchase_id,
                ).call()
            )
        except Exception as e:
            log.error("is_purchase_audited_failed", purchase_id=purchase_id, err=str(e))
            return False

    async def get_pair_settlement_status(
        self,
        genius: str,
        idiot: str,
        epoch: int = 0,
    ) -> dict[str, int | bool]:
        """Version-aware settlement status snapshot for a genius-idiot pair.

        Returns the same shape the Vercel /api/settlement/[g]/[i] route
        historically returned, so callers can swap in without behavior
        change. Detects v1 (cycle-based) vs v2 (queue-based) internally.
        """
        if self._account is None:
            return {
                "contract_version": 1,
                "current_cycle": 0,
                "signals_in_cycle": 0,
                "total_purchases": 0,
                "resolved_count": 0,
                "audited_count": 0,
                "audit_batch_count": 0,
                "ready_for_settlement": False,
            }

        version = await self.detect_contract_version(epoch=epoch)

        if version == 2:
            total, resolved, audited, batches = await self.get_queue_state(genius, idiot)
            return {
                "contract_version": 2,
                "total_purchases": total,
                "resolved_count": resolved,
                "audited_count": audited,
                "audit_batch_count": batches,
                "ready_for_settlement": (resolved - audited) >= 10,
                "current_cycle": batches,
                "signals_in_cycle": total,
            }

        cycle = await self.get_current_cycle(genius, idiot)
        purchase_ids = await self.get_purchase_ids(genius, idiot)
        signals = len(purchase_ids)
        return {
            "contract_version": 1,
            "current_cycle": cycle,
            "signals_in_cycle": signals,
            "total_purchases": signals,
            "resolved_count": 0,
            "audited_count": 0,
            "audit_batch_count": cycle,
            "ready_for_settlement": signals >= 10,
        }

    async def mark_batch_audited(
        self,
        genius: str,
        idiot: str,
        purchase_ids: list[int],
    ) -> str:
        """Mark a batch of purchases as audited on-chain (v2 only). Returns tx hash."""
        if self._account is None:
            raise RuntimeError("Account contract not configured")

        genius_addr = self._w3.to_checksum_address(genius)
        idiot_addr = self._w3.to_checksum_address(idiot)

        return await self._send_tx(
            self._account,
            "markBatchAudited",
            genius_addr,
            idiot_addr,
            purchase_ids,
            gas_limit=500_000,
        )

    # ------------------------------------------------------------------
    # OutcomeVoting write methods
    # ------------------------------------------------------------------

    async def submit_vote(
        self,
        genius: str,
        idiot: str,
        quality_score: int,
        total_notional: int,
        purchase_ids: list[int] | None = None,
        is_early_exit: bool = False,
    ) -> str:
        """Submit a quality score vote to OutcomeVoting. Returns tx hash.

        Automatically selects v1 or v2 call based on contract_version:
        - v1: submitVote(genius, idiot, qualityScore, totalNotional)
        - v2: submitVote(genius, idiot, purchaseIds, qualityScore, totalNotional, isEarlyExit)

        If purchase_ids is provided and contract_version == 2, uses the v2 signature.
        Falls back to v1 if version is 1 or unknown.
        """
        genius_addr = self._w3.to_checksum_address(genius)
        idiot_addr = self._w3.to_checksum_address(idiot)

        if self._contract_version == 2 and purchase_ids is not None:
            if self._outcome_voting_v2 is None:
                raise RuntimeError("OutcomeVoting v2 contract not configured")
            return await self._send_tx(
                self._outcome_voting_v2,
                "submitVote",
                genius_addr,
                idiot_addr,
                purchase_ids,
                quality_score,
                total_notional,
                is_early_exit,
                gas_limit=300_000,
            )

        # v1 path (or version unknown, safe fallback)
        if self._outcome_voting is None:
            raise RuntimeError("OutcomeVoting contract not configured")
        return await self._send_tx(
            self._outcome_voting,
            "submitVote",
            genius_addr,
            idiot_addr,
            quality_score,
            total_notional,
            gas_limit=200_000,
        )

    async def is_cycle_finalized(self, genius: str, idiot: str, cycle: int) -> bool:
        """Check if a cycle has been finalized in OutcomeVoting."""
        if self._outcome_voting is None:
            return False
        try:
            genius_addr = self._w3.to_checksum_address(genius)
            idiot_addr = self._w3.to_checksum_address(idiot)
            return await self._with_failover(
                lambda: self._outcome_voting.functions.isCycleFinalized(  # type: ignore[union-attr]
                    genius_addr,
                    idiot_addr,
                    cycle,
                ).call()
            )
        except Exception as e:
            log.error("is_cycle_finalized_failed", genius=genius, idiot=idiot, cycle=cycle, err=str(e))
            return False

    # ------------------------------------------------------------------
    # Share recovery: per-validator x25519 encryption pubkey registry
    # (additive OV upgrade v1668+, see project_share_recovery_design_2026_05_03.md)
    # ------------------------------------------------------------------

    async def set_encryption_pubkey(self, pubkey_bytes: bytes) -> str:
        """Publish or rotate this validator's x25519 encryption pubkey on chain.

        The pubkey is what genius clients use to NaCl-box their Shamir share to
        this validator. Callable only by registered validators (the contract
        enforces NotValidator). Returns the tx hash.
        """
        if self._outcome_voting is None:
            raise RuntimeError("OutcomeVoting contract not configured")
        if len(pubkey_bytes) != 32:
            raise ValueError(f"pubkey must be 32 bytes, got {len(pubkey_bytes)}")
        return await self._send_tx(
            self._outcome_voting,
            "setEncryptionPubkey",
            pubkey_bytes,
            gas_limit=120_000,
        )

    async def get_encryption_pubkey(self, signer: str) -> bytes:
        """Read the on-chain x25519 encryption pubkey for a validator.

        Returns 32 zero bytes if the validator has not yet published one
        (the genius client treats zero as 'skip and retry on next signal').
        """
        if self._outcome_voting is None:
            return b"\x00" * 32
        try:
            signer_addr = self._w3.to_checksum_address(signer)
            result = await self._with_failover(
                lambda: self._outcome_voting.functions.encryptionPubkey(signer_addr).call()  # type: ignore[union-attr]
            )
            return bytes(result) if result else b"\x00" * 32
        except Exception as e:
            log.warning("get_encryption_pubkey_failed", signer=signer, err=str(e)[:200])
            return b"\x00" * 32

    async def supports_share_recovery(self) -> bool:
        """Return True if the live OV impl supports the share-recovery feature.

        Used by the validator startup path to decide whether to publish a pubkey.
        Falls back to False (legacy plaintext-share path) on any RPC error.
        """
        if self._outcome_voting is None:
            return False
        try:
            from eth_utils import keccak

            feature_id = keccak(text="SHARE_RECOVERY")
            return await self._with_failover(
                lambda: self._outcome_voting.functions.supportsFeature(feature_id).call()  # type: ignore[union-attr]
            )
        except Exception as e:
            log.debug("supports_share_recovery_check_failed", err=str(e)[:200])
            return False

    def _compute_batch_key_v2(
        self,
        genius: str,
        idiot: str,
        purchase_ids: list[int],
    ) -> bytes:
        """Mirror OutcomeVoting.submitVote batchKey computation (v2):
        keccak256(abi.encode(genius, idiot, keccak256(abi.encode(purchaseIds)))).

        Kept in lockstep with contracts/src/OutcomeVoting.sol:405. Validators
        that produce a different batchKey would never coalesce quorum.
        """
        from eth_abi import encode as abi_encode
        from eth_utils import keccak

        genius_addr = self._w3.to_checksum_address(genius)
        idiot_addr = self._w3.to_checksum_address(idiot)
        inner = keccak(abi_encode(["uint256[]"], [list(purchase_ids)]))
        return keccak(abi_encode(["address", "address", "bytes32"], [genius_addr, idiot_addr, inner]))

    async def has_voted_for_batch(
        self,
        genius: str,
        idiot: str,
        purchase_ids: list[int],
    ) -> tuple[bool, bool]:
        """Read (already_voted, finalized) for a v2 batch before submitting.

        P0-01 root cause (v1580): when a v2 submitVote tx reverts on-chain with
        AlreadyVoted/CycleAlreadyFinalized, the receipt has status=0 but no
        decoded reason bubbles up — main.py saw a generic "audit_vote_reverted"
        and continued without marking the audit_set settled, causing the
        settlement loop to retry the same stuck batchKey every 12 seconds
        forever. This pre-flight check lets the caller treat those conditions
        as "already done" and mark_settled without burning another on-chain tx.

        Returns (False, False) on any RPC error so the caller falls back to the
        blind-submit path (status quo) instead of stalling on a flaky provider.
        """
        if self._outcome_voting_v2 is None or not self._validator_address:
            return (False, False)
        if not purchase_ids:
            return (False, False)
        try:
            batch_key = self._compute_batch_key_v2(genius, idiot, purchase_ids)
            signer = self._w3.to_checksum_address(self._validator_address)
            already_voted = await self._with_failover(
                lambda: self._outcome_voting_v2.functions.hasVoted(batch_key, signer).call()  # type: ignore[union-attr]
            )
            is_final = await self._with_failover(
                lambda: self._outcome_voting_v2.functions.finalized(batch_key).call()  # type: ignore[union-attr]
            )
            # 2026-05-02 stale-snapshot bypass: OV.submitVote at line 530-537
            # resets hasVoted for ALL validators when cycleSyncNonce[batchKey]
            # != syncNonce. So a hasVoted=true reading on a stale snapshot is
            # NOT a "skip submit" condition — the on-chain submit will reset
            # it. Without this check, BumpSyncNonce(11→13) leaves validators
            # bailing on every batch they already voted on pre-bump, even
            # though re-submitting is exactly what we want. Discovered when
            # 3/14 shadow_settle_completed events all hit
            # `submit_from_shadow_already_voted_awaiting_quorum` for batches
            # where syncNonce had advanced under them.
            if bool(already_voted) and not bool(is_final):
                try:
                    cur_nonce = await self._with_failover(
                        lambda: self._outcome_voting_v2.functions.syncNonce().call()  # type: ignore[union-attr]
                    )
                    snap_nonce = await self._with_failover(
                        lambda: self._outcome_voting_v2.functions.cycleSyncNonce(batch_key).call()  # type: ignore[union-attr]
                    )
                    if int(snap_nonce) != 0 and int(snap_nonce) != int(cur_nonce):
                        log.info(
                            "has_voted_for_batch_stale_snapshot",
                            cycle_sync_nonce=int(snap_nonce),
                            current_sync_nonce=int(cur_nonce),
                        )
                        # On-chain reset will fire on next submitVote.
                        # Treat as not-yet-voted so caller proceeds.
                        return (False, False)
                except Exception as e:
                    log.debug("stale_snapshot_check_failed", err=str(e)[:120])
                    # Fail-open: trust the raw hasVoted reading.
            return (bool(already_voted), bool(is_final))
        except Exception as e:
            log.debug("has_voted_for_batch_failed", err=str(e)[:200])
            return (False, False)

    async def should_auto_early_exit(self, purchase_ids: list[int]) -> bool:
        """Check whether Audit's 45-day SLA timeout has elapsed for this batch.

        Returns True iff Audit.autoEarlyExitDelay > 0 (V2 initialized) AND
        block.timestamp - max(getPurchase(id).purchasedAt) > delay. Used by
        the validator submit gate to opt sub-MIN_BATCH batches into early
        exit when neither party has called OV.requestEarlyExit but the SLA
        deadline has passed.

        Returns False on any RPC error so the caller falls back to "skip
        submit" (the safe default — never auto-trigger early-exit on a
        flapping RPC).
        """
        if self._audit is None:
            return False
        if not purchase_ids:
            return False
        try:
            delay = await self._with_failover(
                lambda: self._audit.functions.autoEarlyExitDelay().call()  # type: ignore[union-attr]
            )
            if int(delay) == 0:
                return False
            # Find the latest purchase timestamp across the batch.
            latest = 0
            for pid in purchase_ids:
                p = await self._with_failover(
                    lambda pid=pid: self._escrow.functions.getPurchase(int(pid)).call()  # type: ignore[union-attr]
                )
                # Purchase tuple: (idiot, signalId, notional, feePaid, creditUsed,
                # usdcPaid, odds, outcome, purchasedAt, lockedOdds). purchasedAt
                # is index 8 (counting from 0).
                purchased_at = int(p[8])
                if purchased_at > latest:
                    latest = purchased_at
            if latest == 0:
                return False
            block_ts = await self._with_failover(lambda: self._w3.eth.get_block("latest"))
            now_ts = int(block_ts["timestamp"]) if isinstance(block_ts, dict) else int(block_ts.timestamp)
            return (now_ts - latest) > int(delay)
        except Exception as e:
            log.debug("should_auto_early_exit_failed", err=str(e)[:200])
            return False

    async def is_early_exit_requested(
        self,
        genius: str,
        idiot: str,
        purchase_ids: list[int],
    ) -> bool:
        """Read OV.earlyExitRequested[batchKey] for a v2 batch.

        Returns True only when either the genius or the idiot has explicitly
        called OV.requestEarlyExit for these purchaseIds. Validators MUST
        consult this before submitting isEarlyExit=true on a sub-MIN_BATCH
        batch — otherwise they would silently degrade USDC damages to
        Credits-only damages without the parties' consent.

        Returns False on any RPC error so the caller falls back to the
        safe default (don't submit early-exit).
        """
        if self._outcome_voting_v2 is None:
            return False
        if not purchase_ids:
            return False
        try:
            batch_key = self._compute_batch_key_v2(genius, idiot, purchase_ids)
            return bool(
                await self._with_failover(
                    lambda: self._outcome_voting_v2.functions.earlyExitRequested(batch_key).call()  # type: ignore[union-attr]
                )
            )
        except Exception as e:
            log.debug("is_early_exit_requested_failed", err=str(e)[:200])
            return False

    async def is_registered_validator(self) -> bool | None:
        """Check if this validator is registered in OutcomeVoting.

        Returns True/False for a definitive on-chain answer, or None when the
        RPC call itself failed (transport flap, provider rate limit, etc.).
        Callers must distinguish None from False so a flappy RPC doesn't get
        misreported as "missing_bootstrap" in /health diagnosis.
        """
        if self._outcome_voting is None or not self._validator_address:
            return False
        try:
            return await self._with_failover(
                lambda: self._outcome_voting.functions.isValidator(  # type: ignore[union-attr]
                    self._w3.to_checksum_address(self._validator_address),
                ).call()
            )
        except Exception as e:
            log.error("is_registered_validator_failed", err=str(e))
            return None

    async def is_registered_validator_at(self, outcome_voting_address: str) -> bool | None:
        """Check if this validator is registered in an arbitrary OutcomeVoting contract.

        Used by the startup probe to cross-reference against the canonical OV
        address when the configured (.env) address reports not-registered —
        letting us tell the operator "your .env has a stale override" vs
        "your signer genuinely isn't bootstrapped yet".

        Returns True/False for a definitive answer, or None when the RPC call
        itself failed. Callers should treat None as "inconclusive" — don't
        escalate a flappy RPC to a stale-env diagnosis.
        """
        if not self._validator_address:
            return False
        try:
            contract = self._w3.eth.contract(
                address=self._w3.to_checksum_address(outcome_voting_address),
                abi=[
                    {
                        "inputs": [{"name": "validator", "type": "address"}],
                        "name": "isValidator",
                        "outputs": [{"name": "", "type": "bool"}],
                        "stateMutability": "view",
                        "type": "function",
                    }
                ],
            )
            return await self._with_failover(
                lambda: contract.functions.isValidator(
                    self._w3.to_checksum_address(self._validator_address),
                ).call()
            )
        except Exception as e:
            log.debug("is_registered_validator_at_failed", addr=outcome_voting_address, err=str(e)[:200])
            return None

    async def get_validators(self) -> list[str]:
        """Read the on-chain validator set from OutcomeVoting."""
        if self._outcome_voting is None:
            return []
        try:
            result = await self._with_failover(
                lambda: self._outcome_voting.functions.getValidators().call()  # type: ignore[union-attr]
            )
            return [str(addr) for addr in result]
        except Exception as e:
            log.error("get_validators_failed", err=str(e))
            return []

    async def batch_line_outcomes(
        self,
        line_hashes: list[bytes],
        confirmations: int = 2,
    ) -> list[int] | None:
        """v1747 Phase 4: read canonical line outcomes from LineOutcomeRegistry.

        Calls ``batchOutcomes(bytes32[]) returns (Outcome[])`` against the
        deployed registry. Returns the array of Outcome enum values
        (0=Pending, 1=Favorable, 2=Unfavorable, 3=Void).

        Returns None when:
          - the registry contract is not configured (pre-deploy era), OR
          - the RPC call itself fails (transport / provider flake).

        Callers in the MPC orchestrator MUST treat None as "abstain"
        — they MUST NOT fall back to local outcomes for consensus input,
        which is exactly the divergence bug v1747 exists to fix.

        ``confirmations`` reserved for future depth-of-finality enforcement
        (Base finalizes ~1-2 blocks; depth-2 reads protect against very
        rare 1-block reorgs). Currently the chain client batches this as
        a single ``call()`` and trusts the RPC; we'll layer block-depth
        in once the registry is deployed and we observe baseline reorg
        behavior on Sepolia.
        """
        if self._line_outcome_registry is None:
            return None
        if not line_hashes:
            return []
        try:
            result = await self._with_failover(
                lambda: self._line_outcome_registry.functions.batchOutcomes(  # type: ignore[union-attr]
                    list(line_hashes)
                ).call()
            )
            return [int(o) for o in result]
        except Exception as e:
            log.warning("batch_line_outcomes_failed", err=str(e)[:200], n=len(line_hashes))
            return None

    async def get_sync_nonce(self) -> int:
        """Read the current sync nonce from OutcomeVoting."""
        if self._outcome_voting is None:
            return 0
        try:
            return await self._with_failover(
                lambda: self._outcome_voting.functions.syncNonce().call()  # type: ignore[union-attr]
            )
        except Exception as e:
            log.error("get_sync_nonce_failed", err=str(e))
            return 0

    async def propose_sync(self, new_validators: list[str], nonce: int) -> str:
        """Propose a new validator set on-chain via OutcomeVoting.proposeSync(). Returns tx hash."""
        if self._outcome_voting is None:
            raise RuntimeError("OutcomeVoting contract not configured")

        checksum_addrs = [self._w3.to_checksum_address(addr) for addr in new_validators]
        return await self._send_tx(
            self._outcome_voting,
            "proposeSync",
            checksum_addrs,
            nonce,
            gas_limit=500_000,
        )

    # ─── P0-11 liveness-aware quorum (v1596+)

    async def ov_active_window(self) -> int:
        """Read OutcomeVoting.activeWindow. Zero means liveness-aware quorum is off."""
        if self._outcome_voting is None:
            return 0
        try:
            return int(await self._outcome_voting.functions.activeWindow().call())
        except Exception as e:
            log.debug("ov_active_window_failed", err=str(e))
            return 0

    async def ov_is_active(self, addr: str) -> bool:
        """Read OutcomeVoting.isActive(addr). True if within active window."""
        if self._outcome_voting is None:
            return False
        try:
            return bool(await self._outcome_voting.functions.isActive(self._w3.to_checksum_address(addr)).call())
        except Exception as e:
            log.debug("ov_is_active_failed", err=str(e))
            return False

    async def ov_last_active_block(self, addr: str) -> int:
        """Read OutcomeVoting.lastActiveBlock(addr)."""
        if self._outcome_voting is None:
            return 0
        try:
            return int(await self._outcome_voting.functions.lastActiveBlock(self._w3.to_checksum_address(addr)).call())
        except Exception as e:
            log.debug("ov_last_active_block_failed", err=str(e))
            return 0

    async def heartbeat(self) -> str:
        """Post a liveness heartbeat to OutcomeVoting. Returns tx hash.

        Cheap (~26k gas) no-op that ticks lastActiveBlock[msg.sender]. Used by
        the heartbeat_loop to keep this validator in the quorum denominator
        during periods without audit activity. Votes also tick liveness, so
        heartbeat is only load-bearing during dry spells.
        """
        if self._outcome_voting is None:
            raise RuntimeError("OutcomeVoting contract not configured")
        return await self._send_tx(self._outcome_voting, "heartbeat", gas_limit=80_000)

    async def close(self) -> None:
        """Close the underlying HTTP provider session."""
        provider = self._w3.provider
        if hasattr(provider, "_request_session") and provider._request_session:
            session = provider._request_session
            try:
                close_coro = session.aclose() if hasattr(session, "aclose") else session.close()
                await asyncio.wait_for(close_coro, timeout=5.0)
            except TimeoutError:
                log.warning("chain_client_close_timeout")
            except Exception as e:
                log.warning("chain_client_close_error", err=str(e))

    async def is_connected(self) -> bool:
        """Check Base chain RPC connectivity (tries all endpoints)."""
        for _ in range(len(self._rpc_urls)):
            try:
                await self._w3.eth.block_number
                return True
            except _FAILOVER_ERRORS:
                if not self._rotate_rpc():
                    break
            except Exception as e:
                log.warning("rpc_connection_failed", err=str(e))
                return False
        return False

    async def wait_for_receipt(
        self,
        tx_hash: str,
        *,
        timeout_s: float = 120.0,
        poll_interval_s: float = 2.0,
    ) -> dict[str, Any]:
        """Poll until a tx is mined, returning its receipt dict.

        MAINNET_BLOCKERS P0-09: settlement previously marked complete after
        `send_raw_transaction` returned, before the tx was actually mined.
        Dropped/reverted/reorged txs silently stranded audit batches. Callers
        that need "settled only if confirmed" semantics should await this and
        check `receipt["status"] == 1` before updating local state.

        Args:
            tx_hash: hex string (`0x...`) returned by `_send_tx`.
            timeout_s: overall deadline. Base block time ≈ 2s; 120s = ~60
                blocks of slack for RPC hiccups and inclusion delay.
            poll_interval_s: seconds between receipt polls.

        Returns:
            The receipt dict with `status`, `blockNumber`, `transactionHash`, etc.

        Raises:
            TimeoutError: if no receipt appears within `timeout_s`. Caller
                should treat as "not confirmed yet" (may still confirm later).
        """
        deadline = asyncio.get_event_loop().time() + timeout_s
        while True:
            try:
                receipt = await self._with_failover(lambda: self._w3.eth.get_transaction_receipt(tx_hash))
                if receipt is not None:
                    return dict(receipt)
            except Exception as e:
                # Receipt lookup is expected to miss (None) until mined; any
                # hard error here (RPC down) is worth noticing but not fatal
                # — we keep polling until the deadline.
                log.debug("receipt_poll_error", tx_hash=tx_hash, err=str(e)[:120])
            if asyncio.get_event_loop().time() >= deadline:
                raise TimeoutError(f"Receipt for {tx_hash} not mined within {timeout_s}s")
            await asyncio.sleep(poll_interval_s)

    async def verify_chain_id(self) -> None:
        """Assert the RPC's chain_id matches the configured BASE_CHAIN_ID.

        Runs at startup. Configured `chain_id` is what we sign against; if the
        RPC is actually pointing at a different chain, every signed tx silently
        drops on the wire (wrong-chain signatures never mine), and the validator
        appears healthy while its quorum contribution is zero. We must fail
        loud before the settlement loop runs.

        Raises:
            RuntimeError: if the RPC returns a chain_id different from the
                configured one. Message includes both values so the operator
                can fix the .env.
            Exception: propagates the underlying RPC error if the node is
                unreachable after failover across all configured URLs.
        """
        actual = await self._with_failover(lambda: self._w3.eth.chain_id)
        expected = self._chain_id
        if actual != expected:
            raise RuntimeError(
                f"RPC chain_id mismatch: configured BASE_CHAIN_ID={expected} "
                f"but RPC at {self.rpc_url} reports chain_id={actual}. "
                f"Validator would sign wrong-chain transactions that silently "
                f"drop, reducing effective signer quorum. Fix .env and restart."
            )
        log.info("chain_id_verified", chain_id=actual, rpc=_sanitize_url(self.rpc_url))

    @property
    def rpc_url(self) -> str:
        """Current active RPC URL."""
        return self._rpc_urls[self._rpc_index]

    @property
    def rpc_url_count(self) -> int:
        """Number of configured RPC endpoints."""
        return len(self._rpc_urls)
