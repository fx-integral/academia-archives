"""FastAPI server for the Djinn validator REST API.

Endpoints from Appendix A of the whitepaper:
- POST /v1/signal                    -- Accept encrypted key shares from Genius
- POST /v1/signal/{id}/purchase      -- Handle buyer purchase (MPC + share release)
- POST /v1/signal/{id}/register      -- Register purchased signal for outcome tracking
- POST /v1/signal/{id}/check-odds    -- Fetch BPA/WPA odds for a signal at purchase time
- POST /v1/signal/{id}/outcome       -- Submit outcome attestation
- POST /v1/signals/resolve           -- Resolve all pending signal outcomes
- PUT  /v1/preferences/{address}     -- Store buyer preferences (books, encrypted data)
- GET  /v1/preferences/{address}     -- Retrieve buyer preferences
- POST /v1/attest                    -- Web attestation: TLSNotary proof of any URL (S15)
- POST /v1/notary/session            -- Assign a notary miner for external provers (browser extensions)
- POST /v1/analytics/attempt         -- Fire-and-forget analytics
- GET  /health                       -- Health check

Inter-validator MPC endpoints:
- POST /v1/mpc/init                  -- Accept MPC session invitation
- POST /v1/mpc/round1               -- Submit Round 1 multiplication messages
- POST /v1/mpc/result               -- Accept coordinator's final result
- GET  /v1/mpc/{session_id}/status   -- Check MPC session status
"""

from __future__ import annotations

import asyncio
import ipaddress
import json
import os
import re
import socket
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

# Module-load timestamp = process start (the validator imports server.py
# exactly once, at uvicorn boot). Surfaced on /health.process_started_ts
# so dashboards can render "restarted 4m ago" alongside the static
# "deployed at" git_commit_ts. Captured at import time, never updated.
_PROCESS_STARTED_TS = int(time.time())


def _egress_self_reported_or_none() -> str | None:
    try:
        from djinn_validator.utils.egress_publisher import get_self_detected_ip

        return get_self_detected_ip()
    except Exception:
        return None


import httpx
import structlog
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from starlette.responses import JSONResponse as StarletteJSONResponse
from web3 import Web3

from djinn_validator.api.metrics import (
    ACTIVE_SHARES,
    ATTESTATION_DISPATCHED,
    ATTESTATION_DURATION,
    ATTESTATION_VERIFIED,
    BT_CONNECTED,
    MPC_ACTIVE_SESSIONS,
    NOTARY_SESSIONS_ASSIGNED,
    OUTCOMES_ATTESTED,
    PURCHASES_PROCESSED,
    SHARES_STORED,
    UPTIME_SECONDS,
    metrics_response,
)
from djinn_validator.api.middleware import (
    RateLimiter,
    RateLimitMiddleware,
    RequestIdMiddleware,
    get_cors_origins,
    require_admin_auth,
    validate_signed_request,
)
from djinn_validator.api.models import (
    AnalyticsRequest,
    AttestRequest,
    AttestResponse,
    AuditGossipRequest,
    AuditGossipResponse,
    AuditSetStatusResponse,
    AuditSummaryResponse,
    BookPrice,
    CanonicalOddsObservation,
    CanonicalOddsRequest,
    CanonicalOddsResponse,
    CheckOddsRequest,
    CheckOddsResponse,
    CircuitBreakerAppealRequest,
    CircuitBreakerAppealResponse,
    CircuitBreakerStatusResponse,
    HealthResponse,
    IdentityResponse,
    LineOdds,
    MembershipFinalizeMaskRequest,
    MembershipFinalizeMaskResponse,
    MembershipInitRequest,
    MembershipInitResponse,
    MembershipRevealRequest,
    MembershipRevealResponse,
    MembershipRoundOpShare,
    MembershipRoundRequest,
    MembershipRoundResponse,
    MPCAbortRequest,
    MPCAbortResponse,
    MPCBatchAccumulateRequest,
    MPCBatchAccumulateResponse,
    MPCBatchComputeGateRequest,
    MPCBatchComputeGateResponse,
    MPCBatchInitRequest,
    MPCBatchInitResponse,
    MPCBatchOpenRequest,
    MPCBatchOpenResponse,
    MPCComputeGateRequest,
    MPCComputeGateResponse,
    MPCFinalizeRequest,
    MPCFinalizeResponse,
    MPCInitRequest,
    MPCInitResponse,
    MPCResultRequest,
    MPCResultResponse,
    MPCRound1Request,
    MPCRound1Response,
    MPCSessionStatusResponse,
    NotarySessionResponse,
    OTChoicesRequest,
    OTChoicesResponse,
    OTCompleteRequest,
    OTCompleteResponse,
    OTSetupRequest,
    OTSetupResponse,
    OTSharesRequest,
    OTSharesResponse,
    OTTransfersRequest,
    OTTransfersResponse,
    OutcomeGossipRequest,
    OutcomeGossipResponse,
    OutcomeRequest,
    OutcomeResponse,
    PreferencesResponse,
    PurchaseOddsGossipRequest,
    PurchaseOddsGossipResponse,
    PurchaseRequest,
    PurchaseResponse,
    ReadinessResponse,
    RegisterSignalRequest,
    RegisterSignalResponse,
    ResolveResponse,
    SetPreferencesRequest,
    ShareInfoResponse,
    ShareRecoveryResponse,
    StoreShareBundleRequest,
    StoreShareBundleResponse,
    ValidatorPeerHint,
)
from djinn_validator.core.activity import ActivityBuffer
from djinn_validator.core.audit_set import AuditSetStore
from djinn_validator.core.mpc import (
    DistributedParticipantState,
    MPCResult,
    Round1Message,
)
from djinn_validator.core.mpc_coordinator import MPCCoordinator, SessionStatus
from djinn_validator.core.mpc_orchestrator import MPCOrchestrator
from djinn_validator.core.outcomes import (
    SUPPORTED_SPORTS,
    Outcome,
    OutcomeAttestor,
    SignalMetadata,
    parse_pick,
)
from djinn_validator.core.purchase import PurchaseOrchestrator, PurchaseStatus
from djinn_validator.core.purchase_odds_ledger import PurchaseOddsLedger
from djinn_validator.core.scoring import MinerScorer
from djinn_validator.core.shares import ShareStore, SignalShareRecord
from djinn_validator.core.telemetry import TelemetryStore
from djinn_validator.utils.circuit_breaker import CircuitBreaker
from djinn_validator.utils.crypto import BN254_PRIME, Share

_SIGNAL_ID_PATH_RE = re.compile(r"^[a-zA-Z0-9_\-]{1,256}$")

# Per-signal asyncio locks for purchase endpoint race-condition prevention (R25-15)
_purchase_locks: dict[str, asyncio.Lock] = {}
_purchase_locks_guard = asyncio.Lock()


def _validate_signal_id_path(signal_id: str) -> None:
    """Validate signal_id path parameter format."""
    if not _SIGNAL_ID_PATH_RE.match(signal_id):
        raise HTTPException(status_code=400, detail="Invalid signal_id format")


def _parse_field_hex(value: str, name: str) -> int:
    """Parse a hex string to int, validating it's a valid BN254 field element."""
    if not isinstance(value, str) or len(value) > 66:
        raise HTTPException(status_code=400, detail=f"{name} must be a hex string of at most 66 chars")
    try:
        v = int(value, 16)
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail=f"Invalid hex encoding for {name}")
    if v < 0 or v >= BN254_PRIME:
        raise HTTPException(
            status_code=400,
            detail=f"{name} must be a valid field element (0 <= v < BN254_PRIME)",
        )
    return v


def _signal_id_to_uint256(signal_id: str) -> int:
    """Convert a string signal ID to a uint256 for on-chain lookups.

    Signal IDs are numeric uint256 values assigned by the SignalCommitment
    contract. The web client passes them as decimal strings.
    """
    try:
        v = int(signal_id)
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail=f"Invalid signal ID: {signal_id!r}")
    if v < 0 or v >= 2**256:
        raise HTTPException(status_code=400, detail="Signal ID out of uint256 range")
    return v


if TYPE_CHECKING:
    from djinn_validator.bt.neuron import DjinnValidator
    from djinn_validator.chain.contracts import ChainClient
    from djinn_validator.core.attestation_log import AttestationLog

log = structlog.get_logger()


# Cache last-known-good settlement_registered per signer to smooth transient
# RPC flap on /health. OTF's upstream Base Sepolia RPC for v189 has been
# flapping for 10+ iterations per UX_FINDINGS 2026-04-20 16:54Z; the raw
# on-chain probe returns None during the flap, which (without this cache)
# surfaces as a yo-yoing "Settlement Registered: unknown" on the dashboard.
# Sticky-positive behavior: once we see True, subsequent None within 60s is
# masked to True. False always passes through (never mask a real
# deregistration). Keyed by signer EOA so different validators' caches
# don't collide if the process is ever shared-tenant.
#
# Each entry is (value, probe_start_ns). Writes use probe-start time
# (captured before the await, in monotonic nanoseconds) so two concurrent
# probes can't have a slow-returning stale True overwrite a newer False:
# the older write loses the compare-and-set. Nanosecond resolution is
# used so two in-flight probes within the same millisecond are still
# strictly ordered on the single-threaded event loop.
_SETTLEMENT_REG_CACHE: dict[str, tuple[bool, int]] = {}
_SETTLEMENT_REG_CACHE_TTL_NS = 60 * 10**9


async def _probe_settlement_registered_cached(chain_client: ChainClient, signer: str) -> bool | None:
    """Probe OutcomeVoting.isValidator(signer) with transient-flap smoothing.

    Returns True/False definitively when the RPC answers; returns True
    (from cache) when the live probe returns None AND we saw True within
    the last 60 seconds; returns None otherwise (inconclusive). False
    always passes through — we never mask a real deregistration because
    the operator needs to see it immediately to re-bootstrap.
    """
    probe_start_ns = time.monotonic_ns()
    try:
        live = await chain_client.is_registered_validator()
    except Exception as e:
        log.debug("settlement_registered_probe_failed", error=str(e))
        live = None
    if live is True or live is False:
        cached = _SETTLEMENT_REG_CACHE.get(signer)
        if cached is None or probe_start_ns > cached[1]:
            _SETTLEMENT_REG_CACHE[signer] = (live, probe_start_ns)
        return live
    cached = _SETTLEMENT_REG_CACHE.get(signer)
    if cached is not None:
        value, observed_at_ns = cached
        if value is True and (probe_start_ns - observed_at_ns) < _SETTLEMENT_REG_CACHE_TTL_NS:
            return True
    return None


async def _require_not_paused(
    chain_client: ChainClient | None,
    subsystem: str,
    action: str,
) -> None:
    """Short-circuit a user-facing endpoint with 503 if the named subsystem is paused.

    Reads ``<Contract>.paused()`` on the Base proxy. The contract-layer read is
    fail-open (False on any error), so a misconfigured or unreachable RPC never
    falsely claims "paused" and DoSes the validator — worst case we do the
    work and the on-chain tx reverts, same as today. A true paused()=true
    flips this endpoint to 503 before expensive MPC/share-store work runs.

    Skipped entirely when chain_client is None (dev mode). MAINNET_BLOCKERS P0-04
    validator-side residual.
    """
    if chain_client is None:
        return
    if await chain_client.is_paused(subsystem):
        raise HTTPException(
            status_code=503,
            detail=(f"protocol_paused: {subsystem} contract is paused; " f"{action} temporarily unavailable"),
            headers={"Retry-After": "60"},
        )


def _detect_bot_challenge(response_body: str | None) -> bool:
    """Check if a response body looks like a bot protection challenge page."""
    if not response_body:
        return False
    lower = response_body[:4000].lower()
    indicators = [
        "<title>client challenge</title>",
        "<title>just a moment...</title>",
        "<title>attention required</title>",
        "<title>access denied</title>",
        "cf-challenge-running",
        "cf_chl_opt",
        "_cf_chl_tk",
        "jschl_vc",
        "jschl-answer",
        "managed_checking_msg",
        "challenges.cloudflare.com",
        "cdn-cgi/challenge-platform",
        "please verify you are a human",
        "checking your browser",
        "ddos-guard",
        "please wait while we verify",
    ]
    return any(ind in lower for ind in indicators)


async def _gossip_purchase_odds_to_peers(
    neuron: Any,
    signal_id: str,
    buyer_address: str,
    bpas: list[int],
    wpas: list[int],
    bpa_mode: bool,
    timeout_s: float = 5.0,
) -> None:
    """Fire-and-forget gossip of a (signal, buyer, BPA/WPA) tuple to committee peers.

    Called after the purchase-handling validator successfully records a
    per-line BPA/WPA in its local purchase_odds ledger. Every registered
    validator peer (excluding self) receives a signed POST to
    /v1/purchase_odds/record so batch-audit settlement (which can run on
    any validator) has the vectors locally when the audit set closes.

    Errors are logged and swallowed — a failed gossip to one peer must
    not block the purchase response or the audit settlement path on the
    other peers. The endpoint is idempotent, so at-least-once delivery
    via retry is safe but not implemented here (retry would be pursued
    at the settlement layer via the existing GET /v1/purchase_odds
    fallback if the vectors are missing).
    """
    if neuron is None or neuron.metagraph is None:
        log.debug("purchase_odds_gossip_skipped_no_metagraph", signal_id=signal_id)
        return

    # Reuse the orchestrator's peer-discovery helper so IP filtering,
    # self-skip and validator_permit gating stay in one place.
    from djinn_validator.core.mpc_orchestrator import _is_public_ip

    peers: list[dict[str, Any]] = []
    try:
        metagraph = neuron.metagraph
        for uid in range(metagraph.n.item()):
            if not metagraph.validator_permit[uid].item():
                continue
            if uid == neuron.uid:
                continue
            axon = metagraph.axons[uid]
            if not axon.ip or axon.ip == "0.0.0.0":
                continue
            if not _is_public_ip(axon.ip):
                continue
            peers.append(
                {
                    "uid": uid,
                    "url": f"http://{axon.ip}:{axon.port}",
                    "hotkey": metagraph.hotkeys[uid],
                }
            )
    except Exception as e:
        log.warning("purchase_odds_gossip_peer_discovery_failed", error=str(e)[:120])
        return

    if not peers:
        log.debug("purchase_odds_gossip_no_peers", signal_id=signal_id)
        return

    payload = {
        "signal_id": signal_id,
        "buyer_address": buyer_address,
        "bpas": bpas,
        "wpas": wpas,
        "bpa_mode": bpa_mode,
    }
    body = json.dumps(payload, separators=(",", ":")).encode()

    if neuron.wallet is None:
        log.warning("purchase_odds_gossip_no_wallet", signal_id=signal_id)
        return

    from djinn_validator.api.middleware import create_signed_headers

    try:
        auth_headers = create_signed_headers("/v1/purchase_odds/record", body, neuron.wallet)
    except Exception as e:
        log.warning("purchase_odds_gossip_signing_failed", error=str(e)[:120])
        return

    sent = 0
    failed = 0

    # v1704: per-peer push gossip outcome counter. Closes the symmetry
    # with v1702 pull-side prefetch — together they answer "did the
    # originating validator gossip at all?" vs "did the receiving
    # validator drop?".
    from djinn_validator.api.metrics import GOSSIP_PUSH_RESULT, safe_label_inc

    def _gossip_tick(outcome: str) -> None:
        safe_label_inc(GOSSIP_PUSH_RESULT, path="purchase_odds", outcome=outcome)

    # v1721: each _post_one call returns one of:
    #   "ack"        — peer 200, retry not needed
    #   "retry"      — transient failure (5xx, timeout, connection error);
    #                  retry next round
    #   "permanent"  — 4xx (request rejected by peer's own validation;
    #                  retrying won't change the outcome)
    async def _post_one(peer: dict[str, Any], client: httpx.AsyncClient) -> str:
        try:
            resp = await client.post(
                f"{peer['url']}/v1/purchase_odds/record",
                content=body,
                headers={"Content-Type": "application/json", **auth_headers},
            )
            if resp.status_code == 200:
                _gossip_tick("sent")
                return "ack"
            if resp.status_code == 404:
                _gossip_tick("peer_404")
                return "permanent"
            if 400 <= resp.status_code < 500:
                _gossip_tick("peer_status_4xx")
                return "permanent"
            if 500 <= resp.status_code < 600:
                _gossip_tick("peer_status_5xx")
                log.info(
                    "purchase_odds_gossip_peer_rejected",
                    peer_uid=peer["uid"],
                    status=resp.status_code,
                    signal_id=signal_id,
                )
                return "retry"
            _gossip_tick("peer_status_other")
            return "permanent"
        except httpx.HTTPError as e:
            _gossip_tick("peer_unreachable")
            log.info(
                "purchase_odds_gossip_peer_error",
                peer_uid=peer["uid"],
                error=str(e)[:100],
                signal_id=signal_id,
            )
            return "retry"

    # v1721: retry-until-acked. Pre-fix, gossip was a single fan-out with
    # no retry — when a peer 504'd or transiently dropped (concurrent stress
    # load, brief restart, congestion), the BPA/WPA never reached that peer.
    # build_pi_abstain_missing_bpa_wpa fired forever on the affected pair.
    # Net effect: 4-of-5 quorum was unreachable for any cohort where 2+
    # peers transiently failed at gossip time. With retry, transient
    # failures recover automatically; permanent (4xx) failures still abort
    # so we don't burn cycles on validation rejections.
    #
    # Politeness: exponential backoff (30s, 90s, 240s) — initial fan-out
    # + 3 retries = 4 attempts per peer over ~6 minutes total. Each
    # attempt only re-targets peers that returned "retry"; acks and
    # permanent failures drop out of the queue. Runs in background
    # (caller fires via asyncio.create_task), so the purchase response
    # latency is unaffected.
    GOSSIP_MIN_ACKS = int(os.environ.get("DJINN_GOSSIP_MIN_ACKS", "4"))
    # Comma-separated list; tests override with "0,0,0" to skip sleeps.
    GOSSIP_BACKOFFS_S = [
        float(x) for x in os.environ.get("DJINN_GOSSIP_BACKOFFS_S", "30,90,240").split(",") if x.strip()
    ]

    pending = list(peers)
    acks = 0
    permanent_failures = 0

    async with httpx.AsyncClient(timeout=timeout_s) as client:
        for attempt in range(len(GOSSIP_BACKOFFS_S) + 1):
            results = await asyncio.gather(
                *(_post_one(p, client) for p in pending),
                return_exceptions=True,
            )
            still_pending: list[dict[str, Any]] = []
            for peer, r in zip(pending, results):
                if r == "ack":
                    acks += 1
                elif r == "permanent":
                    permanent_failures += 1
                else:
                    still_pending.append(peer)
            pending = still_pending
            log.info(
                "purchase_odds_gossip_round",
                signal_id=signal_id,
                buyer=buyer_address[:10],
                attempt=attempt,
                acks=acks,
                permanent=permanent_failures,
                pending=len(pending),
                target=GOSSIP_MIN_ACKS,
            )
            if acks >= GOSSIP_MIN_ACKS or not pending:
                break
            if attempt < len(GOSSIP_BACKOFFS_S):
                await asyncio.sleep(GOSSIP_BACKOFFS_S[attempt])

    sent = acks
    failed = permanent_failures + len(pending)

    # v1744: any peer still pending after the in-memory budget gets handed
    # off to the durable retry queue. Worker drains continuously with
    # exponential backoff, so a peer that recovers >6 min later still
    # eventually receives the gossip and can participate in the audit.
    # Without this hand-off, a 6+ minute outage at gossip time strands
    # the data on the originating validator forever.
    if pending:
        try:
            from djinn_validator.core import gossip_outbox

            for p in pending:
                gossip_outbox.enqueue(
                    peer_uid=int(p["uid"]),
                    peer_url=p["url"],
                    peer_hotkey=p.get("hotkey", ""),
                    endpoint="/v1/purchase_odds/record",
                    payload=payload,
                    path_label="purchase_odds",
                )
        except Exception as e:  # pragma: no cover — defensive
            log.warning(
                "purchase_odds_gossip_outbox_enqueue_failed",
                error=str(e)[:120],
                pending=len(pending),
            )

    log.info(
        "purchase_odds_gossip_complete",
        signal_id=signal_id,
        buyer=buyer_address[:10],
        peers=len(peers),
        sent=sent,
        failed=failed,
        permanent_failures=permanent_failures,
        give_up_pending=len(pending),
        outbox_enqueued=len(pending),
        reached_target=acks >= GOSSIP_MIN_ACKS,
    )


def _store_peer_attestation_sigs(
    *,
    req: OutcomeGossipRequest,
    outcome_attestor: Any,
    peer_attestation_store: Any,
    chain_id: int,
    registry_address: str,
    ov_signer_set_provider: Any,
    signer_hotkey: str,
) -> None:
    """v1747 Phase 3: persist peer EIP-712 line attestation sigs.

    Walks ``req.outcomes`` aligned with ``req.eoa_sigs``. For each line:
      1. Builds the canonical LineKey from the local SignalMetadata.
      2. Computes lineHash bound to (chain_id, registry_address).
      3. Recovers the signer EOA from the sig + outcome digest.
      4. Confirms the recovered EOA matches ``req.eoa`` (caller honesty).
      5. Confirms ``req.eoa`` is in the OV validator set.
      6. Persists into ``peer_attestation_store``.

    Bad sigs are dropped silently per-line (log warning). The outer
    receive_outcome_gossip handler treats this as best-effort: legacy
    outcome propagation continues regardless of sig-layer failures.
    """
    from djinn_validator.chain.outcome_signer import (
        line_hash as compute_line_hash,
        signer_from_signature,
    )
    from djinn_validator.core.outcomes import parsed_pick_to_line_key

    if req.eoa is None or req.eoa_sigs is None:
        return

    sender_eoa = req.eoa.lower()

    # OV validator set check. If no provider wired, skip storage entirely
    # (production path always wires the provider; tests opt out by leaving
    # ov_signer_set_provider=None to avoid mocking the metagraph).
    if ov_signer_set_provider is None:
        return
    try:
        is_in_set = bool(ov_signer_set_provider(sender_eoa))
    except Exception as e:
        log.warning("peer_att_validator_set_check_failed", err=str(e)[:120])
        return
    if not is_in_set:
        log.warning(
            "peer_att_signer_not_in_validator_set",
            eoa=sender_eoa,
            signer_hotkey=signer_hotkey[:10],
        )
        return

    meta = outcome_attestor.get_signal(req.signal_id) if outcome_attestor else None
    if meta is None:
        return

    if len(req.eoa_sigs) != len(req.outcomes):
        log.warning(
            "peer_att_eoa_sigs_len_mismatch",
            sigs_len=len(req.eoa_sigs),
            outcomes_len=len(req.outcomes),
        )
        return
    if len(meta.lines) != len(req.outcomes):
        log.warning(
            "peer_att_outcomes_lines_len_mismatch",
            lines_len=len(meta.lines),
            outcomes_len=len(req.outcomes),
        )
        return

    stored = 0
    for idx, (pick, outcome_int, sig_hex) in enumerate(
        zip(meta.lines, req.outcomes, req.eoa_sigs)
    ):
        if outcome_int == 0:  # PENDING — never signed
            continue
        if outcome_int < 1 or outcome_int > 3:
            continue
        if not sig_hex:
            continue
        lk = parsed_pick_to_line_key(
            pick, meta.sport, meta.event_id, meta.home_team, meta.away_team
        )
        if lk is None:
            continue
        try:
            lh = compute_line_hash(lk, chain_id, registry_address)
        except (ValueError, TypeError):
            continue
        try:
            sig_bytes = bytes.fromhex(sig_hex.removeprefix("0x"))
        except ValueError:
            continue
        if len(sig_bytes) != 65:
            continue
        try:
            recovered = signer_from_signature(
                sig_bytes, lh, outcome_int, chain_id, registry_address
            )
        except Exception as e:
            log.debug("peer_att_recover_failed", line_idx=idx, err=str(e)[:120])
            continue
        if recovered.lower() != sender_eoa:
            log.warning(
                "peer_att_signer_mismatch",
                claimed=sender_eoa,
                recovered=recovered.lower(),
                line_idx=idx,
            )
            continue
        result = peer_attestation_store.add_peer_sig(
            line_hash=lh,
            peer_eoa=sender_eoa,
            outcome=outcome_int,
            signature=sig_bytes,
        )
        if result == "added":
            stored += 1
    if stored:
        log.info(
            "peer_att_stored",
            signal_id=req.signal_id,
            count=stored,
            from_eoa=sender_eoa,
        )


async def _gossip_resolved_outcome_to_peers(
    neuron: Any,
    signal_id: str,
    outcomes: list[int],
    raw_espn_summary: dict[str, Any] | None = None,
    timeout_s: float = 5.0,
    audit_set_store: Any = None,
    outcome_attestor: Any = None,
    signer_address: str | None = None,
) -> None:
    """Fire-and-forget gossip of a newly-resolved outcome to committee peers.

    Phase A1 of the outcome layer (see docs/outcome-layer-plan.md).

    Called by the main loop right after `OutcomeAttestor.resolve_all_pending`
    returns a list of newly-resolved signal_ids. Every registered validator
    peer (excluding self) gets a signed POST to /v1/outcomes/gossip.

    Receivers replay-verify by independent ESPN fetch — they do NOT trust
    the raw_espn_summary in the payload. The summary is included only for
    debug correlation when the receiver's local ESPN view diverges.

    Errors are swallowed per peer; one slow or down peer must not stall
    the local resolve loop. The endpoint is idempotent on receive.
    """
    if neuron is None or neuron.metagraph is None:
        log.debug("outcome_gossip_skipped_no_metagraph", signal_id=signal_id)
        return

    from djinn_validator.core.mpc_orchestrator import _is_public_ip

    peers: list[dict[str, Any]] = []
    try:
        metagraph = neuron.metagraph
        for uid in range(metagraph.n.item()):
            if not metagraph.validator_permit[uid].item():
                continue
            if uid == neuron.uid:
                continue
            axon = metagraph.axons[uid]
            if not axon.ip or axon.ip == "0.0.0.0":
                continue
            if not _is_public_ip(axon.ip):
                continue
            peers.append(
                {
                    "uid": uid,
                    "url": f"http://{axon.ip}:{axon.port}",
                    "hotkey": metagraph.hotkeys[uid],
                }
            )
    except Exception as e:
        log.warning("outcome_gossip_peer_discovery_failed", error=str(e)[:120])
        return

    if not peers:
        log.debug("outcome_gossip_no_peers", signal_id=signal_id)
        return

    payload: dict[str, Any] = {
        "signal_id": signal_id,
        "outcomes": outcomes,
        "raw_espn_summary": raw_espn_summary or {},
        "source_uid": int(neuron.uid),
    }
    # Phase A1.8: carry pair metadata so peers can register the signal
    # in their audit_set_store immediately, even during their post-restart
    # bootstrap window. Look up locally; if not in our audit_set either
    # (we're also mid-bootstrap), omit fields and fall back to the older
    # gossip-only path.
    if audit_set_store is not None:
        try:
            pair = audit_set_store.get_pair_for_signal(signal_id)
            if pair is not None:
                payload["genius"] = pair[0]
                payload["idiot"] = pair[1]
                pid = audit_set_store.get_purchase_id_for_signal(signal_id)
                if pid is not None:
                    payload["purchase_id"] = pid
        except Exception:
            pass
    # v1679 (P1-36 partial): propagate game_date so receivers' replay-verify
    # locks to the same ESPN scoreboard. For pre-v1676 signals committed
    # without game_date, only the validator that back-walked-found the game
    # has the date; without this, every receiver re-back-walks independently
    # and may match a different game → divergent outcomes.
    try:
        meta = outcome_attestor.get_signal(signal_id) if outcome_attestor else None
        if meta is not None and getattr(meta, "game_date", None):
            payload["game_date"] = meta.game_date
    except Exception:
        pass

    # v1747 Phase 7c: piggyback per-line EIP-712 sigs onto outcome gossip so
    # peers can store them in peer_attestation_store and aggregate a 4-of-5
    # bundle locally. Send only when the signer EOA is known and at least
    # one line has been signed (sign_stable_lines may not have fired yet on
    # the very first gossip — reconcile gossip every ~5 min picks up the
    # rest). eoa_sigs is aligned 1:1 with outcomes; entries are 0x-hex
    # sigs or None for unsigned lines.
    try:
        if outcome_attestor is not None:
            sigs = outcome_attestor.get_signal_line_sigs(signal_id)
            if sigs and any(s is not None for s in sigs):
                # Pydantic on the receiving side rejects None entries (it
                # expects all-strings). Substitute a sentinel zero-sig
                # for None — the receiver's ECDSA.recover will reject it
                # and skip-store, which is the correct behavior.
                zero_sig = "0x" + "00" * 65
                payload["eoa_sigs"] = [s if s is not None else zero_sig for s in sigs]
                if signer_address:
                    payload["eoa"] = signer_address
    except Exception:
        # Phase 7c is best-effort — never let sig-propagation failures
        # break the legacy outcome gossip.
        pass

    body = json.dumps(payload, separators=(",", ":")).encode()

    if neuron.wallet is None:
        log.warning("outcome_gossip_no_wallet", signal_id=signal_id)
        return

    from djinn_validator.api.middleware import create_signed_headers

    try:
        auth_headers = create_signed_headers("/v1/outcomes/gossip", body, neuron.wallet)
    except Exception as e:
        log.warning("outcome_gossip_signing_failed", error=str(e)[:120])
        return

    sent = 0
    failed = 0
    accepted = 0
    disputed = 0
    pending = 0

    # v1704: per-peer outcome push counter under the same family as
    # purchase_odds gossip. path="outcomes" distinguishes the two flows.
    from djinn_validator.api.metrics import GOSSIP_PUSH_RESULT, safe_label_inc

    def _gossip_tick(outcome: str) -> None:
        safe_label_inc(GOSSIP_PUSH_RESULT, path="outcomes", outcome=outcome)

    async with httpx.AsyncClient(timeout=timeout_s) as client:

        async def _post_one(peer: dict[str, Any]) -> tuple[bool, str]:
            try:
                resp = await client.post(
                    f"{peer['url']}/v1/outcomes/gossip",
                    content=body,
                    headers={"Content-Type": "application/json", **auth_headers},
                )
                if resp.status_code == 200:
                    _gossip_tick("sent")
                    try:
                        data = resp.json()
                        return True, str(data.get("reason") or ("duplicate" if data.get("duplicate") else "accepted"))
                    except Exception:
                        return True, "accepted"
                if resp.status_code == 404:
                    _gossip_tick("peer_404")
                elif 400 <= resp.status_code < 500:
                    _gossip_tick("peer_status_4xx")
                elif 500 <= resp.status_code < 600:
                    _gossip_tick("peer_status_5xx")
                else:
                    _gossip_tick("peer_status_other")
                log.info(
                    "outcome_gossip_peer_rejected",
                    peer_uid=peer["uid"],
                    status=resp.status_code,
                    signal_id=signal_id,
                )
                return False, f"status_{resp.status_code}"
            except httpx.HTTPError as e:
                _gossip_tick("peer_unreachable")
                log.info(
                    "outcome_gossip_peer_error",
                    peer_uid=peer["uid"],
                    error=str(e)[:100],
                    signal_id=signal_id,
                )
                return False, "http_error"

        results = await asyncio.gather(*(_post_one(p) for p in peers), return_exceptions=True)
        # v1745: collect transient-failure peers for the durable outbox.
        # 5xx + network errors are transient (peer might recover); 4xx is
        # permanent (peer rejected on validation/auth/version) and not
        # worth queueing.
        outbox_targets: list[dict[str, Any]] = []
        for peer, r in zip(peers, results):
            if isinstance(r, tuple):
                ok, reason = r
                if ok:
                    sent += 1
                    if "accepted" in reason:
                        accepted += 1
                    elif "duplicate" in reason or "already_resolved" in reason:
                        accepted += 1  # treat duplicates as a success
                    elif "disputed" in reason:
                        disputed += 1
                    elif "pending_local" in reason or "unknown_signal" in reason:
                        pending += 1
                else:
                    failed += 1
                    # Transient: 5xx upstream or any httpx error. 4xx is
                    # permanent and skipped.
                    if reason == "http_error" or reason.startswith("status_5"):
                        outbox_targets.append(peer)
            else:
                failed += 1
                # Exception bubbled out of gather — treat as transient.
                outbox_targets.append(peer)

    # v1745: enqueue transient failures to the durable retry queue so a
    # peer that recovers >5min later still receives the resolved outcome.
    # Symmetric to v1744's purchase_odds enqueue; uses path_label="outcomes"
    # so operators can distinguish the two gossip streams in queue stats.
    if outbox_targets:
        try:
            from djinn_validator.core import gossip_outbox

            for p in outbox_targets:
                gossip_outbox.enqueue(
                    peer_uid=int(p["uid"]),
                    peer_url=p["url"],
                    peer_hotkey=p.get("hotkey", ""),
                    endpoint="/v1/outcomes/gossip",
                    payload=payload,
                    path_label="outcomes",
                )
        except Exception as e:  # pragma: no cover — defensive
            log.warning(
                "outcome_gossip_outbox_enqueue_failed",
                error=str(e)[:120],
                pending=len(outbox_targets),
            )

    log.info(
        "outcome_gossip_complete",
        signal_id=signal_id,
        peers=len(peers),
        sent=sent,
        failed=failed,
        accepted=accepted,
        disputed=disputed,
        pending=pending,
        outbox_enqueued=len(outbox_targets),
    )


async def _gossip_audit_set_to_peers(
    neuron: Any,
    genius: str,
    idiot: str,
    signal_id: str,
    purchase_id: int,
    timeout_s: float = 5.0,
) -> None:
    """v1710: fire-and-forget gossip of a newly-discovered (genius, idiot,
    signal_id, purchase_id) tuple to committee peers. Receivers verify
    against chain RPC + add to their own audit_set_store within seconds
    of any one validator scanning chain.

    Architectural fallback for when the v1709 subgraph fast path is
    stale, errored, or unreachable. When subgraph is healthy, peers
    converge through the same GraphQL view; gossip then deduplicates
    quickly (receiver returns 'duplicate'). When subgraph is down, this
    path is the only thing keeping the fleet's audit_set_store views
    in sync without per-validator chain-pagination races.

    Errors swallowed per peer; one slow / down peer must not stall
    audit_bootstrap. Idempotent on receive (duplicate adds are no-ops).
    """
    if neuron is None or neuron.metagraph is None:
        return

    from djinn_validator.core.mpc_orchestrator import _is_public_ip

    peers: list[dict[str, Any]] = []
    try:
        metagraph = neuron.metagraph
        for uid in range(metagraph.n.item()):
            if not metagraph.validator_permit[uid].item():
                continue
            if uid == neuron.uid:
                continue
            axon = metagraph.axons[uid]
            if not axon.ip or axon.ip == "0.0.0.0":
                continue
            if not _is_public_ip(axon.ip):
                continue
            peers.append(
                {
                    "uid": uid,
                    "url": f"http://{axon.ip}:{axon.port}",
                    "hotkey": metagraph.hotkeys[uid],
                }
            )
    except Exception as e:
        log.warning("audit_gossip_peer_discovery_failed", err=str(e)[:120])
        return

    if not peers:
        try:
            from djinn_validator.api.metrics import AUDIT_GOSSIP_PUSH_RESULT

            AUDIT_GOSSIP_PUSH_RESULT.labels(outcome="no_peers").inc()
        except Exception:
            pass
        return

    payload = {
        "genius": genius,
        "idiot": idiot,
        "signal_id": signal_id,
        "purchase_id": int(purchase_id),
        "source_uid": int(neuron.uid),
    }
    body = json.dumps(payload, separators=(",", ":")).encode()

    if neuron.wallet is None:
        return

    from djinn_validator.api.middleware import create_signed_headers

    try:
        auth_headers = create_signed_headers("/v1/audit/gossip", body, neuron.wallet)
    except Exception as e:
        log.warning("audit_gossip_signing_failed", err=str(e)[:120])
        return

    def _push_tick(outcome: str) -> None:
        try:
            from djinn_validator.api.metrics import AUDIT_GOSSIP_PUSH_RESULT

            AUDIT_GOSSIP_PUSH_RESULT.labels(outcome=outcome).inc()
        except Exception:
            pass

    async with httpx.AsyncClient(timeout=timeout_s) as client:

        async def _post_one(peer: dict[str, Any]) -> None:
            try:
                resp = await client.post(
                    f"{peer['url']}/v1/audit/gossip",
                    content=body,
                    headers={"Content-Type": "application/json", **auth_headers},
                )
                if resp.status_code == 200:
                    _push_tick("sent")
                elif resp.status_code == 404:
                    _push_tick("peer_404")
                elif 400 <= resp.status_code < 500:
                    _push_tick("peer_status_4xx")
                elif 500 <= resp.status_code < 600:
                    _push_tick("peer_status_5xx")
                else:
                    _push_tick("peer_status_other")
            except httpx.HTTPError:
                _push_tick("peer_unreachable")

        await asyncio.gather(*(_post_one(p) for p in peers), return_exceptions=True)


def create_app(
    share_store: ShareStore,
    purchase_orch: PurchaseOrchestrator,
    outcome_attestor: OutcomeAttestor,
    chain_client: ChainClient | None = None,
    neuron: DjinnValidator | None = None,
    mpc_coordinator: MPCCoordinator | None = None,
    rate_limit_capacity: int = 60,
    rate_limit_rate: int = 10,
    mpc_availability_timeout: float = 60.0,
    shares_threshold: int = 7,
    attestation_log: AttestationLog | None = None,
    fallback_miner_url: str | None = None,
    scorer: MinerScorer | None = None,
    activity_buffer: ActivityBuffer | None = None,
    audit_set_store: AuditSetStore | None = None,
    telemetry: TelemetryStore | None = None,
    purchase_odds_ledger: PurchaseOddsLedger | None = None,
    encryption_privkey: bytes | None = None,
    signer_address: str | None = None,
    peer_attestation_store: Any = None,
    line_outcome_chain_id: int | None = None,
    line_outcome_registry_address: str | None = None,
    ov_signer_set_provider: Any = None,
) -> FastAPI:
    """Create the FastAPI application with injected dependencies."""
    bt_network = os.environ.get("BT_NETWORK", "")
    _is_production = bt_network in ("finney", "mainnet")

    # Warn loudly if chain client is missing in production (hard guard is on
    # the purchase endpoint — shares will never be released without payment
    # verification in production mode).
    if chain_client is None and _is_production:
        log.error(
            "chain_client_missing_production",
            bt_network=bt_network,
            msg="No chain client configured. Share release will be BLOCKED "
            "until BASE_RPC_URL is set and chain_client is provided.",
        )

    # Resources that need cleanup on shutdown
    _cleanup_resources: list = []
    _shutdown_event = asyncio.Event()
    # Mutable container for last-cleanup timestamp (throttle purchase-path cleanup)
    _last_cleanup = [0.0]

    import time as _startup_time_mod

    _startup_monotonic = _startup_time_mod.monotonic()

    async def _periodic_state_cleanup() -> None:
        """Background task to evict stale participant/OT states every 60s."""
        while not _shutdown_event.is_set():
            try:
                await asyncio.sleep(60)
            except asyncio.CancelledError:
                return
            try:
                with _participant_lock:
                    _cleanup_stale_participants_locked()
                with _ot_lock:
                    _cleanup_stale_ot_states_locked()
                _mpc.cleanup_expired()
                # Prune purchase locks to prevent unbounded growth
                async with _purchase_locks_guard:
                    to_remove = [k for k, lock in _purchase_locks.items() if not lock.locked()]
                    for k in to_remove:
                        del _purchase_locks[k]
                    if to_remove:
                        log.debug("purchase_locks_pruned", count=len(to_remove))
                # Update operational gauges
                MPC_ACTIVE_SESSIONS.set(_mpc.active_session_count)
                UPTIME_SECONDS.set(_startup_time_mod.monotonic() - _startup_monotonic)
                BT_CONNECTED.set(1 if neuron and neuron.metagraph is not None else 0)
            except Exception:
                log.warning("periodic_cleanup_error", exc_info=True)

    @asynccontextmanager
    async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
        try:
            from djinn_validator.feature_flags import flags as _startup_flags

            log.info(
                "feature_flags_active",
                summary=_startup_flags.summary(),
                **_startup_flags.as_dict(),
            )
        except Exception as _ff_err:
            log.warning("feature_flags_log_failed", error=str(_ff_err)[:100])

        if os.environ.get("DJINN_REQUIRE_BUYER_AUTH", "0") != "1":
            log.warning(
                "buyer_auth_disabled",
                detail="DJINN_REQUIRE_BUYER_AUTH is not '1'. "
                "Purchase endpoint will accept unsigned requests. "
                "Set DJINN_REQUIRE_BUYER_AUTH=1 for production.",
            )

        # Warm circuit breakers from persistent attestation history so we
        # don't waste time re-discovering dead miners after a restart.
        if attestation_log is not None:
            try:
                streaks = attestation_log.miner_failure_streaks(lookback_seconds=3600)
                warmed = 0
                for uid, failures in streaks.items():
                    if failures >= 3:
                        breaker = _get_miner_breaker(uid)
                        for _ in range(failures):
                            breaker.record_failure()
                        warmed += 1
                if warmed:
                    log.info("circuit_breakers_warmed", count=warmed, from_log=True)
            except Exception as e:
                log.warning("circuit_breaker_warmup_failed", error=str(e))

        cleanup_task = asyncio.create_task(_periodic_state_cleanup())
        yield
        _shutdown_event.set()
        cleanup_task.cancel()
        try:
            await cleanup_task
        except asyncio.CancelledError:
            pass
        for resource in _cleanup_resources:
            try:
                close = getattr(resource, "aclose", None) or getattr(resource, "close", None)
                if close is not None:
                    result = close()
                    if hasattr(result, "__await__"):
                        await result
            except Exception as e:
                log.warning("resource_cleanup_error", resource=type(resource).__name__, error=str(e))

    from djinn_validator import __version__

    app = FastAPI(
        title="Djinn Validator",
        version=__version__,
        description="Djinn Protocol Bittensor Validator API",
        lifespan=_lifespan,
    )

    # Catch unhandled exceptions — never leak stack traces to clients
    @app.exception_handler(Exception)
    async def _unhandled_error(request: Request, exc: Exception) -> StarletteJSONResponse:
        log.error(
            "unhandled_exception",
            error=str(exc),
            path=request.url.path,
            method=request.method,
            exc_info=True,
        )
        return StarletteJSONResponse(
            status_code=500,
            content={"detail": "Internal server error"},
        )

    # CORS — restricted in production, open in dev
    cors_origins = get_cors_origins(os.getenv("CORS_ORIGINS", ""), os.getenv("BT_NETWORK", ""))
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Request body size limit (1MB default, 5MB for OT endpoints)
    @app.middleware("http")
    async def limit_body_size(request: Request, call_next):  # type: ignore[no-untyped-def]
        from starlette.responses import JSONResponse

        max_size = 5_242_880 if request.url.path.startswith("/v1/mpc/ot/") else 1_048_576
        content_length = request.headers.get("content-length")
        if content_length:
            try:
                if int(content_length) > max_size:
                    return JSONResponse(
                        status_code=413, content={"detail": f"Request body too large (max {max_size // 1048576}MB)"}
                    )
            except (ValueError, OverflowError):
                return JSONResponse(status_code=400, content={"detail": "Invalid Content-Length header"})
        elif request.method in ("POST", "PUT", "PATCH"):
            # Reject requests without Content-Length to prevent chunked encoding bypass
            te = request.headers.get("transfer-encoding", "").lower()
            if "chunked" in te:
                return JSONResponse(status_code=411, content={"detail": "Content-Length header required"})
        return await call_next(request)

    # Rate limiting (MAINNET P1-31: uniform per-IP limits across /v1/*).
    # Browsers hit validators directly under DEV-045, so the middleware
    # here replaces the Vercel edge rate-limit that used to gate traffic.
    # Defaults are tuned in config.py (30 burst / 4 req/sec ≈ 240/min).
    limiter = RateLimiter(default_capacity=rate_limit_capacity, default_rate=rate_limit_rate)
    limiter.set_path_limit("/v1/signal", capacity=20, rate=2)  # Share storage: 2/sec
    limiter.set_path_limit("/v1/signals/resolve", capacity=10, rate=1)  # Resolution: 1/sec
    limiter.set_path_limit("/v1/mpc/", capacity=100, rate=50)  # MPC: higher for multi-round (internal)
    limiter.set_path_limit("/v1/analytics", capacity=30, rate=5)  # Analytics: 5/sec
    limiter.set_path_limit("/v1/odds", capacity=120, rate=2)  # Odds proxy: mirrors Next (120/min/IP)
    limiter.set_path_limit("/v1/report-error", capacity=5, rate=1)  # Error reports: 5 burst, 1/sec
    # Expensive fan-out endpoints: each request can hit every miner on the
    # metagraph and/or span multiple validators. Browser-initiated load
    # should be bursty and rare (a page reload), not sustained — a 30/min
    # cap mostly lets real users through while blocking scrapers.
    limiter.set_path_limit("/v1/network/matrix", capacity=10, rate=0.5)  # 30/min
    limiter.set_path_limit("/v1/network/miners", capacity=10, rate=0.5)  # 30/min
    limiter.set_path_limit("/v1/network/miner/", capacity=10, rate=0.5)  # 30/min (per uid)
    limiter.set_path_limit("/v1/network/validator/", capacity=10, rate=0.5)  # 30/min (per uid)
    limiter.set_path_limit("/v1/network/metagraph/", capacity=10, rate=0.5)  # 30/min
    limiter.set_path_limit("/v1/network/overview", capacity=20, rate=1)  # 60/min (common page)
    # Outcome layer: gossip + pull recovery are inter-validator chatter,
    # not user-facing. Pre-2026-05-03 default (60 burst / 10 rps) saw ~38%
    # 429s on UID 0 during normal fleet activity which directly correlates
    # with outcome divergence (see project_outcome_recovery_design_2026_05_03.md).
    # Bumped so a 5-validator gossip burst on a freshly-resolved batch of
    # 10+ signals doesn't drop on the receivers.
    limiter.set_path_limit("/v1/outcomes/gossip", capacity=200, rate=50)
    limiter.set_path_limit("/v1/outcomes/", capacity=100, rate=20)  # pull recovery
    app.add_middleware(RateLimitMiddleware, limiter=limiter)

    # Request ID tracing (outermost — must be added last)
    app.add_middleware(RequestIdMiddleware)

    # Admin auth dependency — if ADMIN_API_KEY is set, require Bearer token
    _admin_auth = require_admin_auth(os.getenv("ADMIN_API_KEY", ""))

    _ETH_ADDR_RE = re.compile(r"^0x[0-9a-fA-F]{40}$")

    # Shamir threshold bounds. Floor of 2 during bootstrap (not all validators
    # updated yet). Raise to 3 once the network stabilizes. Cap of 7.
    # The client computes clamp(ceil(2/3 * healthy), 2, 7).
    _MIN_SHAMIR_THRESHOLD = 2
    _MAX_SHAMIR_THRESHOLD = 7

    # POST /v1/signal (legacy plaintext-share fan-out) was removed 2026-05-04.
    # /v1/signal/bundle is the only supported share-distribution path; it
    # accepts encrypted SealedBox bundles per OV signer with forwarding
    # entries that peers serve via /v1/share-recovery for MPC-time recovery.
    # See web/lib/share-bundle.ts (client) + scripts/lib/share-bundle.mjs
    # (test scripts) + project_share_recovery_design_2026_05_03.md.

    @app.post("/v1/signal/bundle", response_model=StoreShareBundleResponse)
    async def store_share_bundle(req: StoreShareBundleRequest) -> StoreShareBundleResponse:
        """Accept an encrypted-bundle Shamir fan-out (share recovery, C+F design).

        The genius sends THE SAME bundle to every OV signer. Each entry holds a
        per-target SealedBox ciphertext of the plaintext share_y bytes. We
        decrypt our OWN entry (matching signer_address) to recover share_y,
        store via the existing share path, and persist the rest as forwarding
        blobs. Peers serve those blobs on demand via /v1/share-recovery.
        """
        await _require_not_paused(chain_client, "signal", "signal commits")

        if encryption_privkey is None or signer_address is None:
            raise HTTPException(
                status_code=503,
                detail="validator x25519 keypair not configured; cannot accept bundle",
            )

        if req.shamir_threshold < _MIN_SHAMIR_THRESHOLD:
            raise HTTPException(
                status_code=400,
                detail=f"shamir_threshold must be >= {_MIN_SHAMIR_THRESHOLD}",
            )

        if not _ETH_ADDR_RE.match(req.genius_address):
            raise HTTPException(status_code=400, detail="genius_address invalid")

        # Verify on-chain genius matches (non-blocking on RPC errors).
        if chain_client is not None:
            try:
                on_chain = await chain_client.get_signal(int(req.signal_id))
                if on_chain and on_chain.get("genius"):
                    if on_chain["genius"].lower() != req.genius_address.lower():
                        raise HTTPException(
                            status_code=403,
                            detail=f"genius_address mismatch: on-chain={on_chain['genius']}",
                        )
            except HTTPException:
                raise
            except Exception as e:
                log.warning("on_chain_signal_verification_failed", signal_id=req.signal_id, err=str(e)[:200])

        my_addr = signer_address.lower()
        own_entry = None
        forwarding_entries = []
        for entry in req.bundle:
            if entry.target_address.lower() == my_addr:
                own_entry = entry
            else:
                forwarding_entries.append(entry)

        # v1705: bundle-store outcome counter. Best-effort import.
        from djinn_validator.api.metrics import BUNDLE_STORE_RESULT, safe_label_inc

        def _bundle_tick(outcome: str) -> None:
            safe_label_inc(BUNDLE_STORE_RESULT, outcome=outcome)

        if own_entry is None:
            _bundle_tick("missing_own_entry")
            log.warning(
                "bundle_missing_own_entry",
                signal_id=req.signal_id,
                signer=my_addr,
                bundle_targets=[e.target_address.lower() for e in req.bundle],
            )
            # Still store forwarding entries — peers may need them. But
            # report own_share_stored=False so caller can route to a
            # different validator for own-share retry.

        own_share_stored = False
        if own_entry is not None:
            try:
                from djinn_validator.chain.encryption_keys import decrypt_sealed_box

                share_ct = bytes.fromhex(own_entry.share_ciphertext)
                index_ct = bytes.fromhex(own_entry.index_ciphertext) if own_entry.index_ciphertext else b""

                share_y_bytes = decrypt_sealed_box(encryption_privkey, share_ct)
                index_y_bytes = decrypt_sealed_box(encryption_privkey, index_ct) if index_ct else b""
            except Exception as e:
                _bundle_tick("own_decrypt_failed")
                log.warning("bundle_decrypt_failed", signal_id=req.signal_id, err=str(e)[:200])
                raise HTTPException(status_code=400, detail="own bundle entry could not be decrypted")

            try:
                share_y = int.from_bytes(share_y_bytes, "big")
                if share_y < 0 or share_y >= BN254_PRIME:
                    _bundle_tick("own_oof_field")
                    raise HTTPException(status_code=400, detail="decrypted share_y out of BN254 field range")
                share = Share(x=own_entry.share_x, y=share_y)

                from djinn_validator.core.shares import PrecomputedTriple

                triples = (
                    [PrecomputedTriple(a=int(t.a, 16), b=int(t.b, 16), c=int(t.c, 16)) for t in req.precomputed_triples]
                    if req.precomputed_triples
                    else []
                )

                share_store.store(
                    signal_id=req.signal_id,
                    genius_address=req.genius_address,
                    share=share,
                    encrypted_key_share=share_y_bytes,
                    encrypted_index_share=index_y_bytes,
                    shamir_threshold=req.shamir_threshold,
                    precomputed_triples=triples,
                )
                own_share_stored = True
                SHARES_STORED.inc()
                ACTIVE_SHARES.set(share_store.count)
            except HTTPException:
                raise
            except ValueError as e:
                detail = str(e)
                if "already stored" in detail:
                    # Idempotent: re-bundle to the same validator is fine.
                    own_share_stored = True
                    _bundle_tick("own_already_stored")
                else:
                    raise HTTPException(status_code=400, detail=detail)

        # Persist forwarding blobs verbatim — they're encrypted to other targets,
        # we never decrypt them. Peers serve them via /v1/share-recovery.
        forwarding_count = 0
        forwarding_failures = 0
        for entry in forwarding_entries:
            try:
                share_ct = bytes.fromhex(entry.share_ciphertext)
                index_ct = bytes.fromhex(entry.index_ciphertext) if entry.index_ciphertext else b""
                share_store.store_forwarding(
                    signal_id=req.signal_id,
                    target_address=entry.target_address,
                    share_x=entry.share_x,
                    share_ciphertext=share_ct,
                    index_ciphertext=index_ct,
                    shamir_threshold=req.shamir_threshold,
                )
                forwarding_count += 1
            except Exception as e:
                forwarding_failures += 1
                log.warning(
                    "forwarding_store_failed",
                    signal_id=req.signal_id,
                    target=entry.target_address,
                    err=str(e)[:200],
                )

        # v1705: tick completion outcome. own-entry-already-stored
        # already ticked above; here we only fire `complete` when we
        # both stored own + every forwarding entry without failures.
        # Both `forwarding_failed` and `complete` are mutually exclusive
        # for a single bundle; missing_own_entry/own_decrypt_failed/
        # own_oof_field already ticked + raised earlier so this code
        # only runs on the success-or-partial-success paths.
        if own_share_stored and forwarding_failures == 0:
            _bundle_tick("complete")
        elif forwarding_failures > 0:
            _bundle_tick("forwarding_failed")

        log.info(
            "bundle_stored",
            signal_id=req.signal_id,
            own=own_share_stored,
            forwarding=forwarding_count,
            forwarding_failed=forwarding_failures,
            total_targets=len(req.bundle),
        )

        return StoreShareBundleResponse(
            signal_id=req.signal_id,
            own_share_stored=own_share_stored,
            forwarding_count=forwarding_count,
        )

    @app.get(
        "/v1/share-recovery/{signal_id}/{target_address}",
        response_model=ShareRecoveryResponse,
    )
    async def share_recovery(signal_id: str, target_address: str) -> ShareRecoveryResponse:
        """Serve a forwarding blob to a peer validator that missed initial delivery.

        No auth: ciphertext is encrypted to target's pubkey, peer-readable is fine.
        Returns 404 if no forwarding entry exists locally for (signal, target).
        """
        if not _ETH_ADDR_RE.match(target_address):
            raise HTTPException(status_code=400, detail="target_address invalid")

        entry = share_store.get_forwarding(signal_id, target_address)
        if entry is None:
            raise HTTPException(status_code=404, detail="no forwarding entry")

        return ShareRecoveryResponse(
            signal_id=signal_id,
            target_address=target_address.lower(),
            share_x=entry["share_x"],
            share_ciphertext=entry["share_ciphertext"].hex(),
            index_ciphertext=entry["index_ciphertext"].hex() if entry["index_ciphertext"] else "",
            shamir_threshold=entry["shamir_threshold"],
        )

    @app.post("/v1/signal/{signal_id}/purchase", response_model=PurchaseResponse)
    async def purchase_signal(signal_id: str, req: PurchaseRequest) -> PurchaseResponse:
        """Handle a buyer's purchase request.

        Flow:
        1. Verify buyer owns buyer_address (EIP-191 signature)
        2. Verify signal exists and is active
        3. Run MPC to check if real index ∈ available indices
        4. If available, release encrypted key share

        Uses per-signal locking to prevent concurrent purchases for the
        same signal from racing through payment verification and share release.
        """
        _validate_signal_id_path(signal_id)

        await _require_not_paused(chain_client, "escrow", "purchases")

        # v1723: buyer_signature mandatory by default. Pre-fix, the gate was
        # opt-in via DJINN_REQUIRE_BUYER_AUTH=1, leaving the share-release
        # endpoint open to anyone who could observe a victim's on-chain
        # purchase: the attacker would call this endpoint with the victim's
        # buyer_address (and no signature), validator would verify on-chain
        # payment, then return the encrypted_key_share to the attacker. With
        # threshold-many shares collected this way, the attacker reconstructs
        # the AES key and decrypts the signal — without the victim's wallet.
        # Codex audit 2026-05-05 flagged this as the top High finding.
        # Default flips to mandatory; opt-out via DJINN_ALLOW_UNSIGNED_PURCHASE=1
        # for legacy or test-only validator instances.
        # Smart wallet signatures (EIP-1271) are longer and use contract-based
        # verification we can't do here; we still accept those by length and
        # rely on the on-chain payment record + the mandatory signature
        # presence to gate share release.
        _allow_unsigned = os.environ.get("DJINN_ALLOW_UNSIGNED_PURCHASE", "0") == "1"
        if req.buyer_signature and len(req.buyer_signature) <= 132:
            try:
                from eth_account import Account as EthAccount
                from eth_account.messages import encode_defunct

                msg = encode_defunct(text=f"djinn:purchase:{signal_id}")
                recovered = EthAccount.recover_message(msg, signature=req.buyer_signature)
                if recovered.lower() != req.buyer_address.lower():
                    raise HTTPException(
                        status_code=403,
                        detail=f"Signature does not match buyer_address (recovered {recovered})",
                    )
            except HTTPException:
                raise
            except Exception as e:
                raise HTTPException(status_code=400, detail=f"Invalid buyer_signature: {e}")
        elif req.buyer_signature and len(req.buyer_signature) > 132:
            # Smart-wallet (EIP-1271) signature: too long to verify locally
            # without a chain RPC call. Accept under the chain-payment +
            # signature-presence gate; full verification lives on the chain
            # side at audit time.
            pass
        elif not _allow_unsigned:
            raise HTTPException(
                status_code=401,
                detail=(
                    "buyer_signature is required. Sign 'djinn:purchase:"
                    f"{signal_id}' with your wallet. Set "
                    "DJINN_ALLOW_UNSIGNED_PURCHASE=1 only for legacy / "
                    "test-only validator instances."
                ),
            )

        # Acquire per-signal lock to prevent concurrent purchase races (R25-15)
        async with _purchase_locks_guard:
            if signal_id not in _purchase_locks:
                if len(_purchase_locks) > 10_000:
                    raise HTTPException(status_code=503, detail="Server busy, try again")
                _purchase_locks[signal_id] = asyncio.Lock()
            signal_lock = _purchase_locks[signal_id]

        async with signal_lock:
            # Throttle cleanup to at most once per 60 seconds
            import time as _time

            _now = _time.monotonic()
            if _now - _last_cleanup[0] > 60:
                _mpc.cleanup_expired()
                purchase_orch.cleanup_stale()
                purchase_orch.cleanup_completed()
                _last_cleanup[0] = _now

            # Check we hold a share for this signal
            all_records = share_store.get_all(signal_id)
            if not all_records:
                raise HTTPException(status_code=404, detail="Signal not found on this validator")
            record = all_records[0]

            # Phase 1 of MPC batch settlement: if the client supplied the
            # per-line BPA/WPA vectors, record them keyed by (signal_id,
            # buyer_address). This is idempotent — only the FIRST
            # recording for a given pair is kept. See
            # docs/specs/mpc-batch-settlement.md for the full design.
            # The stored vectors are used at audit time by the batch
            # settlement MPC; they are NOT yet trusted as inputs to the
            # on-chain Escrow.purchase() call (that's Phase 2).
            if (
                purchase_odds_ledger is not None
                and req.bpas is not None
                and req.wpas is not None
                and req.bpa_mode is not None
            ):
                try:
                    purchase_odds_ledger.record(
                        signal_id=signal_id,
                        buyer_address=req.buyer_address,
                        bpas=req.bpas,
                        wpas=req.wpas,
                        bpa_mode=req.bpa_mode,
                    )
                    # P0-01 fix: broadcast to committee peers so any
                    # validator can assemble PurchaseInputs at audit time.
                    # Fire-and-forget — the purchase response must not
                    # wait on fan-out latency.
                    asyncio.create_task(
                        _gossip_purchase_odds_to_peers(
                            neuron=neuron,
                            signal_id=signal_id,
                            buyer_address=req.buyer_address,
                            bpas=req.bpas,
                            wpas=req.wpas,
                            bpa_mode=req.bpa_mode,
                        )
                    )

                    # v1720: also add to audit_set_store + gossip the
                    # (genius, idiot, signal_id) tuple so peers can settle
                    # this pair without waiting for their next bootstrap
                    # cycle. Pre-fix: /v1/signal/{id}/purchase recorded
                    # BPA/WPA + gossiped vectors but NEVER created the
                    # audit_set entry. The settlement loop iterates
                    # audit_set_store.get_ready_sets — without an entry,
                    # the (genius, idiot) pair is invisible to settlement
                    # forever, even with full BPA/WPA on every validator.
                    # Cohort 5 (10 fresh signals on 0xa68C9DA6, full
                    # BPA/WPA on 3 validators) sat unvoted for 2 hours
                    # because of this. record.genius_address is populated
                    # at bundle-store time, so it's available here.
                    if audit_set_store is not None:
                        try:
                            audit_set_store.add_signal(
                                genius=record.genius_address,
                                idiot=req.buyer_address,
                                cycle=0,
                                signal_id=signal_id,
                            )
                            if neuron is not None:
                                asyncio.create_task(
                                    _gossip_audit_set_to_peers(
                                        neuron=neuron,
                                        genius=record.genius_address,
                                        idiot=req.buyer_address,
                                        signal_id=signal_id,
                                        purchase_id=0,
                                    )
                                )
                        except Exception as e:
                            log.warning(
                                "audit_set_add_on_purchase_failed",
                                signal_id=signal_id,
                                err=str(e)[:120],
                            )
                except ValueError as e:
                    # Don't fail the purchase over a ledger write; log
                    # and continue. The purchase flow is still correct
                    # without the record, it just means the batch
                    # settlement will fall back to cross-line max for
                    # this buyer.
                    log.warning(
                        "purchase_odds_record_failed",
                        signal_id=signal_id,
                        buyer=req.buyer_address[:10],
                        error=str(e),
                    )

            # Initiate purchase
            purchase = purchase_orch.initiate(signal_id, req.buyer_address, req.sportsbook)
            if purchase.status == PurchaseStatus.FAILED:
                raise HTTPException(status_code=500, detail="Purchase initiation failed")

            # Skip MPC if it already passed for this signal+buyer (share collection
            # retry after on-chain payment). MPC only needs to run once.
            mpc_already_passed = (
                purchase.status == PurchaseStatus.AWAITING_PAYMENT
                and purchase.mpc_result is not None
                and purchase.mpc_result.available
            )

            if mpc_already_passed:
                mpc_result = purchase.mpc_result
                log.info("mpc_skipped_already_passed", signal_id=signal_id, buyer=req.buyer_address)
            else:
                # Oracle attack mitigation. Before running MPC, independently
                # query the miner network to see which indices are actually
                # available at the buyer's preferred books. If the buyer's
                # claimed available_indices includes any index the validator
                # cannot see as available, treat it as a binary-search probe
                # of the real signal index and reject. The cross-check is
                # gated by DJINN_FF_PURCHASE_V2 so it can be rolled out in
                # shadow mode (log-only) before becoming strict (reject).
                #
                # Reasoning: a malicious buyer can binary-search the hidden
                # real index by submitting purchases with carefully chosen
                # available_indices subsets and observing which complete vs.
                # fail. The fix is for the validator to determine the
                # available set itself, not trust the buyer.
                from djinn_validator.core.purchase_audit import (
                    cross_check as _purchase_cross_check,
                )
                from djinn_validator.core.purchase_audit import (
                    observe_available_indices as _observe_available_indices,
                )
                from djinn_validator.feature_flags import flags as _ff

                buyer_books_for_check: list[str] | None = req.buyer_books
                if not buyer_books_for_check and outcome_attestor._db is not None:
                    try:
                        row = outcome_attestor._db.execute(
                            "SELECT books_json FROM buyer_preferences WHERE address = ?",
                            (req.buyer_address.lower(),),
                        ).fetchone()
                        if row and row[0]:
                            buyer_books_for_check = json.loads(row[0])
                    except Exception as _pref_err:
                        log.warning(
                            "purchase_audit_prefs_lookup_failed",
                            buyer=req.buyer_address[:10],
                            error=str(_pref_err)[:100],
                        )

                if buyer_books_for_check:
                    try:
                        observed = await _observe_available_indices(
                            signal_id=signal_id,
                            buyer_books=buyer_books_for_check,
                            outcome_attestor=outcome_attestor,
                            neuron=neuron,
                        )
                        cross = _purchase_cross_check(
                            claimed_indices=req.available_indices,
                            observed=observed,
                        )
                        # SECURITY: log only counts, NEVER the index sets
                        # themselves. Logging claimed_indices or
                        # extra_in_claim would leak the buyer's view of
                        # which lines they think are real, which combined
                        # with timing data could deanonymize the buyer's
                        # bet. Always counts only.
                        log_fields = dict(
                            signal_id=signal_id,
                            buyer=req.buyer_address[:10],
                            verdict=cross.verdict,
                            claimed_count=len(cross.claimed_indices),
                            observed_count=len(observed.observed_indices),
                            extra_count=len(cross.extra_in_claim),
                            missing_count=len(cross.missing_from_claim),
                            source=observed.source,
                            strict_mode=_ff.purchase_v2,
                        )
                        if cross.is_attack_signal:
                            log.warning("purchase_audit_attack_signal", **log_fields)
                            if _ff.purchase_v2:
                                PURCHASES_PROCESSED.labels(result="oracle_attack").inc()
                                raise HTTPException(
                                    status_code=403,
                                    detail=(
                                        "Purchase rejected: claimed available_indices contains "
                                        "indices the validator cannot see as live at the buyer's "
                                        "books. This pattern matches a binary-search probe of the "
                                        "real signal index. If you believe this is in error, retry "
                                        "after ensuring your line check is fresh."
                                    ),
                                )
                        elif cross.verdict == "narrowed":
                            log.info("purchase_audit_narrowed", **log_fields)
                        elif cross.verdict == "validator_blind":
                            log.warning("purchase_audit_validator_blind", **log_fields)
                        else:
                            log.info("purchase_audit_pass", **log_fields)
                    except HTTPException:
                        raise
                    except Exception as audit_err:
                        # An audit error must NEVER block a legitimate purchase.
                        # Log loudly and continue with the buyer's claim.
                        log.error(
                            "purchase_audit_failed",
                            signal_id=signal_id,
                            buyer=req.buyer_address[:10],
                            error=str(audit_err)[:200],
                        )
                else:
                    log.info(
                        "purchase_audit_skipped_no_books",
                        signal_id=signal_id,
                        buyer=req.buyer_address[:10],
                        reason="no buyer_books in request and no stored preferences",
                    )

                # Run MPC availability check (multi-validator or single-validator fallback)
                # The MPC checks if realIndex ∈ available_indices. The Shamir shares
                # of the real index are stored in encrypted_index_share (as big-endian
                # bytes), NOT in share_y (which holds the AES key share).
                available_set = set(req.available_indices)

                def _index_share(rec: SignalShareRecord) -> Share:
                    """Extract the real-index Shamir share from a record."""
                    if rec.encrypted_index_share and len(rec.encrypted_index_share) > 0:
                        return Share(x=rec.share.x, y=int.from_bytes(rec.encrypted_index_share, "big"))
                    # Legacy: no index share stored; fall back to share_y (will give wrong results)
                    return rec.share

                local_index_share = _index_share(record)
                all_local_index_shares = [_index_share(r) for r in all_records]
                # Use the per-signal threshold declared at creation time, not the
                # global default. This is critical because signals created during
                # bootstrap may have threshold=2 while the orchestrator default is 7.
                signal_threshold = record.shamir_threshold
                try:
                    # Use pre-computed triples if available (skip OT setup).
                    # These are raw (a, b, c) values; the orchestrator will
                    # Shamir-split them at the actual participant x-coordinates.
                    pre_triples = None
                    try:
                        stored_triples = record.precomputed_triples if hasattr(record, "precomputed_triples") else []
                        pre_triples = [(t.a, t.b, t.c) for t in stored_triples] if stored_triples else None
                    except Exception as triple_err:
                        log.warning("precomputed_triples_load_failed", error=str(triple_err))

                    mpc_result = await asyncio.wait_for(
                        _orchestrator.check_availability(
                            signal_id=signal_id,
                            local_share=local_index_share,
                            available_indices=available_set,
                            local_shares=all_local_index_shares,
                            threshold_override=signal_threshold,
                            precomputed_triples=pre_triples,
                        ),
                        timeout=mpc_availability_timeout,
                    )
                except TimeoutError:
                    from djinn_validator.api.metrics import MPC_ERRORS

                    MPC_ERRORS.labels(reason="timeout").inc()
                    PURCHASES_PROCESSED.labels(result="error").inc()
                    raise HTTPException(status_code=504, detail="MPC availability check timed out")

                purchase_orch.set_mpc_result(signal_id, req.buyer_address, mpc_result)

            if not mpc_result.available:
                PURCHASES_PROCESSED.labels(result="unavailable").inc()
                return PurchaseResponse(
                    signal_id=signal_id,
                    status="unavailable",
                    available=False,
                    message="Signal not available at this sportsbook",
                    mpc_participants=mpc_result.participating_validators,
                    mpc_failure_reason=mpc_result.failure_reason,
                )

            # Check for payment replay (TOCTOU prevention)
            if purchase_orch.is_payment_consumed(signal_id, req.buyer_address):
                PURCHASES_PROCESSED.labels(result="already_purchased").inc()
                # Return the previously released share if available
                record = share_store.get(signal_id)
                if record and req.buyer_address in record.released_to:
                    return PurchaseResponse(
                        signal_id=signal_id,
                        status="complete",
                        available=True,
                        encrypted_key_share=record.encrypted_key_share.hex(),
                        share_x=record.share.x,
                        message="Share already released (idempotent)",
                    )
                return PurchaseResponse(
                    signal_id=signal_id,
                    status="already_purchased",
                    available=True,
                    message="Payment already processed for this signal",
                )

            # Verify on-chain payment before releasing share
            if chain_client is not None:
                try:
                    on_chain_id = _signal_id_to_uint256(signal_id)
                    purchase_record = await asyncio.wait_for(
                        chain_client.verify_purchase(on_chain_id, req.buyer_address),
                        timeout=10.0,
                    )
                    if purchase_record.get("pricePaid", 0) == 0:
                        PURCHASES_PROCESSED.labels(result="payment_required").inc()
                        return PurchaseResponse(
                            signal_id=signal_id,
                            status="payment_required",
                            available=True,
                            message="On-chain payment not found. Call Escrow.purchase() first.",
                        )
                    tx_hash = f"verified-{on_chain_id}"
                except TimeoutError:
                    log.error("payment_verification_timeout", signal_id=signal_id)
                    raise HTTPException(
                        status_code=504,
                        detail="Payment verification timed out",
                    )
                except Exception as e:
                    log.error("payment_verification_error", signal_id=signal_id, err=str(e))
                    raise HTTPException(
                        status_code=502,
                        detail="Payment verification failed",
                    )
            else:
                # In production, refuse to release shares without payment verification
                if _is_production:
                    log.error(
                        "share_release_blocked",
                        signal_id=signal_id,
                        reason="No chain client in production — cannot verify payment",
                    )
                    raise HTTPException(
                        status_code=503,
                        detail="Payment verification unavailable. Validator misconfigured.",
                    )
                # Dev mode: no chain client configured — skip payment check
                log.warning(
                    "payment_check_skipped",
                    signal_id=signal_id,
                    reason="no chain client configured",
                )
                tx_hash = "dev-mode-no-verification"

            # Record the payment to prevent replay attacks
            if not purchase_orch.record_payment(signal_id, req.buyer_address, tx_hash, "PAYMENT_CONFIRMED"):
                log.warning("concurrent_payment_race", signal_id=signal_id, buyer=req.buyer_address)
                # Another concurrent request already recorded — wait briefly for share release
                for _retry in range(5):
                    record = share_store.get(signal_id)
                    if record and record.encrypted_key_share and req.buyer_address in record.released_to:
                        return PurchaseResponse(
                            signal_id=signal_id,
                            status="complete",
                            available=True,
                            encrypted_key_share=record.encrypted_key_share.hex(),
                            share_x=record.share.x,
                            message="Share already released (concurrent request)",
                        )
                    await asyncio.sleep(0.5)
                raise HTTPException(
                    status_code=409, detail="Payment already processed — share not yet available, retry shortly"
                )

            result = purchase_orch.confirm_payment(signal_id, req.buyer_address, tx_hash)
            if result is None or result.status == PurchaseStatus.FAILED:
                raise HTTPException(status_code=500, detail="Share release failed")

            # confirm_payment already released the share; read the encrypted key share
            record = share_store.get(signal_id)
            if record is None or record.encrypted_key_share is None:
                raise HTTPException(status_code=500, detail="Share release failed")
            share_data = record.encrypted_key_share

            # Mark payment as fully consumed (share released)
            purchase_orch.update_payment_status(signal_id, req.buyer_address, "SHARES_RELEASED")

            PURCHASES_PROCESSED.labels(result="available").inc()
            ACTIVE_SHARES.set(share_store.count)

            return PurchaseResponse(
                signal_id=signal_id,
                status="complete",
                available=True,
                encrypted_key_share=share_data.hex(),
                share_x=record.share.x,
                message="Key share released",
            )

    @app.post("/v1/signal/{signal_id}/register", response_model=RegisterSignalResponse)
    async def register_signal(
        signal_id: str,
        req: RegisterSignalRequest,
        request: Request,
    ) -> RegisterSignalResponse:
        """Register a purchased signal for blind outcome tracking.

        Accepts all 10 public decoy lines (already committed on-chain).
        The validator resolves every line, producing 10 outcomes.  The real
        outcome is selected later by batch MPC at the audit-set level.

        v1724: protects against unsigned re-registration overwriting outcome
        metadata. First-writer-wins for the (sport, event_id, teams, lines)
        tuple; idempotent re-submits with identical data return "duplicate".
        Re-submits that DIFFER are rejected with 409 unless the caller
        signed the request with a validator hotkey (operator override path
        for legitimate fixes). Codex audit 2026-05-05 High finding #2.
        """
        _validate_signal_id_path(signal_id)
        if req.sport not in SUPPORTED_SPORTS:
            raise HTTPException(status_code=400, detail="Unsupported sport key")
        parsed_lines = [parse_pick(line) for line in req.lines]
        # v1676 (P1-36): use client-provided game_date when set so the
        # OutcomeAttestor's ESPN lookup is deterministic across validators.
        # Empty string from the client is normalized to None to match the
        # default-back-walk path.
        meta_game_date = (req.game_date or None) if req.game_date else None
        metadata = SignalMetadata(
            signal_id=signal_id,
            sport=req.sport,
            event_id=req.event_id,
            home_team=req.home_team,
            away_team=req.away_team,
            lines=parsed_lines,
            game_date=meta_game_date,
        )
        # v1724: check for validator-hotkey signature on the request to
        # decide whether to allow overwrite. Validators legitimately
        # re-register signals via gossip / reconciliation paths; the
        # signature proves the caller is a registered SN103 validator
        # (not a random poisoner). Unsigned callers get first-writer-wins.
        allow_overwrite = False
        try:
            await validate_signed_request(request, _get_validator_hotkeys())
            allow_overwrite = True
        except HTTPException:
            allow_overwrite = False
        register_outcome = outcome_attestor.register_signal(metadata, allow_overwrite=allow_overwrite)
        if register_outcome == "overwrite_rejected":
            raise HTTPException(
                status_code=409,
                detail=(
                    "Signal already registered with different metadata. "
                    "Re-registration that overwrites existing fields requires "
                    "a validator-hotkey-signed request."
                ),
            )

        # Add to audit set if genius/idiot addresses are provided
        if audit_set_store and req.genius_address and req.idiot_address:
            audit_set_store.add_signal(
                genius=req.genius_address,
                idiot=req.idiot_address,
                cycle=req.cycle,
                signal_id=signal_id,
                notional=req.notional,
                odds=req.odds,
                sla_bps=req.sla_bps,
            )

        return RegisterSignalResponse(
            signal_id=signal_id,
            registered=True,
            lines_count=len(parsed_lines),
        )

    @app.post("/v1/signals/resolve", response_model=ResolveResponse)
    async def resolve_signals(request: Request) -> ResolveResponse:
        """Check all pending signals and resolve any with completed games.

        AUTHENTICATION REQUIRED. This triggers outbound ESPN API
        calls for every pending signal, which is expensive and
        rate-limited upstream. Only registered SN103 validators may
        call it — the validator also self-calls this on a schedule.
        In BT_NETWORK=test mode the check is a no-op.

        Resolution stores 10 line outcomes on each signal's metadata.
        Settlement happens later at the audit-set level via batch MPC.
        """
        if os.environ.get("BT_NETWORK", "").lower() in ("finney", "mainnet"):
            try:
                await validate_signed_request(request, _get_validator_hotkeys())
            except HTTPException:
                log.warning(
                    "resolve_signals_unauthenticated_attempt",
                    src_ip=request.client.host if request.client else "unknown",
                )
                raise

        hotkey = ""
        if neuron:
            hotkey = neuron.wallet.hotkey.ss58_address if neuron.wallet else ""

        try:
            resolved_ids = await asyncio.wait_for(
                outcome_attestor.resolve_all_pending(hotkey),
                timeout=30.0,
            )
        except TimeoutError:
            log.error("resolve_all_pending_timeout")
            raise HTTPException(status_code=504, detail="Signal resolution timed out")

        # Record outcomes on audit set store
        results = []
        for signal_id in resolved_ids:
            meta = outcome_attestor.get_signal(signal_id)
            if meta and meta.outcomes:
                if audit_set_store:
                    audit_set_store.record_outcomes(
                        signal_id,
                        meta.outcomes,
                    )
                results.append(
                    {
                        "signal_id": signal_id,
                        "outcomes_count": len(meta.outcomes),
                    }
                )
        return ResolveResponse(resolved_count=len(resolved_ids), results=results)

    @app.get("/v1/audit/summary", response_model=AuditSummaryResponse)
    async def audit_summary() -> AuditSummaryResponse:
        """Audit-queue state at a glance for external monitors.

        Returns per-bucket counts and per-signal totals for all audit sets
        this validator is tracking. Safe to poll every few seconds; the
        underlying store holds everything in memory and the summary
        iteration is O(sets). Buckets:
          - waiting_for_outcomes: at least one signal not yet resolved
          - ready_for_settlement: fully resolved, not yet settled
          - permanently_abstained (v1742): subset of ready_for_settlement
            that the v1716 abstain counter has evicted; settle-eligible
            count = ready_for_settlement - permanently_abstained
          - settled: marked settled (post-onchain)
        """
        if audit_set_store is None:
            raise HTTPException(status_code=503, detail="Audit set store not configured")
        s = audit_set_store.summary()
        # v1744: surface durable gossip queue depth alongside the bucket
        # counts so operators can see at a glance whether there are
        # stragglers mid-flight to recovering peers.
        try:
            from djinn_validator.core import gossip_outbox

            outbox = gossip_outbox.stats()
            s["gossip_outbox_pending"] = outbox.get("pending", 0)
            s["gossip_outbox_acked"] = outbox.get("acked", 0)
            s["gossip_outbox_failed_terminal"] = outbox.get("failed_terminal", 0)
        except Exception:  # pragma: no cover — defensive
            pass
        return AuditSummaryResponse(**s)

    @app.get("/v1/diag/v1747")
    async def diag_v1747(request: Request) -> dict[str, Any]:
        """v1747 dual-write diagnostic snapshot. Hotkey-signed access only.

        Operator-to-operator debug surface: lets a validator with a
        registered SN103 hotkey query any peer for its v1747 sign + submit
        state without SSH access. Used to diagnose silent failures (e.g.
        validator signs locally but submit reverts on a specific error
        code, or signs never fire because _line_resolutions is empty).

        Privacy invariant (audited 2026-05-09): all returned fields are
        either pure counters, content-addressed-public values (lineHash
        is derivable from on-chain decoyLines), or error codes only.
        Never includes signal_id, buyer/purchase data, raw signatures,
        peer IPs, MPC share values, or error message bodies. See
        OutcomeAttestor.diag_v1747 docstring for the field-by-field
        rationale.

        If you add fields here, audit each new field against the
        privacy invariant in CLAUDE.md before merging.
        """
        await validate_signed_request(request, _get_validator_hotkeys())
        if outcome_attestor is None:
            raise HTTPException(status_code=503, detail="OutcomeAttestor not configured")
        return outcome_attestor.diag_v1747()

    @app.get("/v1/audit/{genius}/{idiot}/status", response_model=AuditSetStatusResponse)
    async def audit_set_status(genius: str, idiot: str, cycle: int = 0) -> AuditSetStatusResponse:
        """Check the status of an audit set for a genius-idiot pair."""
        if audit_set_store is None:
            raise HTTPException(status_code=503, detail="Audit set store not configured")
        audit_set = audit_set_store.get_set(genius, idiot, cycle)
        if audit_set is None:
            raise HTTPException(status_code=404, detail="Audit set not found")
        resolved_count = sum(1 for s in audit_set.signals.values() if s.outcomes is not None)
        return AuditSetStatusResponse(
            genius=audit_set.genius_address,
            idiot=audit_set.idiot_address,
            cycle=audit_set.cycle,
            signals_count=len(audit_set.signals),
            resolved_count=resolved_count,
            ready=audit_set.ready_for_settlement,
            settled=audit_set.settled,
        )

    @app.get("/v1/audit/{genius}/{idiot}/detail")
    async def audit_set_detail(genius: str, idiot: str, cycle: int = 0):
        """Dump per-signal membership + outcome-resolution + local-share state.

        Read-only diagnostic used to localize P0-01 input divergence across
        validators. Exposes no secret material: signal_ids, purchase_ids,
        and whether outcomes are populated are all derivable from
        public on-chain events. Intended for fleet cross-comparison.
        """
        if audit_set_store is None:
            raise HTTPException(status_code=503, detail="Audit set store not configured")
        audit_set = audit_set_store.get_set(genius, idiot, cycle)
        if audit_set is None:
            raise HTTPException(status_code=404, detail="Audit set not found")
        signals = []
        for sid, sig in sorted(
            audit_set.signals.items(),
            key=lambda kv: (int(kv[1].purchase_id), kv[0]),
        ):
            has_local_share = False
            try:
                if share_store is not None:
                    has_local_share = share_store.get(sid) is not None
            except Exception:
                has_local_share = False
            # v1677 (P1-33 partial): expose BPA/WPA presence so the readiness
            # diagnostic can predict build_pi success accurately. build_pi
            # abstains on missing BPA/WPA even when has_local_share + outcomes
            # are present, so without this field the diagnostic over-reports
            # quorum-readiness.
            has_bpa_wpa = False
            try:
                if purchase_odds_ledger is not None:
                    rec = purchase_odds_ledger.get(signal_id=sid, buyer_address=audit_set.idiot_address)
                    has_bpa_wpa = rec is not None
            except Exception:
                has_bpa_wpa = False
            # v1680 (P1-36 visibility): hash of outcomes so operators can
            # compare across validators without leaking actual outcomes.
            # Two validators with the same matched ESPN game produce the
            # same outcomes → same hash. Divergent matches → different
            # hashes → operator sees the gap. None when unresolved.
            outcomes_hash = None
            if sig.outcomes is not None:
                try:
                    from eth_utils import keccak

                    outcomes_hash = (
                        "0x" + keccak(bytes(int(o) for o in sig.outcomes)).hex()[:16]
                    )  # truncated to 8 bytes for compactness
                except Exception:
                    outcomes_hash = None
            signals.append(
                {
                    "signal_id": sid,
                    "purchase_id": int(sig.purchase_id),
                    "notional": int(sig.notional),
                    "odds": int(sig.odds),
                    "sla_bps": int(sig.sla_bps),
                    "outcomes_resolved": sig.outcomes is not None,
                    "outcomes_count": len(sig.outcomes) if sig.outcomes else 0,
                    "outcomes_hash": outcomes_hash,
                    "has_local_share": has_local_share,
                    "has_bpa_wpa": has_bpa_wpa,
                }
            )
        return {
            "genius": audit_set.genius_address,
            "idiot": audit_set.idiot_address,
            "cycle": audit_set.cycle,
            "version": audit_set.version,
            "ready": audit_set.ready_for_settlement,
            "settled": audit_set.settled,
            "signals_count": len(audit_set.signals),
            "signals": signals,
        }

    @app.post("/v1/signal/{signal_id}/outcome", response_model=OutcomeResponse)
    async def attest_outcome(
        signal_id: str,
        req: OutcomeRequest,
        request: Request,
    ) -> OutcomeResponse:
        """Submit an outcome attestation for a signal.

        AUTHENTICATION REQUIRED. The request must be signed by the
        SAME validator hotkey that appears in req.validator_hotkey.
        Without this check, any unauthenticated caller could pollute
        the in-memory attestations dict with forged votes under any
        validator's identity and flip the consensus response. In
        BT_NETWORK=test mode the check is a no-op (no metagraph).
        """
        # AUTH FIRST. allowed_hotkeys = current SN103 validator set.
        # In test mode _get_validator_hotkeys returns None and
        # validate_signed_request takes its test-mode escape hatch.
        if os.environ.get("BT_NETWORK", "").lower() in ("finney", "mainnet"):
            try:
                verified = await validate_signed_request(request, _get_validator_hotkeys())
            except HTTPException:
                log.warning(
                    "attest_outcome_unauthenticated_attempt",
                    signal_id=signal_id[:40],
                    src_ip=request.client.host if request.client else "unknown",
                )
                raise
            if verified and verified != req.validator_hotkey:
                log.warning(
                    "attest_outcome_hotkey_mismatch",
                    signer=verified[:10],
                    claimed=req.validator_hotkey[:10],
                )
                raise HTTPException(
                    status_code=403,
                    detail="Attestation must be signed by the claimed validator hotkey",
                )

        _validate_signal_id_path(signal_id)
        try:
            event_result = await asyncio.wait_for(
                outcome_attestor.fetch_event_result(req.event_id),
                timeout=10.0,
            )
        except TimeoutError:
            log.error("fetch_event_result_timeout", event_id=req.event_id)
            raise HTTPException(status_code=504, detail="Event result fetch timed out")
        outcome = Outcome(req.outcome)

        outcome_attestor.attest(
            signal_id=signal_id,
            validator_hotkey=req.validator_hotkey,
            outcome=outcome,
            event_result=event_result,
        )
        OUTCOMES_ATTESTED.labels(outcome=outcome.value).inc()

        # Check if consensus is reached
        if neuron and neuron.metagraph:
            total_validators = sum(
                1 for uid in range(neuron.metagraph.n.item()) if neuron.metagraph.validator_permit[uid].item()
            )
        else:
            total_validators = 1  # Single-validator dev mode
            log.warning("no_metagraph", msg="Using total_validators=1 (no metagraph available)")

        consensus = outcome_attestor.check_consensus(signal_id, total_validators)

        return OutcomeResponse(
            signal_id=signal_id,
            outcome=req.outcome,
            consensus_reached=consensus is not None,
            consensus_outcome=consensus.value if consensus else None,
        )

    # ------------------------------------------------------------------
    # Web Attestation (whitepaper §15 — pure Bittensor)
    # ------------------------------------------------------------------

    import os as _os

    _ATTEST_MAX_CONCURRENT = int(_os.environ.get("ATTEST_MAX_CONCURRENT", "15"))
    _attest_semaphore = asyncio.Semaphore(_ATTEST_MAX_CONCURRENT)

    # Per-miner circuit breakers: 3 consecutive failures -> open for 60s.
    # Prevents wasting parallel fan-out slots on miners whose sidecar is down.
    _miner_breakers: dict[int, CircuitBreaker] = {}

    def _get_miner_breaker(uid: int, _active_uids: set[int] | None = None) -> CircuitBreaker:
        if uid not in _miner_breakers:
            # Prune stale entries when dict grows too large
            if len(_miner_breakers) > 500 and _active_uids:
                stale = [u for u in _miner_breakers if u not in _active_uids]
                for u in stale:
                    del _miner_breakers[u]
                if stale:
                    log.info("miner_breakers_pruned", count=len(stale))
            _miner_breakers[uid] = CircuitBreaker(
                name=f"miner_{uid}",
                failure_threshold=3,
                recovery_timeout=60.0,
            )
        return _miner_breakers[uid]

    @app.get("/v1/attest/capacity")
    async def attest_capacity() -> dict:
        """Return current attestation capacity for admission control."""
        inflight = _ATTEST_MAX_CONCURRENT - _attest_semaphore._value
        return {
            "inflight": inflight,
            "max": _ATTEST_MAX_CONCURRENT,
            "available": _attest_semaphore._value,
        }

    @app.post("/v1/attest", response_model=AttestResponse)
    async def attest_url(req: AttestRequest) -> AttestResponse:
        """Dispatch a TLSNotary attestation request to a miner and verify the proof.

        Flow:
        1. Check admission control — reject immediately if at capacity
        2. Rank miners by attestation track record (proven > unproven > failed)
        3. Try up to 3 miners sequentially with short timeouts
        4. Verify the returned TLSNotary proof
        5. Return the verified proof to the caller
        """

        # Admission control: reject immediately if at capacity
        if _attest_semaphore._value <= 0:
            return AttestResponse(
                request_id=req.request_id,
                url=req.url,
                success=False,
                error="Validator at capacity -- try another validator",
                busy=True,
                retry_after=30,
            )

        async with _attest_semaphore:
            return await _attest_url_inner(req)

    async def _attest_url_inner(req: AttestRequest) -> AttestResponse:
        import json as _json
        import time as _t

        import httpx

        from djinn_validator.core.challenges import (
            assign_peer_notary,
            discover_peer_notaries,
        )

        start = _t.perf_counter()
        ATTESTATION_DISPATCHED.inc()

        # Resolve redirects to get the canonical URL so the TLS server_name
        # in the proof matches what we verify against (e.g. hackernews.com → news.ycombinator.com)
        try:
            async with httpx.AsyncClient(follow_redirects=True, timeout=10.0) as client:
                head = await client.head(req.url)
                resolved_url = str(head.url)
                if resolved_url != req.url:
                    log.info("attest_url_resolved", original=req.url, resolved=resolved_url)
                    req = AttestRequest(url=resolved_url, request_id=req.request_id)
        except Exception as e:
            log.debug("attest_redirect_check_failed", url=req.url, error=str(e))

        # SSRF protection: verify the resolved URL's hostname resolves to a public IP.
        # Prevents redirects to internal/private network addresses.
        try:
            from urllib.parse import urlparse

            _parsed = urlparse(req.url)
            _hostname = _parsed.hostname or ""
            if _hostname:
                _resolved_ip = socket.gethostbyname(_hostname)
                if not ipaddress.ip_address(_resolved_ip).is_global:
                    log.warning(
                        "attest_ssrf_blocked",
                        url=req.url,
                        resolved_ip=_resolved_ip,
                    )
                    return AttestResponse(
                        request_id=req.request_id,
                        url=req.url,
                        success=False,
                        error="URL resolves to a non-public IP address",
                    )
        except Exception as e:
            log.debug("attest_ssrf_check_failed", url=req.url, error=str(e))

        # Build axon lookup by UID
        axon_by_uid: dict[int, dict] = {}
        if neuron:
            for uid in neuron.get_miner_uids():
                try:
                    axon = neuron.get_axon_info(uid)
                    ip = axon.get("ip", "")
                    port = axon.get("port", 0)
                    if ip and port:
                        axon_by_uid[uid] = {
                            "uid": uid,
                            "ip": ip,
                            "port": port,
                            "hotkey": axon.get("hotkey", ""),
                            "coldkey": axon.get("coldkey", ""),
                        }
                except (IndexError, KeyError, AttributeError) as exc:
                    log.warning("attest_axon_lookup_failed", uid=uid, error=str(exc))

        # Discover peer notaries from the metagraph, then filter to only
        # notaries whose miners have a verified proactive proof. This ensures
        # we only assign notaries with working TLSNotary binaries, not v726
        # miners that pass WebSocket handshake but have broken MPC.
        peer_notaries = []
        if axon_by_uid:
            try:
                all_notaries = await discover_peer_notaries(_attest_client, list(axon_by_uid.values()))
                # Filter notaries by binary version compatibility.
                # MPC requires matching binary versions. Different builds of
                # the TLSNotary library are not interoperable.
                if scorer is not None:
                    verified = [
                        n for n in all_notaries if (m := scorer.get(n.uid)) is not None and m.proactive_proof_verified
                    ]
                    if not verified:
                        peer_notaries = all_notaries
                        log.info("attest_peer_notaries_no_verified", total=len(all_notaries))
                    else:
                        # Group verified notaries by binary hash
                        by_hash: dict[str, list] = {}
                        for n in verified:
                            m = scorer.get(n.uid)
                            bh = m.tlsn_binary_hash if m else ""
                            by_hash.setdefault(bh or "unknown", []).append(n)

                        # Find the binary hash of the candidate miners (provers).
                        # Prefer notaries matching the prover's binary hash.
                        # Collect all prover binary hashes from the candidate pool.
                        prover_hashes: set[str] = set()
                        for uid_key in axon_by_uid:
                            pm = scorer.get(uid_key)
                            if pm and pm.tlsn_binary_hash:
                                prover_hashes.add(pm.tlsn_binary_hash)

                        # Select notaries matching any prover's binary hash
                        compatible = []
                        for bh in prover_hashes:
                            compatible.extend(by_hash.get(bh, []))

                        if compatible:
                            peer_notaries = compatible
                            log.info(
                                "attest_peer_notaries_version_matched",
                                matched=len(compatible),
                                verified=len(verified),
                                total=len(all_notaries),
                                hashes=list(prover_hashes),
                            )
                        else:
                            # No version match; fall back to all verified
                            peer_notaries = verified
                            log.info(
                                "attest_peer_notaries_no_version_match", verified=len(verified), total=len(all_notaries)
                            )
                else:
                    peer_notaries = all_notaries
                log.info("attest_peer_notaries_discovered", count=len(peer_notaries))
            except Exception as e:
                log.warning("attest_peer_notary_discovery_failed", error=str(e))

        # Smart miner selection: proven miners first, then unproven.
        # Skip miners whose circuit breaker is open (known-down sidecars).
        # When min_memory_gb is set, filter to miners with sufficient available RAM.
        _min_mem_mb = int((req.min_memory_gb or 0) * 1024)
        candidates: list[tuple[dict, str]] = []  # (axon_info, tier)
        breaker_deferred: list[tuple[dict, str]] = []  # circuit-broken, appended last
        if scorer is not None and axon_by_uid:
            ranked = scorer.select_attest_miners(list(axon_by_uid.keys()))
            for uid, tier in ranked:
                if uid in axon_by_uid:
                    # Filter by memory requirement if specified
                    if _min_mem_mb > 0:
                        m = scorer.get(uid)
                        if m and m.capabilities_reported and m.memory_available_mb < _min_mem_mb:
                            continue
                    breaker = _get_miner_breaker(uid)
                    if breaker.allow_request():
                        candidates.append((axon_by_uid[uid], tier))
                    else:
                        breaker_deferred.append((axon_by_uid[uid], tier))
            candidates.extend(breaker_deferred)

        # Fallback: if scorer has no data yet, try all miners with health responses
        if not candidates and axon_by_uid:
            for uid, axon in list(axon_by_uid.items())[:5]:
                breaker = _get_miner_breaker(uid)
                if breaker.allow_request():
                    candidates.append((axon, "unproven"))

        # Always include the fallback miner in the parallel race.
        # Metagraph miners often fail (broken sidecars, version mismatch),
        # wasting 60-120s before the sequential fallback can start.
        # Racing the fallback alongside metagraph miners means we get a
        # result in ~70s even if all metagraph miners fail.
        if fallback_miner_url:
            candidates.append(
                (
                    {
                        "uid": -1,
                        "ip": "",
                        "port": 0,
                        "hotkey": "fallback",
                        "_url": fallback_miner_url.rstrip("/") + "/v1/attest",
                    },
                    "fallback",
                )
            )

        if not candidates:
            if attestation_log is not None:
                attestation_log.log_attestation(
                    url=req.url,
                    request_id=req.request_id,
                    success=False,
                    verified=False,
                    error="No reachable miners available",
                )
            return AttestResponse(
                request_id=req.request_id,
                url=req.url,
                success=False,
                error="No reachable miners available",
            )

        log.info(
            "attest_candidates",
            url=req.url,
            request_id=req.request_id,
            candidates=[(c[0]["uid"], c[1]) for c in candidates],
        )

        # Fan out to up to 5 miners in parallel, first success wins
        last_error = "No miners attempted"
        miner_data: dict | None = None
        selected: dict | None = None
        proof_hex: str | None = None
        selected_notary_uid: int | None = None
        selected_notary_pubkey: str | None = None
        _failed_notary_uids: set[int] = set()
        _notary_assignment_counts: dict[int, int] = {}

        def _credit_notary_duty(
            notary_uid: int | None,
            proof_valid: bool,
            proof_bytes: int = 0,
            duration_ms: int = 0,
        ) -> None:
            """Credit a peer notary for serving in this attest request.

            Increments notary_duties_assigned unconditionally and
            notary_duties_completed when proof_valid. Feeds notary_reliability
            and total_scored_samples. Call only at outcome points where the
            notary was actually involved in MPC (miner reached the notary and
            either returned a proof or failed with a notary-attributable
            error). Pre-miner-response failures do not credit a duty.

            proof_bytes and duration_ms accumulate only on proof_valid=True;
            they feed future DJINN_FF_PROOF_COMPLEXITY_WEIGHT gating that
            rewards notaries serving heavier sessions.
            """
            if scorer is None or notary_uid is None:
                return
            hk = axon_by_uid.get(notary_uid, {}).get("hotkey", f"notary-{notary_uid}")
            nm = scorer.get_or_create(notary_uid, hk)
            nm.record_notary_duty(
                proof_valid,
                proof_bytes=proof_bytes,
                duration_ms=duration_ms,
            )

        async def _try_miner(axon: dict, tier: str) -> tuple[dict, dict, str, float, int | None, str | None] | None:
            """Try one miner. Returns (axon, data, proof_hex, elapsed_s, notary_uid, notary_pubkey) on success."""
            attempt_start = _t.perf_counter()
            miner_url = axon.get("_url") or f"http://{axon['ip']}:{axon['port']}/v1/attest"
            # 180s for proven/unproven (proofs take 90-105s on typical hardware),
            # 60s for redemption, 180s for fallback.
            _tier_timeouts = {"proven": 180.0, "unproven": 180.0, "redemption": 60.0, "fallback": 180.0}
            tier_timeout = _tier_timeouts.get(tier, 90.0)
            timeout = min(req.timeout or tier_timeout, 600.0)
            breaker = _get_miner_breaker(axon["uid"]) if axon["uid"] >= 0 else None

            # Assign a peer notary, using pair history to prefer compatible notaries
            _prover_metrics = scorer.get(axon["uid"]) if scorer else None
            assigned_notary = assign_peer_notary(
                axon["uid"],
                peer_notaries,
                prover_ip=axon.get("ip"),
                prover_coldkey=axon.get("coldkey"),
                assignment_counts=_notary_assignment_counts,
                max_per_notary=2,
                exclude_uids=_failed_notary_uids,
                pair_successes=_prover_metrics.notary_pair_successes if _prover_metrics else None,
                pair_failures=_prover_metrics.notary_pair_failures if _prover_metrics else None,
            )

            payload: dict = {"url": req.url, "request_id": req.request_id}
            if assigned_notary:
                payload["notary_host"] = assigned_notary.ip
                payload["notary_port"] = assigned_notary.notary_port
                payload["notary_ws_port"] = assigned_notary.port
                if neuron and neuron.wallet:
                    try:
                        from djinn_validator.api.middleware import create_notary_ticket

                        payload["notary_ticket"] = create_notary_ticket(
                            prover_uid=axon["uid"],
                            notary_uid=assigned_notary.uid,
                            wallet=neuron.wallet,
                        )
                    except Exception as _ticket_err:
                        log.warning("attest_notary_ticket_failed", error=str(_ticket_err))

            _body = _json.dumps(payload).encode()
            _auth_hdrs: dict[str, str] = {}
            if neuron and neuron.wallet:
                from djinn_validator.api.middleware import create_signed_headers

                _auth_hdrs = create_signed_headers("/v1/attest", _body, neuron.wallet)

            log.info(
                "attest_dispatching",
                url=req.url,
                request_id=req.request_id,
                miner_uid=axon["uid"],
                tier=tier,
                timeout_s=timeout,
                peer_notary=assigned_notary.uid if assigned_notary else None,
            )

            try:
                resp = await _attest_client.post(
                    miner_url,
                    content=_body,
                    headers={"Content-Type": "application/json", **_auth_hdrs},
                    timeout=timeout,
                )
            except httpx.HTTPError as e:
                elapsed = _t.perf_counter() - attempt_start
                log.warning(
                    "attest_miner_unreachable",
                    miner_uid=axon["uid"],
                    tier=tier,
                    err=str(e),
                    elapsed_s=round(elapsed, 1),
                )
                if breaker:
                    breaker.record_failure()
                if scorer is not None and axon["uid"] >= 0:
                    m = scorer.get_or_create(axon["uid"], axon.get("hotkey", ""))
                    m.record_attestation(latency=elapsed, proof_valid=False)
                if assigned_notary:
                    _failed_notary_uids.add(assigned_notary.uid)
                    if _prover_metrics:
                        _prover_metrics.notary_pair_failures[assigned_notary.uid] = (
                            _prover_metrics.notary_pair_failures.get(assigned_notary.uid, 0) + 1
                        )
                return None

            if resp.status_code != 200:
                log.warning("attest_miner_error", miner_uid=axon["uid"], status=resp.status_code)
                if breaker:
                    breaker.record_failure()
                if scorer is not None and axon["uid"] >= 0:
                    m = scorer.get_or_create(axon["uid"], axon.get("hotkey", ""))
                    m.record_attestation(latency=_t.perf_counter() - attempt_start, proof_valid=False)
                if assigned_notary:
                    _failed_notary_uids.add(assigned_notary.uid)
                return None

            try:
                data = resp.json()
            except Exception:
                log.error("miner_malformed_json", miner_uid=axon["uid"])
                if breaker:
                    breaker.record_failure()
                if scorer is not None and axon["uid"] >= 0:
                    m = scorer.get_or_create(axon["uid"], axon.get("hotkey", ""))
                    m.record_attestation(latency=_t.perf_counter() - attempt_start, proof_valid=False)
                return None

            # Miner busy -- skip without penalising (not a notary failure)
            if data.get("busy"):
                log.info("attest_miner_busy", miner_uid=axon["uid"])
                return None

            if not data.get("success"):
                err = data.get("error", f"Miner {axon['uid']} attestation failed")
                if breaker:
                    breaker.record_failure()
                if scorer is not None and axon["uid"] >= 0:
                    m = scorer.get_or_create(axon["uid"], axon.get("hotkey", ""))
                    m.record_attestation(latency=_t.perf_counter() - attempt_start, proof_valid=False)
                # If the error mentions notary/WebSocket/connection/MPC, mark notary as failed
                _notary_keywords = ("notary", "websocket", "bridge", "connection is closed", "mpc", "preprocessing")
                if assigned_notary and any(kw in err.lower() for kw in _notary_keywords):
                    _failed_notary_uids.add(assigned_notary.uid)
                    # Persist pair failure so future requests avoid this notary
                    if _prover_metrics:
                        _prover_metrics.notary_pair_failures[assigned_notary.uid] = (
                            _prover_metrics.notary_pair_failures.get(assigned_notary.uid, 0) + 1
                        )
                    _credit_notary_duty(assigned_notary.uid, proof_valid=False)
                log.warning("attest_miner_failed", miner_uid=axon["uid"], error=err)
                return None

            phex = data.get("proof_hex")
            if not phex:
                log.warning("attest_miner_no_proof_hex", miner_uid=axon["uid"])
                if breaker:
                    breaker.record_failure()
                if scorer is not None and axon["uid"] >= 0:
                    m = scorer.get_or_create(axon["uid"], axon.get("hotkey", ""))
                    m.record_attestation(latency=_t.perf_counter() - attempt_start, proof_valid=False)
                return None

            # Miner produced a proof -- record circuit breaker success
            if breaker:
                breaker.record_success()

            return (
                axon,
                data,
                phex,
                _t.perf_counter() - attempt_start,
                assigned_notary.uid if assigned_notary else None,
                assigned_notary.pubkey_hex if assigned_notary else None,
            )

        # Launch parallel tasks for all candidates (up to 6).
        # The fallback miner is always appended last, so the limit must
        # be high enough to include it alongside metagraph miners.
        import asyncio as _aio

        pick = candidates[:6]
        tasks = [_aio.create_task(_try_miner(axon, tier)) for axon, tier in pick]

        async def _score_runner_ups(
            remaining: list[_aio.Task],
            _scorer: object,
            _url: str,
            _expected_server: str,
        ) -> None:
            """Background: let remaining miners finish, verify their proofs, and credit only verified ones.

            Pre-fix: runner-ups were credited proof_valid=True without their TLSNotary
            proof being verified — only the winner's proof was checked. A malicious
            miner could return success=true with garbage proof_hex on every request
            and only do real MPC when it expected to win, accumulating reputation
            from runner-up credit alone (especially during 360-block immune period).
            Match the winner-path verification: actually run tlsn_verifier.verify_proof
            on each runner-up's proof before crediting.
            """
            from djinn_validator.core import tlsn as tlsn_verifier

            for t in remaining:
                try:
                    result = await t
                except Exception:
                    continue
                if result is None:
                    continue
                axon, _data, _phex, elapsed, _notary_uid, _notary_pubkey = result
                if _scorer is None or axon["uid"] < 0:
                    continue

                proof_valid = False
                try:
                    proof_bytes = bytes.fromhex(_phex)
                    verify_result = await _aio.wait_for(
                        tlsn_verifier.verify_proof(
                            proof_bytes,
                            expected_server=_expected_server,
                            expected_notary_key=_notary_pubkey,
                        ),
                        timeout=30.0,
                    )
                    proof_valid = verify_result.verified
                except Exception as _verify_err:
                    log.warning(
                        "attest_runner_up_verify_failed",
                        miner_uid=axon["uid"],
                        error=str(_verify_err)[:200],
                    )
                    proof_valid = False

                m = _scorer.get_or_create(axon["uid"], axon.get("hotkey", ""))
                _phex_bytes = len(_phex) // 2 if _phex else 0
                _elapsed_ms = int(elapsed * 1000)
                m.record_attestation(
                    latency=elapsed,
                    proof_valid=proof_valid,
                    proof_bytes=_phex_bytes if proof_valid else 0,
                    duration_ms=_elapsed_ms if proof_valid else 0,
                )
                _credit_notary_duty(
                    _notary_uid,
                    proof_valid=proof_valid,
                    proof_bytes=_phex_bytes if proof_valid else 0,
                    duration_ms=_elapsed_ms if proof_valid else 0,
                )
                log.info(
                    "attest_runner_up_scored",
                    miner_uid=axon["uid"],
                    elapsed_s=round(elapsed, 1),
                    proof_valid=proof_valid,
                    url=_url,
                )

        # Process results as they complete — first success wins
        for coro in _aio.as_completed(tasks):
            try:
                result = await coro
            except Exception as e:
                log.warning("attest_miner_task_error", error=str(e))
                continue
            if result is not None:
                selected, miner_data, proof_hex = result[0], result[1], result[2]
                selected_notary_uid = result[4]
                selected_notary_pubkey = result[5]
                # Let remaining miners finish in background — verify their proofs, credit only verified
                remaining = [t for t in tasks if not t.done()]
                if remaining and scorer is not None:
                    from urllib.parse import urlparse

                    _expected_server = urlparse(req.url).hostname or ""
                    _aio.create_task(_score_runner_ups(remaining, scorer, req.url, _expected_server))
                break
            else:
                last_error = "All attempted miners failed or were busy"

        # All candidates failed. Try fallback miner as last resort.
        # Send the request WITHOUT notary_host so the miner uses its own
        # local notary sidecar (no peer notary = no broken MPC connections).
        if selected is None and fallback_miner_url:
            log.info("attest_trying_fallback_miner", url=req.url, fallback=fallback_miner_url)
            fb_url = fallback_miner_url.rstrip("/") + "/v1/attest"
            fb_body = _json.dumps({"url": req.url, "request_id": req.request_id}).encode()
            fb_hdrs: dict[str, str] = {"Content-Type": "application/json"}
            if neuron and neuron.wallet:
                from djinn_validator.api.middleware import create_signed_headers

                fb_hdrs.update(create_signed_headers("/v1/attest", fb_body, neuron.wallet))
            try:
                fb_resp = await _attest_client.post(
                    fb_url,
                    content=fb_body,
                    headers=fb_hdrs,
                    timeout=180.0,
                )
                if fb_resp.status_code == 200:
                    fb_data = fb_resp.json()
                    if fb_data.get("success") and fb_data.get("proof_hex"):
                        miner_data = fb_data
                        proof_hex = fb_data["proof_hex"]
                        selected = {"uid": -1, "ip": "", "port": 0, "hotkey": "fallback"}
                        log.info("attest_fallback_succeeded", url=req.url)
            except Exception as e:
                log.warning("attest_fallback_failed", error=str(e)[:200])

        # All attempts failed
        if selected is None or miner_data is None or proof_hex is None:
            elapsed = _t.perf_counter() - start
            ATTESTATION_DURATION.observe(elapsed)
            ATTESTATION_VERIFIED.labels(valid="false").inc()
            if attestation_log is not None:
                attestation_log.log_attestation(
                    url=req.url,
                    request_id=req.request_id,
                    success=False,
                    verified=False,
                    elapsed_s=round(elapsed, 2),
                    error=last_error,
                )
            return AttestResponse(
                request_id=req.request_id,
                url=req.url,
                success=False,
                error=last_error,
                busy=True,
                retry_after=15,
            )

        # Verify the TLSNotary proof
        from urllib.parse import urlparse

        from djinn_validator.core import tlsn as tlsn_verifier

        try:
            proof_bytes = bytes.fromhex(proof_hex)
        except (ValueError, TypeError):
            elapsed = _t.perf_counter() - start
            ATTESTATION_DURATION.observe(elapsed)
            ATTESTATION_VERIFIED.labels(valid="false").inc()
            if scorer is not None and selected["uid"] >= 0:
                miner_metrics = scorer.get_or_create(selected["uid"], selected.get("hotkey", ""))
                miner_metrics.record_attestation(latency=elapsed, proof_valid=False)
            _credit_notary_duty(selected_notary_uid, proof_valid=False)
            if attestation_log is not None:
                attestation_log.log_attestation(
                    url=req.url,
                    request_id=req.request_id,
                    success=False,
                    verified=False,
                    miner_uid=selected["uid"],
                    notary_uid=selected_notary_uid,
                    elapsed_s=round(elapsed, 2),
                    error="Miner returned invalid proof hex",
                )
            return AttestResponse(
                request_id=req.request_id,
                url=req.url,
                success=False,
                error="Miner returned invalid proof hex",
            )
        expected_server = urlparse(req.url).hostname

        try:
            verify_result = await asyncio.wait_for(
                tlsn_verifier.verify_proof(
                    proof_bytes,
                    expected_server=expected_server,
                    expected_notary_key=selected_notary_pubkey,
                ),
                timeout=30.0,
            )
        except TimeoutError:
            elapsed = _t.perf_counter() - start
            ATTESTATION_DURATION.observe(elapsed)
            ATTESTATION_VERIFIED.labels(valid="false").inc()
            # Miner DID generate a proof, credit the attempt even though verification timed out
            if scorer is not None and selected["uid"] >= 0:
                miner_metrics = scorer.get_or_create(selected["uid"], selected.get("hotkey", ""))
                miner_metrics.record_attestation(latency=elapsed, proof_valid=False)
            _credit_notary_duty(selected_notary_uid, proof_valid=False)
            if attestation_log is not None:
                attestation_log.log_attestation(
                    url=req.url,
                    request_id=req.request_id,
                    success=True,
                    verified=False,
                    server_name=miner_data.get("server_name"),
                    miner_uid=selected["uid"],
                    notary_uid=selected_notary_uid,
                    elapsed_s=round(elapsed, 2),
                    error="Proof verification timed out",
                )
            return AttestResponse(
                request_id=req.request_id,
                url=req.url,
                success=True,
                verified=False,
                proof_hex=proof_hex,
                server_name=miner_data.get("server_name"),
                timestamp=miner_data.get("timestamp", 0),
                miner_uid=selected["uid"] if selected else None,
                notary_uid=selected_notary_uid,
                error="Proof verification timed out",
            )

        elapsed = _t.perf_counter() - start
        ATTESTATION_DURATION.observe(elapsed)
        ATTESTATION_VERIFIED.labels(valid=str(verify_result.verified).lower()).inc()

        # Record attestation performance in scorer for weight setting
        if scorer is not None and selected["uid"] >= 0:
            miner_metrics = scorer.get_or_create(selected["uid"], selected.get("hotkey", ""))
            miner_metrics.record_attestation(
                latency=elapsed,
                proof_valid=verify_result.verified,
                proof_bytes=(len(proof_hex) // 2 if (verify_result.verified and proof_hex) else 0),
                duration_ms=int(elapsed * 1000) if verify_result.verified else 0,
            )
            # Track pair success/failure for future notary assignment
            if selected_notary_uid is not None:
                if verify_result.verified:
                    miner_metrics.notary_pair_successes[selected_notary_uid] = (
                        miner_metrics.notary_pair_successes.get(selected_notary_uid, 0) + 1
                    )
                else:
                    miner_metrics.notary_pair_failures[selected_notary_uid] = (
                        miner_metrics.notary_pair_failures.get(selected_notary_uid, 0) + 1
                    )
        _credit_notary_duty(
            selected_notary_uid,
            proof_valid=verify_result.verified,
            proof_bytes=len(proof_hex) // 2 if (verify_result.verified and proof_hex) else 0,
            duration_ms=int(elapsed * 1000) if verify_result.verified else 0,
        )

        # Detect bot challenge / protection walls in the response
        is_blocked = _detect_bot_challenge(verify_result.response_body)

        log.info(
            "attest_complete",
            url=req.url,
            request_id=req.request_id,
            verified=verify_result.verified,
            blocked=is_blocked,
            server=verify_result.server_name,
            elapsed_s=round(elapsed, 1),
        )

        if attestation_log is not None:
            attestation_log.log_attestation(
                url=req.url,
                request_id=req.request_id,
                success=True,
                verified=verify_result.verified,
                server_name=verify_result.server_name,
                miner_uid=selected["uid"],
                notary_uid=selected_notary_uid,
                elapsed_s=round(elapsed, 2),
                error="Site served bot challenge"
                if is_blocked
                else (verify_result.error if not verify_result.verified else None),
            )

        return AttestResponse(
            request_id=req.request_id,
            url=req.url,
            success=True,
            verified=verify_result.verified,
            proof_hex=proof_hex,
            response_body=verify_result.response_body or None,
            server_name=verify_result.server_name or miner_data.get("server_name"),
            timestamp=miner_data.get("timestamp", 0),
            miner_uid=selected["uid"] if selected else None,
            notary_uid=selected_notary_uid,
            blocked=is_blocked,
            error=verify_result.error if not verify_result.verified else None,
        )

    @app.get("/v1/metrics/attestations")
    async def admin_attestations(limit: int = 50) -> dict:
        """Recent attestation requests with full details."""
        if attestation_log is None:
            return {"attestations": []}
        return {"attestations": attestation_log.recent_attestations(max(1, min(limit, 200)))}

    @app.get("/v1/metrics/timeseries")
    async def admin_timeseries(hours: int = 168, bucket: int = 3600) -> dict:
        """Time-series metrics for the admin dashboard.

        Args:
            hours: How many hours of history (default 168 = 7 days).
            bucket: Bucket width in seconds (default 3600 = 1 hour).
        """
        import time as _ts

        since = _ts.time() - max(1, min(hours, 720)) * 3600
        bucket_s = max(300, min(bucket, 86400))  # 5min to 1day

        # Attestation time-series
        attest_buckets: list[dict] = []
        if attestation_log is not None:
            attest_buckets = attestation_log.timeseries(
                since=int(since),
                bucket_seconds=bucket_s,
            )

        # Challenge / weight telemetry time-series
        challenge_buckets: list[dict] = []
        weight_buckets: list[dict] = []
        if telemetry is not None:
            raw = telemetry.timeseries(
                categories=[
                    "challenge_round",
                    "attestation_challenge",
                    "weight_set",
                    "weight_set_failed",
                ],
                since=since,
                bucket_seconds=bucket_s,
            )
            # Aggregate challenge rounds
            for b in raw.get("challenge_round", []):
                challenged = sum(d.get("miners_challenged", d.get("challenged", 0)) for d in b["details"])
                responded = sum(d.get("responding", d.get("responded", 0)) for d in b["details"])
                correct = sum(sum(1 for mr in d.get("miners", []) if mr.get("correct")) for d in b["details"])
                challenge_buckets.append(
                    {
                        "t": b["t"],
                        "rounds": b["count"],
                        "challenged": challenged,
                        "responded": responded,
                        "correct": correct,
                    }
                )
            # Aggregate weight setting
            ws_by_t: dict[int, dict] = {}
            for b in raw.get("weight_set", []):
                ws_by_t.setdefault(b["t"], {"t": b["t"], "attempts": 0, "success": 0, "failed": 0})
                ws_by_t[b["t"]]["attempts"] += b["count"]
                ws_by_t[b["t"]]["success"] += b["count"]
            for b in raw.get("weight_set_failed", []):
                ws_by_t.setdefault(b["t"], {"t": b["t"], "attempts": 0, "success": 0, "failed": 0})
                ws_by_t[b["t"]]["attempts"] += b["count"]
                ws_by_t[b["t"]]["failed"] += b["count"]
            weight_buckets = sorted(ws_by_t.values(), key=lambda x: x["t"])

        return {
            "attestations": attest_buckets,
            "challenges": challenge_buckets,
            "weights": weight_buckets,
            "bucket_seconds": bucket_s,
        }

    @app.post("/v1/check")
    async def check_lines(request: Request) -> dict:
        """Fan-out line-check to multiple miners in parallel, merge results.

        Queries up to MAX_CHECK_MINERS miners concurrently and takes the
        union of available_indices.  If ANY miner says a line is available,
        it counts as available.  This compensates for miners with broken
        or exhausted Odds API keys.  Faster, more accurate miners naturally
        contribute more to the merged result.
        """
        import json as _json
        import random as _random
        import time as _time

        from pydantic import ValidationError

        from djinn_validator.api.middleware import create_signed_headers
        from djinn_validator.api.models import CheckRequest

        MAX_CHECK_MINERS = 15

        body = await request.body()

        # Full Pydantic validation against CheckRequest, matching the miner
        # schema. Rejecting malformed payloads here avoids fanning out to 15
        # miners (which would each return 422 and degrade their uptime
        # metrics) and returns a clear, actionable error to the client.
        try:
            payload_dict = _json.loads(body)
        except _json.JSONDecodeError:
            raise HTTPException(status_code=400, detail="Invalid JSON")

        try:
            CheckRequest.model_validate(payload_dict)
        except ValidationError as exc:
            log.warning(
                "check_validation_failed",
                errors=exc.errors(include_url=False)[:5],
                body_preview=str(payload_dict)[:500],
            )
            raise HTTPException(status_code=422, detail=exc.errors(include_url=False))

        payload = payload_dict

        if not neuron:
            raise HTTPException(status_code=503, detail="Validator not connected to network")

        miner_uids = neuron.get_miner_uids()
        if not miner_uids:
            raise HTTPException(status_code=503, detail="No miners available")

        # Build list of reachable miner endpoints
        _random.shuffle(miner_uids)
        targets: list[tuple[int, str]] = []  # (uid, url)
        for uid in miner_uids:
            axon = neuron.get_axon_info(uid)
            ip = axon.get("ip", "")
            port = axon.get("port", 0)
            if not ip or not port or ip in ("0.0.0.0", "127.0.0.1"):
                continue
            targets.append((uid, f"http://{ip}:{port}/v1/check"))
            if len(targets) >= MAX_CHECK_MINERS:
                break

        if not targets:
            raise HTTPException(status_code=503, detail="No reachable miners")

        auth_headers: dict[str, str] = {}
        if neuron.wallet:
            auth_headers = create_signed_headers("/v1/check", body, neuron.wallet)

        start = _time.monotonic()

        # Fire all miner checks in parallel
        async def _query_miner(uid: int, url: str) -> tuple[int, dict | None, float]:
            t0 = _time.monotonic()
            try:
                async with httpx.AsyncClient() as client:
                    resp = await client.post(
                        url,
                        content=body,
                        headers={"Content-Type": "application/json", **auth_headers},
                        timeout=10.0,
                    )
                elapsed = _time.monotonic() - t0
                if resp.status_code != 200:
                    log.warning(
                        "check_miner_error", miner_uid=uid, status=resp.status_code, elapsed_ms=round(elapsed * 1000)
                    )
                    return (uid, None, elapsed)
                data = resp.json()
                if data.get("api_error") and not data.get("available_indices"):
                    log.warning(
                        "check_miner_api_error",
                        miner_uid=uid,
                        api_error=data["api_error"],
                        elapsed_ms=round(elapsed * 1000),
                    )
                    return (uid, None, elapsed)
                return (uid, data, elapsed)
            except Exception as e:
                elapsed = _time.monotonic() - t0
                log.warning("check_miner_failed", miner_uid=uid, error=str(e)[:100], elapsed_ms=round(elapsed * 1000))
                return (uid, None, elapsed)

        results = await asyncio.gather(*[_query_miner(uid, url) for uid, url in targets])

        # Merge: union of available_indices, richest bookmaker data per line
        merged_results: dict[int, dict] = {}
        successful_miners = 0
        fastest_uid: int | None = None
        fastest_time: float = float("inf")

        for uid, data, elapsed in results:
            if data is None:
                continue
            successful_miners += 1
            if elapsed < fastest_time:
                fastest_time = elapsed
                fastest_uid = uid

            for lr in data.get("results", []):
                idx = lr.get("index")
                if idx is None:
                    continue
                existing = merged_results.get(idx)
                if not existing:
                    merged_results[idx] = {**lr, "bookmakers": list(lr.get("bookmakers", []))}
                elif lr.get("available") and not existing.get("available"):
                    merged_results[idx] = {**lr, "bookmakers": list(lr.get("bookmakers", []))}
                elif lr.get("available") and existing.get("available"):
                    if len(lr.get("bookmakers", [])) > len(existing.get("bookmakers", [])):
                        merged_results[idx] = {**lr, "bookmakers": list(lr.get("bookmakers", []))}

        total_elapsed = _time.monotonic() - start

        if successful_miners == 0:
            raise HTTPException(status_code=502, detail="All miners unreachable or have broken API keys")

        # Build response
        all_results = []
        for line in payload["lines"]:
            idx = line.get("index")
            if idx in merged_results:
                all_results.append(merged_results[idx])
            else:
                all_results.append({"index": idx, "available": False, "bookmakers": []})

        available_indices = [r["index"] for r in all_results if r.get("available")]

        log.info(
            "check_merged",
            miners_queried=len(targets),
            miners_ok=successful_miners,
            available=len(available_indices),
            total_lines=len(payload["lines"]),
            fastest_miner=fastest_uid,
            fastest_ms=round(fastest_time * 1000) if fastest_uid else None,
            total_ms=round(total_elapsed * 1000),
        )

        return {
            "results": all_results,
            "available_indices": available_indices,
            "response_time_ms": round(total_elapsed * 1000),
            "miners_queried": len(targets),
            "miners_ok": successful_miners,
        }

    @app.post("/v1/analytics/attempt")
    async def analytics(req: AnalyticsRequest) -> dict:
        """Fire-and-forget analytics endpoint."""
        truncated = {k: v for k, v in list(req.data.items())[:20]}
        log.info("analytics", event_type=req.event_type, data=truncated)
        return {"received": True}

    @app.get("/v1/identity", response_model=IdentityResponse)
    async def identity() -> IdentityResponse:
        """Return this validator's identity for peer discovery.

        Used by other validators running metagraph sync to discover
        this validator's Base (EVM) address.
        """
        from djinn_validator import __version__

        base_addr = chain_client.validator_address if chain_client else ""
        hotkey = ""
        if neuron and neuron.wallet:
            hotkey = neuron.wallet.hotkey.ss58_address
        return IdentityResponse(
            base_address=base_addr or "",
            hotkey=hotkey,
            version=__version__,
        )

    @app.get("/health-lite")
    async def health_lite() -> dict[str, Any]:
        """Lock-free health probe.

        Returns immediately without acquiring any locks, querying chain
        state, computing aggregates, or touching the share store.
        Returns just `alive=True` plus the validator's process metadata.

        Use this to distinguish "alive but busy" (the full /health
        endpoint may take seconds when the validator is mid-MPC or
        under stress) from "process dead" (curl gets connection refused
        or empty response). Operator runbooks should poll /health-lite
        for liveness checks and only fall back to /health when richer
        state is needed.

        Added 2026-05-09 (v1761) after a 100-signal stress run hung the
        full /health endpoint for ~10 minutes while the underlying
        validator process was alive but busy draining a backlog.
        """
        import os, time as _time
        return {
            "alive": True,
            "pid": os.getpid(),
            "ts": _time.time(),
        }

    @app.get("/health", response_model=HealthResponse)
    async def health() -> HealthResponse:
        """Health check endpoint.

        Includes self-advertise fields (public_hostname, peers) so the
        static web client can discover the network via gossip without
        going through any centralized proxy. See validatorHostnames.ts.
        """
        chain_ok = False
        if chain_client:
            try:
                chain_ok = await chain_client.is_connected()
            except Exception as e:
                log.warning("chain_health_check_failed", error=str(e))

        from djinn_validator import __git_commit_ts__, __version__
        from djinn_validator.core import tlsn as _tlsn_mod

        # Self-advertise: validators that have configured a public HTTPS
        # hostname report it here. The web client uses this to upgrade
        # from IP:port (HTTP, mixed-content blocked) to direct HTTPS.
        public_hostname = os.environ.get("PUBLIC_HOSTNAME", "")

        # Peer hints: which other validators this one knows about,
        # gathered from its own metagraph view. The web client uses
        # these to gossip-discover the rest of the network.
        peer_hints: list[ValidatorPeerHint] = []
        try:
            if neuron is not None:
                miner_uids = neuron.get_validator_uids() if hasattr(neuron, "get_validator_uids") else []
                for v_uid in miner_uids:
                    try:
                        axon = neuron.get_axon_info(v_uid)
                        peer_hints.append(
                            ValidatorPeerHint(
                                uid=v_uid,
                                ip=axon.get("ip", ""),
                                port=axon.get("port", 0),
                            )
                        )
                    except Exception:
                        continue
        except Exception as e:
            log.debug("peer_hints_unavailable", error=str(e))

        # Settlement registration: is our signer EOA known to OutcomeVoting?
        # If can_write=True and the answer is False, our submitVote will revert.
        # Operators need this surfaced so they notice before audits pile up.
        settlement_registered: bool | None = None
        validator_signer: str | None = None
        settlement_contract: str | None = None
        settlement_diagnosis: str | None = None
        settlement_remediation: str | None = None
        if chain_client is not None:
            ov_addr = getattr(chain_client, "_outcome_voting_address", "")
            if isinstance(ov_addr, str) and ov_addr:
                settlement_contract = ov_addr
            sa = getattr(chain_client, "validator_address", None)
            if isinstance(sa, str) and sa:
                validator_signer = sa
            if chain_client.can_write and validator_signer:
                settlement_registered = await _probe_settlement_registered_cached(chain_client, validator_signer)

                # When not registered, cross-reference canonical OV to tell the
                # operator whether the fix is .env (stale override) or timelock
                # (missing bootstrap). Same logic as startup probe, exposed via HTTP.
                if settlement_registered is False and settlement_contract:
                    from djinn_validator.config import CANONICAL_OUTCOME_VOTING_ADDRESS

                    is_canonical = settlement_contract.lower() == CANONICAL_OUTCOME_VOTING_ADDRESS.lower()
                    on_canonical: bool | None = False
                    if not is_canonical:
                        try:
                            on_canonical = await chain_client.is_registered_validator_at(
                                CANONICAL_OUTCOME_VOTING_ADDRESS
                            )
                        except Exception as e:
                            log.debug("canonical_probe_failed_health", error=str(e))
                            on_canonical = None

                    if on_canonical is None:
                        settlement_diagnosis = "rpc_flap_inconclusive"
                        settlement_remediation = (
                            "Canonical OV RPC probe failed. Cannot distinguish stale-env "
                            "override from missing-bootstrap. Retry /health or check chain "
                            "RPC connectivity."
                        )
                    elif on_canonical:
                        settlement_diagnosis = "stale_env_override"
                        settlement_remediation = (
                            f"Signer is registered on canonical OV "
                            f"({CANONICAL_OUTCOME_VOTING_ADDRESS}) but this validator "
                            f"reads from {settlement_contract}. Remove "
                            f"OUTCOME_VOTING_ADDRESS from .env and restart the validator."
                        )
                    else:
                        settlement_diagnosis = "missing_bootstrap"
                        settlement_remediation = (
                            "Signer is not registered on the canonical OutcomeVoting. "
                            "Operator must run AddValidatorSigner.s.sol (with SIGNER="
                            f"{validator_signer}) and execute after timelock delay."
                        )

        own_hotkey = ""
        if neuron is not None:
            try:
                own_hotkey = str(getattr(getattr(neuron, "wallet", None), "hotkey", None).ss58_address)
            except Exception:
                try:
                    mg_local = getattr(neuron, "metagraph", None)
                    if mg_local is not None and neuron.uid is not None:
                        own_hotkey = str(mg_local.hotkeys[neuron.uid])
                except Exception:
                    own_hotkey = ""

        # Fleet-wide settlement config echo (v1454). Reads from audit_set
        # module (single source of truth for MIN_BATCH_SIZE) and the
        # Config singleton (SHAMIR_THRESHOLD). Defensive try/except: a
        # validator that can't import these for any reason still returns
        # /health with the remaining fields populated.
        try:
            from djinn_validator.core.audit_set import MIN_BATCH_SIZE as _min_batch

            audit_min_batch_size_val: int | None = int(_min_batch)
        except Exception:
            audit_min_batch_size_val = None
        try:
            shamir_threshold_val: int | None = int(_readiness_config.shares_threshold)
        except Exception:
            shamir_threshold_val = None
        # v1562: expose DJINN_FF_BATCH_SETTLEMENT_HTTP(_SUBMIT) state on
        # /health so operators can verify P0-01 rollout fleet-wide from the
        # network dashboard instead of SSH+grep on each .env.
        try:
            from djinn_validator.feature_flags import flags as _ff

            batch_settlement_http_val: bool | None = bool(_ff.batch_settlement_http)
            batch_settlement_http_submit_val: bool | None = bool(_ff.batch_settlement_http_submit)
        except Exception:
            batch_settlement_http_val = None
            batch_settlement_http_submit_val = None

        # Git-tree diagnostics, captured once at module import.
        # See djinn_validator/__init__.py — running these subprocesses
        # inline on every /health drove tail latency past the overview
        # self-probe budget. Watchtower restarts pm2 on every pull, so
        # process lifetime == "git tree unchanged" and a static read
        # is correct here.
        from djinn_validator import (
            __git_branch__,
            __git_dirty__,
            __git_dirty_files__,
        )

        git_dirty_val = __git_dirty__
        git_dirty_files_val = __git_dirty_files__
        git_branch_val = __git_branch__

        return HealthResponse(
            status="ok",
            version=__version__,
            uid=neuron.uid if neuron else None,
            shares_held=share_store.count,
            pending_outcomes=len(outcome_attestor.get_pending_signals()),
            outcomes_resolved_total=outcome_attestor.resolved_total,
            last_outcome_resolved_ms=(
                int(outcome_attestor.last_resolve_at * 1000) if outcome_attestor.last_resolve_at is not None else None
            ),
            chain_connected=chain_ok,
            bt_connected=neuron is not None and neuron.uid is not None,
            attest_capable=_tlsn_mod.is_available(),
            public_hostname=public_hostname,
            peers=peer_hints,
            settlement_registered=settlement_registered,
            validator_signer=validator_signer,
            settlement_contract=settlement_contract,
            settlement_diagnosis=settlement_diagnosis,
            settlement_remediation=settlement_remediation,
            hotkey=own_hotkey,
            audit_min_batch_size=audit_min_batch_size_val,
            shamir_threshold=shamir_threshold_val,
            batch_settlement_http=batch_settlement_http_val,
            batch_settlement_http_submit=batch_settlement_http_submit_val,
            git_dirty=git_dirty_val,
            git_dirty_files=git_dirty_files_val,
            git_branch=git_branch_val,
            git_commit_ts=__git_commit_ts__,
            process_started_ts=_PROCESS_STARTED_TS,
            egress_ip_self_reported=_egress_self_reported_or_none(),
        )

    # Cache Config for readiness checks (avoid re-loading dotenv on every probe)
    from djinn_validator.config import Config as _ConfigCls

    _readiness_config = _ConfigCls()

    @app.get("/health/ready", response_model=ReadinessResponse)
    async def readiness() -> ReadinessResponse:
        """Deep readiness probe — checks RPC, contracts, and dependencies."""
        checks: dict[str, bool] = {}

        # Check RPC connectivity
        if chain_client:
            try:
                checks["rpc"] = await chain_client.is_connected()
            except Exception as e:
                log.warning("readiness_check_failed", check="rpc", error=str(e))
                checks["rpc"] = False
        else:
            checks["rpc"] = False

        # Check contract addresses are configured (non-zero)
        try:
            cfg = _readiness_config
            zero = "0" * 40
            checks["escrow_configured"] = bool(cfg.escrow_address) and zero not in cfg.escrow_address
            checks["signal_configured"] = (
                bool(cfg.signal_commitment_address) and zero not in cfg.signal_commitment_address
            )
            checks["account_configured"] = bool(cfg.account_address) and zero not in cfg.account_address
            checks["collateral_configured"] = bool(cfg.collateral_address) and zero not in cfg.collateral_address
        except Exception as e:
            log.warning("readiness_config_error", error=str(e))
            checks["escrow_configured"] = False
            checks["signal_configured"] = False
            checks["account_configured"] = False
            checks["collateral_configured"] = False

        # Bittensor connectivity
        checks["bt_connected"] = neuron is not None and neuron.uid is not None

        # Database accessibility
        try:
            _ = share_store.count
            checks["database"] = True
        except Exception as e:
            log.warning("readiness_check_failed", check="database", error=str(e))
            checks["database"] = False

        ready = all(checks.values())
        return ReadinessResponse(ready=ready, checks=checks)

    # ------------------------------------------------------------------
    # Signal status (lightweight share availability check)
    # ------------------------------------------------------------------

    @app.get("/v1/signal/{signal_id}/status")
    async def signal_status(signal_id: str) -> dict:
        """Check if this validator holds shares for a signal (no auth required)."""
        _validate_signal_id_path(signal_id)
        records = share_store.get_all(signal_id)
        return {"signal_id": signal_id, "has_shares": len(records) > 0}

    # ------------------------------------------------------------------
    # Public signal browse (mirrors legacy /api/idiot/browse)
    # ------------------------------------------------------------------

    _browse_cache: dict[str, Any] = {"signals": [], "last_block": 0, "updated_at": 0.0}
    _BROWSE_CACHE_TTL = 30.0
    _BROWSE_CACHE_HARD_TTL = 300.0
    _BROWSE_SEVEN_DAYS_BLOCKS = 604_800
    _browse_cache_lock = asyncio.Lock()

    async def _browse_enrich_is_active(events: list[dict[str, Any]], now: int) -> list[dict[str, Any]]:
        """Drop expired events, then isActive-filter the rest with bounded concurrency."""
        if not events or chain_client is None or chain_client._signal is None:
            return []
        active = [e for e in events if int(e.get("expires_at", 0)) >= now]
        sem = asyncio.Semaphore(15)

        async def _check(ev: dict[str, Any]) -> dict[str, Any] | None:
            async with sem:
                try:
                    ok = await chain_client.is_signal_active(int(ev["signal_id"]))
                except Exception:
                    return None
            if not ok:
                return None
            sid = int(ev["signal_id"])
            max_n = int(ev["max_notional"])
            expires_at = int(ev["expires_at"])
            return {
                "signal_id": str(sid),
                "genius": ev["genius"],
                "sport": ev["sport"],
                "fee_bps": int(ev["max_price_bps"]),
                "sla_multiplier_bps": int(ev["sla_multiplier_bps"]),
                "max_notional": str(max_n),
                "min_notional": "0",
                "expires_at_unix": expires_at,
                "max_notional_usdc": max_n / 1_000_000,
                "expires_at": datetime.fromtimestamp(expires_at, tz=UTC).isoformat().replace("+00:00", "Z"),
            }

        results = await asyncio.gather(*[_check(e) for e in active], return_exceptions=True)
        return [r for r in results if isinstance(r, dict)]

    async def _browse_refresh(now_ts: float, *, genius: str | None) -> dict[str, Any]:
        """Rescan SignalCommitted events (incremental when possible) and refresh the cache."""
        if chain_client is None or chain_client._signal is None:
            return {"signals": []}

        current_block = await chain_client.get_current_block()
        full_scan_from = max(0, current_block - _BROWSE_SEVEN_DAYS_BLOCKS)
        cached_signals = list(_browse_cache.get("signals") or [])
        cache_recent = (now_ts - _browse_cache.get("updated_at", 0.0)) < _BROWSE_CACHE_HARD_TTL and cached_signals
        from_block = int(_browse_cache["last_block"]) + 1 if cache_recent else full_scan_from
        if from_block > current_block:
            _browse_cache["updated_at"] = now_ts
            return {"signals": cached_signals}

        events = await chain_client.get_recent_signal_events(
            from_block=from_block,
            to_block=current_block,
            genius_filter=genius,
        )
        now_unix = int(now_ts)
        new_signals = await _browse_enrich_is_active(events, now_unix)

        if cache_recent:
            new_ids = {s["signal_id"] for s in new_signals}
            kept = [
                s
                for s in cached_signals
                if int(s.get("expires_at_unix", 0)) >= now_unix and s["signal_id"] not in new_ids
            ]
            merged = kept + new_signals
        else:
            merged = new_signals

        _browse_cache["signals"] = merged
        _browse_cache["last_block"] = current_block
        _browse_cache["updated_at"] = now_ts
        return {"signals": merged}

    @app.get("/v1/idiot/browse")
    async def idiot_browse(
        sport: str | None = None,
        genius: str | None = None,
        sort: str = "expires_soon",
        limit: int = 20,
        offset: int = 0,
    ) -> dict:
        """Public signal marketplace listing.

        Mirrors the legacy /api/idiot/browse Vercel route byte-for-byte on
        the response shape so static IPFS web clients can hit the
        wildcard router directly instead of a centralized proxy.

        Scans the last ~7 days of SignalCommitted events, caches for 30s
        soft / 300s hard with incremental re-scan, then filters by sport
        and/or genius, sorts by expires_soon (default) or fee, and
        paginates. No auth required; any unknown query params (including
        `bust=true` forwarded by the Vercel proxy) are ignored so an
        anonymous caller cannot force a full RPC rescan.
        """
        import time as _browse_time

        safe_limit = max(1, min(100, limit))
        safe_offset = max(0, offset)

        if genius:
            try:
                genius = Web3.to_checksum_address(genius)
            except ValueError:
                raise HTTPException(
                    status_code=400,
                    detail="genius must be a valid Ethereum address",
                )

        if chain_client is None or chain_client._signal is None:
            return {"signals": [], "total": 0, "offset": safe_offset, "limit": safe_limit}

        now_ts = _browse_time.time()
        cached_age = now_ts - _browse_cache.get("updated_at", 0.0)
        if cached_age >= _BROWSE_CACHE_TTL or not _browse_cache.get("signals"):
            async with _browse_cache_lock:
                now_ts = _browse_time.time()
                cached_age = now_ts - _browse_cache.get("updated_at", 0.0)
                if cached_age >= _BROWSE_CACHE_TTL or not _browse_cache.get("signals"):
                    await _browse_refresh(now_ts, genius=None)

        now_unix = int(_browse_time.time())
        all_signals = list(_browse_cache.get("signals") or [])
        filtered = []
        for s in all_signals:
            if int(s.get("expires_at_unix", 0)) < now_unix:
                continue
            if sport and s.get("sport") != sport:
                continue
            if genius and str(s.get("genius", "")).lower() != genius.lower():
                continue
            filtered.append(s)

        if sort == "expires_soon":
            filtered.sort(key=lambda s: s.get("expires_at", ""))
        elif sort == "fee":
            filtered.sort(key=lambda s: s.get("fee_bps", 0))

        paged = filtered[safe_offset : safe_offset + safe_limit]
        return {
            "signals": paged,
            "total": len(filtered),
            "offset": safe_offset,
            "limit": safe_limit,
        }

    # ------------------------------------------------------------------
    # Public per-genius signal listing (mirrors legacy /api/genius/signals)
    # ------------------------------------------------------------------

    _genius_signals_cache: dict[str, dict[str, Any]] = {}
    _genius_signals_cache_lock = asyncio.Lock()
    _GENIUS_SIGNALS_CACHE_TTL = 30.0
    _GENIUS_SIGNALS_CACHE_MAX = 256

    async def _genius_signals_enrich(events: list[dict[str, Any]], now: int) -> list[dict[str, Any]]:
        """Annotate each SignalCommitted event with status (active|expired|cancelled|unknown).

        Unlike _browse_enrich_is_active, this does NOT drop expired or
        cancelled signals — the Vercel genius dashboard renders them with
        a dimmed status badge. Uses the same bounded-concurrency isActive
        probe so enrichment cost stays capped regardless of per-genius
        signal count.
        """
        if not events or chain_client is None or chain_client._signal is None:
            return []
        sem = asyncio.Semaphore(15)

        async def _check(ev: dict[str, Any]) -> dict[str, Any]:
            expires_at = int(ev.get("expires_at", 0))
            if expires_at < now:
                status = "expired"
            else:
                async with sem:
                    try:
                        ok = await chain_client.is_signal_active(int(ev["signal_id"]))
                        status = "active" if ok else "cancelled"
                    except Exception:
                        status = "unknown"
            sid = int(ev["signal_id"])
            max_n = int(ev.get("max_notional", 0))
            return {
                "signal_id": str(sid),
                "genius": ev.get("genius", ""),
                "sport": ev.get("sport", ""),
                "fee_bps": int(ev.get("max_price_bps", 0)),
                "sla_multiplier_bps": int(ev.get("sla_multiplier_bps", 0)),
                "max_notional": str(max_n),
                "min_notional": "0",
                "expires_at_unix": expires_at,
                "status": status,
                "block_number": int(ev.get("block_number", 0)),
            }

        results = await asyncio.gather(*[_check(e) for e in events], return_exceptions=True)
        return [r for r in results if isinstance(r, dict)]

    @app.get("/v1/genius/{address}/signals")
    async def genius_signals(
        address: str,
        limit: int = 20,
        offset: int = 0,
        include_all: int = 0,
    ) -> dict:
        """List signals committed by a specific genius address.

        Mirrors the legacy /api/genius/signals?address=X route. Scans the
        last 7 days of SignalCommitted events filtered by genius, enriches
        each with on-chain status (active|expired|cancelled|unknown), sorts
        newest-first by block number, and paginates. Cached per-address
        for 30s.

        When include_all=0 (default), only signals with status=='active'
        are returned; when include_all=1, all signals in scan range are
        returned (so the genius dashboard can show a full history).
        """
        import time as _genius_time

        safe_limit = max(1, min(100, limit))
        safe_offset = max(0, offset)
        include_all_bool = bool(include_all)

        try:
            address_cs = Web3.to_checksum_address(address)
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail="address must be a valid Ethereum address",
            )

        if chain_client is None or chain_client._signal is None:
            return {"signals": [], "total": 0, "offset": safe_offset, "limit": safe_limit}

        # Cache key scopes by address only — include_all filtering happens on
        # the cached full list so both modes share the same RPC scan cost.
        now_ts = _genius_time.time()
        cache_entry = _genius_signals_cache.get(address_cs)
        if cache_entry is None or now_ts - cache_entry.get("updated_at", 0.0) >= _GENIUS_SIGNALS_CACHE_TTL:
            async with _genius_signals_cache_lock:
                now_ts = _genius_time.time()
                cache_entry = _genius_signals_cache.get(address_cs)
                if cache_entry is None or now_ts - cache_entry.get("updated_at", 0.0) >= _GENIUS_SIGNALS_CACHE_TTL:
                    current_block = await chain_client.get_current_block()
                    scan_from = max(0, current_block - _BROWSE_SEVEN_DAYS_BLOCKS)
                    events = await chain_client.get_recent_signal_events(
                        from_block=scan_from,
                        to_block=current_block,
                        genius_filter=address_cs,
                    )
                    now_unix = int(now_ts)
                    enriched = await _genius_signals_enrich(events, now_unix)
                    enriched.sort(key=lambda s: -int(s.get("block_number", 0)))
                    # Bound memory: drop oldest entry when cache grows past cap.
                    if len(_genius_signals_cache) >= _GENIUS_SIGNALS_CACHE_MAX:
                        oldest = min(
                            _genius_signals_cache.items(),
                            key=lambda kv: kv[1].get("updated_at", 0.0),
                        )[0]
                        _genius_signals_cache.pop(oldest, None)
                    _genius_signals_cache[address_cs] = {
                        "signals": enriched,
                        "updated_at": now_ts,
                    }
                    cache_entry = _genius_signals_cache[address_cs]

        all_signals = list(cache_entry.get("signals") or [])
        if include_all_bool:
            filtered = all_signals
        else:
            filtered = [s for s in all_signals if s.get("status") == "active"]

        paged = filtered[safe_offset : safe_offset + safe_limit]
        return {
            "signals": paged,
            "total": len(filtered),
            "offset": safe_offset,
            "limit": safe_limit,
        }

    # ------------------------------------------------------------------
    # Genius track record (mirrors legacy /api/idiot/genius/[address])
    # ------------------------------------------------------------------

    _genius_track_cache: dict[str, dict[str, Any]] = {}
    _genius_track_cache_lock = asyncio.Lock()
    _GENIUS_TRACK_CACHE_TTL = 30.0
    _GENIUS_TRACK_CACHE_MAX = 256

    @app.get("/v1/genius/{address}/track_record")
    async def genius_track_record(address: str) -> dict:
        """Return a genius's public track record derived from AuditSettled events.

        Mirrors the legacy /api/idiot/genius/[address] Vercel route (which
        queried a non-existent AuditSetSettled event and silently returned
        zeros). Scans ~7 days of real AuditSettled events filtered by the
        given genius, aggregates quality scores, derives favorable /
        unfavorable / void counts from qualityScore sign. Cached 30s per
        address with a 256-entry LRU bound.
        """
        import time as _track_time

        try:
            address_cs = Web3.to_checksum_address(address)
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail="address must be a valid Ethereum address",
            )

        empty_body = {
            "address": address_cs,
            "quality_score_avg": 0,
            "total_signals": 0,
            "settled_batches": 0,
            "win_rate": 0.0,
            "favorable": 0,
            "unfavorable": 0,
            "void": 0,
            "recent_settlements": [],
        }

        if chain_client is None or chain_client._audit is None:
            return empty_body

        now_ts = _track_time.time()
        cache_entry = _genius_track_cache.get(address_cs)
        if cache_entry is None or now_ts - cache_entry.get("updated_at", 0.0) >= _GENIUS_TRACK_CACHE_TTL:
            async with _genius_track_cache_lock:
                now_ts = _track_time.time()
                cache_entry = _genius_track_cache.get(address_cs)
                if cache_entry is None or now_ts - cache_entry.get("updated_at", 0.0) >= _GENIUS_TRACK_CACHE_TTL:
                    try:
                        current_block = await chain_client.get_current_block()
                    except Exception as e:
                        log.warning("genius_track_record_block_failed", error=str(e)[:200])
                        return empty_body
                    scan_from = max(0, current_block - _BROWSE_SEVEN_DAYS_BLOCKS)
                    try:
                        events = await chain_client.get_recent_audit_settlements(
                            from_block=scan_from,
                            to_block=current_block,
                            genius_filter=address_cs,
                        )
                    except Exception as e:
                        log.warning("genius_track_record_scan_failed", error=str(e)[:200])
                        events = []

                    settled_batches = len(events)
                    favorable = sum(1 for e in events if int(e.get("quality_score", 0)) > 0)
                    unfavorable = sum(1 for e in events if int(e.get("quality_score", 0)) < 0)
                    void = sum(1 for e in events if int(e.get("quality_score", 0)) == 0)
                    total_signals = favorable + unfavorable + void
                    win_rate = round(favorable / (favorable + unfavorable), 2) if (favorable + unfavorable) > 0 else 0.0
                    quality_sum = sum(int(e.get("quality_score", 0)) for e in events)
                    quality_avg = int(quality_sum / settled_batches) if settled_batches > 0 else 0

                    events_sorted = sorted(events, key=lambda e: int(e.get("block_number", 0)))
                    recent = [
                        {
                            "batch_id": e["batch_id"],
                            "quality_score": e["quality_score"],
                            "tranche_a": e["tranche_a"],
                            "tranche_b": e["tranche_b"],
                            "protocol_fee": e["protocol_fee"],
                            "block_number": e["block_number"],
                        }
                        for e in events_sorted[-10:]
                    ]
                    recent.reverse()

                    body = {
                        "address": address_cs,
                        "quality_score_avg": quality_avg,
                        "total_signals": total_signals,
                        "settled_batches": settled_batches,
                        "win_rate": win_rate,
                        "favorable": favorable,
                        "unfavorable": unfavorable,
                        "void": void,
                        "recent_settlements": recent,
                    }

                    # Bound memory: drop oldest when over cap.
                    if len(_genius_track_cache) >= _GENIUS_TRACK_CACHE_MAX:
                        oldest = min(
                            _genius_track_cache.items(),
                            key=lambda kv: kv[1].get("updated_at", 0.0),
                        )[0]
                        _genius_track_cache.pop(oldest, None)
                    _genius_track_cache[address_cs] = {
                        "body": body,
                        "updated_at": now_ts,
                    }
                    cache_entry = _genius_track_cache[address_cs]

        return cache_entry.get("body") or empty_body

    # ------------------------------------------------------------------
    # Genius earnings (mirrors legacy /api/genius/earnings)
    # ------------------------------------------------------------------

    _genius_earnings_cache: dict[str, dict[str, Any]] = {}
    _genius_earnings_cache_lock = asyncio.Lock()
    _GENIUS_EARNINGS_CACHE_TTL = 30.0
    _GENIUS_EARNINGS_CACHE_MAX = 256
    _EARNINGS_SCAN_BLOCKS = 200_000  # Matches Vercel's queryFilter(-200000).

    @app.get("/v1/genius/{address}/earnings")
    async def genius_earnings(address: str) -> dict:
        """Return a genius's collateral position + recent settlement summary.

        Mirrors the legacy /api/genius/earnings Vercel route. Reads
        Collateral.deposits / Collateral.locked for the given address
        (scaled to float USDC), plus recent AuditSettled events aggregated
        into a quality_score_avg. Cached 30s per address with a 256-entry
        LRU bound.
        """
        import time as _earn_time

        try:
            address_cs = Web3.to_checksum_address(address)
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail="address must be a valid Ethereum address",
            )

        empty_body = {
            "address": address_cs,
            "collateral_deposited_usdc": 0.0,
            "collateral_locked_usdc": 0.0,
            "collateral_available_usdc": 0.0,
            "settled_batches": 0,
            "quality_score_avg": 0,
            "recent_settlements": [],
        }

        if chain_client is None:
            return empty_body

        now_ts = _earn_time.time()
        cache_entry = _genius_earnings_cache.get(address_cs)
        if cache_entry is None or now_ts - cache_entry.get("updated_at", 0.0) >= _GENIUS_EARNINGS_CACHE_TTL:
            async with _genius_earnings_cache_lock:
                now_ts = _earn_time.time()
                cache_entry = _genius_earnings_cache.get(address_cs)
                if cache_entry is None or now_ts - cache_entry.get("updated_at", 0.0) >= _GENIUS_EARNINGS_CACHE_TTL:
                    try:
                        collateral = await chain_client.get_genius_collateral(address_cs)
                    except Exception as e:
                        log.warning("genius_earnings_collateral_failed", error=str(e)[:200])
                        collateral = {"deposited": 0, "locked": 0}

                    deposited_usdc = float(collateral.get("deposited", 0)) / 1_000_000.0
                    locked_usdc = float(collateral.get("locked", 0)) / 1_000_000.0

                    events: list[dict[str, Any]] = []
                    if chain_client._audit is not None:
                        try:
                            current_block = await chain_client.get_current_block()
                            scan_from = max(0, current_block - _EARNINGS_SCAN_BLOCKS)
                            events = await chain_client.get_recent_audit_settlements(
                                from_block=scan_from,
                                to_block=current_block,
                                genius_filter=address_cs,
                            )
                        except Exception as e:
                            log.warning("genius_earnings_scan_failed", error=str(e)[:200])
                            events = []

                    settled_batches = len(events)
                    quality_sum = sum(int(e.get("quality_score", 0)) for e in events)
                    quality_avg = int(quality_sum / settled_batches) if settled_batches > 0 else 0

                    events_sorted = sorted(events, key=lambda e: int(e.get("block_number", 0)))
                    recent = [
                        {
                            "batch_id": e["batch_id"],
                            "quality_score": e["quality_score"],
                            "block_number": e["block_number"],
                        }
                        for e in events_sorted[-10:]
                    ]
                    recent.reverse()

                    body = {
                        "address": address_cs,
                        "collateral_deposited_usdc": deposited_usdc,
                        "collateral_locked_usdc": locked_usdc,
                        "collateral_available_usdc": deposited_usdc - locked_usdc,
                        "settled_batches": settled_batches,
                        "quality_score_avg": quality_avg,
                        "recent_settlements": recent,
                    }

                    if len(_genius_earnings_cache) >= _GENIUS_EARNINGS_CACHE_MAX:
                        oldest = min(
                            _genius_earnings_cache.items(),
                            key=lambda kv: kv[1].get("updated_at", 0.0),
                        )[0]
                        _genius_earnings_cache.pop(oldest, None)
                    _genius_earnings_cache[address_cs] = {
                        "body": body,
                        "updated_at": now_ts,
                    }
                    cache_entry = _genius_earnings_cache[address_cs]

        return cache_entry.get("body") or empty_body

    # ------------------------------------------------------------------
    # Pair settlement status (mirrors legacy /api/settlement/{g}/{i})
    # ------------------------------------------------------------------

    _pair_settlement_cache: dict[str, dict[str, Any]] = {}
    _pair_settlement_cache_lock = asyncio.Lock()
    _PAIR_SETTLEMENT_CACHE_TTL = 30.0
    _PAIR_SETTLEMENT_CACHE_MAX = 256

    @app.get("/v1/settlement/{genius}/{idiot}")
    async def pair_settlement(genius: str, idiot: str) -> dict:
        """Return a settlement snapshot for a specific genius-idiot pair.

        Mirrors the legacy /api/settlement/[genius]/[idiot] route. Detects
        v1 (cycle-based) vs v2 (queue-based) contract and returns the
        same JSON shape both versions have emitted historically. Cached
        30s per pair with a 256-entry LRU bound.
        """
        import time as _pair_time

        try:
            genius_cs = Web3.to_checksum_address(genius)
            idiot_cs = Web3.to_checksum_address(idiot)
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail="genius and idiot must be valid Ethereum addresses",
            )

        empty_body = {
            "genius": genius_cs,
            "idiot": idiot_cs,
            "contract_version": 1,
            "current_cycle": 0,
            "signals_in_cycle": 0,
            "total_purchases": 0,
            "resolved_count": 0,
            "audited_count": 0,
            "audit_batch_count": 0,
            "ready_for_settlement": False,
        }

        if chain_client is None:
            return empty_body

        cache_key = f"{genius_cs}:{idiot_cs}"
        now_ts = _pair_time.time()
        cache_entry = _pair_settlement_cache.get(cache_key)
        if cache_entry is None or now_ts - cache_entry.get("updated_at", 0.0) >= _PAIR_SETTLEMENT_CACHE_TTL:
            async with _pair_settlement_cache_lock:
                now_ts = _pair_time.time()
                cache_entry = _pair_settlement_cache.get(cache_key)
                if cache_entry is None or now_ts - cache_entry.get("updated_at", 0.0) >= _PAIR_SETTLEMENT_CACHE_TTL:
                    try:
                        status = await chain_client.get_pair_settlement_status(
                            genius_cs,
                            idiot_cs,
                        )
                    except Exception as e:
                        log.warning("pair_settlement_read_failed", error=str(e)[:200])
                        status = {
                            "contract_version": 1,
                            "current_cycle": 0,
                            "signals_in_cycle": 0,
                            "total_purchases": 0,
                            "resolved_count": 0,
                            "audited_count": 0,
                            "audit_batch_count": 0,
                            "ready_for_settlement": False,
                        }

                    body = {
                        "genius": genius_cs,
                        "idiot": idiot_cs,
                        **status,
                    }

                    if len(_pair_settlement_cache) >= _PAIR_SETTLEMENT_CACHE_MAX:
                        oldest = min(
                            _pair_settlement_cache.items(),
                            key=lambda kv: kv[1].get("updated_at", 0.0),
                        )[0]
                        _pair_settlement_cache.pop(oldest, None)
                    _pair_settlement_cache[cache_key] = {
                        "body": body,
                        "updated_at": now_ts,
                    }
                    cache_entry = _pair_settlement_cache[cache_key]

        return cache_entry.get("body") or empty_body

    # ------------------------------------------------------------------
    # Public network config (mirrors legacy /api/network/config)
    # ------------------------------------------------------------------

    @app.get("/v1/network/config")
    async def network_config() -> dict:
        """Return the public network config blob the SDK + static clients need.

        Mirrors the legacy /api/network/config Vercel route. Includes chain_id,
        canonical contract proxy addresses, Shamir threshold params, and the
        list of validators discoverable from the metagraph. Validators are
        filtered to those with a non-zero axon (ip:port > 0) — same semantics
        as the legacy route's "online" filter, but skips the per-call probe
        fan-out since clients can hit each endpoint directly if they need
        liveness.

        Pubkey is null for every entry. The legacy route expected a `pubkey`
        field from /v1/identity, but /v1/identity has never published one —
        so the web proxy always returned null too. Preserved verbatim here
        for static-export parity; if per-validator encryption pubkeys get
        wired in a future protocol upgrade, add them to IdentityResponse
        and resolve them here.
        """
        cfg = _readiness_config

        validators_out: list[dict] = []
        if neuron is not None and neuron.metagraph is not None:
            try:
                validator_uids = neuron.get_validator_uids() if hasattr(neuron, "get_validator_uids") else []
                for v_uid in validator_uids:
                    try:
                        axon = neuron.metagraph.axons[v_uid]
                    except Exception:
                        continue
                    ip = getattr(axon, "ip", "") or ""
                    port = int(getattr(axon, "port", 0) or 0)
                    if not ip or port <= 0:
                        continue
                    validators_out.append(
                        {
                            "uid": int(v_uid),
                            "name": f"UID {int(v_uid)}",
                            "endpoint": f"http://{ip}:{port}",
                            "pubkey": None,
                        }
                    )
            except Exception as e:
                log.warning("network_config_validators_failed", error=str(e)[:200])

        return {
            "validators": validators_out,
            "chain_id": cfg.base_chain_id,
            "contracts": {
                "signal_commitment": cfg.signal_commitment_address,
                "escrow": cfg.escrow_address,
                "collateral": cfg.collateral_address,
                "account": cfg.account_address,
                "audit": cfg.audit_address,
                "credit_ledger": cfg.credit_ledger_address,
                "key_recovery": cfg.key_recovery_address,
                "usdc": cfg.usdc_address,
            },
            "shamir": {
                "n": cfg.shares_total,
                "k": cfg.shares_threshold,
            },
            "cached_at": datetime.now(UTC).isoformat(),
        }

    # ------------------------------------------------------------------
    # Public per-idiot balance (mirrors legacy /api/idiot/balance)
    # ------------------------------------------------------------------

    @app.get("/v1/idiot/{address}/balance")
    async def idiot_balance(address: str) -> dict:
        """Return escrow deposit, USDC wallet balance, and credit-ledger
        balance for a given idiot address.

        Mirrors the legacy /api/idiot/balance?address=X route. All data is
        public on-chain and unauthenticated. Returns USDC-scaled floats
        (divided by 1e6) to match the Vercel output shape exactly so
        static IPFS clients can swap the endpoint transparently.

        Degrades to zero for any unreadable contract rather than failing —
        a missing USDC address on an older validator deployment returns
        wallet_usdc=0, not a 500.
        """
        try:
            address_cs = Web3.to_checksum_address(address)
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail="address must be a valid Ethereum address",
            )

        if chain_client is None:
            return {
                "address": address_cs,
                "escrow_balance_usdc": 0,
                "wallet_usdc": 0,
                "credits": 0,
            }

        raw = await chain_client.get_idiot_balances(address_cs)
        return {
            "address": address_cs,
            "escrow_balance_usdc": raw["escrow"] / 1e6,
            "wallet_usdc": raw["wallet_usdc"] / 1e6,
            "credits": raw["credits"] / 1e6,
        }

    # ------------------------------------------------------------------
    # Idiot purchase history (mirrors legacy /api/idiot/purchases)
    # ------------------------------------------------------------------

    _idiot_purchases_cache: dict[str, dict[str, Any]] = {}
    _idiot_purchases_cache_lock = asyncio.Lock()
    _IDIOT_PURCHASES_CACHE_TTL = 30.0
    _IDIOT_PURCHASES_CACHE_MAX = 256
    _OUTCOME_LABELS = {0: "pending", 1: "favorable", 2: "unfavorable", 3: "void"}

    def _outcome_to_status(outcome: int) -> str:
        if outcome == 0:
            return "pending"
        if outcome == 3:
            return "void"
        return "settled"

    @app.get("/v1/idiot/{address}/purchases")
    async def idiot_purchases(
        address: str,
        status: str | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> dict:
        """Return a paginated purchase history for a given idiot address.

        Mirrors the legacy /api/idiot/purchases Vercel route. Scans
        Escrow.SignalPurchased events filtered by buyer, enriches each
        with the current outcome from Escrow.getPurchase, applies the
        status filter (pending / settled / void), sorts newest-first,
        paginates. Cached 30s per (address, status, limit, offset).

        Auth note: the Vercel route gated this behind session auth for
        UX reasons, but the underlying on-chain data is public. The
        validator exposes it unauthenticated so static IPFS clients
        can render a user's own history after a wallet-signed session.
        """
        import time as _purch_time

        try:
            address_cs = Web3.to_checksum_address(address)
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail="address must be a valid Ethereum address",
            )

        if status is not None and status not in ("pending", "settled", "void"):
            raise HTTPException(
                status_code=400,
                detail="status must be one of: pending, settled, void",
            )

        limit = max(1, min(int(limit), 100))
        offset = max(0, int(offset))

        empty_body = {
            "purchases": [],
            "total": 0,
            "offset": offset,
            "limit": limit,
        }

        if chain_client is None or chain_client._escrow is None:
            return empty_body

        cache_key = f"{address_cs}:{status or ''}:{limit}:{offset}"
        now_ts = _purch_time.time()
        cache_entry = _idiot_purchases_cache.get(cache_key)
        if cache_entry is None or now_ts - cache_entry.get("updated_at", 0.0) >= _IDIOT_PURCHASES_CACHE_TTL:
            async with _idiot_purchases_cache_lock:
                now_ts = _purch_time.time()
                cache_entry = _idiot_purchases_cache.get(cache_key)
                if cache_entry is None or now_ts - cache_entry.get("updated_at", 0.0) >= _IDIOT_PURCHASES_CACHE_TTL:
                    try:
                        current_block = await chain_client.get_current_block()
                        scan_from = max(0, current_block - _BROWSE_SEVEN_DAYS_BLOCKS)
                        events = await chain_client.get_recent_signal_purchases(
                            from_block=scan_from,
                            to_block=current_block,
                            buyer_filter=address_cs,
                        )
                    except Exception as e:
                        log.warning("idiot_purchases_scan_failed", error=str(e)[:200])
                        events = []

                    records: list[dict[str, Any]] = []
                    for ev in events:
                        pid = int(ev["purchase_id"])
                        outcome = 0
                        purchased_at_unix = 0
                        try:
                            pdata = await chain_client.get_purchase(pid)
                            if pdata:
                                outcome = int(pdata[7]) if len(pdata) > 7 else 0
                                purchased_at_unix = int(pdata[8]) if len(pdata) > 8 else 0
                        except Exception:
                            pass
                        if purchased_at_unix == 0:
                            purchased_at_unix = await chain_client.get_block_timestamp(int(ev["block_number"]))

                        rec_status = _outcome_to_status(outcome)
                        if status is not None and rec_status != status:
                            continue

                        records.append(
                            {
                                "purchase_id": pid,
                                "signal_id": str(ev["signal_id"]),
                                "notional_usdc": float(ev["notional"]) / 1_000_000.0,
                                "fee_usdc": float(ev["fee_paid"]) / 1_000_000.0,
                                "credit_used_usdc": float(ev["credit_used"]) / 1_000_000.0,
                                "usdc_paid": float(ev["usdc_paid"]) / 1_000_000.0,
                                "outcome": _OUTCOME_LABELS.get(outcome, "unknown"),
                                "status": rec_status,
                                "purchased_at": (
                                    datetime.fromtimestamp(purchased_at_unix, tz=UTC).isoformat().replace("+00:00", "Z")
                                    if purchased_at_unix
                                    else ""
                                ),
                                "block_number": int(ev["block_number"]),
                            }
                        )

                    records.sort(key=lambda r: r["block_number"], reverse=True)
                    total = len(records)
                    paged = [
                        {k: v for k, v in r.items() if k != "block_number"} for r in records[offset : offset + limit]
                    ]

                    body = {
                        "purchases": paged,
                        "total": total,
                        "offset": offset,
                        "limit": limit,
                    }

                    if len(_idiot_purchases_cache) >= _IDIOT_PURCHASES_CACHE_MAX:
                        oldest = min(
                            _idiot_purchases_cache.items(),
                            key=lambda kv: kv[1].get("updated_at", 0.0),
                        )[0]
                        _idiot_purchases_cache.pop(oldest, None)
                    _idiot_purchases_cache[cache_key] = {
                        "body": body,
                        "updated_at": now_ts,
                    }
                    cache_entry = _idiot_purchases_cache[cache_key]

        return cache_entry.get("body") or empty_body

    # ------------------------------------------------------------------
    # Activity log
    # ------------------------------------------------------------------

    @app.get("/v1/activity", dependencies=[_admin_auth])
    async def get_activity(
        limit: int = 100,
        category: str | None = None,
    ) -> dict:
        """Return recent validator activity events for admin dashboard."""
        if activity_buffer is None:
            return {"events": [], "total": 0}
        safe_limit = max(1, min(500, limit))
        events = activity_buffer.recent(limit=safe_limit, category=category)
        return {"events": events, "total": len(events)}

    @app.get("/v1/telemetry", dependencies=[_admin_auth])
    async def get_telemetry(
        limit: int = 200,
        since: float | None = None,
        category: str | None = None,
        offset: int = 0,
    ) -> dict:
        """Query persistent telemetry events. Full history, newest first."""
        if telemetry is None:
            return {"events": [], "total": 0}
        events = telemetry.query(limit=limit, since=since, category=category, offset=offset)
        total = telemetry.count(category=category)
        return {"events": events, "total": total}

    # ------------------------------------------------------------------
    # Miner score lookup
    # ------------------------------------------------------------------

    @app.get("/v1/miner/{uid}/scores")
    async def miner_scores(uid: int) -> dict:
        """Return current live scoring metrics for a specific miner UID.

        Public endpoint (no auth). Miners and operators need visibility
        into how validators are scoring them.
        """
        if scorer is None:
            return {"uid": uid, "found": False}
        m = scorer.get(uid)
        if m is None:
            return {"uid": uid, "found": False}

        # Compute the weight breakdown so miners can see exactly why
        # they're getting the weight they're getting.
        weights, breakdowns = scorer.compute_weights_detailed(is_active_epoch=True)
        breakdown = breakdowns.get(uid, {})
        weight = weights.get(uid, 0.0)

        return {
            "uid": uid,
            "found": True,
            "hotkey": m.hotkey,
            # Raw metrics
            "accuracy": round(m.accuracy_score(), 4),
            "coverage": round(m.coverage_score(), 4),
            "uptime": round(m.uptime_score(), 4),
            "attest_validity": round(m.attestation_validity_score(), 4),
            "queries_total": m.queries_total,
            "queries_correct": m.queries_correct,
            "proofs_submitted": m.proofs_submitted,
            "proofs_verified": m.proofs_verified,
            "proofs_requested": m.proofs_requested,
            "attestations_total": m.attestations_total,
            "attestations_valid": m.attestations_valid,
            "health_checks_total": m.health_checks_total,
            "health_checks_responded": m.health_checks_responded,
            "consecutive_epochs": m.consecutive_epochs,
            "notary_duties_assigned": m.notary_duties_assigned,
            "notary_duties_completed": m.notary_duties_completed,
            "notary_reliability": round(m.notary_reliability(), 4),
            "proactive_proof_verified": m.proactive_proof_verified,
            # Lifetime counters (never reset, for dashboard display)
            "lifetime_queries": m.lifetime_queries,
            "lifetime_correct": m.lifetime_correct,
            "lifetime_attestations": m.lifetime_attestations,
            "lifetime_attestations_valid": m.lifetime_attestations_valid,
            "lifetime_attestation_proof_bytes": m.lifetime_attestation_proof_bytes,
            "lifetime_attestation_duration_ms": m.lifetime_attestation_duration_ms,
            "lifetime_attestation_proof_sessions": m.lifetime_attestation_proof_sessions,
            "lifetime_notary_duties_assigned": m.lifetime_notary_duties_assigned,
            "lifetime_notary_duties_completed": m.lifetime_notary_duties_completed,
            "lifetime_notary_proof_bytes": m.lifetime_notary_proof_bytes,
            "lifetime_notary_duration_ms": m.lifetime_notary_duration_ms,
            "lifetime_notary_proof_sessions": m.lifetime_notary_proof_sessions,
            # Weight breakdown: how the final weight is computed
            "weight": round(weight, 8),
            "weight_breakdown": {k: round(v, 6) if isinstance(v, float) else v for k, v in breakdown.items()}
            if breakdown
            else None,
        }

    @app.get("/v1/miner/{uid}/history")
    async def miner_history(uid: int, hours: int = 168) -> dict:
        """Return historical weight/score data for a specific miner.

        Public endpoint. Extracts per-miner data from weight_set telemetry
        events so the dashboard can show score timeseries without admin auth.

        Args:
            uid: Miner UID to look up.
            hours: How far back to look (default 7 days).
        """
        if telemetry is None:
            return {"uid": uid, "history": []}

        import time as _time

        since = _time.time() - max(1, min(hours, 720)) * 3600
        history = telemetry.miner_history(uid, since)

        return {"uid": uid, "history": history}

    @app.get("/v1/network/miners")
    async def network_miners() -> dict:
        """Return health and scoring data for all miners this validator tracks.

        Public endpoint. The web dashboard uses this instead of probing
        miners directly (which fails when miners whitelist validator IPs).
        This validator already health-checks every miner each epoch, so
        the data is fresh and authoritative.
        """
        if scorer is None:
            return {"miners": [], "validator_uid": getattr(neuron, "uid", None)}

        weights, breakdowns = scorer.compute_weights_detailed(is_active_epoch=True)
        # Pre-compute coldkey cluster sizes so each miner entry can report
        # how many UIDs share its coldkey. Used by dashboards to surface
        # sybil topology and by the (future) DJINN_FF_COLDKEY_DENSITY_WEIGHT
        # gate. Empty coldkey counts as its own bucket (unknown cluster).
        coldkey_sizes: dict[str, int] = {}
        for mm in scorer._miners.values():
            if mm.coldkey:
                coldkey_sizes[mm.coldkey] = coldkey_sizes.get(mm.coldkey, 0) + 1
        miners_out = []
        for uid, m in sorted(scorer._miners.items()):
            b = breakdowns.get(uid, {})
            miner_entry = {
                "uid": uid,
                "hotkey": m.hotkey,
                "coldkey": m.coldkey,
                "coldkey_size": coldkey_sizes.get(m.coldkey, 1) if m.coldkey else 1,
                "status": "ok" if m.ema_uptime > 0.001 and m.uptime_score() > 0.5 else "offline",
                "version": m.reported_version,
                "uptime": round(m.uptime_score(), 4),
                "health_checks_total": m.health_checks_total,
                "health_checks_responded": m.health_checks_responded,
                "queries_total": m.queries_total,
                "queries_correct": m.queries_correct,
                "accuracy": round(m.accuracy_score(), 4),
                "attestations_total": m.attestations_total,
                "attestations_valid": m.attestations_valid,
                "proactive_proof_verified": m.proactive_proof_verified,
                "notary_duties_assigned": m.notary_duties_assigned,
                "notary_duties_completed": m.notary_duties_completed,
                "notary_reliability": round(m.notary_reliability(), 4),
                "weight": round(weights.get(uid, 0.0), 8),
                "lifetime_queries": m.lifetime_queries,
                "lifetime_correct": m.lifetime_correct,
                "lifetime_attestations": m.lifetime_attestations,
                "lifetime_attestations_valid": m.lifetime_attestations_valid,
                "lifetime_attestation_proof_bytes": m.lifetime_attestation_proof_bytes,
                "lifetime_attestation_duration_ms": m.lifetime_attestation_duration_ms,
                "lifetime_attestation_proof_sessions": m.lifetime_attestation_proof_sessions,
                "lifetime_notary_duties_assigned": m.lifetime_notary_duties_assigned,
                "lifetime_notary_duties_completed": m.lifetime_notary_duties_completed,
                "lifetime_notary_proof_bytes": m.lifetime_notary_proof_bytes,
                "lifetime_notary_duration_ms": m.lifetime_notary_duration_ms,
                "lifetime_notary_proof_sessions": m.lifetime_notary_proof_sessions,
                "capabilities_reported": m.capabilities_reported,
                "memory_total_mb": m.memory_total_mb,
                "cpu_cores": m.cpu_cores,
                "shield_installed": m.shield_installed,
                # Score component transparency (added with v1159 scoring changes).
                # Exposed so operators can diagnose WHY a miner is over/underweighted:
                # volume_factor < 1.0 means bootstrap-ramp, canonical_agreement < 1.0
                # means odds diverge from consensus, etc.
                "attest_validity": round(b.get("attest_validity", 0.0), 4),
                "sports_score": round(b.get("sports_score", 0.0), 4),
                "attestation_score": round(b.get("attestation_score", 0.0), 4),
                "canonical_agreement": round(b.get("canonical_agreement", 0.0), 4),
                "canonical_samples": b.get("canonical_samples", 0),
                "volume_factor": round(b.get("volume_factor", 0.0), 4),
                "total_samples": b.get("total_samples", 0),
            }
            miners_out.append(miner_entry)

        return {
            "miners": miners_out,
            "validator_uid": getattr(neuron, "uid", None) if neuron else None,
            "miner_count": len(miners_out),
        }

    # ------------------------------------------------------------------
    # Purchase odds vector retrieval (durability for option C settlement)
    # ------------------------------------------------------------------

    @app.get("/v1/purchase_odds/{signal_id}/{buyer_address}")
    async def get_purchase_odds(
        signal_id: str,
        buyer_address: str,
        request: Request,
    ) -> dict:
        """Return the BPA/WPA vectors and Merkle roots for a given
        (signal, buyer) pair, if this validator has them.

        AUTHENTICATION REQUIRED. The vectors are PRIVATE — exposing
        them publicly would defeat the option C privacy guarantee
        (an attacker could enumerate which lines were executable for
        each buyer, partially deanonymizing the bet).

        Only registered SN103 validators may call this endpoint.
        The caller must sign the request with their hotkey via the
        standard X-Hotkey/X-Signature/X-Timestamp/X-Nonce headers.
        The audit MPC, which is run BY validators, uses its own
        hotkey to authenticate when reconstructing vectors at
        settlement time.

        Used by the audit MPC at settlement time to recover the
        off-chain BPA/WPA vectors that back the on-chain Merkle root
        committed by purchaseV2(). Any validator that holds the
        vectors can serve them; the audit only needs threshold-of-N
        copies that match the on-chain root.

        Returns 404 if this validator doesn't have a record for the
        pair. Returns the vectors plus per-vector Merkle roots so the
        caller can independently verify against the on-chain commitment.
        """
        # AUTH: only registered validators may read these vectors. The
        # allowed-hotkeys set is the current SN103 validator hotkey
        # list (anyone with validator_permit). If the metagraph is
        # unavailable, fall through to the more permissive default
        # (any signed request) — the signature still has to be valid.
        allowed_hotkeys: set[str] | None = None
        if neuron is not None and neuron.metagraph is not None:
            try:
                validator_uids = neuron.get_validator_uids() if hasattr(neuron, "get_validator_uids") else []
                allowed_hotkeys = {neuron.metagraph.hotkeys[v_uid] for v_uid in validator_uids}
            except Exception as e:
                log.warning("purchase_odds_allowlist_failed", error=str(e)[:100])
        try:
            verified_hotkey = await validate_signed_request(request, allowed_hotkeys)
        except HTTPException:
            log.warning(
                "purchase_odds_unauthenticated_attempt",
                signal_id=signal_id,
                buyer=buyer_address[:10],
                src_ip=request.client.host if request.client else "unknown",
            )
            raise

        _validate_signal_id_path(signal_id)
        if not buyer_address.startswith("0x") or len(buyer_address) != 42:
            raise HTTPException(status_code=400, detail="Invalid buyer_address format")

        if purchase_odds_ledger is None:
            raise HTTPException(status_code=503, detail="Purchase odds ledger not configured")

        record = purchase_odds_ledger.get(signal_id=signal_id, buyer_address=buyer_address)
        if record is None:
            raise HTTPException(status_code=404, detail="No record for (signal_id, buyer)")

        # Compute Merkle roots from the stored vectors using the
        # canonical leaf format: keccak256(abi.encode(uint256 lineIndex, uint256 priceX1e6))
        # Single binary tree, sorted-pair hashing — same shape the
        # contract's purchaseV2 uses.
        from djinn_validator.utils.merkle import compute_vector_root

        bpa_root = compute_vector_root(record.bpas)
        wpa_root = compute_vector_root(record.wpas)

        log.info(
            "purchase_odds_served",
            signal_id=signal_id,
            buyer=buyer_address[:10],
            requester_hotkey=(verified_hotkey or "")[:10],
            n_lines=len(record.bpas),
        )

        return {
            "signal_id": record.signal_id,
            "buyer_address": record.buyer_address,
            "bpa_mode": record.bpa_mode,
            "bpas": record.bpas,
            "wpas": record.wpas,
            "bpa_root": "0x" + bpa_root.hex(),
            "wpa_root": "0x" + wpa_root.hex(),
            "recorded_at_ms": int(record.recorded_at * 1000),
            "served_by_uid": getattr(neuron, "uid", None) if neuron else None,
        }

    @app.post("/v1/purchase_odds/record", response_model=PurchaseOddsGossipResponse)
    async def record_purchase_odds_gossip(
        req: PurchaseOddsGossipRequest,
        request: Request,
    ) -> PurchaseOddsGossipResponse:
        """Accept a peer validator's BPA/WPA gossip.

        The validator that served POST /v1/signal/{id}/purchase gossips
        the recorded vectors to every committee peer so batch settlement
        (which can run on any validator) has the data locally. Without
        this, only the purchase-handling validator can assemble
        PurchaseInputs at audit time, and shadow settlement silently
        produces an empty batch on all other peers. See P0-01 in
        MAINNET_BLOCKERS.md for the incident that surfaced this gap.
        """
        await validate_signed_request(request, _get_validator_hotkeys())

        # v1707: receive-side gossip counter for purchase_odds.
        from djinn_validator.api.metrics import (
            GOSSIP_RECEIVE_RESULT,
            safe_label_inc,
        )

        def _recv_tick(outcome: str) -> None:
            safe_label_inc(GOSSIP_RECEIVE_RESULT, path="purchase_odds", outcome=outcome)

        if purchase_odds_ledger is None:
            _recv_tick("no_ledger")
            raise HTTPException(status_code=503, detail="Purchase odds ledger not configured")

        existing = purchase_odds_ledger.get(signal_id=req.signal_id, buyer_address=req.buyer_address)
        was_duplicate = existing is not None

        if not was_duplicate:
            try:
                purchase_odds_ledger.record(
                    signal_id=req.signal_id,
                    buyer_address=req.buyer_address,
                    bpas=req.bpas,
                    wpas=req.wpas,
                    bpa_mode=req.bpa_mode,
                )
            except ValueError as e:
                _recv_tick("bad_request")
                raise HTTPException(status_code=400, detail=f"Invalid record: {e}")
            _recv_tick("stored")

            # v1717: new BPA/WPA arrival may unblock a previously-abstained
            # audit_set. Reset its abstain counter so the next get_ready_sets
            # call surfaces it again. Without this, an audit_set that hit
            # threshold in the early gossip window stays evicted forever
            # even after the missing data finally arrives.
            if audit_set_store is not None:
                pair = audit_set_store.get_pair_for_signal(req.signal_id)
                if pair is not None:
                    g, i, cyc = pair
                    audit_set_store.reset_abstain(g, i, cyc)
        else:
            _recv_tick("duplicate")

        log.info(
            "purchase_odds_gossip_received",
            signal_id=req.signal_id,
            buyer=req.buyer_address[:10],
            n_lines=len(req.bpas),
            bpa_mode=req.bpa_mode,
            duplicate=was_duplicate,
        )

        return PurchaseOddsGossipResponse(recorded=True, duplicate=was_duplicate)

    @app.get("/v1/outcomes/{signal_id}")
    async def get_outcome_for_signal(signal_id: str) -> dict:
        """Pull-side recovery for outcome gossip.

        Mirror of the share-recovery endpoint but for outcomes. A peer
        validator that missed the original gossip push (HTTP down,
        429-rate-limited, restarted, etc.) calls this to fetch our
        local view of a signal's metadata + resolved outcomes.

        The receiver is expected to replay-verify the outcomes via its own
        ESPN fetch (same trust model as the gossip path); this endpoint's
        response is a HINT, not authority. Therefore no auth: outcomes
        are non-secret, and the security boundary is the receiver's
        independent ESPN replay.

        See project_outcome_recovery_design_2026_05_03.md.
        """
        _validate_signal_id_path(signal_id)
        if outcome_attestor is None:
            raise HTTPException(status_code=503, detail="Outcome attestor not configured")
        meta = outcome_attestor.get_signal(signal_id)
        if meta is None:
            raise HTTPException(status_code=404, detail="signal not registered locally")

        # Serialize each ParsedPick back to the JSON form parse_pick accepts
        # on the receiving side. Receiver feeds these strings to parse_pick().
        line_strs: list[str] = []
        for pick in meta.lines:
            try:
                obj = {
                    "market": pick.market,
                    "team": pick.team or "",
                    "side": pick.side or "",
                    "line": pick.line,
                    "odds": pick.odds,
                }
                line_strs.append(json.dumps(obj, separators=(",", ":")))
            except Exception:
                continue

        return {
            "signal_id": meta.signal_id,
            "sport": meta.sport,
            "event_id": meta.event_id,
            "home_team": meta.home_team,
            "away_team": meta.away_team,
            "lines": line_strs,
            "resolved": meta.resolved,
            "outcomes": [int(o) for o in (meta.outcomes or [])] if meta.resolved else None,
        }

    @app.post("/v1/audit/gossip", response_model=AuditGossipResponse)
    async def receive_audit_gossip(
        req: AuditGossipRequest,
        request: Request,
    ) -> AuditGossipResponse:
        """v1710: accept a peer validator's audit-set entry announcement.

        Receivers MUST verify the (genius, idiot, signal_id, purchase_id)
        tuple against on-chain Escrow.purchases(pid) before adding. A
        malicious or stale peer can claim any tuple; chain verification
        means we only ever add tuples chain itself confirms.

        Idempotent: if the tuple is already in audit_set_store, return
        accepted=True duplicate=True without re-calling chain.
        """
        await validate_signed_request(request, _get_validator_hotkeys())

        def _recv_tick(outcome: str) -> None:
            try:
                from djinn_validator.api.metrics import AUDIT_GOSSIP_RECEIVE_RESULT

                AUDIT_GOSSIP_RECEIVE_RESULT.labels(outcome=outcome).inc()
            except Exception:
                pass

        if audit_set_store is None:
            _recv_tick("no_audit_set")
            raise HTTPException(status_code=503, detail="audit_set_store not configured")

        # Quick duplicate check before the chain RPC. add_signal is
        # idempotent but the chain call is expensive — skip when we
        # already have the tuple. get_pair_for_signal returns
        # (genius, idiot, cycle); we only compare g + i since cycle
        # is opaque under v2 (always 0).
        existing_pair = audit_set_store.get_pair_for_signal(req.signal_id)
        if existing_pair is not None:
            existing_g, existing_i, _cycle = existing_pair
            if existing_g.lower() == req.genius.lower() and existing_i.lower() == req.idiot.lower():
                _recv_tick("duplicate")
                return AuditGossipResponse(accepted=True, duplicate=True, reason="duplicate")

        if chain_client is None:
            _recv_tick("chain_unreachable")
            raise HTTPException(status_code=503, detail="chain_client not configured; cannot verify")

        try:
            on_chain = await chain_client.get_purchase(int(req.purchase_id))
        except Exception as e:
            log.warning("audit_gossip_chain_lookup_failed", err=str(e)[:120], pid=req.purchase_id)
            _recv_tick("chain_unreachable")
            return AuditGossipResponse(accepted=False, duplicate=False, reason="chain_unreachable")

        if on_chain is None:
            _recv_tick("chain_mismatch")
            return AuditGossipResponse(accepted=False, duplicate=False, reason="purchase_not_on_chain")

        # Verify the gossip-claimed (signal_id, idiot) match what chain
        # reports for this purchase_id. genius is verified via
        # SignalCommitment which we don't double-call here — its mismatch
        # would have surfaced at signal creation time on the originating
        # validator. The idiot + signal_id together are sufficient
        # sender-binding for audit_set_store.
        chain_signal_id = str(on_chain.get("signalId", ""))
        chain_idiot = str(on_chain.get("idiot") or on_chain.get("buyer") or "").lower()
        if chain_signal_id != req.signal_id:
            _recv_tick("chain_mismatch")
            log.warning(
                "audit_gossip_signal_mismatch",
                claimed=req.signal_id[:20],
                chain=chain_signal_id[:20],
                pid=req.purchase_id,
            )
            return AuditGossipResponse(accepted=False, duplicate=False, reason="chain_mismatch")
        if chain_idiot and chain_idiot != req.idiot.lower():
            _recv_tick("chain_mismatch")
            log.warning(
                "audit_gossip_idiot_mismatch",
                claimed=req.idiot[:10],
                chain=chain_idiot[:10],
                pid=req.purchase_id,
            )
            return AuditGossipResponse(accepted=False, duplicate=False, reason="chain_mismatch")

        # Chain confirmed. Add to audit_set_store with placeholder
        # notional/odds; settlement-time MPC reconstructs from on-chain
        # BPA/WPA vectors anyway, and a refreshed bootstrap fills the
        # canonical numbers. The important thing is the pair tuple is
        # in audit_set_store so shadow_settle picks it up.
        try:
            audit_set_store.add_signal(
                genius=req.genius,
                idiot=req.idiot,
                cycle=0,
                signal_id=req.signal_id,
                purchase_id=int(req.purchase_id),
            )
            _recv_tick("added")
            return AuditGossipResponse(accepted=True, duplicate=False, reason="added")
        except Exception as e:
            log.warning("audit_gossip_add_signal_failed", err=str(e)[:120])
            _recv_tick("bad_request")
            return AuditGossipResponse(accepted=False, duplicate=False, reason="add_failed")

    @app.post("/v1/outcomes/gossip", response_model=OutcomeGossipResponse)
    async def receive_outcome_gossip(
        req: OutcomeGossipRequest,
        request: Request,
    ) -> OutcomeGossipResponse:
        """Accept a peer validator's resolved-outcome gossip.

        Phase A2 of the outcome layer (see docs/outcome-layer-plan.md).

        The flow:
        1. Auth: signature must be from a registered SN103 validator hotkey.
        2. Cross-check: source_uid in payload matches the signing hotkey
           against the metagraph (prevents one validator from spoofing
           another's UID in our local gossip-source telemetry).
        3. Replay-verify: OutcomeAttestor.receive_gossip independently
           fetches ESPN and compares derived outcomes against the gossip.
        4. On accept: outcomes recorded locally, audit_set_store wired,
           main loop's settlement path now sees the signal as resolved
           without waiting for our own ESPN poll.
        5. On dispute: log only, do NOT store. Phase B will dispatch
           an ESPN URL to miners for TLSN attestation when disputes
           persist.
        """
        signer_hotkey = await validate_signed_request(request, _get_validator_hotkeys())

        # v1707: receive-side gossip counter for outcomes.
        from djinn_validator.api.metrics import (
            GOSSIP_RECEIVE_RESULT,
            safe_label_inc,
        )

        def _recv_tick(outcome: str) -> None:
            safe_label_inc(GOSSIP_RECEIVE_RESULT, path="outcomes", outcome=outcome)

        # Cross-check source_uid against the signing hotkey. If a peer
        # is honest about who they are, signer_hotkey must match the
        # claimed source_uid's metagraph entry. If not, log + accept
        # the request anyway (the signature is the security boundary;
        # source_uid is a telemetry field).
        if neuron is not None and neuron.metagraph is not None and signer_hotkey:
            try:
                claimed_hotkey = neuron.metagraph.hotkeys[req.source_uid]
                if claimed_hotkey != signer_hotkey:
                    log.warning(
                        "outcome_gossip_uid_hotkey_mismatch",
                        claimed_uid=req.source_uid,
                        signer=signer_hotkey[:10],
                        actual_hotkey=claimed_hotkey[:10] if claimed_hotkey else "",
                    )
            except (IndexError, AttributeError):
                pass

        if outcome_attestor is None:
            _recv_tick("no_ledger")
            raise HTTPException(status_code=503, detail="Outcome attestor not configured")

        status, accepted_outcomes = await outcome_attestor.receive_gossip(
            signal_id=req.signal_id,
            gossiped_outcomes=req.outcomes,
            signer_hotkey=signer_hotkey or "",
            gossiped_game_date=req.game_date,
        )

        # Wire accepted/already_resolved gossip into audit_set_store so
        # settlement path sees it. The already_resolved path is the
        # bridge that closes the post-restart gap: pending_signals reloads
        # resolved=True from SQLite, but audit_set_store is in-memory and
        # starts empty, so audit_set entries show outcomes_resolved=False
        # even when this validator has the outcome. Recording on every
        # already_resolved gossip pulls the SQLite-resolved state into
        # audit_set_store within ~5 min of any peer reconciliation cycle,
        # without waiting for chain bootstrap backfill (~30 min). Idempotent
        # if already recorded. accepted: outcome is genuinely new.
        # already_resolved: outcome already in pending_signals; we may or
        # may not have already wired audit_set_store — call is safe either
        # way.
        if status in ("accepted", "already_resolved") and accepted_outcomes is not None and audit_set_store is not None:
            from djinn_validator.core.outcomes import Outcome as _Outcome

            try:
                outcomes_enum = [_Outcome(int(x)) for x in accepted_outcomes]
                # Phase A1.8: if signal not in local audit_set yet AND
                # sender provided pair metadata, register first so
                # record_outcomes can succeed. Closes the post-restart
                # window where audit_set_store is empty (bootstrap pending)
                # but pending_signals already has resolved=True from SQLite.
                if (
                    req.genius is not None
                    and req.idiot is not None
                    and audit_set_store.get_pair_for_signal(req.signal_id) is None
                ):
                    pid = req.purchase_id if req.purchase_id is not None else 0
                    try:
                        audit_set_store.add_signal(
                            genius=req.genius,
                            idiot=req.idiot,
                            cycle=0,
                            signal_id=req.signal_id,
                            purchase_id=pid,
                        )
                        log.info(
                            "outcome_gossip_added_signal_from_peer",
                            signal_id=req.signal_id,
                            source_uid=req.source_uid,
                            genius=req.genius[:10],
                            idiot=req.idiot[:10],
                        )
                    except Exception as e:
                        log.warning(
                            "outcome_gossip_add_signal_failed",
                            signal_id=req.signal_id,
                            error=str(e)[:120],
                        )
                audit_set_store.record_outcomes(req.signal_id, outcomes_enum)
                # v1717: outcomes for a previously-abstained signal can now
                # complete its batch. Reset abstain counter so the next
                # get_ready_sets surfaces the audit_set again.
                pair = audit_set_store.get_pair_for_signal(req.signal_id)
                if pair is not None:
                    g, i, cyc = pair
                    audit_set_store.reset_abstain(g, i, cyc)
            except Exception as e:
                log.warning(
                    "outcome_gossip_audit_record_failed",
                    signal_id=req.signal_id,
                    error=str(e)[:120],
                )

        log.info(
            "outcome_gossip_received",
            signal_id=req.signal_id,
            source_uid=req.source_uid,
            signer=(signer_hotkey or "")[:10],
            status=status,
            outcome_len=len(req.outcomes),
            # Diagnostic for Phase A1.8 bridge: tells us whether sender
            # included pair metadata. If has_pair=False on a status=
            # already_resolved gossip, the sender's audit_set_store
            # didn't know about the signal — sender bug. If has_pair=True
            # but outcome_gossip_added_signal_from_peer didn't fire,
            # the receiver-side bridge has a bug.
            has_pair=(req.genius is not None and req.idiot is not None),
            has_purchase_id=(req.purchase_id is not None),
        )

        # v1747 Phase 3: store per-line peer attestation sigs when the gossip
        # carries them and we have chain context wired. Bad sigs are dropped
        # without rejecting the gossip — the legacy outcome propagation is
        # unaffected by sig-layer issues.
        if (
            status in ("accepted", "already_resolved")
            and req.eoa is not None
            and req.eoa_sigs is not None
            and peer_attestation_store is not None
            and line_outcome_chain_id is not None
            and line_outcome_registry_address is not None
        ):
            _store_peer_attestation_sigs(
                req=req,
                outcome_attestor=outcome_attestor,
                peer_attestation_store=peer_attestation_store,
                chain_id=line_outcome_chain_id,
                registry_address=line_outcome_registry_address,
                ov_signer_set_provider=ov_signer_set_provider,
                signer_hotkey=signer_hotkey or "",
            )

        if status == "accepted":
            _recv_tick("stored")
            return OutcomeGossipResponse(accepted=True, duplicate=False, reason="accepted")
        if status == "already_resolved":
            _recv_tick("duplicate")
            return OutcomeGossipResponse(accepted=True, duplicate=True, reason="already_resolved")
        if status == "unknown_signal":
            _recv_tick("unknown_signal")
            # 200 not 404 — sender will retry on next gossip cycle if signal
            # registers later. Returning 404 would just generate noise in
            # peer-error logs without changing behavior.
            return OutcomeGossipResponse(accepted=False, duplicate=False, reason="unknown_signal")
        if status == "pending_local":
            _recv_tick("replay_pending")
            return OutcomeGossipResponse(accepted=False, duplicate=False, reason="pending_local")
        # disputed
        _recv_tick("replay_disputed")
        return OutcomeGossipResponse(accepted=False, duplicate=False, reason="disputed")

    def _build_metagraph_node(mg: Any, uid: int, egress_map: dict[int, list[str]] | None = None) -> dict | None:
        """Project one metagraph row into the shape expected by the web
        /api/{validators,miners}/discover consumers. Returns None if the
        row can't be read. Stakes are converted from TAO (float) to rao
        (int) so the wire format matches the SubnetState-derived bigint
        strings produced by `web/lib/bt-metagraph.ts` directly.

        ``egress_map`` is ``{uid: [ips]}`` from
        ``egress_reader.get_all_egress_commitments``; passed in (rather
        than fetched per-call) so the caller can amortize one read
        across the whole validator list.
        """

        def _to_int(val: Any) -> int:
            try:
                if hasattr(val, "item"):
                    return int(val.item())
                return int(val)
            except Exception:
                return 0

        def _to_float(val: Any) -> float:
            try:
                if hasattr(val, "item"):
                    return float(val.item())
                return float(val)
            except Exception:
                return 0.0

        def _to_bool(val: Any) -> bool:
            try:
                if hasattr(val, "item"):
                    return bool(val.item())
                return bool(val)
            except Exception:
                return False

        try:
            axon = mg.axons[uid]
        except Exception:
            return None
        ip = getattr(axon, "ip", "") or ""
        port = int(getattr(axon, "port", 0) or 0)
        hotkey = getattr(axon, "hotkey", "") or ""
        try:
            coldkey = mg.coldkeys[uid]
        except Exception:
            coldkey = ""

        # Stakes: TAO floats on the metagraph, rao bigints on the wire.
        def _rao(val: Any) -> str:
            return str(int(_to_float(val) * 1e9))

        total_stake_field = getattr(mg, "total_stake", None)
        alpha_stake_field = getattr(mg, "alpha_stake", None)
        tao_stake_field = getattr(mg, "tao_stake", None)
        total_stake = total_stake_field[uid] if total_stake_field is not None else getattr(mg, "S", [0])[uid]
        alpha_stake = alpha_stake_field[uid] if alpha_stake_field is not None else total_stake
        tao_stake = tao_stake_field[uid] if tao_stake_field is not None else 0

        incentive = _to_float(mg.I[uid]) if hasattr(mg, "I") else 0.0
        emission = _rao(mg.E[uid]) if hasattr(mg, "E") else "0"
        consensus = _to_float(mg.C[uid]) if hasattr(mg, "C") else 0.0
        dividends = _to_float(mg.D[uid]) if hasattr(mg, "D") else 0.0
        validator_trust = _to_float(mg.Tv[uid]) if hasattr(mg, "Tv") else 0.0
        # rank/trust aren't populated in lite mode; default to 0.0.
        rank = _to_float(getattr(mg, "rank", [0])[uid]) if hasattr(mg, "rank") else 0.0
        trust = _to_float(getattr(mg, "trust", [0])[uid]) if hasattr(mg, "trust") else 0.0
        is_validator = _to_bool(mg.validator_permit[uid]) if hasattr(mg, "validator_permit") else False

        # Chain-liveness: did this neuron submit something on chain
        # recently? Distinct from API liveness (HTTP /health probe). A
        # validator with chain_alive=True but api_alive=False is running
        # only the weight-setter (collects emissions, no buyer service).
        last_update_block = 0
        chain_blocks_since_update: int | None = None
        if hasattr(mg, "last_update"):
            try:
                last_update_block = _to_int(mg.last_update[uid])
            except Exception:
                last_update_block = 0
        if hasattr(mg, "block") and last_update_block > 0:
            try:
                cur = _to_int(mg.block)
                if cur > 0:
                    chain_blocks_since_update = cur - last_update_block
            except Exception:
                pass

        return {
            "uid": uid,
            "ip": ip,
            "port": port,
            "hotkey": hotkey,
            "coldkey": coldkey,
            "ss58Hotkey": hotkey,
            "stake": _rao(total_stake),
            "alphaStake": _rao(alpha_stake),
            "taoStake": _rao(tao_stake),
            "incentive": incentive,
            "emission": emission,
            "consensus": consensus,
            "trust": trust,
            "validatorTrust": validator_trust,
            "dividends": dividends,
            "rank": rank,
            "isValidator": is_validator,
            "egressIps": (egress_map or {}).get(uid, []) if is_validator else [],
            "lastUpdateBlock": last_update_block,
            "chainBlocksSinceUpdate": chain_blocks_since_update,
        }

    @app.get("/v1/network/validators")
    async def network_validators() -> dict:
        """Return the validator subset of the metagraph as JSON.

        Public endpoint. Lets the static IPFS-deployable web client
        discover the network without going through a centralized
        proxy. The client calls one bootstrap validator's
        /v1/network/validators, gets back the full validator list,
        then upgrades each entry to its v<uid>.djinn.gg pattern URL
        (or to the operator-advertised hostname from /health) for
        subsequent direct calls.

        The endpoint is read-only and unauthenticated. The data is
        already public on the Bittensor metagraph; this is just a
        JSON projection over the validator's local view of it.

        Response shape matches /api/validators/discover so the Next
        proxy can forward it through verbatim with no field mapping.
        """
        import time as _net_time

        served_at_ms = int(_net_time.time() * 1000)

        if neuron is None or neuron.metagraph is None:
            return {
                "validators": [],
                "served_by_uid": None,
                "validator_count": 0,
                "served_at_ms": served_at_ms,
            }

        mg = neuron.metagraph
        validators_out: list[dict] = []
        try:
            from djinn_validator.utils.egress_reader import get_all_egress_commitments

            egress_map = get_all_egress_commitments(neuron)
        except Exception as e:
            log.warning("network_validators_egress_failed", error=str(e)[:200])
            egress_map = {}
        try:
            validator_uids = neuron.get_validator_uids() if hasattr(neuron, "get_validator_uids") else []
            for v_uid in validator_uids:
                node = _build_metagraph_node(mg, v_uid, egress_map=egress_map)
                if node is None:
                    continue
                validators_out.append(node)
        except Exception as e:
            log.warning("network_validators_failed", error=str(e)[:200])

        # Sort by stake descending to match the web client's ordering.
        validators_out.sort(key=lambda v: int(v.get("stake", "0") or "0"), reverse=True)

        return {
            "validators": validators_out,
            "served_by_uid": getattr(neuron, "uid", None),
            "validator_count": len(validators_out),
            "served_at_ms": served_at_ms,
        }

    _delegates_cache: dict[str, object] = {"map": None, "fetched_at": 0.0}
    _DELEGATES_TTL_SEC = 600.0  # 10 min, matches web/app/api/delegates/route.ts

    @app.get("/v1/network/delegates")
    async def network_delegates() -> dict:
        """Taostats name map: {hex|ss58 → delegate name}.

        Mirror of the former `web/app/api/delegates/route.ts` so the
        IPFS-served bundle can fetch names from any validator without
        a Vercel proxy. Pulls dTAO validators on the configured subnet
        and root-network validators; indexes both hotkeys and coldkeys,
        each stored under the 0x-hex and ss58 form so callers can match
        whichever they hold.

        Returns `{}` with 200 when TAOSTATS_API_KEY is missing (name
        map is a UX nice-to-have, not a correctness requirement).
        """
        now = time.time()
        cached = _delegates_cache.get("map")
        fetched_at = float(_delegates_cache.get("fetched_at", 0.0))
        if cached is not None and (now - fetched_at) < _DELEGATES_TTL_SEC:
            return cached  # type: ignore[return-value]

        api_key = os.getenv("TAOSTATS_API_KEY", "")
        if not api_key:
            log.warning("delegates_no_taostats_key")
            empty: dict = {}
            _delegates_cache["map"] = empty
            _delegates_cache["fetched_at"] = now
            return empty

        netuid = os.getenv("BT_NETUID", "103")
        headers = {"Authorization": api_key}
        base = "https://api.taostats.io/api"

        try:
            from scalecodec.utils.ss58 import ss58_decode
        except ImportError:
            log.warning("delegates_scalecodec_missing")
            raise HTTPException(status_code=503, detail="ss58 decoder unavailable")

        def _to_hex(ss58: str) -> str | None:
            try:
                return "0x" + ss58_decode(ss58)
            except Exception:
                return None

        name_map: dict[str, str] = {}
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                dtao_url = f"{base}/dtao/validator/available/v1?netuid={netuid}&limit=200"
                vroot_url = f"{base}/validator/latest/v1?limit=200&order=stake_desc"
                dtao_resp, vroot_resp = await asyncio.gather(
                    client.get(dtao_url, headers=headers),
                    client.get(vroot_url, headers=headers),
                    return_exceptions=True,
                )

            if not isinstance(dtao_resp, Exception) and dtao_resp.status_code == 200:
                for entry in dtao_resp.json().get("data") or []:
                    name = entry.get("name")
                    addr = (entry.get("address") or {}).get("ss58")
                    if not name or not addr:
                        continue
                    hex_ = _to_hex(addr)
                    if hex_:
                        name_map[hex_] = name
                    name_map[addr] = name

            if not isinstance(vroot_resp, Exception) and vroot_resp.status_code == 200:
                for v in vroot_resp.json().get("data") or []:
                    name = v.get("name")
                    if not name:
                        continue
                    for key in (
                        (v.get("hotkey") or {}).get("ss58"),
                        (v.get("coldkey") or {}).get("ss58"),
                    ):
                        if not key:
                            continue
                        hex_ = _to_hex(key)
                        if hex_ and hex_ not in name_map:
                            name_map[hex_] = name
                        if key not in name_map:
                            name_map[key] = name
        except httpx.HTTPError as e:
            log.warning("delegates_taostats_http_error", error=str(e)[:200])
            # On upstream failure, serve the stale map if we have one.
            if cached is not None:
                return cached  # type: ignore[return-value]
            raise HTTPException(status_code=502, detail="taostats unreachable") from e

        _delegates_cache["map"] = name_map
        _delegates_cache["fetched_at"] = now
        return name_map

    @app.get("/v1/network/metagraph/miners")
    async def network_metagraph_miners() -> dict:
        """Return the miner subset of the metagraph as JSON.

        Mirror of /v1/network/validators for the miner table. Public,
        unauthenticated; all data is already on the public metagraph.
        Filters out UIDs with validator_permit so the response matches
        /api/miners/discover's semantics (miners only).

        Distinct from /v1/network/miners (which returns this validator's
        scorer view of miners — accuracy, uptime, attestation stats).
        This endpoint is the metagraph axon projection — just what the
        web /api/miners/discover proxy needs to render the miner table
        without a Vercel proxy.
        """
        import time as _net_time

        served_at_ms = int(_net_time.time() * 1000)

        if neuron is None or neuron.metagraph is None:
            return {
                "miners": [],
                "served_by_uid": None,
                "miner_count": 0,
                "served_at_ms": served_at_ms,
            }

        mg = neuron.metagraph
        miners_out: list[dict] = []
        try:
            total_n = neuron._safe_item(mg.n) if hasattr(neuron, "_safe_item") else int(mg.n)
            for uid in range(total_n):
                node = _build_metagraph_node(mg, uid)
                if node is None:
                    continue
                if node.get("isValidator"):
                    continue
                miners_out.append(node)
        except Exception as e:
            log.warning("network_metagraph_miners_failed", error=str(e)[:200])

        # Sort by incentive descending: highest earners first.
        miners_out.sort(key=lambda m: m.get("incentive", 0.0), reverse=True)

        return {
            "miners": miners_out,
            "served_by_uid": getattr(neuron, "uid", None),
            "miner_count": len(miners_out),
            "served_at_ms": served_at_ms,
        }

    def _peer_identity_matches(hj: dict[str, Any], expected_uid: int, expected_hotkey: str) -> bool:
        """Validate a peer's /health response against metagraph-claimed identity.

        Defends against 8421 port-squatting and UID spoofing: a peer is
        only trusted if its self-reported uid matches the metagraph uid
        we probed, AND its hotkey matches the metagraph hotkey for that
        uid. Missing hotkey handling depends on DJINN_FF_STRICT_PEER_HOTKEY:

        - OFF (default, pre-fleet-upgrade): accept empty claimed_hotkey
          for backwards compatibility with validators running <v1351,
          but log `peer_hotkey_missing` at INFO so operators can track
          rollout. UID is still required to match.
        - ON: reject empty or mismatched hotkey. Use once every peer
          is confirmed on v1351+ (closes the empty-hotkey bypass
          flagged by v1352 fresh-eyes audit).
        """
        if "version" not in hj or "uid" not in hj:
            return False
        try:
            claimed_uid = int(hj["uid"])
        except (TypeError, ValueError):
            return False
        if claimed_uid != expected_uid:
            return False
        claimed_hotkey = str(hj.get("hotkey", "") or "")
        if expected_hotkey:
            if not claimed_hotkey:
                try:
                    from djinn_validator.feature_flags import flags as _ff

                    if _ff.strict_peer_hotkey:
                        return False
                except Exception:
                    pass
                try:
                    log.info(
                        "peer_hotkey_missing",
                        expected_uid=expected_uid,
                        expected_hotkey=expected_hotkey[:12],
                        claimed_version=str(hj.get("version", ""))[:16],
                    )
                except Exception:
                    pass
            elif claimed_hotkey != expected_hotkey:
                return False
        return True

    # Shared HTTP client for all peer aggregator endpoints (matrix, overview,
    # per-validator detail). One pool is bounded so a dashboard refresh storm
    # on a 50-peer fleet can't open 1000 TCP sockets. Default httpx timeouts
    # are overridden per-call via `timeout=` kwarg on each .get().
    _peer_probe_client = httpx.AsyncClient(
        limits=httpx.Limits(max_connections=50, max_keepalive_connections=20),
    )
    _cleanup_resources.append(_peer_probe_client)

    # Cap per-response body size when probing peers. A malicious peer
    # returning a 5GB JSON stream would otherwise OOM the validator. 4MB is
    # comfortably above any honest /health (<1KB) or /v1/network/miners
    # (scales with miner count × ~500 bytes/entry; 4MB handles ~8000 miners).
    _PEER_MAX_BODY_BYTES = 4 * 1024 * 1024

    # Whole-probe-call budget. Even if individual .get() calls time out at
    # the httpx level, DNS, TCP connect, and retry logic shouldn't let a
    # peer consume more than this much wall-clock time.
    _PEER_PROBE_BUDGET_S = 30.0

    async def _peer_get_bounded(url: str, *, timeout: float) -> dict[str, Any] | None:
        """GET a peer URL and return parsed JSON, capped at _PEER_MAX_BODY_BYTES.

        Returns None on any error (timeout, non-200, oversized body, bad JSON).
        Used by all validator aggregator probes to defend against malicious
        peers responding with multi-gigabyte streams that would OOM us.
        """
        try:
            async with _peer_probe_client.stream("GET", url, timeout=timeout) as r:
                if r.status_code != 200:
                    return None
                buf = bytearray()
                async for chunk in r.aiter_bytes():
                    buf.extend(chunk)
                    if len(buf) > _PEER_MAX_BODY_BYTES:
                        return None
                import json as _json

                return _json.loads(buf.decode("utf-8", errors="replace"))
        except Exception:
            return None

    # In-memory cache for the /v1/network/overview aggregation.
    # Rebuilding requires N peer health probes; web clients polling the
    # dashboard would otherwise trigger O(N) fan-out on every request.
    # 120s TTL matches the old Vercel edge cache. Guarded by a lock so a
    # burst of concurrent requests during a cache-miss all await the same
    # fill instead of each triggering their own fan-out (stampede defense).
    _overview_cache: dict[str, Any] = {"data": None, "fetched_at": 0.0}
    _OVERVIEW_CACHE_TTL = 120.0
    _overview_cache_lock = asyncio.Lock()
    # v1697: per-peer last-known-good cache. Surfaces "ok" for ~5 min after
    # the most recent successful probe so a single transient timeout (UID 2
    # consistently flapped 1-of-5 probes due to GCP egress hiccups) doesn't
    # mark a peer "Offline" on /network UI. Only refreshes when we GET a
    # successful probe or the grace window expires.
    _peer_last_ok: dict[int, dict[str, Any]] = {}
    _PEER_OK_GRACE_S = 300.0  # 5 min: long enough to absorb a single skipped overview build

    @app.get("/v1/network/overview")
    async def network_overview() -> dict:
        """Aggregate validator + miner view of the subnet for dashboards.

        Returns the same shape as the legacy /api/network/status Vercel
        aggregator so static IPFS web clients can hit the wildcard
        router instead of a centralized proxy. Cached for 120s per
        validator; peer /health probes happen in parallel with a 5s
        budget so one slow peer doesn't block the whole response.

        Public endpoint. All data is already on the public metagraph or
        served by each peer's own public /health; this is a join.
        """
        import time as _net_time

        now = _net_time.time()
        cached = _overview_cache.get("data")
        if cached is not None and now - _overview_cache.get("fetched_at", 0.0) < _OVERVIEW_CACHE_TTL:
            return cached

        # Stampede defense: only the first cache-miss filler does the fan-out.
        # Concurrent requests arriving during a 20s+ cache fill await the
        # same result instead of each spawning an independent N-peer probe.
        async with _overview_cache_lock:
            now = _net_time.time()
            cached = _overview_cache.get("data")
            if cached is not None and now - _overview_cache.get("fetched_at", 0.0) < _OVERVIEW_CACHE_TTL:
                return cached
            return await _network_overview_build(now)

    async def _network_overview_build(now: float) -> dict:
        empty: dict[str, Any] = {
            "summary": None,
            "validators": [],
            "miners": [],
            "ipClusters": {},
            "served_by_uid": getattr(neuron, "uid", None) if neuron else None,
            "served_at_ms": int(now * 1000),
        }
        if neuron is None or neuron.metagraph is None:
            return empty

        mg = neuron.metagraph
        try:
            total_n = neuron._safe_item(mg.n) if hasattr(neuron, "_safe_item") else int(mg.n)
        except Exception:
            return empty

        def _float(val: Any) -> float:
            try:
                if hasattr(val, "item"):
                    return float(val.item())
                return float(val)
            except Exception:
                return 0.0

        nodes: list[dict[str, Any]] = []
        for uid in range(total_n):
            try:
                axon = mg.axons[uid]
                ip = getattr(axon, "ip", "") or ""
                port = int(getattr(axon, "port", 0) or 0)
                hotkey = getattr(axon, "hotkey", "") or ""
                permit = mg.validator_permit[uid]
                is_validator = bool(permit.item() if hasattr(permit, "item") else permit)
                coldkey = ""
                try:
                    coldkey = mg.coldkeys[uid]
                except (IndexError, AttributeError, TypeError):
                    pass
                stake = _float(mg.S[uid])
                incentive = _float(mg.I[uid]) if hasattr(mg, "I") else 0.0
                emission = _float(mg.E[uid]) if hasattr(mg, "E") else 0.0
                vtrust = _float(mg.validator_trust[uid]) if hasattr(mg, "validator_trust") else 0.0
                nodes.append(
                    {
                        "uid": uid,
                        "ip": ip,
                        "port": port,
                        "hotkey": hotkey,
                        "coldkey": coldkey,
                        "stake": stake,
                        "incentive": incentive,
                        "emission": emission,
                        "validator_trust": vtrust,
                        "is_validator": is_validator,
                    }
                )
            except Exception as e:
                log.debug("overview_uid_skip", uid=uid, error=str(e)[:100])
                continue

        from djinn_validator.core.mpc_orchestrator import _is_public_ip

        # Probe-eligible validators: have a public axon we can reach.
        validators = [n for n in nodes if n["is_validator"] and _is_public_ip(n["ip"]) and n["port"] > 0]
        # No-axon validators: have validator_permit but ip=0.0.0.0 or
        # port=0 (haven't run djinn-validator yet). Surface them in the
        # /admin and /network UI so operators can chase the stragglers
        # rather than have them silently filtered out.
        no_axon_validators = [n for n in nodes if n["is_validator"] and (n["port"] == 0 or n["ip"] in ("", "0.0.0.0"))]
        miners_all = [n for n in nodes if not n["is_validator"]]

        own_uid = getattr(neuron, "uid", None) if neuron else None

        async def _probe_peer(v_node: dict[str, Any]) -> dict[str, Any]:
            ip, port, uid = v_node["ip"], v_node["port"], v_node["uid"]
            expected_hotkey = v_node.get("hotkey") or ""
            # Self-probe via loopback. Probing our own external IP from inside
            # the validator container hits NAT-hairpin paths that intermittently
            # exceed the 5s probe budget, leaving the bootstrap validator
            # reporting itself as "unreachable" on its own /v1/network/overview
            # (and therefore on djinn.gg/network, since that page consumes the
            # bootstrap's view). 127.0.0.1 always resolves to the same uvicorn
            # listener and returns in <1s.
            is_self = own_uid is not None and uid == own_uid
            if is_self:
                ip = "127.0.0.1"
            candidate_ports = [port]
            if port != 8421:
                candidate_ports.append(8421)
            # Self-probe goes to our own uvicorn. /health does inline git
            # subprocesses + chain RPC, so under the parallel fan-out of an
            # overview build it routinely takes 2-4s and occasionally past
            # 5s — at which point the old timeout flagged us "unreachable"
            # on our own dashboard. Loopback is essentially free, so a
            # generous self-timeout (still under _PEER_PROBE_BUDGET_S=30s)
            # absorbs the variance without changing peer-probe behavior.
            self_health_timeout = 15.0 if is_self else 5.0

            async def _inner() -> dict[str, Any]:
                for p in candidate_ports:
                    hj = await _peer_get_bounded(f"http://{ip}:{p}/health", timeout=self_health_timeout)
                    if hj is None:
                        continue
                    if not _peer_identity_matches(hj, uid, expected_hotkey):
                        continue
                    return {
                        "uid": uid,
                        "service_port": p,
                        "status": hj.get("status", "ok"),
                        "version": str(hj.get("version", "")),
                        "shares_held": hj.get("shares_held"),
                        "chain_connected": hj.get("chain_connected"),
                        "bt_connected": hj.get("bt_connected"),
                        "settlement_registered": hj.get("settlement_registered"),
                        "settlement_contract": hj.get("settlement_contract"),
                        "settlement_diagnosis": hj.get("settlement_diagnosis"),
                        "shamir_threshold": hj.get("shamir_threshold"),
                        "audit_min_batch_size": hj.get("audit_min_batch_size"),
                        "batch_settlement_http": hj.get("batch_settlement_http"),
                        "batch_settlement_http_submit": hj.get("batch_settlement_http_submit"),
                        "git_commit_ts": hj.get("git_commit_ts"),
                        "process_started_ts": hj.get("process_started_ts"),
                    }
                return {"uid": uid, "status": "unreachable", "version": ""}

            try:
                result = await asyncio.wait_for(_inner(), timeout=_PEER_PROBE_BUDGET_S)
            except TimeoutError:
                result = {"uid": uid, "status": "unreachable", "version": ""}
            # v1697: last-known-good cache. If this probe succeeded, refresh
            # the cache. If it failed, fall back to the prior good response
            # within _PEER_OK_GRACE_S — surfaces "ok" through transient flaps.
            now_p = time.time()
            if result.get("status") == "ok":
                _peer_last_ok[uid] = {"data": result, "ts": now_p}
                return result
            cached_ok = _peer_last_ok.get(uid)
            if cached_ok and now_p - cached_ok.get("ts", 0) < _PEER_OK_GRACE_S:
                stale = dict(cached_ok["data"])
                stale["status"] = "ok"
                stale["_from_grace_cache"] = True
                return stale
            return result

        health_results = await asyncio.gather(
            *[_probe_peer(v) for v in validators],
            return_exceptions=True,
        )
        health_by_uid: dict[int, dict[str, Any]] = {}
        for r in health_results:
            if isinstance(r, dict) and "uid" in r:
                health_by_uid[r["uid"]] = r

        # Local scoring view (our validator's opinion of miners). Other
        # validators may score differently; dashboards showing a single
        # pane of truth use whichever validator served the request.
        scoring_by_uid: dict[int, dict[str, Any]] = {}
        if scorer is not None:
            try:
                weights, breakdowns = scorer.compute_weights_detailed(is_active_epoch=True)
                for muid, mm in scorer._miners.items():
                    scoring_by_uid[muid] = {
                        "weight": round(float(weights.get(muid, 0.0)), 8),
                        "attestations_total": mm.attestations_total,
                        "attestations_valid": mm.attestations_valid,
                        "lifetime_attestations": mm.lifetime_attestations,
                        "lifetime_attestations_valid": mm.lifetime_attestations_valid,
                        "proactive_proof_verified": mm.proactive_proof_verified,
                        "uptime": round(mm.uptime_score(), 4),
                        "accuracy": round(mm.accuracy_score(), 4),
                        "queries_total": mm.queries_total,
                        "queries_correct": mm.queries_correct,
                        "notary_duties_assigned": mm.notary_duties_assigned,
                        "notary_duties_completed": mm.notary_duties_completed,
                    }
            except Exception as e:
                log.warning("overview_scoring_failed", error=str(e)[:200])

        validators.sort(key=lambda n: n["stake"], reverse=True)
        validator_list = [
            {
                "uid": v["uid"],
                "ip": v["ip"],
                "port": health_by_uid.get(v["uid"], {}).get("service_port", v["port"]),
                "ss58Hotkey": v["hotkey"],
                "coldkey": v["coldkey"],
                "stake": str(int(v["stake"])),
                "incentive": v["incentive"],
                "emission": str(v["emission"]),
                "validatorTrust": v["validator_trust"],
                "health": health_by_uid.get(v["uid"]),
            }
            for v in validators
        ]
        # Append validators with permit but no axon, with synthetic
        # health.status = "no_axon" so the UI distinguishes "not yet
        # running" from "ran but unreachable". Sort merged list by stake.
        no_axon_validators.sort(key=lambda n: n["stake"], reverse=True)
        for v in no_axon_validators:
            validator_list.append(
                {
                    "uid": v["uid"],
                    "ip": v["ip"] or "0.0.0.0",
                    "port": v["port"],
                    "ss58Hotkey": v["hotkey"],
                    "coldkey": v["coldkey"],
                    "stake": str(int(v["stake"])),
                    "incentive": v["incentive"],
                    "emission": str(v["emission"]),
                    "validatorTrust": v["validator_trust"],
                    "health": {"uid": v["uid"], "status": "no_axon", "version": ""},
                }
            )
        validator_list.sort(key=lambda x: int(x["stake"]), reverse=True)

        miners_all.sort(key=lambda n: n["incentive"], reverse=True)
        miner_list = [
            {
                "uid": m["uid"],
                "ip": m["ip"] or "0.0.0.0",
                "stake": str(int(m["stake"])),
                "incentive": m["incentive"],
                "emission": str(m["emission"]),
                **scoring_by_uid.get(m["uid"], {}),
            }
            for m in miners_all
        ]

        ip_clusters: dict[str, list[int]] = {}
        unique_ips: set[str] = set()
        for m in miners_all:
            ip = m["ip"]
            if ip and ip != "0.0.0.0":
                unique_ips.add(ip)
                subnet = ".".join(ip.split(".")[:3])
                ip_clusters.setdefault(subnet, []).append(m["uid"])

        incentive_vals = [m["incentive"] for m in miners_all if m["uid"] != 0]
        gini = 0.0
        if incentive_vals:
            srt = sorted(incentive_vals)
            tot = sum(srt)
            if tot > 0:
                n = len(srt)
                weighted = sum((i + 1) * v for i, v in enumerate(srt))
                gini = (2 * weighted) / (n * tot) - (n + 1) / n

        total_incentive = sum(n["incentive"] for n in nodes)
        uid0 = next((n for n in nodes if n["uid"] == 0), None)
        burn_percent = (uid0["incentive"] / total_incentive * 100.0) if (uid0 and total_incentive > 0) else 0.0

        healthy_vs = [h for h in health_by_uid.values() if h.get("status") == "ok"]
        holding_vs = [h for h in health_by_uid.values() if (h.get("shares_held") or 0) > 0]
        total_shares = sum(int(h.get("shares_held") or 0) for h in health_by_uid.values())
        versions_int: list[int] = []
        for h in health_by_uid.values():
            try:
                vi = int(str(h.get("version") or "0"))
                if vi > 0:
                    versions_int.append(vi)
            except Exception:
                pass
        highest_version = max(versions_int) if versions_int else 0

        summary = {
            "totalValidators": len(validators),
            "totalMiners": len(miners_all),
            "validatorsHealthy": len(healthy_vs),
            "validatorsHoldingShares": len(holding_vs),
            "totalShares": total_shares,
            "highestVersion": highest_version,
            "timestamp": int(now * 1000),
            "uniqueIps": len(unique_ips),
            "gini": round(gini, 3),
            "burnPercent": round(burn_percent, 1),
        }

        result = {
            "summary": summary,
            "validators": validator_list,
            "miners": miner_list,
            "ipClusters": ip_clusters,
            "served_by_uid": getattr(neuron, "uid", None),
            "served_at_ms": int(now * 1000),
        }
        _overview_cache["data"] = result
        _overview_cache["fetched_at"] = now
        return result

    # Cache for /v1/network/matrix. The matrix is a cross-validator score
    # join: each peer's /v1/network/miners fetched in parallel. 60s TTL
    # matches the old Vercel edge cache the endpoint replaces. Guarded by
    # a lock so a burst of concurrent requests during a cache-miss all
    # await the same fill (stampede defense).
    _matrix_cache: dict[str, Any] = {"data": None, "fetched_at": 0.0}
    _MATRIX_CACHE_TTL = 60.0
    _matrix_cache_lock = asyncio.Lock()

    @app.get("/v1/network/matrix")
    async def network_matrix() -> dict:
        """Validator × miner scoring matrix for dashboards.

        Fans out to every peer validator's /health and /v1/network/miners
        in parallel, joins the per-miner scoring views into a single
        matrix keyed by validator uid then miner uid. Cached for 60s.

        Returns the same shape as the legacy /api/network/matrix Vercel
        aggregator so static IPFS web clients can hit the wildcard
        router instead of a centralized proxy.

        Public endpoint. All inputs are public-metagraph or peer-public.
        """
        import time as _mx_time

        now = _mx_time.time()
        cached = _matrix_cache.get("data")
        if cached is not None and now - _matrix_cache.get("fetched_at", 0.0) < _MATRIX_CACHE_TTL:
            return cached

        async with _matrix_cache_lock:
            now = _mx_time.time()
            cached = _matrix_cache.get("data")
            if cached is not None and now - _matrix_cache.get("fetched_at", 0.0) < _MATRIX_CACHE_TTL:
                return cached
            return await _network_matrix_build(now)

    async def _network_matrix_build(now: float) -> dict:
        empty: dict[str, Any] = {
            "validators": [],
            "minerUids": [],
            "timestamp": int(now * 1000),
            "served_by_uid": getattr(neuron, "uid", None) if neuron else None,
        }
        if neuron is None or neuron.metagraph is None:
            return empty

        mg = neuron.metagraph
        try:
            total_n = neuron._safe_item(mg.n) if hasattr(neuron, "_safe_item") else int(mg.n)
        except Exception:
            return empty

        def _float(val: Any) -> float:
            try:
                if hasattr(val, "item"):
                    return float(val.item())
                return float(val)
            except Exception:
                return 0.0

        from djinn_validator.core.mpc_orchestrator import _is_public_ip

        validators_raw: list[dict[str, Any]] = []
        for uid in range(total_n):
            try:
                permit = mg.validator_permit[uid]
                is_validator = bool(permit.item() if hasattr(permit, "item") else permit)
                if not is_validator:
                    continue
                axon = mg.axons[uid]
                ip = getattr(axon, "ip", "") or ""
                port = int(getattr(axon, "port", 0) or 0)
                if not ip or ip == "0.0.0.0" or port <= 0 or not _is_public_ip(ip):
                    continue
                stake = _float(mg.S[uid])
                hotkey = ""
                try:
                    hotkey = str(mg.hotkeys[uid]) if hasattr(mg, "hotkeys") else ""
                except (IndexError, AttributeError, TypeError):
                    hotkey = ""
                if not hotkey:
                    hotkey = str(getattr(axon, "hotkey", "") or "")
                validators_raw.append({"uid": uid, "ip": ip, "port": port, "stake": stake, "hotkey": hotkey})
            except Exception as e:
                log.debug("matrix_uid_skip", uid=uid, error=str(e)[:100])
                continue

        own_uid_matrix = getattr(neuron, "uid", None) if neuron else None

        async def _probe_peer(v: dict[str, Any]) -> dict[str, Any]:
            ip, port, uid = v["ip"], v["port"], v["uid"]
            expected_hotkey = v.get("hotkey") or ""
            # Self-probe via loopback to avoid NAT-hairpin flakiness on the
            # validator's own external IP (see _network_overview_build for
            # the same fix).
            is_self_matrix = own_uid_matrix is not None and uid == own_uid_matrix
            if is_self_matrix:
                ip = "127.0.0.1"
            candidate_ports = [port]
            if port != 8421:
                candidate_ports.append(8421)
            # Self-probe is to our own uvicorn; /health is slow under
            # parallel fan-out (see _network_overview_build comment), so
            # bump the per-call budget for self only.
            self_health_timeout = 18.0 if is_self_matrix else 8.0

            # Phase 1: /health probe — determines the healthy verdict. Run
            # under its own wall-clock budget so a slow/hanging miners
            # endpoint in Phase 2 cannot retroactively null out a successful
            # health response (which is what produced the cached "Offline"
            # flap on UID 2 / UID 213 around the v1651 rolling upgrade).
            async def _probe_health() -> tuple[dict[str, Any] | None, int]:
                for p in candidate_ports:
                    hj = await _peer_get_bounded(f"http://{ip}:{p}/health", timeout=self_health_timeout)
                    if hj is None:
                        continue
                    if not _peer_identity_matches(hj, uid, expected_hotkey):
                        continue
                    return hj, p
                return None, port

            try:
                health, service_port = await asyncio.wait_for(_probe_health(), timeout=_PEER_PROBE_BUDGET_S)
            except TimeoutError:
                health, service_port = None, port

            # Phase 2: /v1/network/miners — best-effort. Failure or timeout
            # leaves miners empty for this validator's row but the
            # healthy/version verdict from Phase 1 stands.
            miners_by_uid: dict[int, dict[str, Any]] = {}
            if health is not None:
                try:
                    mj = await asyncio.wait_for(
                        _peer_get_bounded(
                            f"http://{ip}:{service_port}/v1/network/miners",
                            timeout=12.0,
                        ),
                        timeout=_PEER_PROBE_BUDGET_S,
                    )
                    if mj is not None:
                        for m in mj.get("miners") or []:
                            muid = m.get("uid")
                            if isinstance(muid, int):
                                miners_by_uid[muid] = m
                except TimeoutError:
                    pass

            return {
                "uid": uid,
                "ip": ip,
                "port": service_port,
                "stake": str(int(v["stake"] * 1e9)),  # TAO → rao, matches web shape
                "version": (str(health.get("version")) if health else None),
                "healthy": bool(health and health.get("status") == "ok"),
                "miners": miners_by_uid,
            }

        probe_results = await asyncio.gather(
            *[_probe_peer(v) for v in validators_raw],
            return_exceptions=True,
        )
        validator_rows: list[dict[str, Any]] = []
        miner_uids: set[int] = set()
        for r in probe_results:
            if isinstance(r, dict):
                validator_rows.append(r)
                for muid in r["miners"].keys():
                    miner_uids.add(int(muid))

        result = {
            "validators": validator_rows,
            "minerUids": sorted(miner_uids),
            "timestamp": int(now * 1000),
            "served_by_uid": getattr(neuron, "uid", None),
        }
        _matrix_cache["data"] = result
        _matrix_cache["fetched_at"] = now
        return result

    # Per-uid cache for /v1/network/validator/{uid}. Separate from the
    # overview cache because: (a) the hot case is "self-report" (uid ==
    # neuron.uid) which is effectively free to rebuild from local state,
    # and (b) peer-probe responses for a single uid are small. 60s TTL
    # mirrors the Vercel edge cache the endpoint replaces.
    #
    # OrderedDict + max-size cap prevents a scanner hitting all 65536
    # possible UIDs from blowing memory (~200MB at 3KB/entry). 256 is
    # 25× the current subnet size, so legitimate traffic never evicts.
    from collections import OrderedDict as _OD

    _validator_detail_cache: _OD[int, dict[str, Any]] = _OD()
    _validator_detail_fetched: _OD[int, float] = _OD()
    _VALIDATOR_DETAIL_TTL = 60.0
    _VALIDATOR_DETAIL_MAX_ENTRIES = 256
    # Bound concurrent peer probes so a burst of distinct-UID requests
    # can't amplify into FD exhaustion on this validator or the target.
    # 8 is enough to keep the overview path responsive (needs parallel
    # fan-out) while capping worst-case outbound connections.
    _validator_detail_probe_sem = asyncio.Semaphore(8)

    @app.get("/v1/network/validator/{uid}")
    async def network_validator_detail(uid: int) -> dict:
        """Per-validator detail: metagraph view + health + scored miners.

        Public endpoint mirroring the legacy /api/network/validator/[uid]
        Vercel route so the static web client can render validator detail
        pages via the wildcard router. When called on v<uid>.djinn.gg the
        server short-circuits to local state; when called on another
        validator it probes the target peer for its health and miner list.
        """
        import time as _net_time

        if uid < 0 or uid > 65535:
            return {"uid": uid, "found": False, "error": "Invalid UID"}

        now = _net_time.time()
        cached = _validator_detail_cache.get(uid)
        if cached is not None and now - _validator_detail_fetched.get(uid, 0.0) < _VALIDATOR_DETAIL_TTL:
            # Promote to MRU end so active entries don't get LRU-evicted.
            _validator_detail_cache.move_to_end(uid)
            _validator_detail_fetched.move_to_end(uid)
            return cached

        if neuron is None or neuron.metagraph is None:
            return {"uid": uid, "found": False, "error": "Neuron not ready"}

        mg = neuron.metagraph
        try:
            total_n = neuron._safe_item(mg.n) if hasattr(neuron, "_safe_item") else int(mg.n)
        except Exception:
            return {"uid": uid, "found": False, "error": "Metagraph unavailable"}

        if uid >= total_n:
            return {"uid": uid, "found": False, "error": "UID out of range"}

        def _cache_store(entry: dict) -> dict:
            """LRU-bounded cache write. Moves key to MRU end, pops LRU when over cap."""
            _validator_detail_cache[uid] = entry
            _validator_detail_cache.move_to_end(uid)
            _validator_detail_fetched[uid] = now
            _validator_detail_fetched.move_to_end(uid)
            while len(_validator_detail_cache) > _VALIDATOR_DETAIL_MAX_ENTRIES:
                evicted_uid, _ = _validator_detail_cache.popitem(last=False)
                _validator_detail_fetched.pop(evicted_uid, None)
            return entry

        def _float(val: Any) -> float:
            try:
                if hasattr(val, "item"):
                    return float(val.item())
                return float(val)
            except Exception:
                return 0.0

        try:
            axon = mg.axons[uid]
            permit = mg.validator_permit[uid]
            is_validator = bool(permit.item() if hasattr(permit, "item") else permit)
        except Exception as e:
            return {"uid": uid, "found": False, "error": f"axon_lookup_failed: {str(e)[:80]}"}

        ip = getattr(axon, "ip", "") or ""
        port = int(getattr(axon, "port", 0) or 0)
        expected_hotkey = ""
        try:
            expected_hotkey = str(mg.hotkeys[uid]) if hasattr(mg, "hotkeys") else ""
        except (IndexError, AttributeError, TypeError):
            expected_hotkey = ""
        if not expected_hotkey:
            expected_hotkey = str(getattr(axon, "hotkey", "") or "")

        if not is_validator:
            return _cache_store({"uid": uid, "found": False, "error": "UID is not a validator"})

        from djinn_validator.core.mpc_orchestrator import _is_public_ip

        if not _is_public_ip(ip) or port <= 0:
            return _cache_store({"uid": uid, "found": False, "error": "Validator not reachable"})

        try:
            from djinn_validator.utils.egress_reader import get_all_egress_commitments

            _egress_for_uid = get_all_egress_commitments(neuron).get(uid, [])
        except Exception:
            _egress_for_uid = []

        metagraph_view = {
            "ip": ip,
            "port": port,
            "stake": str(int(_float(mg.S[uid]))),
            "incentive": _float(mg.I[uid]) if hasattr(mg, "I") else 0.0,
            "emission": str(_float(mg.E[uid]) if hasattr(mg, "E") else 0.0),
            "validatorTrust": _float(mg.validator_trust[uid]) if hasattr(mg, "validator_trust") else 0.0,
            "egressIps": _egress_for_uid,
        }

        health_data: dict[str, Any] | None = None
        miners_data: list[dict[str, Any]] = []
        validator_uid_reported: int | None = None

        # Fast path: if this validator IS the requested uid, serve from
        # local state. Avoids an unnecessary self-probe and always has
        # the freshest scoring data.
        own_uid = getattr(neuron, "uid", None)
        self_served = own_uid is not None and int(own_uid) == int(uid)

        if self_served:
            # Build health from local state (no self-HTTP call).
            from djinn_validator import __git_sha__, __version__

            try:
                shares = share_store.count if share_store is not None else 0
            except Exception:
                shares = 0
            try:
                pending = len(outcome_attestor.get_pending_signals()) if outcome_attestor is not None else 0
            except Exception:
                pending = 0
            chain_ok = False
            if chain_client is not None:
                try:
                    chain_ok = await chain_client.is_connected()
                except Exception:
                    chain_ok = False
            settlement_contract_val = None
            settlement_registered_val: bool | None = None
            if chain_client is not None:
                ov_addr = getattr(chain_client, "_outcome_voting_address", "")
                if isinstance(ov_addr, str) and ov_addr:
                    settlement_contract_val = ov_addr
                sa = getattr(chain_client, "validator_address", None)
                if chain_client.can_write and isinstance(sa, str) and sa:
                    settlement_registered_val = await _probe_settlement_registered_cached(chain_client, sa)

            from djinn_validator.core import tlsn as _tlsn_mod

            # v1562 parity: self-view should expose the same config-echo +
            # feature-flag fields as the peer-probe path so the detail page
            # renders the same badges whether UID matches or not.
            try:
                from djinn_validator.core.audit_set import MIN_BATCH_SIZE as _min_batch_local

                _audit_min_batch_local: int | None = int(_min_batch_local)
            except Exception:
                _audit_min_batch_local = None
            try:
                _shamir_threshold_local: int | None = int(_readiness_config.shares_threshold)
            except Exception:
                _shamir_threshold_local = None
            try:
                from djinn_validator.feature_flags import flags as _ff_local

                _bs_http_local: bool | None = bool(_ff_local.batch_settlement_http)
                _bs_http_submit_local: bool | None = bool(_ff_local.batch_settlement_http_submit)
            except Exception:
                _bs_http_local = None
                _bs_http_submit_local = None

            from djinn_validator import __git_commit_ts__ as _self_commit_ts

            health_data = {
                "status": "ok",
                "version": __version__,
                "git_sha": __git_sha__,
                "uid": own_uid,
                "shares_held": shares,
                "pending_outcomes": pending,
                "chain_connected": chain_ok,
                "bt_connected": True,
                "attest_capable": _tlsn_mod.is_available(),
                "settlement_registered": settlement_registered_val,
                "settlement_contract": settlement_contract_val,
                "shamir_threshold": _shamir_threshold_local,
                "audit_min_batch_size": _audit_min_batch_local,
                "batch_settlement_http": _bs_http_local,
                "batch_settlement_http_submit": _bs_http_submit_local,
                "git_commit_ts": _self_commit_ts,
                "process_started_ts": _PROCESS_STARTED_TS,
            }
            validator_uid_reported = own_uid

            # Fill miners_data from local scorer.
            if scorer is not None:
                try:
                    weights, breakdowns = scorer.compute_weights_detailed(is_active_epoch=True)
                    for muid, mm in sorted(scorer._miners.items()):
                        breakdowns.get(muid, {})
                        miners_data.append(
                            {
                                "uid": muid,
                                "hotkey": mm.hotkey,
                                "coldkey": mm.coldkey,
                                "status": "ok" if mm.ema_uptime > 0.001 and mm.uptime_score() > 0.5 else "offline",
                                "version": mm.reported_version,
                                "uptime": round(mm.uptime_score(), 4),
                                "accuracy": round(mm.accuracy_score(), 4),
                                "queries_total": mm.queries_total,
                                "queries_correct": mm.queries_correct,
                                "attestations_total": mm.attestations_total,
                                "attestations_valid": mm.attestations_valid,
                                "proactive_proof_verified": mm.proactive_proof_verified,
                                "notary_duties_assigned": mm.notary_duties_assigned,
                                "notary_duties_completed": mm.notary_duties_completed,
                                "notary_reliability": round(mm.notary_reliability(), 4),
                                "weight": round(weights.get(muid, 0.0), 8),
                                "lifetime_attestations": mm.lifetime_attestations,
                                "lifetime_attestations_valid": mm.lifetime_attestations_valid,
                            }
                        )
                except Exception as e:
                    log.warning("self_validator_scoring_failed", error=str(e)[:200])
        else:
            # Peer path: probe the target validator for its health + miners.
            # Guarded by a small semaphore so a burst of distinct-UID requests
            # can't amplify into FD exhaustion (each probe opens up to 2 TCP
            # connections for the port fallback).
            async def _probe_peer() -> tuple[dict | None, list[dict], int | None]:
                candidate_ports = [port]
                if port != 8421:
                    candidate_ports.append(8421)
                health_out: dict | None = None
                miners_out: list[dict] = []
                vuid_out: int | None = None
                for p in candidate_ports:
                    hj = await _peer_get_bounded(f"http://{ip}:{p}/health", timeout=5.0)
                    if hj is None:
                        continue
                    if not _peer_identity_matches(hj, uid, expected_hotkey):
                        continue
                    health_out = {
                        "status": hj.get("status", "ok"),
                        "version": str(hj.get("version", "")),
                        "uid": hj.get("uid"),
                        "shares_held": hj.get("shares_held"),
                        "pending_outcomes": hj.get("pending_outcomes"),
                        "chain_connected": hj.get("chain_connected"),
                        "bt_connected": hj.get("bt_connected"),
                        "attest_capable": hj.get("attest_capable"),
                        "settlement_registered": hj.get("settlement_registered"),
                        "settlement_contract": hj.get("settlement_contract"),
                        "settlement_diagnosis": hj.get("settlement_diagnosis"),
                        "settlement_remediation": hj.get("settlement_remediation"),
                        "shamir_threshold": hj.get("shamir_threshold"),
                        "audit_min_batch_size": hj.get("audit_min_batch_size"),
                        "batch_settlement_http": hj.get("batch_settlement_http"),
                        "batch_settlement_http_submit": hj.get("batch_settlement_http_submit"),
                        "git_commit_ts": hj.get("git_commit_ts"),
                        "process_started_ts": hj.get("process_started_ts"),
                    }
                    mj = await _peer_get_bounded(f"http://{ip}:{p}/v1/network/miners", timeout=5.0)
                    if mj is not None:
                        miners_out = mj.get("miners", []) or []
                        vuid_out = mj.get("validator_uid")
                    return health_out, miners_out, vuid_out
                return health_out, miners_out, vuid_out

            async with _validator_detail_probe_sem:
                try:
                    health_data, miners_data, validator_uid_reported = await asyncio.wait_for(
                        _probe_peer(), timeout=_PEER_PROBE_BUDGET_S
                    )
                except TimeoutError:
                    health_data, miners_data, validator_uid_reported = None, [], None

        return _cache_store(
            {
                "uid": uid,
                "found": True,
                "metagraph": metagraph_view,
                "health": health_data,
                "miners": miners_data,
                "validatorUid": validator_uid_reported,
            }
        )

    # Per-uid cache for /v1/network/miner/{uid}. Cross-validator fan-out
    # amplification defense: 30s TTL prevents a scanner iterating UIDs
    # from fanning out N×M probes per second. 256-entry OrderedDict with
    # LRU eviction mirrors the /v1/network/validator/{uid} cache shape;
    # per-uid asyncio.Lock collapses concurrent misses for the same UID
    # into a single fill (stampede defense).
    _miner_agg_cache: _OD[int, dict[str, Any]] = _OD()
    _miner_agg_fetched: _OD[int, float] = _OD()
    _MINER_AGG_TTL = 30.0
    _MINER_AGG_MAX_ENTRIES = 256
    _miner_agg_locks: dict[int, asyncio.Lock] = {}

    @app.get("/v1/network/miner/{uid}")
    async def network_miner_aggregate(uid: int) -> dict:
        """Per-miner aggregate view: fan-out scores from every validator
        plus this subnet's metagraph entry for the target UID.

        Public endpoint mirroring the legacy /api/network/miner/[uid] Vercel
        route so static IPFS web clients can read miner dashboards via the
        wildcard validator router instead of a centralized proxy.

        Returns:
            {uid, scores: [{validatorUid, ...per-validator fields from
             /v1/miner/{uid}/scores}], metagraph: {ip, incentive, emission,
             isValidator, stake} or null if the UID is not in the metagraph}
        """
        import time as _nm_time

        if uid < 0 or uid > 65535:
            raise HTTPException(status_code=400, detail="Invalid UID")

        now = _nm_time.time()
        cached = _miner_agg_cache.get(uid)
        if cached is not None and now - _miner_agg_fetched.get(uid, 0.0) < _MINER_AGG_TTL:
            _miner_agg_cache.move_to_end(uid)
            _miner_agg_fetched.move_to_end(uid)
            return cached

        lock = _miner_agg_locks.setdefault(uid, asyncio.Lock())
        async with lock:
            now = _nm_time.time()
            cached = _miner_agg_cache.get(uid)
            if cached is not None and now - _miner_agg_fetched.get(uid, 0.0) < _MINER_AGG_TTL:
                _miner_agg_cache.move_to_end(uid)
                _miner_agg_fetched.move_to_end(uid)
                return cached
            built = await _network_miner_build(uid, now)
            _miner_agg_cache[uid] = built
            _miner_agg_cache.move_to_end(uid)
            _miner_agg_fetched[uid] = now
            _miner_agg_fetched.move_to_end(uid)
            while len(_miner_agg_cache) > _MINER_AGG_MAX_ENTRIES:
                evicted_uid, _ = _miner_agg_cache.popitem(last=False)
                _miner_agg_fetched.pop(evicted_uid, None)
                _miner_agg_locks.pop(evicted_uid, None)
            return built

    async def _network_miner_build(uid: int, now: float) -> dict:
        empty = {"uid": uid, "scores": [], "metagraph": None}
        if neuron is None or neuron.metagraph is None:
            return empty

        mg = neuron.metagraph
        try:
            total_n = neuron._safe_item(mg.n) if hasattr(neuron, "_safe_item") else int(mg.n)
        except Exception:
            return empty

        def _float(val: Any) -> float:
            try:
                if hasattr(val, "item"):
                    return float(val.item())
                return float(val)
            except Exception:
                return 0.0

        from djinn_validator.core.mpc_orchestrator import _is_public_ip

        metagraph_view: dict | None = None
        if uid < total_n:
            try:
                axon = mg.axons[uid]
                permit = mg.validator_permit[uid]
                is_validator = bool(permit.item() if hasattr(permit, "item") else permit)
                metagraph_view = {
                    "ip": (getattr(axon, "ip", "") or "0.0.0.0"),
                    "incentive": _float(mg.I[uid]) if hasattr(mg, "I") else 0.0,
                    "emission": str(int(_float(mg.E[uid] if hasattr(mg, "E") else 0.0) * 1e9)),
                    "isValidator": is_validator,
                    "stake": str(int(_float(mg.S[uid]) * 1e9)),
                }
            except Exception as e:
                log.debug("miner_agg_metagraph_skip", uid=uid, error=str(e)[:100])

        validators_raw: list[dict[str, Any]] = []
        for vuid in range(total_n):
            try:
                permit = mg.validator_permit[vuid]
                is_val = bool(permit.item() if hasattr(permit, "item") else permit)
                if not is_val:
                    continue
                vaxon = mg.axons[vuid]
                ip = getattr(vaxon, "ip", "") or ""
                port = int(getattr(vaxon, "port", 0) or 0)
                if not ip or ip == "0.0.0.0" or port <= 0 or not _is_public_ip(ip):
                    continue
                validators_raw.append({"uid": vuid, "ip": ip, "port": port})
            except Exception:
                continue

        own_uid = getattr(neuron, "uid", None)

        async def _probe(v: dict) -> dict | None:
            if own_uid is not None and int(own_uid) == int(v["uid"]):
                if scorer is None:
                    return None
                m = scorer.get(uid)
                if m is None:
                    return {"validatorUid": v["uid"], "uid": uid, "found": False}
                try:
                    weights, breakdowns = scorer.compute_weights_detailed(is_active_epoch=True)
                except Exception:
                    weights, breakdowns = {}, {}
                breakdown = breakdowns.get(uid, {})
                weight = weights.get(uid, 0.0)
                return {
                    "validatorUid": v["uid"],
                    "uid": uid,
                    "found": True,
                    "hotkey": m.hotkey,
                    "accuracy": round(m.accuracy_score(), 4),
                    "coverage": round(m.coverage_score(), 4),
                    "uptime": round(m.uptime_score(), 4),
                    "attest_validity": round(m.attestation_validity_score(), 4),
                    "queries_total": m.queries_total,
                    "queries_correct": m.queries_correct,
                    "attestations_total": m.attestations_total,
                    "attestations_valid": m.attestations_valid,
                    "notary_duties_assigned": m.notary_duties_assigned,
                    "notary_duties_completed": m.notary_duties_completed,
                    "notary_reliability": round(m.notary_reliability(), 4),
                    "weight": round(weight, 8),
                    "weight_breakdown": {k: round(x, 6) if isinstance(x, float) else x for k, x in breakdown.items()}
                    if breakdown
                    else None,
                }
            candidate_ports = [v["port"]]
            if v["port"] != 8421:
                candidate_ports.append(8421)
            for p in candidate_ports:
                data = await _peer_get_bounded(f"http://{v['ip']}:{p}/v1/miner/{uid}/scores", timeout=6.0)
                if data is None:
                    continue
                if not data.get("found", False):
                    continue
                return {"validatorUid": v["uid"], **data}
            return None

        probe_results = await asyncio.gather(
            *[_probe(v) for v in validators_raw],
            return_exceptions=True,
        )
        scores: list[dict] = []
        for r in probe_results:
            if isinstance(r, dict) and r.get("found", False):
                scores.append(r)

        return {"uid": uid, "scores": scores, "metagraph": metagraph_view}

    # ------------------------------------------------------------------
    # Shared HTTP client for attestation dispatch (connection reuse)
    # ------------------------------------------------------------------
    _attest_client = httpx.AsyncClient(
        timeout=120.0,
        limits=httpx.Limits(max_keepalive_connections=10, max_connections=50),
    )
    _cleanup_resources.append(_attest_client)

    # ------------------------------------------------------------------
    # MPC orchestration
    # ------------------------------------------------------------------
    _mpc = mpc_coordinator or MPCCoordinator()
    _orchestrator = MPCOrchestrator(
        coordinator=_mpc,
        neuron=neuron,
        threshold=shares_threshold,
        encryption_privkey=encryption_privkey,
        signer_address=signer_address,
        outcome_attestor=outcome_attestor,
    )
    _cleanup_resources.append(_orchestrator)

    # Per-session participant state for the distributed MPC protocol.
    # Keyed by session_id. Stores either DistributedParticipantState (semi-honest)
    # or AuthenticatedParticipantState (SPDZ malicious security).
    import threading as _threading
    import time as _time

    from djinn_validator.core.spdz import AuthenticatedParticipantState, AuthenticatedShare, MACKeyShare

    _participant_states: dict[str, DistributedParticipantState | AuthenticatedParticipantState] = {}
    _participant_created: dict[str, float] = {}  # session_id -> monotonic timestamp
    _participant_lock = _threading.Lock()

    # Separate state table for masked polynomial membership sessions.
    # Kept distinct from the sequential-gate participant states to avoid
    # cross-protocol bugs and simplify cleanup.
    from djinn_validator.core.mpc_membership import MembershipPeerState

    _membership_states: dict[str, MembershipPeerState] = {}
    _membership_created: dict[str, float] = {}

    _PARTICIPANT_TTL = 120  # seconds before stale participant states are cleaned up
    _MAX_PARTICIPANT_STATES = 500

    def _cleanup_stale_participants_locked() -> int:
        """Remove participant states older than _PARTICIPANT_TTL. Caller holds _participant_lock."""
        now = _time.monotonic()
        stale = [sid for sid, ts in _participant_created.items() if now - ts > _PARTICIPANT_TTL]
        for sid in stale:
            _participant_states.pop(sid, None)
            _participant_created.pop(sid, None)
        if stale:
            log.info("participant_state_cleanup", evicted=len(stale))
        return len(stale)

    # Collect validator hotkeys from metagraph for auth
    def _get_validator_hotkeys() -> set[str] | None:
        """Get set of validator hotkeys from metagraph for MPC auth."""
        if neuron is None or neuron.metagraph is None:
            return None  # No auth in dev mode
        hotkeys = set()
        for uid in range(neuron.metagraph.n.item()):
            if neuron.metagraph.validator_permit[uid].item():
                hotkeys.add(neuron.metagraph.hotkeys[uid])
        return hotkeys if hotkeys else None

    @app.post("/v1/mpc/init", response_model=MPCInitResponse)
    async def mpc_init(req: MPCInitRequest, request: Request) -> MPCInitResponse:
        """Accept an MPC session invitation from the coordinator."""
        await validate_signed_request(request, _get_validator_hotkeys())

        # Clean up expired sessions to prevent memory leak
        _mpc.cleanup_expired()
        with _participant_lock:
            _cleanup_stale_participants_locked()
        with _ot_lock:
            _cleanup_stale_ot_states_locked()

        session = _mpc.get_session(req.session_id)
        if session is not None:
            return MPCInitResponse(
                session_id=req.session_id,
                accepted=True,
                message="Session already exists",
            )

        # Create session locally (participant mirrors coordinator state).
        # Pass empty pre_generated_triples to skip wasteful OT triple
        # generation. The peer uses the coordinator's triple shares (from
        # req.triple_shares), not locally-generated ones.
        session = _mpc.create_session(
            signal_id=req.signal_id,
            available_indices=req.available_indices,
            coordinator_x=req.coordinator_x,
            participant_xs=req.participant_xs,
            threshold=req.threshold,
            pre_generated_triples=[],
        )
        # Override the session_id to match coordinator's
        if not _mpc.replace_session_id(session.session_id, req.session_id):
            raise HTTPException(status_code=409, detail="Session ID conflict")

        # Create distributed participant state if r_share provided
        if req.r_share_y is not None:
            # Look up our local share for this signal
            record = share_store.get(req.signal_id)
            if record is None:
                log.warning("mpc_init_no_share", signal_id=req.signal_id)
                return MPCInitResponse(
                    session_id=req.session_id,
                    accepted=False,
                    message="No share held for this signal",
                )

            # Use the real-index share for MPC (not the AES key share)
            if record.encrypted_index_share and len(record.encrypted_index_share) > 0:
                index_share_y = int.from_bytes(record.encrypted_index_share, "big")
            else:
                index_share_y = record.share.y  # Legacy fallback

            try:
                if req.authenticated and req.auth_triple_shares and req.alpha_share and req.auth_r_share:
                    # SPDZ authenticated mode — validate all field elements
                    alpha_val = _parse_field_hex(req.alpha_share, "alpha_share")
                    r_y = _parse_field_hex(req.auth_r_share["y"], "auth_r_share.y")
                    r_mac = _parse_field_hex(req.auth_r_share["mac"], "auth_r_share.mac")

                    # Use auth_secret_share if provided, otherwise create from local index share
                    if req.auth_secret_share:
                        s_y = _parse_field_hex(req.auth_secret_share["y"], "auth_secret_share.y")
                        s_mac = _parse_field_hex(req.auth_secret_share["mac"], "auth_secret_share.mac")
                    else:
                        s_y = index_share_y
                        s_mac = 0  # Will fail MAC check if actually used

                    auth_ta = []
                    auth_tb = []
                    auth_tc = []
                    for i, ts in enumerate(req.auth_triple_shares):
                        auth_ta.append(
                            AuthenticatedShare(
                                x=record.share.x,
                                y=_parse_field_hex(ts["a"]["y"], f"triple[{i}].a.y"),
                                mac=_parse_field_hex(ts["a"]["mac"], f"triple[{i}].a.mac"),
                            )
                        )
                        auth_tb.append(
                            AuthenticatedShare(
                                x=record.share.x,
                                y=_parse_field_hex(ts["b"]["y"], f"triple[{i}].b.y"),
                                mac=_parse_field_hex(ts["b"]["mac"], f"triple[{i}].b.mac"),
                            )
                        )
                        auth_tc.append(
                            AuthenticatedShare(
                                x=record.share.x,
                                y=_parse_field_hex(ts["c"]["y"], f"triple[{i}].c.y"),
                                mac=_parse_field_hex(ts["c"]["mac"], f"triple[{i}].c.mac"),
                            )
                        )

                    state: DistributedParticipantState | AuthenticatedParticipantState = AuthenticatedParticipantState(
                        validator_x=record.share.x,
                        secret_share=AuthenticatedShare(x=record.share.x, y=s_y, mac=s_mac),
                        r_share=AuthenticatedShare(x=record.share.x, y=r_y, mac=r_mac),
                        alpha_share=MACKeyShare(x=record.share.x, alpha_share=alpha_val),
                        available_indices=req.available_indices,
                        triple_a=auth_ta,
                        triple_b=auth_tb,
                        triple_c=auth_tc,
                    )
                else:
                    # Semi-honest mode — validate all field elements
                    r_share = _parse_field_hex(req.r_share_y, "r_share_y")
                    triple_a = [
                        _parse_field_hex(ts.get("a", "0"), f"triple[{i}].a") for i, ts in enumerate(req.triple_shares)
                    ]
                    triple_b = [
                        _parse_field_hex(ts.get("b", "0"), f"triple[{i}].b") for i, ts in enumerate(req.triple_shares)
                    ]
                    triple_c = [
                        _parse_field_hex(ts.get("c", "0"), f"triple[{i}].c") for i, ts in enumerate(req.triple_shares)
                    ]

                    state = DistributedParticipantState(
                        validator_x=record.share.x,
                        secret_share_y=index_share_y,
                        r_share_y=r_share,
                        available_indices=req.available_indices,
                        triple_a=triple_a,
                        triple_b=triple_b,
                        triple_c=triple_c,
                    )
            except (ValueError, TypeError, KeyError) as e:
                log.warning("mpc_init_parse_error", error=str(e), session_id=req.session_id)
                raise HTTPException(status_code=400, detail="Invalid MPC init data format")

            with _participant_lock:
                # Evict oldest if at capacity
                if len(_participant_states) >= _MAX_PARTICIPANT_STATES:
                    _cleanup_stale_participants_locked()
                if len(_participant_states) >= _MAX_PARTICIPANT_STATES:
                    raise HTTPException(status_code=503, detail="Too many active MPC sessions")
                _participant_states[req.session_id] = state
                _participant_created[req.session_id] = _time.monotonic()

        return MPCInitResponse(
            session_id=req.session_id,
            accepted=True,
        )

    @app.post("/v1/mpc/round1", response_model=MPCRound1Response)
    async def mpc_round1(req: MPCRound1Request, request: Request) -> MPCRound1Response:
        """Accept a Round 1 message for a multiplication gate."""
        await validate_signed_request(request, _get_validator_hotkeys())
        d_val = _parse_field_hex(req.d_value, "d_value")
        e_val = _parse_field_hex(req.e_value, "e_value")
        msg = Round1Message(
            validator_x=req.validator_x,
            d_value=d_val,
            e_value=e_val,
        )
        ok = _mpc.submit_round1(req.session_id, req.gate_idx, msg)
        return MPCRound1Response(
            session_id=req.session_id,
            gate_idx=req.gate_idx,
            accepted=ok,
        )

    @app.post("/v1/mpc/compute_gate", response_model=MPCComputeGateResponse)
    async def mpc_compute_gate(req: MPCComputeGateRequest, request: Request) -> MPCComputeGateResponse:
        """Compute this validator's (d_i, e_i) for a multiplication gate."""
        await validate_signed_request(request, _get_validator_hotkeys())

        # Reject if session has been aborted
        session = _mpc.get_session(req.session_id)
        if session is not None and session.status == SessionStatus.FAILED:
            raise HTTPException(status_code=409, detail="Session aborted")

        with _participant_lock:
            state = _participant_states.get(req.session_id)
        if state is None:
            raise HTTPException(status_code=404, detail="No participant state for this session")

        prev_d = _parse_field_hex(req.prev_opened_d, "prev_opened_d") if req.prev_opened_d else None
        prev_e = _parse_field_hex(req.prev_opened_e, "prev_opened_e") if req.prev_opened_e else None

        try:
            if isinstance(state, AuthenticatedParticipantState):
                # Finalize previous gate if we have opened values
                if prev_d is not None and prev_e is not None and req.gate_idx > 0:
                    state.finalize_gate(prev_d, prev_e)
                d_i, e_i, d_mac, e_mac = state.compute_gate(req.gate_idx, prev_d, prev_e)
                return MPCComputeGateResponse(
                    session_id=req.session_id,
                    gate_idx=req.gate_idx,
                    d_value=hex(d_i),
                    e_value=hex(e_i),
                    d_mac=hex(d_mac),
                    e_mac=hex(e_mac),
                )
            else:
                d_i, e_i = state.compute_gate(req.gate_idx, prev_d, prev_e)
                return MPCComputeGateResponse(
                    session_id=req.session_id,
                    gate_idx=req.gate_idx,
                    d_value=hex(d_i),
                    e_value=hex(e_i),
                )
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

    @app.post("/v1/mpc/finalize", response_model=MPCFinalizeResponse)
    async def mpc_finalize(req: MPCFinalizeRequest, request: Request) -> MPCFinalizeResponse:
        """Compute and return this validator's final output share z_i.

        Called by the coordinator after the last gate's (d, e) are opened.
        Each peer computes z_i locally using only its own triple shares
        and the publicly opened d, e values. The coordinator never sees
        the peer's raw triple shares.
        """
        await validate_signed_request(request, _get_validator_hotkeys())

        with _participant_lock:
            state = _participant_states.get(req.session_id)
        if state is None:
            raise HTTPException(status_code=404, detail="No participant state for this session")

        last_d = _parse_field_hex(req.last_opened_d, "last_opened_d")
        last_e = _parse_field_hex(req.last_opened_e, "last_opened_e")

        try:
            if isinstance(state, DistributedParticipantState):
                z_i = state.compute_output_share(last_d, last_e)
            elif isinstance(state, AuthenticatedParticipantState):
                state.finalize_gate(last_d, last_e)
                out = state.get_output_share()
                if out is None:
                    raise HTTPException(status_code=500, detail="No output share")
                z_i = out.y
            else:
                raise HTTPException(status_code=400, detail="Unknown participant state type")
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

        return MPCFinalizeResponse(
            session_id=req.session_id,
            z_share=hex(z_i),
        )

    @app.post("/v1/mpc/result", response_model=MPCResultResponse)
    async def mpc_result(req: MPCResultRequest, request: Request) -> MPCResultResponse:
        """Accept the coordinator's final MPC result broadcast."""
        await validate_signed_request(request, _get_validator_hotkeys())
        result = MPCResult(
            available=req.available,
            participating_validators=req.participating_validators,
        )
        if not _mpc.set_result(req.session_id, result):
            log.warning(
                "mpc_result_rejected",
                session_id=req.session_id,
                signal_id=req.signal_id,
                reason="session not found or result already set",
            )
            return MPCResultResponse(
                session_id=req.session_id,
                acknowledged=False,
            )

        log.info(
            "mpc_result_received",
            session_id=req.session_id,
            signal_id=req.signal_id,
            available=req.available,
        )

        # Clean up participant state
        with _participant_lock:
            _participant_states.pop(req.session_id, None)
            _participant_created.pop(req.session_id, None)

        return MPCResultResponse(
            session_id=req.session_id,
            acknowledged=True,
        )

    @app.post("/v1/mpc/abort", response_model=MPCAbortResponse)
    async def mpc_abort(req: MPCAbortRequest, request: Request) -> MPCAbortResponse:
        """Accept an abort notification from the coordinator.

        When a validator detects MAC verification failure during an
        authenticated MPC session, the coordinator broadcasts an abort
        to all participants. Each participant marks the session as FAILED
        and cleans up participant state.
        """
        await validate_signed_request(request, _get_validator_hotkeys())
        session = _mpc.get_session(req.session_id)
        if session is None:
            return MPCAbortResponse(session_id=req.session_id, acknowledged=False)

        # Mark session as failed
        with _mpc._lock:
            session.status = SessionStatus.FAILED
        log.warning(
            "mpc_abort_received",
            session_id=req.session_id,
            reason=req.reason,
            gate_idx=req.gate_idx,
            offending_x=req.offending_validator_x,
        )

        # Clean up participant state
        with _participant_lock:
            _participant_states.pop(req.session_id, None)
            _participant_created.pop(req.session_id, None)

        return MPCAbortResponse(session_id=req.session_id, acknowledged=True)

    # ------------------------------------------------------------------
    # Masked polynomial membership endpoints (O(log k)-round protocol)
    # ------------------------------------------------------------------
    #
    # Coordinator drives peers through init -> rounds -> finalize_mask
    # -> reveal. Each peer's MembershipPeerState lives in
    # _membership_states keyed by session_id and is wiped after reveal
    # or on TTL expiry. Authentication is the standard signed-request
    # middleware used by the sequential protocol.

    from djinn_validator.core.mpc_membership import (
        MembershipOpenedPower,
        MembershipRoundOp,
    )

    def _cleanup_stale_membership_locked() -> int:
        now = _time.monotonic()
        stale = [sid for sid, ts in _membership_created.items() if now - ts > _PARTICIPANT_TTL]
        for sid in stale:
            _membership_states.pop(sid, None)
            _membership_created.pop(sid, None)
        if stale:
            log.info("membership_state_cleanup", evicted=len(stale))
        return len(stale)

    # Throttle cleanup sweeps so we don't hold the lock on every single
    # request. At most once per _MEMBERSHIP_CLEANUP_INTERVAL seconds, any
    # inbound membership request triggers a TTL sweep — this guarantees
    # abandoned sessions get swept even when we're nowhere near capacity,
    # while keeping the per-request cost to a dict lookup + time check.
    _MEMBERSHIP_CLEANUP_INTERVAL = 60.0
    _membership_last_cleanup = [0.0]  # list for mutability inside closure

    def _maybe_cleanup_stale_membership() -> None:
        now = _time.monotonic()
        if now - _membership_last_cleanup[0] < _MEMBERSHIP_CLEANUP_INTERVAL:
            return
        with _participant_lock:
            if now - _membership_last_cleanup[0] < _MEMBERSHIP_CLEANUP_INTERVAL:
                return  # another thread beat us to it
            _membership_last_cleanup[0] = now
            _cleanup_stale_membership_locked()

    @app.post("/v1/mpc/membership/init", response_model=MembershipInitResponse)
    async def mpc_membership_init(
        req: MembershipInitRequest,
        request: Request,
    ) -> MembershipInitResponse:
        """Initialize a membership session on this peer.

        Loads the peer's Beaver triple shares, mask share, and initial
        secret share. The secret share is this validator's Shamir share
        of the signal's real index, already held locally — the
        coordinator does NOT transmit it. Only triples and the mask
        share (generated freshly per purchase) are sent over the wire.
        """
        await validate_signed_request(request, _get_validator_hotkeys())
        _maybe_cleanup_stale_membership()

        _validate_signal_id_path(req.signal_id)

        # Locate this validator's share for the signal
        record = share_store.get(req.signal_id)
        if record is None:
            raise HTTPException(
                status_code=404,
                detail="Signal not found on this validator",
            )

        # The index-share (not the AES key share) is what MPC operates on.
        if not record.encrypted_index_share or len(record.encrypted_index_share) == 0:
            raise HTTPException(
                status_code=400,
                detail="Signal has no index share; cannot participate in membership MPC",
            )
        index_share_y = int.from_bytes(record.encrypted_index_share, "big")

        if record.share.x not in req.participant_xs:
            raise HTTPException(
                status_code=400,
                detail=f"This validator x={record.share.x} not in participant set",
            )

        try:
            triple_a = [_parse_field_hex(h, "triple_a") for h in req.triple_a]
            triple_b = [_parse_field_hex(h, "triple_b") for h in req.triple_b]
            triple_c = [_parse_field_hex(h, "triple_c") for h in req.triple_c]
            mask_share = _parse_field_hex(req.mask_share, "mask_share")
        except (ValueError, TypeError) as e:
            raise HTTPException(status_code=400, detail=f"Invalid hex: {e}")

        if not (len(triple_a) == len(triple_b) == len(triple_c)):
            raise HTTPException(
                status_code=400,
                detail="triple_a/b/c must have equal length",
            )
        if len(triple_a) < 1:
            raise HTTPException(
                status_code=400,
                detail="need at least one triple",
            )

        state = MembershipPeerState(
            validator_x=record.share.x,
            threshold=req.threshold,
            available_indices=list(req.available_indices),
            triple_a=triple_a,
            triple_b=triple_b,
            triple_c=triple_c,
            mask_share=mask_share,
        )
        state.set_initial_secret_share(index_share_y)

        with _participant_lock:
            if len(_membership_states) >= _MAX_PARTICIPANT_STATES:
                _cleanup_stale_membership_locked()
            if len(_membership_states) >= _MAX_PARTICIPANT_STATES:
                raise HTTPException(
                    status_code=503,
                    detail="Too many active membership sessions",
                )
            _membership_states[req.session_id] = state
            _membership_created[req.session_id] = _time.monotonic()

        return MembershipInitResponse(
            session_id=req.session_id,
            accepted=True,
        )

    @app.post("/v1/mpc/membership/round", response_model=MembershipRoundResponse)
    async def mpc_membership_round(
        req: MembershipRoundRequest,
        request: Request,
    ) -> MembershipRoundResponse:
        """Run one power-tree round on this peer.

        The request carries:
          - ``prev_opened``: opened d, e from the previous round (empty
            for round 0). Finalized first to populate new power shares.
          - ``ops``: multiplications to compute in this round. Each op
            produces a (d_share, e_share) pair to return.
        """
        await validate_signed_request(request, _get_validator_hotkeys())
        _maybe_cleanup_stale_membership()

        with _participant_lock:
            state = _membership_states.get(req.session_id)
        if state is None:
            raise HTTPException(
                status_code=404,
                detail="No membership state for this session",
            )

        try:
            opened = [
                MembershipOpenedPower(
                    gate_idx=op.gate_idx,
                    target_pow=op.target_pow,
                    opened_d=_parse_field_hex(op.opened_d, "opened_d"),
                    opened_e=_parse_field_hex(op.opened_e, "opened_e"),
                )
                for op in req.prev_opened
            ]
            if opened:
                state.finalize_round(opened)

            ops = [
                MembershipRoundOp(
                    gate_idx=op.gate_idx,
                    a_pow=op.a_pow,
                    b_pow=op.b_pow,
                )
                for op in req.ops
            ]
            de_shares = state.compute_round(ops)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

        return MembershipRoundResponse(
            session_id=req.session_id,
            round_idx=req.round_idx,
            op_shares=[
                MembershipRoundOpShare(
                    gate_idx=g,
                    d_share=hex(d),
                    e_share=hex(e),
                )
                for (g, d, e) in de_shares
            ],
        )

    @app.post(
        "/v1/mpc/membership/finalize_mask",
        response_model=MembershipFinalizeMaskResponse,
    )
    async def mpc_membership_finalize_mask(
        req: MembershipFinalizeMaskRequest,
        request: Request,
    ) -> MembershipFinalizeMaskResponse:
        """Consume the last opened d, e, compute [q] = [p(r)], then produce
        the (d, e) shares for the mask multiply [s] * [q]."""
        await validate_signed_request(request, _get_validator_hotkeys())
        _maybe_cleanup_stale_membership()

        with _participant_lock:
            state = _membership_states.get(req.session_id)
        if state is None:
            raise HTTPException(
                status_code=404,
                detail="No membership state for this session",
            )

        try:
            if req.final_opened:
                state.finalize_round(
                    [
                        MembershipOpenedPower(
                            gate_idx=op.gate_idx,
                            target_pow=op.target_pow,
                            opened_d=_parse_field_hex(op.opened_d, "opened_d"),
                            opened_e=_parse_field_hex(op.opened_e, "opened_e"),
                        )
                        for op in req.final_opened
                    ]
                )

            coefficients = [_parse_field_hex(c, "coefficient") for c in req.coefficients]
            state.compute_q_share(coefficients)
            d_i, e_i = state.compute_mask_multiply_shares()
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

        return MembershipFinalizeMaskResponse(
            session_id=req.session_id,
            mask_d_share=hex(d_i),
            mask_e_share=hex(e_i),
        )

    @app.post(
        "/v1/mpc/membership/reveal",
        response_model=MembershipRevealResponse,
    )
    async def mpc_membership_reveal(
        req: MembershipRevealRequest,
        request: Request,
    ) -> MembershipRevealResponse:
        """Final step: compute this peer's share of [s * p(r)].

        The coordinator interpolates all peers' shares to reveal the
        masked product. Zero means ``r in A``; anything else means it
        isn't (and reveals nothing beyond that bit).

        Note: session state is NOT dropped until after compute_product_share
        succeeds, so a malformed or transient failure returns 4xx without
        making retries impossible (coordinator would otherwise be stuck
        with one participant permanently missing).
        """
        await validate_signed_request(request, _get_validator_hotkeys())
        _maybe_cleanup_stale_membership()

        with _participant_lock:
            state = _membership_states.get(req.session_id)
        if state is None:
            raise HTTPException(
                status_code=404,
                detail="No membership state for this session",
            )

        try:
            opened_d = _parse_field_hex(req.mask_opened_d, "mask_opened_d")
            opened_e = _parse_field_hex(req.mask_opened_e, "mask_opened_e")
            product_share = state.compute_product_share(opened_d, opened_e)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

        # Compute succeeded — now it's safe to drop the session state.
        # A subsequent identical call from a retry will 404 because the
        # session is gone; but a retry due to a transient network error
        # between our 200 and the coordinator would still benefit because
        # the coordinator would have received product_share the first time.
        with _participant_lock:
            _membership_states.pop(req.session_id, None)
            _membership_created.pop(req.session_id, None)

        return MembershipRevealResponse(
            session_id=req.session_id,
            product_share=hex(product_share),
        )

    @app.get("/v1/mpc/{session_id}/status", response_model=MPCSessionStatusResponse)
    async def mpc_status(session_id: str) -> MPCSessionStatusResponse:
        """Check the status of an MPC session."""
        _validate_signal_id_path(session_id)
        session = _mpc.get_session(session_id)
        if session is None:
            raise HTTPException(status_code=404, detail="MPC session not found")

        # Count Round 1 responses for the first gate as a proxy
        responded = len(session.round1_messages.get(0, []))

        return MPCSessionStatusResponse(
            session_id=session_id,
            status=session.status.name.lower(),
            available=session.result.available if session.result else None,
            participants_responded=responded,
            total_participants=len(session.participant_xs),
        )

    # ------------------------------------------------------------------
    # Batch settlement MPC (task #9)
    #
    # These endpoints are the HTTP runtime for distributed batch
    # settlement. When DJINN_FF_BATCH_SETTLEMENT_HTTP is OFF, they all
    # return 503 after auth. The correctness oracle is
    # ``simulate_distributed_batch_settle`` in
    # djinn_validator.core.mpc_batch_settlement; the HTTP handlers
    # drive the same BatchSession state machine that
    # ``_drive_batch_session_across_peers`` uses in the unit tests, so
    # any HTTP-level divergence shows up immediately in the
    # end-to-end tests.
    # ------------------------------------------------------------------

    from djinn_validator.core.mpc_batch_settlement import (
        BatchSession as _BatchSession,
    )
    from djinn_validator.core.mpc_batch_settlement import (
        BatchSessionError as _BatchSessionError,
    )

    # Each session entry: (BatchSession, last_used_ts_monotonic, asyncio.Lock).
    # The per-session asyncio.Lock serializes mutations against concurrent
    # compute_gate/accumulate/open calls — without it, a coordinator retry
    # storm could pass the "already accumulated" check non-atomically and
    # double-count or corrupt the running sum (codex audit 2026-04-15).
    _batch_sessions: dict[str, tuple[_BatchSession, float, asyncio.Lock]] = {}
    _batch_sessions_lock = _threading.Lock()
    _BATCH_SESSION_TTL = 600  # 10 minutes
    _MAX_BATCH_SESSIONS = 100

    def _cleanup_stale_batch_sessions_locked() -> int:
        now = _time.monotonic()
        stale = [sid for sid, entry in _batch_sessions.items() if now - entry[1] > _BATCH_SESSION_TTL]
        for sid in stale:
            _batch_sessions.pop(sid, None)
        if stale:
            log.info("batch_session_cleanup", evicted=len(stale))
        return len(stale)

    def _resolve_my_validator_x(signal_id: str, allowed_xs: list[int]) -> int | None:
        """Find this peer's share x-coordinate for a signal, restricted to
        the set of x-coords the coordinator declared in the batch init.

        Returns None if no matching share record exists. If the peer
        happens to hold multiple shares for the signal (single-machine
        testnet), picks the first one whose x is in ``allowed_xs``.
        """
        records = share_store.get_all(signal_id)
        for rec in records:
            if rec.share.x in allowed_xs:
                return rec.share.x
        return None

    def _load_my_index_share_y(signal_id: str, my_x: int) -> int | None:
        """Return this peer's realIndex Shamir share y-value at x=my_x.

        The batch MPC evaluates gain_vector[realIndex] at the secret
        Shamir-shared index, so the secret for polynomial evaluation
        is the INDEX share (encrypted_index_share), NOT the AES key
        share (rec.share.y). Using the key share by mistake feeds a
        random ~2^254 field element into Q(s), producing field-element
        garbage in the ~10^75 range — the exact P0-01 symptom observed
        on-chain (see MAINNET_BLOCKERS.md and djinn-notes.md).

        Returns None if no matching record exists or the record lacks
        an index share (legacy signals created before index-share
        persistence landed).
        """
        for rec in share_store.get_all(signal_id):
            if rec.share.x == my_x:
                if not rec.encrypted_index_share:
                    return None
                return int.from_bytes(rec.encrypted_index_share, "big")
        return None

    @app.post("/v1/mpc/batch/init", response_model=MPCBatchInitResponse)
    async def mpc_batch_init(
        req: MPCBatchInitRequest,
        request: Request,
    ) -> MPCBatchInitResponse:
        """Accept a batch settlement session invitation.

        The coordinator transmits the ordered list of purchases plus
        per-purchase Beaver triples. Each peer looks up its own
        Shamir share of ``realIndex`` for each purchase's signal_id
        in its local share_store; the coordinator never transmits
        shares (that would defeat MPC).
        """
        await validate_signed_request(request, _get_validator_hotkeys())

        from djinn_validator.feature_flags import flags as _ff

        if not _ff.batch_settlement_http:
            raise HTTPException(
                status_code=503,
                detail="Batch settlement HTTP runtime is disabled on this validator",
            )

        if not req.purchases:
            raise HTTPException(status_code=400, detail="batch must be non-empty")

        # Determine this peer's validator_x by looking at the FIRST
        # purchase's share record. Every subsequent purchase must
        # also have a share at the same x for this peer or the batch
        # cannot be accumulated (Shamir linearity only holds at one
        # fixed x per party).
        first_signal = req.purchases[0].signal_id
        my_x = _resolve_my_validator_x(first_signal, req.participant_xs)
        if my_x is None:
            raise HTTPException(
                status_code=404,
                detail=f"no share for {first_signal} matching participant_xs {req.participant_xs}",
            )

        # Build the state machine. Size + participant-set errors map
        # to 400 (the coordinator mis-configured the batch).
        try:
            session = _BatchSession(
                session_id=req.session_id,
                validator_x=my_x,
                participant_xs=req.participant_xs,
                threshold=req.threshold,
            )
        except _BatchSessionError as e:
            raise HTTPException(status_code=400, detail=str(e))

        # Convert the request-shape purchases into the state-machine
        # tuples. Each triple-share dict is {"a": hex, "b": hex, "c": hex}
        # with this peer's y-coordinate for that gate's Beaver triple.
        purchase_tuples: list[tuple[str, list[int], int, list[tuple[int, int, int]]]] = []
        for spec in req.purchases:
            try:
                gain_vector = [int(g, 16) for g in spec.gain_vector]
            except ValueError as e:
                raise HTTPException(
                    status_code=400,
                    detail=f"{spec.signal_id}: invalid hex in gain_vector: {e}",
                )
            triple_tuples: list[tuple[int, int, int]] = []
            for ts in spec.triple_shares:
                try:
                    triple_tuples.append(
                        (
                            int(ts["a"], 16),
                            int(ts["b"], 16),
                            int(ts["c"], 16),
                        )
                    )
                except (KeyError, ValueError, TypeError) as e:
                    raise HTTPException(
                        status_code=400,
                        detail=f"{spec.signal_id}: malformed triple_shares: {e}",
                    )
            purchase_tuples.append((spec.signal_id, gain_vector, spec.purchase_id, triple_tuples))

        def _share_lookup(sig_id: str) -> int | None:
            return _load_my_index_share_y(sig_id, my_x)

        try:
            session.accept_init(purchase_tuples, _share_lookup)
        except _BatchSessionError as e:
            raise HTTPException(status_code=400, detail=str(e))

        with _batch_sessions_lock:
            if len(_batch_sessions) >= _MAX_BATCH_SESSIONS:
                _cleanup_stale_batch_sessions_locked()
            if len(_batch_sessions) >= _MAX_BATCH_SESSIONS:
                raise HTTPException(
                    status_code=503,
                    detail="Too many active batch sessions",
                )
            # v1692: init is now IDEMPOTENT. Pre-fix, a network blip on the
            # coordinator's first init request triggered _peer_request's
            # _PEER_RETRIES=2 → server processed both, second saw existing
            # session and 409'd → coordinator treated as protocol_failed →
            # whole shadow_settle aborted. UID 0 logs at 11:22:07 caught this
            # exact pattern: init session XYZ created at 11:21:47, retry init
            # for same session XYZ failed with 409 at 11:22:07.
            # If the same session_id is re-init'd with matching parameters,
            # treat as success — the protocol state is already correct.
            existing = _batch_sessions.get(req.session_id)
            if existing is not None:
                _existing_session = existing[0]
                # Compare critical params: same participant set + threshold +
                # purchase count. If anything differs, it's a real conflict.
                if (
                    _existing_session.validator_x == my_x
                    and tuple(_existing_session.participant_xs) == tuple(req.participant_xs)
                    and _existing_session.threshold == req.threshold
                    and _existing_session.purchase_count == len(req.purchases)
                ):
                    log.info(
                        "batch_session_init_idempotent",
                        session_id=req.session_id,
                        my_x=my_x,
                        purchase_count=len(req.purchases),
                        msg="re-init for existing session with matching params; treat as success",
                    )
                    return MPCBatchInitResponse(
                        session_id=req.session_id,
                        accepted=True,
                        purchase_count=len(req.purchases),
                    )
                raise HTTPException(
                    status_code=409,
                    detail=f"session {req.session_id} already exists with different parameters",
                )
            _batch_sessions[req.session_id] = (
                session,
                _time.monotonic(),
                asyncio.Lock(),
            )

        log.info(
            "batch_session_init",
            session_id=req.session_id,
            my_x=my_x,
            participant_xs=req.participant_xs,
            purchase_count=len(req.purchases),
        )
        return MPCBatchInitResponse(
            session_id=req.session_id,
            accepted=True,
            purchase_count=len(req.purchases),
        )

    def _get_batch_session_or_404(
        session_id: str,
    ) -> tuple[_BatchSession, asyncio.Lock]:
        """Return (session, per-session lock).

        Enforces TTL on every lookup (codex audit 2026-04-15: previously
        TTL was only checked on init/capacity pressure, so partial state
        could persist indefinitely after a coordinator failure). Refreshes
        last_used_ts so an actively-driven session stays alive.
        """
        now = _time.monotonic()
        with _batch_sessions_lock:
            entry = _batch_sessions.get(session_id)
            if entry is not None:
                session, ts, lock = entry
                if now - ts > _BATCH_SESSION_TTL:
                    _batch_sessions.pop(session_id, None)
                    entry = None
                else:
                    # Touch: reset TTL so the session survives long
                    # multi-purchase batches.
                    _batch_sessions[session_id] = (session, now, lock)
        if entry is None:
            raise HTTPException(
                status_code=404,
                detail=f"batch session {session_id} not found",
            )
        return entry[0], entry[2]

    @app.post(
        "/v1/mpc/batch/compute_gate",
        response_model=MPCBatchComputeGateResponse,
    )
    async def mpc_batch_compute_gate(
        req: MPCBatchComputeGateRequest,
        request: Request,
    ) -> MPCBatchComputeGateResponse:
        """Compute one gate in one purchase's power chain."""
        await validate_signed_request(request, _get_validator_hotkeys())

        from djinn_validator.feature_flags import flags as _ff

        if not _ff.batch_settlement_http:
            raise HTTPException(
                status_code=503,
                detail="Batch settlement HTTP runtime is disabled on this validator",
            )

        session, _slock = _get_batch_session_or_404(req.session_id)

        prev_d = int(req.prev_opened_d, 16) if req.prev_opened_d else None
        prev_e = int(req.prev_opened_e, 16) if req.prev_opened_e else None

        async with _slock:
            try:
                d_i, e_i = session.compute_gate(
                    req.purchase_idx,
                    req.gate_idx,
                    prev_d,
                    prev_e,
                )
            except _BatchSessionError as e:
                raise HTTPException(status_code=400, detail=str(e))

        return MPCBatchComputeGateResponse(
            session_id=req.session_id,
            purchase_idx=req.purchase_idx,
            gate_idx=req.gate_idx,
            d_value=hex(d_i),
            e_value=hex(e_i),
        )

    @app.post(
        "/v1/mpc/batch/accumulate",
        response_model=MPCBatchAccumulateResponse,
    )
    async def mpc_batch_accumulate(
        req: MPCBatchAccumulateRequest,
        request: Request,
    ) -> MPCBatchAccumulateResponse:
        """Fold a completed purchase's output share into the peer's
        running batch sum share.

        The per-purchase share MUST stay inside the peer — it is
        never returned from this endpoint. Leaking it would let the
        coordinator reverse-engineer that purchase's realIndex.
        """
        await validate_signed_request(request, _get_validator_hotkeys())

        from djinn_validator.feature_flags import flags as _ff

        if not _ff.batch_settlement_http:
            raise HTTPException(
                status_code=503,
                detail="Batch settlement HTTP runtime is disabled on this validator",
            )

        session, _slock = _get_batch_session_or_404(req.session_id)

        try:
            last_d = int(req.last_opened_d, 16) if req.last_opened_d else None
            last_e = int(req.last_opened_e, 16) if req.last_opened_e else None
        except ValueError as e:
            raise HTTPException(status_code=400, detail=f"invalid hex: {e}")

        async with _slock:
            try:
                session.accumulate(req.purchase_idx, last_d, last_e)
            except _BatchSessionError as e:
                raise HTTPException(status_code=400, detail=str(e))

            return MPCBatchAccumulateResponse(
                session_id=req.session_id,
                purchase_idx=req.purchase_idx,
                accumulated=True,
                purchases_accumulated_so_far=session.purchases_accumulated,
            )

    @app.post("/v1/mpc/batch/open", response_model=MPCBatchOpenResponse)
    async def mpc_batch_open(
        req: MPCBatchOpenRequest,
        request: Request,
    ) -> MPCBatchOpenResponse:
        """Return the peer's accumulated sum share for the batch.

        This is the ONLY endpoint that exposes a value derived from
        per-purchase MPC output. The returned scalar is a Shamir share
        of the batch total; the coordinator needs ``threshold`` such
        shares to reconstruct the final total score change.
        """
        await validate_signed_request(request, _get_validator_hotkeys())

        from djinn_validator.feature_flags import flags as _ff

        if not _ff.batch_settlement_http:
            raise HTTPException(
                status_code=503,
                detail="Batch settlement HTTP runtime is disabled on this validator",
            )

        session, _slock = _get_batch_session_or_404(req.session_id)

        async with _slock:
            try:
                # v1693: open() is now safe to call after already-opened
                # because BatchSession returns the same cached result. The
                # legacy "Drop the session from the registry after opening"
                # behavior would have made retries 404; we keep the session
                # alive for one extra TTL window so coordinator-side retries
                # on transport blip get the same result.
                sum_share, public_c0 = session.open()
            except _BatchSessionError as e:
                raise HTTPException(status_code=400, detail=str(e))

        log.info(
            "batch_session_opened",
            session_id=req.session_id,
            validator_x=session.validator_x,
            purchase_count=session.purchase_count,
        )
        return MPCBatchOpenResponse(
            session_id=req.session_id,
            sum_share=hex(sum_share),
            purchases_accumulated=session.purchase_count,
            validator_x=session.validator_x,
            public_c_0_sum=hex(public_c0),
        )

    # ------------------------------------------------------------------
    # Signal share info (for peer share discovery)
    # ------------------------------------------------------------------

    @app.get("/v1/signal/{signal_id}/share_info", response_model=ShareInfoResponse)
    async def share_info(signal_id: str, request: Request) -> ShareInfoResponse:
        """Return this validator's share x-coordinate for MPC peer discovery.

        No auth required: share_x is a public evaluation point, not a secret.
        Peers need this to set up correct Lagrange interpolation coordinates.
        """
        _validate_signal_id_path(signal_id)

        record = share_store.get(signal_id)
        if record is None:
            raise HTTPException(status_code=404, detail="Signal not found on this validator")

        return ShareInfoResponse(
            signal_id=signal_id,
            share_x=record.share.x,
            shamir_threshold=record.shamir_threshold,
        )

    @app.get("/v1/signal/{signal_id}/mpc_diagnostic")
    async def mpc_diagnostic(signal_id: str, request: Request) -> dict:
        """Diagnostic endpoint: check MPC readiness for a signal.

        AUTHENTICATION REQUIRED. Each call triggers ~8 outbound
        requests to peer validators and leaks internal peer discovery
        state, circuit breaker state, and per-peer share_x values.
        Exposing this unauthenticated was both an information
        disclosure and an amplification vector (1 inbound → N
        outbound). Only registered SN103 validators may call it.
        In BT_NETWORK=test mode the check is a no-op.
        """
        if os.environ.get("BT_NETWORK", "").lower() in ("finney", "mainnet"):
            try:
                await validate_signed_request(request, _get_validator_hotkeys())
            except HTTPException:
                log.warning(
                    "mpc_diagnostic_unauthenticated_attempt",
                    signal_id=signal_id[:40],
                    src_ip=request.client.host if request.client else "unknown",
                )
                raise

        _validate_signal_id_path(signal_id)
        record = share_store.get(signal_id)
        if record is None:
            return {"error": "Signal not found", "signal_id": signal_id}

        has_index_share = bool(record.encrypted_index_share and len(record.encrypted_index_share) > 0)
        my_x = record.share.x
        threshold = record.shamir_threshold

        # Peer discovery
        peers = _orchestrator._get_peer_validators()
        peer_summary = [{"uid": p["uid"], "ip": p["ip"], "port": p["port"]} for p in peers[:20]]

        # Circuit breaker state
        breaker_state = {}
        for uid, breaker in list(_orchestrator._peer_breakers.items())[:20]:
            breaker_state[uid] = {
                "allow_request": breaker.allow_request(),
                "failure_count": breaker._failure_count,
                "state": breaker._state.name if hasattr(breaker._state, "name") else str(breaker._state),
            }

        # Version cache (may not exist on all versions)
        version_cache = dict(list(getattr(_orchestrator, "_peer_versions", {}).items())[:20])

        # Try share_x lookup on known good peers (unsigned)
        share_x_results = {}
        for peer in peers[:5]:
            try:
                resp = await _orchestrator._http.get(
                    f"{peer['url']}/v1/signal/{signal_id}/share_info",
                    timeout=5.0,
                )
                if resp.status_code == 200:
                    data = resp.json()
                    share_x_results[peer["uid"]] = {"share_x": data.get("share_x"), "status": 200}
                else:
                    share_x_results[peer["uid"]] = {"status": resp.status_code}
            except Exception as e:
                share_x_results[peer["uid"]] = {"error": str(e)[:200]}

        # Test signed GET and POST to peers that hold shares
        import time as _t_diag

        signed_test = {}
        peers_with_shares = [
            p for p in peers if p["uid"] in share_x_results and share_x_results[p["uid"]].get("status") == 200
        ]
        for peer in peers_with_shares[:3]:
            tests = {}
            # GET test (signed, but share_info doesn't validate auth)
            t0 = _t_diag.monotonic()
            try:
                resp = await _orchestrator._peer_request(
                    "get",
                    f"{peer['url']}/v1/signal/{signal_id}/share_info",
                    peer_uid=peer["uid"],
                )
                tests["get"] = {"status": resp.status_code, "ms": round((_t_diag.monotonic() - t0) * 1000)}
            except Exception as e:
                tests["get"] = {"error": str(e)[:100], "ms": round((_t_diag.monotonic() - t0) * 1000)}

            # POST test (signed, mpc_init validates auth)
            # Send a minimal init payload to test the full signed POST flow
            sx = share_x_results[peer["uid"]].get("share_x", 1)
            import secrets as _secrets_diag

            test_init = {
                "session_id": f"diag-test-{_secrets_diag.token_hex(4)}",
                "signal_id": signal_id,
                "available_indices": [1],
                "coordinator_x": my_x,
                "participant_xs": [my_x, sx],
                "threshold": 2,
            }
            t0 = _t_diag.monotonic()
            try:
                resp = await _orchestrator._peer_request(
                    "post",
                    f"{peer['url']}/v1/mpc/init",
                    peer_uid=peer["uid"],
                    json=test_init,
                )
                body = resp.text[:200]
                tests["post_init"] = {
                    "status": resp.status_code,
                    "ms": round((_t_diag.monotonic() - t0) * 1000),
                    "body": body,
                }
            except Exception as e:
                tests["post_init"] = {"error": str(e)[:200], "ms": round((_t_diag.monotonic() - t0) * 1000)}

            signed_test[peer["uid"]] = tests

        # Check signing capability
        signing_ok = False
        signing_error = None
        if neuron is not None and hasattr(neuron, "wallet") and neuron.wallet is not None:
            try:
                from djinn_validator.api.middleware import create_signed_headers

                test_headers = create_signed_headers("/v1/test", b"test", neuron.wallet)
                signing_ok = "X-Signature" in test_headers
            except Exception as e:
                signing_error = str(e)[:200]
        else:
            signing_error = "no_wallet"

        return {
            "signal_id": signal_id[:40],
            "my_x": my_x,
            "threshold": threshold,
            "has_index_share": has_index_share,
            "my_uid": neuron.uid if neuron else None,
            "peers_discovered": len(peers),
            "peer_sample": peer_summary,
            "breaker_state": breaker_state,
            "version_cache": version_cache,
            "share_x_lookup": share_x_results,
            "signed_request_test": signed_test,
            "signing_ok": signing_ok,
            "signing_error": signing_error,
        }

    # ------------------------------------------------------------------
    # OT network endpoints (distributed triple generation)
    # ------------------------------------------------------------------

    from djinn_validator.core.ot_network import (
        DEFAULT_DH_GROUP,
        DHGroup,
        OTTripleGenState,
        serialize_dh_public_key,
    )

    _ot_states: dict[str, OTTripleGenState] = {}
    _ot_created: dict[str, float] = {}  # session_id -> monotonic timestamp
    _ot_lock = _threading.Lock()

    _OT_TTL = 180  # seconds before stale OT states are cleaned up
    _MAX_OT_STATES = 200

    def _cleanup_stale_ot_states_locked() -> int:
        """Remove OT states older than _OT_TTL. Caller holds _ot_lock."""
        now = _time.monotonic()
        stale = [sid for sid, ts in _ot_created.items() if now - ts > _OT_TTL]
        for sid in stale:
            _ot_states.pop(sid, None)
            _ot_created.pop(sid, None)
        if stale:
            log.info("ot_state_cleanup", evicted=len(stale))
        return len(stale)

    # Maximum allowed bit length for DH group primes (4096 bits)
    _MAX_DH_PRIME_BITS = 4096

    def _resolve_ot_params(
        field_prime_hex: str | None,
        dh_prime_hex: str | None,
    ) -> tuple[int, DHGroup]:
        """Resolve OT parameters from request, falling back to defaults."""
        if field_prime_hex:
            try:
                fp = int(field_prime_hex, 16)
            except (ValueError, TypeError):
                raise HTTPException(status_code=400, detail="Invalid hex for field_prime")
            if fp < 2 or fp >= 2**256:
                raise HTTPException(status_code=400, detail="field_prime out of range")
        else:
            fp = BN254_PRIME

        if dh_prime_hex:
            try:
                dhp = int(dh_prime_hex, 16)
            except (ValueError, TypeError):
                raise HTTPException(status_code=400, detail="Invalid hex for dh_prime")
            if dhp < 2 or dhp.bit_length() > _MAX_DH_PRIME_BITS:
                raise HTTPException(status_code=400, detail="dh_prime out of range")
            bl = (dhp.bit_length() + 7) // 8
            dh_group = DHGroup(prime=dhp, generator=2, byte_length=bl)
        else:
            dh_group = DEFAULT_DH_GROUP
        return fp, dh_group

    @app.post("/v1/mpc/ot/setup", response_model=OTSetupResponse)
    async def ot_setup(req: OTSetupRequest, request: Request) -> OTSetupResponse:
        """Initialize distributed triple generation on this peer."""
        await validate_signed_request(request, _get_validator_hotkeys())

        with _ot_lock:
            if req.session_id in _ot_states:
                state = _ot_states[req.session_id]
                return OTSetupResponse(
                    session_id=req.session_id,
                    accepted=True,
                    sender_public_keys={
                        str(t): serialize_dh_public_key(pk, state.dh_group)
                        for t, pk in state.get_sender_public_keys().items()
                    },
                )

            # Evict stale OT states before creating new ones
            if len(_ot_states) >= _MAX_OT_STATES:
                _cleanup_stale_ot_states_locked()
            if len(_ot_states) >= _MAX_OT_STATES:
                raise HTTPException(status_code=503, detail="Too many active OT sessions")

            fp, dh_group = _resolve_ot_params(req.field_prime, req.dh_prime)

        # Initialize outside the lock (CPU-intensive modexp work)
        state = OTTripleGenState(
            session_id=req.session_id,
            party_role="peer",
            n_triples=req.n_triples,
            x_coords=req.x_coords,
            threshold=req.threshold,
            prime=fp,
            dh_group=dh_group,
        )
        await asyncio.get_event_loop().run_in_executor(None, state.initialize)

        with _ot_lock:
            _ot_states[req.session_id] = state
            _ot_created[req.session_id] = _time.monotonic()

        return OTSetupResponse(
            session_id=req.session_id,
            accepted=True,
            sender_public_keys={
                str(t): serialize_dh_public_key(pk, state.dh_group) for t, pk in state.get_sender_public_keys().items()
            },
        )

    @app.post("/v1/mpc/ot/choices", response_model=OTChoicesResponse)
    async def ot_choices(req: OTChoicesRequest, request: Request) -> OTChoicesResponse:
        """Generate and exchange OT choice commitments."""
        await validate_signed_request(request, _get_validator_hotkeys())

        with _ot_lock:
            state = _ot_states.get(req.session_id)
        if state is None:
            raise HTTPException(status_code=404, detail="OT session not found")

        from djinn_validator.core.ot_network import (
            OTReceiverNotReadyError,
            deserialize_dh_public_key,
            serialize_choices,
        )

        # Deserialize peer's sender public keys
        peer_pks = {int(t): deserialize_dh_public_key(pk_hex) for t, pk_hex in req.peer_sender_pks.items()}

        # Generate this party's receiver choices.
        # Run in thread pool to avoid blocking the event loop (receiver
        # initialization may need to wait for background modexp thread).
        try:
            our_choices = await asyncio.get_event_loop().run_in_executor(
                None,
                state.generate_receiver_choices,
                peer_pks,
            )
        except OTReceiverNotReadyError as exc:
            raise HTTPException(
                status_code=503,
                detail=str(exc),
                headers={"Retry-After": "2"},
            )

        return OTChoicesResponse(
            session_id=req.session_id,
            choices={str(t): serialize_choices(c) for t, c in our_choices.items()},
        )

    @app.post("/v1/mpc/ot/transfers", response_model=OTTransfersResponse)
    async def ot_transfers(req: OTTransfersRequest, request: Request) -> OTTransfersResponse:
        """Process peer choices and return encrypted OT transfers."""
        await validate_signed_request(request, _get_validator_hotkeys())

        with _ot_lock:
            state = _ot_states.get(req.session_id)
        if state is None:
            raise HTTPException(status_code=404, detail="OT session not found")

        from djinn_validator.core.ot_network import (
            deserialize_choices,
            serialize_transfers,
        )

        # Deserialize peer's choices for our sender instances
        peer_choices_deserialized = {int(t): deserialize_choices(c) for t, c in req.peer_choices.items()}

        # Process: encrypt OT messages using our sender states
        # Run in thread pool to avoid blocking the event loop
        # (process_sender_choices does CPU-heavy modexp via ProcessPool)
        transfers, sender_shares = await asyncio.get_event_loop().run_in_executor(
            None,
            state.process_sender_choices,
            peer_choices_deserialized,
        )

        return OTTransfersResponse(
            session_id=req.session_id,
            transfers={str(t): serialize_transfers(pairs) for t, pairs in transfers.items()},
            sender_shares={str(t): hex(s) for t, s in sender_shares.items()},
        )

    @app.post("/v1/mpc/ot/complete", response_model=OTCompleteResponse)
    async def ot_complete(req: OTCompleteRequest, request: Request) -> OTCompleteResponse:
        """Decrypt peer transfers and compute Shamir polynomial evaluations."""
        await validate_signed_request(request, _get_validator_hotkeys())

        with _ot_lock:
            state = _ot_states.get(req.session_id)
        if state is None:
            raise HTTPException(status_code=404, detail="OT session not found")

        from djinn_validator.core.ot_network import deserialize_transfers

        # Decrypt the peer's encrypted transfers (where this party is receiver)
        peer_transfers_deserialized = {int(t): deserialize_transfers(pairs) for t, pairs in req.peer_transfers.items()}
        receiver_shares = state.decrypt_receiver_transfers(peer_transfers_deserialized)

        # Parse this party's own sender shares
        own_sender_shares = {int(t): int(s, 16) for t, s in req.own_sender_shares.items()}

        # Accumulate cross-term shares into c values
        state.accumulate_ot_shares(own_sender_shares, receiver_shares)

        # Compute Shamir polynomial evaluations for distribution
        state.compute_shamir_evaluations()

        return OTCompleteResponse(
            session_id=req.session_id,
            completed=True,
        )

    @app.post("/v1/mpc/ot/shares", response_model=OTSharesResponse)
    async def ot_shares(req: OTSharesRequest, request: Request) -> OTSharesResponse:
        """Serve Shamir polynomial evaluations to a requesting party.

        Each party contacts the OT peer directly to get the peer's partial
        triple shares.  This prevents the coordinator from seeing the peer's
        polynomial evaluations.
        """
        await validate_signed_request(request, _get_validator_hotkeys())

        with _ot_lock:
            state = _ot_states.get(req.session_id)
        if state is None:
            raise HTTPException(status_code=404, detail="OT session not found")

        shares = state.get_shamir_shares_for_party(req.party_x)
        if shares is None:
            raise HTTPException(
                status_code=425,
                detail="OT triple generation not yet complete",
            )

        return OTSharesResponse(
            session_id=req.session_id,
            triple_shares=[{k: hex(v) for k, v in ts.items()} for ts in shares],
        )

    # ------------------------------------------------------------------
    # External Notary Session Assignment (for browser extension provers)
    # ------------------------------------------------------------------

    @app.post("/v1/notary/session", response_model=NotarySessionResponse)
    async def notary_session(request: Request) -> NotarySessionResponse:
        """Assign a random notary miner for an external prover.

        Auth: burn-gate. Caller provides three headers:
          - X-Coldkey: SS58 coldkey address (the burn_alpha extrinsic signer)
          - X-Burn-Tx: hex tx hash of the burn_alpha extrinsic
          - X-Signature: sr25519 signature of the tx hash bytes by the coldkey

        The validator verifies the signature, looks up the burn on-chain
        (cached), and confirms >= 1 alpha burned on SN103 within 30 days.

        Dedup (optional request body):
          - exclude_miners: hotkeys to skip (previously assigned)
          - exclude_ips: IPs to skip (same operator dedup)
        """
        import time as _time
        import uuid as _uuid

        from djinn_validator.api import burn_gate
        from djinn_validator.core.challenges import assign_peer_notary, discover_peer_notaries

        # Extract burn-gate headers
        coldkey_ss58 = request.headers.get("x-coldkey", "")
        tx_hash = request.headers.get("x-burn-tx", "")
        signature = request.headers.get("x-signature", "")

        if not coldkey_ss58 or not tx_hash or not signature:
            NOTARY_SESSIONS_ASSIGNED.labels(status="auth_failed").inc()
            raise HTTPException(
                status_code=401,
                detail="Missing required headers: X-Coldkey, X-Burn-Tx, X-Signature",
            )

        # Get substrate connection for on-chain verification
        substrate = None
        if neuron and neuron.subtensor:
            substrate = neuron.subtensor.substrate

        valid, error = burn_gate.authenticate_request(
            coldkey_ss58,
            tx_hash,
            signature,
            substrate,
        )
        if not valid:
            # On-chain lookup failed (likely pruned). Try peer validators.
            if neuron and neuron.metagraph is not None:
                from djinn_validator.core.mpc_orchestrator import _is_public_ip

                peer_urls = []
                peer_hotkeys: set[str] = set()
                mg = neuron.metagraph
                for uid in range(mg.n.item()):
                    if not mg.validator_permit[uid].item():
                        continue
                    if uid == neuron.uid:
                        continue
                    axon = mg.axons[uid]
                    if axon.ip and axon.ip != "0.0.0.0" and _is_public_ip(axon.ip):
                        peer_urls.append(f"http://{axon.ip}:{axon.port}")
                        peer_hotkeys.add(mg.hotkeys[uid])
                if peer_urls:
                    self_hotkey = ""
                    try:
                        self_hotkey = neuron.wallet.hotkey.ss58_address
                    except Exception:
                        pass
                    valid, _ = await burn_gate.verify_burn_via_peers(
                        tx_hash,
                        coldkey_ss58,
                        peer_urls,
                        allowed_hotkeys=peer_hotkeys,
                        self_hotkey=self_hotkey,
                    )
            if not valid:
                NOTARY_SESSIONS_ASSIGNED.labels(status="auth_failed").inc()
                raise HTTPException(status_code=401, detail=error)

        exclude_hotkeys: set[str] = set()
        exclude_coldkeys: set[str] = set()

        # Per-call dedup: exclude previously assigned miners/IPs from this batch
        try:
            body = await request.json()
        except Exception:
            body = {}
        exclude_ips: set[str] = set()
        if isinstance(body, dict):
            for hk in body.get("exclude_miners") or []:
                if isinstance(hk, str):
                    exclude_hotkeys.add(hk)
            for ip in body.get("exclude_ips") or []:
                if isinstance(ip, str):
                    exclude_ips.add(ip)

        # Build miner axon list from metagraph
        if not neuron:
            NOTARY_SESSIONS_ASSIGNED.labels(status="no_miners").inc()
            raise HTTPException(status_code=503, detail="Validator not connected to network")

        miner_uids = neuron.get_miner_uids()
        if not miner_uids:
            NOTARY_SESSIONS_ASSIGNED.labels(status="no_miners").inc()
            raise HTTPException(status_code=503, detail="No miners available")

        axons = []
        for uid in miner_uids:
            try:
                axon = neuron.get_axon_info(uid)
                ip = axon.get("ip", "")
                port = axon.get("port", 0)
                hotkey = axon.get("hotkey", "")
                if not ip or not port or ip in ("0.0.0.0", "127.0.0.1"):
                    continue
                # Exclude by IP (dedup across calls in a batch)
                if ip in exclude_ips:
                    continue
                # Exclude by hotkey
                if hotkey in exclude_hotkeys:
                    continue
                # Exclude by coldkey (look up from metagraph)
                if exclude_coldkeys and neuron.metagraph is not None:
                    coldkey = neuron.metagraph.coldkeys[uid]
                    if coldkey in exclude_coldkeys:
                        continue
                axons.append({"uid": uid, "ip": ip, "port": port, "hotkey": hotkey})
            except (IndexError, KeyError, AttributeError):
                continue

        if not axons:
            NOTARY_SESSIONS_ASSIGNED.labels(status="no_miners").inc()
            raise HTTPException(status_code=503, detail="No reachable miners (after exclusions)")

        # Pre-filter to miners with PROVEN notary capability. Browser
        # extension provers are fragile (no retry/fallback), so we only
        # assign miners that have:
        # 1. A verified proactive proof (TLSNotary binary works)
        # 2. At least one successful attestation challenge (MPC completes)
        # This eliminates miners with broken sidecars, version mismatches,
        # or stale MPC state that cause "connection is closed" errors.
        if scorer is not None:
            proven_uids: set[int] = set()
            capable_uids: set[int] = set()
            for a in axons:
                m = scorer.get(a["uid"])
                if m is None:
                    continue
                if m.notary_capable:
                    capable_uids.add(a["uid"])
                if m.proactive_proof_verified and m.attestations_valid > 0:
                    proven_uids.add(a["uid"])
            if proven_uids:
                axons_for_discovery = [a for a in axons if a["uid"] in proven_uids]
                log.info(
                    "notary_session_prefilter",
                    total_axons=len(axons),
                    proven=len(proven_uids),
                    capable=len(capable_uids),
                )
            elif capable_uids:
                axons_for_discovery = [a for a in axons if a["uid"] in capable_uids]
                log.info(
                    "notary_session_prefilter_fallback_capable",
                    total_axons=len(axons),
                    capable=len(capable_uids),
                )
            else:
                axons_for_discovery = axons
        else:
            axons_for_discovery = axons

        # Discover which miners have live notary sidecars
        async with httpx.AsyncClient() as client:
            peer_notaries = await discover_peer_notaries(client, axons_for_discovery)

        if not peer_notaries:
            NOTARY_SESSIONS_ASSIGNED.labels(status="no_miners").inc()
            raise HTTPException(status_code=503, detail="No miners with active notary sidecars")

        # Filter out miners whose circuit breaker is open (repeated failures)
        breaker_open_uids: set[int] = set()
        for pn in peer_notaries:
            breaker = _get_miner_breaker(pn.uid)
            if not breaker.allow_request():
                breaker_open_uids.add(pn.uid)
        if breaker_open_uids:
            log.info(
                "notary_session_breaker_filtered",
                filtered_uids=sorted(breaker_open_uids),
                remaining=len(peer_notaries) - len(breaker_open_uids),
            )

        # Rank notaries by proven MPC reliability instead of random selection.
        # The scorer tracks which miners successfully complete attestation
        # challenges and notary duties, so proven miners float to the top.
        candidate_uids = [pn.uid for pn in peer_notaries]
        ranked_uids = scorer.rank_notary_candidates(candidate_uids) if scorer is not None else None

        chosen = assign_peer_notary(
            prover_uid=-1,
            notaries=peer_notaries,
            exclude_uids=breaker_open_uids or None,
            ranked_uids=ranked_uids,
        )
        if chosen is None:
            NOTARY_SESSIONS_ASSIGNED.labels(status="no_miners").inc()
            raise HTTPException(status_code=503, detail="No eligible notary miners")

        # Look up the reliability score for logging and response metadata
        chosen_score = 0.0
        chosen_tier = "unknown"
        if ranked_uids:
            for uid, score in ranked_uids:
                if uid == chosen.uid:
                    chosen_score = round(score, 4)
                    m = scorer.get(uid) if scorer is not None else None
                    if m and m.attestations_valid > 0:
                        chosen_tier = "proven"
                    elif m and m.ema_uptime > 0.001:
                        chosen_tier = "unproven"
                    break

        session_id = _uuid.uuid4().hex[:16]
        expires_at = int(_time.time()) + 120  # 2 minute window to connect

        NOTARY_SESSIONS_ASSIGNED.labels(status="ok").inc()
        log.info(
            "notary_session_assigned",
            session_id=session_id,
            miner_uid=chosen.uid,
            miner_ip=chosen.ip,
            tier=chosen_tier,
            reliability=chosen_score,
            caller_coldkey=coldkey_ss58[:16] + "...",
            excluded_hotkeys=len(exclude_hotkeys),
            breaker_filtered=len(breaker_open_uids),
        )

        return NotarySessionResponse(
            session_id=session_id,
            miner_ip=chosen.ip,
            miner_port=chosen.port,
            miner_hotkey=next((a["hotkey"] for a in axons if a["uid"] == chosen.uid), ""),
            notary_public_key=chosen.pubkey_hex,
            expires_at=expires_at,
            miner_uid=chosen.uid,
            tier=chosen_tier,
            reliability_score=chosen_score,
        )

    @app.post("/v1/notary/session/feedback", dependencies=[_admin_auth])
    async def notary_session_feedback(request: Request) -> dict:
        """Report success or failure of a notary session back to the validator.

        Feeds the circuit breaker so future assignments skip broken miners.
        Requires admin auth to prevent unauthenticated users from sending
        fake feedback that trips circuit breakers.

        Body: {"session_id": str, "miner_uid": int, "success": bool, "error": str}
        """
        try:
            body = await request.json()
        except Exception:
            raise HTTPException(status_code=400, detail="JSON body required")

        miner_uid = body.get("miner_uid")
        success = body.get("success", False)
        error_msg = body.get("error", "")

        if not isinstance(miner_uid, int) or miner_uid < 0:
            raise HTTPException(status_code=400, detail="miner_uid (int >= 0) required")

        breaker = _get_miner_breaker(miner_uid)
        if success:
            breaker.record_success()
        else:
            breaker.record_failure()

        log.info(
            "notary_session_feedback",
            miner_uid=miner_uid,
            success=success,
            error=error_msg[:200] if error_msg else "",
            breaker_state=breaker.state.value,
            session_id=body.get("session_id", ""),
        )
        return {"ok": True}

    @app.get("/v1/burn/verify")
    async def burn_verify(
        request: Request,
        tx_hash: str = "",
        coldkey: str = "",
        recipient_hotkey: str = "",
    ) -> dict:
        """Check if a burn tx is in this validator's verified cache.

        Used by peer validators when their local chain lookup fails (pruned
        block state). Returns a hotkey-signed verification result so the
        caller can cryptographically authenticate the responding validator
        and reject MITM'd or unregistered-peer responses.

        ``recipient_hotkey`` (P1-25, 2026-04-18): the requesting validator's
        own hotkey. When present we fold it into the signed payload so the
        response cannot be replayed to a different requesting validator.
        Empty string preserves the legacy unbound payload for old callers.

        P1-26 (2026-04-18): source IP must map to a registered-validator
        axon in the metagraph (or localhost for self-probe). Fail-open when
        metagraph is unavailable. Escape hatch env
        ``DJINN_BURN_GATE_ALLOW_ANY_IP=1`` restores pre-P1-26 behavior.
        """
        from djinn_validator.api.burn_gate import (
            BURN_WINDOW_SECONDS,
            _cache_get,
            is_allowed_peer_ip,
            sign_peer_response,
        )

        request_ip = request.client.host if request.client else ""
        if not is_allowed_peer_ip(neuron, request_ip):
            raise HTTPException(
                status_code=403,
                detail="peer endpoint restricted to registered validator IPs",
            )

        if not tx_hash or not coldkey:
            raise HTTPException(status_code=400, detail="tx_hash and coldkey required")

        cached = _cache_get(tx_hash)
        if cached is None or not cached.get("valid"):
            return {"valid": False}

        if cached.get("coldkey") != coldkey:
            return {"valid": False}

        import time as _time

        age = _time.time() - cached.get("block_ts", 0)
        if age > BURN_WINDOW_SECONDS:
            return {"valid": False}

        if neuron is None or not getattr(neuron, "wallet", None):
            # No wallet available to sign. Return unsigned; caller will
            # reject when strict verification is on (burn_gate default).
            return {
                "valid": True,
                "amount": cached.get("amount", 0),
                "block_ts": cached.get("block_ts", 0),
            }

        return sign_peer_response(
            tx_hash=tx_hash,
            coldkey=coldkey,
            valid=True,
            amount=cached.get("amount", 0),
            block_ts=cached.get("block_ts", 0),
            signer_hotkey=neuron.wallet.hotkey.ss58_address,
            wallet=neuron.wallet,
            recipient_hotkey=recipient_hotkey,
        )

    # ------------------------------------------------------------------
    # Check-Odds: buyer fetches live odds through the validator
    # ------------------------------------------------------------------

    @app.post("/v1/signal/{signal_id}/check-odds", response_model=CheckOddsResponse)
    async def check_odds(signal_id: str, req: CheckOddsRequest) -> CheckOddsResponse:
        """Fetch current odds for BPA/WPA pricing at purchase time.

        Fans out to miners via /v1/check, filters results by the buyer's
        sportsbooks, and computes BPA (best price available) and WPA
        (worst price available) per line. Falls back to stored line
        prices when no miners are reachable.
        """
        import json as _json
        import random as _random

        from djinn_validator.api.middleware import create_signed_headers

        _validate_signal_id_path(signal_id)

        signal_meta = outcome_attestor.get_signal(signal_id)
        if signal_meta is None:
            raise HTTPException(status_code=404, detail="Signal not registered on this validator")

        # Convert stored ParsedPick lines to CandidateLine dicts for the miner
        candidate_lines: list[dict] = []
        for i, pick in enumerate(signal_meta.lines):
            candidate_lines.append(
                {
                    "index": i + 1,
                    "sport": signal_meta.sport,
                    "event_id": signal_meta.event_id,
                    "home_team": signal_meta.home_team,
                    "away_team": signal_meta.away_team,
                    "market": pick.market,
                    "line": pick.line,
                    "side": pick.team if pick.market in ("spreads", "h2h") else pick.side,
                }
            )

        # Fan out to miners (same pattern as /v1/check)
        MAX_CHECK_MINERS = 10
        miner_data: list[dict] = []
        miner_source = "stored"

        if neuron:
            miner_uids = neuron.get_miner_uids()
            if miner_uids:
                _random.shuffle(miner_uids)
                targets: list[tuple[int, str]] = []
                for uid in miner_uids:
                    axon = neuron.get_axon_info(uid)
                    ip = axon.get("ip", "")
                    port = axon.get("port", 0)
                    if not ip or not port or ip in ("0.0.0.0", "127.0.0.1"):
                        continue
                    targets.append((uid, f"http://{ip}:{port}/v1/check"))
                    if len(targets) >= MAX_CHECK_MINERS:
                        break

                if targets:
                    body = _json.dumps({"lines": candidate_lines}).encode()
                    auth_headers: dict[str, str] = {}
                    if neuron.wallet:
                        auth_headers = create_signed_headers("/v1/check", body, neuron.wallet)

                    async def _query(uid: int, url: str) -> tuple[int, dict | None]:
                        try:
                            async with httpx.AsyncClient() as client:
                                resp = await client.post(
                                    url,
                                    content=body,
                                    headers={"Content-Type": "application/json", **auth_headers},
                                    timeout=10.0,
                                )
                            if resp.status_code != 200:
                                return (uid, None)
                            data = resp.json()
                            if data.get("api_error") and not data.get("available_indices"):
                                return (uid, None)
                            return (uid, data)
                        except Exception as e:
                            log.warning("check_odds_miner_failed", miner_uid=uid, error=str(e)[:100])
                            return (uid, None)

                    results = await asyncio.gather(*[_query(uid, url) for uid, url in targets])
                    for _uid, data in results:
                        if data and data.get("results"):
                            miner_data.append(data)

        # Merge miner results: union of bookmaker data per line index
        merged_by_index: dict[int, list[dict]] = {}
        if miner_data:
            miner_source = "miner"
            for data in miner_data:
                for lr in data.get("results", []):
                    idx = lr.get("index")
                    if idx is None:
                        continue
                    if idx not in merged_by_index:
                        merged_by_index[idx] = []
                    for bm in lr.get("bookmakers", []):
                        merged_by_index[idx].append(bm)

        # Normalize buyer_books to lowercase for matching
        buyer_books_lower = {b.lower() for b in req.buyer_books}

        # Read bpa_mode from on-chain signal. BPA (best-price aggregation)
        # and WPA (worst-price aggregation) modes agree on executability;
        # they differ only in which price gets locked in as the payout
        # odds. See project_bpa_wpa_design.md in the Djinn memory for the
        # canonical model:
        #   - The genius's committed price is a LIMIT ORDER. A line is
        #     executable iff at least one of the buyer's configured books
        #     currently offers price >= committed, regardless of mode.
        #   - BPA mode: lockedOdds = max(prices_at_buyer_books). The buyer
        #     is credited at the best book.
        #   - WPA mode: lockedOdds = min(p for p in prices_at_buyer_books
        #     if p >= committed). Books below the genius's committed limit
        #     are filtered out first, then the min of the surviving set is
        #     taken. The buyer is credited at the worst-but-still-above-
        #     committed book.
        # The genius never covers spread — they're only on the hook for
        # outcome variance via the SLA multiplier on collateral.
        bpa_mode = False
        if chain_client:
            try:
                on_chain = await chain_client.get_signal(int(signal_id))
                bpa_mode = bool(on_chain.get("bpaMode", False))
            except Exception:
                pass

        from djinn_validator.utils.odds_logic import (
            american_to_decimal as _american_to_decimal,
        )
        from djinn_validator.utils.odds_logic import (
            compute_line_odds as _compute_line_odds,
        )

        # Build odds response per line.
        #
        # A line is ONLY executable when the current market at the buyer's
        # books still honors the odds the genius committed to at creation
        # time. This is the "per-buyer availability" promise: the buyer
        # should never end up paying for a signal whose underlying line
        # has moved against them.
        #
        # The executability + BPA/WPA logic is in djinn_validator.utils
        # .odds_logic so it can be unit-tested in isolation from the
        # miner fan-out and signal registration plumbing that surrounds
        # this endpoint.
        odds_list: list[LineOdds] = []
        n_live = 0
        n_price_dropped = 0
        for i, pick in enumerate(signal_meta.lines):
            idx = i + 1
            bm_results = merged_by_index.get(idx, [])

            # Filter to buyer's books
            filtered = [bm for bm in bm_results if bm.get("bookmaker", "").lower() in buyer_books_lower]

            committed_decimal = _american_to_decimal(pick.odds) if pick.odds else 0.0

            if filtered:
                prices = [bm["odds"] for bm in filtered if bm.get("odds")]
                if prices:
                    n_live += 1
                    result = _compute_line_odds(prices, committed_decimal)
                    if not result.executable:
                        n_price_dropped += 1
                    per_book = [
                        BookPrice(
                            bookmaker=str(bm.get("bookmaker", "")),
                            odds=float(bm["odds"]),
                        )
                        for bm in filtered
                        if bm.get("odds") and bm.get("bookmaker")
                    ]
                    odds_list.append(
                        LineOdds(
                            index=idx,
                            bpa=result.bpa,
                            wpa=result.wpa,
                            executable=result.executable,
                            per_book=per_book,
                        )
                    )
                    continue

            # Fallback: no miner data for this line at the buyer's books.
            # Use the stored price, but mark executable only when we are
            # ALREADY in the stored-price fallback mode (i.e. miners are
            # unreachable across the board). Otherwise treat as unavailable
            # because the specific line wasn't returned by any miner.
            stored_price = pick.odds or 0
            if stored_price and stored_price != 0:
                dec = _american_to_decimal(stored_price)
                odds_list.append(
                    LineOdds(
                        index=idx,
                        bpa=dec,
                        wpa=dec,
                        executable=miner_source == "stored",
                    )
                )
            else:
                odds_list.append(
                    LineOdds(
                        index=idx,
                        bpa=0,
                        wpa=0,
                        executable=False,
                    )
                )

        if miner_source == "stored":
            log.warning(
                "check_odds_fallback",
                signal_id=signal_id,
                msg="No miners reachable, using stored line prices",
            )

        if n_price_dropped > 0:
            log.info(
                "check_odds_price_filtered",
                signal_id=signal_id,
                mode="bpa" if bpa_mode else "wpa",
                lines_live=n_live,
                lines_below_committed=n_price_dropped,
            )

        return CheckOddsResponse(
            signal_id=signal_id,
            line_count=len(signal_meta.lines),
            odds=odds_list,
            bpa_mode=bpa_mode,
            source=miner_source,
        )

    # ------------------------------------------------------------------
    # Buyer Preferences
    # ------------------------------------------------------------------

    def _verify_preferences_signature(address: str, signature: str) -> None:
        """Verify an EIP-191 signature over 'djinn:preferences:{address}' recovers to *address*."""
        if not signature:
            raise HTTPException(
                status_code=401,
                detail=f"signature is required. Sign 'djinn:preferences:{address}' with your wallet.",
            )
        try:
            from eth_account import Account as EthAccount
            from eth_account.messages import encode_defunct

            msg = encode_defunct(text=f"djinn:preferences:{address.lower()}")
            recovered = EthAccount.recover_message(msg, signature=signature)
            if recovered.lower() != address.lower():
                raise HTTPException(
                    status_code=403,
                    detail=f"Signature does not match address (recovered {recovered})",
                )
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Invalid signature: {e}")

    @app.put("/v1/preferences/{address}")
    async def set_preferences(address: str, req: SetPreferencesRequest):
        """Store buyer preferences (encrypted)."""
        if not address.startswith("0x") or len(address) != 42:
            raise HTTPException(status_code=400, detail="Invalid address format")

        _verify_preferences_signature(address, req.signature)

        if outcome_attestor._db:
            outcome_attestor._db.execute(
                """INSERT OR REPLACE INTO buyer_preferences
                   (address, books_json, encrypted_data, updated_at)
                   VALUES (?, ?, ?, ?)""",
                (address.lower(), json.dumps(req.books), req.encrypted_data, time.time()),
            )
            outcome_attestor._db.commit()

        return {"address": address, "stored": True}

    @app.get("/v1/preferences/{address}", response_model=PreferencesResponse)
    async def get_preferences(address: str, sig: str = ""):
        """Retrieve buyer preferences."""
        if not address.startswith("0x") or len(address) != 42:
            raise HTTPException(status_code=400, detail="Invalid address format")

        _verify_preferences_signature(address, sig)

        if outcome_attestor._db:
            row = outcome_attestor._db.execute(
                "SELECT books_json, encrypted_data FROM buyer_preferences WHERE address = ?",
                (address.lower(),),
            ).fetchone()
            if row:
                return PreferencesResponse(
                    address=address,
                    books=json.loads(row[0]) if row[0] else [],
                    encrypted_data=row[1] or "",
                )

        return PreferencesResponse(address=address)

    # ------------------------------------------------------------------
    # Canonical Odds (validator-served, decoupled from The Odds API)
    # ------------------------------------------------------------------

    @app.post("/v1/odds/canonical", response_model=CanonicalOddsResponse)
    async def canonical_odds(req: CanonicalOddsRequest) -> CanonicalOddsResponse:
        """Return live odds in the canonical schema.

        Gated by DJINN_FF_CANONICAL_ODDS. With the flag OFF, returns an
        empty list and feature_flag_enabled=False so the client knows
        to fall back to legacy /api/odds.

        With the flag ON, the validator fans out to healthy miners
        via /v1/odds/canonical, runs the median-based consensus
        reducer from canonical_consensus.py, and returns the
        per-(event, market, side, bookmaker) consensus observations.
        """
        import json as _json
        import random as _random
        import time as _time

        from djinn_validator.api.middleware import create_signed_headers
        from djinn_validator.feature_flags import flags as _ff
        from djinn_validator.utils.canonical_consensus import (
            reduce_observations_to_consensus,
        )

        served_at_ms = int(_time.time() * 1000)

        if not _ff.canonical_odds:
            return CanonicalOddsResponse(
                sport=req.sport,
                market=req.market,
                requested_bookmakers=req.bookmakers,
                observations=[],
                miner_count=0,
                served_at_ms=served_at_ms,
                feature_flag_enabled=False,
            )

        # Fan out to miners. Reuses the same pattern as /v1/check
        # (MAX_CANONICAL_MINERS capped, random-shuffled for load
        # distribution, 10s per-miner timeout).
        MAX_CANONICAL_MINERS = 10
        miner_observation_lists: list[list[dict]] = []
        targets: list[tuple[int, str]] = []

        if neuron:
            miner_uids = neuron.get_miner_uids()
            if miner_uids:
                miner_uids_copy = list(miner_uids)
                _random.shuffle(miner_uids_copy)
                for uid in miner_uids_copy:
                    axon = neuron.get_axon_info(uid)
                    ip = axon.get("ip", "")
                    port = axon.get("port", 0)
                    if not ip or not port or ip in ("0.0.0.0", "127.0.0.1"):
                        continue
                    targets.append((uid, f"http://{ip}:{port}/v1/odds/canonical"))
                    if len(targets) >= MAX_CANONICAL_MINERS:
                        break

                if targets:
                    body = _json.dumps(
                        {
                            "sport": req.sport,
                            "markets": ["h2h", "spreads", "totals"],
                        }
                    ).encode()
                    auth_headers: dict[str, str] = {}
                    if neuron.wallet:
                        auth_headers = create_signed_headers(
                            "/v1/odds/canonical",
                            body,
                            neuron.wallet,
                        )

                    async def _query_miner_canonical(uid: int, url: str) -> list[dict]:
                        try:
                            async with httpx.AsyncClient() as client:
                                resp = await client.post(
                                    url,
                                    content=body,
                                    headers={
                                        "Content-Type": "application/json",
                                        **auth_headers,
                                    },
                                    timeout=10.0,
                                )
                            if resp.status_code != 200:
                                return []
                            data = resp.json()
                            return data.get("observations", []) or []
                        except Exception as e:
                            log.debug(
                                "canonical_miner_query_failed",
                                miner_uid=uid,
                                error=str(e)[:100],
                            )
                            return []

                    miner_observation_lists = list(
                        await asyncio.gather(*(_query_miner_canonical(uid, url) for uid, url in targets))
                    )

        # Run the consensus reducer over all miner observations.
        consensus = reduce_observations_to_consensus(
            miner_observation_lists,
            min_miners=1,
        )

        # Score each miner on distance from consensus and feed the
        # observe-only canonical agreement metric on their MinerMetrics
        # record. NOT yet fed into the weight formula — the tuning for
        # that ships in a follow-up once we've gathered enough live
        # data to pick a coefficient. See DEV-043.
        if scorer is not None and consensus:
            try:
                from djinn_validator.utils.canonical_consensus import (
                    miner_distance_scores,
                )

                distances = miner_distance_scores(
                    miner_observation_lists,
                    consensus,
                )
                # ``targets`` was populated above with (uid, url) pairs
                # in the same order as miner_observation_lists.
                for (uid, _url), distance in zip(targets, distances):
                    scorer.record_canonical_distance(uid, distance)
            except Exception as _score_err:
                log.warning(
                    "canonical_distance_score_failed",
                    error=str(_score_err)[:200],
                )

        # Optional client-side filter: if the caller restricted
        # bookmakers, drop groups whose bookmaker is not in that set.
        if req.bookmakers:
            allowed = {b.lower() for b in req.bookmakers}
            consensus = [c for c in consensus if c.bookmaker.lower() in allowed]

        # Optional market filter: map the caller's requested market
        # to the canonical form and keep only matches.
        canonical_market = {
            "moneyline": "moneyline",
            "h2h": "moneyline",
            "spread": "spread",
            "spreads": "spread",
            "total": "total",
            "totals": "total",
        }.get(req.market, req.market)
        if req.market:
            consensus = [c for c in consensus if c.market == canonical_market]

        observations = [
            CanonicalOddsObservation(
                event_id=c.event_id,
                sport=c.sport,
                home_team=c.home_team,
                away_team=c.away_team,
                commence_time_ms=c.commence_time_ms,
                market=c.market,
                side=c.side,
                decimal_price=c.consensus_price,
                line=c.consensus_line,
                bookmaker=c.bookmaker,
                fetched_at_ms=c.latest_fetched_at_ms,
                source=",".join(c.sources) if c.sources else "consensus",
            )
            for c in consensus
        ]

        miner_count = sum(1 for lst in miner_observation_lists if lst)

        log.info(
            "canonical_odds_consensus",
            sport=req.sport,
            market=req.market,
            observation_count=len(observations),
            miner_count=miner_count,
            requested_bookmakers=len(req.bookmakers),
        )

        return CanonicalOddsResponse(
            sport=req.sport,
            market=req.market,
            requested_bookmakers=req.bookmakers,
            observations=observations,
            miner_count=miner_count,
            served_at_ms=served_at_ms,
            feature_flag_enabled=True,
        )

    # ------------------------------------------------------------------
    # Consensus Circuit Breaker (CUSUM tracker + appeal flow)
    # ------------------------------------------------------------------

    @app.get("/v1/cb/status/{hotkey}", response_model=CircuitBreakerStatusResponse)
    async def cb_status(hotkey: str, request: Request) -> CircuitBreakerStatusResponse:
        """Query a miner's CUSUM state.

        AUTHENTICATION REQUIRED. The miner must sign for their own
        hotkey, OR another registered SN103 validator can query (for
        gossip / cross-validator scoring debate). This prevents
        competitors from enumerating which miners are at risk of
        being flagged.

        Returns the publicly-derivable fields (score, sample_count,
        flagged, threshold) plus the recent disputed query IDs that
        the miner needs to construct an appeal. Disputed query IDs
        are validator-internal identifiers; exposing them to a
        competitor would leak the validator's challenge cadence.
        """
        if not hotkey or len(hotkey) > 128:
            raise HTTPException(status_code=400, detail="Invalid hotkey")

        # AUTH: only the miner themselves OR a registered validator
        # may query. Building an allowlist that includes the miner's
        # own hotkey lets them self-monitor while keeping the data
        # private from random observers and competitors.
        #
        # In BT_NETWORK=test mode (local dev only), pass
        # allowed_hotkeys=None so validate_signed_request takes its
        # existing test-mode escape hatch and permits unauthenticated
        # requests. Production (finney/mainnet) always enforces.
        if os.environ.get("BT_NETWORK", "").lower() in ("finney", "mainnet"):
            allowed_hotkeys: set[str] | None = {hotkey}
            if neuron is not None and neuron.metagraph is not None:
                try:
                    validator_uids = neuron.get_validator_uids() if hasattr(neuron, "get_validator_uids") else []
                    for v_uid in validator_uids:
                        try:
                            allowed_hotkeys.add(neuron.metagraph.hotkeys[v_uid])
                        except Exception:
                            continue
                except Exception:
                    pass
        else:
            allowed_hotkeys = None
        try:
            await validate_signed_request(request, allowed_hotkeys)
        except HTTPException:
            log.warning(
                "cb_status_unauthenticated_attempt",
                hotkey=hotkey[:10],
                src_ip=request.client.host if request.client else "unknown",
            )
            raise

        cb = scorer._circuit_breaker if scorer else None
        if cb is None:
            return CircuitBreakerStatusResponse(
                hotkey=hotkey,
                score=0.0,
                sample_count=0,
                flagged=False,
                flagged_at=0.0,
                last_disputes=[],
                threshold=0.0,
            )
        state = cb.get_state(hotkey)
        if state is None:
            return CircuitBreakerStatusResponse(
                hotkey=hotkey,
                score=0.0,
                sample_count=0,
                flagged=False,
                flagged_at=0.0,
                last_disputes=[],
                threshold=cb.flag_threshold,
            )
        return CircuitBreakerStatusResponse(
            hotkey=hotkey,
            score=state.score,
            sample_count=state.sample_count,
            flagged=state.is_flagged(),
            flagged_at=state.flagged_at,
            last_disputes=[(qid, dev) for qid, dev in state.last_disputes],
            threshold=cb.flag_threshold,
        )

    @app.post("/v1/cb/appeal", response_model=CircuitBreakerAppealResponse)
    async def cb_appeal(
        req: CircuitBreakerAppealRequest,
        request: Request,
    ) -> CircuitBreakerAppealResponse:
        """A flagged miner submits proof to clear their flag.

        AUTHENTICATION REQUIRED. The request must be signed by the
        hotkey being appealed FOR. Without this check, anyone could
        guess query IDs and clear any flagged miner's slash. The
        signed request proves the appellant controls the hotkey
        whose flag they're clearing.

        Three operating modes, gated by DJINN_FF_APPEAL_MECHANISM:

        - flag OFF: 503 Service Unavailable. The mechanism is not
          enabled on this validator.
        - flag ON, no TLSNotary verifier wired: honor-system mode.
          Appeal succeeds if the miner is currently flagged AND has at
          least one disputed query in their history matching the
          submitted IDs. NO cryptographic verification — useful for
          testing the wire protocol and the slash-then-restore flow
          before the real verifier ships.
        - flag ON, TLSNotary verifier wired: real proof verification.
          (Not yet implemented; the wire protocol is the same.)

        Per project_consensus_circuit_breaker.md, a successful appeal
        clears the flag with reset_score=True (miner is restored to
        zero CUSUM and resumes earning weight). A failed appeal leaves
        the flag in place. The actual slash math (forward weight
        reduction) lives in the scoring loop, not here.
        """
        # AUTH FIRST: check the request signature before any other
        # logic. Doing this before the feature flag check prevents an
        # attacker from fingerprinting flag state via response codes
        # (501/503 vs 401 would otherwise reveal whether the appeal
        # mechanism is enabled on this validator).
        #
        # The request must be signed by the EXACT hotkey being
        # appealed for. allowed_hotkeys = {req.hotkey} so any other
        # signer (including other validators) is rejected. This is
        # the critical check that prevents anyone from clearing
        # someone else's flag.
        #
        # In BT_NETWORK=test mode the auth check is skipped to keep
        # local dev iteration fast. Production always enforces.
        if os.environ.get("BT_NETWORK", "").lower() in ("finney", "mainnet"):
            try:
                verified = await validate_signed_request(request, {req.hotkey})
            except HTTPException:
                log.warning(
                    "cb_appeal_unauthenticated_attempt",
                    hotkey=req.hotkey[:10],
                    src_ip=request.client.host if request.client else "unknown",
                )
                raise
            if verified != req.hotkey:
                log.warning(
                    "cb_appeal_hotkey_mismatch",
                    req_hotkey=req.hotkey[:10],
                    signer_hotkey=(verified or "")[:10],
                )
                raise HTTPException(
                    status_code=403,
                    detail="Appeal must be signed by the hotkey being appealed for",
                )

        from djinn_validator.feature_flags import flags as _ff

        if not _ff.appeal_mechanism:
            raise HTTPException(
                status_code=503,
                detail="Appeal mechanism not enabled on this validator (DJINN_FF_APPEAL_MECHANISM=false)",
            )

        cb = scorer._circuit_breaker if scorer else None
        if cb is None:
            raise HTTPException(
                status_code=503,
                detail="Circuit breaker not configured on this validator",
            )

        state = cb.get_state(req.hotkey)
        if state is None or not state.is_flagged():
            return CircuitBreakerAppealResponse(
                hotkey=req.hotkey,
                verdict="not_flagged",
                cleared=False,
                new_score=state.score if state else 0.0,
                verification_mode="honor_system",
                message="Hotkey is not currently flagged; no appeal needed.",
            )

        # Honor-system mode: accept if any of the submitted disputed
        # query IDs appear in the miner's recent_disputes buffer. This
        # proves the miner at least knows which queries are being
        # disputed (a tiny anti-spam bar). Real TLSNotary verification
        # lands in a follow-up.
        recorded_ids = {qid for qid, _ in state.last_disputes}
        matched = recorded_ids & set(req.disputed_query_ids)

        if not matched:
            log.warning(
                "cb_appeal_no_matching_disputes",
                hotkey=req.hotkey[:10],
                submitted=len(req.disputed_query_ids),
                in_record=len(recorded_ids),
            )
            return CircuitBreakerAppealResponse(
                hotkey=req.hotkey,
                verdict="denied",
                cleared=False,
                new_score=state.score,
                verification_mode="honor_system",
                message=(
                    "None of the submitted disputed_query_ids match this hotkey's "
                    "recorded disputes. Check /v1/cb/status/<hotkey> for the actual "
                    "list of recent disputes."
                ),
            )

        # In honor-system mode the appeal succeeds. Real TLSNotary
        # verification will replace this with proof.verify(declared_source).
        cleared = cb.clear_flag(
            req.hotkey,
            reason=f"appeal_honor_system matched={len(matched)} of {len(req.disputed_query_ids)}",
            reset_score=True,
        )
        new_state = cb.get_state(req.hotkey)
        log.info(
            "cb_appeal_accepted",
            hotkey=req.hotkey[:10],
            matched=len(matched),
            mode="honor_system",
        )
        return CircuitBreakerAppealResponse(
            hotkey=req.hotkey,
            verdict="honor_system_accepted",
            cleared=cleared,
            new_score=new_state.score if new_state else 0.0,
            verification_mode="honor_system",
            message=(
                f"Appeal accepted in honor-system mode ({len(matched)} matching "
                "disputes). Real TLSNotary verification lands in a follow-up commit."
            ),
        )

    # --- Sprint A Stage A-1: platform-unique routes moved off Vercel. ---
    # Odds feed, sports catalog, and debug metagraph snapshot. See
    # docs/off-vercel-sprint-a.md for the multi-stage rollout.
    from djinn_validator.core import odds_feed as _odds_feed

    @app.get("/v1/odds/{sport}")
    async def odds_upcoming(sport: str, markets: str | None = None):
        """Proxy The Odds API /v4/sports/{sport}/odds with key rotation + cache."""
        try:
            sport_ok = _odds_feed.validate_sport(sport)
            markets_ok = _odds_feed.validate_markets(markets)
        except _odds_feed._InvalidRequest as e:
            raise HTTPException(status_code=400, detail=str(e))

        try:
            data = await _odds_feed.fetch_upcoming(sport_ok, markets_ok)
        except _odds_feed._NoKeysConfigured as e:
            raise HTTPException(status_code=503, detail=str(e))
        except _odds_feed._UpstreamFailed as e:
            raise HTTPException(status_code=502, detail=str(e))
        return data

    @app.get("/v1/odds/{sport}/events/{event_id}/alt")
    async def odds_event_alt(sport: str, event_id: str):
        """Alternate spreads + totals for a specific event. Shares rotation state with /v1/odds."""
        try:
            sport_ok = _odds_feed.validate_sport(sport)
        except _odds_feed._InvalidRequest as e:
            raise HTTPException(status_code=400, detail=str(e))
        if not event_id:
            raise HTTPException(status_code=400, detail="event_id required")

        try:
            data = await _odds_feed.fetch_event_alt(sport_ok, event_id)
        except _odds_feed._NoKeysConfigured as e:
            raise HTTPException(status_code=503, detail=str(e))
        except _odds_feed._InvalidRequest as e:
            raise HTTPException(status_code=400, detail=str(e))
        except _odds_feed._UpstreamFailed as e:
            raise HTTPException(status_code=502, detail=str(e))
        return data

    @app.get("/v1/sports")
    async def sports_catalog():
        """Static list of supported sports (those with ESPN score-resolution mapping)."""
        return {
            "sports": list(_odds_feed.SPORTS_CATALOG),
            "total": len(_odds_feed.SPORTS_CATALOG),
        }

    @app.get("/v1/debug/metagraph", dependencies=[_admin_auth])
    async def debug_metagraph(request: Request):
        """Admin-auth gated snapshot of the live metagraph + peer-version probe.

        Replaces `web/app/api/debug/metagraph/route.ts` which called subtensor
        directly. The validator already holds a hot metagraph in memory, so
        this endpoint is strictly cheaper and lives where the data already is.
        """
        if neuron is None or getattr(neuron, "metagraph", None) is None:
            raise HTTPException(
                status_code=503,
                detail="metagraph not available (validator not joined to network)",
            )
        t0 = time.time()
        snap = neuron.metagraph
        synced_ms = getattr(neuron, "metagraph_synced_at_ms", None)

        nodes: list[dict[str, Any]] = []
        validators: list[dict[str, Any]] = []
        active_validators: list[dict[str, Any]] = []
        miners: list[dict[str, Any]] = []
        public_nodes: list[dict[str, Any]] = []
        try:
            from djinn_validator.utils.egress_reader import get_all_egress_commitments

            _debug_egress_map = get_all_egress_commitments(neuron)
        except Exception:
            _debug_egress_map = {}
        try:
            uids = list(snap.uids.tolist()) if hasattr(snap.uids, "tolist") else list(snap.uids)
            n = len(uids)
            validator_permits = (
                list(snap.validator_permit.tolist())
                if hasattr(snap.validator_permit, "tolist")
                else list(snap.validator_permit)
            )
            stakes = list(snap.S.tolist()) if hasattr(snap.S, "tolist") else list(snap.S)
            try:
                emissions = list(snap.E.tolist()) if hasattr(snap.E, "tolist") else list(snap.E)
            except Exception:
                emissions = [0.0] * n
            try:
                hotkeys = list(snap.hotkeys)
            except Exception:
                hotkeys = ["" for _ in range(n)]
            try:
                axons = list(snap.axons)
            except Exception:
                axons = [None] * n
            for idx, uid in enumerate(uids):
                axon = axons[idx] if idx < len(axons) else None
                ip = getattr(axon, "ip", "0.0.0.0") if axon else "0.0.0.0"
                port = getattr(axon, "port", 0) if axon else 0
                is_public = bool(axon) and ip not in ("0.0.0.0", "") and port > 0
                stake = float(stakes[idx]) if idx < len(stakes) else 0.0
                emission = float(emissions[idx]) if idx < len(emissions) else 0.0
                hotkey = hotkeys[idx] if idx < len(hotkeys) else ""
                is_validator = bool(validator_permits[idx]) if idx < len(validator_permits) else False
                node = {
                    "uid": int(uid),
                    "hotkey": hotkey,
                    "ip": ip,
                    "port": port,
                    "stake": stake,
                    "emission": emission,
                    "is_validator": is_validator,
                    "is_public": is_public,
                    "egress_ips": _debug_egress_map.get(int(uid), []) if is_validator else [],
                }
                nodes.append(node)
                if is_public:
                    public_nodes.append(node)
                if is_validator:
                    validators.append(node)
                    if stake > 0:
                        active_validators.append(node)
                else:
                    miners.append(node)
        except Exception as e:
            log.warning(f"debug_metagraph: metagraph projection failed: {e}")

        miners_sorted = sorted(miners, key=lambda m: m.get("emission", 0.0), reverse=True)[:10]
        validators_sorted = sorted(validators, key=lambda v: v.get("stake", 0.0), reverse=True)[:10]

        discovery_ms = int((time.time() - t0) * 1000)
        now_ms = int(time.time() * 1000)
        cache_age_ms = (now_ms - synced_ms) if synced_ms else None

        # Environment-var presence (values are never returned).
        env_presence = {
            "ODDS_API_KEYS": bool(_odds_feed.get_api_keys()),
            "TAOSTATS_API_KEY": bool(os.getenv("TAOSTATS_API_KEY", "")),
            "ADMIN_API_KEY": bool(os.getenv("ADMIN_API_KEY", "")),
            "BT_NETWORK": os.getenv("BT_NETWORK", ""),
            "BT_NETUID": os.getenv("BT_NETUID", ""),
        }

        return {
            "env": env_presence,
            "discoveryMs": discovery_ms,
            "minerDiscoveryMs": discovery_ms,
            "totalNodes": len(nodes),
            "publicNodes": len(public_nodes),
            "validators": len(validators),
            "activeValidators": len(active_validators),
            "miners": len(miners),
            "minerUrl": None,
            "cacheAge": cache_age_ms,
            "topMiners": miners_sorted,
            "topValidators": validators_sorted,
        }

    # --- Sprint A Stage A-3: /api/report-error + /api/admin/errors ported here. ---
    from djinn_validator.core import error_reports as _err_reports

    def _client_ip(request: Request) -> str:
        real_ip = request.headers.get("x-real-ip")
        if real_ip:
            return real_ip.strip()
        xff = request.headers.get("x-forwarded-for")
        if xff:
            parts = [p.strip() for p in xff.split(",") if p.strip()]
            if parts:
                return parts[-1]
        return request.client.host if request.client else "unknown"

    @app.post("/v1/report-error")
    async def submit_error_report(request: Request):
        """Public error-report sink. Rate-limited, durably persisted.

        Returns the submission_id so callers can correlate with the
        eventually-created GitHub issue (the forward worker writes the
        submission_id into the issue body). `forwarded` is False on the
        immediate response and flips True after the background worker
        successfully posts to GitHub; clients can poll
        /v1/report-error/recent (admin-only) to confirm if needed.
        """
        raw = await request.body()
        if len(raw) > _err_reports.MAX_BODY_BYTES:
            raise HTTPException(status_code=413, detail="Report too large")
        try:
            payload = json.loads(raw.decode("utf-8") or "{}")
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise HTTPException(status_code=400, detail="Invalid JSON")
        if not isinstance(payload, dict):
            raise HTTPException(status_code=400, detail="Invalid JSON")

        ip = _client_ip(request)
        try:
            entry = _err_reports.submit_report(payload, ip=ip)
        except _err_reports._RateLimited as e:
            raise HTTPException(status_code=429, detail=str(e))
        except _err_reports._InvalidReport as e:
            raise HTTPException(status_code=400, detail=str(e))

        _err_reports.fire_and_forget_issue(entry)
        return {
            "ok": True,
            "submission_id": entry.submission_id,
            "persisted": True,
            "forwarded": entry.forwarded,
            "github_token_configured": bool(_err_reports.github_token()),
        }

    @app.get("/v1/report-error/recent", dependencies=[_admin_auth])
    async def recent_error_reports(limit: int = 50):
        """Admin-auth gated view of the recent error report queue."""
        return _err_reports.recent_reports(limit)

    @app.get("/v1/report-error/stats")
    async def error_report_stats():
        """Public-readable queue health.

        Operators rely on this to detect a silently-broken feedback
        pipeline (e.g. missing GITHUB_ERROR_TOKEN). No sensitive content;
        bare counts only.
        """
        return {
            "total": _err_reports.total_stored(),
            "pending": _err_reports.pending_count(),
            "github_token_configured": bool(_err_reports.github_token()),
            "github_repo": _err_reports.github_repo(),
        }

    @app.get("/v1/hash/{path:path}")
    async def hash_path(path: str):
        """Return SHA-256 of the path segment (deterministic).

        Mirror of `web/app/api/hash/[...path]/route.ts` so TLSNotary nonce
        challenges can hit a validator directly instead of relying on
        djinn.gg. The input is the URL path (everything after /v1/hash/),
        URL-unencoded. Since path is deterministic, any prover can
        compute the expected hash locally.

        An empty path returns 404 to match the Next catch-all behavior
        (`[...path]` requires at least one segment).
        """
        import hashlib

        from fastapi.responses import Response

        if not path:
            raise HTTPException(status_code=404, detail="path required")
        digest = hashlib.sha256(path.encode("utf-8")).hexdigest()
        body = json.dumps({"input": path, "sha256": digest}, separators=(",", ":"))
        return Response(
            content=body,
            media_type="application/json",
            headers={"Cache-Control": "public, max-age=31536000, immutable"},
        )

    @app.get("/metrics")
    async def metrics() -> bytes:
        """Prometheus metrics endpoint."""
        from fastapi.responses import Response

        return Response(
            content=metrics_response(),
            media_type="text/plain; version=0.0.4; charset=utf-8",
        )

    return app
