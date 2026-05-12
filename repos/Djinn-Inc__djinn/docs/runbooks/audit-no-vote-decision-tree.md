# Why didn't this batch settle? — full decision tree

A ready audit batch can fail to land an on-chain vote in **30+** distinct ways.
Most fail silently at `info` level. This runbook is the comprehensive list so a
maintainer can jump from symptom to file:line without re-deriving the gauntlet.

Generated 2026-05-01 by a fresh-eyes Opus subagent reading
`validator/djinn_validator/{main.py, core/mpc_audit.py,
core/mpc_batch_settlement.py, core/mpc_orchestrator.py, core/audit_set.py}`.
Bump this when settlement code changes.

| log_key | file:line | trigger condition | recoverable | external diagnostic | fix owner |
|---|---|---|---|---|---|
| (silent, no log) | audit_set.py:140-144 | `audit_set.settled=True` already set locally | permanent for this set | `GET /v1/audit/summary` `settled` counter; cross-check `cast logs Audit.AuditSettled` | validator-code (mark_settled bug) |
| (silent, no log) | audit_set.py:142-143 | v2 set has fewer than `MIN_BATCH_SIZE` resolved signals | recoverable on more outcomes | `GET /v1/audit/summary` resolved < 10 | operator (more signals) |
| `audit_record_outcomes_unknown_signal` | audit_set.py:284 | outcome arrives but `signal_id` not in `_signal_index` | recoverable next bootstrap | `grep audit_record_outcomes_unknown_signal` | validator-code (bootstrap) |
| `audit_set_not_ready` | mpc_audit.py:82 | local path called on not-ready set (race) | recoverable | warn-level grep | validator-code |
| `settle_abstain_missing_outcomes` | mpc_audit.py:115 | a signal in canonical set has `outcomes=None` | recoverable when ESPN resolves | `/v1/audit/summary` resolved < signals | sdk/operator (ESPN backfill) |
| `settle_abstain_no_shares` / `settle_abstain_no_index_shares` | mpc_audit.py:120, 134 | local ShareStore has zero shares for a signal | permanent locally | `GET /v1/signal/{id}/share_info` 404 | validator-code (build_pi distributed path covers) |
| `settle_abstain_outcome_selection_failed` | mpc_audit.py:150 | trusted-dealer Lagrange returned None | permanent local; covered by HTTP path | log grep | validator-code |
| `audit_set_no_settable_signals` | mpc_audit.py:175 | every signal abstained in loop (`n==0`) | recoverable | log grep | sdk-side |
| `build_pi_abstain_missing_outcomes` | mpc_batch_settlement.py:876 | distributed path: signal lacks outcomes | recoverable | log grep + ESPN status | operator |
| `build_pi_abstain_missing_share` | mpc_batch_settlement.py:885 | local share record absent for a signal | permanent locally | `share_info` 404 | validator-code |
| `build_pi_abstain_no_ledger` | mpc_batch_settlement.py:899 | `purchase_odds_ledger=None` (DI failure) | permanent until restart | `/v1/audit/summary` lacks po fields | validator-code |
| `build_pi_abstain_missing_bpa_wpa` | mpc_batch_settlement.py:906 | no PurchaseOdds row for (signal_id, idiot) AND prefetch failed | recoverable when peer responds with valid root | `cast call Escrow.purchaseBpaRoot(pid)` non-zero | sdk-side / operator |
| `build_pi_vector_length_mismatch` | mpc_batch_settlement.py:914 | `len(bpas)!=len(wpas)` or != outcomes | permanent | warn grep | sdk-side (purchase commit) |
| `purchase_odds_prefetch_root_rpc_failed` | mpc_orchestrator.py:1363 | RPC for `purchaseBpaRoot` failed | recoverable | RPC health check | operator |
| `purchase_odds_prefetch_skip_legacy` | mpc_orchestrator.py:1373 | pre-V6 purchase, on-chain root is zero | permanent (legacy) | `cast call purchaseBpaRoot(pid)` returns 0 | contract-side (V6 backfill) |
| `purchase_odds_prefetch_root_mismatch` | mpc_orchestrator.py:1437 | peer's bpas/wpas don't hash to on-chain root | recoverable from honest peer | warn grep | validator-code (peer adversarial) |
| `shadow_settle_no_batch` | mpc_orchestrator.py:1539 | `build_purchase_inputs_from_audit_set` returned None | recoverable | log grep `batch_is_none=True` | see build_pi_* row |
| `shadow_settle_no_quorum` / `batch_participants_below_threshold` | mpc_orchestrator.py:1564, 1222 | < `threshold-1` peers consistent on share_x | recoverable when peers come back | `GET /v1/signal/{id}/share_info` per peer | operator (peer fleet) |
| `batch_participants_no_peers` | mpc_orchestrator.py:1146 | `_get_peer_validators()` empty | recoverable | metagraph probe | operator |
| `batch_participant_xs_inconsistent` | mpc_orchestrator.py:1182 | peer reports different `share_x` across signals | recoverable on peer restart | warn grep | validator-code (peer share corruption) |
| `shadow_settle_no_local_share` | mpc_orchestrator.py:1577 | local share for `signal_ids[0]` missing | permanent locally | `share_info` 404 | validator-code |
| `shadow_settle_no_self_url` | mpc_orchestrator.py:1604 | own axon IP `0.0.0.0` (not advertised) | recoverable on `btcli serve` | `btcli subnet metagraph` shows 0.0.0.0 | operator |
| `shadow_settle_participant_count_below_threshold` | mpc_orchestrator.py:1617 | after adding self, still `<threshold` | recoverable | log grep | operator |
| `shadow_settle_protocol_failed` | mpc_orchestrator.py:1644 | distributed protocol raised | recoverable | warn grep, `mac_verification_failed` | validator-code/peer |
| `shadow_settle_score_out_of_range` | mpc_orchestrator.py:1677 | reconstructed score > 100x notional (field-element artifact) | recoverable on inputs fix | warn grep | validator-code (MPC bug) |
| `shadow_settle_submit_shape_failed` | mpc_orchestrator.py:1659 | int cast on notional/purchase_id raised | permanent | warn grep | validator-code |
| `settlement_skipped_no_batch_result` | main.py:736 | local result None AND (HTTP_SUBMIT off OR distributed None OR chain readonly) | recoverable when flag/peer/wallet healthy | `cast call neuron addresses` + `/v1/health.batch_settlement_http_submit` | operator (flip flag) |
| `submit_from_shadow_preflight_skip` (reason=finalized) | main.py:574 | `OV.isFinalized(batchKey)` already true | terminal-OK; mark_settled fires | `cast call OutcomeVoting.isFinalized(batchKey)` | none |
| `submit_from_shadow_already_voted_awaiting_quorum` | main.py:589 | `OV.hasVoted(batchKey, signer)` true, finalized false | recoverable when peers vote | `cast call OV.voteCounts(batchKey)` | operator (peer fleet) |
| `skip_settle_below_min_batch_no_request_no_timeout` (shadow) | main.py:630 | batch < 10 AND no `requestEarlyExit` AND 45-day SLA not elapsed | recoverable: idiot calls requestEarlyExit or wait | `cast call OV.earlyExitRequested(...)`; check signal age | operator (genius/idiot UX) |
| `skip_audit_vote_below_min_batch_no_request_no_timeout` (local) | main.py:817 | same gate on local path | same | same | same |
| `audit_vote_preflight_skip` (finalized) | main.py:771 | local-path: OV finalized | terminal-OK | `cast call OV.isFinalized(batchKey)` | none |
| `audit_vote_already_cast_awaiting_quorum` | main.py:784 | local-path: hasVoted true, not finalized | recoverable | `cast call OV.voteCounts(batchKey)` per signer | operator |
| `audit_vote_already_cast_race` (AlreadyVoted thrown) | main.py:881 | submit raced and reverted | recoverable | grep + `cast logs OV.VoteSubmitted` | none |
| `audit_vote_skipped_finalized` | main.py:879 | revert was `CycleAlreadyFinalized` / `BatchAlreadyAudited` | terminal-OK; mark_settled | `cast logs Audit.AuditSettled` | none |
| `audit_vote_failed` | main.py:885 | submit reverted with any other custom error | depends: BatchTooSmall recoverable, ScoreHashMismatch permanent until peers re-vote, UnknownSigner permanent until OV.addSigner | error grep + `cast run <tx_hash>` to decode selector | contract-side / operator (signer registration) / validator-code (scoreHash divergence) |
| `audit_vote_receipt_timeout` | main.py:902 | tx sent but not mined within 120s | recoverable next epoch (becomes AlreadyVoted) | `cast tx <hash>` + `cast nonce <signer>` | operator (gas / RPC) |
| `audit_vote_reverted` | main.py:920 | tx mined with `status=0` | recoverable iff transient | `cast run <tx_hash>` for selector | depends |
| `audit_vote_skipped_no_writer` | main.py:948 | `chain_client is None` OR `can_write=False` | recoverable | `/v1/health.chain_client_can_write` | operator (env: CHAIN_PRIVATE_KEY) |
| `submit_from_shadow_reverted` | main.py:692 | shadow-path tx mined `status=0` | recoverable iff transient | `cast run <hash>` | depends |
| `submit_from_shadow_receipt_timeout` | main.py:701 | shadow-path tx not mined in 120s | recoverable | `cast tx <hash>` | operator |
| `submit_from_shadow_failed` | main.py:722 | shadow-path submit raised non-AlreadyVoted/Finalized exception | recoverable iff transient | error grep | depends |

## Silent killers (info-level, easy to miss)
- `build_pi_abstain_missing_bpa_wpa` — PurchaseOdds rows missing
- `purchase_odds_prefetch_skip_legacy` / `_root_mismatch` — pre-V6 dead-end + adversarial peer
- `shadow_settle_no_quorum` / `batch_participant_xs_inconsistent` — peer share_x divergence
- `skip_(settle|audit_vote)_below_min_batch_no_request_no_timeout` — the 10-batch gate
- `audit_vote_already_cast_awaiting_quorum` — vote landed, but no telemetry on peer votes

## Top-3 minimal external probes
1. `cast call OutcomeVoting.isFinalized(batchKey) / hasVoted(batchKey,signer) / voteCounts(batchKey)` — separates "no quorum" from "we never voted"
2. `cast run <tx_hash>` on any `audit_vote_*` tx — decodes the custom-error selector that `audit_vote_failed` truncates to 500 chars
3. `GET /v1/audit/summary` per validator AND `cast logs OutcomeVoting.VoteSubmitted ~5k blocks` — local `settled` counter is bookkeeping only (3 of 4 paths skip the on-chain check)
