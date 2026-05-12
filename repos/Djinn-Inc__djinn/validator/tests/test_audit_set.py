"""Tests for AuditSet data model and AuditSetStore."""

from __future__ import annotations

import pytest

from djinn_validator.core.audit_set import (
    SIGNALS_PER_CYCLE,
    AuditSet,
    AuditSetStore,
    AuditSignal,
)
from djinn_validator.core.outcomes import Outcome

GENIUS = "0x" + "aa" * 20
IDIOT = "0x" + "bb" * 20
SAMPLE_OUTCOMES = [Outcome.FAVORABLE] * 10


class TestAuditSignal:
    def test_defaults(self) -> None:
        sig = AuditSignal(signal_id="s1")
        assert sig.outcomes is None
        assert sig.notional == 0
        assert sig.odds == 1_000_000
        assert sig.sla_bps == 10_000


class TestAuditSet:
    def test_empty_set(self) -> None:
        s = AuditSet(genius_address=GENIUS, idiot_address=IDIOT)
        assert not s.is_full
        assert not s.all_resolved
        assert not s.ready_for_settlement

    def test_is_full_at_10(self) -> None:
        s = AuditSet(genius_address=GENIUS, idiot_address=IDIOT)
        for i in range(SIGNALS_PER_CYCLE):
            s.signals[f"sig-{i}"] = AuditSignal(signal_id=f"sig-{i}")
        assert s.is_full

    def test_not_full_at_9(self) -> None:
        s = AuditSet(genius_address=GENIUS, idiot_address=IDIOT)
        for i in range(9):
            s.signals[f"sig-{i}"] = AuditSignal(signal_id=f"sig-{i}")
        assert not s.is_full

    def test_all_resolved_when_outcomes_set(self) -> None:
        s = AuditSet(genius_address=GENIUS, idiot_address=IDIOT)
        for i in range(3):
            s.signals[f"sig-{i}"] = AuditSignal(signal_id=f"sig-{i}", outcomes=SAMPLE_OUTCOMES)
        assert s.all_resolved

    def test_not_resolved_when_missing(self) -> None:
        s = AuditSet(genius_address=GENIUS, idiot_address=IDIOT)
        s.signals["sig-0"] = AuditSignal(signal_id="sig-0", outcomes=SAMPLE_OUTCOMES)
        s.signals["sig-1"] = AuditSignal(signal_id="sig-1")  # no outcomes
        assert not s.all_resolved

    def test_not_resolved_when_empty(self) -> None:
        s = AuditSet(genius_address=GENIUS, idiot_address=IDIOT)
        assert not s.all_resolved

    def test_ready_for_settlement(self) -> None:
        s = AuditSet(genius_address=GENIUS, idiot_address=IDIOT)
        for i in range(SIGNALS_PER_CYCLE):
            s.signals[f"sig-{i}"] = AuditSignal(signal_id=f"sig-{i}", outcomes=SAMPLE_OUTCOMES)
        assert s.ready_for_settlement

    def test_not_ready_when_settled(self) -> None:
        s = AuditSet(genius_address=GENIUS, idiot_address=IDIOT, settled=True)
        for i in range(SIGNALS_PER_CYCLE):
            s.signals[f"sig-{i}"] = AuditSignal(signal_id=f"sig-{i}", outcomes=SAMPLE_OUTCOMES)
        assert not s.ready_for_settlement


class TestAuditSetStore:
    def test_add_signal(self) -> None:
        store = AuditSetStore()
        result = store.add_signal(GENIUS, IDIOT, 0, "sig-1")
        assert len(result.signals) == 1
        assert "sig-1" in result.signals

    def test_add_multiple_signals(self) -> None:
        store = AuditSetStore()
        for i in range(5):
            store.add_signal(GENIUS, IDIOT, 0, f"sig-{i}")
        audit_set = store.get_set(GENIUS, IDIOT, 0)
        assert audit_set is not None
        assert len(audit_set.signals) == 5

    def test_add_signal_preserves_economics(self) -> None:
        store = AuditSetStore()
        store.add_signal(GENIUS, IDIOT, 0, "sig-1", notional=100, odds=2_000_000, sla_bps=5000)
        audit_set = store.get_set(GENIUS, IDIOT, 0)
        assert audit_set is not None
        sig = audit_set.signals["sig-1"]
        assert sig.notional == 100
        assert sig.odds == 2_000_000
        assert sig.sla_bps == 5000

    def test_duplicate_signal_ignored(self) -> None:
        store = AuditSetStore()
        store.add_signal(GENIUS, IDIOT, 0, "sig-1")
        store.add_signal(GENIUS, IDIOT, 0, "sig-1")
        audit_set = store.get_set(GENIUS, IDIOT, 0)
        assert audit_set is not None
        assert len(audit_set.signals) == 1

    def test_full_set_rejects_new_signals(self) -> None:
        store = AuditSetStore()
        for i in range(SIGNALS_PER_CYCLE):
            store.add_signal(GENIUS, IDIOT, 0, f"sig-{i}")
        store.add_signal(GENIUS, IDIOT, 0, "sig-extra")
        audit_set = store.get_set(GENIUS, IDIOT, 0)
        assert audit_set is not None
        assert len(audit_set.signals) == SIGNALS_PER_CYCLE
        assert "sig-extra" not in audit_set.signals

    def test_different_cycles_separate(self) -> None:
        store = AuditSetStore()
        store.add_signal(GENIUS, IDIOT, 0, "sig-0")
        store.add_signal(GENIUS, IDIOT, 1, "sig-1")
        assert store.count == 2

    def test_different_pairs_separate(self) -> None:
        idiot2 = "0x" + "cc" * 20
        store = AuditSetStore()
        store.add_signal(GENIUS, IDIOT, 0, "sig-0")
        store.add_signal(GENIUS, idiot2, 0, "sig-1")
        assert store.count == 2

    def test_case_insensitive_keys(self) -> None:
        store = AuditSetStore()
        store.add_signal(GENIUS.upper(), IDIOT.upper(), 0, "sig-0")
        result = store.get_set(GENIUS.lower(), IDIOT.lower(), 0)
        assert result is not None

    def test_record_outcomes(self) -> None:
        store = AuditSetStore()
        store.add_signal(GENIUS, IDIOT, 0, "sig-1")
        success = store.record_outcomes("sig-1", SAMPLE_OUTCOMES)
        assert success is True
        audit_set = store.get_set(GENIUS, IDIOT, 0)
        assert audit_set is not None
        assert audit_set.signals["sig-1"].outcomes == SAMPLE_OUTCOMES

    def test_record_outcomes_unknown_signal(self) -> None:
        store = AuditSetStore()
        success = store.record_outcomes("nonexistent", SAMPLE_OUTCOMES)
        assert success is False

    def test_get_ready_sets(self) -> None:
        store = AuditSetStore()
        # Set 1: full and resolved → ready
        for i in range(SIGNALS_PER_CYCLE):
            store.add_signal(GENIUS, IDIOT, 0, f"sig-{i}")
            store.record_outcomes(f"sig-{i}", SAMPLE_OUTCOMES)
        # Set 2: not full → not ready
        store.add_signal(GENIUS, IDIOT, 1, "sig-next")
        store.record_outcomes("sig-next", SAMPLE_OUTCOMES)

        ready = store.get_ready_sets()
        assert len(ready) == 1
        assert ready[0].cycle == 0

    def test_mark_settled(self) -> None:
        store = AuditSetStore()
        for i in range(SIGNALS_PER_CYCLE):
            store.add_signal(GENIUS, IDIOT, 0, f"sig-{i}")
            store.record_outcomes(f"sig-{i}", SAMPLE_OUTCOMES)
        assert len(store.get_ready_sets()) == 1

        store.mark_settled(GENIUS, IDIOT, 0)
        assert len(store.get_ready_sets()) == 0

    def test_abstain_eviction(self) -> None:
        """v1716: a set abstain'd >= threshold times is excluded from
        get_ready_sets so head-of-queue can advance to settleable pairs."""
        store = AuditSetStore()
        for i in range(SIGNALS_PER_CYCLE):
            store.add_signal(GENIUS, IDIOT, 0, f"sig-{i}")
            store.record_outcomes(f"sig-{i}", SAMPLE_OUTCOMES)
        assert len(store.get_ready_sets()) == 1

        threshold = store._abstain_threshold
        for _ in range(threshold - 1):
            store.mark_abstain(GENIUS, IDIOT, 0)
        assert len(store.get_ready_sets()) == 1, "below threshold still ready"

        store.mark_abstain(GENIUS, IDIOT, 0)
        assert len(store.get_ready_sets()) == 0, "at threshold evicts"

        store.reset_abstain(GENIUS, IDIOT, 0)
        assert len(store.get_ready_sets()) == 1, "reset restores"

    def test_permanent_abstain_survives_reset(self) -> None:
        """v1734: lifetime abstain counter never resets on push gossip, so
        legacy pairs whose data will never arrive eventually evict for good
        instead of ping-ponging back into the queue forever via v1717."""
        store = AuditSetStore()
        store._permanent_abstain_threshold = 3
        for i in range(SIGNALS_PER_CYCLE):
            store.add_signal(GENIUS, IDIOT, 0, f"sig-{i}")
            store.record_outcomes(f"sig-{i}", SAMPLE_OUTCOMES)
        assert len(store.get_ready_sets()) == 1

        for _ in range(2):
            store.mark_abstain(GENIUS, IDIOT, 0)
            store.reset_abstain(GENIUS, IDIOT, 0)
        assert len(store.get_ready_sets()) == 1, "below permanent threshold ready"

        store.mark_abstain(GENIUS, IDIOT, 0)
        store.reset_abstain(GENIUS, IDIOT, 0)
        assert len(store.get_ready_sets()) == 0, (
            "permanent threshold reached, reset_abstain cannot revive"
        )

    def test_protected_signal_ids_includes_unsettled(self) -> None:
        """v1620: protected_signal_ids returns every signal in unsettled
        audit_sets so the outcome attestor's cleanup loop never wipes them.
        """
        store = AuditSetStore()
        for i in range(3):
            store.add_signal(GENIUS, IDIOT, 0, f"sig-{i}")
        protected = store.protected_signal_ids()
        assert protected == {"sig-0", "sig-1", "sig-2"}

    def test_protected_signal_ids_excludes_settled(self) -> None:
        """v1620: once an audit_set is mark_settled-ed, its signals are
        no longer protected and may be cleaned by their natural age."""
        store = AuditSetStore()
        for i in range(3):
            store.add_signal(GENIUS, IDIOT, 0, f"sig-{i}")
        store.mark_settled(GENIUS, IDIOT, 0)
        assert store.protected_signal_ids() == set()

    def test_protected_signal_ids_mixed(self) -> None:
        """v1620: mix of settled and unsettled — only unsettled signals
        appear in protected set."""
        store = AuditSetStore()
        store.add_signal(GENIUS, IDIOT, 0, "sig-settled-0")
        store.add_signal(GENIUS, IDIOT, 0, "sig-settled-1")
        store.mark_settled(GENIUS, IDIOT, 0)

        # Different idiot, same genius, still active
        other_idiot = "0xff" + "00" * 19
        store.add_signal(GENIUS, other_idiot, 0, "sig-active-0")
        store.add_signal(GENIUS, other_idiot, 0, "sig-active-1")

        protected = store.protected_signal_ids()
        assert protected == {"sig-active-0", "sig-active-1"}

    def test_get_set_for_signal(self) -> None:
        store = AuditSetStore()
        store.add_signal(GENIUS, IDIOT, 0, "sig-42")
        result = store.get_set_for_signal("sig-42")
        assert result is not None
        assert result.genius_address == GENIUS

    def test_get_set_for_unknown_signal(self) -> None:
        store = AuditSetStore()
        assert store.get_set_for_signal("nope") is None

    def test_count(self) -> None:
        store = AuditSetStore()
        assert store.count == 0
        store.add_signal(GENIUS, IDIOT, 0, "sig-1")
        assert store.count == 1

    def test_summary_empty(self) -> None:
        store = AuditSetStore()
        s = store.summary()
        assert s == {
            "total": 0,
            "waiting_for_outcomes": 0,
            "ready_for_settlement": 0,
            "permanently_abstained": 0,
            "settled": 0,
            "total_signals": 0,
            "resolved_signals": 0,
        }

    def test_summary_buckets(self) -> None:
        # Two sets: one waiting (incomplete), one settled.
        store = AuditSetStore()
        # Set 1: one signal, not resolved → waiting
        store.add_signal(GENIUS, IDIOT, 0, "sig-a")
        # Set 2: fill to 10, resolve all, then mark settled.
        other_idiot = "0x" + "cc" * 20
        for i in range(SIGNALS_PER_CYCLE):
            store.add_signal(GENIUS, other_idiot, 0, f"sig-b{i}")
            store.record_outcomes(f"sig-b{i}", SAMPLE_OUTCOMES)
        # Before marking settled, this set is ready_for_settlement.
        summary_ready = store.summary()
        assert summary_ready["total"] == 2
        assert summary_ready["waiting_for_outcomes"] == 1
        assert summary_ready["ready_for_settlement"] == 1
        assert summary_ready["settled"] == 0
        assert summary_ready["total_signals"] == 1 + SIGNALS_PER_CYCLE
        assert summary_ready["resolved_signals"] == SIGNALS_PER_CYCLE

        store.mark_settled(GENIUS, other_idiot, 0)
        summary_settled = store.summary()
        assert summary_settled["ready_for_settlement"] == 0
        assert summary_settled["settled"] == 1
        # Waiting set is unchanged.
        assert summary_settled["waiting_for_outcomes"] == 1

    def test_summary_permanently_abstained(self) -> None:
        """v1742: ready_for_settlement sets evicted by the v1716
        permanent-abstain counter are still counted in
        ready_for_settlement (they have the flag set) but are also
        surfaced as a subset under permanently_abstained so operators
        can see how many sets are actually eligible for the settle path.
        """
        store = AuditSetStore()
        store._permanent_abstain_threshold = 3
        for i in range(SIGNALS_PER_CYCLE):
            store.add_signal(GENIUS, IDIOT, 0, f"sig-pa{i}")
            store.record_outcomes(f"sig-pa{i}", SAMPLE_OUTCOMES)

        s = store.summary()
        assert s["ready_for_settlement"] == 1
        assert s["permanently_abstained"] == 0

        for _ in range(3):
            store.mark_abstain(GENIUS, IDIOT, 0)

        s = store.summary()
        assert s["ready_for_settlement"] == 1, (
            "permanent_abstain doesn't change the underlying ready flag"
        )
        assert s["permanently_abstained"] == 1
        assert len(store.get_ready_sets()) == 0, (
            "but get_ready_sets filters it out (settle-eligible bucket)"
        )

    def test_signal_rejects_second_set_binding(self) -> None:
        """Codex-audit regression: same signal_id added to a second
        (genius, idiot, cycle) must NOT be double-counted.
        """
        store = AuditSetStore()
        store.add_signal(GENIUS, IDIOT, 0, "sig-shared")
        # Re-add same signal_id under a different cycle — should be
        # rejected (returns the existing set, not the attempted one).
        result = store.add_signal(GENIUS, IDIOT, 99, "sig-shared")
        assert result.cycle == 0  # we got the original back
        assert store.count == 1
        assert store.summary()["total_signals"] == 1  # not 2

    def test_version_change_migrates_existing_sets(self) -> None:
        """Codex-audit regression: when contract_version flips from v1 to
        v2 post-bootstrap, sets created before the flip must upgrade
        (otherwise they stay on v1 ready_for_settlement rules forever).
        """
        store = AuditSetStore(contract_version=1)
        store.add_signal(GENIUS, IDIOT, 0, "early-sig")
        early = store.get_set(GENIUS, IDIOT, 0)
        assert early is not None and early.version == 1

        store.contract_version = 2

        # Existing set's version moved with the store
        assert store.get_set(GENIUS, IDIOT, 0).version == 2
        # New set also gets v2
        store.add_signal(GENIUS, IDIOT, 1, "late-sig")
        assert store.get_set(GENIUS, IDIOT, 1).version == 2
