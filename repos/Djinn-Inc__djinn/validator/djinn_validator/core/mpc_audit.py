"""Batch MPC settlement for audit sets.

Processes an entire audit set (10 signals × 10 lines = 100 outcomes) in
one pass, outputting only aggregate statistics.  No individual signal
outcome is ever revealed to validators.

Quality score formula (matches Audit.sol computeScore):
  FAVORABLE:   +notional × (odds - 1e6) / 1e6
  UNFAVORABLE: -notional × sla_bps / 10_000
  VOID:         0
"""

from __future__ import annotations

from dataclasses import dataclass

import structlog

from djinn_validator.core.audit_set import AuditSet
from djinn_validator.core.mpc_outcome import prototype_select_outcome
from djinn_validator.core.outcomes import Outcome
from djinn_validator.core.shares import ShareStore
from djinn_validator.utils.crypto import BN254_PRIME, Share

log = structlog.get_logger()


@dataclass
class AuditResult:
    """Aggregate settlement result — the only output of batch MPC."""

    genius: str
    idiot: str
    cycle: int
    quality_score: int  # Signed, in notional units (USDC 6-decimal)
    total_notional: int  # Sum of notional for non-void signals (CF-06)
    wins: int
    losses: int
    voids: int
    n: int
    purchase_ids: list[int] | None = None  # v2: on-chain purchase IDs in this batch


def _compute_signal_quality(
    outcome: Outcome,
    notional: int,
    odds: int,
    sla_bps: int,
) -> int:
    """Compute per-signal quality contribution.

    Matches Audit.sol computeScore() formula.
    """
    if outcome == Outcome.FAVORABLE:
        return notional * (odds - 1_000_000) // 1_000_000
    elif outcome == Outcome.UNFAVORABLE:
        return -(notional * sla_bps // 10_000)
    return 0  # VOID or PENDING


def batch_settle_audit_set(
    audit_set: AuditSet,
    share_store: ShareStore,
    threshold: int = 1,
    prime: int = BN254_PRIME,
) -> AuditResult | None:
    """Run batch MPC settlement on a complete audit set.

    For each signal:
    1. Retrieve index shares from the share store
    2. Use prototype_select_outcome to extract the real outcome
    3. Compute quality contribution using the Audit.sol formula

    Returns aggregate statistics only — never individual outcomes.

    In prototype/dev mode, prototype_select_outcome reconstructs the index
    locally.  In production with distributed MPC, each validator only holds
    one Shamir share and the polynomial evaluation prevents any single
    validator from learning any index.
    """
    if not audit_set.ready_for_settlement:
        log.warning(
            "audit_set_not_ready",
            genius=audit_set.genius_address,
            idiot=audit_set.idiot_address,
            cycle=audit_set.cycle,
        )
        return None

    quality_score = 0
    total_notional = 0
    wins = 0
    losses = 0
    voids = 0
    n = 0
    settled_signal_ids: set[str] = set()

    # Determinism contract (P0-01 Stage C, v1577): iterate ALL signals in
    # the audit_set in ascending (purchase_id, signal_id) order and abstain
    # on any missing data. Both v1 and v2 share this code path now —
    # v2's previous "iterate resolved_signals, continue on missing" was
    # the upstream counterpart to v1576's mpc_batch_settlement divergence:
    # validators with slightly different resolved sets produced different
    # AuditResult.quality_score + AuditResult.purchase_ids, which in turn
    # produced different scoreHash + batchKey on-chain, and the 4-of-6
    # OutcomeVoting threshold never coalesced (8 VoteSubmitted, 0
    # QuorumReached across 5k Sepolia blocks pre-v1577).
    # v1637 (2026-05-01): mirror mpc_batch_settlement.build_purchase_inputs
    # — iterate only the resolved signals in canonical order, so the local
    # trusted-dealer path produces the same batch_purchase_ids (when it
    # produces any) as the shadow path. v1577 comment above is now
    # superseded: "abstain on any missing" was a workaround for the same
    # divergence; the actual root cause was both paths iterating
    # UNRESOLVED signals from "ready" v2 sets.
    resolved_items = [(sid, s) for sid, s in audit_set.signals.items() if s.outcomes is not None]
    signal_iter = sorted(
        resolved_items,
        key=lambda kv: (int(kv[1].purchase_id), kv[0]),
    )

    # v1706: per-signal abstain reason on the v1 audit path. Uses the shared
    # safe_label_inc helper so test paths that bypass the metrics module
    # continue to work.
    from djinn_validator.api.metrics import (
        SETTLE_ABSTAIN_REASON,
        safe_label_inc,
    )

    def _settle_tick(reason: str) -> None:
        safe_label_inc(SETTLE_ABSTAIN_REASON, reason=reason)

    for signal_id, signal in signal_iter:
        if signal.outcomes is None:
            log.info("settle_abstain_missing_outcomes", signal_id=signal_id[:20])
            _settle_tick("missing_outcomes")
            return None

        all_records = share_store.get_all(signal_id)
        if not all_records:
            log.info("settle_abstain_no_shares", signal_id=signal_id[:20])
            _settle_tick("no_shares")
            return None

        index_shares: list[Share] = []
        for rec in all_records:
            if rec.encrypted_index_share and len(rec.encrypted_index_share) > 0:
                index_shares.append(
                    Share(
                        x=rec.share.x,
                        y=int.from_bytes(rec.encrypted_index_share, "big"),
                    )
                )

        if not index_shares:
            log.info(
                "settle_abstain_no_index_shares",
                signal_id=signal_id[:20],
                all_records_count=len(all_records),
            )
            _settle_tick("no_index_shares")
            return None

        # MPC: extract the real outcome without revealing the index
        outcome_value = prototype_select_outcome(
            index_shares,
            [o.value for o in signal.outcomes],
            threshold=threshold,
            prime=prime,
        )

        if outcome_value is None:
            log.info("settle_abstain_outcome_selection_failed", signal_id=signal_id[:20])
            _settle_tick("outcome_selection_failed")
            return None

        outcome = Outcome(outcome_value)
        contribution = _compute_signal_quality(
            outcome,
            signal.notional,
            signal.odds,
            signal.sla_bps,
        )
        quality_score += contribution

        if outcome == Outcome.FAVORABLE:
            wins += 1
            total_notional += signal.notional
        elif outcome == Outcome.UNFAVORABLE:
            losses += 1
            total_notional += signal.notional
        elif outcome == Outcome.VOID:
            voids += 1
            # Void signals excluded from total_notional (CF-06)
        n += 1
        settled_signal_ids.add(signal_id)

    if n == 0:
        log.warning(
            "audit_set_no_settable_signals",
            genius=audit_set.genius_address,
            idiot=audit_set.idiot_address,
            cycle=audit_set.cycle,
        )
        return None

    log.info(
        "audit_set_settled",
        genius=audit_set.genius_address,
        idiot=audit_set.idiot_address,
        cycle=audit_set.cycle,
        quality_score=quality_score,
        total_notional=total_notional,
        wins=wins,
        losses=losses,
        voids=voids,
        n=n,
    )

    # Collect purchase IDs for v2 vote submission in the same canonical
    # order used for iteration above. Because v1577 abstains on ANY missing
    # signal, reaching this point means every signal contributed and the
    # batch is the full audit_set, sorted by (purchase_id, signal_id). The
    # on-chain OutcomeVoting.sol batchKey = keccak256(
    #   genius, idiot, keccak256(purchase_ids)
    # ) is now byte-identical across validators that reach this line.
    batch_purchase_ids: list[int] | None = None
    if audit_set.version == 2:
        batch_purchase_ids = [s.purchase_id for _signal_id, s in signal_iter if s.purchase_id > 0]

    return AuditResult(
        genius=audit_set.genius_address,
        idiot=audit_set.idiot_address,
        cycle=audit_set.cycle,
        quality_score=quality_score,
        total_notional=total_notional,
        wins=wins,
        losses=losses,
        voids=voids,
        n=n,
        purchase_ids=batch_purchase_ids,
    )
