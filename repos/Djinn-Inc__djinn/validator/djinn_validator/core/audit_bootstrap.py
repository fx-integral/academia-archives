"""Bootstrap audit sets from on-chain state.

On startup the validator has no in-memory audit sets because
AuditSetStore is ephemeral.  This module reconstructs them from
on-chain truth (Account.getPurchaseIds + Escrow.getPurchase) using
the genius addresses already persisted in the ShareStore.

Also registers signals with the OutcomeAttestor by parsing the
on-chain decoyLines (which contain full JSON with sport, event_id,
home_team, away_team, market, line, side, price, commence_time).

Flow:
  1. Query ShareStore for all distinct genius addresses
  2. Scan SignalPurchased events (or use share signal_ids) to find buyers
  3. For each (genius, idiot) pair: read current cycle + purchase IDs
  4. Populate AuditSetStore with signal data from chain
  5. Parse decoy line JSON and register signals with OutcomeAttestor
  6. The normal epoch loop then resolves outcomes and triggers settlement
"""

from __future__ import annotations

import asyncio
import json
import os
from typing import TYPE_CHECKING, Any

import structlog

if TYPE_CHECKING:
    from djinn_validator.chain.contracts import ChainClient
    from djinn_validator.chain.subgraph import SubgraphClient
    from djinn_validator.core.audit_set import AuditSetStore
    from djinn_validator.core.outcomes import OutcomeAttestor
    from djinn_validator.core.shares import ShareStore

log = structlog.get_logger()

# How far back to scan SignalPurchased events at bootstrap. 60 days of
# Base Sepolia (~2s blocks) = ~2.6M blocks. Any signal older than this
# has already either settled or been abandoned; stale shares.db rows
# that never got an on-chain signal are pure noise we want to skip.
_BOOTSTRAP_PURCHASE_SCAN_BLOCKS = int(os.getenv("DJINN_BOOTSTRAP_SCAN_BLOCKS", "2600000"))

# v1730: hard floor on bootstrap. When set, signals/purchases at or
# before this block are skipped during bootstrap entirely. Use this to
# discard a legacy backlog of pre-v1722-bundle-retry pairs whose data is
# fragmented across the fleet (some validators are missing shares /
# BPA/WPA and recovery returns peer_404 because peers also missed the
# original bundle). Setting this to "the block after the last known-bad
# cohort" lets the validator skip churn on un-settleable pairs without
# losing future-cohort coverage. Default 0 = disabled (legacy behavior).
_BOOTSTRAP_MIN_BLOCK = int(os.getenv("DJINN_BOOTSTRAP_MIN_BLOCK", "0"))

# Pre-V6 purchases (legacy Escrow.purchase()) leave both Merkle roots at
# 0x00..00 on-chain. purchaseV2() commits a non-zero BPA + WPA root per
# vector. v1577's abstain-on-missing-BPA/WPA rule refuses to settle any
# batch containing a zero-root signal, so loading those signals into
# audit_set_store is pure waste — they can never reach a batch. We filter
# them out at bootstrap so audit_set membership is (a) derivable from
# chain alone (every validator computes the same set) and (b) only
# contains signals that could actually settle.
_ZERO_ROOT = b"\x00" * 32


async def bootstrap_audit_sets(
    chain_client: ChainClient,
    share_store: ShareStore,
    audit_set_store: AuditSetStore,
    outcome_attestor: OutcomeAttestor | None = None,
    subgraph: SubgraphClient | None = None,
    neuron: Any | None = None,
) -> int:
    """Populate audit_set_store from on-chain state.

    If outcome_attestor is provided, also registers signals by parsing
    the on-chain decoyLines JSON so the epoch loop can resolve outcomes.

    Returns the number of audit sets populated.
    """
    # Step 1: Get all distinct (genius_address, signal_id) pairs from shares DB.
    # v1585 (2026-04-22): this is the LOCAL-only subset. Each validator holds
    # shares for a different subset of signals under Shamir fan-out, so using
    # this as the authoritative genius lookup caused audit_set divergence
    # across the fleet (different pairs/pids produced different batchKey ⇒
    # 4-of-6 OV quorum unreachable). We now merge with on-chain SignalCommitted
    # events below so every validator loads the identical pair set.
    genius_signals = _get_genius_signals(share_store)

    # Step 2: Find (genius, idiot) pairs via a bounded SignalPurchased event
    # scan. One chunked eth_getLogs call replaces ~1349 per-signal RPC probes
    # that were each reverting with SignalNotFound for stale shares.db rows.
    # Fallback: if the event scan fails, fall through to the per-signal path
    # so we don't silently lose pairs on an RPC outage.
    pairs: set[tuple[str, str]] = set()
    # When the event scan succeeds we know the complete set of purchase IDs
    # that have actually emitted SignalPurchased in the scan window. Account's
    # getPairPurchaseIds returns ALL historical pids including ancient pre-V6
    # entries that never had resolvable outcomes; if we load those into
    # audit_set_store they sit unresolved and block throughput forever.
    # Scope loading to pids we've actually observed to guarantee "forward
    # progress only" as of user directive 2026-04-20.
    valid_pids_by_pair: dict[tuple[str, str], set[int]] = {}
    local_signal_count = len(genius_signals)
    log.info("audit_bootstrap_scanning", local_signals=local_signal_count)

    pre_filter_ok = False
    try:
        latest_block = await chain_client.get_current_block()
        scan_from = max(0, latest_block - _BOOTSTRAP_PURCHASE_SCAN_BLOCKS)
        # v1730: hard floor — operator can pin scan_from forward to skip
        # legacy unsettleable cohorts. Logs explicitly when applied so the
        # operator can audit what got discarded.
        if _BOOTSTRAP_MIN_BLOCK > 0 and _BOOTSTRAP_MIN_BLOCK > scan_from:
            log.info(
                "audit_bootstrap_min_block_floor",
                env_min_block=_BOOTSTRAP_MIN_BLOCK,
                scan_window_floor=scan_from,
                effective_floor=_BOOTSTRAP_MIN_BLOCK,
                latest_block=latest_block,
            )
            scan_from = _BOOTSTRAP_MIN_BLOCK

        # v1585: merge on-chain SignalCommitted events into the genius lookup.
        # SignalCommitted's `genius` field is indexed; one eth_getLogs chunk
        # yields signal_id → genius for the ENTIRE fleet view, not just the
        # local validator's share subset. This is what makes audit_set
        # deterministic across validators. Local shares.db still wins on
        # conflict (it's a superset for legacy rows that predate the event
        # scan window), but the on-chain scan fills every signal the local
        # validator doesn't hold a share for.
        committed_map: dict[str, str] = {}
        try:
            commit_events = await chain_client.get_recent_signal_events(
                from_block=scan_from,
                to_block=latest_block,
            )
            for ev in commit_events:
                sig_id = ev.get("signal_id")
                genius_addr = ev.get("genius")
                if sig_id is None or not genius_addr:
                    continue
                committed_map[str(sig_id)] = str(genius_addr).lower()
            log.info(
                "audit_bootstrap_commit_scan",
                from_block=scan_from,
                to_block=latest_block,
                events=len(commit_events),
                unique_signals=len(committed_map),
            )
        except Exception as e:
            log.warning(
                "audit_bootstrap_commit_scan_failed",
                err=str(e)[:200],
            )

        merged_signals: dict[str, str] = dict(committed_map)
        for sid, g in genius_signals.items():
            merged_signals.setdefault(sid, g.lower() if g else g)
        added_from_chain = len(merged_signals) - local_signal_count
        log.info(
            "audit_bootstrap_genius_merged",
            local=local_signal_count,
            chain=len(committed_map),
            merged=len(merged_signals),
            added_from_chain=added_from_chain,
        )

        purchase_events = await chain_client.get_recent_signal_purchases(
            from_block=scan_from,
            to_block=latest_block,
        )
        log.info(
            "audit_bootstrap_event_scan",
            from_block=scan_from,
            to_block=latest_block,
            events=len(purchase_events),
        )
        orphaned_events = 0
        for ev in purchase_events:
            sig_id = ev.get("signal_id")
            buyer = ev.get("buyer")
            if not sig_id or not buyer:
                continue
            genius = merged_signals.get(str(sig_id))
            if genius is None:
                orphaned_events += 1
                continue
            pair_key = (genius.lower(), buyer.lower())
            pairs.add(pair_key)
            pid = int(ev.get("purchase_id") or 0)
            if pid:
                valid_pids_by_pair.setdefault(pair_key, set()).add(pid)
        log.info(
            "audit_bootstrap_event_pairs",
            pairs=len(pairs),
            events=len(purchase_events),
            orphaned=orphaned_events,
            pids_with_id=sum(len(s) for s in valid_pids_by_pair.values()),
        )
        pre_filter_ok = True
    except Exception as e:
        log.warning(
            "audit_bootstrap_event_scan_failed",
            err=str(e)[:200],
        )

    # Legacy fallback: only engage if event scan failed. The per-signal
    # scan is slow (1 RPC per row, ~10 min for 1349 shares) and triggers
    # SignalNotFound reverts for stale rows, but it's the only way to
    # recover when event logs are unavailable.
    if not pre_filter_ok:
        batch_size = 5
        signal_list = list(genius_signals.items())
        errors = 0

        for i in range(0, len(signal_list), batch_size):
            batch = signal_list[i : i + batch_size]
            tasks = []
            for signal_id, genius_addr in batch:
                tasks.append(_get_buyers_for_signal(chain_client, signal_id, genius_addr))

            results = await asyncio.gather(*tasks, return_exceptions=True)
            for result in results:
                if isinstance(result, Exception):
                    errors += 1
                    continue
                for genius, idiot in result:
                    pairs.add((genius.lower(), idiot.lower()))

            processed = min(i + batch_size, len(signal_list))
            if processed % 100 < batch_size:
                log.info(
                    "audit_bootstrap_progress",
                    processed=processed,
                    total=len(signal_list),
                    pairs_found=len(pairs),
                    errors=errors,
                )

            if i + batch_size < len(signal_list):
                await asyncio.sleep(1.0)

    if not pairs:
        log.info("audit_bootstrap_no_pairs")
        return 0

    log.info("audit_bootstrap_pairs_found", count=len(pairs))

    # Detect contract version to decide which read path to use
    contract_version = await chain_client.detect_contract_version()
    log.info("audit_bootstrap_contract_version", version=contract_version)

    # v1709: probe the subgraph once at bootstrap entry. If it's fresh
    # (within DJINN_SUBGRAPH_MAX_LAG_BLOCKS of chain), per-pair scans go
    # through one GraphQL query instead of ~3-5 RPC calls per purchase.
    # If unset, errored, or stale, the per-pair path falls back to RPC
    # by leaving subgraph_fresh=False. Settlement correctness is still
    # rooted in chain RPC for verification (genius/idiot/bpaRoot/wpaRoot
    # checks) — subgraph is a cache, never authority.
    subgraph_fresh = False
    if subgraph is not None:
        try:
            # latest_block was set inside the try-block at the top of
            # this function; if the chain probe failed there it isn't
            # defined. Re-fetch defensively so subgraph freshness check
            # always has a chain reference, even on the fallback path.
            try:
                _chain_latest = latest_block  # type: ignore[name-defined]
            except NameError:
                _chain_latest = await chain_client.get_current_block()
            subgraph_fresh = await subgraph.is_fresh(_chain_latest)
            log.info(
                "audit_bootstrap_subgraph_state",
                fresh=subgraph_fresh,
                chain_latest=_chain_latest,
            )
            try:
                from djinn_validator.api.metrics import AUDIT_BOOTSTRAP_SOURCE

                AUDIT_BOOTSTRAP_SOURCE.labels(source=("subgraph" if subgraph_fresh else "subgraph_stale")).inc()
            except Exception:
                pass
        except Exception as e:
            log.warning("audit_bootstrap_subgraph_probe_failed", err=str(e)[:120])
            subgraph_fresh = False

    # Step 3: For each pair, load purchase data (v1: cycle-based, v2: queue-based)
    # 2026-05-03 (P1-34 partial fix): bounded-concurrency parallel iteration. Each pair
    # involves 10-15 sequential RPC calls; default sequential mode meant ~1-2 min per
    # pair × 60+ pairs = 100+ min per bootstrap cycle, which made post-restart
    # settlement verification glacial (see MAINNET_BLOCKERS.md P1-34). With
    # BOOTSTRAP_CONCURRENCY > 1 we run N pairs in parallel via asyncio.gather,
    # giving roughly N× speedup until RPC rate limits cap us. Default kept at 1
    # for backward compatibility; UID 0 sets to 4 in .env once the fix lands.
    populated = 0
    # 2026-05-03 v1678: default concurrency bumped 1→2. Public Base Sepolia RPC
    # easily handles 2 parallel pair iterations; observed live UID 0 result was
    # ~3 pairs in 7s with concurrency=4 (RPC capped before we hit the budget),
    # so 2 is safe even for higher-load validators. Operators can still
    # opt down to 1 (BOOTSTRAP_CONCURRENCY=1) or up to 4-8 if their RPC supports.
    concurrency = max(1, int(os.environ.get("BOOTSTRAP_CONCURRENCY", "2")))

    # v1710: snapshot audit_set_store size per pair before/after each
    # _process_pair so we can identify newly-added (G, I, sig, pid)
    # tuples and gossip them to peers. The audit_set_store doesn't expose
    # an event hook, so we diff its post-add state instead.
    async def _gossip_new_signals(genius: str, idiot: str, before_sigs: set[str]) -> None:
        if neuron is None:
            return
        try:
            from djinn_validator.api.server import _gossip_audit_set_to_peers
        except Exception:
            return
        # Read the current pair's signal set; entries not in `before_sigs`
        # are newly added on this bootstrap iteration and need gossip.
        # v2 uses cycle=0 throughout (queue-based; cycle is opaque).
        try:
            audit_set = audit_set_store.get_set(genius, idiot, 0)
            if audit_set is None:
                return
            new_sigs = [
                (sid, sig.purchase_id)
                for sid, sig in audit_set.signals.items()
                if sid not in before_sigs and sig.purchase_id
            ]
        except Exception:
            return
        # Fan out per new signal in parallel; helper swallows per-peer errors.
        if new_sigs:
            await asyncio.gather(
                *[
                    _gossip_audit_set_to_peers(
                        neuron=neuron,
                        genius=genius,
                        idiot=idiot,
                        signal_id=sid,
                        purchase_id=int(pid),
                    )
                    for sid, pid in new_sigs
                ],
                return_exceptions=True,
            )

    async def _process_pair(genius: str, idiot: str) -> int:
        # Snapshot pre-add signal IDs so we can gossip only the deltas.
        before_sigs: set[str] = set()
        try:
            existing = audit_set_store.get_set(genius, idiot, 0)
            if existing is not None:
                before_sigs = set(existing.signals.keys())
        except Exception:
            pass
        try:
            if contract_version == 2:
                # v1709 fast path: when the subgraph is fresh, one
                # GraphQL query replaces ~3-5 RPC calls per purchase.
                # On error we fall through to the RPC scan unchanged,
                # so subgraph downtime never blocks bootstrap.
                if subgraph_fresh and subgraph is not None:
                    loaded = await _bootstrap_pair_v2_via_subgraph(
                        subgraph,
                        chain_client,
                        audit_set_store,
                        genius,
                        idiot,
                    )
                    if loaded is not None:
                        await _gossip_new_signals(genius, idiot, before_sigs)
                        return loaded
                    # subgraph returned None (transport/parse error). Fall
                    # through to RPC scan below.
                    try:
                        from djinn_validator.api.metrics import AUDIT_BOOTSTRAP_SOURCE

                        AUDIT_BOOTSTRAP_SOURCE.labels(source="subgraph_then_rpc").inc()
                    except Exception:
                        pass
                else:
                    try:
                        from djinn_validator.api.metrics import AUDIT_BOOTSTRAP_SOURCE

                        AUDIT_BOOTSTRAP_SOURCE.labels(source="rpc").inc()
                    except Exception:
                        pass
                valid_pids = valid_pids_by_pair.get((genius, idiot)) if pre_filter_ok else None
                loaded = await _bootstrap_pair_v2(
                    chain_client,
                    audit_set_store,
                    genius,
                    idiot,
                    valid_pids=valid_pids,
                )
                await _gossip_new_signals(genius, idiot, before_sigs)
                return loaded
            else:
                loaded = await _bootstrap_pair_v1(
                    chain_client,
                    audit_set_store,
                    genius,
                    idiot,
                )
                await _gossip_new_signals(genius, idiot, before_sigs)
                return loaded
        except Exception as e:
            log.debug(
                "audit_bootstrap_pair_skip",
                genius=genius[:10],
                idiot=idiot[:10],
                err=str(e)[:100],
            )
            return 0

    pairs_list = list(pairs)
    if concurrency == 1:
        # Sequential path preserves the prior 0.2s inter-pair delay so the
        # behavior on default-config validators is byte-identical to pre-fix.
        for genius, idiot in pairs_list:
            populated += await _process_pair(genius, idiot)
            await asyncio.sleep(0.2)
    else:
        # Bounded-concurrency parallel path. Process in chunks of `concurrency`
        # and use asyncio.gather for in-flight parallelism. The outer chunk
        # loop preserves the small inter-batch breathing room so the chain
        # client's failover RPC pool isn't perpetually saturated.
        for i in range(0, len(pairs_list), concurrency):
            chunk = pairs_list[i : i + concurrency]
            results = await asyncio.gather(
                *[_process_pair(g, i_) for g, i_ in chunk],
                return_exceptions=False,  # _process_pair already swallows
            )
            populated += sum(int(r or 0) for r in results)
            if i + concurrency < len(pairs_list):
                await asyncio.sleep(0.2)

    # Step 4: Register signals with OutcomeAttestor by parsing on-chain decoy lines.
    # The decoyLines stored on-chain contain full JSON with sport, event_id, teams.
    # Register signals that are in audit_set_store (real on-chain purchases).
    # v1409's original fix iterated every share in ShareStore to break a
    # chicken-and-egg where audit_set_store population needed resolved
    # outcomes. v1410 unblocked that path (unaudited_total = total_purchases
    # - audited_count needs no outcome data), so the full-ShareStore scan is
    # no longer required — and on validators with pre-UUPS or failed-commit
    # stale shares, the scan wastes ~10 min reverting every SignalCommitment
    # call with SignalNotFound(uint256). v1413's periodic rebootstrap (900s)
    # picks up any newly-purchased signals that miss the initial audit_set_store
    # snapshot, so missed signals still get registered within one rebootstrap
    # cycle. See P0-01 2026-04-20 11:12Z operational finding in MAINNET_BLOCKERS.md.
    if outcome_attestor:
        registered = await _register_signals_from_chain(
            chain_client,
            audit_set_store,
            outcome_attestor,
        )
        log.info("audit_bootstrap_signals_registered", count=registered)

        # Back-fill: if an outcome resolved BEFORE bootstrap added the signal
        # to audit_set_store, record_outcomes returned False silently and the
        # outcome got stuck in OutcomeAttestor's cache. Bootstrap now pulls
        # any already-resolved outcomes into audit_set_store so resolved_signals
        # reflects reality. Without this, ready_for_settlement never fires for
        # pairs whose games resolved during a bootstrap gap.
        backfilled = 0
        with audit_set_store._lock:
            pending_backfills: list[tuple[str, list]] = []
            for audit_set in audit_set_store._sets.values():
                for sig_id, sig in audit_set.signals.items():
                    if sig.outcomes is None:
                        meta = outcome_attestor.get_signal(sig_id)
                        if meta and meta.outcomes:
                            pending_backfills.append((sig_id, meta.outcomes))
        for sig_id, outs in pending_backfills:
            if audit_set_store.record_outcomes(sig_id, outs):
                backfilled += 1
        if backfilled:
            log.info("audit_bootstrap_outcomes_backfilled", count=backfilled)

    ready = audit_set_store.get_ready_sets()
    log.info(
        "audit_bootstrap_complete",
        pairs_loaded=populated,
        total_audit_sets=audit_set_store.count,
        ready_for_settlement=len(ready),
    )
    return populated


async def _bootstrap_pair_v1(
    chain_client: ChainClient,
    audit_set_store: AuditSetStore,
    genius: str,
    idiot: str,
) -> int:
    """Bootstrap a single pair using v1 cycle-based reads. Returns 1 on success, 0 on skip."""
    cycle = await chain_client.get_current_cycle(genius, idiot)
    count = await chain_client.get_signal_count(genius, idiot)
    if count == 0:
        return 0

    purchase_ids = await chain_client.get_purchase_ids(genius, idiot)
    if not purchase_ids:
        return 0

    for pid in purchase_ids:
        try:
            purchase = await chain_client.get_purchase(pid)
            if purchase is None:
                continue

            signal_id = str(purchase["signalId"])
            notional = int(purchase["notional"])
            odds = int(purchase["odds"])

            signal = await chain_client.get_signal(_parse_signal_id_to_int(signal_id))
            sla_bps = int(signal["slaMultiplierBps"]) if signal and isinstance(signal, dict) else 10_000

            audit_set_store.add_signal(
                genius=genius,
                idiot=idiot,
                cycle=cycle,
                signal_id=signal_id,
                notional=notional,
                odds=odds,
                sla_bps=sla_bps,
                purchase_id=pid,
            )
        except Exception as e:
            log.debug("audit_bootstrap_purchase_skip", purchase_id=pid, err=str(e)[:100])
            continue

    log.info(
        "audit_bootstrap_pair_loaded",
        genius=genius[:10],
        idiot=idiot[:10],
        cycle=cycle,
        signals=count,
        purchases=len(purchase_ids),
        version=1,
    )
    return 1


async def _bootstrap_pair_v2_via_subgraph(
    subgraph: SubgraphClient,
    chain_client: ChainClient,
    audit_set_store: AuditSetStore,
    genius: str,
    idiot: str,
) -> int | None:
    """v1709 fast path: load purchases for one (genius, idiot) pair from
    The Graph subgraph instead of paginating chain RPC.

    Returns:
      - int: number of signals added to audit_set_store
      - None: subgraph returned an error / empty / malformed; caller
        should fall back to the RPC scan path

    Verification: the subgraph index is a CACHE of chain events, never
    authority. We accept a row only if (a) the subgraph entity exists
    AND (b) chain RPC confirms the purchase isn't already audited AND
    (c) the on-chain Merkle roots are non-zero (post-V6 commitment).
    Skipping the on-chain audit + root checks would let a malicious or
    out-of-sync subgraph poison audit_set_store with stale or fabricated
    rows that the v1577 missing-BPA/WPA gate later swallows silently.

    The chain queue_state read is NOT replicated through the subgraph
    here because audit_set_store doesn't strictly need it — the absence
    of pending purchases is encoded in the subgraph's own filter
    (`outcome: Pending`).
    """
    rows = await subgraph.get_pair_purchases(genius, idiot)
    if rows is None:
        # transport / parse error — caller falls back to RPC.
        return None

    if not rows:
        # subgraph confirmed: no Pending purchases for this pair. Treat
        # as a successful bootstrap with 0 signals. (Don't fall back to
        # RPC — that would defeat the freshness guarantee.)
        return 0

    # We need the BPA/WPA roots to skip pre-V6 legacy purchases (where
    # both roots are zero). The subgraph doesn't expose these as a Purchase
    # field, so we batch-call chain RPC for each subgraph-listed purchase.
    # Even with this RPC, we save ~1 call per purchase vs the legacy path
    # (which also calls is_purchase_audited + get_purchase + get_signal).
    loaded = 0
    skipped_legacy = 0
    for row in rows:
        pid = row["purchase_id"]
        try:
            try:
                roots = await chain_client.get_purchase_vector_roots(pid)
            except Exception as e:
                log.debug(
                    "audit_bootstrap_subgraph_roots_rpc_raised",
                    purchase_id=pid,
                    err=str(e)[:80],
                )
                roots = None
            if roots is not None:
                bpa_root, wpa_root = roots
                if bpa_root == _ZERO_ROOT and wpa_root == _ZERO_ROOT:
                    skipped_legacy += 1
                    continue

            audit_set_store.add_signal(
                genius=genius,
                idiot=idiot,
                # cycle is opaque to v2 settlement (queue-based); use 0
                # as a placeholder, matching the behavior of /v1/audit/
                # gossip ingestion on the receiver side.
                cycle=0,
                signal_id=row["signal_id"],
                notional=row["notional"],
                odds=1_000_000,  # subgraph doesn't index per-purchase odds; settlement
                # uses the on-chain BPA/WPA vector for actual price
                sla_bps=row["sla_bps"],
                purchase_id=pid,
            )
            loaded += 1
        except Exception as e:
            log.debug(
                "audit_bootstrap_subgraph_pair_skip",
                purchase_id=pid,
                err=str(e)[:100],
            )
            continue

    if loaded > 0 or skipped_legacy > 0:
        log.info(
            "audit_bootstrap_pair_loaded_subgraph",
            genius=genius[:10],
            idiot=idiot[:10],
            signals=loaded,
            skipped_legacy=skipped_legacy,
            subgraph_rows=len(rows),
        )
    return loaded


async def _bootstrap_pair_v2(
    chain_client: ChainClient,
    audit_set_store: AuditSetStore,
    genius: str,
    idiot: str,
    valid_pids: set[int] | None = None,
) -> int:
    """Bootstrap a single pair using v2 queue-based reads. Returns 1 on success, 0 on skip.

    If `valid_pids` is supplied (from the event scan), purchase IDs from
    Account are intersected with it before loading. This drops ancient
    pre-V6 PIDs that Account still tracks but that never emitted a
    post-deploy event, so audit_set_store only ever holds purchases we
    can actually resolve and settle. Passing None preserves legacy
    behavior (load every pid) for the RPC-outage fallback path.
    """
    total_purchases, resolved_count, audited_count, batch_count = await chain_client.get_queue_state(
        genius,
        idiot,
    )
    unaudited_total = total_purchases - audited_count
    if unaudited_total <= 0:
        return 0

    purchase_ids = await chain_client.get_pair_purchase_ids(genius, idiot)
    if not purchase_ids:
        return 0

    if valid_pids is not None:
        ancient = [p for p in purchase_ids if p not in valid_pids]
        if ancient:
            log.info(
                "audit_bootstrap_ancient_pids_skipped",
                genius=genius[:10],
                idiot=idiot[:10],
                ancient=len(ancient),
                kept=len(valid_pids),
            )
        purchase_ids = [p for p in purchase_ids if p in valid_pids]
        if not purchase_ids:
            return 0

    # Filter to unaudited purchases only
    loaded = 0
    skipped_legacy = 0
    for pid in purchase_ids:
        try:
            already_audited = await chain_client.is_purchase_audited(pid)
            if already_audited:
                continue

            purchase = await chain_client.get_purchase(pid)
            if purchase is None:
                continue

            # v1587: skip pre-V6 legacy purchases before adding to the store.
            # v1590: isolate the roots call from the outer try/except so that
            # a raised exception (network error that escapes ChainClient's
            # own swallow) fails open (keep the pid) rather than being treated
            # as an outer-loop skip. Both-zero = legacy, explicit skip with
            # per-pid debug log + aggregate info log below.
            try:
                roots = await chain_client.get_purchase_vector_roots(pid)
            except Exception as e:
                log.debug("audit_bootstrap_roots_rpc_raised", purchase_id=pid, err=str(e)[:100])
                roots = None
            if roots is not None:
                bpa_root, wpa_root = roots
                if bpa_root == _ZERO_ROOT and wpa_root == _ZERO_ROOT:
                    skipped_legacy += 1
                    log.debug(
                        "audit_bootstrap_skip_legacy_roots",
                        genius=genius[:10],
                        idiot=idiot[:10],
                        purchase_id=pid,
                    )
                    continue

            signal_id = str(purchase["signalId"])
            notional = int(purchase["notional"])
            odds = int(purchase["odds"])

            signal = await chain_client.get_signal(_parse_signal_id_to_int(signal_id))
            sla_bps = int(signal["slaMultiplierBps"]) if signal and isinstance(signal, dict) else 10_000

            # v2: use batch_count as the "cycle" identifier for the current batch
            audit_set_store.add_signal(
                genius=genius,
                idiot=idiot,
                cycle=batch_count,
                signal_id=signal_id,
                notional=notional,
                odds=odds,
                sla_bps=sla_bps,
                purchase_id=pid,
            )
            loaded += 1
        except Exception as e:
            log.debug("audit_bootstrap_purchase_skip", purchase_id=pid, err=str(e)[:100])
            continue

    if loaded > 0 or skipped_legacy > 0:
        log.info(
            "audit_bootstrap_pair_loaded",
            genius=genius[:10],
            idiot=idiot[:10],
            cycle=batch_count,
            signals=loaded,
            skipped_legacy=skipped_legacy,
            purchases=len(purchase_ids),
            unaudited_total=unaudited_total,
            version=2,
        )
    return 1 if loaded > 0 else 0


def _parse_signal_id_to_int(signal_id: str) -> int:
    """Parse a signal_id string as uint256. Accepts decimal or hex (with/without 0x).

    Signal IDs on-chain are uint256. Web UI serializes them as decimal;
    stress-scale and some off-chain clients serialize as 64-char hex.
    """
    s = signal_id.strip()
    if s.startswith("0x") or s.startswith("0X"):
        return int(s, 16)
    try:
        return int(s, 10)
    except ValueError:
        return int(s, 16)


async def _get_buyers_for_signal(
    chain_client: ChainClient,
    signal_id: str,
    genius_addr: str,
) -> list[tuple[str, str]]:
    """Return list of (genius, idiot) pairs for a signal's purchases."""
    pairs = []
    try:
        purchase_ids = await chain_client.get_purchases_by_signal(_parse_signal_id_to_int(signal_id))
        if purchase_ids:
            log.info(
                "audit_bootstrap_signal_has_purchases",
                signal_id=signal_id[:20],
                purchases=len(purchase_ids),
            )
        for pid in purchase_ids:
            purchase = await chain_client.get_purchase(pid)
            if purchase:
                buyer = purchase["idiot"]
                pairs.append((genius_addr, buyer))
    except Exception as e:
        # Only log first few errors to avoid spam
        if not hasattr(_get_buyers_for_signal, "_error_count"):
            _get_buyers_for_signal._error_count = 0  # type: ignore[attr-defined]
        _get_buyers_for_signal._error_count += 1  # type: ignore[attr-defined]
        if _get_buyers_for_signal._error_count <= 5:  # type: ignore[attr-defined]
            log.info(
                "audit_bootstrap_buyer_check_failed",
                signal_id=signal_id[:20],
                err=str(e)[:150],
            )
    return pairs


def _get_genius_signals(share_store: ShareStore) -> dict[str, str]:
    """Query ShareStore for all (signal_id -> genius_address) mappings."""
    result: dict[str, str] = {}
    try:
        with share_store._lock:
            cursor = share_store._conn.execute("SELECT DISTINCT signal_id, genius_address FROM shares")
            for row in cursor:
                result[row[0]] = row[1]
    except Exception as e:
        log.error("audit_bootstrap_db_query_failed", err=str(e))
    return result


async def _register_signals_from_chain(
    chain_client: ChainClient,
    audit_set_store: AuditSetStore,
    outcome_attestor: OutcomeAttestor,
    all_signal_ids: list[str] | None = None,
) -> int:
    """Parse on-chain decoyLines JSON and register signals for outcome resolution.

    The decoyLines stored on SignalCommitment contain full JSON objects like:
      {"sport":"soccer_epl","event_id":"9c44...","home_team":"Sunderland",
       "away_team":"Brighton","market":"h2h","line":null,"side":"Brighton",
       "price":2.19,"commence_time":"2026-03-14T15:00:00Z"}

    We parse these to build SignalMetadata for the OutcomeAttestor.

    If all_signal_ids is provided (e.g. from ShareStore), registers every one
    regardless of audit_set_store membership. Otherwise falls back to walking
    just the signals already in audit sets (legacy behavior).
    """
    from djinn_validator.core.outcomes import SignalMetadata, parse_pick

    signal_ids: set[str] = set()
    if all_signal_ids:
        signal_ids.update(all_signal_ids)
    else:
        for audit_set in audit_set_store._sets.values():
            for sig_id in audit_set.signals:
                signal_ids.add(sig_id)

    if not signal_ids:
        return 0

    registered = 0
    for signal_id in signal_ids:
        # Skip if already registered
        if outcome_attestor.get_signal(signal_id) is not None:
            continue

        try:
            signal = await chain_client.get_signal(_parse_signal_id_to_int(signal_id))
            if not signal or not isinstance(signal, dict):
                continue

            decoy_lines = signal.get("decoyLines", [])
            if not decoy_lines or len(decoy_lines) < 10:
                continue

            # Parse the first decoy line's JSON to extract game metadata
            first_line = _parse_decoy_json(decoy_lines[0])
            if not first_line:
                continue

            sport = first_line.get("sport", "")
            event_id = first_line.get("event_id", "")
            home_team = first_line.get("home_team", "")
            away_team = first_line.get("away_team", "")

            if not sport or not event_id:
                continue

            # Build pick strings for parse_pick (e.g., "Brighton ML +220")
            parsed_lines = []
            for dl in decoy_lines:
                dl_data = _parse_decoy_json(dl)
                if dl_data:
                    pick_str = _decoy_to_pick_string(dl_data)
                    try:
                        parsed_lines.append(parse_pick(pick_str))
                    except Exception:
                        parsed_lines.append(parse_pick("Unknown 0 (+100)"))
                else:
                    parsed_lines.append(parse_pick("Unknown 0 (+100)"))

            if len(parsed_lines) != 10:
                continue

            metadata = SignalMetadata(
                signal_id=signal_id,
                sport=sport,
                event_id=event_id,
                home_team=home_team,
                away_team=away_team,
                lines=parsed_lines,
            )
            # v1724: bootstrap is a trusted internal path (data sourced from
            # chain), so allow_overwrite=True. The poisoning concern only
            # applies to unauthenticated HTTP callers.
            outcome_attestor.register_signal(metadata, allow_overwrite=True)
            registered += 1

        except Exception as e:
            log.debug(
                "audit_bootstrap_register_skip",
                signal_id=signal_id[:20],
                err=str(e)[:100],
            )
            continue

        # Rate limit
        if registered % 10 == 0:
            await asyncio.sleep(0.5)

    return registered


def _parse_decoy_json(line: str) -> dict | None:
    """Try to parse a decoy line as JSON."""
    try:
        data = json.loads(line)
        if isinstance(data, dict):
            return data
    except (json.JSONDecodeError, TypeError):
        pass
    return None


def _decoy_to_pick_string(data: dict) -> str:
    """Convert a decoy line JSON object to a pick string for parse_pick."""
    market = data.get("market", "h2h")
    team = data.get("side", data.get("team", "Unknown"))
    line_val = data.get("line")
    price = data.get("price", 2.0)

    # Convert decimal odds to American
    if price >= 2.0:
        american = int((price - 1) * 100)
    else:
        american = int(-100 / (price - 1))

    if market == "spreads" and line_val is not None:
        return f"{team} {line_val:+g} ({american:+d})"
    elif market == "totals" and line_val is not None:
        side = data.get("side", "Over")
        return f"{side} {line_val} ({american:+d})"
    else:
        # h2h / moneyline
        return f"{team} ML ({american:+d})"
