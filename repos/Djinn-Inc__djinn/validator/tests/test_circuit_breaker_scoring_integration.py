"""Integration tests: consensus circuit breaker tied into MinerScorer.

These tests verify that flagged miners are forced to weight 0 in the
scoring loop when DJINN_FF_CIRCUIT_BREAKER is on, and that the OFF
state is identical to the existing scoring behavior. The tracker
primitive itself is tested in test_consensus_circuit_breaker.py;
this file tests the wire-up.
"""

from __future__ import annotations

import importlib
import os

import pytest

from djinn_validator.core.circuit_breaker import ConsensusCircuitBreaker
from djinn_validator.core.scoring import MinerMetrics, MinerScorer


@pytest.fixture
def fresh_flags(monkeypatch):
    for key in list(os.environ.keys()):
        if key.startswith("DJINN_FF_"):
            monkeypatch.delenv(key, raising=False)

    def _reload(**flags: bool):
        for k, v in flags.items():
            monkeypatch.setenv(k, "true" if v else "false")
        from djinn_validator import feature_flags

        importlib.reload(feature_flags)
        return feature_flags

    yield _reload

    # Teardown: restore the feature_flags module to its all-OFF state so
    # this test's reloaded `flags` singleton does not leak into other
    # test files via the module-level cache. monkeypatch already cleans
    # up env vars, but it doesn't undo `importlib.reload` side effects
    # on the singleton.
    for key in list(os.environ.keys()):
        if key.startswith("DJINN_FF_"):
            monkeypatch.delenv(key, raising=False)
    from djinn_validator import feature_flags as _ff

    importlib.reload(_ff)


def _scorer_with_breaker(*, fresh_flags_factory, flag_on: bool) -> tuple[MinerScorer, ConsensusCircuitBreaker]:
    fresh_flags_factory(DJINN_FF_CIRCUIT_BREAKER=flag_on)
    cb = ConsensusCircuitBreaker(tolerance=0.005, flag_threshold=5.0)
    scorer = MinerScorer(circuit_breaker=cb)
    return scorer, cb


def _make_active_miner(uid: int, hotkey: str) -> MinerMetrics:
    """A miner with enough activity to score above zero (so we can tell
    when the circuit breaker zeros it)."""
    m = MinerMetrics(uid=uid, hotkey=hotkey, first_seen_at=1.0)  # legacy-equivalent
    m.queries_total = 600
    m.queries_correct = 570
    m.lifetime_queries = 600
    m.attestations_total = 200
    m.attestations_valid = 200
    m.lifetime_attestations = 200
    m.ema_uptime = 0.9
    m.proactive_proof_verified = True
    return m


# ----------------------------------------------------------------------
# Flag OFF: identical to existing behavior
# ----------------------------------------------------------------------


def test_flag_off_does_not_zero_flagged_miner(fresh_flags):
    scorer, cb = _scorer_with_breaker(fresh_flags_factory=fresh_flags, flag_on=False)
    miner = _make_active_miner(uid=1, hotkey="5Aa")
    scorer._miners[1] = miner
    for i in range(200):
        cb.record_observation(hotkey="5Aa", deviation=0.05, query_id=f"q{i}")
    assert cb.is_flagged("5Aa")

    weights, _ = scorer.compute_weights_detailed(is_active_epoch=True)
    assert weights.get(1, 0.0) > 0.0


def test_flag_off_with_no_breaker_attached_works():
    scorer = MinerScorer()
    miner = _make_active_miner(uid=1, hotkey="5Aa")
    scorer._miners[1] = miner
    weights, _ = scorer.compute_weights_detailed(is_active_epoch=True)
    assert weights.get(1, 0.0) > 0.0


# ----------------------------------------------------------------------
# Flag ON: flagged miners get zero weight
# ----------------------------------------------------------------------


def test_flag_on_zeros_flagged_miner(fresh_flags):
    scorer, cb = _scorer_with_breaker(fresh_flags_factory=fresh_flags, flag_on=True)
    bad = _make_active_miner(uid=1, hotkey="5BadKey")
    good = _make_active_miner(uid=2, hotkey="5GoodKey")
    scorer._miners[1] = bad
    scorer._miners[2] = good

    for i in range(200):
        cb.record_observation(hotkey="5BadKey", deviation=0.05, query_id=f"q{i}")
    assert cb.is_flagged("5BadKey")
    assert not cb.is_flagged("5GoodKey")

    weights, _ = scorer.compute_weights_detailed(is_active_epoch=True)
    assert weights.get(1, 0.0) == 0.0
    assert weights.get(2, 0.0) > 0.0
    # The good miner should take the entire normalized weight since the
    # bad miner is the only other one in the pool.
    assert weights.get(2, 0.0) == pytest.approx(1.0, abs=1e-6)


def test_flag_on_with_no_breaker_falls_back_safely(fresh_flags):
    fresh_flags(DJINN_FF_CIRCUIT_BREAKER=True)
    scorer = MinerScorer()  # no breaker attached
    miner = _make_active_miner(uid=1, hotkey="5Aa")
    scorer._miners[1] = miner
    weights, _ = scorer.compute_weights_detailed(is_active_epoch=True)
    assert weights.get(1, 0.0) > 0.0


def test_flag_on_unflagged_miner_unaffected(fresh_flags):
    scorer, cb = _scorer_with_breaker(fresh_flags_factory=fresh_flags, flag_on=True)
    miner = _make_active_miner(uid=1, hotkey="5Aa")
    scorer._miners[1] = miner
    cb.get_or_create("5Aa")
    assert not cb.is_flagged("5Aa")

    weights, _ = scorer.compute_weights_detailed(is_active_epoch=True)
    assert weights.get(1, 0.0) > 0.0


def test_clear_flag_restores_weight(fresh_flags):
    scorer, cb = _scorer_with_breaker(fresh_flags_factory=fresh_flags, flag_on=True)
    miner = _make_active_miner(uid=1, hotkey="5Aa")
    other = _make_active_miner(uid=2, hotkey="5Bb")
    scorer._miners[1] = miner
    scorer._miners[2] = other

    for i in range(200):
        cb.record_observation(hotkey="5Aa", deviation=0.05, query_id=f"q{i}")
    weights_during_flag, _ = scorer.compute_weights_detailed(is_active_epoch=True)
    assert weights_during_flag.get(1, 0.0) == 0.0

    cb.clear_flag("5Aa", reason="appeal_succeeded", reset_score=True)
    weights_after_clear, _ = scorer.compute_weights_detailed(is_active_epoch=True)
    assert weights_after_clear.get(1, 0.0) > 0.0


# ----------------------------------------------------------------------
# record_consensus_observation pass-through
# ----------------------------------------------------------------------


def test_record_consensus_observation_feeds_breaker(fresh_flags):
    scorer, cb = _scorer_with_breaker(fresh_flags_factory=fresh_flags, flag_on=True)
    for i in range(200):
        scorer.record_consensus_observation(hotkey="5Aa", deviation=0.05, query_id=f"q{i}")
    assert cb.is_flagged("5Aa")


def test_record_consensus_observation_no_op_without_breaker():
    scorer = MinerScorer()  # no breaker
    # Should not raise
    scorer.record_consensus_observation(hotkey="5Aa", deviation=0.05)


def test_record_consensus_observation_no_op_for_empty_hotkey():
    cb = ConsensusCircuitBreaker(tolerance=0.005, flag_threshold=5.0)
    scorer = MinerScorer(circuit_breaker=cb)
    scorer.record_consensus_observation(hotkey="", deviation=0.05)
    assert cb.get_state("") is None


def test_record_consensus_observation_swallows_breaker_errors():
    """A bad observation must not blow up the scoring loop."""
    cb = ConsensusCircuitBreaker(tolerance=0.005, flag_threshold=5.0)
    scorer = MinerScorer(circuit_breaker=cb)
    scorer.record_consensus_observation(hotkey="5Aa", deviation=float("nan"), query_id="q1")
    state = cb.get_state("5Aa")
    assert state is None or state.score == 0.0


# ----------------------------------------------------------------------
# Multiple miners, mixed flagged states
# ----------------------------------------------------------------------


def test_record_query_feeds_breaker_via_metrics(fresh_flags):
    """When the breaker is wired into MinerScorer, the per-miner
    record_query path automatically pushes a CUSUM observation. This
    is the production hook: the validator's challenge loop already
    calls record_query for every sports query, so by attaching the
    breaker once at construction time, observations flow without
    every call site needing to know about the breaker."""
    fresh_flags(DJINN_FF_CIRCUIT_BREAKER=True)
    cb = ConsensusCircuitBreaker(tolerance=0.005, flag_threshold=5.0)
    scorer = MinerScorer(circuit_breaker=cb)
    miner = scorer.get_or_create(uid=1, hotkey="5LiarKey")
    # Record many wrong answers — should accumulate CUSUM and flag.
    for i in range(200):
        miner.record_query(correct=False, latency=0.1, proof_submitted=True, query_id=f"q{i}")
    assert cb.is_flagged("5LiarKey")
    state = cb.get_state("5LiarKey")
    assert state is not None
    assert state.sample_count == 200


def test_record_query_correct_does_not_flag(fresh_flags):
    fresh_flags(DJINN_FF_CIRCUIT_BREAKER=True)
    cb = ConsensusCircuitBreaker(tolerance=0.005, flag_threshold=5.0)
    scorer = MinerScorer(circuit_breaker=cb)
    miner = scorer.get_or_create(uid=1, hotkey="5HonestKey")
    for i in range(500):
        miner.record_query(correct=True, latency=0.1, proof_submitted=True, query_id=f"q{i}")
    assert not cb.is_flagged("5HonestKey")


def test_record_query_with_no_breaker_attached_does_not_raise():
    scorer = MinerScorer()  # no breaker
    miner = scorer.get_or_create(uid=1, hotkey="5Aa")
    # Should not raise even though there's nothing to feed
    miner.record_query(correct=False, latency=0.1, proof_submitted=True)
    assert miner.queries_total == 1


def test_record_attestation_feeds_breaker(fresh_flags):
    """Attestation challenge failures also push CUSUM observations to
    the breaker. Verifies the second observation feed point (the first
    being record_query) is wired correctly."""
    fresh_flags(DJINN_FF_CIRCUIT_BREAKER=True)
    cb = ConsensusCircuitBreaker(tolerance=0.005, flag_threshold=5.0)
    scorer = MinerScorer(circuit_breaker=cb)
    miner = scorer.get_or_create(uid=1, hotkey="5BadAttestKey")
    for _ in range(200):
        miner.record_attestation(latency=0.5, proof_valid=False)
    assert cb.is_flagged("5BadAttestKey")
    state = cb.get_state("5BadAttestKey")
    assert state is not None
    assert state.sample_count == 200


def test_record_attestation_validator_timeout_does_not_feed_breaker(fresh_flags):
    """Validator-side timeouts are not the miner's fault and must NOT
    count against the miner's CUSUM score, otherwise validators with
    flaky verifiers would slash honest miners."""
    fresh_flags(DJINN_FF_CIRCUIT_BREAKER=True)
    cb = ConsensusCircuitBreaker(tolerance=0.005, flag_threshold=5.0)
    scorer = MinerScorer(circuit_breaker=cb)
    miner = scorer.get_or_create(uid=1, hotkey="5VictimKey")
    for _ in range(500):
        miner.record_attestation(latency=0.5, proof_valid=False, validator_timeout=True)
    # No observations fed → no CUSUM accumulation → not flagged
    assert not cb.is_flagged("5VictimKey")
    state = cb.get_state("5VictimKey")
    # The state may or may not exist depending on whether get_or_create
    # was called as a side effect; either way it must have score 0.
    if state is not None:
        assert state.score == 0.0


def test_record_attestation_valid_does_not_flag(fresh_flags):
    fresh_flags(DJINN_FF_CIRCUIT_BREAKER=True)
    cb = ConsensusCircuitBreaker(tolerance=0.005, flag_threshold=5.0)
    scorer = MinerScorer(circuit_breaker=cb)
    miner = scorer.get_or_create(uid=1, hotkey="5GoodAttestKey")
    for _ in range(500):
        miner.record_attestation(latency=0.5, proof_valid=True)
    assert not cb.is_flagged("5GoodAttestKey")


def test_multiple_miners_mixed_states(fresh_flags):
    scorer, cb = _scorer_with_breaker(fresh_flags_factory=fresh_flags, flag_on=True)
    miners = [_make_active_miner(uid=i, hotkey=f"5miner{i}") for i in range(5)]
    for m in miners:
        scorer._miners[m.uid] = m

    # Flag two of the five
    for i in range(200):
        cb.record_observation(hotkey="5miner0", deviation=0.05, query_id=f"q{i}")
        cb.record_observation(hotkey="5miner3", deviation=0.05, query_id=f"q{i}")

    weights, _ = scorer.compute_weights_detailed(is_active_epoch=True)

    assert weights.get(0, 0.0) == 0.0
    assert weights.get(3, 0.0) == 0.0
    # The remaining three should split the entire weight
    remaining_total = sum(weights.get(i, 0.0) for i in [1, 2, 4])
    assert remaining_total == pytest.approx(1.0, abs=1e-6)
    assert all(weights.get(i, 0.0) > 0 for i in [1, 2, 4])
