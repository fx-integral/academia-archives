"""Entry point for the Djinn Protocol Bittensor validator.

Starts the FastAPI server and the Bittensor epoch loop concurrently.
"""

from __future__ import annotations

import asyncio
import os
import random
import signal
import time

import httpx
import structlog
import uvicorn

from djinn_validator import __version__
from djinn_validator.log_config import configure_logging

configure_logging()

from djinn_validator.api.server import create_app
from djinn_validator.bt.neuron import DjinnValidator
from djinn_validator.chain.contracts import ChainClient
from djinn_validator.chain.encryption_keys import load_or_generate_keypair
from djinn_validator.config import CANONICAL_OUTCOME_VOTING_ADDRESS, Config
from djinn_validator.core.activity import ActivityBuffer, ActivityCategory
from djinn_validator.core.attestation_log import AttestationLog
from djinn_validator.core.audit_set import AuditSetStore
from djinn_validator.core.challenges import challenge_miners, challenge_miners_attestation
from djinn_validator.core.espn import ESPNClient
from djinn_validator.core.mpc_audit import batch_settle_audit_set
from djinn_validator.core.mpc_coordinator import MPCCoordinator
from djinn_validator.core.outcomes import OutcomeAttestor
from djinn_validator.core.purchase import PurchaseOrchestrator
from djinn_validator.core.purchase_odds_ledger import PurchaseOddsLedger
from djinn_validator.core.scoring import MinerScorer
from djinn_validator.core.shares import ShareStore
from djinn_validator.core.telemetry import TelemetryStore
from djinn_validator.core.validator_sync import ValidatorSetSyncer
from djinn_validator.utils.watchtower import watch_loop as watchtower_loop


def _sanitize_url(url: str) -> str:
    """Strip credentials and path from URL for safe logging."""
    from urllib.parse import urlparse

    try:
        parsed = urlparse(url)
        return f"{parsed.scheme}://{parsed.hostname}:{parsed.port or 443}"
    except Exception:
        return "<unparseable>"


log = structlog.get_logger()


async def epoch_loop(
    neuron: DjinnValidator,
    scorer: MinerScorer,
    share_store: ShareStore,
    outcome_attestor: OutcomeAttestor,
    chain_client: ChainClient | None = None,
    activity: ActivityBuffer | None = None,
    audit_set_store: AuditSetStore | None = None,
    burn_fraction: float = 0.80,
    espn_client: ESPNClient | None = None,
    shares_threshold: int = 3,
    telemetry: TelemetryStore | None = None,
    purchase_odds_ledger: PurchaseOddsLedger | None = None,
    encryption_privkey: bytes | None = None,
    line_outcome_submitter: object | None = None,
    peer_attestation_store: object | None = None,
) -> None:
    """Main validator epoch loop: sync metagraph, score miners, set weights."""
    log.info(
        "epoch_loop_started",
        settlement_enabled=chain_client is not None and chain_client.can_write,
    )
    consecutive_errors = 0

    # Detect contract version on startup and periodically
    if chain_client:
        try:
            detected_version = await chain_client.detect_contract_version(epoch=0)
            log.info("contract_version_initial", version=detected_version)
            if audit_set_store:
                audit_set_store.contract_version = detected_version
        except Exception as e:
            log.warning("contract_version_detect_failed", err=str(e))

    # DDoS shield: resolve miner tunnel URLs for fallback routing
    _shield_resolver = None
    try:
        from djinn_tunnel_shield import ShieldResolver

        _shield_resolver = ShieldResolver(wallet=neuron.wallet if neuron else None)
        log.info("shield_resolver_enabled")
    except ImportError:
        pass  # Shield not installed, direct IP only

    # Throttle miner challenges: once every CHALLENGE_INTERVAL_EPOCHS epochs (~10 min)
    CHALLENGE_INTERVAL_EPOCHS = 50  # 50 * 12s = 10 minutes
    ATTESTATION_CHALLENGE_INTERVAL = 100  # 100 * 12s = ~20 min
    epoch_count = 0
    # Time-based fallback: reset scorer if weights haven't been set in MAX_EPOCH_DURATION
    MAX_EPOCH_DURATION = 1800  # 30 minutes
    last_reset_time = time.monotonic()

    # v1696: time-cap the per-epoch settlement phase so it doesn't starve the
    # 12s health-check tempo. Pre-fix, settling 70+ ready audit_sets serially
    # at ~30-60s each blocked the loop for 35-70 minutes per pass — health
    # checks fired once per ~hour instead of once per 12s, EMA decay was
    # frozen, miner uptime scoring drifted (James spotted this 2026-05-03).
    # v1715: the settlement queue is always processed from index 0 of the
    # deterministically-sorted ready_sets (see audit_set.get_ready_sets); the
    # soft budget caps per-epoch work so health-check tempo is preserved while
    # all validators converge on the head-of-queue pair.
    _SETTLE_BUDGET_S = float(os.environ.get("DJINN_SETTLE_BUDGET_S", "10.0"))

    while True:
        try:
            # Sync metagraph in a thread so the blocking future.result()
            # call inside sync_metagraph doesn't stall in-flight attestations
            await asyncio.to_thread(neuron.sync_metagraph, timeout=30.0)

            # Health-check all miners by pinging their axon /health endpoint
            miner_uids = neuron.get_miner_uids()
            if epoch_count % 50 == 0:
                log.info("epoch_tick", epoch=epoch_count, miners=len(miner_uids))

            # Prune deregistered miner UIDs from scorer
            scorer.prune_absent(set(miner_uids))

            async def _verify_proactive_proof(
                ip: str,
                port: int,
                uid: int,
                metrics: object,
            ) -> None:
                """Fetch and verify a miner's proactive attestation proof.

                Uses its own httpx client because the health check client
                may close before this background task runs.
                """
                try:
                    async with httpx.AsyncClient(timeout=30.0) as proof_client:
                        proof_resp = await proof_client.get(
                            f"http://{ip}:{port}/v1/attestation/latest",
                        )
                    if proof_resp.status_code != 200:
                        return
                    pdata = proof_resp.json()
                    if not pdata.get("available") or not pdata.get("proof_hex"):
                        return

                    proof_bytes = bytes.fromhex(pdata["proof_hex"])
                    notary_key = pdata.get("notary_pubkey", "")

                    from djinn_validator.core import tlsn as tlsn_verifier

                    if not tlsn_verifier.is_available():
                        return
                    verify_result = await asyncio.wait_for(
                        tlsn_verifier.verify_proof(
                            proof_bytes,
                            expected_notary_key=notary_key or None,
                        ),
                        timeout=30.0,
                    )
                    if verify_result.verified:
                        metrics.proactive_proof_verified = True
                        metrics.record_attestation(latency=pdata.get("proof_age_s", 0), proof_valid=True)
                        log.info(
                            "proactive_proof_verified",
                            uid=uid,
                            server=pdata.get("server_name", ""),
                            age_s=round(pdata.get("proof_age_s", 0), 1),
                        )
                    else:
                        log.warning("proactive_proof_invalid", uid=uid, error=verify_result.error)
                except Exception as e:
                    log.warning("proactive_proof_check_error", uid=uid, error=str(e))

            async def _check_health(client: httpx.AsyncClient, uid: int) -> None:
                axon = neuron.get_axon_info(uid)
                hotkey = axon.get("hotkey", f"uid-{uid}")
                coldkey = axon.get("coldkey", "")
                ip = axon.get("ip", "")
                port = axon.get("port", 0)
                metrics = scorer.get_or_create(uid, hotkey)
                scorer.update_coldkey(uid, coldkey)
                if not ip or not port:
                    metrics.record_health_check(responded=False)
                    return
                # SSRF protection: skip miners with non-public IPs
                from djinn_validator.core.mpc_orchestrator import _is_public_ip

                if not _is_public_ip(ip):
                    log.debug("health_check_skip_non_public_ip", uid=uid, ip=ip)
                    metrics.record_health_check(responded=False)
                    return
                urls = [f"http://{ip}:{port}/health"]
                if _shield_resolver:
                    urls = _shield_resolver.urls(uid, ip, port, "/health")
                responded = False
                for url in urls:
                    try:
                        resp = await client.get(url)
                        if resp.status_code == 200:
                            responded = True
                            if _shield_resolver:
                                _shield_resolver.record_success(uid)
                            break
                    except httpx.HTTPError:
                        if _shield_resolver:
                            _shield_resolver.record_failure(uid)
                        continue
                if responded:
                    try:
                        data = resp.json()
                        v = data.get("version", "")
                        if v:
                            metrics.reported_version = str(v)
                        caps = data.get("capabilities")
                        if caps and isinstance(caps, dict):
                            metrics.update_capabilities(
                                memory_total_mb=caps.get("memory_total_mb", 0),
                                memory_available_mb=caps.get("memory_available_mb", 0),
                                cpu_cores=caps.get("cpu_cores", 0),
                                cpu_load_1m=caps.get("cpu_load_1m", 0.0),
                                tlsn_max_concurrent=caps.get("tlsn_max_concurrent", 0),
                                tlsn_active_sessions=caps.get("tlsn_active_sessions", 0),
                                notary_max_concurrent=caps.get("notary_max_concurrent", 0),
                                notary_active_sessions=caps.get("notary_active_sessions", 0),
                                disk_free_gb=caps.get("disk_free_gb", 0.0),
                            )
                        # Mark notary-capable if miner reports notary capacity
                        if caps.get("notary_max_concurrent", 0) > 0:
                            metrics.notary_capable = True
                        # Track shield adoption
                        shield = data.get("shield_installed")
                        if shield is not None:
                            metrics.shield_installed = bool(shield)
                        # Cache tunnel URL for DDoS fallback
                        if _shield_resolver and data.get("tunnel_url"):
                            _shield_resolver.cache_from_health(uid, data)
                        # Check proactive proof if present.
                        # Do NOT set proactive_proof_verified here.
                        # A malicious miner could fake this health field.
                        # The flag is only set after background TLSNotary
                        # verification succeeds in _verify_proactive_proof.
                        pp = data.get("proactive_proof")
                        if pp:
                            bh = pp.get("binary_hash", "")
                            if bh:
                                metrics.tlsn_binary_hash = bh
                            if pp.get("proof_age_s", 99999) < 86400 and not metrics.proactive_proof_verified:
                                asyncio.create_task(_verify_proactive_proof(ip, port, uid, metrics))
                    except Exception:
                        pass  # Old miners may not return JSON or capabilities
                metrics.record_health_check(responded=responded)

            async with httpx.AsyncClient(timeout=httpx.Timeout(5.0)) as client:
                await asyncio.gather(*[_check_health(client, uid) for uid in miner_uids])

            responded = (
                sum(1 for uid in miner_uids if (m := scorer.get(uid)) is not None and m.ema_uptime > 0.001)
                if miner_uids
                else 0
            )
            failed_uids = (
                [uid for uid in miner_uids if (m := scorer.get(uid)) is not None and m.health_checks_responded == 0]
                if miner_uids
                else []
            )
            if activity is not None and miner_uids:
                activity.record(
                    ActivityCategory.HEALTH_CHECK,
                    f"{responded}/{len(miner_uids)} miners responded",
                    responded=responded,
                    total=len(miner_uids),
                    failed_uids=failed_uids[:50],
                )
            if telemetry and miner_uids:
                telemetry.record(
                    "health_check",
                    f"{responded}/{len(miner_uids)} miners responded",
                    responded=responded,
                    total=len(miner_uids),
                    failed_uids=failed_uids[:50],
                )

            # Challenge miners for accuracy scoring (throttled)
            epoch_count += 1

            # Re-detect contract version periodically (picks up mid-run proxy upgrades)
            if chain_client and epoch_count % 100 == 0:
                try:
                    detected_version = await chain_client.detect_contract_version(epoch=epoch_count)
                    if audit_set_store:
                        audit_set_store.contract_version = detected_version
                except Exception as e:
                    log.debug("contract_version_redetect_failed", err=str(e))

            if epoch_count % CHALLENGE_INTERVAL_EPOCHS == 0:
                if miner_uids:
                    miner_axons = []
                    for uid in miner_uids:
                        axon = neuron.get_axon_info(uid)
                        miner_axons.append(
                            {
                                "uid": uid,
                                "hotkey": axon.get("hotkey", f"uid-{uid}"),
                                "ip": axon.get("ip", ""),
                                "port": axon.get("port", 0),
                                "coldkey": axon.get("coldkey", ""),
                            }
                        )
                    try:
                        cr = await challenge_miners(scorer, miner_axons, espn_client=espn_client, wallet=neuron.wallet)
                        if activity and cr.challenged:
                            activity.record(
                                ActivityCategory.CHALLENGE_ROUND,
                                f"Challenged {cr.challenged} miners on {cr.sport}",
                                miners_challenged=cr.challenged,
                                sport=cr.sport,
                                games_found=cr.games_found,
                                lines_used=cr.lines_used,
                                responding=cr.responding,
                                consensus_quorum=cr.consensus_quorum,
                                proofs_requested=cr.proofs_requested,
                                proofs_submitted=cr.proofs_submitted,
                                miners=cr.miner_results[:50],
                                challenge_lines=cr.challenge_lines,
                            )
                        if telemetry and cr.challenged:
                            telemetry.record(
                                "challenge_round",
                                f"Challenged {cr.challenged} miners on {cr.sport}: {cr.responding} responded, {cr.games_found} games, {cr.lines_used} lines",
                                miners_challenged=cr.challenged,
                                sport=cr.sport,
                                games_found=cr.games_found,
                                lines_used=cr.lines_used,
                                responding=cr.responding,
                                consensus_quorum=cr.consensus_quorum,
                                proofs_requested=cr.proofs_requested,
                                proofs_submitted=cr.proofs_submitted,
                                miners=cr.miner_results[:50],
                                challenge_lines=cr.challenge_lines,
                            )
                    except Exception as e:
                        log.warning("challenge_miners_error", err=str(e))
                        if telemetry:
                            telemetry.record(
                                "challenge_error", f"Challenge failed: {e}", error=str(e), error_type=type(e).__name__
                            )

            # Attestation challenges: run less frequently than sports (~20 min)
            if epoch_count % ATTESTATION_CHALLENGE_INTERVAL == 0 and miner_uids:
                miner_axons = []
                for uid in miner_uids:
                    axon = neuron.get_axon_info(uid)
                    miner_axons.append(
                        {
                            "uid": uid,
                            "hotkey": axon.get("hotkey", f"uid-{uid}"),
                            "ip": axon.get("ip", ""),
                            "port": axon.get("port", 0),
                            "coldkey": axon.get("coldkey", ""),
                        }
                    )
                try:
                    ar = await challenge_miners_attestation(scorer, miner_axons, wallet=neuron.wallet)
                    if activity and ar.challenged:
                        # Count how many miners used peer notaries vs default
                        peer_notarized = sum(1 for m in ar.miner_results if m.get("peer_notary"))
                        summary = f"Attestation: {ar.verified}/{ar.challenged} verified ({ar.url.split('/')[2]})"
                        if peer_notarized:
                            summary += f" [{peer_notarized} peer-notarized]"
                        activity.record(
                            ActivityCategory.ATTESTATION_CHALLENGE,
                            summary,
                            challenged=ar.challenged,
                            verified=ar.verified,
                            url=ar.url,
                            reachable=ar.reachable,
                            capable=ar.capable,
                            peer_notarized=peer_notarized,
                            miners=ar.miner_results,
                        )
                    if telemetry and ar.challenged:
                        telemetry.record(
                            "attestation_challenge",
                            f"Attestation: {ar.verified}/{ar.challenged} verified for {ar.url}",
                            challenged=ar.challenged,
                            verified=ar.verified,
                            url=ar.url,
                            reachable=ar.reachable,
                            capable=ar.capable,
                            miners=ar.miner_results,
                        )
                except Exception as e:
                    log.warning("attest_challenge_error", err=str(e))
                    if telemetry:
                        telemetry.record(
                            "attestation_error",
                            f"Attestation challenge failed: {e}",
                            error=str(e),
                            error_type=type(e).__name__,
                        )

            # Phase 1: Resolve games — compute all 10 line outcomes per signal
            # (public ESPN data, no MPC at this stage)
            hotkey = ""
            if neuron.wallet:
                hotkey = neuron.wallet.hotkey.ss58_address

            resolved_ids = await outcome_attestor.resolve_all_pending(hotkey)

            # v1747 Phase 7b: sign newly-stable lines (180s soak gate) and
            # submit own EIP-712 sigs to LineOutcomeRegistry. Both methods
            # are no-ops when chain context (private key, registry address)
            # is unwired, or when no lines have crossed the soak boundary.
            # Failures are logged and absorbed — the legacy resolution +
            # gossip path is unaffected.
            try:
                signed = await outcome_attestor.sign_stable_lines()
                if signed:
                    log.info("v1747_lines_signed", count=len(signed))
            except Exception as e:
                log.warning("v1747_sign_stable_failed", err=str(e)[:200])
            if line_outcome_submitter is not None:
                # Threshold path runs FIRST: if a 4-of-5 bundle is ready,
                # one tx finalizes the line for the whole fleet. Saves gas
                # vs every-validator-submits-its-own. Falls through cleanly
                # when no peer sigs are available yet.
                if peer_attestation_store is not None:
                    try:
                        finalized = await outcome_attestor.submit_threshold_lines(
                            peer_attestation_store, line_outcome_submitter
                        )
                        if finalized:
                            log.info("v1747_threshold_lines_finalized", count=len(finalized))
                    except Exception as e:
                        log.warning("v1747_submit_threshold_failed", err=str(e)[:200])
                try:
                    submitted_own = await outcome_attestor.submit_own_attestations(
                        line_outcome_submitter
                    )
                    if submitted_own:
                        log.info("v1747_own_attestations_submitted", count=len(submitted_own))
                except Exception as e:
                    log.warning("v1747_submit_own_failed", err=str(e)[:200])

            if resolved_ids:
                log.info("outcomes_resolved", count=len(resolved_ids))
                if activity is not None:
                    activity.record(
                        ActivityCategory.OUTCOME_RESOLUTION,
                        f"Resolved {len(resolved_ids)} signal outcomes",
                        count=len(resolved_ids),
                        signal_ids=resolved_ids[:20],
                    )
                if telemetry:
                    telemetry.record(
                        "outcome_resolution",
                        f"Resolved {len(resolved_ids)} signal outcomes",
                        count=len(resolved_ids),
                        signal_ids=resolved_ids[:20],
                    )
                # Record outcomes on audit set store
                if audit_set_store:
                    for signal_id in resolved_ids:
                        meta = outcome_attestor.get_signal(signal_id)
                        if meta and meta.outcomes:
                            audit_set_store.record_outcomes(signal_id, meta.outcomes)

                # Phase A1 outcome gossip (docs/outcome-layer-plan.md):
                # Broadcast each newly-resolved signal to peer validators so
                # they can mark resolved without waiting for their own ESPN
                # poll. Receivers replay-verify by independent ESPN fetch
                # before storing. Fire-and-forget — one slow peer must not
                # stall the local resolve loop.
                from djinn_validator.api.server import _gossip_resolved_outcome_to_peers

                for signal_id in resolved_ids:
                    meta = outcome_attestor.get_signal(signal_id)
                    if not meta or not meta.outcomes:
                        continue
                    raw_summary = {
                        "home_team": meta.home_team,
                        "away_team": meta.away_team,
                        "sport": meta.sport,
                        "event_id": meta.event_id,
                    }
                    asyncio.create_task(
                        _gossip_resolved_outcome_to_peers(
                            neuron,
                            signal_id,
                            [int(o) for o in meta.outcomes],
                            raw_espn_summary=raw_summary,
                            audit_set_store=audit_set_store,
                            outcome_attestor=outcome_attestor,
                            signer_address=chain_client.signer_address() if chain_client else None,
                        )
                    )
                    outcome_attestor.mark_gossiped(signal_id)

            # Phase A1.5 — reconciliation gossip (docs/outcome-layer-plan.md):
            # Re-broadcast oldest-gossiped resolved signals every ~5 min so
            # peers that missed the original gossip (offline, 422'd on a
            # Pydantic cap, transient timeout) self-heal. Receivers return
            # already_resolved for ones they have (cheap memory hit) and
            # accepted for the gaps. Closes per-peer subset divergence
            # without per-failed-peer retry queues. epoch_count increments
            # ~every 12s; reconcile every 25 cycles ≈ 5 min.
            RECONCILE_EVERY_N_LOOPS = 25
            RECONCILE_CHUNK_SIZE = 50
            if epoch_count > 0 and epoch_count % RECONCILE_EVERY_N_LOOPS == 0 and outcome_attestor:
                from djinn_validator.api.server import _gossip_resolved_outcome_to_peers as _gossip

                reconcile_ids = outcome_attestor.get_resolved_for_reconcile(limit=RECONCILE_CHUNK_SIZE)
                if reconcile_ids:
                    log.info(
                        "outcome_gossip_reconcile_start",
                        chunk=len(reconcile_ids),
                        epoch=epoch_count,
                    )
                    for signal_id in reconcile_ids:
                        meta = outcome_attestor.get_signal(signal_id)
                        if not meta or not meta.outcomes:
                            continue
                        raw_summary = {
                            "home_team": meta.home_team,
                            "away_team": meta.away_team,
                            "sport": meta.sport,
                            "event_id": meta.event_id,
                        }
                        asyncio.create_task(
                            _gossip(
                                neuron,
                                signal_id,
                                [int(o) for o in meta.outcomes],
                                raw_espn_summary=raw_summary,
                                audit_set_store=audit_set_store,
                                outcome_attestor=outcome_attestor,
                                signer_address=chain_client.signer_address() if chain_client else None,
                            )
                        )
                        outcome_attestor.mark_gossiped(signal_id)

            # Phase 2: Check for ready audit sets → batch MPC → vote aggregates
            # v1715: always process from index 0 of the deterministically-sorted
            # ready_sets list. v1696's per-validator round-robin offset (advanced
            # by _settle_processed each epoch) was actively preventing
            # convergence: different validators ended up at different positions
            # in the sorted queue, so they voted on disjoint (genius, idiot,
            # cycle) tuples and never reached 4-of-5 quorum on any single one.
            # Symptom: 7 VoteSubmitted on chain across 7 disjoint pairs, 0
            # QuorumReached. With v1714's deterministic sort already in place,
            # starting at 0 means every validator hammers the head-of-queue
            # pair until it settles + drops out, then moves to the new head.
            # The soft 10s budget still preserves the 12s health-check tempo;
            # tail-of-queue pairs just wait their turn (priority by sort order).
            if audit_set_store:
                ready_sets = audit_set_store.get_ready_sets()
                _settle_deadline = time.monotonic() + _SETTLE_BUDGET_S
                _settle_processed = 0
                for audit_set in ready_sets:
                    if time.monotonic() >= _settle_deadline:
                        log.info(
                            "settle_budget_exhausted",
                            processed=_settle_processed,
                            remaining=len(ready_sets) - _settle_processed,
                            budget_s=_SETTLE_BUDGET_S,
                        )
                        break
                    _settle_processed += 1
                    result = await asyncio.to_thread(
                        batch_settle_audit_set,
                        audit_set,
                        share_store,
                        threshold=shares_threshold,
                    )

                    # SHADOW MODE: when DJINN_FF_BATCH_SETTLEMENT_HTTP is
                    # on, run the distributed HTTP protocol for this audit
                    # set. Runs independently of local settlement success
                    # (v1428 change) so P0-01 diagnosis can observe peer-
                    # fetch even when local trusted-dealer reconstruction
                    # silently fails (e.g., validator holds <threshold
                    # shares for signal). By default still observe-only.
                    # When DJINN_FF_BATCH_SETTLEMENT_HTTP_SUBMIT is ON and
                    # the local ``result`` is None, the distributed
                    # aggregate is submitted on-chain instead (closes
                    # P0-01 under 2-of-2 Shamir). See DEV-044 and
                    # feedback_validator_backward_compat.md.
                    distributed: ShadowSettleSubmitData | None = None  # type: ignore[name-defined]  # noqa: F821
                    try:
                        from djinn_validator.feature_flags import flags as _ff_shadow

                        if _ff_shadow.batch_settlement_http and purchase_odds_ledger is not None:
                            from djinn_validator.core.mpc_coordinator import MPCCoordinator
                            from djinn_validator.core.mpc_orchestrator import MPCOrchestrator

                            _shadow_orch = MPCOrchestrator(
                                coordinator=MPCCoordinator(),
                                neuron=neuron,
                                threshold=shares_threshold,
                                chain_client=chain_client,
                                encryption_privkey=encryption_privkey,
                                signer_address=chain_client.signer_address() if chain_client else None,
                                outcome_attestor=outcome_attestor,
                                audit_set_store=audit_set_store,
                            )
                            try:
                                distributed = await _shadow_orch.try_shadow_distributed_settlement(
                                    audit_set=audit_set,
                                    share_store=share_store,
                                    purchase_odds_ledger=purchase_odds_ledger,
                                    threshold=shares_threshold,
                                )
                                local_q = result.quality_score if result is not None else None
                                if distributed is not None:
                                    # v1716: a successful shadow_settle means
                                    # the batch did build (data finally arrived
                                    # via gossip / recovery). Reset the abstain
                                    # counter so the set isn't evicted later
                                    # if it transiently abstains again.
                                    audit_set_store.reset_abstain(
                                        audit_set.genius_address,
                                        audit_set.idiot_address,
                                        audit_set.cycle,
                                    )
                                    distributed_q = distributed.quality_score
                                    divergence = abs(distributed_q - local_q) if local_q is not None else None
                                    log.info(
                                        "shadow_settle_completed",
                                        local_quality_score=local_q,
                                        local_settled=(result is not None),
                                        distributed_total=distributed_q,
                                        distributed_total_notional=distributed.total_notional,
                                        distributed_purchase_count=distributed.purchase_count,
                                        divergence=divergence,
                                        genius=audit_set.genius_address,
                                        idiot=audit_set.idiot_address,
                                        cycle=audit_set.cycle,
                                    )
                                    if telemetry:
                                        telemetry.record(
                                            "shadow_settle",
                                            f"Shadow distr={distributed_q} local={local_q} delta={divergence}",
                                            local_quality_score=local_q,
                                            local_settled=(result is not None),
                                            distributed_total=distributed_q,
                                            divergence=divergence,
                                            genius=audit_set.genius_address,
                                            idiot=audit_set.idiot_address,
                                            cycle=audit_set.cycle,
                                        )
                                else:
                                    # v1716: shadow_settle returned None — most
                                    # commonly because build_purchase_inputs
                                    # found missing share / BPA-WPA / outcome
                                    # for one of the resolved signals. Track
                                    # the abstain so persistently-broken
                                    # legacy pairs are evicted from
                                    # get_ready_sets after N attempts and
                                    # head-of-queue can advance.
                                    abstain_n = audit_set_store.mark_abstain(
                                        audit_set.genius_address,
                                        audit_set.idiot_address,
                                        audit_set.cycle,
                                    )
                                    log.info(
                                        "shadow_settle_returned_none",
                                        local_settled=(result is not None),
                                        genius=audit_set.genius_address,
                                        idiot=audit_set.idiot_address,
                                        abstain_count=abstain_n,
                                    )
                            finally:
                                await _shadow_orch.close()
                    except Exception as _shadow_err:
                        # Shadow runs must NEVER break the real audit
                        # path. Any failure gets logged and swallowed.
                        # error_type added 2026-05-03 (v1672 followup): the
                        # NameError that hid for a full day of v1670/v1671
                        # would have been obvious from a single grep on
                        # error_type=NameError; without the class name the
                        # operator has to read every line of the message.
                        log.warning(
                            "shadow_settle_exception",
                            error_type=type(_shadow_err).__name__,
                            error=str(_shadow_err)[:200],
                            genius=audit_set.genius_address,
                            idiot=audit_set.idiot_address,
                        )

                    if result is None:
                        # v1558 (task #90): when local trusted-dealer
                        # settlement returns None, try to submit from the
                        # distributed shadow aggregate instead — gated
                        # behind DJINN_FF_BATCH_SETTLEMENT_HTTP_SUBMIT.
                        # Under 2-of-2 Shamir fan-out the local path can
                        # never succeed; distributed is the only settlement
                        # path that reaches on-chain.
                        from djinn_validator.feature_flags import flags as _ff_submit

                        # v1695: tick a counter when the flag-gated submit path
                        # is SKIPPED so operators can see remotely whether
                        # shadow-completed work is being silently dropped by
                        # the feature flag (UID 1's 3 completes -> 0 votes
                        # mystery — either flag off, no chain client, or
                        # not write-enabled).
                        if not (
                            _ff_submit.batch_settlement_http_submit
                            and distributed is not None
                            and chain_client is not None
                            and chain_client.can_write
                        ):
                            try:
                                from djinn_validator.api.metrics import VOTE_SUBMIT_OUTCOME

                                if distributed is not None:
                                    if not _ff_submit.batch_settlement_http_submit:
                                        VOTE_SUBMIT_OUTCOME.labels(outcome="skipped_flag_off").inc()
                                    elif chain_client is None:
                                        VOTE_SUBMIT_OUTCOME.labels(outcome="skipped_no_chain_client").inc()
                                    elif not chain_client.can_write:
                                        VOTE_SUBMIT_OUTCOME.labels(outcome="skipped_no_write").inc()
                            except Exception:
                                pass

                        if (
                            _ff_submit.batch_settlement_http_submit
                            and distributed is not None
                            and chain_client is not None
                            and chain_client.can_write
                        ):
                            log.info(
                                "submit_from_shadow_attempt",
                                genius=distributed.genius,
                                idiot=distributed.idiot,
                                cycle=distributed.cycle,
                                quality_score=distributed.quality_score,
                                total_notional=distributed.total_notional,
                                purchase_count=distributed.purchase_count,
                                session_id=distributed.session_id,
                            )
                            # v1581 (P0-01): pre-flight hasVoted/finalized on the
                            # shadow submit path. Without this, every audit_set
                            # whose batchKey we already voted on (or that was
                            # finalized by peer quorum) burns gas on a revert.
                            # Mirrors the v1580 main-path pre-flight. See
                            # djinn-notes.md "on-chain revert != raised exception".
                            if chain_client.contract_version == 2 and distributed.purchase_ids:
                                pre_voted, pre_final = await chain_client.has_voted_for_batch(
                                    distributed.genius,
                                    distributed.idiot,
                                    distributed.purchase_ids,
                                )
                                # v1614 (2026-04-26 SEV-1 audit-queue stall fix):
                                # mark_settled ONLY on pre_final. pre_voted=true means
                                # this validator already cast its vote but quorum is
                                # not yet reached on-chain — the batch is genuinely
                                # still pending. Pre-fix, mark_settled fired on
                                # pre_voted alone, advancing /v1/audit/summary.settled
                                # locally while on-chain stayed unsettled. That
                                # masked the real stall (other validators not voting)
                                # and wasted an iteration of operator triage time.
                                if pre_final:
                                    try:
                                        from djinn_validator.api.metrics import VOTE_SUBMIT_OUTCOME

                                        VOTE_SUBMIT_OUTCOME.labels(outcome="preflight_finalized").inc()
                                    except Exception:
                                        pass
                                    log.info(
                                        "submit_from_shadow_preflight_skip",
                                        reason="finalized",
                                        genius=distributed.genius,
                                        idiot=distributed.idiot,
                                        cycle=distributed.cycle,
                                        session_id=distributed.session_id,
                                    )
                                    audit_set_store.mark_settled(
                                        distributed.genius,
                                        distributed.idiot,
                                        distributed.cycle,
                                    )
                                    continue
                                if pre_voted:
                                    try:
                                        from djinn_validator.api.metrics import VOTE_SUBMIT_OUTCOME

                                        VOTE_SUBMIT_OUTCOME.labels(outcome="preflight_already_voted").inc()
                                    except Exception:
                                        pass
                                    log.info(
                                        "submit_from_shadow_already_voted_awaiting_quorum",
                                        genius=distributed.genius,
                                        idiot=distributed.idiot,
                                        cycle=distributed.cycle,
                                        session_id=distributed.session_id,
                                    )
                                    continue
                            # P0-01 gate (v1611+v1612): submit only when a
                            # contract-accepted settlement precondition holds.
                            # V1611: batch>=10 OR explicit OV.requestEarlyExit.
                            # V1612: also accept the on-chain SLA timeout (45 days
                            # default) as auto-trigger for early exit. The
                            # contract enforces the same precondition so a
                            # validator that's wrong about timing just reverts.
                            # Note: Audit V2 _settleCommon now refunds principal
                            # in USDC up to sum(usdcPaid) and excess in Credits
                            # on BOTH paths, so isEarlyExit no longer affects
                            # damages currency — only batch-size constraints
                            # and event emission.
                            CONTRACT_MIN_BATCH_SIZE = 10
                            _is_early_exit = False
                            _batch_size = len(distributed.purchase_ids)
                            if _batch_size >= CONTRACT_MIN_BATCH_SIZE:
                                _is_early_exit = False
                            else:
                                _opted_in = await chain_client.is_early_exit_requested(
                                    distributed.genius,
                                    distributed.idiot,
                                    distributed.purchase_ids,
                                )
                                if _opted_in:
                                    _is_early_exit = True
                                else:
                                    _timeout_ok = await chain_client.should_auto_early_exit(
                                        distributed.purchase_ids,
                                    )
                                    if _timeout_ok:
                                        _is_early_exit = True
                                    else:
                                        log.info(
                                            "skip_settle_below_min_batch_no_request_no_timeout",
                                            genius=distributed.genius,
                                            idiot=distributed.idiot,
                                            cycle=distributed.cycle,
                                            batch_size=_batch_size,
                                            min_batch=CONTRACT_MIN_BATCH_SIZE,
                                            session_id=distributed.session_id,
                                        )
                                        try:
                                            from djinn_validator.api.metrics import VOTE_SUBMIT_OUTCOME

                                            VOTE_SUBMIT_OUTCOME.labels(outcome="pregate_skip").inc()
                                        except Exception:
                                            pass
                                        continue
                            try:
                                from djinn_validator.api.metrics import VOTE_SUBMIT_OUTCOME

                                VOTE_SUBMIT_OUTCOME.labels(outcome="attempted").inc()
                                cv = chain_client.contract_version
                                tx_hash = await chain_client.submit_vote(
                                    distributed.genius,
                                    distributed.idiot,
                                    distributed.quality_score,
                                    distributed.total_notional,
                                    purchase_ids=distributed.purchase_ids,
                                    is_early_exit=_is_early_exit,
                                )
                                VOTE_SUBMIT_OUTCOME.labels(outcome="submitted").inc()
                                log.info(
                                    "submit_from_shadow_submitted",
                                    genius=distributed.genius,
                                    idiot=distributed.idiot,
                                    cycle=distributed.cycle,
                                    quality_score=distributed.quality_score,
                                    total_notional=distributed.total_notional,
                                    tx_hash=tx_hash,
                                    contract_version=cv,
                                    purchase_ids_count=len(distributed.purchase_ids),
                                    session_id=distributed.session_id,
                                )
                                if telemetry:
                                    telemetry.record(
                                        "submit_from_shadow",
                                        f"Distributed submit (v{cv}): quality={distributed.quality_score} "
                                        f"notional={distributed.total_notional} pids={len(distributed.purchase_ids)}",
                                        genius=distributed.genius,
                                        idiot=distributed.idiot,
                                        cycle=distributed.cycle,
                                        quality_score=distributed.quality_score,
                                        total_notional=distributed.total_notional,
                                        tx_hash=tx_hash,
                                        contract_version=cv,
                                    )
                                try:
                                    receipt = await chain_client.wait_for_receipt(tx_hash, timeout_s=120.0)
                                    if int(receipt.get("status", 0)) == 1:
                                        VOTE_SUBMIT_OUTCOME.labels(outcome="confirmed").inc()
                                        log.info(
                                            "submit_from_shadow_confirmed",
                                            tx_hash=tx_hash,
                                            block=receipt.get("blockNumber"),
                                            genius=distributed.genius,
                                            idiot=distributed.idiot,
                                            cycle=distributed.cycle,
                                        )
                                        audit_set_store.mark_settled(
                                            distributed.genius,
                                            distributed.idiot,
                                            distributed.cycle,
                                        )
                                    else:
                                        VOTE_SUBMIT_OUTCOME.labels(outcome="reverted").inc()
                                        log.error(
                                            "submit_from_shadow_reverted",
                                            tx_hash=tx_hash,
                                            block=receipt.get("blockNumber"),
                                            genius=distributed.genius,
                                            idiot=distributed.idiot,
                                            cycle=distributed.cycle,
                                        )
                                except TimeoutError:
                                    VOTE_SUBMIT_OUTCOME.labels(outcome="receipt_timeout").inc()
                                    log.warning(
                                        "submit_from_shadow_receipt_timeout",
                                        tx_hash=tx_hash,
                                        genius=distributed.genius,
                                        idiot=distributed.idiot,
                                        cycle=distributed.cycle,
                                    )
                            except Exception as _submit_err:
                                err_str = str(_submit_err)
                                if "AlreadyVoted" in err_str:
                                    VOTE_SUBMIT_OUTCOME.labels(outcome="already_voted").inc()
                                    log.debug("submit_from_shadow_skipped", reason=err_str[:80])
                                    audit_set_store.mark_settled(
                                        distributed.genius,
                                        distributed.idiot,
                                        distributed.cycle,
                                    )
                                elif "CycleAlreadyFinalized" in err_str or "BatchAlreadyAudited" in err_str:
                                    VOTE_SUBMIT_OUTCOME.labels(outcome="cycle_finalized").inc()
                                    log.debug("submit_from_shadow_skipped", reason=err_str[:80])
                                    audit_set_store.mark_settled(
                                        distributed.genius,
                                        distributed.idiot,
                                        distributed.cycle,
                                    )
                                else:
                                    VOTE_SUBMIT_OUTCOME.labels(outcome="network_error").inc()
                                    log.error(
                                        "submit_from_shadow_failed",
                                        err=err_str[:500],
                                        genius=distributed.genius,
                                        idiot=distributed.idiot,
                                        cycle=distributed.cycle,
                                    )
                            continue

                        # Observability (v1453): surface the silent dropout
                        # between ready_for_settlement and on-chain submit.
                        # Without this, P0-01 diagnosis has no breadcrumb
                        # connecting resolved signals to actual settlement
                        # attempts. See MAINNET_BLOCKERS P0-01 2026-04-21.
                        log.warning(
                            "settlement_skipped_no_batch_result",
                            genius=audit_set.genius_address,
                            idiot=audit_set.idiot_address,
                            cycle=audit_set.cycle,
                            version=audit_set.version,
                            signal_count=len(audit_set.signals),
                            resolved_count=len(audit_set.resolved_signals),
                            shadow_available=(distributed is not None),
                            shadow_submit_ff=_ff_submit.batch_settlement_http_submit,
                        )
                        continue
                    # Phase 3: Submit aggregate quality score vote on-chain
                    if chain_client and chain_client.can_write:
                        tx_hash: str | None = None
                        already_voted = False
                        # v1580: pre-flight hasVoted/finalized read so a
                        # reverting duplicate-submit doesn't trap the
                        # settlement loop in a 12s retry loop.
                        # v1614 (2026-04-26 SEV-1 audit-queue stall fix): split
                        # the pre_final and pre_voted branches. pre_final means
                        # quorum reached + Audit fired → safe to mark_settled.
                        # pre_voted alone means we voted but quorum is still
                        # pending → skip resubmit but DON'T mark_settled, so
                        # /v1/audit/summary.settled doesn't lie about progress.
                        if chain_client.contract_version == 2 and result.purchase_ids:
                            pre_voted, pre_final = await chain_client.has_voted_for_batch(
                                result.genius,
                                result.idiot,
                                result.purchase_ids,
                            )
                            if pre_final:
                                log.info(
                                    "audit_vote_preflight_skip",
                                    reason="finalized",
                                    genius=result.genius,
                                    idiot=result.idiot,
                                    cycle=result.cycle,
                                    purchase_ids_count=len(result.purchase_ids),
                                )
                                audit_set_store.mark_settled(result.genius, result.idiot, result.cycle)
                                continue
                            if pre_voted:
                                log.info(
                                    "audit_vote_already_cast_awaiting_quorum",
                                    genius=result.genius,
                                    idiot=result.idiot,
                                    cycle=result.cycle,
                                    purchase_ids_count=len(result.purchase_ids),
                                )
                                continue
                        # P0-01 gate (v1611+v1612): mirror the shadow-path gate above.
                        # batch>=10 OR opted-in OR timeout-elapsed → submit.
                        # else → skip (don't submit, log + continue).
                        CONTRACT_MIN_BATCH_SIZE = 10
                        _is_early_exit_local = False
                        _local_purchase_ids = result.purchase_ids or []
                        _local_batch_size = len(_local_purchase_ids)
                        _local_skip = False
                        if _local_batch_size >= CONTRACT_MIN_BATCH_SIZE:
                            _is_early_exit_local = False
                        elif chain_client.contract_version == 2 and _local_purchase_ids:
                            _opted_in_local = await chain_client.is_early_exit_requested(
                                result.genius,
                                result.idiot,
                                _local_purchase_ids,
                            )
                            if _opted_in_local:
                                _is_early_exit_local = True
                            else:
                                _timeout_ok_local = await chain_client.should_auto_early_exit(
                                    _local_purchase_ids,
                                )
                                if _timeout_ok_local:
                                    _is_early_exit_local = True
                                else:
                                    log.info(
                                        "skip_audit_vote_below_min_batch_no_request_no_timeout",
                                        genius=result.genius,
                                        idiot=result.idiot,
                                        cycle=result.cycle,
                                        batch_size=_local_batch_size,
                                        min_batch=CONTRACT_MIN_BATCH_SIZE,
                                    )
                                    _local_skip = True

                        if _local_skip:
                            continue

                        try:
                            cv = chain_client.contract_version
                            if not already_voted:
                                tx_hash = await chain_client.submit_vote(
                                    result.genius,
                                    result.idiot,
                                    result.quality_score,
                                    result.total_notional,
                                    purchase_ids=result.purchase_ids,
                                    is_early_exit=_is_early_exit_local,
                                )
                                log.info(
                                    "audit_vote_submitted",
                                    genius=result.genius,
                                    idiot=result.idiot,
                                    cycle=result.cycle,
                                    quality_score=result.quality_score,
                                    wins=result.wins,
                                    losses=result.losses,
                                    voids=result.voids,
                                    tx_hash=tx_hash,
                                    contract_version=cv,
                                    purchase_ids_count=len(result.purchase_ids) if result.purchase_ids else 0,
                                )
                                if telemetry:
                                    telemetry.record(
                                        "audit_vote",
                                        f"Vote submitted (v{cv}): quality={result.quality_score} ({result.wins}W/{result.losses}L/{result.voids}V)",
                                        genius=result.genius,
                                        idiot=result.idiot,
                                        cycle=result.cycle,
                                        quality_score=result.quality_score,
                                        wins=result.wins,
                                        losses=result.losses,
                                        voids=result.voids,
                                        tx_hash=tx_hash,
                                        contract_version=cv,
                                    )
                        except Exception as e:
                            err_str = str(e)
                            # v1614 split: AlreadyVoted ≠ settled. Only treat
                            # CycleAlreadyFinalized / BatchAlreadyAudited as
                            # post-settlement signals. AlreadyVoted means this
                            # validator's vote landed but quorum is still
                            # pending — skip but don't claim settled.
                            if "CycleAlreadyFinalized" in err_str or "BatchAlreadyAudited" in err_str:
                                log.debug("audit_vote_skipped_finalized", reason=err_str[:80])
                                already_voted = True  # falls through to mark_settled at line 934
                            elif "AlreadyVoted" in err_str:
                                log.debug("audit_vote_already_cast_race", reason=err_str[:80])
                                continue  # explicit: don't claim settled
                            else:
                                log.error("audit_vote_failed", err=err_str)
                                if telemetry:
                                    telemetry.record(
                                        "audit_vote_error", f"Vote failed: {err_str[:200]}", error=err_str[:500]
                                    )
                                continue  # Don't mark settled if vote failed

                        # MAINNET_BLOCKERS P0-09: wait for tx to confirm before
                        # marking settled. If the tx is dropped/reverted/reorged,
                        # leave the audit set in ready state so the next epoch
                        # retries. AlreadyVoted is a known-landed signal from a
                        # prior epoch's tx, so we can mark settled without a
                        # fresh receipt.
                        if tx_hash and not already_voted:
                            try:
                                receipt = await chain_client.wait_for_receipt(tx_hash, timeout_s=120.0)
                            except TimeoutError:
                                log.warning(
                                    "audit_vote_receipt_timeout",
                                    genius=result.genius,
                                    idiot=result.idiot,
                                    cycle=result.cycle,
                                    tx_hash=tx_hash,
                                )
                                if telemetry:
                                    telemetry.record(
                                        "audit_vote_receipt_timeout",
                                        f"Vote tx not mined within 120s: {tx_hash}",
                                        genius=result.genius,
                                        idiot=result.idiot,
                                        cycle=result.cycle,
                                        tx_hash=tx_hash,
                                    )
                                continue  # Retry next epoch (will get AlreadyVoted if it landed late)
                            if int(receipt.get("status", 0)) != 1:
                                log.error(
                                    "audit_vote_reverted",
                                    genius=result.genius,
                                    idiot=result.idiot,
                                    cycle=result.cycle,
                                    tx_hash=tx_hash,
                                    block=receipt.get("blockNumber"),
                                )
                                if telemetry:
                                    telemetry.record(
                                        "audit_vote_reverted",
                                        f"Vote tx reverted: {tx_hash}",
                                        genius=result.genius,
                                        idiot=result.idiot,
                                        cycle=result.cycle,
                                        tx_hash=tx_hash,
                                    )
                                continue  # Retry next epoch
                            log.info(
                                "audit_vote_confirmed",
                                genius=result.genius,
                                idiot=result.idiot,
                                cycle=result.cycle,
                                tx_hash=tx_hash,
                                block=receipt.get("blockNumber"),
                            )
                    else:
                        # No chain client or read-only mode — skip settlement
                        log.debug(
                            "audit_vote_skipped_no_writer", genius=result.genius, idiot=result.idiot, cycle=result.cycle
                        )
                        continue
                    audit_set_store.mark_settled(
                        result.genius,
                        result.idiot,
                        result.cycle,
                    )

            # Prune old resolved signals to prevent memory growth.
            # v1620: pass the set of signals still in unsettled audit_sets so
            # cleanup never wipes outcomes that MPC will still need at settle
            # time. Without this guard, settlement that lags >60d (or 24h on
            # pre-v1618 validators) silently abstains forever — breaks the
            # entire pipeline for any batch that takes a long time to fill.
            protected_ids = audit_set_store.protected_signal_ids() if audit_set_store is not None else None
            await outcome_attestor.cleanup_resolved(protected_ids=protected_ids)

            # Active epoch = miners were actually challenged this interval
            is_active = any(m.queries_total > 0 or m.attestations_total > 0 for m in scorer._miners.values())

            # Compute and set weights — only reset metrics AFTER weights are set
            # so that challenge data accumulates across the full interval
            if neuron.should_set_weights():
                weights, breakdowns = scorer.compute_weights_detailed(is_active)
                weights = neuron.apply_burn(weights or {}, burn_fraction)
                n_miners = len(weights) - 1  # exclude UID 0 burn entry
                success = await asyncio.to_thread(neuron.set_weights, weights)
                if success:
                    neuron.record_weight_set()
                    # All miners by weight (excluding UID 0 burn)
                    sorted_w = sorted(
                        ((uid, w) for uid, w in weights.items() if uid != 0),
                        key=lambda x: x[1],
                        reverse=True,
                    )
                    top_miners = []
                    for uid, w in sorted_w:
                        bd = breakdowns.get(uid, {})
                        top_miners.append(
                            {
                                "uid": uid,
                                "weight": round(w, 6),
                                "accuracy": round(bd.get("accuracy", 0), 4),
                                "speed": round(bd.get("speed", 0), 4),
                                "coverage": round(bd.get("coverage", 0), 4),
                                "uptime": round(bd.get("uptime", 0), 4),
                                "attest_validity": round(bd.get("attest_validity", 0), 4),
                                "attest_speed": round(bd.get("attest_speed", 0), 4),
                                "sports_score": round(bd.get("sports_score", 0), 4),
                                "attestation_score": round(bd.get("attestation_score", 0), 4),
                                "queries_total": bd.get("queries_total", 0),
                                "attestations_total": bd.get("attestations_total", 0),
                                "health_responded": bd.get("health_checks_responded", 0),
                                "consecutive_epochs": bd.get("consecutive_epochs", 0),
                            }
                        )
                    if activity is not None:
                        activity.record(
                            ActivityCategory.WEIGHT_SET,
                            f"Set weights for {n_miners} miners (burn={burn_fraction})",
                            n_miners=n_miners,
                            is_active=is_active,
                            burn_fraction=burn_fraction,
                            top_miners=top_miners,
                            total_miners=len(sorted_w),
                        )
                    if telemetry:
                        telemetry.record(
                            "weight_set",
                            f"Set weights for {n_miners} miners (burn={burn_fraction})",
                            n_miners=n_miners,
                            is_active=is_active,
                            burn_fraction=burn_fraction,
                            top_miners=top_miners,
                            total_miners=len(sorted_w),
                            success=True,
                        )
                        telemetry.record_miner_weights(top_miners)
                else:
                    weight_error = neuron.last_weight_error or "Unknown error"
                    if activity is not None:
                        activity.record(
                            ActivityCategory.WEIGHT_SET,
                            f"Failed to set weights for {n_miners} miners: {weight_error}",
                            n_miners=n_miners,
                            is_active=is_active,
                            success=False,
                            error=weight_error,
                        )
                    if telemetry:
                        telemetry.record(
                            "weight_set_failed",
                            f"Failed to set weights for {n_miners} miners: {weight_error}",
                            n_miners=n_miners,
                            is_active=is_active,
                            success=False,
                            error=weight_error,
                        )
                log.info("weights_updated", n_miners=n_miners, active=is_active, success=success)
                # Persist scores to SQLite before resetting epoch metrics
                scorer.persist_all()
                # Reset per-epoch metrics after weight setting (increments
                # consecutive_epochs for miners that participated)
                scorer.reset_epoch()
                last_reset_time = time.monotonic()
            elif time.monotonic() - last_reset_time > MAX_EPOCH_DURATION:
                # Fallback: reset scorer even if weights weren't set to prevent
                # unbounded metric accumulation when weight-setting is stuck
                log.warning(
                    "epoch_reset_fallback",
                    seconds_since_reset=round(time.monotonic() - last_reset_time),
                    msg="Resetting scorer metrics. Weight-setting has not fired in 30 min.",
                )
                scorer.persist_all()
                scorer.reset_epoch()
                last_reset_time = time.monotonic()

            consecutive_errors = 0

        except asyncio.CancelledError:
            log.info("epoch_loop_cancelled")
            return
        except (KeyboardInterrupt, SystemExit):
            raise
        except Exception as e:
            consecutive_errors += 1
            base = min(12 * (2**consecutive_errors), 300)
            backoff = base * (0.5 + random.random())  # jitter: 50-150% of base
            level = "critical" if consecutive_errors >= 10 else "error"
            getattr(log, level)(
                "epoch_error",
                err=str(e),
                error_type=type(e).__name__,
                consecutive=consecutive_errors,
                backoff_s=round(backoff, 1),
                exc_info=True,
            )
            if telemetry:
                telemetry.record(
                    "epoch_error",
                    f"Epoch error ({type(e).__name__}): {e}",
                    error=str(e),
                    error_type=type(e).__name__,
                    consecutive_errors=consecutive_errors,
                    backoff_s=round(backoff, 1),
                )
            await asyncio.sleep(backoff)
            continue

        # Wait for next epoch (~12 seconds per Bittensor block, SN103 tempo = 360 blocks)
        await asyncio.sleep(12)


async def mpc_cleanup_loop(mpc_coordinator: MPCCoordinator) -> None:
    """Periodically remove expired MPC sessions to prevent memory growth."""
    log.info("mpc_cleanup_loop_started")
    while True:
        try:
            await asyncio.sleep(300)  # Every 5 minutes
            removed = mpc_coordinator.cleanup_expired()
            if removed > 0:
                log.info("mpc_sessions_cleaned", count=removed)
        except asyncio.CancelledError:
            log.info("mpc_cleanup_loop_cancelled")
            return
        except Exception as e:
            log.error("mpc_cleanup_error", error=str(e))


async def scorer_persist_loop(scorer: MinerScorer) -> None:
    """Periodically flush scorer state to SQLite between weight-set boundaries.

    Without this, miner lifetime counters only persist on the ~20-minute
    weight-set cadence (or the 30-min fallback reset). A crash or pm2
    restart mid-window loses every query/attestation recorded since the
    last flush — up to 20 minutes of evidence. For a miner on the 50-sample
    bootstrap edge, that can briefly regress them into the zero-weight
    cohort until counters re-accumulate.

    Flushing every 60s caps crash-loss to 60s, which is well within the
    self-healing window. Cheap: one sqlite WAL commit per minute.
    """
    log.info("scorer_persist_loop_started")
    while True:
        try:
            await asyncio.sleep(60)
            scorer.persist_all()
        except asyncio.CancelledError:
            log.info("scorer_persist_loop_cancelled")
            return
        except Exception as e:
            log.error("scorer_persist_error", error=str(e)[:200])


async def validator_sync_loop(syncer: ValidatorSetSyncer) -> None:
    """Periodically sync the on-chain validator set with the Bittensor metagraph."""
    log.info("validator_sync_loop_started")
    while True:
        try:
            await asyncio.sleep(60)  # Check every 60 seconds
            await syncer.sync_once()
        except asyncio.CancelledError:
            log.info("validator_sync_loop_cancelled")
            return
        except Exception as e:
            log.error("validator_sync_error", error=str(e))


async def heartbeat_loop(chain_client: object, signer_address: str) -> None:
    """Periodically post a liveness heartbeat to OutcomeVoting (P0-11, v1596+).

    Keeps this validator in the active-quorum denominator even during dry
    spells without audit activity. Only runs when `activeWindow > 0`
    on-chain (liveness-aware quorum enabled by operator). Polls the flag
    every minute and adjusts cadence: heartbeat every ~activeWindow/4
    blocks → ~15 min on the default 1800-block window.

    Submitting a vote via `submitVote` already ticks the liveness clock,
    so this loop is load-bearing only during periods with no audits. If
    the validator is not currently registered on OV (via `isValidator`),
    the call will revert — we catch + log + skip until re-registered.
    """
    log.info("heartbeat_loop_started", signer=signer_address)
    # Block cadence: Base ~2s per block → ~30 blocks/minute. Poll every 60s.
    # Actual heartbeat fires when `block.number - lastActiveBlock > window/4`.
    while True:
        try:
            await asyncio.sleep(60)

            # Only heartbeat if liveness-aware quorum is enabled on-chain
            if not getattr(chain_client, "can_write", False):
                continue
            window = await chain_client.ov_active_window()
            if window == 0:
                continue

            # Check if we're approaching stale (> window/4 blocks since last)
            current_block = int(await chain_client._w3.eth.block_number)
            last_active = await chain_client.ov_last_active_block(signer_address)
            blocks_since = current_block - last_active if last_active > 0 else window * 2
            if blocks_since <= window // 4:
                log.debug(
                    "heartbeat_skip_fresh",
                    blocks_since=blocks_since,
                    window=window,
                )
                continue

            # Post heartbeat
            tx_hash = await chain_client.heartbeat()
            log.info(
                "heartbeat_posted",
                tx=tx_hash,
                blocks_since=blocks_since,
                window=window,
            )
        except asyncio.CancelledError:
            log.info("heartbeat_loop_cancelled")
            return
        except Exception as e:
            err = str(e)
            if "NotValidator" in err:
                log.debug("heartbeat_skip_not_registered", err=err[:120])
            else:
                log.error("heartbeat_error", err=err[:200])


async def run_server(app: object, host: str, port: int) -> None:
    """Run uvicorn as an async task.

    ``proxy_headers=True`` + ``forwarded_allow_ips`` (MAINNET_BLOCKERS
    P1-26, 2026-04-18): when the validator sits behind the nginx
    wildcard router (scripts/nginx-wildcard-djinn-gg.conf) or any local
    reverse proxy, uvicorn rewrites ``request.client.host`` from the
    loopback source to the X-Forwarded-For / X-Real-IP value. Without
    this, ``/v1/burn/verify`` saw 127.0.0.1 for every HTTPS request and
    the IP allowlist was a no-op. Operators who put the validator on a
    multi-hop proxy chain must set ``DJINN_FORWARDED_ALLOW_IPS`` to the
    comma-separated list of trusted proxy IPs (default: ``127.0.0.1``).
    """
    forwarded_allow = os.getenv("DJINN_FORWARDED_ALLOW_IPS", "127.0.0.1")
    config = uvicorn.Config(
        app,
        host=host,
        port=port,
        log_level="info",
        timeout_graceful_shutdown=10,
        timeout_keep_alive=65,
        proxy_headers=True,
        forwarded_allow_ips=forwarded_allow,
    )
    server = uvicorn.Server(config)
    await server.serve()


async def async_main() -> None:
    """Start validator with concurrent API server and epoch loop."""
    config = Config()
    warnings = config.validate()
    for w in warnings:
        log.warning("config_warning", msg=w)

    # Initialize components — SQLite persistence for key shares and attestation log
    from pathlib import Path

    data_dir = Path(config.data_dir).resolve()
    data_dir.mkdir(parents=True, exist_ok=True)
    share_store = ShareStore(db_path=str(data_dir / "shares.db"))
    attestation_log = AttestationLog(db_path=str(data_dir / "attestations.db"))
    purchase_orch = PurchaseOrchestrator(share_store, db_path=str(data_dir / "purchases.db"))
    # Phase 1 of MPC batch settlement: persistent ledger of per-line
    # BPA/WPA vectors committed at purchase time. Values are stored
    # for future audit settlement use; nothing reads them yet in
    # production. See docs/specs/mpc-batch-settlement.md.
    from djinn_validator.core.purchase_odds_ledger import PurchaseOddsLedger

    purchase_odds_ledger = PurchaseOddsLedger(
        db_path=str(data_dir / "purchase_odds.db"),
    )
    espn_client = ESPNClient()
    outcome_attestor = OutcomeAttestor(
        espn_client=espn_client,
        db_path=str(data_dir / "signal_registrations.db"),
        chain_id=config.base_chain_id,
        registry_address=config.line_outcome_registry_address,
        private_key_hex=config.base_validator_private_key or None,
    )
    audit_set_store = AuditSetStore(
        db_path=str(data_dir / "audit_set_store.db"),
    )
    # Consensus circuit breaker (CUSUM tracker for sustained miner
    # deviation from consensus). Persistent so a validator restart
    # does not erase pending flags. The scorer wires this in and
    # zeros weight for flagged miners when DJINN_FF_CIRCUIT_BREAKER
    # is on. See project_consensus_circuit_breaker memory for design.
    from djinn_validator.core import error_reports as err_reports_module
    from djinn_validator.core.circuit_breaker import ConsensusCircuitBreaker

    circuit_breaker = ConsensusCircuitBreaker(
        db_path=str(data_dir / "circuit_breaker.db"),
    )
    # v1743: durable feedback queue. Pre-v1743 the validator held reports in
    # an in-process ring buffer and silently dropped them on restart or when
    # GITHUB_ERROR_TOKEN was unset. The persistent queue + retry worker fixes
    # both gaps; existing queued reports drain automatically once the
    # operator provisions the token.
    err_reports_module.configure(str(data_dir / "error_reports.db"))

    # v1744: durable outbound gossip retry queue. v1721 in-memory retries
    # cap at ~6 min; if a peer is offline longer than that during a gossip
    # window, the BPA/WPA payload is permanently lost on that peer.
    # gossip_outbox catches stragglers and retries up to 24h with
    # exponential backoff, so peers that recover late still receive the
    # data and can participate in the audit. Wallet+signer wired below
    # once neuron is available.
    from djinn_validator.core import gossip_outbox as gossip_outbox_module

    gossip_outbox_module.configure(str(data_dir / "gossip_outbox.db"))
    scorer = MinerScorer(
        db_path=str(data_dir / "miner_scores.db"),
        circuit_breaker=circuit_breaker,
    )
    activity = ActivityBuffer()

    # Persistent telemetry — stores all events to SQLite
    telemetry_path = os.getenv("TELEMETRY_DB", str(data_dir / "validator_telemetry.db"))
    telemetry = TelemetryStore(telemetry_path)
    telemetry.record(
        "startup",
        f"Validator v{__version__} starting",
        version=__version__,
        network=config.bt_network,
        netuid=config.bt_netuid,
    )

    chain_client = ChainClient(
        rpc_url=config.base_rpc_url,
        escrow_address=config.escrow_address,
        signal_address=config.signal_commitment_address,
        account_address=config.account_address,
        outcome_voting_address=config.outcome_voting_address,
        usdc_address=config.usdc_address,
        credit_ledger_address=config.credit_ledger_address,
        audit_address=config.audit_address,
        collateral_address=config.collateral_address,
        line_outcome_registry_address=config.line_outcome_registry_address,
        private_key=config.base_validator_private_key,
        chain_id=config.base_chain_id,
    )

    # v1747 Phase 7b: build the LineOutcomeRegistry submitter from the chain
    # client's web3 instance. .configured is False (and submit() short-circuits)
    # whenever the validator key is unset, so observer-only nodes silently
    # skip submission without errors.
    from djinn_validator.chain.line_registry import LineOutcomeSubmitter as _LineOutcomeSubmitter

    line_outcome_submitter = _LineOutcomeSubmitter(
        w3=chain_client._w3,
        registry_address=config.line_outcome_registry_address,
        private_key_hex=config.base_validator_private_key or None,
        chain_id=config.base_chain_id,
        nonce_lock=chain_client._nonce_lock,
    )

    # v1747 Phase 7c: peer attestation store for gossip-driven sig
    # aggregation. Persisted to SQLite so the bundle survives validator
    # restarts and one slow peer doesn't reset our progress toward
    # threshold. Wired into create_app so /v1/outcomes/gossip's receive
    # path can _store_peer_attestation_sigs into it, and into the
    # epoch_loop so submit_threshold_lines can query it.
    from djinn_validator.core.peer_attestations import PeerAttestationStore as _PeerAttestationStore

    peer_attestation_store = _PeerAttestationStore(
        db_path=str(data_dir / "peer_attestations.db"),
    )

    # MAINNET_BLOCKERS P1-23: hard-fail on chain_id mismatch. A validator whose
    # RPC points at the wrong chain will sign wrong-chain transactions that
    # silently drop — it appears healthy but contributes nothing to quorum.
    # Skip the check in pure-read deployments (no signer, never writes) and
    # in test environments that wire a mock RPC.
    if config.base_validator_private_key and os.getenv("DJINN_SKIP_CHAIN_ID_CHECK") != "1":
        try:
            await chain_client.verify_chain_id()
        except RuntimeError as e:
            log.error("chain_id_mismatch_fatal", msg=str(e))
            telemetry.record("chain_id_mismatch_fatal", str(e))
            raise SystemExit(1) from e
        except Exception as e:
            log.warning(
                "chain_id_verify_rpc_unreachable",
                err=str(e)[:200],
                msg="RPC unreachable at startup — proceeding but tx sends may fail; operator should verify connectivity",
            )

    # Share recovery (project_share_recovery_design_2026_05_03.md): load or generate
    # this validator's x25519 encryption keypair, then publish the pubkey on chain
    # if the live OV supports the feature and the on-chain entry is stale or absent.
    # Genius clients read the on-chain pubkey to NaCl-box per-validator Shamir
    # shares so peer-forwarding can hold encrypted blobs without decrypt capability.
    encryption_privkey: bytes | None = None
    encryption_pubkey: bytes | None = None
    if config.base_validator_private_key:
        try:
            encryption_privkey, encryption_pubkey = load_or_generate_keypair(data_dir)
            if await chain_client.supports_share_recovery():
                signer_addr = chain_client.signer_address()
                if signer_addr:
                    on_chain = await chain_client.get_encryption_pubkey(signer_addr)
                    if on_chain != encryption_pubkey:
                        log.info(
                            "encryption_pubkey_publishing",
                            local=encryption_pubkey.hex(),
                            on_chain=on_chain.hex(),
                        )
                        try:
                            tx = await chain_client.set_encryption_pubkey(encryption_pubkey)
                            log.info("encryption_pubkey_published", tx=tx)
                        except Exception as e:
                            log.warning(
                                "encryption_pubkey_publish_failed",
                                err=str(e)[:200],
                                msg="setEncryptionPubkey failed (likely not yet a registered OV validator); will retry on next startup",
                            )
                    else:
                        log.info("encryption_pubkey_in_sync", pubkey=encryption_pubkey.hex())
            else:
                log.info(
                    "share_recovery_feature_not_live",
                    msg="OV impl does not yet expose FEATURE_SHARE_RECOVERY; skipping pubkey publish",
                )
        except Exception as e:
            log.warning("encryption_key_setup_failed", err=str(e)[:200])

    # Initialize Bittensor neuron
    neuron = DjinnValidator(
        netuid=config.bt_netuid,
        network=config.bt_network,
        wallet_name=config.bt_wallet_name,
        hotkey_name=config.bt_wallet_hotkey,
        axon_port=config.api_port,
        external_ip=config.external_ip or None,
        external_port=config.external_port or None,
    )

    bt_ok = neuron.setup()
    if not bt_ok and config.bt_network in ("finney", "mainnet"):
        log.error(
            "bt_setup_failed_production",
            msg="Wallet/subtensor setup failed on production network — refusing to start. "
            'Check that your coldkeypub.txt is valid JSON: {"ss58Address": "5Your..."}',
        )
        raise SystemExit(1)
    elif not bt_ok:
        log.warning(
            "running_without_bittensor",
            msg="Validator API will start but no weights will be set",
        )

    # Egress publish is launched as a background task (one-shot at startup,
    # then re-runs each epoch so the FIFO accumulates new outbound IPs).
    # See running_tasks below.

    mpc_coordinator = MPCCoordinator()

    # Create FastAPI app
    app = create_app(
        share_store=share_store,
        purchase_orch=purchase_orch,
        outcome_attestor=outcome_attestor,
        chain_client=chain_client,
        neuron=neuron if bt_ok else None,
        mpc_coordinator=mpc_coordinator,
        rate_limit_capacity=config.rate_limit_capacity,
        rate_limit_rate=config.rate_limit_rate,
        mpc_availability_timeout=config.mpc_availability_timeout,
        shares_threshold=config.shares_threshold,
        attestation_log=attestation_log,
        fallback_miner_url=config.fallback_miner_url or None,
        scorer=scorer,
        activity_buffer=activity,
        audit_set_store=audit_set_store,
        telemetry=telemetry,
        purchase_odds_ledger=purchase_odds_ledger,
        encryption_privkey=encryption_privkey,
        signer_address=chain_client.signer_address(),
        peer_attestation_store=peer_attestation_store,
        line_outcome_chain_id=config.base_chain_id,
        line_outcome_registry_address=config.line_outcome_registry_address,
    )

    log.info(
        "validator_starting",
        version=__version__,
        host=config.api_host,
        port=config.api_port,
        netuid=config.bt_netuid,
        bt_network=config.bt_network,
        bt_connected=bt_ok,
        rpc_url=_sanitize_url(config.base_rpc_url),
        shares_held=share_store.count,
        settlement_enabled=chain_client.can_write,
        settlement_address=chain_client.validator_address or "none",
        log_format=os.getenv("LOG_FORMAT", "console"),
    )

    # One-shot startup probe: is our signer EOA registered in OutcomeVoting?
    # If not, every submitVote will revert with NotValidator and quality-score
    # voting will silently fail. Fail loud at boot so operators notice.
    async def _probe_settlement_registration() -> None:
        if not chain_client.can_write or not chain_client.validator_address:
            return
        try:
            registered = await chain_client.is_registered_validator()
        except Exception as e:
            log.warning("settlement_registration_probe_failed", err=str(e)[:200])
            return
        if registered is None:
            log.warning(
                "settlement_registration_probe_rpc_flap",
                msg="RPC call to isValidator() failed; skipping diagnosis to avoid false missing_bootstrap",
            )
            return
        if registered:
            log.info(
                "settlement_registration_ok",
                signer=chain_client.validator_address,
                ov=config.outcome_voting_address,
            )
            return

        # Not registered on the configured OV. Two root causes:
        #   (a) The signer genuinely isn't bootstrapped yet → operator needs
        #       addValidator via timelock.
        #   (b) The .env has a stale OUTCOME_VOTING_ADDRESS override pointing
        #       at an old/empty OV proxy → signer IS registered on canonical,
        #       just not where we're reading from.
        # Cross-reference against canonical to distinguish (2026-04-18).
        configured = config.outcome_voting_address
        is_canonical = configured.lower() == CANONICAL_OUTCOME_VOTING_ADDRESS.lower()
        on_canonical = False
        if not is_canonical:
            try:
                on_canonical = await chain_client.is_registered_validator_at(CANONICAL_OUTCOME_VOTING_ADDRESS)
            except Exception as e:
                log.debug("canonical_probe_failed", err=str(e)[:200])

        if on_canonical is None:
            log.warning(
                "settlement_registration_canonical_rpc_flap",
                msg="Canonical OV RPC check failed; skipping stale-env vs missing-bootstrap diagnosis",
            )
            return

        if on_canonical:
            log.error(
                "settlement_registration_stale_env",
                signer=chain_client.validator_address,
                configured_ov=configured,
                canonical_ov=CANONICAL_OUTCOME_VOTING_ADDRESS,
                msg=(
                    "Our signer IS registered on the canonical OutcomeVoting "
                    f"({CANONICAL_OUTCOME_VOTING_ADDRESS}) but .env has a stale "
                    f"OUTCOME_VOTING_ADDRESS={configured}. Votes submitted "
                    "against the stale address will not reach quorum with other "
                    "validators. Remove the OUTCOME_VOTING_ADDRESS override "
                    "from .env (or set it to the canonical value) and restart."
                ),
            )
            telemetry.record(
                "settlement_registration_stale_env",
                "Stale OUTCOME_VOTING_ADDRESS in .env — remove override and restart",
                signer=chain_client.validator_address,
                configured_ov=configured,
                canonical_ov=CANONICAL_OUTCOME_VOTING_ADDRESS,
            )
        else:
            log.error(
                "settlement_registration_missing",
                signer=chain_client.validator_address,
                configured_ov=configured,
                msg=(
                    "Our signer EOA is NOT registered in OutcomeVoting. "
                    "Every submitVote will revert with NotValidator. "
                    "Ask the operator to run AddValidatorSigner.s.sol with "
                    "SIGNER=our EOA (or ScheduleRegisterValidators for initial "
                    "bootstrap) and execute after the timelock delay."
                ),
            )
            telemetry.record(
                "settlement_registration_missing",
                "Signer EOA not registered in OutcomeVoting — votes will revert",
                signer=chain_client.validator_address,
            )

    # Bootstrap audit sets from on-chain state in the background.
    # Initial run at startup scans 1200+ shares (~5 min). After that, a periodic
    # rescan runs every REBOOTSTRAP_INTERVAL_S so new purchases get indexed
    # without requiring a validator restart. Without the periodic pass,
    # audit_set_store is only populated once — any signal purchased after
    # startup never becomes part of an audit set, so no votes, no settlements.
    async def _run_bootstrap() -> None:
        from djinn_validator.chain.subgraph import get_default_subgraph_client
        from djinn_validator.core.audit_bootstrap import bootstrap_audit_sets

        # v1709: optional subgraph fast path. If DJINN_SUBGRAPH_URL is
        # unset the client is None and bootstrap stays on the RPC scan
        # path byte-identically. When set + fresh, per-pair bootstrap
        # uses one GraphQL query instead of ~3-5 RPC calls per purchase.
        subgraph_client = get_default_subgraph_client()
        rebootstrap_interval_s = int(os.environ.get("REBOOTSTRAP_INTERVAL_S", "900"))
        first_run = True
        while True:
            try:
                pairs_loaded = await bootstrap_audit_sets(
                    chain_client=chain_client,
                    share_store=share_store,
                    audit_set_store=audit_set_store,
                    outcome_attestor=outcome_attestor,
                    subgraph=subgraph_client,
                    # v1710: when audit_bootstrap finds new (G,I,sig,pid)
                    # tuples, gossip to peers via /v1/audit/gossip so the
                    # fleet's audit_set_store views converge in seconds
                    # rather than waiting for each validator's own scan.
                    # Receivers verify the tuple against chain RPC before
                    # adding, so a malicious peer can't poison.
                    neuron=neuron,
                )
                log.info(
                    "audit_bootstrap_done",
                    pairs=pairs_loaded,
                    first_run=first_run,
                    next_run_s=rebootstrap_interval_s,
                    subgraph_configured=subgraph_client is not None,
                )

                # v1740: BPA/WPA backfill at bootstrap time. The existing
                # _prefetch_missing_purchase_odds_from_peers helper only
                # runs INSIDE try_shadow_distributed_settlement, which
                # only fires when the validator coordinates a particular
                # audit_set. Validators that miss the original purchase
                # gossip (offline at commit time, dropped 5xx, etc.) have
                # no other path to the data and end up abstaining at
                # settle time forever. By pulling at bootstrap, every
                # validator backfills any gap before settle attempts run.
                # Gated by feature flag so operators can disable for
                # debugging; default ON. peer_404 reduces measurably
                # only when peers HAVE the data — if the originating
                # validator's gossip never landed anywhere, this is a
                # no-op (counter logs "all_peers_404" so we know).
                if os.environ.get("DJINN_FF_BOOTSTRAP_BPA_BACKFILL", "1") == "1":
                    try:
                        await _bootstrap_pull_missing_purchase_odds()
                    except Exception as e:
                        log.warning(
                            "bootstrap_bpa_backfill_failed",
                            err=str(e)[:200],
                        )
            except Exception as e:
                log.warning("audit_bootstrap_failed", err=str(e)[:200])
            first_run = False
            if rebootstrap_interval_s <= 0:
                return
            await asyncio.sleep(rebootstrap_interval_s)

    async def _bootstrap_pull_missing_purchase_odds() -> None:
        """v1740: Backfill BPA/WPA from peers for ready-for-settlement
        audit sets at bootstrap time.

        Constructs a single MPCOrchestrator and calls the existing
        _prefetch_missing_purchase_odds_from_peers helper for each
        ready audit_set. Each call is bounded at 60s; total wall time
        is bounded by len(ready_sets) * 60s in worst case, but typical
        runs finish in seconds because most audit_sets either have all
        BPA/WPA already (skip) or have none recoverable (early bail).

        This catches gaps that try_shadow_distributed_settlement would
        not otherwise see: when the recoverable abstain counter throttles
        a pair, settle skips it for the rebootstrap window, so peer-pull
        for that pair never runs in the steady state. Bootstrap-time
        peer-pull is the only opportunity to backfill before another
        validator coordinates the next attempt.

        v1741: aligned the iteration set with get_ready_sets(), which
        applies the permanent_abstain filter. Empirically (UID 0) the
        legacy 71-batch backlog returns peer_404 100% on every peer,
        so iterating them was wasted work; if an admin re-admits a pair
        the existing shadow-settle path will lazily pull on the first
        try, restoring the same latency as before v1740.
        """
        from djinn_validator.core.mpc_coordinator import MPCCoordinator
        from djinn_validator.core.mpc_orchestrator import MPCOrchestrator

        ready_sets = audit_set_store.get_ready_sets()
        if not ready_sets:
            log.info("bootstrap_bpa_backfill_skip", reason="no_ready_sets")
            return

        signer_addr = chain_client.signer_address() if chain_client else None
        orch = MPCOrchestrator(
            coordinator=MPCCoordinator(),
            neuron=neuron,
            threshold=2,  # threshold isn't used in the prefetch path
            chain_client=chain_client,
            encryption_privkey=encryption_privkey,
            signer_address=signer_addr,
            outcome_attestor=outcome_attestor,
            audit_set_store=audit_set_store,
        )

        total_fetched = 0
        sets_processed = 0
        for audit_set in ready_sets:
            try:
                fetched = await asyncio.wait_for(
                    orch._prefetch_missing_purchase_odds_from_peers(  # noqa: SLF001
                        audit_set=audit_set,
                        purchase_odds_ledger=purchase_odds_ledger,
                    ),
                    timeout=60.0,
                )
                total_fetched += fetched
                sets_processed += 1
            except TimeoutError:
                log.warning(
                    "bootstrap_bpa_backfill_set_timeout",
                    genius=audit_set.genius_address,
                    idiot=audit_set.idiot_address,
                )
            except Exception as e:
                log.warning(
                    "bootstrap_bpa_backfill_set_failed",
                    genius=audit_set.genius_address,
                    idiot=audit_set.idiot_address,
                    err=str(e)[:200],
                )
        log.info(
            "bootstrap_bpa_backfill_complete",
            ready_sets=len(ready_sets),
            sets_processed=sets_processed,
            rows_fetched=total_fetched,
        )

    # Run API server, epoch loop, MPC cleanup, watchtower, and validator sync concurrently
    # v1743: drain the persistent feedback queue. start_worker is idempotent
    # and a no-op if no asyncio loop is running yet; safe to call here before
    # the tasks list is materialized.
    err_reports_module.start_worker()

    # v1744: wire the live wallet into the gossip outbox so the worker can
    # sign retries with the validator's hotkey, then start the drain loop.
    # The signer captures `wallet` lexically; if the wallet rotates (rare),
    # operators restart and a fresh closure is built here.
    if neuron is not None and getattr(neuron, "wallet", None) is not None:
        from djinn_validator.api.middleware import create_signed_headers as _sign

        _wallet = neuron.wallet

        def _gossip_outbox_signer(endpoint: str, body: bytes) -> dict[str, str]:
            return _sign(endpoint, body, _wallet)

        gossip_outbox_module.configure(
            str(data_dir / "gossip_outbox.db"),
            signer=_gossip_outbox_signer,
        )
    gossip_outbox_module.start_worker()

    running_tasks = [
        asyncio.create_task(run_server(app, config.api_host, config.api_port)),
        asyncio.create_task(mpc_cleanup_loop(mpc_coordinator)),
        asyncio.create_task(scorer_persist_loop(scorer)),  # 60s flush cadence
        asyncio.create_task(watchtower_loop(package_dir=Path(__file__).resolve().parent.parent)),
        asyncio.create_task(_run_bootstrap()),  # Background: ~5 min, doesn't block startup
        asyncio.create_task(_probe_settlement_registration()),
    ]
    if bt_ok:
        running_tasks.append(
            asyncio.create_task(
                epoch_loop(
                    neuron,
                    scorer,
                    share_store,
                    outcome_attestor,
                    chain_client,
                    activity,
                    audit_set_store,
                    config.bt_burn_fraction,
                    espn_client=espn_client,
                    shares_threshold=config.shares_threshold,
                    telemetry=telemetry,
                    purchase_odds_ledger=purchase_odds_ledger,
                    encryption_privkey=encryption_privkey,
                    line_outcome_submitter=line_outcome_submitter,
                    peer_attestation_store=peer_attestation_store,
                )
            )
        )
        # Validator set sync: discover peers via metagraph, propose on-chain changes
        if chain_client.can_write:
            syncer = ValidatorSetSyncer(chain_client, neuron)
            running_tasks.append(asyncio.create_task(validator_sync_loop(syncer)))

            # P0-11 liveness-aware quorum heartbeat (v1596+): keeps this validator
            # in the active-quorum denominator during dry spells. No-op when
            # on-chain activeWindow=0 (feature disabled). Signer address is the
            # EVM address derived from the configured private key.
            signer_addr = getattr(chain_client, "_validator_address", None)
            if signer_addr:
                running_tasks.append(asyncio.create_task(heartbeat_loop(chain_client, signer_addr)))

        # Egress IP commitment: re-publishes each epoch so the FIFO can
        # accumulate up to MAX_IPS recent outbound IPs without manual env edits.
        from djinn_validator.utils.egress_publisher import egress_publish_loop

        running_tasks.append(asyncio.create_task(egress_publish_loop(neuron)))

    shutdown_event = asyncio.Event()

    def _shutdown(sig: signal.Signals) -> None:
        log.info("shutdown_signal", signal=sig.name)
        shutdown_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, _shutdown, sig)

    await shutdown_event.wait()
    log.info("shutting_down")
    telemetry.record("shutdown", "Validator shutting down")
    for t in running_tasks:
        t.cancel()
    try:
        await asyncio.wait_for(
            asyncio.gather(*running_tasks, return_exceptions=True),
            timeout=15.0,
        )
    except TimeoutError:
        log.warning("shutdown_timeout", msg="Tasks did not finish within 15s")
    try:
        scorer.persist_all()
        log.info("scorer_persisted_on_shutdown")
    except Exception as e:
        log.warning("scorer_persist_error", error=str(e))
    try:
        await outcome_attestor.close()
    except Exception as e:
        log.warning("outcome_attestor_close_error", error=str(e))
    try:
        await chain_client.close()
    except Exception as e:
        log.warning("chain_client_close_error", error=str(e))
    try:
        removed = mpc_coordinator.cleanup_expired()
        if removed:
            log.info("mpc_sessions_cleaned_on_shutdown", removed=removed)
    except Exception as e:
        log.warning("mpc_cleanup_error", error=str(e))
    try:
        from djinn_validator.core.ot_network import shutdown_modexp_pool

        shutdown_modexp_pool()
    except Exception as e:
        log.warning("modexp_pool_shutdown_error", error=str(e))
    try:
        purchase_orch.close()
    except Exception as e:
        log.warning("purchase_orch_close_error", error=str(e))
    try:
        share_store.close()
    except Exception as e:
        log.warning("share_store_close_error", error=str(e))
    try:
        attestation_log.close()
    except Exception as e:
        log.warning("attestation_log_close_error", error=str(e))
    log.info("shutdown_complete")


def _kill_stale_port_holders(port: int) -> None:
    """Kill any orphan processes holding our port from a previous crash.

    After an unclean shutdown (e.g. pm2 SIGKILL before graceful shutdown
    completes), uvicorn worker threads can survive as orphans holding the
    socket. The new process can't bind and silently fails. This detects
    and kills them before we start.
    """
    import subprocess

    try:
        result = subprocess.run(
            ["lsof", "-ti", f":{port}"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode != 0 or not result.stdout.strip():
            return
        stale_pids = [int(p) for p in result.stdout.strip().split("\n") if p.strip()]
        my_pid = os.getpid()
        stale_pids = [p for p in stale_pids if p != my_pid]
        if not stale_pids:
            return
        log.warning("killing_stale_port_holders", port=port, pids=stale_pids)
        for pid in stale_pids:
            try:
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        # Brief pause for the OS to release the socket
        time.sleep(0.5)
    except Exception as e:
        log.warning("stale_port_check_failed", error=str(e))


def main() -> None:
    """Start the Djinn validator."""
    _kill_stale_port_holders(int(os.getenv("DJINN_PORT", "8421")))
    asyncio.run(async_main())


if __name__ == "__main__":
    main()
