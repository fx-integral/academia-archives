"""Metagraph-synced validator set management.

Discovers peer validators via the Bittensor metagraph, queries each for their
Base (EVM) address via ``GET /v1/identity``, and proposes the resulting set
on-chain via ``OutcomeVoting.proposeSync()``. When 2/3+ of current validators
agree on the same proposed set, it atomically replaces the old one.
"""

from __future__ import annotations

import httpx
import structlog

from djinn_validator.bt.neuron import DjinnValidator
from djinn_validator.chain.contracts import ChainClient

log = structlog.get_logger()

# Timeout for querying a peer's /v1/identity endpoint
_IDENTITY_TIMEOUT = 5.0

# Minimum alpha stake to be considered a real validator (filters noise from
# neurons that happen to have validator permits but aren't running Djinn)
_MIN_STAKE_ALPHA = 1000


class ValidatorSetSyncer:
    """Discovers peer validators and proposes on-chain set changes."""

    def __init__(
        self,
        chain_client: ChainClient,
        neuron: DjinnValidator,
    ) -> None:
        self._chain = chain_client
        self._neuron = neuron

    async def sync_once(self) -> None:
        """One round of: read metagraph -> discover peers -> propose if changed."""
        if self._neuron.metagraph is None:
            log.debug("validator_sync_skip", reason="no metagraph")
            return

        if not self._chain.can_write:
            log.debug("validator_sync_skip", reason="chain client cannot write")
            return

        # 1. Get current on-chain set
        on_chain = await self._chain.get_validators()
        on_chain_sorted = sorted(addr.lower() for addr in on_chain)

        # 2. Discover peers from metagraph
        discovered = await self._discover_peer_addresses()
        if not discovered:
            log.warning("validator_sync_no_peers", msg="No peer addresses discovered")
            return

        discovered_sorted = sorted(addr.lower() for addr in discovered)

        # 3. Compare sets — additions-only sync (P0-01 root cause v1640).
        #
        # Previously: any diff (additions OR removals) triggered a proposal
        # of the discovered set verbatim. When five operators each had
        # slightly different metagraph views — UID 0 unreachable from
        # operator A right now, UID 213 unreachable from operator B — they
        # each proposed a DIFFERENT 4-validator subset of the on-chain 5.
        # No proposal hash got 2/3 quorum; every signer used their vote
        # at nonce N; sync jammed. On 2026-05-01 we observed nonce=11
        # with 5/5 hasSyncVoted=true and 0 AuditSettled across 28h
        # because vote-submit is gated on stable validator set.
        #
        # Fix: only propose ADDITIONS. Removals require explicit owner
        # action via timelock. This makes the protocol fail-closed under
        # transient peer-discovery failures.
        union_sorted = sorted(set(on_chain_sorted) | set(discovered_sorted))
        if on_chain_sorted == union_sorted:
            log.debug(
                "validator_sync_no_additions",
                on_chain=len(on_chain_sorted),
                discovered=len(discovered_sorted),
            )
            return

        # 4. Propose the union (current set + any new additions).
        nonce = await self._chain.get_sync_nonce()

        # Use checksum addresses for the proposal (sorted by lowercase to
        # match contract-side hashing).
        from web3 import Web3

        checksum_sorted = sorted(
            [Web3.to_checksum_address(addr) for addr in union_sorted],
            key=lambda a: a.lower(),
        )

        try:
            tx_hash = await self._chain.propose_sync(checksum_sorted, nonce)
            log.info(
                "validator_sync_proposed",
                on_chain=len(on_chain_sorted),
                proposed=len(checksum_sorted),
                nonce=nonce,
                tx_hash=tx_hash,
            )
        except Exception as e:
            err_str = str(e)
            if "StaleNonce" in err_str or "AlreadySyncVoted" in err_str:
                log.debug("validator_sync_already_voted", reason=err_str[:80])
            else:
                log.error("validator_sync_propose_failed", err=err_str)

    async def _discover_peer_addresses(self) -> list[str]:
        """Query metagraph for validator UIDs and fetch their Base addresses."""
        metagraph = self._neuron.metagraph
        if metagraph is None:
            return []

        n = DjinnValidator._safe_item(metagraph.n)
        addresses: list[str] = []

        async with httpx.AsyncClient(timeout=_IDENTITY_TIMEOUT) as client:
            for uid in range(n):
                permit = metagraph.validator_permit[uid]
                is_validator = bool(permit.item() if hasattr(permit, "item") else permit)
                if not is_validator:
                    continue

                stake = DjinnValidator._safe_item(metagraph.S[uid])
                if stake < _MIN_STAKE_ALPHA:
                    continue

                axon = metagraph.axons[uid]
                ip = axon.ip
                port = axon.port

                if not ip or ip == "0.0.0.0":
                    continue

                addr = await self._fetch_identity(client, ip, port)
                if addr:
                    addresses.append(addr)

        return addresses

    async def _fetch_identity(
        self,
        client: httpx.AsyncClient,
        ip: str,
        port: int,
    ) -> str | None:
        """Fetch a peer's Base address via GET /v1/identity.

        Note: previously filtered out version="999" peers as a stale-code
        proxy, but "999" is just the VERSION-file fallback sentinel for
        non-git installs (committed in 3d82d97f) — it doesn't reliably
        indicate stale code, only stale version-detection. v1625 ships a
        self-heal in __init__.py that writes the git-described version back
        to VERSION on every successful import, so honest operators stop
        reporting "999" after one process restart. Excluding "999" here
        would unfairly drop them. If a peer is genuinely on pre-v1616 code
        and can't vote, removeValidator via timelock is the correct lever.
        """
        url = f"http://{ip}:{port}/v1/identity"
        try:
            resp = await client.get(url)
            if resp.status_code == 200:
                data = resp.json()
                base_addr = data.get("base_address", "")
                if base_addr and base_addr != "0x" + "0" * 40:
                    return base_addr
            return None
        except Exception:
            # Peer unreachable — skip silently
            return None
