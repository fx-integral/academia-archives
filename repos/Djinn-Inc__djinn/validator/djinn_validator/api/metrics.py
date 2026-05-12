"""Prometheus metrics for the Djinn validator.

Exposes key operational metrics via a /metrics endpoint.
"""

from __future__ import annotations

from prometheus_client import Counter, Gauge, Histogram, generate_latest

# --- Request metrics ---
REQUEST_COUNT = Counter(
    "djinn_validator_requests_total",
    "Total HTTP requests",
    ["method", "endpoint", "status"],
)

REQUEST_LATENCY = Histogram(
    "djinn_validator_request_latency_seconds",
    "Request latency in seconds",
    ["endpoint"],
    buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
)

# --- Business metrics ---
SHARES_STORED = Counter(
    "djinn_validator_shares_stored_total",
    "Total key shares stored",
)

PURCHASES_PROCESSED = Counter(
    "djinn_validator_purchases_processed_total",
    "Total signal purchases processed",
    ["result"],  # available, unavailable, error
)

MPC_SESSIONS = Counter(
    "djinn_validator_mpc_sessions_total",
    "Total MPC sessions initiated",
    ["mode"],  # single_validator, distributed
)

MPC_DURATION = Histogram(
    "djinn_validator_mpc_duration_seconds",
    "End-to-end MPC availability check duration",
    ["mode"],  # single_validator, distributed
    buckets=(0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 15.0, 30.0),
)

MPC_ERRORS = Counter(
    "djinn_validator_mpc_errors_total",
    "MPC errors by reason",
    ["reason"],  # timeout, network, mac_failure, ot_setup_failure, insufficient_peers
)

RPC_FAILOVERS = Counter(
    "djinn_validator_rpc_failovers_total",
    "RPC endpoint failover events",
)

CIRCUIT_BREAKER_STATE = Gauge(
    "djinn_validator_circuit_breaker_open",
    "Whether a circuit breaker is open (1) or closed (0)",
    ["target"],  # rpc, peer_{uid}
)

OUTCOMES_ATTESTED = Counter(
    "djinn_validator_outcomes_attested_total",
    "Total outcomes attested",
    ["outcome"],  # favorable, unfavorable, void
)

ERROR_REPORT_FORWARD = Counter(
    "djinn_validator_error_report_forward_total",
    "Error-report forwarding outcomes (silent drops are gone in v1743+)",
    ["outcome"],  # ok, no_token, http_4xx, http_5xx, network, exhausted
)

ERROR_REPORT_PENDING = Gauge(
    "djinn_validator_error_report_pending",
    "Number of feedback reports queued for GitHub forward",
)

# --- State metrics ---
ACTIVE_SHARES = Gauge(
    "djinn_validator_active_shares",
    "Number of key shares currently stored",
)

MPC_ACTIVE_SESSIONS = Gauge(
    "djinn_validator_mpc_active_sessions",
    "Number of active MPC sessions",
)

ATTESTATION_DISPATCHED = Counter(
    "djinn_validator_attestation_dispatched_total",
    "Total web attestation requests dispatched to miners",
)

ATTESTATION_VERIFIED = Counter(
    "djinn_validator_attestation_verified_total",
    "Total web attestation proofs verified",
    ["valid"],  # true, false
)

ATTESTATION_GATED = Counter(
    "djinn_validator_attestation_gated_total",
    "Attestation requests rejected by burn gate",
    ["reason"],  # invalid_tx, already_consumed, insufficient_amount
)

BURN_GATE_FAIL_OPEN = Counter(
    "djinn_validator_burn_gate_fail_open_total",
    "Times /v1/burn/verify IP allowlist failed open (metagraph unavailable)",
    ["reason"],  # neuron_missing, metagraph_missing, metagraph_read_error
)

ATTESTATION_DURATION = Histogram(
    "djinn_validator_attestation_duration_seconds",
    "End-to-end attestation round-trip time",
    buckets=(1.0, 5.0, 10.0, 20.0, 30.0, 60.0, 120.0),
)

NOTARY_SESSIONS_ASSIGNED = Counter(
    "djinn_validator_notary_sessions_assigned_total",
    "External notary sessions assigned to miners",
    ["status"],  # ok, no_miners, auth_failed
)

RATE_LIMIT_REJECTIONS = Counter(
    "djinn_validator_rate_limit_rejections_total",
    "Total requests rejected by rate limiter",
)

UPTIME_SECONDS = Gauge(
    "djinn_validator_uptime_seconds",
    "Validator uptime in seconds",
)

BT_CONNECTED = Gauge(
    "djinn_validator_bt_connected",
    "Whether connected to Bittensor (1=yes, 0=no)",
)

# --- Audit bootstrap source (v1709) ---
# Counts which data path each pair-bootstrap took. Helps operators tell
# fleet-wide "is the subgraph fast-path actually firing or are we still
# on RPC?" without SSH log access. source values:
#   subgraph         — subgraph fresh + loaded rows successfully
#   subgraph_stale   — subgraph reachable but trailing chain too far
#   subgraph_then_rpc — subgraph fresh but query errored; fell back to RPC
#   rpc              — no subgraph configured / probe failed; using RPC scan
AUDIT_BOOTSTRAP_SOURCE = Counter(
    "djinn_validator_audit_bootstrap_source_total",
    "Per-bootstrap-attempt data source for audit_set_store population.",
    ["source"],
)


# --- Audit-set push gossip (v1710) ---
# When a validator's bootstrap finds a new (genius, idiot, signal_id,
# purchase_id) tuple it gossips to peers; peers verify on-chain + add
# to their own audit_set_store. Mirror counter shape of v1704
# GOSSIP_PUSH_RESULT and v1707 GOSSIP_RECEIVE_RESULT for consistency.
# Use case: subgraph fast-path covers steady-state; gossip is the
# fallback when the subgraph is stale, errored, or unreachable.
AUDIT_GOSSIP_PUSH_RESULT = Counter(
    "djinn_validator_audit_gossip_push_result_total",
    "Per-peer outcome of audit-set push gossip.",
    ["outcome"],
    # outcome values: sent / peer_404 / peer_status_4xx / peer_status_5xx /
    # peer_unreachable / no_peers
)

AUDIT_GOSSIP_RECEIVE_RESULT = Counter(
    "djinn_validator_audit_gossip_receive_result_total",
    "Per-incoming-gossip outcome on /v1/audit/gossip.",
    ["outcome"],
    # outcome values:
    #  added            — chain-verified, add_signal succeeded
    #  duplicate        — already in audit_set_store; no-op
    #  chain_mismatch   — chain RPC reports different (G, I, signal) than
    #                     the gossip claims; reject for forensics
    #  chain_unreachable — couldn't verify; rejected
    #  no_audit_set     — audit_set_store unavailable (config bug)
    #  bad_request      — malformed payload
)


# --- Shadow-settle stage progress (v1686+) ---
# Tracks intermediate stages of shadow_settle so we can localize hangs
# between "attempt" and any outcome label. If `attempt` ticks but no
# `outcome` label ticks, the function is blocked between two stages —
# the last-ticked stage tells operators which `await` is hanging.
SHADOW_SETTLE_STAGE = Counter(
    "djinn_validator_shadow_settle_stages_total",
    "Stage progression inside try_shadow_distributed_settlement.",
    ["stage"],
    # stage values (in execution order):
    #   pre_recovery        — entered
    #   post_bpa_wpa        — past _prefetch_missing_purchase_odds_from_peers
    #   post_outcome_recv   — past recover_missing_outcomes
    #   post_recovery       — past recover_missing_shares (all recovery done)
    #   pre_build_pi        — about to call build_purchase_inputs_from_audit_set
    #   post_build_pi       — batch assembled
    #   post_canonical_pid  — past v1681 canonical PID divergence check
    #   post_postbuild_pregate — past v1660 post-build pregate (consent/timeout)
    #   pre_resolve_peers   — about to resolve_batch_participants
    #   post_resolve_peers  — peers resolved
    #   pre_run_mpc         — about to run_batch_settlement
    #   post_run_mpc        — MPC returned (success OR exception caught)
)

# --- Shadow-settle protocol_failed error categorization (v1694+) ---
# When SHADOW_SETTLE_OUTCOME[protocol_failed] ticks, this counter records
# the exception type so operators can localize the failure mode without
# log access. Low cardinality (~10-20 distinct types max).
SHADOW_SETTLE_PROTOCOL_FAILURE = Counter(
    "djinn_validator_shadow_settle_protocol_failures_total",
    "MPC protocol exception types (when SHADOW_SETTLE_OUTCOME[protocol_failed] ticks).",
    ["error_type"],
    # Common values: RuntimeError, HTTPError, BatchSessionError, TimeoutError,
    # ConnectError, etc.
)

# --- Shadow-settle / vote-submission metrics (v1684+) ---
# Diagnoses why a validator with full data is silent on chain. Counters tick on
# every shadow_settle outcome so operators can read /metrics and tell whether
# the validator is even attempting to coordinate, where it abstains, and why
# its attempts fail to reach a vote.
SHADOW_SETTLE_OUTCOME = Counter(
    "djinn_validator_shadow_settle_outcomes_total",
    "Outcome of each shadow_settle attempt by reason. Helps diagnose silent validators.",
    ["outcome"],
    # outcome values:
    #  attempt              — entered try_shadow_distributed_settlement
    #  abstain_no_share     — no local Shamir share for any signal in batch
    #  abstain_no_peers     — no peers discovered from metagraph
    #  abstain_no_batch     — build_pi returned empty (no local data)
    #  abstain_below_threshold     — fewer participants than Shamir threshold
    #  abstain_subset_divergence   — local PIDs differ from chain canonical
    #  abstain_pregate_min_batch   — local batch < MIN before MPC
    #  abstain_pre_mpc_already_voted — v1699: hasVoted=true pre-MPC; skipped
    #  abstain_pre_mpc_finalized     — v1699: finalized=true pre-MPC; mark_settled
    #  abstain_no_self_url         — own axon ip/port not published
    #  abstain_local_x_collision   — peer claims same x as local
    #  protocol_failed             — run_batch_settlement raised
    #  quality_score_out_of_range  — sanity gate rejected reconstructed score
    #  completed                   — distributed result returned to caller
)

VOTE_SUBMIT_OUTCOME = Counter(
    "djinn_validator_vote_submit_outcomes_total",
    "Outcome of each chain_client.submit_vote call after a shadow_settle completion.",
    ["outcome"],
    # outcome values:
    #  attempted    — submit_vote called
    #  submitted    — tx broadcast (no receipt yet)
    #  confirmed    — receipt status=1
    #  reverted     — receipt status=0
    #  receipt_timeout — wait_for_receipt timed out
    #  already_voted   — duplicate vote rejected by contract
    #  cycle_finalized — batch already audited
    #  network_error   — RPC/HTTP error before tx broadcast
    #  pregate_skip    — submit gate skipped (below MIN, no consent, not timeout)
    #  preflight_already_voted — pre-flight hasVoted=true (this validator already voted, quorum pending)
    #  preflight_finalized     — pre-flight finalized=true (quorum already reached)
    #  skipped_flag_off        — DJINN_FF_BATCH_SETTLEMENT_HTTP_SUBMIT off; shadow result discarded
    #  skipped_no_chain_client — chain_client unavailable; can't submit
    #  skipped_no_write        — chain_client.can_write=False (no signing key)
)

# Per-cause breakdown of the SHADOW_SETTLE_OUTCOME[abstain_no_batch] rollup
# (v1698, 2026-05-04). When build_purchase_inputs_from_audit_set returns None,
# the validator drops the whole batch. The high-level abstain_no_batch counter
# tells operators THAT this happened but not WHY. Without per-reason labels we
# can't tell whether to prioritize share recovery (P1-33), BPA/WPA gossip
# reliability (P1-33), or upstream signal-resolution backfill — each abstain
# cause maps to a different fix.
# Per-attempt result of share recovery (v1700). When a validator misses a
# share at commit time, recover_missing_shares() polls peers for forwarding
# ciphertexts. Without this counter, the build_pi missing_share rollup is
# blind to whether recovery succeeded, was tried-but-no-peer-had-it, or
# failed inside decrypt/store. Operators read /metrics to localize the gap.
SHARE_RECOVERY_RESULT = Counter(
    "djinn_validator_share_recovery_result_total",
    "Per-signal outcome of share recovery polling.",
    ["outcome"],
    # outcome values:
    #  recovered           — peer returned a forwarding share, decrypted, stored
    #  no_peer_had_it      — exhausted peers, none had a forwarding blob
    #  skip_present        — share already in store; skipped recovery
    #  skip_already_stored — race: another path stored mid-recovery
    #  decrypt_failed_<E>  — peer ciphertext decrypt threw exception type E
    #  store_failed_<E>    — share_store.store threw exception type E
    #  bad_shape_<E>       — peer response missing or wrong-typed fields
    #  share_y_out_of_field — recovered y outside BN254_PRIME
    #  peer_status_<C>     — peer returned non-200, non-404 HTTP status C
    #  peer_unreachable    — httpx raised connect/read/network error (v1701)
    #  peer_404            — peer responded 404 no forwarding entry (v1701).
    #                        Distinguish from peer_unreachable: 404 means the
    #                        genius bundle never landed on that peer (upstream
    #                        replication gap), unreachable means the peer was
    #                        unreachable from this validator at probe time.
)


BUILD_PI_ABSTAIN_REASON = Counter(
    "djinn_validator_build_pi_abstain_reason_total",
    "Per-cause breakdown of build_pi None returns. Localizes which data layer is missing.",
    ["reason"],
    # reason values:
    #  no_audit_set       — audit_set is None or empty (caller bug)
    #  no_resolved        — audit_set has signals but none with outcomes (waiting)
    #  missing_share      — Shamir index share record absent on this validator
    #  empty_index_share  — record present but encrypted_index_share is empty
    #                       bytes; commit path stored an incomplete record
    #                       (v1700; previously rolled into missing_share)
    #  no_ledger          — purchase_odds_ledger uninitialized (config bug)
    #  missing_bpa_wpa    — BPA/WPA vectors not gossiped here yet (P1-33)
    #  vector_mismatch    — len(bpas) != len(wpas) != len(outcomes) (data corruption)
    #  empty_batch        — loop produced empty list (defensive; shouldn't occur)
)


# Per-incoming-gossip outcome on receive endpoints (v1707).
# Symmetric closure to v1704 GOSSIP_PUSH_RESULT. v1704 ticks on the
# originating validator's push side — so if push.sent=N but the next
# layer of recovery still 404s, we know either the network dropped
# silently OR the receive endpoint accepted-then-discarded. v1707 ticks
# on the RECEIVE side so push.sent=N must equal receive.stored+
# receive.duplicate+receive.bad_request across the fleet (modulo per-
# validator metric reset windows).
GOSSIP_RECEIVE_RESULT = Counter(
    "djinn_validator_gossip_receive_result_total",
    "Per-incoming-gossip outcome on /v1/purchase_odds/record + /v1/outcomes/gossip (v1707).",
    ["path", "outcome"],
    # path values: "purchase_odds" | "outcomes"
    # outcome values:
    #  stored             — first-time record, ledger.record / receive_gossip OK
    #  duplicate          — same record already present (idempotent)
    #  bad_request        — 400 validation failure (ValueError)
    #  no_ledger          — 503 service not configured (purchase_odds)
    #  ledger_exception   — ValueError raised by ledger.record / receive_gossip
    #  replay_disputed    — outcomes only: peer outcomes != local ESPN
    #  replay_pending     — outcomes only: local ESPN says game not final
    #  unknown_signal     — outcomes only: signal not registered locally
)


# Per-bundle outcome of /v1/signal/bundle (v1705).
# Closes the receive-side gap on the genius's bundle fan-out. With
# v1701 we see share recovery fail with peer_404 (peers don't have
# forwarding entries), but we can't tell whether those peers ever
# received a bundle to begin with. v1705 ticks one of:
#   complete           — bundle had own entry + N forwarding entries, all stored
#   missing_own_entry  — bundle didn't include this validator's address
#                        (genius client targeted a different signer set)
#   own_decrypt_failed — own SealedBox could not be decrypted
#   own_oof_field      — decrypted share_y outside BN254 field
#   own_already_stored — idempotent re-bundle (counted as success)
#   forwarding_failed  — at least one forwarding store_forwarding raised
# A validator with bundle_stored_total{outcome="missing_own_entry"} > 0
# is being targeted by a genius client that doesn't see them as an OV
# signer. peer_404 on share recovery against THAT validator is then
# a true upstream gap on the genius side.
BUNDLE_STORE_RESULT = Counter(
    "djinn_validator_bundle_store_result_total",
    "Per-bundle outcome of /v1/signal/bundle storage (v1705).",
    ["outcome"],
)


# v1706: per-signal abstain breakdown for the v1 settlement path
# (mpc_audit.py::settle_audit_set). v1698's BUILD_PI_ABSTAIN_REASON only
# covers the v2 BATCH path. The v1 per-signal path was uninstrumented; logs
# show settle_abstain_outcome_selection_failed and settle_abstain_no_shares
# firing in production but no operator-visible counter. Closes the gap.
SETTLE_ABSTAIN_REASON = Counter(
    "djinn_validator_settle_abstain_reason_total",
    "Per-signal abstain reason in mpc_audit.settle_audit_set (v1 path).",
    ["reason"],
    # reason values:
    #  missing_outcomes          — signal.outcomes is None (defensive; resolved
    #                              filter above should prevent this firing)
    #  no_shares                 — share_store.get_all returned empty list;
    #                              this validator has no record at all for the
    #                              signal (commit fan-out + recovery both lost)
    #  no_index_shares           — records exist but none has a non-empty
    #                              encrypted_index_share; same bug class as
    #                              v1700 empty_index_share but on the v1 path
    #  outcome_selection_failed  — prototype_select_outcome returned None;
    #                              Shamir reconstruction failed (insufficient
    #                              shares, out-of-range index, etc.)
)


# v1707: per-call result of OutcomeAttestor.resolve_signal. We have plenty
# of metrics now for what happens AFTER an outcome is resolved, but the
# resolution function itself was silent. With outcomes_resolved_total=0
# fleet-wide despite hundreds of registered signals (2026-05-04), operators
# need to see WHY: are signals not_registered (queue empty), still
# not_final (games haven't ended), or do they end up all_pending (final
# game but no decoy line matched)? This counter answers that.
RESOLVE_SIGNAL_RESULT = Counter(
    "djinn_validator_resolve_signal_result_total",
    "Per-call result of OutcomeAttestor.resolve_signal.",
    ["outcome"],
    # outcome values:
    #  not_registered     — signal_id not in _pending_signals (caller bug)
    #  already_resolved   — meta.resolved=True; idempotent skip
    #  not_final          — fetch_event_result returned status != final/postponed/cancelled
    #  all_pending        — game is final but every decoy line resolved to PENDING
    #                       (decoys reference markets/props ESPN doesn't expose;
    #                       suggests sport-specific resolver gaps)
    #  race_already_resolved — second pass after first already wrote outcomes
    #  resolved           — happy path: outcomes written, _resolved_total+=1
)


# Per-peer outcome of validator-to-validator push gossip (v1704).
# Closes the symmetry with v1702 (BPA/WPA prefetch) and v1703 (outcome
# recovery): if the pull side reports peer_404 dominantly but the push
# side ticks 0 sent, the originating validator never gossiped at all
# (different bug than the receiving validator dropping the gossip).
# Two paths share the same counter via the `path` label so operators
# can read both BPA/WPA gossip and outcome gossip in one place.
GOSSIP_PUSH_RESULT = Counter(
    "djinn_validator_gossip_push_result_total",
    "Per-peer outcome of validator-to-validator push gossip (v1704).",
    ["path", "outcome"],
    # path values: "purchase_odds" | "outcomes"
    # outcome values:
    #  sent              — 200 from peer (delivery accepted; for outcomes,
    #                       semantic accept/duplicate/etc still encoded
    #                       in log line, but transport succeeded)
    #  peer_404          — peer endpoint not found (peer is on old version)
    #  peer_status_4xx   — non-200 4xx (auth fail, payload reject, etc.)
    #  peer_status_5xx   — non-200 5xx (peer crashed / timed out internally)
    #  peer_unreachable  — httpx error (connect, read, network)
)


# Per-signal outcome of pull-side outcome recovery (v1703).
# recover_missing_outcomes polls peers' /v1/outcomes/{signal} when the
# local OutcomeAttestor hasn't resolved a signal but it's needed for
# the audit batch. Without this counter, outcomes_resolved_total=0 on
# UID 0 leaves operators blind to whether peers genuinely lack the
# outcome (peer_404), are unreachable (peer_unreachable), peer responses
# are getting rejected at replay-verify (replay_disputed), or our own
# ESPN says the game is still pending (replay_pending_local). 11
# bounded outcomes mirror the share_recovery pattern.
OUTCOME_RECOVERY_RESULT = Counter(
    "djinn_validator_outcome_recovery_result_total",
    "Per-signal outcome of pull-side outcome recovery polling.",
    ["outcome"],
    # outcome values:
    #  recovered                    — peer 200, replay-verify accepted
    #  skip_already_resolved        — local resolution beat us
    #  replay_disputed              — peer's outcomes != local ESPN fetch
    #  replay_pending_local         — our ESPN says game not final yet
    #  no_peer_had_it               — exhausted peers, no resolved data
    #  registration_failed          — signal metadata couldn't be registered
    #  receive_gossip_err           — receive_gossip raised an exception
    #  unknown_signal_after_register — race in metadata registration
    #  peer_404                     — peer responded 404
    #  peer_unreachable             — httpx raised connect/read/network err
    #  peer_status_4xx / 5xx        — non-200 non-404 (bounded buckets)
    #  bad_json                     — peer 200 but body wasn't JSON
)


# Per-attempt outcome of BPA/WPA prefetch from peer validators (v1702).
# Build-PI's missing_bpa_wpa rollup tells us THAT a row is missing, but
# not why. _prefetch_missing_purchase_odds_from_peers polls peers for
# every absent (signal, buyer) row, validates against the on-chain
# Merkle root, and records on success. Without this counter we cannot
# tell upstream-gossip gaps (peer_404 dominant) from peer adversarial
# data (root_mismatch) from RPC reliability (root_rpc_failed) — each
# implies a different remediation. Bounded cardinality: 11 outcomes,
# no per-uid label.
PURCHASE_ODDS_PREFETCH_RESULT = Counter(
    "djinn_validator_purchase_odds_prefetch_result_total",
    "Per-attempt outcome of BPA/WPA prefetch from peers (v1702).",
    ["outcome"],
    # outcome values:
    #  recovered          — peer 200 + Merkle-verified + ledger.record OK
    #  peer_404           — peer responded 404 (no row locally; gossip gap)
    #  peer_unreachable   — httpx raised connect/read/network error
    #  peer_status_4xx    — peer non-200 4xx (other than 404)
    #  peer_status_5xx    — peer non-200 5xx
    #  bad_shape          — peer 200 but missing/wrong-typed JSON keys
    #  root_compute_err   — local Merkle compute on peer vectors threw
    #  root_mismatch      — peer vectors didn't hash to on-chain root
    #                       (peer is buggy, stale, or adversarial)
    #  root_rpc_failed    — couldn't read on-chain root via chain_client
    #  zero_root_legacy   — pre-V6 purchase, no on-chain commitment exists
    #  skipped_no_pid     — audit_signal had purchase_id <= 0
    #  record_failed      — ledger.record raised after Merkle pass
)


def safe_label_inc(counter: Counter, **labels: str) -> None:
    """Increment ``counter`` for the given label values, swallowing any error.

    Diagnostic counters are best-effort: a failure to increment must NEVER
    break the surrounding hot-path code. This helper centralizes the
    try/except pattern that was previously copy-pasted as private closures
    across mpc_audit, mpc_batch_settlement, outcomes, share_recovery, etc.

    Pass labels as keyword arguments matching the counter's label names:

        safe_label_inc(BUILD_PI_ABSTAIN_REASON, reason="missing_share")
        safe_label_inc(SHARE_RECOVERY_RESULT, outcome="peer_404")

    The helper is import-cheap (no per-call import); call-site cost is a
    single Python attribute lookup plus the underlying Counter.inc(),
    measured at <1µs/call.
    """
    try:
        counter.labels(**labels).inc()
    except Exception:
        pass


def metrics_response() -> bytes:
    """Generate Prometheus-compatible metrics text."""
    return generate_latest()
