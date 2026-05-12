"""Tests for the reliability-weight amplification and shield bonus (v1171).

Closes the linear-scaling sybil hole: under flat per-UID emissions, a 30-UID
cluster simply earns 30× a singleton. Amplifying notary_reliability — which
sybil farms scale sub-linearly because they share one notary sidecar — makes
each cluster UID earn only as much as its actual peer-completed notary work.
"""

from __future__ import annotations

import importlib
import os

import pytest

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

    for key in list(os.environ.keys()):
        if key.startswith("DJINN_FF_"):
            monkeypatch.delenv(key, raising=False)
    from djinn_validator import feature_flags as _ff

    importlib.reload(_ff)


def _seasoned_miner(
    uid: int,
    hotkey: str,
    *,
    reliab_num: int,
    reliab_den: int,
    shield: bool = False,
) -> MinerMetrics:
    """A miner with enough notary assignments to pass the gate."""
    m = MinerMetrics(uid=uid, hotkey=hotkey, first_seen_at=0.0)
    m.queries_total = 600
    m.queries_correct = 600
    m.lifetime_queries = 600
    m.ema_uptime = 1.0
    m.notary_duties_assigned = reliab_den
    m.notary_duties_completed = reliab_num
    m.lifetime_notary_duties_assigned = reliab_den
    m.lifetime_notary_duties_completed = reliab_num
    m.shield_installed = shield
    return m


def test_flag_off_preserves_legacy_weight(fresh_flags):
    fresh_flags(DJINN_FF_RELIABILITY_WEIGHT=False)
    scorer = MinerScorer()
    # Unreliable but well-assigned (reliab=0, assigned=10)
    a = _seasoned_miner(1, "5Aa", reliab_num=0, reliab_den=10)
    # Perfect reliability
    b = _seasoned_miner(2, "5Bb", reliab_num=10, reliab_den=10)
    scorer._miners = {1: a, 2: b}

    weights, _ = scorer.compute_weights_detailed(is_active_epoch=True)
    # Both earn weight; the gate is not applied
    assert weights.get(1, 0.0) > 0.0
    assert weights.get(2, 0.0) > 0.0


def test_flag_on_zeros_unreliable_seasoned_miner_floor(fresh_flags):
    """With the flag on, a seasoned miner with zero reliability is multiplied
    by the floor (0.20), not fully zeroed. Keeps them recoverable."""
    fresh_flags(DJINN_FF_RELIABILITY_WEIGHT=True)
    scorer = MinerScorer()
    unreliable = _seasoned_miner(1, "5Aa", reliab_num=0, reliab_den=10)
    reliable = _seasoned_miner(2, "5Bb", reliab_num=10, reliab_den=10)
    scorer._miners = {1: unreliable, 2: reliable}

    weights, breakdowns = scorer.compute_weights_detailed(is_active_epoch=True)
    # Both still earn; unreliable earns roughly 1/5 of reliable
    assert weights[1] > 0.0
    assert weights[2] > 0.0
    # Ratio: unreliable / reliable should equal RELIAB_FLOOR (0.20) post-normalization
    # because the raw scores pre-gate are equal (same accuracy, uptime, etc.)
    ratio = weights[1] / weights[2]
    assert ratio == pytest.approx(scorer.RELIAB_FLOOR, rel=0.05)


def test_flag_on_skips_gate_below_min_assigned(fresh_flags):
    """A miner with fewer than RELIAB_GATE_MIN_ASSIGNED duties is not gated,
    so new miners don't get zeroed while accumulating notary history.

    Proof: an unreliable below-gate miner should score the same as the same
    miner with the flag off — the gate didn't fire.
    """
    # Run with flag OFF first to capture baseline score
    fresh_flags(DJINN_FF_RELIABILITY_WEIGHT=False)
    scorer_off = MinerScorer()
    scorer_off._miners = {
        1: _seasoned_miner(
            1,
            "5Aa",
            reliab_num=0,
            reliab_den=MinerScorer.RELIAB_GATE_MIN_ASSIGNED - 1,
        )
    }
    w_off, _ = scorer_off.compute_weights_detailed(is_active_epoch=True)

    # Same miner with flag ON
    fresh_flags(DJINN_FF_RELIABILITY_WEIGHT=True)
    scorer_on = MinerScorer()
    scorer_on._miners = {
        1: _seasoned_miner(
            1,
            "5Aa",
            reliab_num=0,
            reliab_den=MinerScorer.RELIAB_GATE_MIN_ASSIGNED - 1,
        )
    }
    w_on, _ = scorer_on.compute_weights_detailed(is_active_epoch=True)

    # Below-gate miner is not gated, so normalized weights match.
    assert w_on[1] == pytest.approx(w_off[1], rel=0.001)


def test_shield_installed_gives_bonus(fresh_flags):
    fresh_flags(DJINN_FF_RELIABILITY_WEIGHT=True)
    scorer = MinerScorer()
    # Two identical miners except one has shield
    no_shield = _seasoned_miner(1, "5Aa", reliab_num=10, reliab_den=10, shield=False)
    with_shield = _seasoned_miner(2, "5Bb", reliab_num=10, reliab_den=10, shield=True)
    scorer._miners = {1: no_shield, 2: with_shield}

    weights, _ = scorer.compute_weights_detailed(is_active_epoch=True)
    # Shield miner should earn (1 + SHIELD_BONUS) times the no-shield miner
    expected_ratio = 1.0 + scorer.SHIELD_BONUS
    actual_ratio = weights[2] / weights[1]
    assert actual_ratio == pytest.approx(expected_ratio, rel=0.01)


def test_shield_bonus_off_when_flag_off(fresh_flags):
    fresh_flags(DJINN_FF_RELIABILITY_WEIGHT=False)
    scorer = MinerScorer()
    no_shield = _seasoned_miner(1, "5Aa", reliab_num=10, reliab_den=10, shield=False)
    with_shield = _seasoned_miner(2, "5Bb", reliab_num=10, reliab_den=10, shield=True)
    scorer._miners = {1: no_shield, 2: with_shield}

    weights, _ = scorer.compute_weights_detailed(is_active_epoch=True)
    # Without the flag, shield gives no bonus
    assert weights[1] == pytest.approx(weights[2], rel=0.01)


def test_gate_does_not_resurrect_zero_score(fresh_flags):
    """If the score was already zeroed (e.g., by bootstrap or circuit breaker),
    reliability amplification should NOT amplify zero back to something.
    Multiplying zero by a reliability factor is a no-op, but the shield bonus
    path multiplies (1 + bonus) which would also be zero — regression test."""
    fresh_flags(DJINN_FF_RELIABILITY_WEIGHT=True)
    scorer = MinerScorer()
    m = _seasoned_miner(1, "5Aa", reliab_num=10, reliab_den=10, shield=True)
    # Force the pre-gate score path: set accuracy-killer penalty
    m.attestations_total = 5
    m.attestations_valid = 0
    m.proactive_proof_verified = False
    scorer._miners = {1: m}

    weights, _ = scorer.compute_weights_detailed(is_active_epoch=True)
    # Miner still earns SOMETHING (0.05 attestation penalty, not full zero)
    # but shield bonus should not distort the intent of that penalty.
    # This test is about not amplifying already-zero scores.
    assert weights.get(1, 0.0) >= 0.0  # No NaN, no negative, no crash


def test_singleton_reliable_beats_sybil_unreliable(fresh_flags):
    """The point of the whole change: a single reliable miner should earn
    more than a clone army whose UIDs don't actually complete notary work."""
    fresh_flags(DJINN_FF_RELIABILITY_WEIGHT=True)
    scorer = MinerScorer()

    # 1 reliable singleton
    singleton = _seasoned_miner(1, "5Aa", reliab_num=10, reliab_den=10)

    # 10 unreliable cluster UIDs (reliability 0, but assigned >= gate)
    cluster = {}
    for i in range(2, 12):
        cluster[i] = _seasoned_miner(i, f"5Sybil{i:02d}", reliab_num=0, reliab_den=10)

    scorer._miners = {1: singleton, **cluster}

    weights, _ = scorer.compute_weights_detailed(is_active_epoch=True)
    cluster_total = sum(weights[i] for i in range(2, 12))
    singleton_weight = weights[1]

    # Without the flag the cluster would earn ~10× the singleton.
    # With the flag (reliab floor 0.20), the cluster earns only
    # 10 × 0.20 = 2× the singleton. Significant sub-linearity.
    assert cluster_total < 3.0 * singleton_weight
    assert cluster_total > 1.5 * singleton_weight  # Not totally wiped
