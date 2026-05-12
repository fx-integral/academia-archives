"""Phase A1.9 — audit_set_store persistence across restarts.

Closes the 30-min post-restart degraded window. Without persistence,
audit_set_store wipes on every validator restart and outcomes can't
be bridged from gossip until chain bootstrap completes (~30 min).
With persistence, restart resumes from SQLite immediately.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from djinn_validator.core.audit_set import AuditSetStore
from djinn_validator.core.outcomes import Outcome


GENIUS = "0x68fc8eeC9E5551d4c93a89b6d861f0a05e0A2A1d"
IDIOT_A = "0x3B1519A265d865FA9b78E337B6bbB30c8Ad843DA"
IDIOT_B = "0x4939D0B0c5bC04439679A4eDA12B32d2c7Bcc170"


class TestAuditSetPersistence:
    def test_signals_survive_reopen(self, tmp_path: Path):
        db = tmp_path / "audit.db"
        store = AuditSetStore(db_path=str(db))
        store.add_signal(GENIUS, IDIOT_A, 0, "sig1", purchase_id=100, notional=50)
        store.add_signal(GENIUS, IDIOT_A, 0, "sig2", purchase_id=101, notional=60)
        store.add_signal(GENIUS, IDIOT_B, 0, "sig3", purchase_id=200)
        del store

        # Reopen — same DB, fresh in-memory state, should load 3 signals + 2 sets
        store2 = AuditSetStore(db_path=str(db))
        assert store2.count == 2
        assert store2.get_pair_for_signal("sig1") == (GENIUS.lower(), IDIOT_A.lower(), 0)
        assert store2.get_pair_for_signal("sig2") == (GENIUS.lower(), IDIOT_A.lower(), 0)
        assert store2.get_pair_for_signal("sig3") == (GENIUS.lower(), IDIOT_B.lower(), 0)
        assert store2.get_purchase_id_for_signal("sig1") == 100
        assert store2.get_purchase_id_for_signal("sig2") == 101
        assert store2.get_purchase_id_for_signal("sig3") == 200

    def test_outcomes_survive_reopen(self, tmp_path: Path):
        db = tmp_path / "audit.db"
        store = AuditSetStore(db_path=str(db))
        store.add_signal(GENIUS, IDIOT_A, 0, "sig1", purchase_id=100)
        outcomes = [
            Outcome.FAVORABLE,
            Outcome.UNFAVORABLE,
            Outcome.VOID,
            Outcome.FAVORABLE,
            Outcome.PENDING,
            Outcome.UNFAVORABLE,
            Outcome.FAVORABLE,
            Outcome.VOID,
            Outcome.FAVORABLE,
            Outcome.UNFAVORABLE,
        ]
        assert store.record_outcomes("sig1", outcomes) is True
        del store

        # Reopen — outcomes should be present
        store2 = AuditSetStore(db_path=str(db))
        audit_set = store2.get_set(GENIUS, IDIOT_A, 0)
        assert audit_set is not None
        sig = audit_set.signals["sig1"]
        assert sig.outcomes == outcomes

    def test_settled_flag_survives_reopen(self, tmp_path: Path):
        db = tmp_path / "audit.db"
        store = AuditSetStore(db_path=str(db))
        store.add_signal(GENIUS, IDIOT_A, 0, "sig1")
        store.mark_settled(GENIUS, IDIOT_A, 0)
        del store

        store2 = AuditSetStore(db_path=str(db))
        audit_set = store2.get_set(GENIUS, IDIOT_A, 0)
        assert audit_set is not None
        assert audit_set.settled is True

    def test_idempotent_add_signal_persists_once(self, tmp_path: Path):
        db = tmp_path / "audit.db"
        store = AuditSetStore(db_path=str(db))
        store.add_signal(GENIUS, IDIOT_A, 0, "sig1", purchase_id=100)
        # Re-add same signal — should be a no-op (returns existing set)
        store.add_signal(GENIUS, IDIOT_A, 0, "sig1", purchase_id=100)
        del store

        store2 = AuditSetStore(db_path=str(db))
        assert store2.count == 1
        audit_set = store2.get_set(GENIUS, IDIOT_A, 0)
        assert len(audit_set.signals) == 1

    def test_summary_after_reopen_matches_pre_close(self, tmp_path: Path):
        db = tmp_path / "audit.db"
        store = AuditSetStore(db_path=str(db))
        # 12 signals across 2 sets, resolve 8 of them
        for i in range(10):
            store.add_signal(GENIUS, IDIOT_A, 0, f"sig_a_{i}", purchase_id=i)
        for i in range(10, 12):
            store.add_signal(GENIUS, IDIOT_B, 0, f"sig_b_{i}", purchase_id=i)
        outcomes = [Outcome.FAVORABLE] * 10
        for i in range(8):
            assert store.record_outcomes(f"sig_a_{i}", outcomes) is True
        pre_summary = store.summary()
        del store

        store2 = AuditSetStore(db_path=str(db))
        post_summary = store2.summary()
        assert pre_summary == post_summary, (
            f"summary differs across reopen — pre={pre_summary} post={post_summary}"
        )

    def test_no_db_path_works_in_memory_only(self, tmp_path: Path):
        """Backwards compatibility: existing tests that don't pass db_path
        should still work — in-memory only, no persistence."""
        store = AuditSetStore()  # no db_path
        store.add_signal(GENIUS, IDIOT_A, 0, "sig1", purchase_id=100)
        assert store.count == 1
        # No SQLite file created anywhere
        assert not any(tmp_path.glob("*.db"))

    def test_record_outcomes_for_unknown_signal_no_persist(self, tmp_path: Path):
        """Calling record_outcomes for an unregistered signal should NOT
        create an orphaned row in audit_signals."""
        db = tmp_path / "audit.db"
        store = AuditSetStore(db_path=str(db))
        result = store.record_outcomes("never_registered", [Outcome.FAVORABLE] * 10)
        assert result is False
        del store

        store2 = AuditSetStore(db_path=str(db))
        assert store2.get_pair_for_signal("never_registered") is None
        assert store2.count == 0
