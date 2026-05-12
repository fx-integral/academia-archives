"""Tests for the new-miner zero-weight bootstrap window.

Closes the registration-window Sybil hole: a freshly-registered hotkey
should be held at weight 0 until it has accumulated enough scored
samples AND been observed long enough by this validator. Either
condition graduates the miner; both must be unmet to remain in
bootstrap.
"""

from __future__ import annotations

import importlib
import os
import time

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

    # Teardown: ensure the feature_flags singleton is reset to all-OFF
    # so this test does not pollute other test files.
    for key in list(os.environ.keys()):
        if key.startswith("DJINN_FF_"):
            monkeypatch.delenv(key, raising=False)
    from djinn_validator import feature_flags as _ff

    importlib.reload(_ff)


def _young_miner(uid: int, hotkey: str = "5Aa", samples: int = 0) -> MinerMetrics:
    m = MinerMetrics(uid=uid, hotkey=hotkey, first_seen_at=time.time())
    # Set BOTH lifetime and per-epoch counters. Bootstrap eligibility is
    # now keyed off lifetime counts (see total_scored_samples docstring)
    # since queries_total resets per epoch.
    m.queries_total = samples
    m.lifetime_queries = samples
    m.ema_uptime = 0.9
    return m


def _old_miner(uid: int, hotkey: str = "5Bb", samples: int = 200) -> MinerMetrics:
    m = MinerMetrics(uid=uid, hotkey=hotkey, first_seen_at=time.time() - 7 * 86400)
    m.queries_total = samples
    m.lifetime_queries = samples
    m.ema_uptime = 0.9
    return m


def _legacy_miner(uid: int, hotkey: str = "5Cc") -> MinerMetrics:
    m = MinerMetrics(uid=uid, hotkey=hotkey, first_seen_at=0.0)
    m.queries_total = 0
    m.ema_uptime = 0.9
    return m


# ----------------------------------------------------------------------
# is_in_bootstrap predicate
# ----------------------------------------------------------------------


def test_fresh_miner_with_no_samples_is_in_bootstrap():
    m = _young_miner(uid=1)
    assert m.is_in_bootstrap(min_samples=50, min_age_seconds=86400)


def test_fresh_miner_graduates_at_sample_threshold():
    m = _young_miner(uid=1, samples=50)
    assert not m.is_in_bootstrap(min_samples=50, min_age_seconds=86400)


def test_fresh_miner_graduates_at_sample_threshold_with_attestations():
    m = _young_miner(uid=1, samples=20)
    m.attestations_total = 30
    m.lifetime_attestations = 30
    assert m.total_scored_samples() == 50
    assert not m.is_in_bootstrap(min_samples=50, min_age_seconds=86400)


def test_total_scored_samples_includes_peer_notary_duties():
    """A miner that specializes in serving as notary for other miners'
    TLSN sessions is doing real scoreable work. Those duties must count
    toward volume confidence, otherwise notary-sidecar miners are
    perpetually underweighted even when they've been exercised heavily.

    Uses lifetime_notary_duties_assigned (not the per-epoch counter).
    Per-epoch counters reset every tempo in reset_epoch(); using them
    would drop a well-established notary miner back into bootstrap
    every 12 seconds — same regression as commit 1c62061 fixed for
    queries_total.
    """
    m = _young_miner(uid=1, samples=100)
    m.attestations_total = 50
    m.lifetime_attestations = 50
    m.notary_duties_assigned = 200
    m.notary_duties_completed = 180
    m.lifetime_notary_duties_assigned = 200
    m.lifetime_notary_duties_completed = 180

    assert m.total_scored_samples() == 100 + 50 + 200
    assert not m.is_in_bootstrap(min_samples=50, min_age_seconds=86400)


def test_old_miner_with_no_samples_graduates_by_age():
    m = MinerMetrics(uid=1, hotkey="5Aa", first_seen_at=time.time() - 7 * 86400)
    assert not m.is_in_bootstrap(min_samples=50, min_age_seconds=86400)


def test_legacy_miner_never_in_bootstrap():
    """Records persisted before the bootstrap window was introduced have
    first_seen_at == 0.0. Such records must NEVER be retroactively
    penalized; the rolling deploy of the new mechanism must not slash
    miners who were honest before the rule existed."""
    m = _legacy_miner(uid=1)
    assert not m.is_in_bootstrap(min_samples=50, min_age_seconds=86400)


def test_explicit_now_argument():
    """The `now` argument lets tests pin time without monkeypatching."""
    pinned = 1_000_000_000.0
    m = MinerMetrics(uid=1, hotkey="5Aa", first_seen_at=pinned - 100)
    assert m.is_in_bootstrap(min_samples=50, min_age_seconds=86400, now=pinned)
    assert not m.is_in_bootstrap(min_samples=50, min_age_seconds=50, now=pinned)


# ----------------------------------------------------------------------
# get_or_create assigns first_seen_at
# ----------------------------------------------------------------------


def test_get_or_create_sets_first_seen_at():
    scorer = MinerScorer()
    m = scorer.get_or_create(uid=42, hotkey="5Aa")
    assert m.first_seen_at > 0


def test_hotkey_change_resets_first_seen_at():
    """If the hotkey at a UID changes, the new owner enters bootstrap."""
    scorer = MinerScorer()
    m1 = scorer.get_or_create(uid=42, hotkey="5Aa")
    original = m1.first_seen_at
    time.sleep(0.01)
    m2 = scorer.get_or_create(uid=42, hotkey="5Bb")
    assert m2.first_seen_at > original
    assert m2.queries_total == 0
    assert m2.first_seen_at > 0


def test_get_or_create_preserves_first_seen_at_on_same_hotkey():
    scorer = MinerScorer()
    m1 = scorer.get_or_create(uid=42, hotkey="5Aa")
    original = m1.first_seen_at
    m1.queries_total = 5
    time.sleep(0.01)
    m2 = scorer.get_or_create(uid=42, hotkey="5Aa")
    assert m2.first_seen_at == original
    assert m2.queries_total == 5


# ----------------------------------------------------------------------
# Weight zeroing under the feature flag
# ----------------------------------------------------------------------


def test_bootstrap_does_nothing_when_flag_off(fresh_flags):
    fresh_flags(DJINN_FF_NEW_MINER_ZERO_WEIGHT=False)
    scorer = MinerScorer()
    young = _young_miner(uid=1, samples=600)
    young.queries_correct = 600
    scorer._miners[1] = young

    weights, _breakdowns = scorer.compute_weights_detailed(is_active_epoch=True)
    assert weights.get(1, 0.0) > 0.0


def test_bootstrap_zeros_fresh_miner_when_flag_on(fresh_flags):
    fresh_flags(DJINN_FF_NEW_MINER_ZERO_WEIGHT=True)
    scorer = MinerScorer()
    young = _young_miner(uid=1)
    young.queries_total = 5
    young.queries_correct = 5
    scorer._miners[1] = young
    old = _old_miner(uid=2, samples=200)
    old.queries_correct = 200
    scorer._miners[2] = old

    weights, _ = scorer.compute_weights_detailed(is_active_epoch=True)
    # The young miner is zeroed; the old miner takes the entire normalized weight
    assert weights.get(1, 0.0) == 0.0
    assert weights.get(2, 0.0) > 0.0


def test_bootstrap_does_not_zero_legacy_miner(fresh_flags):
    fresh_flags(DJINN_FF_NEW_MINER_ZERO_WEIGHT=True)
    scorer = MinerScorer()
    legacy = _legacy_miner(uid=1)
    legacy.queries_total = 600
    legacy.queries_correct = 600
    legacy.lifetime_queries = 600
    scorer._miners[1] = legacy

    weights, _ = scorer.compute_weights_detailed(is_active_epoch=True)
    assert weights.get(1, 0.0) > 0.0


def test_bootstrap_releases_after_enough_samples(fresh_flags):
    fresh_flags(DJINN_FF_NEW_MINER_ZERO_WEIGHT=True)
    scorer = MinerScorer()
    young = _young_miner(uid=1, samples=scorer.BOOTSTRAP_MIN_SAMPLES)
    young.queries_correct = young.queries_total
    scorer._miners[1] = young

    weights, _ = scorer.compute_weights_detailed(is_active_epoch=True)
    assert weights.get(1, 0.0) > 0.0


def test_bootstrap_with_only_attestations_counts():
    m = _young_miner(uid=1)
    m.attestations_total = 50
    m.lifetime_attestations = 50
    assert not m.is_in_bootstrap(min_samples=50, min_age_seconds=86400)


def test_bootstrap_with_split_samples():
    m = _young_miner(uid=1, samples=25)
    m.attestations_total = 25
    m.lifetime_attestations = 25
    assert not m.is_in_bootstrap(min_samples=50, min_age_seconds=86400)


def test_bootstrap_survives_epoch_reset_of_per_epoch_queries():
    """Regression: a miner with lifetime evidence but ZERO current-epoch
    queries must NOT fall back into the bootstrap window just because
    the per-epoch counter was zeroed. This was the prod bug (2026-04-14)
    where 23/223 miners held weight=0 because reset_epoch() zeros
    queries_total but bootstrap-eligibility used it.
    """
    m = _young_miner(uid=1, samples=0)  # queries_total=0 (just-reset epoch)
    m.lifetime_queries = 200  # but plenty of lifetime history
    m.lifetime_attestations = 0
    m.attestations_total = 0  # attestations DON'T reset, but this miner got none
    assert m.total_scored_samples() == 200
    assert not m.is_in_bootstrap(min_samples=50, min_age_seconds=86400)


# ----------------------------------------------------------------------
# Persistence round-trip
# ----------------------------------------------------------------------


def test_first_seen_at_persists_round_trip(tmp_path):
    db_path = tmp_path / "scores.db"
    scorer = MinerScorer(db_path=str(db_path))
    m = scorer.get_or_create(uid=7, hotkey="5Aa")
    m.queries_total = 10
    original_seen = m.first_seen_at
    scorer.persist(uid=7)

    scorer2 = MinerScorer(db_path=str(db_path))
    m2 = scorer2.get(uid=7)
    assert m2 is not None
    assert m2.first_seen_at == pytest.approx(original_seen, abs=0.01)
    assert m2.queries_total == 10


def test_legacy_db_record_loads_with_zero_first_seen_at(tmp_path):
    """A pre-bootstrap-window record (no first_seen_at field) loads as 0.0
    and is treated as 'not in bootstrap' by is_in_bootstrap."""
    import json as _json
    import sqlite3 as _sqlite3

    db_path = tmp_path / "legacy.db"
    conn = _sqlite3.connect(str(db_path))
    conn.execute("CREATE TABLE miner_scores (uid INTEGER PRIMARY KEY, hotkey TEXT, data TEXT, updated_at REAL)")
    legacy_data = _json.dumps({"queries_total": 0, "ema_uptime": 0.5})
    conn.execute(
        "INSERT INTO miner_scores VALUES (?, ?, ?, ?)",
        (3, "5Legacy", legacy_data, time.time()),
    )
    conn.commit()
    conn.close()

    scorer = MinerScorer(db_path=str(db_path))
    m = scorer.get(uid=3)
    assert m is not None
    assert m.first_seen_at == 0.0
    assert not m.is_in_bootstrap(min_samples=50, min_age_seconds=86400)
