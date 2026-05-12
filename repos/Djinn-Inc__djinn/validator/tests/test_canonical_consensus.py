"""Tests for the canonical odds consensus reducer."""

from __future__ import annotations

import pytest

from djinn_validator.utils.canonical_consensus import (
    ConsensusObservation,
    miner_distance_scores,
    reduce_observations_to_consensus,
)


def _obs(**overrides) -> dict:
    """Build a canonical observation dict with reasonable defaults."""
    base = {
        "event_id": "evt-1",
        "sport": "basketball_nba",
        "home_team": "Celtics",
        "away_team": "Lakers",
        "commence_time_ms": 1_776_240_000_000,
        "market": "moneyline",
        "side": "home",
        "decimal_price": 1.91,
        "line": None,
        "bookmaker": "draftkings",
        "fetched_at_ms": 1_776_240_100_000,
        "source": "OddsApiClient",
    }
    base.update(overrides)
    return base


class TestReduceObservationsToConsensus:
    def test_single_miner_single_observation(self) -> None:
        results = reduce_observations_to_consensus([[_obs()]])
        assert len(results) == 1
        c = results[0]
        assert c.event_id == "evt-1"
        assert c.market == "moneyline"
        assert c.side == "home"
        assert c.bookmaker == "draftkings"
        assert c.consensus_price == 1.91
        assert c.miner_count == 1
        assert c.miner_prices == [1.91]

    def test_three_miners_median_selected(self) -> None:
        per_miner = [
            [_obs(decimal_price=1.90)],
            [_obs(decimal_price=1.92)],
            [_obs(decimal_price=1.95)],
        ]
        results = reduce_observations_to_consensus(per_miner)
        assert len(results) == 1
        assert results[0].consensus_price == 1.92
        assert results[0].miner_count == 3
        assert results[0].miner_prices == [1.90, 1.92, 1.95]

    def test_outlier_doesnt_shift_median(self) -> None:
        per_miner = [
            [_obs(decimal_price=1.90)],
            [_obs(decimal_price=1.91)],
            [_obs(decimal_price=1.92)],
            [_obs(decimal_price=5.00)],  # way off
        ]
        results = reduce_observations_to_consensus(per_miner)
        # median of [1.90, 1.91, 1.92, 5.00] = (1.91 + 1.92) / 2 = 1.915
        assert results[0].consensus_price == 1.915

    def test_different_books_separate_groups(self) -> None:
        per_miner = [
            [
                _obs(bookmaker="draftkings", decimal_price=1.91),
                _obs(bookmaker="fanduel", decimal_price=1.95),
            ],
            [
                _obs(bookmaker="draftkings", decimal_price=1.92),
                _obs(bookmaker="fanduel", decimal_price=1.96),
            ],
        ]
        results = reduce_observations_to_consensus(per_miner)
        assert len(results) == 2
        dk = next(c for c in results if c.bookmaker == "draftkings")
        fd = next(c for c in results if c.bookmaker == "fanduel")
        assert dk.consensus_price == pytest.approx(1.915)
        assert fd.consensus_price == pytest.approx(1.955)

    def test_different_events_separate_groups(self) -> None:
        per_miner = [
            [_obs(event_id="e1"), _obs(event_id="e2", decimal_price=2.10)],
        ]
        results = reduce_observations_to_consensus(per_miner)
        assert len(results) == 2
        events = {c.event_id for c in results}
        assert events == {"e1", "e2"}

    def test_min_miners_threshold_drops_under_quorum(self) -> None:
        per_miner = [
            [_obs(decimal_price=1.91)],  # only one miner
        ]
        results = reduce_observations_to_consensus(per_miner, min_miners=3)
        assert results == []

    def test_min_miners_threshold_keeps_at_quorum(self) -> None:
        per_miner = [
            [_obs(decimal_price=1.90)],
            [_obs(decimal_price=1.91)],
            [_obs(decimal_price=1.92)],
        ]
        results = reduce_observations_to_consensus(per_miner, min_miners=3)
        assert len(results) == 1

    def test_totals_line_preserved_when_agreement(self) -> None:
        per_miner = [
            [_obs(market="total", side="over", line=224.5)],
            [_obs(market="total", side="over", line=224.5)],
        ]
        results = reduce_observations_to_consensus(per_miner)
        assert len(results) == 1
        assert results[0].consensus_line == 224.5

    def test_totals_line_dropped_when_disagreement(self) -> None:
        per_miner = [
            [_obs(market="total", side="over", line=224.5)],
            [_obs(market="total", side="over", line=225.0)],  # different line
        ]
        results = reduce_observations_to_consensus(per_miner)
        assert len(results) == 1
        # Line disagreement means we drop the line from consensus.
        assert results[0].consensus_line is None

    def test_malformed_observations_dropped(self) -> None:
        per_miner = [
            [_obs(), "not a dict", None, {"event_id": "e1"}],  # missing most fields
        ]
        results = reduce_observations_to_consensus(per_miner)
        assert len(results) == 1  # only the valid one

    def test_zero_or_negative_prices_dropped(self) -> None:
        per_miner = [
            [_obs(decimal_price=1.91)],
            [_obs(decimal_price=0)],
            [_obs(decimal_price=-1)],
        ]
        results = reduce_observations_to_consensus(per_miner)
        assert results[0].consensus_price == 1.91
        assert results[0].miner_count == 1

    def test_empty_input_returns_empty(self) -> None:
        assert reduce_observations_to_consensus([]) == []
        assert reduce_observations_to_consensus([[], [], []]) == []

    def test_sources_deduplicated(self) -> None:
        per_miner = [
            [_obs(source="OddsApiClient")],
            [_obs(source="OddsApiClient")],
            [_obs(source="OddsJamClient")],
        ]
        results = reduce_observations_to_consensus(per_miner)
        assert len(results) == 1
        assert results[0].sources == ["OddsApiClient", "OddsJamClient"]

    def test_results_deterministic_order(self) -> None:
        per_miner = [
            [
                _obs(event_id="z-evt", market="moneyline"),
                _obs(event_id="a-evt", market="total", side="over", line=220),
                _obs(event_id="a-evt", market="total", side="under", line=220),
            ],
        ]
        results = reduce_observations_to_consensus(per_miner)
        # Sorted by (event_id, market, side, bookmaker)
        assert [c.event_id for c in results] == ["a-evt", "a-evt", "z-evt"]


class TestMinerDistanceScores:
    def test_identical_miner_has_zero_distance(self) -> None:
        per_miner = [
            [_obs(decimal_price=1.91)],
            [_obs(decimal_price=1.91)],
            [_obs(decimal_price=1.91)],
        ]
        consensus = reduce_observations_to_consensus(per_miner)
        scores = miner_distance_scores(per_miner, consensus)
        assert scores == [0.0, 0.0, 0.0]

    def test_outlier_miner_gets_larger_score(self) -> None:
        per_miner = [
            [_obs(decimal_price=1.90)],
            [_obs(decimal_price=1.91)],
            [_obs(decimal_price=2.50)],  # outlier
        ]
        consensus = reduce_observations_to_consensus(per_miner)
        scores = miner_distance_scores(per_miner, consensus)
        # Median = 1.91, so distances are:
        #   miner 0: |1.90 - 1.91| / 1.91 ≈ 0.00524
        #   miner 1: 0
        #   miner 2: |2.50 - 1.91| / 1.91 ≈ 0.309
        assert scores[2] > scores[0] > scores[1]
        assert scores[1] == 0.0

    def test_empty_miner_gets_neutral_score(self) -> None:
        per_miner = [
            [_obs(decimal_price=1.91)],
            [],
        ]
        consensus = reduce_observations_to_consensus(per_miner)
        scores = miner_distance_scores(per_miner, consensus)
        assert scores[1] == 1.0
