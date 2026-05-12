"""Tests for the consensus circuit breaker (CUSUM tracker primitive).

Distinct from test_circuit_breaker.py, which tests the per-peer
retry/timeout circuit breaker used by the chain client and MPC
orchestrator. This file tests the consensus tracker that scores
miners on their agreement with consensus over time.

These tests verify the seven invariants from
project_consensus_circuit_breaker.md, especially:

- I2 (CUSUM correctness): honest miners do not flag, biased miners do
- I3 (detection time bound): bias of magnitude δ is flagged in O(1/δ²)
  observations
- I4 (false positive rate bound): honest steady-state flag rate is small
- I5 (hotkey-keyed scoring): scoring is by hotkey, not UID slot
- I6 (forward-only): clear_flag never edits historical state outside
  the live tracker; settlements are not touched here

The slash mechanics and the appeal endpoint are tested separately when
they land. This file covers the tracker primitive only.
"""

from __future__ import annotations

import random

import pytest

from djinn_validator.core.circuit_breaker import (
    ConsensusCircuitBreaker,
    CusumState,
)


# ----------------------------------------------------------------------
# CusumState dataclass
# ----------------------------------------------------------------------


def test_cusum_state_round_trip():
    state = CusumState(hotkey="5Aa", score=2.5, sample_count=100, last_updated_at=1234.0)
    state.last_disputes = [("q1", 0.01), ("q2", 0.02)]
    d = state.to_dict()
    restored = CusumState.from_dict(d)
    assert restored.hotkey == "5Aa"
    assert restored.score == 2.5
    assert restored.sample_count == 100
    assert restored.last_updated_at == 1234.0
    assert restored.last_disputes == [("q1", 0.01), ("q2", 0.02)]
    assert not restored.is_flagged()


def test_cusum_state_dispute_buffer_caps():
    state = CusumState(hotkey="5Aa")
    for i in range(50):
        state.last_disputes.append((f"q{i}", float(i)))
    d = state.to_dict()
    assert len(d["last_disputes"]) == CusumState.MAX_RECENT_DISPUTES


# ----------------------------------------------------------------------
# Construction validation
# ----------------------------------------------------------------------


def test_rejects_negative_tolerance():
    with pytest.raises(ValueError):
        ConsensusCircuitBreaker(tolerance=-0.1)


def test_rejects_zero_threshold():
    with pytest.raises(ValueError):
        ConsensusCircuitBreaker(flag_threshold=0)


def test_rejects_zero_decay():
    with pytest.raises(ValueError):
        ConsensusCircuitBreaker(decay_per_observation=0)


def test_rejects_decay_above_one():
    with pytest.raises(ValueError):
        ConsensusCircuitBreaker(decay_per_observation=1.1)


# ----------------------------------------------------------------------
# Honest steady state (Invariant I4: low false positive rate)
# ----------------------------------------------------------------------


def test_honest_miner_with_no_deviation_never_flags():
    cb = ConsensusCircuitBreaker(tolerance=0.005, flag_threshold=5.0)
    for i in range(10_000):
        cb.record_observation(hotkey="5Aa", deviation=0.0, query_id=f"q{i}")
    assert not cb.is_flagged("5Aa")
    assert cb.get_score("5Aa") == 0.0


def test_honest_miner_with_normal_jitter_never_flags():
    cb = ConsensusCircuitBreaker(tolerance=0.005, flag_threshold=5.0)
    rng = random.Random(42)
    for i in range(10_000):
        deviation = rng.uniform(0, 0.005)
        cb.record_observation(hotkey="5Aa", deviation=deviation, query_id=f"q{i}")
    assert not cb.is_flagged("5Aa")
    assert cb.get_score("5Aa") == pytest.approx(0.0, abs=1e-9)


def test_honest_miner_with_occasional_outliers_does_not_flag_quickly():
    cb = ConsensusCircuitBreaker(tolerance=0.005, flag_threshold=5.0, decay_per_observation=0.999)
    rng = random.Random(123)
    for i in range(2000):
        if rng.random() < 0.05:
            deviation = rng.uniform(0.01, 0.03)
        else:
            deviation = rng.uniform(0, 0.005)
        cb.record_observation(hotkey="5Aa", deviation=deviation, query_id=f"q{i}")
    assert not cb.is_flagged("5Aa")


# ----------------------------------------------------------------------
# Sustained bias detection (Invariant I3)
# ----------------------------------------------------------------------


def test_large_bias_caught_quickly():
    cb = ConsensusCircuitBreaker(tolerance=0.005, flag_threshold=5.0, decay_per_observation=0.999)
    flagged_at = None
    for i in range(500):
        state = cb.record_observation(hotkey="5Aa", deviation=0.05, query_id=f"q{i}")
        if state.is_flagged() and flagged_at is None:
            flagged_at = i
            break
    assert flagged_at is not None
    assert flagged_at < 200, f"expected ~150 observations, got {flagged_at}"


def test_small_bias_eventually_caught():
    cb = ConsensusCircuitBreaker(tolerance=0.005, flag_threshold=5.0, decay_per_observation=0.999)
    flagged_at = None
    for i in range(2000):
        state = cb.record_observation(hotkey="5Aa", deviation=0.015, query_id=f"q{i}")
        if state.is_flagged():
            flagged_at = i
            break
    assert flagged_at is not None
    assert flagged_at < 1000


def test_tiny_bias_caught_eventually_or_capped_by_decay():
    cb = ConsensusCircuitBreaker(tolerance=0.005, flag_threshold=5.0, decay_per_observation=0.999)
    for i in range(10_000):
        cb.record_observation(hotkey="5Aa", deviation=0.006, query_id=f"q{i}")
    assert not cb.is_flagged("5Aa")
    assert cb.get_score("5Aa") < 5.0


# ----------------------------------------------------------------------
# Oscillation handling
# ----------------------------------------------------------------------


def test_oscillating_attacker_caught():
    cb = ConsensusCircuitBreaker(tolerance=0.005, flag_threshold=5.0)
    flagged_at = None
    for i in range(500):
        sign = 1 if i % 2 == 0 else -1
        state = cb.record_observation(hotkey="5Aa", deviation=sign * 0.05, query_id=f"q{i}")
        if state.is_flagged():
            flagged_at = i
            break
    assert flagged_at is not None
    assert flagged_at < 200


# ----------------------------------------------------------------------
# Hotkey-keyed scoring (Invariant I5)
# ----------------------------------------------------------------------


def test_different_hotkeys_score_independently():
    cb = ConsensusCircuitBreaker(tolerance=0.005, flag_threshold=5.0)
    for i in range(200):
        cb.record_observation(hotkey="5Aa", deviation=0.05, query_id=f"q{i}")
    cb.record_observation(hotkey="5Bb", deviation=0.0, query_id="q0")
    assert cb.is_flagged("5Aa")
    assert not cb.is_flagged("5Bb")


def test_different_hotkeys_in_same_uid_do_not_inherit_score():
    cb = ConsensusCircuitBreaker(tolerance=0.005, flag_threshold=5.0)
    for i in range(200):
        cb.record_observation(hotkey="5old", deviation=0.05, query_id=f"q{i}")
    assert cb.is_flagged("5old")

    state = cb.get_or_create("5new")
    assert state.score == 0.0
    assert not state.is_flagged()


# ----------------------------------------------------------------------
# Flag clearing (appeal success / slash apply)
# ----------------------------------------------------------------------


def test_clear_flag_with_reset_restores_score():
    cb = ConsensusCircuitBreaker(tolerance=0.005, flag_threshold=5.0)
    for i in range(200):
        cb.record_observation(hotkey="5Aa", deviation=0.05, query_id=f"q{i}")
    assert cb.is_flagged("5Aa")
    assert cb.clear_flag("5Aa", reason="appeal_succeeded", reset_score=True)
    assert not cb.is_flagged("5Aa")
    assert cb.get_score("5Aa") == 0.0


def test_clear_flag_without_reset_leaves_score_high():
    cb = ConsensusCircuitBreaker(tolerance=0.005, flag_threshold=5.0)
    for i in range(200):
        cb.record_observation(hotkey="5Aa", deviation=0.05, query_id=f"q{i}")
    assert cb.is_flagged("5Aa")
    high_score = cb.get_score("5Aa")
    assert cb.clear_flag("5Aa", reason="slash_applied", reset_score=False)
    assert not cb.is_flagged("5Aa")
    assert cb.get_score("5Aa") == high_score


def test_clear_flag_returns_false_when_not_flagged():
    cb = ConsensusCircuitBreaker(tolerance=0.005, flag_threshold=5.0)
    assert not cb.clear_flag("5NeverExisted")
    cb.get_or_create("5Aa")
    assert not cb.clear_flag("5Aa")


# ----------------------------------------------------------------------
# Dispute buffer for appeals
# ----------------------------------------------------------------------


def test_recent_disputes_recorded():
    cb = ConsensusCircuitBreaker(tolerance=0.005, flag_threshold=5.0)
    for i in range(5):
        cb.record_observation(hotkey="5Aa", deviation=0.05, query_id=f"q{i}")
    state = cb.get_state("5Aa")
    assert state is not None
    assert len(state.last_disputes) == 5
    assert state.last_disputes[0] == ("q0", 0.05)


def test_recent_disputes_capped():
    cb = ConsensusCircuitBreaker(tolerance=0.005, flag_threshold=5.0)
    for i in range(50):
        cb.record_observation(hotkey="5Aa", deviation=0.05, query_id=f"q{i}")
    state = cb.get_state("5Aa")
    assert state is not None
    assert len(state.last_disputes) == CusumState.MAX_RECENT_DISPUTES


def test_record_without_query_id_does_not_pollute_buffer():
    cb = ConsensusCircuitBreaker(tolerance=0.005, flag_threshold=5.0)
    for _ in range(10):
        cb.record_observation(hotkey="5Aa", deviation=0.05)
    state = cb.get_state("5Aa")
    assert state is not None
    assert state.last_disputes == []


# ----------------------------------------------------------------------
# Validation errors
# ----------------------------------------------------------------------


def test_record_requires_hotkey():
    cb = ConsensusCircuitBreaker()
    with pytest.raises(ValueError, match="hotkey"):
        cb.record_observation(hotkey="", deviation=0.01)


def test_record_rejects_nan_deviation():
    cb = ConsensusCircuitBreaker()
    with pytest.raises(ValueError):
        cb.record_observation(hotkey="5Aa", deviation=float("nan"))


def test_record_rejects_inf_deviation():
    cb = ConsensusCircuitBreaker()
    with pytest.raises(ValueError):
        cb.record_observation(hotkey="5Aa", deviation=float("inf"))


# ----------------------------------------------------------------------
# Persistence round-trip
# ----------------------------------------------------------------------


def test_persistence_round_trip(tmp_path):
    db = tmp_path / "cusum.db"
    cb1 = ConsensusCircuitBreaker(db_path=str(db))
    for i in range(200):
        cb1.record_observation(hotkey="5Aa", deviation=0.05, query_id=f"q{i}")
    assert cb1.is_flagged("5Aa")

    cb2 = ConsensusCircuitBreaker(db_path=str(db))
    state = cb2.get_state("5Aa")
    assert state is not None
    assert state.is_flagged()
    assert state.score >= 5.0
    assert state.sample_count == 200


def test_remove_clears_persistence(tmp_path):
    db = tmp_path / "cusum.db"
    cb1 = ConsensusCircuitBreaker(db_path=str(db))
    cb1.record_observation(hotkey="5Aa", deviation=0.05, query_id="q1")
    assert cb1.remove("5Aa")
    cb2 = ConsensusCircuitBreaker(db_path=str(db))
    assert cb2.get_state("5Aa") is None


def test_clear_flag_persists(tmp_path):
    db = tmp_path / "cusum.db"
    cb1 = ConsensusCircuitBreaker(db_path=str(db))
    for i in range(200):
        cb1.record_observation(hotkey="5Aa", deviation=0.05, query_id=f"q{i}")
    cb1.clear_flag("5Aa", reason="test", reset_score=True)
    cb2 = ConsensusCircuitBreaker(db_path=str(db))
    state = cb2.get_state("5Aa")
    assert state is not None
    assert not state.is_flagged()
    assert state.score == 0.0


# ----------------------------------------------------------------------
# Iteration helpers
# ----------------------------------------------------------------------


def test_all_flagged_returns_only_flagged():
    cb = ConsensusCircuitBreaker(tolerance=0.005, flag_threshold=5.0)
    for i in range(200):
        cb.record_observation(hotkey="5Bad", deviation=0.05, query_id=f"q{i}")
    cb.record_observation(hotkey="5Good", deviation=0.0)
    flagged = list(cb.all_flagged())
    assert len(flagged) == 1
    assert flagged[0].hotkey == "5Bad"


def test_all_states_returns_everyone():
    cb = ConsensusCircuitBreaker(tolerance=0.005, flag_threshold=5.0)
    cb.get_or_create("5Aa")
    cb.get_or_create("5Bb")
    cb.get_or_create("5Cc")
    states = list(cb.all_states())
    assert len(states) == 3


# ----------------------------------------------------------------------
# Statistical: false positive rate at scale
# ----------------------------------------------------------------------


def test_concurrent_record_observations_under_load(tmp_path):
    """Stress test: 4 threads each pushing 200 observations across 5
    distinct hotkeys, all sharing one SQLite-backed breaker. Verifies
    the _db_lock prevents 'database is locked' errors and that all
    observations land cleanly. Without the write lock, this would
    intermittently fail under WAL contention.
    """
    import threading

    db = tmp_path / "stress.db"
    cb = ConsensusCircuitBreaker(db_path=str(db), tolerance=0.005, flag_threshold=5.0)

    errors: list[str] = []

    def worker(idx: int) -> None:
        try:
            for i in range(200):
                hotkey = f"5miner{(idx * 200 + i) % 5}"
                cb.record_observation(
                    hotkey=hotkey,
                    deviation=0.05,
                    query_id=f"t{idx}_q{i}",
                )
        except Exception as e:
            errors.append(str(e))

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert errors == []
    # 4 threads * 200 observations = 800 total, distributed evenly
    # across 5 hotkeys via (idx*200 + i) % 5 → 160 observations per hotkey.
    total_samples = sum(cb.get_sample_count(f"5miner{i}") for i in range(5))
    assert total_samples == 800
    for i in range(5):
        state = cb.get_state(f"5miner{i}")
        assert state is not None
        assert state.sample_count == 160

    # Round-trip via persistence
    cb2 = ConsensusCircuitBreaker(db_path=str(db))
    for i in range(5):
        state = cb2.get_state(f"5miner{i}")
        assert state is not None
        assert state.sample_count == 160


def test_false_positive_rate_at_scale():
    """200 simulated honest miners, 1000 observations each of normal-
    jitter behavior. Verify the false positive rate is well below 1%."""
    cb = ConsensusCircuitBreaker(tolerance=0.005, flag_threshold=5.0)
    rng = random.Random(7)
    for miner_idx in range(200):
        hotkey = f"5miner{miner_idx}"
        for q in range(1000):
            deviation = abs(rng.gauss(0, 0.002))
            cb.record_observation(hotkey=hotkey, deviation=deviation, query_id=f"q{q}")
    flagged = list(cb.all_flagged())
    assert len(flagged) == 0, f"expected 0 false positives, got {len(flagged)}"
