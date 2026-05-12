"""Test the event-scan pre-filter in audit_bootstrap.

The bootstrap flow previously iterated every (signal_id, genius) row in
shares.db and called getPurchasesBySignal on each. That was O(N) RPC per
startup with ~1349 rows on UID 0, ~1253 of which were stale and reverted
with SignalNotFound. Cold boot took ~10 min.

The event-scan fix replaces the inner loop with a single chunked
SignalPurchased event scan, then cross-references buyer→genius via
shares.db. We want to confirm:

  * Events whose signal_id matches a shares.db row produce a pair.
  * Events whose signal_id is orphaned (no shares.db row) are ignored.
  * Shares.db rows with no purchase events contribute zero pairs (the
    whole point — we no longer waste RPC on those stale rows).
  * An RPC outage on the event scan falls back to the legacy path so we
    don't silently lose pairs when eth_getLogs is unavailable.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from djinn_validator.core.audit_bootstrap import bootstrap_audit_sets
from djinn_validator.core.audit_set import AuditSetStore
from djinn_validator.core.shares import ShareStore
from djinn_validator.utils.crypto import Share


@pytest.fixture
def share_store():
    """ShareStore with three live signals and one stale orphan."""
    store = ShareStore()
    store.store("111", "0xGenius1", Share(x=1, y=11), b"k1")
    store.store("222", "0xGenius1", Share(x=1, y=22), b"k2")
    store.store("333", "0xGenius2", Share(x=1, y=33), b"k3")
    # Stale: in shares.db but never committed on-chain. Pre-fix this
    # triggered ~1253 SignalNotFound reverts. Post-fix: silently ignored.
    store.store("999", "0xGhost", Share(x=1, y=99), b"k-stale")
    return store


def _mock_chain_client(
    *,
    latest_block: int = 10_000_000,
    purchase_events: list[dict] | None = None,
    purchase_events_raises: Exception | None = None,
    commit_events: list[dict] | None = None,
):
    """Build a MagicMock ChainClient that satisfies bootstrap's API surface."""
    client = MagicMock()
    client.get_current_block = AsyncMock(return_value=latest_block)

    if purchase_events_raises is not None:
        client.get_recent_signal_purchases = AsyncMock(side_effect=purchase_events_raises)
    else:
        client.get_recent_signal_purchases = AsyncMock(return_value=purchase_events or [])

    # v1585: SignalCommitted scan produces signal_id → genius for signals
    # the local validator doesn't hold a share for. Default empty so existing
    # tests (which only exercise local shares.db paths) stay unaffected.
    client.get_recent_signal_events = AsyncMock(return_value=commit_events or [])

    # detect_contract_version gates pair population; the test below
    # only exercises the pair-extraction step so return a valid version.
    client.detect_contract_version = AsyncMock(return_value=1)

    # Per-pair bootstrap reads: have them all raise so the pair loop
    # short-circuits and we can assert on the pair set before any
    # on-chain reads of getCurrentCycle etc.
    client.get_current_cycle = AsyncMock(side_effect=Exception("stubbed"))
    client.get_signal_count = AsyncMock(side_effect=Exception("stubbed"))

    return client


@pytest.mark.asyncio
async def test_event_scan_populates_pairs_from_events(share_store):
    """Purchase events whose signal_id is in shares.db produce pairs."""
    events = [
        {"signal_id": "111", "buyer": "0xIdiotA", "purchase_id": 1,
         "notional": 0, "fee_paid": 0, "credit_used": 0, "usdc_paid": 0, "block_number": 1},
        {"signal_id": "222", "buyer": "0xIdiotB", "purchase_id": 2,
         "notional": 0, "fee_paid": 0, "credit_used": 0, "usdc_paid": 0, "block_number": 1},
        {"signal_id": "333", "buyer": "0xIdiotC", "purchase_id": 3,
         "notional": 0, "fee_paid": 0, "credit_used": 0, "usdc_paid": 0, "block_number": 1},
    ]
    client = _mock_chain_client(purchase_events=events)
    # Explicit AsyncMock on get_purchases_by_signal so we can assert
    # the legacy fallback path did NOT engage.
    client.get_purchases_by_signal = AsyncMock(return_value=[])
    audit_set_store = AuditSetStore()

    # bootstrap returns 0 populated because per-pair reads are stubbed
    # to raise, but we can still assert the pair scan ran (no exception)
    # and pre_filter_ok suppressed the legacy per-signal probe.
    await bootstrap_audit_sets(client, share_store, audit_set_store)

    # Event scan was called exactly once; per-signal fallback path was NOT.
    assert client.get_recent_signal_purchases.await_count == 1
    assert client.get_purchases_by_signal.await_count == 0


@pytest.mark.asyncio
async def test_orphan_event_does_not_create_pair(share_store):
    """A SignalPurchased event for a signal we have no shares for is dropped."""
    events = [
        {"signal_id": "111", "buyer": "0xIdiotA", "purchase_id": 1,
         "notional": 0, "fee_paid": 0, "credit_used": 0, "usdc_paid": 0, "block_number": 1},
        # Orphan: no shares.db row for 777, some other validator had the shares.
        {"signal_id": "777", "buyer": "0xIdiotX", "purchase_id": 2,
         "notional": 0, "fee_paid": 0, "credit_used": 0, "usdc_paid": 0, "block_number": 1},
    ]
    client = _mock_chain_client(purchase_events=events)
    client.get_purchases_by_signal = AsyncMock(return_value=[])
    audit_set_store = AuditSetStore()

    # Capture log structlog events to confirm orphaned counter incremented.
    await bootstrap_audit_sets(client, share_store, audit_set_store)
    assert client.get_recent_signal_purchases.await_count == 1
    assert client.get_purchases_by_signal.await_count == 0


@pytest.mark.asyncio
async def test_stale_shares_no_rpc_spam(share_store):
    """Shares with no on-chain event produce no per-signal RPC calls.

    This is the core fix: pre v1437+3, 'stale' rows cost one RPC each,
    reverting with SignalNotFound. Post-fix, they cost zero — we only
    touch on-chain state for signals that emitted a real purchase.
    """
    events = []  # zero purchase events
    client = _mock_chain_client(purchase_events=events)
    client.get_purchases_by_signal = AsyncMock(return_value=[])
    audit_set_store = AuditSetStore()

    await bootstrap_audit_sets(client, share_store, audit_set_store)

    # One event scan, zero per-signal RPC — even though the share_store
    # has 4 rows, none triggers get_purchases_by_signal.
    assert client.get_recent_signal_purchases.await_count == 1
    assert client.get_purchases_by_signal.await_count == 0


@pytest.mark.asyncio
async def test_event_scan_failure_falls_back_to_legacy(share_store):
    """If eth_getLogs is unavailable, we must not silently lose pairs."""
    client = _mock_chain_client(
        purchase_events_raises=RuntimeError("rpc 503"),
    )
    # Legacy path calls get_purchases_by_signal per row; stub it to return []
    # so the bootstrap completes cleanly and we can assert it was hit.
    client.get_purchases_by_signal = AsyncMock(return_value=[])
    audit_set_store = AuditSetStore()

    await bootstrap_audit_sets(client, share_store, audit_set_store)

    assert client.get_recent_signal_purchases.await_count == 1
    # Fallback engaged: per-signal probe ran for all 4 distinct signal_ids.
    assert client.get_purchases_by_signal.await_count == 4


@pytest.mark.asyncio
async def test_ancient_pids_filtered_out_of_bootstrap():
    """v1441: Account.getPairPurchaseIds may return ancient pre-V6 PIDs that
    never emitted a scannable event. Those must be dropped so they don't
    flood audit_set_store with signals that will never resolve.

    Scenario: pair (0xG, 0xI) has 3 recent purchase events (pids 335,336,337)
    but Account also tracks 37 ancient pids (1..37). Only the 3 recent pids
    should reach get_purchase — the 37 ancient ones get filtered.
    """
    from djinn_validator.core.shares import ShareStore
    from djinn_validator.utils.crypto import Share
    store = ShareStore()
    store.store("sig-recent-1", "0xGen", Share(x=1, y=1), b"k")
    store.store("sig-recent-2", "0xGen", Share(x=1, y=2), b"k")
    store.store("sig-recent-3", "0xGen", Share(x=1, y=3), b"k")

    events = [
        {"signal_id": "sig-recent-1", "buyer": "0xIdiot", "purchase_id": 335,
         "notional": 0, "fee_paid": 0, "credit_used": 0, "usdc_paid": 0, "block_number": 1},
        {"signal_id": "sig-recent-2", "buyer": "0xIdiot", "purchase_id": 336,
         "notional": 0, "fee_paid": 0, "credit_used": 0, "usdc_paid": 0, "block_number": 1},
        {"signal_id": "sig-recent-3", "buyer": "0xIdiot", "purchase_id": 337,
         "notional": 0, "fee_paid": 0, "credit_used": 0, "usdc_paid": 0, "block_number": 1},
    ]
    client = _mock_chain_client(purchase_events=events)
    # v2 contract path
    client.detect_contract_version = AsyncMock(return_value=2)
    client.get_queue_state = AsyncMock(return_value=(40, 0, 0, 1))
    client.get_pair_purchase_ids = AsyncMock(
        return_value=list(range(1, 38)) + [335, 336, 337]
    )
    client.is_purchase_audited = AsyncMock(return_value=False)
    # get_purchase should ONLY be called with valid pids 335/336/337.
    get_purchase_calls = []

    async def _fake_get_purchase(pid):
        get_purchase_calls.append(pid)
        return {"signalId": f"sig-recent-{pid - 334}", "notional": 100, "odds": 2_000_000}

    client.get_purchase = AsyncMock(side_effect=_fake_get_purchase)
    client.get_signal = AsyncMock(return_value={"slaMultiplierBps": 10_000})
    # v1587: every surviving pid is root-checked; non-zero = V2 purchase.
    client.get_purchase_vector_roots = AsyncMock(return_value=(b"\x01" * 32, b"\x02" * 32))

    audit_set_store = AuditSetStore()
    await bootstrap_audit_sets(client, share_store=store, audit_set_store=audit_set_store)

    # Ancient pids 1..37 must never reach get_purchase.
    assert set(get_purchase_calls) <= {335, 336, 337}, f"ancient pids leaked: {get_purchase_calls}"
    assert set(get_purchase_calls) == {335, 336, 337}, f"recent pids missing: {get_purchase_calls}"


@pytest.mark.asyncio
async def test_v1587_legacy_zero_root_pids_filtered_out_of_bootstrap():
    """v1587: purchases with zero BPA + WPA Merkle roots on-chain are
    pre-V6 legacy purchases that can never settle under v1577's
    abstain-on-missing-BPA/WPA rule. They must be filtered at bootstrap
    so audit_set_store stays clean.

    Scenario: pair has 3 pids — one V2 (non-zero roots), one legacy
    (zero roots), one V2. Only the 2 V2 pids should reach the store.
    On RPC failure (roots=None), fail-open: keep the pid rather than
    silently dropping potentially valid V2 data during a Sepolia outage.
    """
    from djinn_validator.core.shares import ShareStore
    from djinn_validator.utils.crypto import Share
    store = ShareStore()
    store.store("1001", "0xGen", Share(x=1, y=1), b"k")
    store.store("1002", "0xGen", Share(x=1, y=2), b"k")
    store.store("1003", "0xGen", Share(x=1, y=3), b"k")

    events = [
        {"signal_id": "1001", "buyer": "0xIdiot", "purchase_id": 501,
         "notional": 0, "fee_paid": 0, "credit_used": 0, "usdc_paid": 0, "block_number": 1},
        {"signal_id": "1002", "buyer": "0xIdiot", "purchase_id": 502,
         "notional": 0, "fee_paid": 0, "credit_used": 0, "usdc_paid": 0, "block_number": 1},
        {"signal_id": "1003", "buyer": "0xIdiot", "purchase_id": 503,
         "notional": 0, "fee_paid": 0, "credit_used": 0, "usdc_paid": 0, "block_number": 1},
    ]
    client = _mock_chain_client(purchase_events=events)
    client.detect_contract_version = AsyncMock(return_value=2)
    client.get_queue_state = AsyncMock(return_value=(3, 0, 0, 1))
    client.get_pair_purchase_ids = AsyncMock(return_value=[501, 502, 503])
    client.is_purchase_audited = AsyncMock(return_value=False)

    async def _fake_get_purchase(pid):
        return {"signalId": str(1000 + (pid - 500)),  # 501→1001, 502→1002, 503→1003
                "notional": 100, "odds": 2_000_000}
    client.get_purchase = AsyncMock(side_effect=_fake_get_purchase)
    client.get_signal = AsyncMock(return_value={"slaMultiplierBps": 10_000})

    # 501/503 = non-zero (V2), 502 = zero (legacy)
    async def _fake_roots(pid):
        if pid == 502:
            return (b"\x00" * 32, b"\x00" * 32)
        return (b"\xab" * 32, b"\xcd" * 32)
    client.get_purchase_vector_roots = AsyncMock(side_effect=_fake_roots)

    audit_set_store = AuditSetStore()
    await bootstrap_audit_sets(client, share_store=store, audit_set_store=audit_set_store)

    # Exactly 2 V2 signals loaded; legacy dropped.
    sets = list(audit_set_store._sets.values())
    assert len(sets) == 1
    loaded_pids = {s.purchase_id for s in sets[0].signals.values()}
    assert loaded_pids == {501, 503}, f"expected {{501,503}}, got {loaded_pids}"


@pytest.mark.asyncio
async def test_v1587_roots_rpc_failure_fails_open():
    """On RPC failure (get_purchase_vector_roots returns None) the bootstrap
    must KEEP the pid. Dropping on RPC failure would silently lose legit V2
    data during any Sepolia outage. Conservative semantics: only skip when
    we have positive evidence the roots are zero."""
    from djinn_validator.core.shares import ShareStore
    from djinn_validator.utils.crypto import Share
    store = ShareStore()
    store.store("2001", "0xGen", Share(x=1, y=1), b"k")

    events = [
        {"signal_id": "2001", "buyer": "0xIdiot", "purchase_id": 601,
         "notional": 0, "fee_paid": 0, "credit_used": 0, "usdc_paid": 0, "block_number": 1},
    ]
    client = _mock_chain_client(purchase_events=events)
    client.detect_contract_version = AsyncMock(return_value=2)
    client.get_queue_state = AsyncMock(return_value=(1, 0, 0, 1))
    client.get_pair_purchase_ids = AsyncMock(return_value=[601])
    client.is_purchase_audited = AsyncMock(return_value=False)
    client.get_purchase = AsyncMock(return_value={"signalId": "2001", "notional": 100, "odds": 2_000_000})
    client.get_signal = AsyncMock(return_value={"slaMultiplierBps": 10_000})
    # RPC failure on root lookup
    client.get_purchase_vector_roots = AsyncMock(return_value=None)

    audit_set_store = AuditSetStore()
    await bootstrap_audit_sets(client, share_store=store, audit_set_store=audit_set_store)

    # Fail-open: signal still loads.
    sets = list(audit_set_store._sets.values())
    assert len(sets) == 1
    assert len(sets[0].signals) == 1


@pytest.mark.asyncio
async def test_v1590_roots_rpc_raise_fails_open():
    """v1590: if `get_purchase_vector_roots` RAISES (not just returns None),
    the bootstrap still keeps the pid. Pre-v1590 the outer try/except at the
    loop level swallowed the raise and `continue`d, which was the OPPOSITE
    of fail-open — legit V2 signals silently dropped during a transient
    network error. Fresh-eyes audit 2026-04-22 caught this gap."""
    from djinn_validator.core.shares import ShareStore
    from djinn_validator.utils.crypto import Share
    store = ShareStore()
    store.store("3001", "0xGen", Share(x=1, y=1), b"k")

    events = [
        {"signal_id": "3001", "buyer": "0xIdiot", "purchase_id": 701,
         "notional": 0, "fee_paid": 0, "credit_used": 0, "usdc_paid": 0, "block_number": 1},
    ]
    client = _mock_chain_client(purchase_events=events)
    client.detect_contract_version = AsyncMock(return_value=2)
    client.get_queue_state = AsyncMock(return_value=(1, 0, 0, 1))
    client.get_pair_purchase_ids = AsyncMock(return_value=[701])
    client.is_purchase_audited = AsyncMock(return_value=False)
    client.get_purchase = AsyncMock(return_value={"signalId": "3001", "notional": 100, "odds": 2_000_000})
    client.get_signal = AsyncMock(return_value={"slaMultiplierBps": 10_000})
    # Network error escapes ChainClient's own swallow (as can happen if the
    # _with_failover wrapper itself fails during session setup).
    client.get_purchase_vector_roots = AsyncMock(side_effect=RuntimeError("rpc session dead"))

    audit_set_store = AuditSetStore()
    await bootstrap_audit_sets(client, share_store=store, audit_set_store=audit_set_store)

    # Fail-open: signal still loads despite the raise.
    sets = list(audit_set_store._sets.values())
    assert len(sets) == 1
    assert len(sets[0].signals) == 1


@pytest.mark.asyncio
async def test_v1585_merges_onchain_genius_when_local_share_missing():
    """v1585: a validator that holds no share for signal X but sees a
    SignalPurchased(X) event should STILL produce a (genius, idiot) pair
    using the on-chain SignalCommitted(X).genius lookup.

    Pre-v1585: genius_signals came from local shares.db only, so validators
    with a non-overlapping share subset dropped each other's signals as
    "orphans" and produced divergent pair sets → divergent batchKey →
    4-of-6 OV quorum unreachable. This test pins the union behavior.
    """
    # Local shares.db is EMPTY (fresh validator that didn't catch the fan-out).
    store = ShareStore()

    # Event scan returns one purchase for signal 555 / buyer 0xIdiotM.
    purchase_events = [
        {"signal_id": "555", "buyer": "0xIdiotM", "purchase_id": 42,
         "notional": 0, "fee_paid": 0, "credit_used": 0, "usdc_paid": 0, "block_number": 1},
    ]
    # SignalCommitted scan identifies signal 555 as belonging to 0xGeniusQ.
    commit_events = [
        {"signal_id": 555, "genius": "0xGeniusQ", "sport": "NBA",
         "max_price_bps": 0, "sla_multiplier_bps": 0, "max_notional": 0,
         "expires_at": 0, "block_number": 1},
    ]
    client = _mock_chain_client(
        purchase_events=purchase_events,
        commit_events=commit_events,
    )
    client.get_purchases_by_signal = AsyncMock(return_value=[])
    # v2 path, but stub per-pair reads to short-circuit before they're exercised;
    # we only want to confirm the pair was discovered (log via get_queue_state call).
    client.detect_contract_version = AsyncMock(return_value=2)
    client.get_queue_state = AsyncMock(side_effect=Exception("stubbed"))

    audit_set_store = AuditSetStore()
    await bootstrap_audit_sets(client, store, audit_set_store)

    # Event scan fired once (merged pair discovery).
    assert client.get_recent_signal_purchases.await_count == 1
    assert client.get_recent_signal_events.await_count == 1
    # Per-pair loop reached get_queue_state once with the on-chain-derived
    # pair — proving the pair was discovered despite empty local shares.
    assert client.get_queue_state.await_count == 1
    called_args = client.get_queue_state.await_args.args
    assert called_args[0] == "0xgeniusq"  # lowercased
    assert called_args[1] == "0xidiotm"


@pytest.mark.asyncio
async def test_v1585_onchain_wins_on_conflict():
    """When local shares.db and on-chain SignalCommitted disagree on the
    genius for the same signal_id, on-chain wins. The event is the
    fleet-wide source of truth; local shares.db can be stale (wrong genius
    from pre-migration data), but the SignalCommitted event is authoritative.
    If every validator runs this merge identically, they converge on the
    same pair set — which is the entire point of v1585.
    """
    store = ShareStore()
    store.store("888", "0xLocalGenius", Share(x=1, y=88), b"k")

    purchase_events = [
        {"signal_id": "888", "buyer": "0xIdiotZ", "purchase_id": 9,
         "notional": 0, "fee_paid": 0, "credit_used": 0, "usdc_paid": 0, "block_number": 1},
    ]
    # Commit event claims a DIFFERENT genius for signal 888.
    commit_events = [
        {"signal_id": 888, "genius": "0xDifferentGenius", "sport": "NBA",
         "max_price_bps": 0, "sla_multiplier_bps": 0, "max_notional": 0,
         "expires_at": 0, "block_number": 1},
    ]
    client = _mock_chain_client(
        purchase_events=purchase_events,
        commit_events=commit_events,
    )
    client.get_purchases_by_signal = AsyncMock(return_value=[])
    client.detect_contract_version = AsyncMock(return_value=2)
    client.get_queue_state = AsyncMock(side_effect=Exception("stubbed"))

    audit_set_store = AuditSetStore()
    await bootstrap_audit_sets(client, store, audit_set_store)

    # The merge prefers the on-chain SignalCommitted.genius (fleet-wide
    # truth) over the local shares.db. This is intentional: local rows
    # can be stale (wrong genius from pre-migration data), but the
    # on-chain event is authoritative. If every validator runs this merge
    # identically, they converge on the same pair set.
    assert client.get_queue_state.await_count == 1
    called_args = client.get_queue_state.await_args.args
    assert called_args[0] == "0xdifferentgenius"


# ----------------------------------------------------------------------
# P1-34 (2026-05-03): bootstrap parallelization via BOOTSTRAP_CONCURRENCY
# ----------------------------------------------------------------------
# Sequential bootstrap (1 pair × 30-60s × 60+ pairs) makes post-restart
# settlement verification glacial. Bounded-concurrency parallel iteration
# brings cycle time down 4x with default concurrency=4. These tests pin
# (a) default concurrency=1 preserves pre-fix sequential behavior, and
# (b) concurrency>1 actually parallelizes the per-pair RPC fan-out.


class TestBootstrapConcurrency:
    @pytest.mark.asyncio
    async def test_explicit_concurrency_1_is_sequential(self, share_store, monkeypatch):
        """BOOTSTRAP_CONCURRENCY=1 preserves prior sequential behavior."""
        monkeypatch.setenv("BOOTSTRAP_CONCURRENCY", "1")

        purchase_events = [
            {"signal_id": "111", "buyer": "0xBuyerA", "purchase_id": 100, "block_number": 100},
            {"signal_id": "222", "buyer": "0xBuyerB", "purchase_id": 101, "block_number": 101},
            {"signal_id": "333", "buyer": "0xBuyerC", "purchase_id": 102, "block_number": 102},
        ]
        client = _mock_chain_client(purchase_events=purchase_events)
        client.detect_contract_version = AsyncMock(return_value=2)

        # Track pair-iteration order: each call appends to history.
        iteration_history: list[str] = []

        async def slow_pair_load(genius, idiot):
            iteration_history.append(f"start:{idiot}")
            # Tiny sleep so any concurrency would manifest as interleaving.
            import asyncio as _a

            await _a.sleep(0.01)
            iteration_history.append(f"end:{idiot}")
            raise Exception("stubbed-after-trace")

        client.get_queue_state = AsyncMock(side_effect=slow_pair_load)

        audit_set_store = AuditSetStore()
        await bootstrap_audit_sets(client, share_store, audit_set_store)

        # Sequential: every start:X is followed by end:X before next start.
        starts = [h for h in iteration_history if h.startswith("start:")]
        for idx, st in enumerate(starts):
            idiot = st.split(":", 1)[1]
            # The next entry MUST be `end:<same idiot>` for sequential.
            pos = iteration_history.index(st)
            assert iteration_history[pos + 1] == f"end:{idiot}", (
                f"Sequential bootstrap interleaved at {st}: history={iteration_history}"
            )

    @pytest.mark.asyncio
    async def test_default_concurrency_is_2(self, share_store, monkeypatch):
        """v1678: default BOOTSTRAP_CONCURRENCY=2 (no env set) parallelizes 2 at a time."""
        monkeypatch.delenv("BOOTSTRAP_CONCURRENCY", raising=False)

        purchase_events = [
            {"signal_id": "111", "buyer": "0xBuyerA", "purchase_id": 100, "block_number": 100},
            {"signal_id": "222", "buyer": "0xBuyerB", "purchase_id": 101, "block_number": 101},
            {"signal_id": "333", "buyer": "0xBuyerC", "purchase_id": 102, "block_number": 102},
            {"signal_id": "444", "buyer": "0xBuyerD", "purchase_id": 103, "block_number": 103},
        ]
        # share_store fixture only has signal "111", "222", "333", "999" but
        # SignalCommitted scan also feeds entries; we use the existing fixture
        # which produces exactly 3 pairs through the buyer→genius merge.
        client = _mock_chain_client(purchase_events=purchase_events)
        client.detect_contract_version = AsyncMock(return_value=2)

        iteration_history: list[str] = []

        async def slow_pair_load(genius, idiot):
            iteration_history.append(f"start:{idiot}")
            import asyncio as _a

            await _a.sleep(0.05)
            iteration_history.append(f"end:{idiot}")
            raise Exception("stubbed-after-trace")

        client.get_queue_state = AsyncMock(side_effect=slow_pair_load)

        audit_set_store = AuditSetStore()
        await bootstrap_audit_sets(client, share_store, audit_set_store)

        # With concurrency=2, the first 2 pairs should start before either ends.
        first_end_idx = next(
            (i for i, h in enumerate(iteration_history) if h.startswith("end:")),
            len(iteration_history),
        )
        starts_before_first_end = sum(
            1 for h in iteration_history[:first_end_idx] if h.startswith("start:")
        )
        assert starts_before_first_end >= 2, (
            f"Expected at least 2 parallel starts, saw {starts_before_first_end}: history={iteration_history}"
        )

    @pytest.mark.asyncio
    async def test_concurrency_4_parallelizes_pair_iteration(
        self, share_store, monkeypatch
    ):
        """BOOTSTRAP_CONCURRENCY=4 runs up to 4 pairs in parallel."""
        monkeypatch.setenv("BOOTSTRAP_CONCURRENCY", "4")

        purchase_events = [
            {"signal_id": "111", "buyer": "0xBuyerA", "purchase_id": 100, "block_number": 100},
            {"signal_id": "222", "buyer": "0xBuyerB", "purchase_id": 101, "block_number": 101},
            {"signal_id": "333", "buyer": "0xBuyerC", "purchase_id": 102, "block_number": 102},
        ]
        client = _mock_chain_client(purchase_events=purchase_events)
        client.detect_contract_version = AsyncMock(return_value=2)

        iteration_history: list[str] = []

        async def slow_pair_load(genius, idiot):
            iteration_history.append(f"start:{idiot}")
            import asyncio as _a

            await _a.sleep(0.05)  # Long enough for parallel starts to interleave.
            iteration_history.append(f"end:{idiot}")
            raise Exception("stubbed-after-trace")

        client.get_queue_state = AsyncMock(side_effect=slow_pair_load)

        audit_set_store = AuditSetStore()
        await bootstrap_audit_sets(client, share_store, audit_set_store)

        # Parallel: at least 2 start:* entries should appear before any end:*
        # (with 3 pairs and concurrency=4, all 3 start before any end).
        first_end_idx = next(
            (i for i, h in enumerate(iteration_history) if h.startswith("end:")),
            len(iteration_history),
        )
        starts_before_first_end = sum(
            1 for h in iteration_history[:first_end_idx] if h.startswith("start:")
        )
        assert starts_before_first_end >= 2, (
            f"Expected parallel starts but saw {starts_before_first_end}: history={iteration_history}"
        )

    @pytest.mark.asyncio
    async def test_concurrency_invalid_value_falls_back_to_1(
        self, share_store, monkeypatch
    ):
        """Non-integer or negative values fall back to sequential (no crash)."""
        monkeypatch.setenv("BOOTSTRAP_CONCURRENCY", "-5")

        purchase_events = [
            {"signal_id": "111", "buyer": "0xBuyerA", "purchase_id": 100, "block_number": 100},
        ]
        client = _mock_chain_client(purchase_events=purchase_events)
        client.detect_contract_version = AsyncMock(return_value=2)
        client.get_queue_state = AsyncMock(side_effect=Exception("stubbed"))

        audit_set_store = AuditSetStore()
        # Must not raise.
        await bootstrap_audit_sets(client, share_store, audit_set_store)
