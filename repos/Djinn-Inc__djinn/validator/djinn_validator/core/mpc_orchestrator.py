"""MPC orchestration for the purchase flow.

Coordinates the full secure MPC protocol across multiple validators:
1. Discovers peer validators from the Bittensor metagraph
2. Creates an MPC session with Beaver triples
3. Distributes triple shares to peers via HTTP
4. Collects contributions and computes the result
5. Broadcasts the result to all participants

Falls back to single-validator prototype mode when:
- Bittensor is not connected (dev mode)
- Fewer than threshold validators are reachable
"""

from __future__ import annotations

import asyncio
import ipaddress
import json
import os
import secrets
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import httpx
import structlog

from djinn_validator.core.mpc import (
    BeaverTriple,
    DistributedParticipantState,
    MPCResult,
    _split_secret_at_points,
    check_availability,
    compute_local_contribution,
    reconstruct_at_zero,
    secure_check_availability,
)
from djinn_validator.core.mpc_coordinator import MPCCoordinator, SessionStatus
from djinn_validator.core.ot_network import (
    OTReceiverNotReadyError,
    OTTripleGenState,
    deserialize_choices,
    deserialize_dh_public_key,
    deserialize_transfers,
    serialize_choices,
    serialize_dh_public_key,
    serialize_transfers,
)
from djinn_validator.core.spdz import (
    AuthenticatedParticipantState,
    AuthenticatedShare,
    verify_mac_opening,
)
from djinn_validator.utils.circuit_breaker import CircuitBreaker
from djinn_validator.utils.crypto import BN254_PRIME, Share

if TYPE_CHECKING:
    from djinn_validator.bt.neuron import DjinnValidator

log = structlog.get_logger()

# Timeout for inter-validator HTTP calls (configurable via env).
# 2026-05-04: bumped 20s → 45s. Cohort 2 fleet diagnostics showed
# UID 1 and UID 86 each hit 21 ReadTimeout protocol_failed events
# on batch MPC rounds while the audit_set was fully converged
# (10/10/10 across 4 reachable validators). The MPC compute_gate /
# accumulate / open rounds each do non-trivial work (Beaver multiplications,
# OT rounds) and intermittently exceed 20s under fleet load. Pushing
# the per-call ceiling to 45s while keeping GATHER_TIMEOUT = 3x = 135s
# absorbs peer compute variance without architectural change. Revert
# via MPC_PEER_TIMEOUT=20.0 in .env if it regresses anything.
PEER_TIMEOUT = float(os.getenv("MPC_PEER_TIMEOUT", "45.0"))

# Feature flag: when enabled, availability checks use the masked polynomial
# membership protocol (O(log k) rounds) instead of the sequential-gate
# Beaver protocol (O(k) rounds). See mpc_membership.py for the protocol
# and its security argument. Default off during rollout.
USE_MEMBERSHIP_V2 = os.getenv("DJINN_MPC_MEMBERSHIP_V2", "0").lower() in ("1", "true", "yes")


def _is_public_ip(ip_str: str) -> bool:
    """Reject private, loopback, reserved, and link-local addresses (SSRF protection)."""
    try:
        addr = ipaddress.ip_address(ip_str)
        return addr.is_global
    except ValueError:
        return False


# Timeout for gather operations (covers retries + backoff for concurrent peers)
GATHER_TIMEOUT = PEER_TIMEOUT * 3

# Version filtering removed: all validators with a reachable health
# endpoint are eligible MPC peers regardless of reported version.


@dataclass(frozen=True)
class ShadowSettleSubmitData:
    """Fields from a successful distributed shadow settlement run, shaped
    to feed directly into OutcomeVoting.submitVote when local trusted-
    dealer settlement cannot run (e.g., under 2-of-2 Shamir fan-out).

    ``total_notional`` is computed from PurchaseInputs.notional summed
    across the batch. This over-counts VOID signals relative to the
    local AuditResult path (which excludes them per CF-06). The
    distributed MPC circuit does not expose per-signal void status, so
    splitting this out would require an additional aggregate round.
    Gated behind ``DJINN_FF_BATCH_SETTLEMENT_HTTP_SUBMIT`` so operators
    can cut it over only after the approximation has been validated on
    testnet.
    """

    genius: str
    idiot: str
    cycle: int
    quality_score: int
    total_notional: int
    purchase_ids: list[int]
    session_id: str
    purchase_count: int


class MPCOrchestrator:
    """Orchestrates MPC sessions for signal availability checks.

    Used by the purchase endpoint to run the secure MPC protocol
    across multiple validators, falling back to single-validator
    prototype mode when necessary.
    """

    _PEER_RETRIES = 2
    _RETRY_BACKOFF = 0.3  # seconds, doubles each attempt

    def __init__(
        self,
        coordinator: MPCCoordinator,
        neuron: DjinnValidator | None = None,
        threshold: int = 7,
        ot_dh_group: Any | None = None,
        ot_field_prime: int | None = None,
        chain_client: Any | None = None,
        encryption_privkey: bytes | None = None,
        signer_address: str | None = None,
        outcome_attestor: Any | None = None,
        audit_set_store: Any | None = None,
    ) -> None:
        self._coordinator = coordinator
        self._neuron = neuron
        self._threshold = threshold
        self._ot_dh_group = ot_dh_group
        self._ot_field_prime = ot_field_prime
        # v1443: used by _prefetch_missing_purchase_odds_from_peers to
        # authenticate peer-supplied BPA/WPA vectors against the
        # on-chain purchaseBpaRoot/purchaseWpaRoot commitments. When
        # None the peer-backfill refuses to record (fail-closed).
        self._chain_client = chain_client
        # v1670: share recovery (Phase 5). When both are set, the orchestrator
        # pulls encrypted forwarding shares from peers before assembling
        # each audit batch. None disables the path (legacy behavior).
        self._encryption_privkey = encryption_privkey
        self._signer_address = signer_address
        # v1671: outcome recovery. Pulls resolved outcomes from peers for
        # signals whose outcomes haven't yet resolved locally. None disables
        # (the orchestrator falls back to push-only gossip).
        self._outcome_attestor = outcome_attestor
        # v1699: pre-MPC hasVoted gate. When set, the orchestrator can
        # mark_settled on detection of a finalized batchKey so the audit
        # set stops bouncing on every cycle. None disables the mark_settled
        # side-effect (the gate still fires; it just doesn't clean up).
        self._audit_set_store = audit_set_store
        limits = httpx.Limits(max_keepalive_connections=20, max_connections=100)
        self._http = httpx.AsyncClient(timeout=PEER_TIMEOUT, limits=limits)
        self._peer_breakers: dict[int, CircuitBreaker] = {}

    async def close(self) -> None:
        """Release the shared HTTP client."""
        await self._http.aclose()

    def prune_stale_breakers(self, active_uids: set[int]) -> int:
        """Remove circuit breakers for UIDs no longer on the metagraph."""
        stale = [uid for uid in self._peer_breakers if uid not in active_uids]
        for uid in stale:
            del self._peer_breakers[uid]
        return len(stale)

    def _mark_session_failed(self, session: Any) -> None:
        """Mark an MPC session as FAILED to prevent resource leaks."""
        if session.status not in (SessionStatus.COMPLETE, SessionStatus.FAILED):
            with self._coordinator._lock:
                session.status = SessionStatus.FAILED
            log.info("mpc_session_failed_cleanup", session_id=session.session_id)

    def _get_peer_breaker(self, peer_uid: int) -> CircuitBreaker:
        """Get or create a circuit breaker for a peer validator."""
        if peer_uid not in self._peer_breakers:
            self._peer_breakers[peer_uid] = CircuitBreaker(
                name=f"peer_{peer_uid}",
                failure_threshold=3,
                recovery_timeout=20.0,
            )
        return self._peer_breakers[peer_uid]

    async def _peer_request(
        self,
        method: str,
        url: str,
        *,
        peer_uid: int | None = None,
        **kwargs: Any,
    ) -> httpx.Response:
        """HTTP request with circuit breaker, retry, and exponential backoff.

        Retries on transport errors and 5xx server errors.
        Propagates request_id for distributed tracing.
        """
        # Check circuit breaker for this peer
        if peer_uid is not None:
            breaker = self._get_peer_breaker(peer_uid)
            if not breaker.allow_request():
                raise httpx.ConnectError(f"Circuit breaker open for peer {peer_uid}")

        # Propagate request ID for distributed tracing
        headers = kwargs.pop("headers", {})
        try:
            ctx = structlog.contextvars.get_contextvars()
            if "request_id" in ctx:
                headers["X-Request-ID"] = ctx["request_id"]
        except Exception as e:
            log.debug("request_id_propagation_failed", error=str(e))

        # Pre-serialize JSON body so the bytes we sign match the bytes sent.
        # Previously we signed json.dumps(kwargs["json"]) but httpx's json=
        # parameter may serialize differently, causing signature mismatch (401).
        if "json" in kwargs:
            serialized = json.dumps(kwargs.pop("json"), separators=(",", ":")).encode()
            kwargs["content"] = serialized
            headers["Content-Type"] = "application/json"

        # v1561: sign headers INSIDE the retry loop (nonce must be fresh per
        # attempt). Previously we signed once before the retry loop, which
        # meant timeout-and-retry and 5xx-and-retry both replayed the SAME
        # nonce. Peers cache nonces for 120s and reject replays with 401
        # "Nonce already used" — which (a) masked the real failure (e.g.
        # peer 503 from a disabled feature flag) and (b) ensured a retry
        # never succeeded even if the transient issue cleared.
        _body = b""
        if "content" in kwargs:
            _body = kwargs["content"] if isinstance(kwargs["content"], bytes) else str(kwargs["content"]).encode()
        elif "data" in kwargs:
            _body = kwargs["data"] if isinstance(kwargs["data"], bytes) else str(kwargs["data"]).encode()

        from urllib.parse import urlparse as _urlparse

        _endpoint_path = _urlparse(url).path

        def _build_attempt_headers() -> dict[str, str]:
            h = dict(headers)
            if self._neuron is not None and hasattr(self._neuron, "wallet") and self._neuron.wallet is not None:
                try:
                    from djinn_validator.api.middleware import create_signed_headers

                    h.update(create_signed_headers(_endpoint_path, _body, self._neuron.wallet))
                except Exception as e:
                    log.warning("peer_request_signing_failed", url=url[:80], error=str(e))
                    raise httpx.ConnectError(f"Cannot sign peer request: {e}")
            elif self._neuron is None:
                log.warning("peer_request_no_neuron", url=url[:80])
            return h

        last_exc: Exception | None = None
        for attempt in range(self._PEER_RETRIES + 1):
            kwargs["headers"] = _build_attempt_headers()
            try:
                resp = await getattr(self._http, method)(url, **kwargs)
                if resp.status_code < 500:
                    if peer_uid is not None:
                        self._get_peer_breaker(peer_uid).record_success()
                    return resp
                last_exc = httpx.HTTPStatusError(
                    f"Server error {resp.status_code}",
                    request=resp.request,
                    response=resp,
                )
            except httpx.HTTPError as e:
                last_exc = e
            if attempt < self._PEER_RETRIES:
                await asyncio.sleep(self._RETRY_BACKOFF * (2**attempt))
        if peer_uid is not None:
            self._get_peer_breaker(peer_uid).record_failure()
        raise last_exc  # type: ignore[misc]

    def _self_loopback_url(self) -> str | None:
        """Return the loopback URL for addressing self over HTTP in MPC.

        v1685: pre-fix, ``try_shadow_distributed_settlement`` built its
        own participant URL from the metagraph axon's external IP. Many
        validator hosts cannot route to themselves via their own external
        IP because the upstream NAT or router does not reflect outbound
        connections back inside (NAT hairpin). The coordinator's self-init
        HTTP call would time out, the participant slot would never accept
        its batch, and the whole session would abort.

        Loopback (127.0.0.1) bypasses the NAT entirely. The port comes
        from the metagraph axon publication, so it stays in sync with
        whatever externally-visible port the validator advertises. The
        receiver-side auth (validate_signed_request) is hotkey-based,
        not IP-based, so a loopback request authenticates the same as a
        public-IP request.

        Returns ``None`` when the neuron isn't ready (no metagraph yet).
        """
        if self._neuron is None or self._neuron.metagraph is None:
            return None
        try:
            my_axon = self._neuron.metagraph.axons[self._neuron.uid]
            if my_axon.port:
                return f"http://127.0.0.1:{my_axon.port}"
        except Exception as e:
            log.debug("shadow_settle_self_url_lookup_failed", error=str(e)[:100])
        return None

    def _get_peer_validators(self) -> list[dict[str, Any]]:
        """Discover peer validator addresses from the metagraph.

        Returns list of {uid, hotkey, ip, port, url} for each validator.
        Filters to validators with compatible MPC implementations.
        """
        if self._neuron is None or self._neuron.metagraph is None:
            return []

        peers = []
        metagraph = self._neuron.metagraph
        for uid in range(metagraph.n.item()):
            if not metagraph.validator_permit[uid].item():
                continue
            if uid == self._neuron.uid:
                continue  # Skip ourselves

            axon = metagraph.axons[uid]
            if not axon.ip or axon.ip == "0.0.0.0":
                continue
            if not _is_public_ip(axon.ip):
                log.warning("peer_private_ip_skipped", uid=uid, ip=axon.ip)
                continue

            peers.append(
                {
                    "uid": uid,
                    "hotkey": metagraph.hotkeys[uid],
                    "ip": axon.ip,
                    "port": axon.port,
                    "url": f"http://{axon.ip}:{axon.port}",
                }
            )

        return peers

    async def _collect_peer_share_xs(
        self,
        peers: list[dict[str, Any]],
        signal_id: str,
    ) -> list[int]:
        """Request share x-coordinates from peer validators for a signal.

        Returns the list of peer share x-values (evaluation points) for
        validators that hold a share of this signal. The y-values are
        never transmitted — they stay local to each validator and are
        used only within the MPC protocol.
        """
        xs = []
        for peer in peers:
            try:
                resp = await self._peer_request(
                    "get",
                    f"{peer['url']}/v1/signal/{signal_id}/share_info",
                    peer_uid=peer["uid"],
                )
                if resp.status_code == 200:
                    data = resp.json()
                    xs.append(data["share_x"])
            except (httpx.HTTPError, KeyError, ValueError, json.JSONDecodeError) as e:
                log.warning(
                    "peer_share_request_failed",
                    peer_uid=peer["uid"],
                    error=str(e),
                )
        return xs

    async def check_availability(
        self,
        signal_id: str,
        local_share: Share,
        available_indices: set[int],
        local_shares: list[Share] | None = None,
        threshold_override: int | None = None,
        precomputed_triples: list[Any] | None = None,
    ) -> MPCResult:
        """Run the MPC availability check.

        If enough shares are available locally (e.g. shared DB on testnet),
        uses secure_check_availability directly. Otherwise attempts multi-
        validator MPC, falling back to single-validator prototype.

        Args:
            threshold_override: Per-signal threshold declared at creation time.
                Overrides the global default to handle signals created during
                bootstrap with lower thresholds.
            precomputed_triples: Beaver triples pre-generated at signal creation.
                If provided, skips the expensive OT setup during purchase.
        """
        from djinn_validator.api.metrics import MPC_DURATION, MPC_ERRORS, MPC_SESSIONS

        start = time.monotonic()
        threshold = threshold_override if threshold_override is not None else self._threshold

        # If we have enough shares locally, use them directly for a secure check.
        # This handles testnet setups where all shares are co-located in one DB.
        all_local = local_shares or [local_share]
        if len(all_local) >= threshold:
            log.info(
                "mpc_local_shares_mode",
                signal_id=signal_id,
                local_shares=len(all_local),
                threshold=threshold,
            )
            MPC_SESSIONS.labels(mode="local_shares").inc()
            result = secure_check_availability(
                shares=all_local,
                available_indices=available_indices,
                threshold=threshold,
            )
            MPC_DURATION.labels(mode="local_shares").observe(time.monotonic() - start)
            return result

        peers = self._get_peer_validators()

        if not peers:
            # Dev/single-validator mode: no peers discovered.
            # This path is ONLY reached when neuron is None (dev) or no validators
            # are on the metagraph. The single-validator prototype check uses
            # threshold=1 reconstruction — acceptable here because there is no
            # multi-party trust boundary (only one party holds a share).
            # The secrecy guarantee applies to the DISTRIBUTED path where
            # the coordinator must never access peer triple shares or z_i.
            log.info(
                "mpc_single_validator_mode",
                signal_id=signal_id,
                reason="no peers discovered",
            )
            MPC_SESSIONS.labels(mode="single_validator").inc()
            result = self._single_validator_check(local_share, available_indices)
            MPC_DURATION.labels(mode="single_validator").observe(time.monotonic() - start)
            return result

        # Not enough local shares — run distributed protocol via HTTP.
        # Route through the O(log k) masked-polynomial path when the
        # feature flag is enabled; otherwise stay on the legacy O(k)
        # sequential-gate protocol.
        if USE_MEMBERSHIP_V2:
            MPC_SESSIONS.labels(mode="distributed_membership_v2").inc()
            result = await self._distributed_mpc_membership(
                signal_id,
                local_share,
                available_indices,
                peers,
                threshold=threshold,
            )
            if result is not None:
                MPC_DURATION.labels(mode="distributed_membership_v2").observe(
                    time.monotonic() - start,
                )
                return result
        else:
            MPC_SESSIONS.labels(mode="distributed").inc()
            result = await self._distributed_mpc(
                signal_id,
                local_share,
                available_indices,
                peers,
                threshold=threshold,
                precomputed_triples=precomputed_triples,
            )
            if result is not None:
                MPC_DURATION.labels(mode="distributed").observe(time.monotonic() - start)
                return result

        # Distributed MPC failed — return unavailable as a fail-safe.
        # In production, we never fall back to secret reconstruction because
        # the coordinator must not learn the secret index.
        log.error(
            "mpc_distributed_failed",
            signal_id=signal_id,
            reason="distributed MPC failed — returning unavailable as fail-safe",
        )
        MPC_ERRORS.labels(reason="distributed_failed").inc()
        MPC_DURATION.labels(mode="distributed_failed").observe(time.monotonic() - start)
        return MPCResult(available=False, participating_validators=0)

    async def _distributed_mpc(
        self,
        signal_id: str,
        local_share: Share,
        available_indices: set[int],
        peers: list[dict[str, Any]],
        threshold: int | None = None,
        precomputed_triples: list[Any] | None = None,
    ) -> MPCResult | None:
        """Run the distributed MPC protocol via HTTP.

        Supports both semi-honest (basic Beaver) and malicious (SPDZ authenticated)
        modes. The mode is determined by USE_AUTHENTICATED_MPC env var or the
        coordinator's create_session() call.

        Full protocol:
        1. Generate random mask r and split into shares
        2. Create session with Beaver triples (optionally with MAC authentication)
        3. Send /v1/mpc/init to all peers with their triple shares + r shares
        4. For each multiplication gate, collect (d_i, e_i) from all peers
        5. In authenticated mode: verify MACs on opened d, e values
        6. Reconstruct opened d, e and feed into next gate
        7. Open final result and broadcast to peers
        """
        p = BN254_PRIME
        my_x = local_share.x
        sorted_avail = sorted(available_indices)
        n_gates = len(sorted_avail)
        t = threshold if threshold is not None else self._threshold

        if n_gates == 0:
            return MPCResult(available=False, participating_validators=1, failure_reason="no_available_indices")

        # Collect actual Shamir share x-coordinates from peers in parallel.
        # The share_x values are assigned at signal creation time (1, 2, 3, ...)
        # and differ from metagraph UIDs. Using UID+1 would break Lagrange
        # interpolation since the secret was split at different evaluation points.
        peer_x_map: dict[int, int] = {}  # peer UID -> share_x

        async def _lookup_share_x(peer: dict[str, Any]) -> tuple[int, int] | None:
            try:
                resp = await self._peer_request(
                    "get",
                    f"{peer['url']}/v1/signal/{signal_id}/share_info",
                    peer_uid=peer["uid"],
                )
                if resp is not None and resp.status_code == 200:
                    data = resp.json()
                    return peer["uid"], data["share_x"]
            except (httpx.HTTPError, KeyError, ValueError, AttributeError) as e:
                log.debug("peer_share_x_lookup_failed", peer_uid=peer["uid"], error=str(e))
            return None

        # Terminate early once we have enough peers (t-1 needed since we are one).
        # This avoids waiting 30s for unreachable validators when 2 fast ones respond.
        needed_peers = t - 1  # we (coordinator) count as one participant
        tasks = [asyncio.create_task(_lookup_share_x(p)) for p in peers]
        if tasks:
            deadline = asyncio.get_running_loop().time() + GATHER_TIMEOUT
            pending = set(tasks)
            while pending:
                remaining = deadline - asyncio.get_running_loop().time()
                if remaining <= 0:
                    break
                done_batch, pending = await asyncio.wait(
                    pending,
                    timeout=remaining,
                    return_when=asyncio.FIRST_COMPLETED,
                )
                for dtask in done_batch:
                    try:
                        res = dtask.result()
                        if isinstance(res, tuple) and res is not None:
                            peer_x_map[res[0]] = res[1]
                    except Exception:
                        pass
                if len(peer_x_map) >= needed_peers:
                    break
            # Cancel any still-running lookups
            for ptask in pending:
                ptask.cancel()
            if pending:
                log.info(
                    "peer_share_x_early_termination",
                    found=len(peer_x_map),
                    needed=needed_peers,
                    cancelled=len(pending),
                )

        # Only keep peers that hold a share for this signal
        peers = [p for p in peers if p["uid"] in peer_x_map]

        raw_xs = [my_x] + [peer_x_map[p["uid"]] for p in peers]
        if len(raw_xs) != len(set(raw_xs)):
            log.warning("duplicate_participant_x", raw=raw_xs, unique=list(set(raw_xs)))
        participant_xs = sorted(set(x for x in raw_xs if 1 <= x <= 255))

        log.info(
            "mpc_participant_summary",
            signal_id=signal_id[:20],
            my_x=my_x,
            peer_x_map=peer_x_map,
            participant_xs=participant_xs,
            threshold=t,
            total_peers_discovered=len(self._get_peer_validators()),
        )

        if len(participant_xs) < t:
            from djinn_validator.api.metrics import MPC_ERRORS

            MPC_ERRORS.labels(reason="insufficient_peers").inc()
            breaker_info = {
                uid: self._get_peer_breaker(uid).allow_request() for uid in list(self._peer_breakers.keys())[:10]
            }
            log.warning(
                "insufficient_mpc_participants",
                available=len(participant_xs),
                threshold=t,
                my_x=my_x,
                peer_x_map=peer_x_map,
                n_peers_checked=len(peers) if "peers" in dir() else 0,
                breaker_sample=breaker_info,
            )
            return MPCResult(
                available=False,
                participating_validators=len(participant_xs),
                failure_reason=f"insufficient_peers:{len(participant_xs)}/{t}",
            )

        # Generate random mask r (nonzero)
        r = secrets.randbelow(p - 1) + 1
        r_shares = _split_secret_at_points(r, participant_xs, t, p)
        r_share_map = {s.x: s.y for s in r_shares}

        # Use pre-computed triples if available (generated at signal creation time).
        # These arrive as raw (a, b, c) tuples and need to be Shamir-split
        # at the actual participant x-coordinates.
        pre_generated_triples: list[BeaverTriple] | None = None
        if precomputed_triples and len(precomputed_triples) >= n_gates:
            log.info("using_precomputed_triples", signal_id=signal_id[:20], count=len(precomputed_triples))
            split_triples = []
            for raw in precomputed_triples[:n_gates]:
                if isinstance(raw, BeaverTriple):
                    split_triples.append(raw)
                else:
                    a_val, b_val, c_val = raw
                    split_triples.append(
                        BeaverTriple(
                            a_shares=tuple(_split_secret_at_points(a_val, participant_xs, t, p)),
                            b_shares=tuple(_split_secret_at_points(b_val, participant_xs, t, p)),
                            c_shares=tuple(_split_secret_at_points(c_val, participant_xs, t, p)),
                        )
                    )
            pre_generated_triples = split_triples

        # OT-based Beaver triple generation is the fallback for 2-party MPC.
        use_network_ot = os.getenv("USE_NETWORK_OT", "true").lower() not in ("0", "false", "no")
        if pre_generated_triples is None and use_network_ot and len(peers) == 1:
            ot_session_id = f"ot-{signal_id}-{secrets.token_hex(4)}"
            pre_generated_triples = await self._generate_ot_triples_via_network(
                session_id=ot_session_id,
                peer=peers[0],
                n_triples=n_gates,
                participant_xs=participant_xs,
                my_x=my_x,
                dh_group=self._ot_dh_group,
                field_prime=self._ot_field_prime or BN254_PRIME,
            )
            if pre_generated_triples is None:
                from djinn_validator.api.metrics import MPC_ERRORS

                MPC_ERRORS.labels(reason="ot_setup_failure").inc()
                log.warning(
                    "network_ot_failed_fallback",
                    signal_id=signal_id,
                    reason="distributed OT triple generation failed, using local generation",
                )

        # Create MPC session with Beaver triples
        session = self._coordinator.create_session(
            signal_id=signal_id,
            available_indices=sorted_avail,
            coordinator_x=my_x,
            participant_xs=participant_xs,
            threshold=t,
            pre_generated_triples=pre_generated_triples,
        )

        is_auth = session.is_authenticated

        # For authenticated mode: create authenticated r shares and secret shares
        auth_r_map: dict[int, AuthenticatedShare] = {}
        auth_secret_map: dict[int, AuthenticatedShare] = {}
        if is_auth:
            # SECURITY: mac_alpha was removed from session state (C-6 audit finding).
            # The global MAC key must never be stored in a single location.
            # Authenticated MPC requires pre-authenticated shares created at
            # signal submission time. The coordinator must NOT reconstruct
            # the secret, as doing so defeats the purpose of MPC. Until the
            # Genius creates authenticated shares during signal commitment,
            # the authenticated mode is not available.
            self._mark_session_failed(session)
            raise RuntimeError(
                "Authenticated MPC disabled: global MAC key not configured. "
                "mac_alpha was removed from session state (C-6 audit finding); "
                "pre-authenticated shares from signal commitment are required."
            )

        # Build our own participant state
        if is_auth:
            my_auth_triples = self._coordinator.get_authenticated_triple_shares(
                session.session_id,
                my_x,
            )
            my_mac_key = self._coordinator.get_mac_key_share(session.session_id, my_x)
            if my_auth_triples is None or my_mac_key is None:
                self._mark_session_failed(session)
                return None
            my_state_auth = AuthenticatedParticipantState(
                validator_x=my_x,
                secret_share=auth_secret_map[my_x],
                r_share=auth_r_map[my_x],
                alpha_share=my_mac_key,
                available_indices=sorted_avail,
                triple_a=[AuthenticatedShare(x=my_x, y=ts["a"]["y"], mac=ts["a"]["mac"]) for ts in my_auth_triples],
                triple_b=[AuthenticatedShare(x=my_x, y=ts["b"]["y"], mac=ts["b"]["mac"]) for ts in my_auth_triples],
                triple_c=[AuthenticatedShare(x=my_x, y=ts["c"]["y"], mac=ts["c"]["mac"]) for ts in my_auth_triples],
            )
        else:
            my_triples = self._coordinator.get_triple_shares_for_participant(
                session.session_id,
                my_x,
            )
            if my_triples is None:
                self._mark_session_failed(session)
                return None
            my_state_basic = DistributedParticipantState(
                validator_x=my_x,
                secret_share_y=local_share.y,
                r_share_y=r_share_map[my_x],
                available_indices=sorted_avail,
                triple_a=[ts["a"] for ts in my_triples],
                triple_b=[ts["b"] for ts in my_triples],
                triple_c=[ts["c"] for ts in my_triples],
            )

        # Distribute session invitations with triple shares + r shares
        accepted_peers: list[dict[str, Any]] = []

        async def _init_peer(
            peer: dict[str, Any],
        ) -> dict[str, Any] | None:
            peer_x = peer_x_map[peer["uid"]]
            init_payload: dict[str, Any] = {
                "session_id": session.session_id,
                "signal_id": signal_id,
                "available_indices": sorted_avail,
                "coordinator_x": my_x,
                "participant_xs": participant_xs,
                "threshold": t,
                "authenticated": is_auth,
            }

            if is_auth:
                auth_ts = self._coordinator.get_authenticated_triple_shares(
                    session.session_id,
                    peer_x,
                )
                mac_key = self._coordinator.get_mac_key_share(session.session_id, peer_x)
                peer_r_auth = auth_r_map.get(peer_x)
                peer_secret_auth = auth_secret_map.get(peer_x)
                if auth_ts is None or mac_key is None or peer_r_auth is None or peer_secret_auth is None:
                    return None
                init_payload["auth_triple_shares"] = [
                    {comp: {k: hex(v) for k, v in share.items()} for comp, share in ts.items()} for ts in auth_ts
                ]
                init_payload["alpha_share"] = hex(mac_key.alpha_share)
                init_payload["auth_r_share"] = {"y": hex(peer_r_auth.y), "mac": hex(peer_r_auth.mac)}
                init_payload["auth_secret_share"] = {"y": hex(peer_secret_auth.y), "mac": hex(peer_secret_auth.mac)}
                init_payload["r_share_y"] = hex(peer_r_auth.y)
                init_payload["triple_shares"] = []  # Empty for auth mode
            else:
                triple_shares = self._coordinator.get_triple_shares_for_participant(
                    session.session_id,
                    peer_x,
                )
                peer_r = r_share_map.get(peer_x)
                if triple_shares is None or peer_r is None:
                    return None
                init_payload["triple_shares"] = [{k: hex(v) for k, v in ts.items()} for ts in triple_shares]
                init_payload["r_share_y"] = hex(peer_r)

            try:
                t0 = time.monotonic()
                resp = await self._peer_request(
                    "post",
                    f"{peer['url']}/v1/mpc/init",
                    peer_uid=peer["uid"],
                    json=init_payload,
                )
                elapsed = time.monotonic() - t0
                if resp.status_code == 200 and resp.json().get("accepted"):
                    log.info("mpc_init_accepted", peer_uid=peer["uid"], elapsed_ms=round(elapsed * 1000))
                    return peer
                else:
                    log.warning(
                        "mpc_init_rejected",
                        peer_uid=peer["uid"],
                        status=resp.status_code,
                        body=resp.text[:200],
                        elapsed_ms=round(elapsed * 1000),
                    )
            except (httpx.HTTPError, KeyError, ValueError, json.JSONDecodeError) as e:
                log.warning(
                    "mpc_init_failed",
                    peer_uid=peer["uid"],
                    error_type=type(e).__name__,
                    error=str(e)[:200],
                    elapsed_ms=round((time.monotonic() - t0) * 1000) if "t0" in dir() else -1,
                )
            return None

        init_tasks = [asyncio.create_task(_init_peer(peer)) for peer in peers]
        results: list[Any] = []
        if init_tasks:
            done, pending = await asyncio.wait(init_tasks, timeout=GATHER_TIMEOUT)
            for t_task in pending:
                t_task.cancel()
            if pending:
                from djinn_validator.api.metrics import MPC_ERRORS

                MPC_ERRORS.labels(reason="peer_init_timeout").inc()
                log.warning("mpc_peer_init_timeout", n_timed_out=len(pending), n_completed=len(done))
            for t_task in done:
                try:
                    results.append(t_task.result())
                except Exception:
                    results.append(None)

        init_failures = sum(1 for r in results if r is None or isinstance(r, BaseException))
        if init_failures > 0:
            from djinn_validator.api.metrics import MPC_ERRORS

            MPC_ERRORS.labels(reason="peer_init_failure").inc()
            log.info("mpc_peer_init_failures", count=init_failures, total=len(peers))

        accepted_peers = [r for r in results if r is not None and not isinstance(r, BaseException)]

        # CRITICAL: Purge all peer triple shares from coordinator memory.
        # After distribution, the coordinator should only have its own shares.
        # This ensures no single validator can reconstruct intermediate values.
        self._coordinator.purge_peer_triple_shares(session.session_id, my_x)

        if len(accepted_peers) + 1 < t:
            log.warning(
                "mpc_insufficient_accepted",
                accepted=len(accepted_peers) + 1,
                threshold=t,
                init_results=[
                    str(type(r).__name__) if r is None or isinstance(r, BaseException) else r.get("uid", "?")
                    for r in results
                ],
            )
            self._mark_session_failed(session)
            return MPCResult(
                available=False,
                participating_validators=len(accepted_peers) + 1,
                failure_reason=f"init_failed:{len(accepted_peers)+1}/{t}",
            )

        log.info(
            "mpc_distributed_session",
            session_id=session.session_id,
            accepted_peers=len(accepted_peers),
            authenticated=is_auth,
        )

        # Run per-gate protocol
        active_peers = list(accepted_peers)
        prev_d: int | None = None
        prev_e: int | None = None

        for gate_idx in range(n_gates):
            # Compute our own (d_i, e_i)
            if is_auth:
                # Finalize previous gate BEFORE computing the next one,
                # because compute_gate reads _prev_z which finalize_gate sets.
                if gate_idx > 0 and prev_d is not None and prev_e is not None:
                    my_state_auth.finalize_gate(prev_d, prev_e)
                my_d, my_e, my_d_mac, my_e_mac = my_state_auth.compute_gate(gate_idx, prev_d, prev_e)
            else:
                my_d, my_e = my_state_basic.compute_gate(gate_idx, prev_d, prev_e)

            d_vals: dict[int, int] = {my_x: my_d}
            e_vals: dict[int, int] = {my_x: my_e}
            # MAC share maps (authenticated mode only)
            d_mac_vals: dict[int, int] = {}
            e_mac_vals: dict[int, int] = {}
            if is_auth:
                d_mac_vals[my_x] = my_d_mac
                e_mac_vals[my_x] = my_e_mac

            # Collect from peers in parallel. One retry on transient HTTP
            # failure: the per-gate protocol is deterministic and idempotent
            # on the peer side (compute_gate is a pure function of session
            # state + gate_idx + prev_d/prev_e), so resending the same
            # request is safe and avoids killing a whole MPC session over
            # a single dropped packet.
            async def _collect_gate(
                peer: dict[str, Any],
                g_idx: int,
                p_d: int | None,
                p_e: int | None,
            ) -> tuple[int, int, int, int | None, int | None] | None:
                last_err: Exception | None = None
                for attempt in range(2):
                    try:
                        resp = await self._peer_request(
                            "post",
                            f"{peer['url']}/v1/mpc/compute_gate",
                            peer_uid=peer["uid"],
                            json={
                                "session_id": session.session_id,
                                "gate_idx": g_idx,
                                "prev_opened_d": hex(p_d) if p_d is not None else None,
                                "prev_opened_e": hex(p_e) if p_e is not None else None,
                            },
                        )
                        if resp.status_code == 200:
                            data = resp.json()
                            px = peer_x_map[peer["uid"]]
                            d_mac = int(data["d_mac"], 16) if data.get("d_mac") else None
                            e_mac = int(data["e_mac"], 16) if data.get("e_mac") else None
                            return px, int(data["d_value"], 16), int(data["e_value"], 16), d_mac, e_mac
                        last_err = ValueError(f"status {resp.status_code}")
                    except (httpx.HTTPError, KeyError, ValueError, json.JSONDecodeError) as e:
                        last_err = e
                    if attempt == 0:
                        await asyncio.sleep(0.2)
                log.warning(
                    "mpc_gate_failed",
                    peer_uid=peer["uid"],
                    gate_idx=g_idx,
                    error_type=type(last_err).__name__ if last_err else "unknown",
                    error=str(last_err) if last_err else "unknown",
                )
                return None

            gate_tasks = [asyncio.create_task(_collect_gate(peer, gate_idx, prev_d, prev_e)) for peer in active_peers]
            results: list[Any] = [None] * len(active_peers)
            if gate_tasks:
                done_g, pending_g = await asyncio.wait(gate_tasks, timeout=GATHER_TIMEOUT)
                for gt in pending_g:
                    gt.cancel()
                if pending_g:
                    from djinn_validator.api.metrics import MPC_ERRORS

                    MPC_ERRORS.labels(reason="gate_collect_timeout").inc()
                    log.warning(
                        "mpc_gate_collect_timeout",
                        gate_idx=gate_idx,
                        n_timed_out=len(pending_g),
                        n_completed=len(done_g),
                    )
                # Map results back by task index
                task_list = list(gate_tasks)
                for i, gt in enumerate(task_list):
                    if gt in done_g:
                        try:
                            results[i] = gt.result()
                        except Exception:
                            results[i] = None

            failed = []
            for i, result in enumerate(results):
                if result is None or isinstance(result, BaseException):
                    failed.append(active_peers[i])
                else:
                    peer_x, d_val, e_val, d_mac, e_mac = result
                    d_vals[peer_x] = d_val
                    e_vals[peer_x] = e_val
                    if d_mac is not None:
                        d_mac_vals[peer_x] = d_mac
                    if e_mac is not None:
                        e_mac_vals[peer_x] = e_mac

            for fp in failed:
                active_peers.remove(fp)

            if len(d_vals) < t:
                log.warning(
                    "mpc_gate_insufficient",
                    gate_idx=gate_idx,
                    remaining=len(d_vals),
                    threshold=t,
                )
                self._mark_session_failed(session)
                return MPCResult(
                    available=False,
                    participating_validators=len(d_vals),
                    failure_reason=f"gate_{gate_idx}_insufficient:{len(d_vals)}/{t}",
                )

            # Reconstruct publicly opened d and e
            prev_d = reconstruct_at_zero(d_vals, p)
            prev_e = reconstruct_at_zero(e_vals, p)

            # SPDZ MAC verification on opened d and e
            if is_auth and d_mac_vals and e_mac_vals:
                mac_key_shares = [
                    self._coordinator.get_mac_key_share(session.session_id, vx) for vx in sorted(d_mac_vals.keys())
                ]
                # Verify d
                d_auth_shares = [
                    AuthenticatedShare(x=vx, y=d_vals[vx], mac=d_mac_vals[vx]) for vx in sorted(d_mac_vals.keys())
                ]
                if not verify_mac_opening(prev_d, d_auth_shares, [m for m in mac_key_shares if m], p):
                    from djinn_validator.api.metrics import MPC_ERRORS

                    MPC_ERRORS.labels(reason="mac_failure").inc()
                    log.error("mac_verification_failed", gate_idx=gate_idx, value="d")
                    await self._broadcast_abort(
                        session.session_id,
                        active_peers,
                        gate_idx,
                        "d_mac_check_failed",
                    )
                    return None
                # Verify e
                e_auth_shares = [
                    AuthenticatedShare(x=vx, y=e_vals[vx], mac=e_mac_vals[vx]) for vx in sorted(e_mac_vals.keys())
                ]
                if not verify_mac_opening(prev_e, e_auth_shares, [m for m in mac_key_shares if m], p):
                    from djinn_validator.api.metrics import MPC_ERRORS

                    MPC_ERRORS.labels(reason="mac_failure").inc()
                    log.error("mac_verification_failed", gate_idx=gate_idx, value="e")
                    await self._broadcast_abort(
                        session.session_id,
                        active_peers,
                        gate_idx,
                        "e_mac_check_failed",
                    )
                    return None
                log.debug("mac_verified", gate_idx=gate_idx)

        # Finalize last gate for authenticated mode
        if is_auth and prev_d is not None and prev_e is not None:
            my_state_auth.finalize_gate(prev_d, prev_e)

        # Compute final output shares z_i.
        # CRITICAL: Each participant computes its own z_i locally.
        # The coordinator never accesses peer triple shares — this is the
        # secrecy guarantee. Peers return only the scalar z_i value.
        z_vals: dict[int, int] = {}

        # Coordinator computes its own z_i
        if is_auth:
            out = my_state_auth.get_output_share()
            if out:
                z_vals[my_x] = out.y
        else:
            z_vals[my_x] = my_state_basic.compute_output_share(prev_d, prev_e)

        # Collect z_i from each peer via /v1/mpc/finalize
        async def _collect_z(peer: dict[str, Any]) -> tuple[int, int] | None:
            try:
                resp = await self._peer_request(
                    "post",
                    f"{peer['url']}/v1/mpc/finalize",
                    peer_uid=peer["uid"],
                    json={
                        "session_id": session.session_id,
                        "last_opened_d": hex(prev_d),
                        "last_opened_e": hex(prev_e),
                    },
                )
                if resp.status_code == 200:
                    data = resp.json()
                    px = peer_x_map[peer["uid"]]
                    return px, int(data["z_share"], 16)
            except (httpx.HTTPError, KeyError, ValueError, json.JSONDecodeError) as e:
                log.warning("mpc_finalize_failed", peer_uid=peer["uid"], error=str(e))
            return None

        z_tasks = [asyncio.create_task(_collect_z(p)) for p in active_peers]
        z_results: list[Any] = []
        if z_tasks:
            done_z, pending_z = await asyncio.wait(z_tasks, timeout=GATHER_TIMEOUT)
            for zt in pending_z:
                zt.cancel()
            if pending_z:
                log.warning("mpc_finalize_timeout", n_timed_out=len(pending_z), n_completed=len(done_z))
            for zt in done_z:
                try:
                    z_results.append(zt.result())
                except Exception:
                    z_results.append(None)

        for result in z_results:
            if result is not None and not isinstance(result, BaseException):
                peer_x, z_i = result
                z_vals[peer_x] = z_i

        if len(z_vals) < t:
            log.warning("mpc_finalize_insufficient", collected=len(z_vals), threshold=t)
            self._mark_session_failed(session)
            return MPCResult(
                available=False,
                participating_validators=len(z_vals),
                failure_reason=f"finalize_insufficient:{len(z_vals)}/{t}",
            )

        # Reconstruct the final result: r * P(s) — zero iff s ∈ available set
        result_value = reconstruct_at_zero(z_vals, p)
        available = result_value == 0

        mpc_result = MPCResult(
            available=available,
            participating_validators=len(z_vals),
        )

        # Update session state
        with self._coordinator._lock:
            session.result = mpc_result
            session.status = SessionStatus.COMPLETE

        log.info(
            "mpc_distributed_result",
            session_id=session.session_id,
            available=available,
            participants=len(z_vals),
            gates=n_gates,
            authenticated=is_auth,
        )

        # Broadcast result to peers (parallel, best-effort with timeout)
        async def _broadcast_result(peer: dict[str, Any]) -> None:
            try:
                await self._peer_request(
                    "post",
                    f"{peer['url']}/v1/mpc/result",
                    peer_uid=peer["uid"],
                    json={
                        "session_id": session.session_id,
                        "signal_id": signal_id,
                        "available": available,
                        "participating_validators": len(z_vals),
                    },
                )
            except httpx.HTTPError as e:
                log.warning(
                    "mpc_result_broadcast_failed",
                    peer_uid=peer["uid"],
                    error_type=type(e).__name__,
                    error=str(e),
                )

        try:
            await asyncio.wait_for(
                asyncio.gather(
                    *(_broadcast_result(p) for p in active_peers),
                    return_exceptions=True,
                ),
                timeout=GATHER_TIMEOUT,
            )
        except TimeoutError:
            log.warning(
                "mpc_result_broadcast_timeout",
                timeout=GATHER_TIMEOUT,
                n_peers=len(active_peers),
            )

        return mpc_result

    async def resolve_batch_participants(
        self,
        *,
        signal_ids: list[str],
        threshold: int,
    ) -> dict[int, dict[str, Any]] | None:
        """Discover which peer validators hold consistent shares across
        an entire batch of signals.

        For a batch settlement to reconstruct correctly, EVERY signal in
        the batch must have a share at the same x-coordinate for each
        participating peer (see DEV-044). This walks the peer list,
        queries /v1/signal/{id}/share_info for each signal, and keeps
        only peers whose reported share_x is:
          1. identical across all signals in ``signal_ids``, AND
          2. not in conflict with the local validator's own share_x
             for those signals.

        Returns a dict mapping x-coordinate to peer dict. Returns None
        if fewer than ``threshold`` peers satisfy the consistency
        requirement — callers should fall back to single-validator
        settlement or retry once the peer set stabilizes.

        Note: this does NOT fetch share y-values. The y-values stay
        local to each peer and are only used inside the MPC protocol.
        """
        peers = self._get_peer_validators()
        if not peers:
            log.info(
                "batch_participants_no_peers",
                reason="no peers discovered from metagraph",
            )
            return None
        if not signal_ids:
            return None

        # Resolve each peer's share_x for every signal. Any peer that
        # fails lookup on any signal, or reports inconsistent x across
        # signals, is dropped from the batch participant set.
        peer_x_map: dict[int, int] = {}  # peer_uid -> agreed share_x

        async def _probe(peer: dict[str, Any]) -> tuple[int, int | None]:
            xs_seen: set[int] = set()
            for sig_id in signal_ids:
                try:
                    resp = await self._peer_request(
                        "get",
                        f"{peer['url']}/v1/signal/{sig_id}/share_info",
                        peer_uid=peer["uid"],
                    )
                    if resp.status_code != 200:
                        return peer["uid"], None
                    data = resp.json()
                    xs_seen.add(int(data["share_x"]))
                except (httpx.HTTPError, KeyError, ValueError) as e:
                    log.debug(
                        "batch_share_info_lookup_failed",
                        peer_uid=peer["uid"],
                        signal_id=sig_id,
                        error=str(e)[:100],
                    )
                    return peer["uid"], None
            if len(xs_seen) != 1:
                log.info(
                    "batch_participant_xs_inconsistent",
                    peer_uid=peer["uid"],
                    xs_seen=sorted(xs_seen),
                )
                return peer["uid"], None
            return peer["uid"], next(iter(xs_seen))

        probe_results = await asyncio.gather(
            *(_probe(p) for p in peers),
            return_exceptions=True,
        )
        for result in probe_results:
            if isinstance(result, BaseException):
                continue
            uid, share_x = result
            if share_x is None:
                continue
            peer_x_map[uid] = share_x

        # Build x -> peer map, rejecting any x-collision between peers.
        x_to_peer: dict[int, dict[str, Any]] = {}
        collisions: list[int] = []
        for peer in peers:
            vx = peer_x_map.get(peer["uid"])
            if vx is None:
                continue
            if vx in x_to_peer:
                collisions.append(vx)
                continue
            x_to_peer[vx] = peer

        if collisions:
            log.warning(
                "batch_participant_x_collision",
                colliding_xs=collisions,
                msg="multiple peers claim the same share_x; dropping duplicates",
            )

        if len(x_to_peer) < threshold - 1:
            # -1 because the local validator also participates.
            log.warning(
                "batch_participants_below_threshold",
                discovered=len(x_to_peer),
                required=threshold - 1,
            )
            return None

        log.info(
            "batch_participants_resolved",
            participants=len(x_to_peer),
            participant_xs=sorted(x_to_peer.keys()),
            signal_count=len(signal_ids),
        )
        return x_to_peer

    async def _prefetch_missing_purchase_odds_from_peers(
        self,
        *,
        audit_set: Any,
        purchase_odds_ledger: Any,
    ) -> int:
        """Pull BPA/WPA rows that the local ledger is missing from peers.

        The outbound gossip path (``_gossip_purchase_odds_to_peers`` in
        ``server.py``, v1433) fans out every new purchase to committee
        peers at commit time, but historical purchases predating v1433
        only exist on the validator that originally handled them.
        Without this prefetch, settlement on any other validator
        silently skips those signals (see ``build_pi_skip_missing_bpa_wpa_v2``
        in ``mpc_batch_settlement.py``) and the batch ends up empty.

        For every ``(signal_id, idiot_address)`` pair in the audit set
        that is absent from the local ledger, fan out signed GET
        ``/v1/purchase_odds/{signal_id}/{buyer}`` to every committee
        peer. First 200 response wins AUTHENTICATION AGAINST THE ON-CHAIN
        ROOT (v1443): before writing the peer-supplied vectors to the
        local ledger, the caller computes the Merkle root over the
        returned ``bpas`` / ``wpas`` using the canonical leaf format
        (see ``djinn_validator/utils/merkle.py``) and compares against
        ``Escrow.purchaseBpaRoot(purchaseId)`` / ``purchaseWpaRoot`` that
        ``purchaseV2`` commits on-chain. A mismatched or missing
        (pre-V6, zero-bytes) root causes the peer response to be
        rejected — we continue polling other peers, but never accept
        unauthenticated data. Without this, one racing malicious
        validator permanently poisons the local ledger and directly
        biases the settlement ``quality_score`` submitted on-chain.

        Returns the count of rows successfully backfilled.
        """
        if purchase_odds_ledger is None:
            log.info("purchase_odds_prefetch_bail", reason="no_ledger")
            return 0
        if self._neuron is None or self._neuron.metagraph is None:
            log.info(
                "purchase_odds_prefetch_bail",
                reason="no_neuron_or_metagraph",
                has_neuron=self._neuron is not None,
            )
            return 0
        if audit_set is None or not getattr(audit_set, "signals", None):
            log.info(
                "purchase_odds_prefetch_bail",
                reason="no_audit_set_or_empty_signals",
                audit_set_none=audit_set is None,
            )
            return 0
        if self._chain_client is None:
            # Fail-closed: without chain_client we cannot Merkle-verify
            # peer vectors against the on-chain commitment and a
            # malicious peer can corrupt our ledger. Skip backfill
            # entirely — the batch will be incomplete but not
            # poisoned. Operators wiring up MPCOrchestrator must pass
            # a chain_client to enable peer-backfill.
            log.warning(
                "purchase_odds_prefetch_bail",
                reason="no_chain_client_cannot_verify",
            )
            return 0

        idiot_addr = getattr(audit_set, "idiot_address", None)
        if not idiot_addr:
            log.info("purchase_odds_prefetch_bail", reason="no_idiot_addr")
            return 0
        log.info(
            "purchase_odds_prefetch_enter",
            idiot=idiot_addr[:10],
            signal_count=len(audit_set.signals),
        )

        # (signal_id, purchase_id) for missing rows. purchase_id comes
        # straight from the audit_set (populated by audit_bootstrap from
        # the on-chain Escrow state). Zero means "no purchase_id known"
        # — typically a pre-V6 legacy purchase; skip rather than accept.
        missing: list[tuple[str, int]] = []
        for signal_id, audit_signal in audit_set.signals.items():
            existing = purchase_odds_ledger.get(
                signal_id=signal_id,
                buyer_address=idiot_addr,
            )
            if existing is not None:
                continue
            pid = int(getattr(audit_signal, "purchase_id", 0) or 0)
            missing.append((signal_id, pid))

        if not missing:
            return 0

        peers = self._get_peer_validators()
        if not peers:
            log.debug(
                "purchase_odds_prefetch_no_peers",
                missing_count=len(missing),
            )
            return 0

        from djinn_validator.api.middleware import create_signed_headers
        from djinn_validator.utils.merkle import compute_vector_root

        _ZERO_ROOT = b"\x00" * 32

        fetched = 0
        status_tally: dict[str, int] = {}

        # v1702: bounded-cardinality Prometheus counter mirrors the
        # local status_tally so /metrics surfaces fleet-wide. Best-effort
        # import; missing metrics module (tests) doesn't break prefetch.
        def _tick(outcome: str) -> None:
            try:
                from djinn_validator.api.metrics import PURCHASE_ODDS_PREFETCH_RESULT

                PURCHASE_ODDS_PREFETCH_RESULT.labels(outcome=outcome).inc()
            except Exception:
                pass

        async with httpx.AsyncClient(timeout=5.0) as client:
            for signal_id, purchase_id in missing:
                # Pre-V6 purchase: no on-chain root exists. Skip — we
                # cannot authenticate peer data for these so we'd rather
                # leave the row missing than take a malicious peer's word.
                if purchase_id <= 0:
                    status_tally["skipped_no_pid"] = status_tally.get("skipped_no_pid", 0) + 1
                    _tick("skipped_no_pid")
                    log.info(
                        "purchase_odds_prefetch_skip_no_pid",
                        signal_id=signal_id[:20],
                    )
                    continue

                # Fetch on-chain roots ONCE per signal before we start
                # polling peers so every peer response is checked against
                # the same ground truth.
                roots = await self._chain_client.get_purchase_vector_roots(purchase_id)
                if roots is None:
                    status_tally["root_rpc_failed"] = status_tally.get("root_rpc_failed", 0) + 1
                    _tick("root_rpc_failed")
                    log.warning(
                        "purchase_odds_prefetch_root_rpc_failed",
                        signal_id=signal_id[:20],
                        purchase_id=purchase_id,
                    )
                    continue
                bpa_root_onchain, wpa_root_onchain = roots
                if bpa_root_onchain == _ZERO_ROOT and wpa_root_onchain == _ZERO_ROOT:
                    # Pre-V6 purchase recorded on-chain; no commitment.
                    status_tally["zero_root_legacy"] = status_tally.get("zero_root_legacy", 0) + 1
                    _tick("zero_root_legacy")
                    log.info(
                        "purchase_odds_prefetch_skip_legacy",
                        signal_id=signal_id[:20],
                        purchase_id=purchase_id,
                    )
                    continue

                endpoint = f"/v1/purchase_odds/{signal_id}/{idiot_addr}"
                for peer in peers:
                    data: dict[str, Any] | None = None
                    try:
                        headers = create_signed_headers(endpoint, b"", self._neuron.wallet)
                        resp = await client.get(
                            f"{peer['url']}{endpoint}",
                            headers=headers,
                        )
                        if resp.status_code != 200:
                            key = f"uid{peer['uid']}:{resp.status_code}"
                            status_tally[key] = status_tally.get(key, 0) + 1
                            # v1702: bounded label set; map status codes
                            # into 404 / 4xx / 5xx buckets so cardinality
                            # stays bounded across peer fleet sizes.
                            if resp.status_code == 404:
                                _tick("peer_404")
                            elif 400 <= resp.status_code < 500:
                                _tick("peer_status_4xx")
                            elif 500 <= resp.status_code < 600:
                                _tick("peer_status_5xx")
                            else:
                                _tick("peer_status_other")
                            continue
                        data = resp.json()
                    except httpx.HTTPError as e:
                        key = f"uid{peer['uid']}:httpx_{type(e).__name__}"
                        status_tally[key] = status_tally.get(key, 0) + 1
                        _tick("peer_unreachable")
                        continue
                    except Exception as e:
                        key = f"uid{peer['uid']}:exc_{type(e).__name__}"
                        status_tally[key] = status_tally.get(key, 0) + 1
                        _tick("peer_unreachable")
                        continue

                    if data is None:
                        continue

                    # Root check BEFORE write. Compute the canonical
                    # Merkle root over the peer-returned vectors and
                    # compare against the on-chain commitment. Any
                    # mismatch = peer is either buggy, out-of-sync, or
                    # adversarial; drop the response and keep polling.
                    try:
                        peer_bpas = data["bpas"]
                        peer_wpas = data["wpas"]
                        peer_bpa_mode = bool(data["bpa_mode"])
                    except (KeyError, TypeError) as e:
                        key = f"uid{peer['uid']}:bad_shape_{type(e).__name__}"
                        status_tally[key] = status_tally.get(key, 0) + 1
                        _tick("bad_shape")
                        continue

                    try:
                        bpa_root_local = compute_vector_root(peer_bpas)
                        wpa_root_local = compute_vector_root(peer_wpas)
                    except (ValueError, TypeError) as e:
                        key = f"uid{peer['uid']}:root_compute_{type(e).__name__}"
                        status_tally[key] = status_tally.get(key, 0) + 1
                        _tick("root_compute_err")
                        log.warning(
                            "purchase_odds_prefetch_root_compute_failed",
                            signal_id=signal_id[:20],
                            peer_uid=peer["uid"],
                            err=str(e)[:100],
                        )
                        continue

                    if bpa_root_local != bpa_root_onchain or wpa_root_local != wpa_root_onchain:
                        key = f"uid{peer['uid']}:root_mismatch"
                        status_tally[key] = status_tally.get(key, 0) + 1
                        _tick("root_mismatch")
                        log.warning(
                            "purchase_odds_prefetch_root_mismatch",
                            signal_id=signal_id[:20],
                            purchase_id=purchase_id,
                            peer_uid=peer["uid"],
                            bpa_local="0x" + bpa_root_local.hex(),
                            bpa_onchain="0x" + bpa_root_onchain.hex(),
                            wpa_local="0x" + wpa_root_local.hex(),
                            wpa_onchain="0x" + wpa_root_onchain.hex(),
                        )
                        continue

                    try:
                        purchase_odds_ledger.record(
                            signal_id=signal_id,
                            buyer_address=idiot_addr,
                            bpas=peer_bpas,
                            wpas=peer_wpas,
                            bpa_mode=peer_bpa_mode,
                        )
                        fetched += 1
                        _tick("recovered")
                        log.info(
                            "purchase_odds_prefetch_hit",
                            signal_id=signal_id[:20],
                            peer_uid=peer["uid"],
                            purchase_id=purchase_id,
                        )
                    except (KeyError, ValueError, TypeError) as e:
                        _tick("record_failed")
                        log.warning(
                            "purchase_odds_prefetch_record_failed",
                            signal_id=signal_id[:20],
                            err=str(e)[:100],
                        )
                    break  # first authenticated 200 wins — next signal

        log.info(
            "purchase_odds_prefetch_complete",
            missing_total=len(missing),
            fetched=fetched,
            peers_available=len(peers),
            idiot=idiot_addr[:10],
            status_tally=status_tally,
        )
        return fetched

    async def _read_canonical_line_outcomes(
        self,
        audit_set: Any,
    ) -> dict[str, list[Any]] | None:
        """v1747 Phase 4: read canonical line outcomes from LineOutcomeRegistry.

        Returns a {signal_id: [Outcome, ...]} dict aligned with each
        signal's local lines. Returns None to indicate ABSTAIN — caller
        must NOT fall back to local outcomes.

        Abstain reasons (each surfaced via SHADOW_SETTLE_OUTCOME):
          - ``abstain_canonical_unconfigured``: registry/chain context missing
          - ``abstain_canonical_unknown_signal``: outcome_attestor missing
            metadata for a signal in the audit_set (transient; gossip will
            populate next loop)
          - ``abstain_canonical_unparseable_line``: a ParsedPick can't be
            expressed canonically (legacy format issue; should be rare
            after Phase 5 frontend update)
          - ``abstain_rpc_error``: chain read failed
          - ``abstain_canonical_pending``: at least one line not finalized
          - ``abstain_local_divergence``: local outcomes differ from canonical
            (HONESTY GATE — never vote against the chain truth)

        Honesty gate is critical: a validator with a buggy ESPN poll would
        otherwise produce a non-canonical quality_score and lose its share
        of the 4-of-5 quorum. By refusing to vote when local diverges, we
        preserve the option to investigate the bug rather than silently
        cementing wrong outcomes into MPC inputs.
        """
        from djinn_validator.api.metrics import SHADOW_SETTLE_OUTCOME
        from djinn_validator.chain.outcome_signer import line_hash as compute_line_hash
        from djinn_validator.core.outcomes import (
            Outcome,
            parsed_pick_to_line_key,
        )

        chain_id = self._chain_id_for_line_registry()
        registry_addr = self._line_registry_address()
        if (
            self._chain_client is None
            or chain_id is None
            or not registry_addr
            or self._outcome_attestor is None
        ):
            SHADOW_SETTLE_OUTCOME.labels(outcome="abstain_canonical_unconfigured").inc()
            log.info(
                "shadow_settle_canonical_unconfigured",
                has_chain=self._chain_client is not None,
                has_chain_id=chain_id is not None,
                has_registry=bool(registry_addr),
                has_attestor=self._outcome_attestor is not None,
            )
            return None

        resolved_signals = list(getattr(audit_set, "resolved_signals", []) or [])
        if not resolved_signals:
            return {}

        # Build (signal_id, [LineKey, ...]) pairs for every resolved signal
        # in the audit_set. Lines are derived from outcome_attestor's
        # SignalMetadata (the source of truth for canonical line content).
        #
        # v1763: when a signal's picks can't be expressed canonically
        # (parsed_pick_to_line_key returns None — typically pre-Phase-5
        # legacy formats), skip JUST that signal rather than abandoning
        # the whole audit. The caller's build_purchase_inputs_from_audit_set
        # treats missing keys as "use local outcomes for this signal", which
        # is exactly the fallback behavior parsed_pick_to_line_key's
        # docstring prescribes. Other signals in the same audit still get
        # canonical reads + honesty-gate divergence checks.
        signal_keys: dict[str, list[Any]] = {}
        flat_hashes: list[bytes] = []
        per_signal_slices: list[tuple[str, int, int]] = []
        for sig in resolved_signals:
            sid = sig.signal_id
            meta = self._outcome_attestor.get_signal(sid)
            if meta is None or not meta.lines:
                SHADOW_SETTLE_OUTCOME.labels(
                    outcome="abstain_canonical_unknown_signal"
                ).inc()
                log.info(
                    "shadow_settle_canonical_unknown_signal",
                    signal_id=sid[:20],
                )
                return None

            lk_list: list[Any] = []
            unparseable = False
            for pick in meta.lines:
                lk = parsed_pick_to_line_key(
                    pick, meta.sport, meta.event_id, meta.home_team, meta.away_team
                )
                if lk is None:
                    SHADOW_SETTLE_OUTCOME.labels(
                        outcome="abstain_canonical_unparseable_line"
                    ).inc()
                    log.info(
                        "shadow_settle_canonical_unparseable_line",
                        signal_id=sid[:20],
                    )
                    unparseable = True
                    break
                lk_list.append(lk)
            if unparseable:
                continue

            try:
                sig_hashes = [
                    compute_line_hash(lk, chain_id, registry_addr) for lk in lk_list
                ]
            except (ValueError, TypeError):
                # Distinct from abstain_canonical_unparseable_line: the
                # LineKey built fine, but hashing it failed. If a structural
                # bug or library regression ever drives this to non-zero in
                # prod we want to see it in the metric, not have it hidden
                # under the legacy-format bucket.
                SHADOW_SETTLE_OUTCOME.labels(
                    outcome="abstain_canonical_linehash_compute_failed"
                ).inc()
                log.info(
                    "shadow_settle_canonical_linehash_compute_failed",
                    signal_id=sid[:20],
                )
                continue

            signal_keys[sid] = lk_list
            start = len(flat_hashes)
            flat_hashes.extend(sig_hashes)
            per_signal_slices.append((sid, start, len(flat_hashes)))

        # Every signal was unparseable — no canonical reads to make. Return
        # empty dict so caller falls through to local for all signals (vs.
        # None which would abstain the whole audit).
        if not per_signal_slices:
            return {}

        canonical_ints = await self._chain_client.batch_line_outcomes(flat_hashes)
        if canonical_ints is None:
            SHADOW_SETTLE_OUTCOME.labels(outcome="abstain_rpc_error").inc()
            log.warning("shadow_settle_canonical_rpc_error", n_hashes=len(flat_hashes))
            return None

        if any(o == int(Outcome.PENDING) for o in canonical_ints):
            SHADOW_SETTLE_OUTCOME.labels(outcome="abstain_canonical_pending").inc()
            log.info(
                "shadow_settle_canonical_pending",
                n_pending=sum(1 for o in canonical_ints if o == 0),
                n_total=len(canonical_ints),
            )
            return None

        # Honesty gate: refuse to vote when local diverges from canonical.
        override: dict[str, list[Any]] = {}
        for sid, start, end in per_signal_slices:
            slice_ints = canonical_ints[start:end]
            slice_outcomes = [Outcome(o) for o in slice_ints]
            local = next(
                (s.outcomes for s in resolved_signals if s.signal_id == sid),
                None,
            )
            # per_signal_slices is built by iterating resolved_signals above,
            # so every sid here was resolved when we captured it. If this
            # ever fires it means a refactor decoupled the two — a bug, not
            # a runtime condition the abstain machinery should swallow.
            assert local is not None, (
                f"sid {sid[:20]} in per_signal_slices but missing from "
                "resolved_signals; orchestrator state is inconsistent"
            )
            if [int(o) for o in local] != slice_ints:
                SHADOW_SETTLE_OUTCOME.labels(
                    outcome="abstain_local_divergence"
                ).inc()
                log.error(
                    "shadow_settle_local_diverges_from_canonical",
                    signal_id=sid[:20],
                    local=[int(o) for o in local],
                    canonical=slice_ints,
                )
                return None
            override[sid] = slice_outcomes
        return override

    def _chain_id_for_line_registry(self) -> int | None:
        """Resolve chain_id for lineHash binding, preferring chain_client."""
        if self._chain_client is not None:
            cid = getattr(self._chain_client, "_chain_id", None)
            if cid:
                return int(cid)
        raw = os.environ.get("BASE_CHAIN_ID", "")
        if raw:
            try:
                return int(raw)
            except ValueError:
                return None
        return None

    def _line_registry_address(self) -> str:
        """Resolve LineOutcomeRegistry address (env-defaulted)."""
        if self._chain_client is not None:
            addr = getattr(self._chain_client, "_line_outcome_registry_address", "")
            if addr:
                return addr
        return os.environ.get("LINE_OUTCOME_REGISTRY_ADDRESS", "").strip()

    async def try_shadow_distributed_settlement(
        self,
        *,
        audit_set: Any,
        share_store: Any,
        purchase_odds_ledger: Any,
        threshold: int,
    ) -> ShadowSettleSubmitData | None:
        """Run the distributed batch settlement for an AuditSet.

        Wraps the four steps a real distributed audit needs:

          1. Assemble PurchaseInputs for every signal in the batch via
             ``build_purchase_inputs_from_audit_set`` (pulls local
             Shamir shares + BPA/WPA vectors).
          2. Discover peer participants with cross-signal share_x
             consistency via ``resolve_batch_participants``.
          3. Generate Beaver triples via ``generate_batch_beaver_triples``
             and inject this validator's own share_x into the
             participant set so ``run_batch_settlement`` can address
             itself like any other peer.
          4. Drive the protocol via ``run_batch_settlement`` and
             return a ``ShadowSettleSubmitData`` shaped for submit-on-
             chain when the caller opts in.

        Returns ``None`` on ANY failure (missing data, insufficient peers,
        protocol error). On success the caller treats this as shadow
        output when ``DJINN_FF_BATCH_SETTLEMENT_HTTP_SUBMIT`` is OFF
        (log + compare to local ``batch_settle_audit_set`` quality_score)
        and as the submit payload when the flag is ON and the local
        path returned None.

        This method is the orchestration half of the distributed audit
        hook. The data-assembly half lives in
        ``build_purchase_inputs_from_audit_set`` so the fakes can stay
        small and each step can unit test in isolation.
        """
        from djinn_validator.api.metrics import SHADOW_SETTLE_OUTCOME, SHADOW_SETTLE_STAGE
        from djinn_validator.core.audit_set import MIN_BATCH_SIZE as _MIN_BATCH_SIZE
        from djinn_validator.core.mpc_batch_settlement import (
            build_purchase_inputs_from_audit_set,
            generate_batch_beaver_triples,
        )

        SHADOW_SETTLE_OUTCOME.labels(outcome="attempt").inc()
        SHADOW_SETTLE_STAGE.labels(stage="pre_recovery").inc()

        # Pre-gate (perf optimization, 2026-05-02): skip the expensive MPC
        # fan-out if this batch would be rejected at the submit gate
        # anyway. The submit gate (main.py post-shadow_settle) requires:
        #   batch_size >= MIN_BATCH_SIZE, OR
        #   earlyExitRequested(batchKey) on chain, OR
        #   should_auto_early_exit (45-day SLA timeout)
        # Pre-2026-05-02, validators ran full distributed MPC (Lagrange
        # interp + peer fan-out + EC math + 6-peer compute_gate calls)
        # for every ready audit set on every loop, then dropped the result
        # at the submit gate when batch was sub-MIN with no consent. UID 0
        # log analysis showed 11/14 shadow_settle_completed events ended
        # in skip_settle_below_min_batch_no_request_no_timeout — ~80% of
        # MPC compute discarded. With 8 worker processes pegged at 70-100%
        # CPU, this was the dominant time sink.
        # The pre-gate consults the same conditions BEFORE the MPC runs.
        # Conservative: only fast-fail when we are certain the submit gate
        # will reject. If consent or timeout could make this batch
        # settleable, we let the MPC run and the submit gate handle the
        # specifics (different per-validator subsets may produce different
        # batchKeys, only the final submit-time check is authoritative).
        resolved_count = len(getattr(audit_set, "resolved_signals", []) or [])
        if resolved_count < _MIN_BATCH_SIZE:
            # batch_size is sub-MIN; consent/timeout may still allow it.
            timeout_ok = False
            consent_ok = False
            if self._chain_client is not None:
                try:
                    resolved_pids = sorted(getattr(audit_set, "resolved_purchase_ids", []) or [])
                    if resolved_pids:
                        timeout_ok = await self._chain_client.should_auto_early_exit(resolved_pids)
                        if not timeout_ok:
                            consent_ok = await self._chain_client.is_early_exit_requested(
                                getattr(audit_set, "genius_address", ""),
                                getattr(audit_set, "idiot_address", ""),
                                resolved_pids,
                            )
                except Exception as e:
                    log.debug(
                        "shadow_settle_pregate_check_failed",
                        error=str(e)[:120],
                    )
                    # Fail-open: if the pre-gate check itself errors, run
                    # the full MPC so we don't suppress a settle the
                    # submit-side might have allowed.
                    timeout_ok = True
            if not (timeout_ok or consent_ok):
                log.info(
                    "shadow_settle_pregate_skip_below_min",
                    genius=getattr(audit_set, "genius_address", "?"),
                    idiot=getattr(audit_set, "idiot_address", "?"),
                    resolved_count=resolved_count,
                    min_batch=_MIN_BATCH_SIZE,
                )
                SHADOW_SETTLE_OUTCOME.labels(outcome="abstain_pregate_min_batch").inc()
                return None

        # v1434: pull peer BPA/WPA for any rows missing locally before
        # assembling the batch. Without this, purchases predating v1433
        # gossip never settle on non-originating validators. See P0-01
        # in MAINNET_BLOCKERS.md.
        # v1690: 60s ceiling on BPA/WPA prefetch. The internal helper has
        # 30s per chain RPC * N missing signals so 10+ missing -> minutes.
        # Cap so a slow-RPC episode can't strand shadow_settle.
        try:
            await asyncio.wait_for(
                self._prefetch_missing_purchase_odds_from_peers(
                    audit_set=audit_set,
                    purchase_odds_ledger=purchase_odds_ledger,
                ),
                timeout=60.0,
            )
        except TimeoutError:
            log.warning(
                "shadow_settle_bpa_wpa_prefetch_timeout",
                idiot=getattr(audit_set, "idiot_address", "?"),
            )
        SHADOW_SETTLE_STAGE.labels(stage="post_bpa_wpa").inc()

        # v1671: outcome recovery (project_outcome_recovery_design_2026_05_03.md).
        # Pull resolved outcomes from peers for signals where the audit_set
        # records a purchase but the local OutcomeAttestor hasn't yet
        # resolved the signal. Closes the per-validator outcome divergence
        # gap that left batchKey diverging across the fleet even with shares
        # fully distributed. Receiver replay-verifies via independent ESPN
        # fetch (same trust model as push gossip). Runs BEFORE share recovery
        # so pulled outcomes have a chance to land before build_pi reads them.
        if self._outcome_attestor is not None and audit_set is not None:
            from djinn_validator.core.outcome_recovery import recover_missing_outcomes

            # v1672 fix: resolved_signals returns list[AuditSignal] (non-frozen
            # @dataclass, unhashable), and signal IDs are the keys of audit_set.signals.
            # Pre-fix: set(list[AuditSignal]) raised TypeError; comparing string
            # signal_ids against AuditSignal objects always returned False.
            resolved_ids_set = {s.signal_id for s in (getattr(audit_set, "resolved_signals", []) or [])}
            all_signals = list(getattr(audit_set, "signals", {}) or {})
            unresolved = [sid for sid in all_signals if sid not in resolved_ids_set]
            if unresolved:
                peers = self._get_peer_validators()
                if peers:
                    try:
                        # v1690: 30s ceiling. recover_missing_outcomes is
                        # 5s per peer per signal so worst case is 5*5*N which
                        # we don't want to wait for here.
                        await asyncio.wait_for(
                            recover_missing_outcomes(
                                signal_ids=unresolved,
                                peer_validators=peers,
                                outcome_attestor=self._outcome_attestor,
                            ),
                            timeout=30.0,
                        )
                    except TimeoutError:
                        log.warning("outcome_recovery_timeout", n_unresolved=len(unresolved))
                    except Exception as e:
                        log.warning("outcome_recovery_unhandled", err=str(e)[:200])
        SHADOW_SETTLE_STAGE.labels(stage="post_outcome_recv").inc()

        # v1670: share recovery (Phase 5 of project_share_recovery_design_2026_05_03).
        # Pull encrypted forwarding shares from peers for any signal in the
        # audit set we don't have locally. This closes the divergence gap
        # where THIS validator was 504-ing during the original genius
        # fan-out and never got its share — peers that DID receive the
        # bundle hold a forwarding ciphertext addressed to us, decryptable
        # only with our x25519 privkey. Recovered shares slot directly
        # into share_store and are picked up by build_purchase_inputs_from_audit_set
        # below.
        if self._encryption_privkey and self._signer_address and audit_set is not None:
            from djinn_validator.core.share_recovery import recover_missing_shares

            # v1673 fix: resolved_signals returns list[AuditSignal] (non-frozen
            # @dataclass, unhashable). Pre-fix, the dict-comprehension below
            # raised TypeError before the try-block could catch it, AND
            # signal_ids= passed AuditSignal objects to recover_missing_shares
            # instead of the str signal IDs the function expects. Same root
            # bug as the outcome-recovery block above.
            resolved_ids = [s.signal_id for s in (getattr(audit_set, "resolved_signals", []) or [])]
            if resolved_ids:
                peers = self._get_peer_validators()
                if peers:
                    genius_addr = getattr(audit_set, "genius_address", "") or ""
                    genius_map = {sid: genius_addr for sid in resolved_ids} if genius_addr else None
                    try:
                        # v1690: 30s ceiling. recover_missing_shares is the
                        # serial-per-peer-per-signal pattern; same bound.
                        await asyncio.wait_for(
                            recover_missing_shares(
                                signal_ids=resolved_ids,
                                share_store=share_store,
                                peer_validators=peers,
                                encryption_privkey=self._encryption_privkey,
                                signer_address=self._signer_address,
                                genius_address_for=genius_map,
                            ),
                            timeout=30.0,
                        )
                    except TimeoutError:
                        log.warning("share_recovery_timeout", n_resolved=len(resolved_ids))
                    except Exception as e:
                        log.warning("share_recovery_unhandled", err=str(e)[:200])

        SHADOW_SETTLE_STAGE.labels(stage="post_recovery").inc()

        # v1747 Phase 4: canonical outcomes gate. Read line-keyed outcomes
        # from LineOutcomeRegistry on-chain and use them as the
        # consensus input. Abstain on RPC error (NEVER fall back to local —
        # that's the divergence bug v1747 exists to fix), abstain on any
        # canonical-pending line, abstain on local-vs-canonical divergence
        # (honesty gate).
        #
        # Gated behind ``DJINN_FF_OUTCOME_REGISTRY_READ`` so the rollout can
        # land code in production with the gate dormant (Phase 8b dual-write)
        # then flip to canonical reads (Phase 8d) once shadow soak confirms
        # byte-for-byte agreement.
        line_outcomes_override: dict[str, list[Any]] | None = None
        if os.environ.get("DJINN_FF_OUTCOME_REGISTRY_READ", "0") == "1":
            line_outcomes_override = await self._read_canonical_line_outcomes(
                audit_set
            )
            if line_outcomes_override is None:
                # Caller-side metric ticks already happened inside the helper.
                return None

        SHADOW_SETTLE_STAGE.labels(stage="pre_build_pi").inc()
        batch = build_purchase_inputs_from_audit_set(
            audit_set,
            share_store=share_store,
            purchase_odds_ledger=purchase_odds_ledger,
            line_outcomes_override=line_outcomes_override,
        )
        SHADOW_SETTLE_STAGE.labels(stage="post_build_pi").inc()
        if batch is None or not batch:
            log.info(
                "shadow_settle_no_batch",
                genius=getattr(audit_set, "genius_address", "?"),
                idiot=getattr(audit_set, "idiot_address", "?"),
                batch_is_none=batch is None,
                batch_len=0 if batch is None else len(batch),
                signal_count=len(getattr(audit_set, "signals", {}) or {}),
                resolved_count=len(getattr(audit_set, "resolved_signals", []) or []),
            )
            SHADOW_SETTLE_OUTCOME.labels(outcome="abstain_no_batch").inc()
            return None

        # v1681 (P1-37 partial fix): canonical-PID-from-chain check.
        # Every validator must build the SAME purchase_id subset to land on
        # the same batchKey. If our local batch differs from the on-chain
        # canonical PID list (Account.getPairPurchaseIds), our vote will go
        # to a different bucket from the validators that built the canonical
        # list — quorum can never form. Abstain so we don't waste an
        # on-chain submit on a doomed batchKey.
        # The expensive part is the RPC call; gated to once per shadow_settle
        # cycle so the cost is bounded.
        if self._chain_client is not None and batch:
            try:
                local_pids = sorted([int(p.purchase_id) for p in batch if p.purchase_id])
                # v1689: bound the chain RPC at 10s. Pre-fix, a slow / hung
                # RPC could block shadow_settle indefinitely between
                # post_build_pi and pre_resolve_peers (UID 86 metrics: 7 of
                # 11 attempts hung exactly here).
                canonical_pids_raw = await asyncio.wait_for(
                    self._chain_client.get_pair_purchase_ids(
                        getattr(audit_set, "genius_address", ""),
                        getattr(audit_set, "idiot_address", ""),
                    ),
                    timeout=10.0,
                )
                canonical_pids = sorted([int(p) for p in canonical_pids_raw or []])
                if local_pids and canonical_pids and local_pids != canonical_pids:
                    log.info(
                        "shadow_settle_subset_divergence_skip",
                        genius=getattr(audit_set, "genius_address", "?"),
                        idiot=getattr(audit_set, "idiot_address", "?"),
                        local_pid_count=len(local_pids),
                        canonical_pid_count=len(canonical_pids),
                        # Show first 3 of each for debug
                        local_sample=local_pids[:3],
                        canonical_sample=canonical_pids[:3],
                        msg="local audit_set differs from chain; abstaining to avoid divergent batchKey",
                    )
                    SHADOW_SETTLE_OUTCOME.labels(outcome="abstain_subset_divergence").inc()
                    return None
            except (TimeoutError, Exception) as e:
                # Fail-open: if we can't check chain, proceed with local
                # batch (status quo). Better to risk submitting a divergent
                # batchKey than to block on a flaky RPC.
                log.debug(
                    "shadow_settle_canonical_pid_check_failed",
                    error=str(e)[:120],
                    error_type=type(e).__name__,
                )
        SHADOW_SETTLE_STAGE.labels(stage="post_canonical_pid").inc()

        # Pre-gate (post-build_pi, 2026-05-02): the v1664 pre-gate checked
        # `audit_set.resolved_signals < MIN_BATCH_SIZE` BEFORE build_pi.
        # That catches sub-MIN audit_sets but misses the COMMON case where
        # audit_set has 10+ resolved signals but THIS validator's local
        # build_pi output only has 5 (because Shamir k=2 means each signal's
        # share lives on ~2-3 validators only — local share is the bottleneck).
        # When the local batch comes back sub-MIN, the submit gate will reject
        # with skip_settle_below_min_batch_no_request_no_timeout regardless of
        # whether the audit_set itself was full. Fast-fail HERE before the
        # expensive resolve_batch_participants + generate_batch_beaver_triples
        # + run_batch_settlement chain.
        if len(batch) < _MIN_BATCH_SIZE:
            timeout_ok = False
            consent_ok = False
            if self._chain_client is not None:
                try:
                    batch_pids = sorted([p.purchase_id for p in batch if p.purchase_id])
                    if batch_pids:
                        # v1689: per-call 10s timeout to prevent indefinite hang
                        # on slow chain RPC. Two awaits, max 20s total in this
                        # branch.
                        timeout_ok = await asyncio.wait_for(
                            self._chain_client.should_auto_early_exit(batch_pids),
                            timeout=10.0,
                        )
                        if not timeout_ok:
                            consent_ok = await asyncio.wait_for(
                                self._chain_client.is_early_exit_requested(
                                    getattr(audit_set, "genius_address", ""),
                                    getattr(audit_set, "idiot_address", ""),
                                    batch_pids,
                                ),
                                timeout=10.0,
                            )
                except (TimeoutError, Exception) as e:
                    log.debug(
                        "shadow_settle_postbuild_pregate_check_failed",
                        error=str(e)[:120],
                        error_type=type(e).__name__,
                    )
                    # Fail-open: run full MPC if we can't check.
                    timeout_ok = True
            if not (timeout_ok or consent_ok):
                log.info(
                    "shadow_settle_pregate_skip_local_batch_below_min",
                    genius=getattr(audit_set, "genius_address", "?"),
                    idiot=getattr(audit_set, "idiot_address", "?"),
                    local_batch_size=len(batch),
                    audit_set_resolved=len(getattr(audit_set, "resolved_signals", []) or []),
                    min_batch=_MIN_BATCH_SIZE,
                )
                SHADOW_SETTLE_OUTCOME.labels(outcome="abstain_pregate_min_batch").inc()
                return None

        SHADOW_SETTLE_STAGE.labels(stage="post_postbuild_pregate").inc()

        # v1699 (P0-01): pre-MPC hasVoted gate. If this validator already
        # voted on the canonical batchKey and quorum is still pending, skip
        # MPC entirely. UID 1 metrics: of 21 completed shadow_settles, 16
        # ended at preflight_already_voted in submit-from-shadow — meaning
        # 16 expensive MPC runs computed a vote that submit_vote then
        # discarded. Detect at the entry to the MPC compute box and save
        # the compute.
        #
        # Stale-snapshot is handled inside has_voted_for_batch (returns
        # False,False so we re-vote on the new syncNonce). If hasVoted is
        # true AND finalized, mark_settled and abstain so the audit_set
        # stops bouncing on every cycle (mirrors the v1614 post-submit
        # pre_final invariant — we treat post-MPC and pre-MPC reads as
        # equivalent for the mark_settled decision because the chain
        # state read is the same).
        if self._chain_client is not None and batch:
            try:
                batch_pids = sorted([int(p.purchase_id) for p in batch if p.purchase_id])
                if batch_pids:
                    pre_voted, pre_final = await asyncio.wait_for(
                        self._chain_client.has_voted_for_batch(
                            getattr(audit_set, "genius_address", ""),
                            getattr(audit_set, "idiot_address", ""),
                            batch_pids,
                        ),
                        timeout=10.0,
                    )
                    if pre_final:
                        log.info(
                            "shadow_settle_pre_mpc_finalized_skip",
                            genius=getattr(audit_set, "genius_address", "?"),
                            idiot=getattr(audit_set, "idiot_address", "?"),
                            batch_size=len(batch),
                        )
                        # mark_settled so the audit_set stops bouncing each cycle.
                        try:
                            audit_set_store = getattr(self, "_audit_set_store", None)
                            if audit_set_store is not None:
                                audit_set_store.mark_settled(
                                    getattr(audit_set, "genius_address", ""),
                                    getattr(audit_set, "idiot_address", ""),
                                    getattr(audit_set, "cycle", 0),
                                )
                        except Exception as e:
                            log.debug(
                                "shadow_settle_pre_mpc_mark_settled_failed",
                                error=str(e)[:120],
                            )
                        SHADOW_SETTLE_OUTCOME.labels(outcome="abstain_pre_mpc_finalized").inc()
                        return None
                    if pre_voted:
                        log.info(
                            "shadow_settle_pre_mpc_already_voted_skip",
                            genius=getattr(audit_set, "genius_address", "?"),
                            idiot=getattr(audit_set, "idiot_address", "?"),
                            batch_size=len(batch),
                        )
                        SHADOW_SETTLE_OUTCOME.labels(outcome="abstain_pre_mpc_already_voted").inc()
                        return None
            except (TimeoutError, Exception) as e:
                log.debug(
                    "shadow_settle_pre_mpc_hasvoted_check_failed",
                    error=str(e)[:120],
                    error_type=type(e).__name__,
                )
                # Fail-open: run MPC if we can't check.

        # True signal_ids from the batch — only the signals that actually
        # built into PurchaseInputs (have local share + BPA/WPA + outcomes
        # + matching vector length). Using audit_set.signals.keys() would
        # include unresolved/missing-share/missing-BPA signals, causing
        # resolve_batch_participants to drop every peer that can't answer
        # share_info for one of those orphans — yielding discovered=0
        # even when every peer has every signal in the actual batch.
        signal_ids = [p.signal_id for p in batch]

        SHADOW_SETTLE_STAGE.labels(stage="pre_resolve_peers").inc()
        participant_map = await self.resolve_batch_participants(
            signal_ids=signal_ids,
            threshold=threshold,
        )
        SHADOW_SETTLE_STAGE.labels(stage="post_resolve_peers").inc()
        if participant_map is None:
            log.info(
                "shadow_settle_no_quorum",
                genius=audit_set.genius_address,
                idiot=audit_set.idiot_address,
                signal_count=len(signal_ids),
                threshold=threshold,
            )
            SHADOW_SETTLE_OUTCOME.labels(outcome="abstain_no_peers").inc()
            return None

        # Inject our own share_x for the first signal so we address
        # ourselves like any other peer in the participant set.
        local_rec = share_store.get(signal_ids[0])
        if local_rec is None:
            log.info(
                "shadow_settle_no_local_share",
                signal_id=signal_ids[0][:20],
            )
            SHADOW_SETTLE_OUTCOME.labels(outcome="abstain_no_share").inc()
            return None
        local_x = local_rec.share.x
        if local_x in participant_map:
            log.warning(
                "shadow_settle_local_x_collision",
                local_x=local_x,
                msg="metagraph returned a peer whose share_x equals ours; dropping it",
            )
            del participant_map[local_x]
        # For shadow mode, we need a way to address ourselves via HTTP.
        # The run_batch_settlement wrapper talks to peers via URLs, so
        # we insert our own URL under our own x. The handlers then
        # answer our own init call via the same auth-gated path any
        # peer would use — no special self-dispatch code.
        # v1685: address self via loopback to avoid NAT hairpin. See
        # ``_self_loopback_url`` for full reasoning. Pulled out so the
        # invariant ("self-URL is loopback, not external IP") is testable
        # without spinning the full shadow_settle harness.
        my_url = self._self_loopback_url()
        if my_url is None:
            log.info(
                "shadow_settle_no_self_url",
                msg="cannot address self over HTTP; skipping shadow run",
            )
            SHADOW_SETTLE_OUTCOME.labels(outcome="abstain_no_self_url").inc()
            return None
        participant_map[local_x] = {
            "uid": getattr(self._neuron, "uid", 0),
            "url": my_url,
            "hotkey": "",
        }

        # v1731: pre-probe each peer's /v1/identity. ReadTimeout dominates
        # protocol_failed (UID 1: 16 of 17 failures = 94%); a single peer
        # that accepts connections but never responds aborts the WHOLE batch
        # settle even though Shamir can reconstruct from k of n. Dropping
        # the slow peer up-front and running MPC with the remaining
        # participants saves the run. Pre-probe is cheap (~50ms healthy);
        # ReadTimeout pre-probe is bounded by the probe timeout, not the
        # 45s MPC PEER_TIMEOUT.
        local_x_self = local_x

        async def _peer_alive(peer_x: int, info: dict[str, Any]) -> bool:
            if peer_x == local_x_self:
                return True  # self always alive
            url = info.get("url", "")
            if not url:
                return False
            try:
                async with httpx.AsyncClient(timeout=httpx.Timeout(3.0, connect=2.0)) as c:
                    resp = await c.get(f"{url}/v1/identity")
                    return resp.status_code == 200
            except Exception:
                return False

        probe_results = await asyncio.gather(
            *[_peer_alive(x, info) for x, info in participant_map.items()],
            return_exceptions=True,
        )
        keys_in_order = list(participant_map.keys())
        alive_keys = [keys_in_order[i] for i, ok in enumerate(probe_results) if ok is True]
        dropped_keys = [k for k in keys_in_order if k not in alive_keys]
        if dropped_keys:
            log.info(
                "shadow_settle_peer_pre_probe_dropped",
                dropped=dropped_keys,
                kept=alive_keys,
                threshold=threshold,
            )
            for k in dropped_keys:
                participant_map.pop(k, None)

        participant_xs = sorted(participant_map.keys())
        if len(participant_xs) < threshold:
            log.info(
                "shadow_settle_participant_count_below_threshold",
                count=len(participant_xs),
                threshold=threshold,
                dropped=dropped_keys,
            )
            SHADOW_SETTLE_OUTCOME.labels(outcome="abstain_below_threshold").inc()
            return None

        triples = generate_batch_beaver_triples(
            batch,
            participant_xs=participant_xs,
            threshold=threshold,
        )

        import secrets as _secrets

        session_id = f"shadow-{audit_set.genius_address[:6]}-{audit_set.idiot_address[:6]}-{audit_set.cycle}-{_secrets.token_hex(3)}"

        SHADOW_SETTLE_STAGE.labels(stage="pre_run_mpc").inc()
        try:
            result = await self.run_batch_settlement(
                session_id=session_id,
                batch=batch,
                beaver_triples_per_purchase=triples,
                participant_peers=participant_map,
                threshold=threshold,
                local_x=local_x,
            )
        except Exception as e:
            SHADOW_SETTLE_STAGE.labels(stage="post_run_mpc").inc()
            log.warning(
                "shadow_settle_protocol_failed",
                session_id=session_id,
                error=str(e)[:200],
                error_type=type(e).__name__,
            )
            SHADOW_SETTLE_OUTCOME.labels(outcome="protocol_failed").inc()
            try:
                from djinn_validator.api.metrics import SHADOW_SETTLE_PROTOCOL_FAILURE

                SHADOW_SETTLE_PROTOCOL_FAILURE.labels(error_type=type(e).__name__).inc()
            except Exception:
                pass
            return None
        SHADOW_SETTLE_STAGE.labels(stage="post_run_mpc").inc()

        # total_notional approximation: sum PurchaseInputs.notional across
        # the batch. Over-counts voids vs. the local AuditResult path
        # (CF-06 excludes voids). Documented in ShadowSettleSubmitData
        # and in feature_flags.batch_settlement_http_submit.
        try:
            total_notional = sum(int(p.notional) for p in batch)
            purchase_ids = [int(p.purchase_id) for p in batch]
        except Exception as e:
            log.warning(
                "shadow_settle_submit_shape_failed",
                session_id=session_id,
                error=str(e)[:200],
            )
            SHADOW_SETTLE_OUTCOME.labels(outcome="protocol_failed").inc()
            return None

        # Sanity gate: a legitimate quality score is bounded by
        # ~max(|wpa|, |bpa|) * notional * purchase_count, which for Sepolia
        # test purchases lives in the 10^7–10^12 USDC-6dp range. Values
        # above ~100x the total notional almost certainly indicate an MPC
        # reconstruction gone wrong (bad shares, mismatched vector length,
        # unresolved outcomes) and land on-chain as BN254 field elements
        # that pollute OutcomeVoting quorums. Reject those locally so we
        # don't submit a garbage vote. Log with enough detail to debug
        # the upstream reconstruction failure.
        max_plausible = max(total_notional, 1) * 100
        if abs(result.total_score_change) > max_plausible:
            log.warning(
                "shadow_settle_score_out_of_range",
                session_id=session_id,
                quality_score=result.total_score_change,
                max_plausible=max_plausible,
                total_notional=total_notional,
                purchase_count=result.purchase_count,
                msg="MPC produced score that looks like a field-element artifact; refusing to submit",
            )
            SHADOW_SETTLE_OUTCOME.labels(outcome="quality_score_out_of_range").inc()
            return None

        SHADOW_SETTLE_OUTCOME.labels(outcome="completed").inc()
        return ShadowSettleSubmitData(
            genius=audit_set.genius_address,
            idiot=audit_set.idiot_address,
            cycle=getattr(audit_set, "cycle", 0),
            quality_score=result.total_score_change,
            total_notional=total_notional,
            purchase_ids=purchase_ids,
            session_id=session_id,
            purchase_count=result.purchase_count,
        )

    async def run_batch_settlement(
        self,
        *,
        session_id: str,
        batch: list[Any],
        beaver_triples_per_purchase: list[list[Any]],
        participant_peers: dict[int, dict[str, Any]],
        threshold: int,
        local_x: int | None = None,
    ) -> Any:
        """Drive a distributed batch settlement session as the coordinator.

        Thin wrapper that plugs the ``drive_http_batch_settlement``
        core driver into this orchestrator's existing signed-HTTP
        client + peer circuit breakers. The caller supplies:

            participant_peers: dict mapping each participant's
                Shamir x-coord to its peer metadata
                ({"uid": ..., "url": ..., "hotkey": ...}). If
                ``local_x`` is also supplied, its entry may be
                omitted from ``participant_peers`` and this
                orchestrator talks to itself via the same signed
                request path (via an in-process shortcut is not
                yet wired — current behavior requires the local
                validator to be addressable via its own URL just
                like any peer, which matches how MPC already runs
                for single-purchase flows).

        Args:
            session_id: unique session identifier; must match the
                string the peers will see in /v1/mpc/batch/init.
            batch: list of PurchaseInputs for the batch.
            beaver_triples_per_purchase: one list of BeaverTriple
                objects per purchase, aligned with ``batch``.
            participant_peers: x -> peer-dict map.
            threshold: reconstruction threshold (typically 3).
            local_x: this validator's own x-coord, for log context.

        Returns:
            BatchSettlementResult with the reconstructed total.
        """
        from djinn_validator.core.mpc_batch_settlement import (
            drive_http_batch_settlement,
        )

        _ENDPOINT_PATHS = {
            "init": "/v1/mpc/batch/init",
            "compute_gate": "/v1/mpc/batch/compute_gate",
            "accumulate": "/v1/mpc/batch/accumulate",
            "open": "/v1/mpc/batch/open",
        }

        async def _peer_rpc(vx: int, endpoint: str, payload: dict) -> dict:
            peer = participant_peers.get(vx)
            if peer is None:
                raise RuntimeError(f"no peer resolved for validator_x={vx} in batch session {session_id}")
            path = _ENDPOINT_PATHS.get(endpoint)
            if path is None:
                raise RuntimeError(f"unknown batch endpoint: {endpoint}")
            url = f"{peer['url']}{path}"
            resp = await self._peer_request(
                "post",
                url,
                peer_uid=peer.get("uid"),
                json=payload,
            )
            if resp.status_code != 200:
                raise RuntimeError(
                    f"peer {vx} ({peer.get('uid')}) {endpoint} failed: " f"{resp.status_code} {resp.text[:200]}"
                )
            return resp.json()

        participant_xs = sorted(participant_peers.keys())

        log.info(
            "batch_settlement_start",
            session_id=session_id,
            participants=len(participant_xs),
            local_x=local_x,
            threshold=threshold,
            purchase_count=len(batch),
        )

        result = await drive_http_batch_settlement(
            session_id=session_id,
            participant_xs=participant_xs,
            threshold=threshold,
            batch=batch,
            beaver_triples_per_purchase=beaver_triples_per_purchase,
            peer_rpc=_peer_rpc,
        )

        log.info(
            "batch_settlement_complete",
            session_id=session_id,
            total_score_change=result.total_score_change,
            purchase_count=result.purchase_count,
        )
        return result

    async def _broadcast_abort(
        self,
        session_id: str,
        peers: list[dict[str, Any]],
        gate_idx: int,
        reason: str,
        offending_x: int | None = None,
    ) -> None:
        """Broadcast an abort message to all peers when MAC verification fails.

        Marks the local session as FAILED and notifies all active peers
        so they can clean up their participant state.
        """
        # Mark local session as failed
        session = self._coordinator.get_session(session_id)
        if session is not None:
            with self._coordinator._lock:
                session.status = SessionStatus.FAILED

        log.warning(
            "mpc_abort_broadcast",
            session_id=session_id,
            gate_idx=gate_idx,
            reason=reason,
            offending_x=offending_x,
            n_peers=len(peers),
        )

        payload = {
            "session_id": session_id,
            "reason": reason,
            "gate_idx": gate_idx,
            "offending_validator_x": offending_x,
        }

        for peer in peers:
            try:
                await self._peer_request("post", f"{peer['url']}/v1/mpc/abort", peer_uid=peer.get("uid"), json=payload)
            except (httpx.HTTPError, Exception) as e:
                log.warning(
                    "mpc_abort_send_failed",
                    peer_uid=peer.get("uid"),
                    error=str(e),
                )

    async def _generate_ot_triples_via_network(
        self,
        session_id: str,
        peer: dict[str, Any],
        n_triples: int,
        participant_xs: list[int],
        my_x: int,
        dh_group: Any | None = None,
        field_prime: int = BN254_PRIME,
    ) -> list[BeaverTriple] | None:
        """Generate Beaver triples via 2-party OT over HTTP.

        Runs the 4-phase Gilboa OT protocol with a single peer:
        1. Setup — both parties initialize OT state, exchange sender PKs
        2. Choices — exchange receiver choice commitments
        3. Transfers — exchange encrypted OT messages
        4. Complete — decrypt, accumulate, compute Shamir evaluations
        5. Collect partial Shamir evaluations and combine into BeaverTriples

        Neither party learns the other's additive shares. The coordinator
        collects Shamir evaluations at all x_coords to form the final
        BeaverTriple objects for distribution.

        Currently supports 2-party case only (coordinator + 1 peer).
        For n > 2, peer-to-peer connections are needed.
        """
        from djinn_validator.core.ot_network import DEFAULT_DH_GROUP

        if dh_group is None:
            dh_group = DEFAULT_DH_GROUP
        p = field_prime

        # Create coordinator's local OT state
        coord_state = OTTripleGenState(
            session_id=session_id,
            party_role="coordinator",
            n_triples=n_triples,
            x_coords=participant_xs,
            threshold=self._threshold,
            prime=p,
            dh_group=dh_group,
        )
        coord_state.initialize()

        try:
            # Phase 1: Setup — initialize peer's OT state
            setup_payload: dict[str, Any] = {
                "session_id": session_id,
                "n_triples": n_triples,
                "x_coords": participant_xs,
                "threshold": self._threshold,
            }
            # Pass custom field prime / DH group if non-default
            if p != BN254_PRIME:
                setup_payload["field_prime"] = hex(p)
            if dh_group is not DEFAULT_DH_GROUP:
                setup_payload["dh_prime"] = hex(dh_group.prime)

            setup_resp = await self._peer_request(
                "post",
                f"{peer['url']}/v1/mpc/ot/setup",
                peer_uid=peer.get("uid"),
                json=setup_payload,
            )
            if setup_resp.status_code != 200 or not setup_resp.json().get("accepted"):
                log.warning("ot_setup_failed", peer_uid=peer.get("uid"), status=setup_resp.status_code)
                return None

            peer_sender_pks = {
                int(t): deserialize_dh_public_key(pk_hex)
                for t, pk_hex in setup_resp.json()["sender_public_keys"].items()
            }

            # Phase 2: Exchange choices (bidirectional)
            # Direction A: coordinator is sender → get peer's receiver choices
            coord_sender_pks_ser = {
                str(t): serialize_dh_public_key(pk, dh_group) for t, pk in coord_state.get_sender_public_keys().items()
            }
            choices_resp = await self._peer_request(
                "post",
                f"{peer['url']}/v1/mpc/ot/choices",
                peer_uid=peer.get("uid"),
                json={"session_id": session_id, "peer_sender_pks": coord_sender_pks_ser},
            )
            if choices_resp.status_code != 200:
                log.warning("ot_choices_failed", peer_uid=peer.get("uid"), status=choices_resp.status_code)
                return None

            peer_choices = {int(t): deserialize_choices(c) for t, c in choices_resp.json()["choices"].items()}

            # Direction B: peer is sender → coordinator generates receiver choices
            coord_choices = coord_state.generate_receiver_choices(peer_sender_pks)

            # Phase 3: Exchange transfers (bidirectional)
            # Direction A: coordinator processes peer's choices using coordinator's sender
            coord_transfers, coord_sender_shares = coord_state.process_sender_choices(peer_choices)

            # Direction B: send coordinator's choices to peer's sender
            coord_choices_ser = {str(t): serialize_choices(c, dh_group) for t, c in coord_choices.items()}
            transfers_resp = await self._peer_request(
                "post",
                f"{peer['url']}/v1/mpc/ot/transfers",
                peer_uid=peer.get("uid"),
                json={"session_id": session_id, "peer_choices": coord_choices_ser},
            )
            if transfers_resp.status_code != 200:
                log.warning("ot_transfers_failed", peer_uid=peer.get("uid"), status=transfers_resp.status_code)
                return None

            transfer_data = transfers_resp.json()
            peer_transfers = {int(t): deserialize_transfers(pairs) for t, pairs in transfer_data["transfers"].items()}
            peer_sender_shares_hex = transfer_data["sender_shares"]

            # Phase 4: Decrypt & accumulate (both directions)
            # Coordinator decrypts peer's transfers (direction B: peer is sender)
            coord_receiver_shares = coord_state.decrypt_receiver_transfers(peer_transfers)
            coord_state.accumulate_ot_shares(coord_sender_shares, coord_receiver_shares)
            coord_state.compute_shamir_evaluations()

            # Send coordinator's transfers to peer for decryption (direction A)
            coord_transfers_ser = {str(t): serialize_transfers(pairs) for t, pairs in coord_transfers.items()}
            complete_resp = await self._peer_request(
                "post",
                f"{peer['url']}/v1/mpc/ot/complete",
                peer_uid=peer.get("uid"),
                json={
                    "session_id": session_id,
                    "peer_transfers": coord_transfers_ser,
                    "own_sender_shares": peer_sender_shares_hex,
                },
            )
            if complete_resp.status_code != 200 or not complete_resp.json().get("completed"):
                log.warning("ot_complete_failed", peer_uid=peer.get("uid"), status=complete_resp.status_code)
                return None

            # Phase 5: Collect Shamir evaluations and combine
            # Get peer's evaluations at each x_coord
            peer_evals: dict[int, list[dict[str, int]]] = {}
            for x in participant_xs:
                shares_resp = await self._peer_request(
                    "post",
                    f"{peer['url']}/v1/mpc/ot/shares",
                    peer_uid=peer.get("uid"),
                    json={"session_id": session_id, "party_x": x},
                )
                if shares_resp.status_code != 200:
                    log.warning("ot_shares_failed", peer_uid=peer.get("uid"), party_x=x)
                    return None
                peer_evals[x] = [
                    {"a": int(s["a"], 16), "b": int(s["b"], 16), "c": int(s["c"], 16)}
                    for s in shares_resp.json()["triple_shares"]
                ]

        except (httpx.HTTPError, KeyError, ValueError, json.JSONDecodeError) as e:
            log.warning(
                "ot_network_error",
                peer_uid=peer.get("uid"),
                error_type=type(e).__name__,
                error=str(e),
            )
            return None
        except OTReceiverNotReadyError as e:
            # Local coordinator's background modexp thread didn't finish.
            # Treat as a transient failure so the caller falls back to local
            # triple generation instead of crashing the MPC session.
            log.warning(
                "ot_receiver_not_ready_local",
                peer_uid=peer.get("uid"),
                error=str(e),
            )
            return None

        # Combine coordinator + peer Shamir evaluations into BeaverTriples
        triples: list[BeaverTriple] = []
        for t_idx in range(n_triples):
            a_shares = []
            b_shares = []
            c_shares = []
            for x in participant_xs:
                coord_s = coord_state.get_shamir_shares_for_party(x)
                if coord_s is None:
                    return None
                peer_s = peer_evals[x]
                a_val = (coord_s[t_idx]["a"] + peer_s[t_idx]["a"]) % p
                b_val = (coord_s[t_idx]["b"] + peer_s[t_idx]["b"]) % p
                c_val = (coord_s[t_idx]["c"] + peer_s[t_idx]["c"]) % p
                a_shares.append(Share(x=x, y=a_val))
                b_shares.append(Share(x=x, y=b_val))
                c_shares.append(Share(x=x, y=c_val))
            triples.append(
                BeaverTriple(
                    a_shares=tuple(a_shares),
                    b_shares=tuple(b_shares),
                    c_shares=tuple(c_shares),
                )
            )

        log.info(
            "ot_triples_generated_via_network",
            n_triples=n_triples,
            peer_uid=peer.get("uid"),
        )
        return triples

    async def precompute_triples_for_signal(
        self,
        signal_id: str,
        share_x: int,
        n_triples: int = 10,
    ) -> list[Any] | None:
        """Pre-generate Beaver triples for a signal's future MPC purchase.

        Called asynchronously after share storage. Triples are input-independent
        so they can be generated before any purchase request exists.
        If peers are not available (signal too new, validators haven't all received
        shares yet), this fails silently and triples will be generated on-the-fly
        during purchase.
        """
        peers = self._get_peer_validators()
        if not peers:
            return None

        # Find a peer that holds this signal
        target_peer = None
        for peer in peers:
            try:
                resp = await self._peer_request(
                    "get",
                    f"{peer['url']}/v1/signal/{signal_id}/share_info",
                    peer_uid=peer["uid"],
                )
                if resp and resp.status_code == 200:
                    target_peer = peer
                    break
            except Exception:
                continue

        if not target_peer:
            return None

        # Generate triples via OT with the first available peer
        participant_xs = sorted({share_x, resp.json().get("share_x", 1)})
        if len(participant_xs) < 2:
            return None

        try:
            session_id = f"precompute-{signal_id}-{secrets.token_hex(4)}"
            triples = await self._generate_ot_triples_via_network(
                session_id=session_id,
                peer=target_peer,
                n_triples=n_triples,
                participant_xs=participant_xs,
                my_x=share_x,
                dh_group=self._ot_dh_group,
                field_prime=self._ot_field_prime or BN254_PRIME,
            )
            return triples
        except Exception:
            return None

    async def _distributed_mpc_membership(
        self,
        signal_id: str,
        local_share: Share,
        available_indices: set[int],
        peers: list[dict[str, Any]],
        threshold: int | None = None,
    ) -> MPCResult | None:
        """Run the masked polynomial set-membership MPC over HTTP.

        O(log k) round count vs. the legacy O(k) sequential-gate protocol.
        Protocol details + security argument: mpc_membership.py docstring.

        Flow:
          1. Discover peer share_x values (reuses existing share_info endpoint).
          2. Generate Beaver triples + random mask s (trusted-dealer model —
             same as the legacy path).
          3. POST /v1/mpc/membership/init to every peer.
          4. For each round in plan_parallel_powers:
               POST /v1/mpc/membership/round to each peer in parallel.
               Coordinator opens d, e for each op.
               Opened values flow into the NEXT round's request.
          5. POST /v1/mpc/membership/finalize_mask with final opened + public coeffs.
          6. Coordinator opens mask (d, e).
          7. POST /v1/mpc/membership/reveal to each peer.
          8. Coordinator interpolates product shares. Zero => membership.

        Returns None if any HTTP step catastrophically fails. Callers
        interpret None as "unavailable fail-safe" just like the legacy
        path.
        """
        from djinn_validator.api.metrics import MPC_ERRORS
        from djinn_validator.core.mpc import (
            _split_secret_at_points,
            generate_beaver_triples,
            reconstruct_at_zero,
        )
        from djinn_validator.core.mpc_membership import (
            MembershipOpenedPower,
            MembershipPeerState,
            MembershipRoundOp,
            plan_parallel_powers,
            polynomial_from_roots,
        )
        from djinn_validator.utils.crypto import BN254_PRIME

        p = BN254_PRIME
        my_x = local_share.x
        sorted_avail = sorted(available_indices)
        t = threshold if threshold is not None else self._threshold

        if not sorted_avail:
            return MPCResult(
                available=False,
                participating_validators=1,
                failure_reason="no_available_indices",
            )

        # Discover peer share_x values via existing share_info endpoint.
        # Reuses the same early-termination-on-enough-peers logic as
        # _distributed_mpc so both protocols see identical peer sets.
        peer_x_map: dict[int, int] = {}

        async def _lookup_share_x(peer: dict[str, Any]) -> tuple[int, int] | None:
            try:
                resp = await self._peer_request(
                    "get",
                    f"{peer['url']}/v1/signal/{signal_id}/share_info",
                    peer_uid=peer["uid"],
                )
                if resp is not None and resp.status_code == 200:
                    data = resp.json()
                    return peer["uid"], data["share_x"]
            except (httpx.HTTPError, KeyError, ValueError, AttributeError) as e:
                log.debug("peer_share_x_lookup_failed", peer_uid=peer["uid"], error=str(e))
            return None

        needed_peers = t - 1
        tasks = [asyncio.create_task(_lookup_share_x(pr)) for pr in peers]
        if tasks:
            deadline = asyncio.get_running_loop().time() + GATHER_TIMEOUT
            pending = set(tasks)
            while pending:
                remaining = deadline - asyncio.get_running_loop().time()
                if remaining <= 0:
                    break
                done_batch, pending = await asyncio.wait(
                    pending,
                    timeout=remaining,
                    return_when=asyncio.FIRST_COMPLETED,
                )
                for dtask in done_batch:
                    try:
                        res = dtask.result()
                        if isinstance(res, tuple) and res is not None:
                            peer_x_map[res[0]] = res[1]
                    except Exception:
                        pass
                if len(peer_x_map) >= needed_peers:
                    break
            for ptask in pending:
                ptask.cancel()

        active_peers = [pr for pr in peers if pr["uid"] in peer_x_map]
        raw_xs = [my_x] + [peer_x_map[pr["uid"]] for pr in active_peers]
        participant_xs = sorted(set(x for x in raw_xs if 1 <= x <= 255))

        if len(participant_xs) < t:
            MPC_ERRORS.labels(reason="insufficient_peers").inc()
            log.warning(
                "membership_insufficient_participants",
                available=len(participant_xs),
                threshold=t,
                my_x=my_x,
            )
            return MPCResult(
                available=False,
                participating_validators=len(participant_xs),
                failure_reason=f"insufficient_peers:{len(participant_xs)}/{t}",
            )

        # Build round plan (public, pure arithmetic).
        k = len(sorted_avail)
        raw_plan = plan_parallel_powers(k) if k >= 2 else []
        rounds_plan: list[list[MembershipRoundOp]] = []
        gate_cursor = 0
        for round_ops in raw_plan:
            typed: list[MembershipRoundOp] = []
            for a_pow, b_pow in round_ops:
                typed.append(MembershipRoundOp(gate_cursor, a_pow, b_pow))
                gate_cursor += 1
            rounds_plan.append(typed)
        n_power_gates = gate_cursor
        n_triples = n_power_gates + 1

        # Generate triples + mask as trusted dealer.
        triples = generate_beaver_triples(
            n_triples,
            n=len(participant_xs),
            k=t,
            prime=p,
            x_coords=participant_xs,
        )
        import secrets as _secrets

        mask_scalar = _secrets.randbelow(p - 1) + 1
        mask_shares_list = _split_secret_at_points(mask_scalar, participant_xs, t, p)
        mask_share_by_x = {sh.x: sh.y for sh in mask_shares_list}
        x_idx = {vx: i for i, vx in enumerate(participant_xs)}

        # Build local state for the coordinator itself.
        my_triple_a = [triples[g].a_shares[x_idx[my_x]].y for g in range(n_triples)]
        my_triple_b = [triples[g].b_shares[x_idx[my_x]].y for g in range(n_triples)]
        my_triple_c = [triples[g].c_shares[x_idx[my_x]].y for g in range(n_triples)]
        my_state = MembershipPeerState(
            validator_x=my_x,
            threshold=t,
            available_indices=list(sorted_avail),
            triple_a=my_triple_a,
            triple_b=my_triple_b,
            triple_c=my_triple_c,
            mask_share=mask_share_by_x[my_x],
        )
        my_state.set_initial_secret_share(local_share.y)

        session_id = f"memship-{signal_id[:32]}-{_secrets.token_hex(8)}"

        # Init peers via HTTP.
        async def _post_init(peer: dict[str, Any]) -> bool:
            vx = peer_x_map[peer["uid"]]
            try:
                body = {
                    "session_id": session_id,
                    "signal_id": signal_id,
                    "coordinator_x": my_x,
                    "participant_xs": participant_xs,
                    "threshold": t,
                    "available_indices": sorted_avail,
                    "triple_a": [hex(triples[g].a_shares[x_idx[vx]].y) for g in range(n_triples)],
                    "triple_b": [hex(triples[g].b_shares[x_idx[vx]].y) for g in range(n_triples)],
                    "triple_c": [hex(triples[g].c_shares[x_idx[vx]].y) for g in range(n_triples)],
                    "mask_share": hex(mask_share_by_x[vx]),
                }
                resp = await self._peer_request(
                    "post",
                    f"{peer['url']}/v1/mpc/membership/init",
                    peer_uid=peer["uid"],
                    json=body,
                )
                return resp is not None and resp.status_code == 200
            except Exception as e:
                log.warning("membership_init_failed", peer_uid=peer["uid"], error=str(e))
                return False

        init_results = await asyncio.gather(
            *[_post_init(p_) for p_ in active_peers],
            return_exceptions=True,
        )
        ok_peers = [p_ for p_, ok in zip(active_peers, init_results, strict=False) if ok is True]
        if len(ok_peers) + 1 < t:
            return MPCResult(
                available=False,
                participating_validators=len(ok_peers) + 1,
                failure_reason=f"membership_init_insufficient:{len(ok_peers)+1}/{t}",
            )

        # Drive rounds.
        prev_opened: list[MembershipOpenedPower] = []
        for round_idx, round_ops in enumerate(rounds_plan):
            ops_payload = [{"gate_idx": op.gate_idx, "a_pow": op.a_pow, "b_pow": op.b_pow} for op in round_ops]
            prev_opened_payload = [
                {
                    "gate_idx": o.gate_idx,
                    "target_pow": o.target_pow,
                    "opened_d": hex(o.opened_d),
                    "opened_e": hex(o.opened_e),
                }
                for o in prev_opened
            ]

            # Coordinator runs locally.
            if prev_opened:
                my_state.finalize_round(prev_opened)
            my_de = my_state.compute_round(round_ops)
            my_de_by_gate = {g: (d, e) for (g, d, e) in my_de}

            async def _post_round(peer: dict[str, Any]) -> tuple[int, list[tuple[int, int, int]]] | None:
                try:
                    resp = await self._peer_request(
                        "post",
                        f"{peer['url']}/v1/mpc/membership/round",
                        peer_uid=peer["uid"],
                        json={
                            "session_id": session_id,
                            "round_idx": round_idx,
                            "ops": ops_payload,
                            "prev_opened": prev_opened_payload,
                        },
                    )
                    if resp is None or resp.status_code != 200:
                        return None
                    data = resp.json()
                    return peer_x_map[peer["uid"]], [
                        (op["gate_idx"], int(op["d_share"], 16), int(op["e_share"], 16)) for op in data["op_shares"]
                    ]
                except Exception as e:
                    log.warning("membership_round_failed", peer_uid=peer["uid"], round_idx=round_idx, error=str(e))
                    return None

            peer_round_results = await asyncio.gather(
                *[_post_round(p_) for p_ in ok_peers],
                return_exceptions=True,
            )

            # Reconstruct opened d, e for each op in this round.
            per_op_d: dict[int, dict[int, int]] = {op.gate_idx: {} for op in round_ops}
            per_op_e: dict[int, dict[int, int]] = {op.gate_idx: {} for op in round_ops}
            for op in round_ops:
                per_op_d[op.gate_idx][my_x] = my_de_by_gate[op.gate_idx][0]
                per_op_e[op.gate_idx][my_x] = my_de_by_gate[op.gate_idx][1]
            for result in peer_round_results:
                if not isinstance(result, tuple):
                    continue
                peer_x, de_list = result
                for g, d, e in de_list:
                    per_op_d[g][peer_x] = d
                    per_op_e[g][peer_x] = e

            new_opened: list[MembershipOpenedPower] = []
            for op in round_ops:
                d_shares = per_op_d[op.gate_idx]
                e_shares = per_op_e[op.gate_idx]
                if len(d_shares) < t:
                    log.warning(
                        "membership_round_insufficient",
                        round_idx=round_idx,
                        gate_idx=op.gate_idx,
                        got=len(d_shares),
                        need=t,
                    )
                    return MPCResult(
                        available=False,
                        participating_validators=len(d_shares),
                        failure_reason=f"membership_round_{round_idx}_insufficient:{len(d_shares)}/{t}",
                    )
                opened_d = reconstruct_at_zero(d_shares, p)
                opened_e = reconstruct_at_zero(e_shares, p)
                new_opened.append(
                    MembershipOpenedPower(
                        gate_idx=op.gate_idx,
                        target_pow=op.a_pow + op.b_pow,
                        opened_d=opened_d,
                        opened_e=opened_e,
                    )
                )
            prev_opened = new_opened

        # Finalize mask: run [q] linear combination and compute (d, e) for
        # the [s]*[q] multiply. Public coefficients are sent once.
        coefficients = polynomial_from_roots(list(sorted_avail), p)
        coeff_hex = [hex(c) for c in coefficients]

        # Coordinator runs locally.
        if prev_opened:
            my_state.finalize_round(prev_opened)
        my_state.compute_q_share(coefficients)
        my_mask_d, my_mask_e = my_state.compute_mask_multiply_shares()

        final_opened_payload = [
            {
                "gate_idx": o.gate_idx,
                "target_pow": o.target_pow,
                "opened_d": hex(o.opened_d),
                "opened_e": hex(o.opened_e),
            }
            for o in prev_opened
        ]

        async def _post_finalize(peer: dict[str, Any]) -> tuple[int, int, int] | None:
            try:
                resp = await self._peer_request(
                    "post",
                    f"{peer['url']}/v1/mpc/membership/finalize_mask",
                    peer_uid=peer["uid"],
                    json={
                        "session_id": session_id,
                        "final_opened": final_opened_payload,
                        "coefficients": coeff_hex,
                    },
                )
                if resp is None or resp.status_code != 200:
                    return None
                data = resp.json()
                return (
                    peer_x_map[peer["uid"]],
                    int(data["mask_d_share"], 16),
                    int(data["mask_e_share"], 16),
                )
            except Exception as e:
                log.warning("membership_finalize_failed", peer_uid=peer["uid"], error=str(e))
                return None

        finalize_results = await asyncio.gather(
            *[_post_finalize(p_) for p_ in ok_peers],
            return_exceptions=True,
        )
        mask_d_shares: dict[int, int] = {my_x: my_mask_d}
        mask_e_shares: dict[int, int] = {my_x: my_mask_e}
        for r in finalize_results:
            if isinstance(r, tuple):
                vx, d, e = r
                mask_d_shares[vx] = d
                mask_e_shares[vx] = e
        if len(mask_d_shares) < t:
            return MPCResult(
                available=False,
                participating_validators=len(mask_d_shares),
                failure_reason=f"membership_finalize_insufficient:{len(mask_d_shares)}/{t}",
            )
        mask_opened_d = reconstruct_at_zero(mask_d_shares, p)
        mask_opened_e = reconstruct_at_zero(mask_e_shares, p)

        # Reveal: collect final product shares and interpolate.
        my_product = my_state.compute_product_share(mask_opened_d, mask_opened_e)

        async def _post_reveal(peer: dict[str, Any]) -> tuple[int, int] | None:
            try:
                resp = await self._peer_request(
                    "post",
                    f"{peer['url']}/v1/mpc/membership/reveal",
                    peer_uid=peer["uid"],
                    json={
                        "session_id": session_id,
                        "mask_opened_d": hex(mask_opened_d),
                        "mask_opened_e": hex(mask_opened_e),
                    },
                )
                if resp is None or resp.status_code != 200:
                    return None
                data = resp.json()
                return peer_x_map[peer["uid"]], int(data["product_share"], 16)
            except Exception as e:
                log.warning("membership_reveal_failed", peer_uid=peer["uid"], error=str(e))
                return None

        reveal_results = await asyncio.gather(
            *[_post_reveal(p_) for p_ in ok_peers],
            return_exceptions=True,
        )
        product_shares: dict[int, int] = {my_x: my_product}
        for r in reveal_results:
            if isinstance(r, tuple):
                vx, ps = r
                product_shares[vx] = ps
        if len(product_shares) < t:
            return MPCResult(
                available=False,
                participating_validators=len(product_shares),
                failure_reason=f"membership_reveal_insufficient:{len(product_shares)}/{t}",
            )
        revealed = reconstruct_at_zero(product_shares, p)

        log.info(
            "membership_completed",
            signal_id=signal_id[:20],
            n_participants=len(product_shares),
            k=k,
            rounds=len(rounds_plan) + 2,
            in_set=(revealed == 0),
        )
        # Normal negative MPC result (revealed != 0) is NOT a failure. The
        # protocol ran to completion and correctly determined the real
        # index is not in the requested set. failure_reason is reserved
        # for actual protocol failures (insufficient peers etc).
        return MPCResult(
            available=(revealed == 0),
            participating_validators=len(product_shares),
        )

    def _single_validator_check(
        self,
        share: Share,
        available_indices: set[int],
    ) -> MPCResult:
        """Prototype single-validator availability check.

        Uses threshold=1 reconstruction for dev/testing mode.
        NOT used in production — the distributed path with /v1/mpc/finalize
        ensures no single validator can reconstruct the secret.
        """
        all_xs = [share.x]
        contrib = compute_local_contribution(share, all_xs)
        return check_availability([contrib], available_indices, threshold=1)
