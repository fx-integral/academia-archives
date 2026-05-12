"""Tests for the validator-side oracle attack mitigation: independent
observation of available indices and cross-check against the buyer's claim.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

from djinn_validator.core.purchase_audit import (
    CrossCheckResult,
    ObservedAvailability,
    _compute_observed_indices,
    cross_check,
)


@dataclass
class FakePick:
    market: str
    line: float | None
    side: str | None
    team: str | None
    odds: int  # American odds


@dataclass
class FakeSignalMeta:
    sport: str
    event_id: str
    home_team: str
    away_team: str
    lines: list[FakePick] = field(default_factory=list)


def _make_signal(*odds_per_line: int) -> FakeSignalMeta:
    return FakeSignalMeta(
        sport="basketball_nba",
        event_id="evt_123",
        home_team="LAL",
        away_team="BOS",
        lines=[FakePick(market="spreads", line=-3.5, side=None, team="LAL", odds=o) for o in odds_per_line],
    )


def _miner_response(per_line: dict[int, list[tuple[str, float]]]) -> dict[str, Any]:
    """Build a miner /v1/check response.

    per_line maps 1-based line index to list of (bookmaker, decimal_odds).
    """
    return {
        "results": [
            {
                "index": idx,
                "bookmakers": [{"bookmaker": book, "odds": price} for book, price in books],
            }
            for idx, books in per_line.items()
        ]
    }


# ----------------------------------------------------------------------
# _compute_observed_indices
# ----------------------------------------------------------------------


def test_observed_includes_lines_executable_at_buyer_books():
    signal = _make_signal(-110, -110, -110)
    miner_data = [
        _miner_response(
            {
                1: [("draftkings", 1.95)],
                2: [("draftkings", 1.85)],  # below committed
                3: [("draftkings", 2.0)],
            }
        )
    ]
    obs = _compute_observed_indices(
        signal_meta=signal,
        miner_data=miner_data,
        buyer_books=["draftkings"],
        line_count=3,
        miner_source="miner",
    )
    assert obs.observed_indices == {1, 3}
    assert obs.source == "miner"


def test_observed_filters_to_buyer_books_only():
    signal = _make_signal(-110, -110)
    miner_data = [
        _miner_response(
            {
                1: [("draftkings", 1.95), ("fanduel", 2.0)],
                2: [("pinnacle", 2.0), ("betmgm", 1.85)],
            }
        )
    ]
    obs = _compute_observed_indices(
        signal_meta=signal,
        miner_data=miner_data,
        buyer_books=["draftkings", "fanduel"],
        line_count=2,
        miner_source="miner",
    )
    assert obs.observed_indices == {1}


def test_observed_empty_when_no_miner_data_and_not_stored_fallback():
    signal = _make_signal(-110, -110)
    obs = _compute_observed_indices(
        signal_meta=signal,
        miner_data=[],
        buyer_books=["draftkings"],
        line_count=2,
        miner_source="miner",
    )
    assert obs.observed_indices == set()


def test_observed_uses_stored_prices_when_in_stored_fallback():
    signal = _make_signal(-110, -110, -110)
    obs = _compute_observed_indices(
        signal_meta=signal,
        miner_data=[],
        buyer_books=["draftkings"],
        line_count=3,
        miner_source="stored",
    )
    assert obs.observed_indices == {1, 2, 3}
    assert obs.source == "stored"


def test_per_book_executable_breakdown():
    signal = _make_signal(-110, -110)
    miner_data = [
        _miner_response(
            {
                1: [("draftkings", 1.95), ("fanduel", 2.0)],
                2: [("draftkings", 1.85), ("fanduel", 2.05)],
            }
        )
    ]
    obs = _compute_observed_indices(
        signal_meta=signal,
        miner_data=miner_data,
        buyer_books=["draftkings", "fanduel"],
        line_count=2,
        miner_source="miner",
    )
    assert obs.observed_indices == {1, 2}
    assert obs.executable_indices_per_book["draftkings"] == {1}
    assert obs.executable_indices_per_book["fanduel"] == {1, 2}


# ----------------------------------------------------------------------
# cross_check
# ----------------------------------------------------------------------


def _obs(indices: set[int], source: str = "miner", line_count: int = 5) -> ObservedAvailability:
    return ObservedAvailability(observed_indices=indices, source=source, line_count=line_count)


def test_cross_check_pass_when_claim_matches_observation():
    result = cross_check(claimed_indices=[1, 2, 3], observed=_obs({1, 2, 3}))
    assert result.verdict == "pass"
    assert result.allow_purchase
    assert not result.is_attack_signal
    assert result.extra_in_claim == set()
    assert result.missing_from_claim == set()


def test_cross_check_narrowed_when_buyer_omits_some_observed():
    result = cross_check(claimed_indices=[1, 2], observed=_obs({1, 2, 3, 4}))
    assert result.verdict == "narrowed"
    assert result.allow_purchase
    assert not result.is_attack_signal
    assert result.missing_from_claim == {3, 4}
    assert result.extra_in_claim == set()


def test_cross_check_rejects_claim_extending_beyond_observation():
    result = cross_check(claimed_indices=[1, 2, 99], observed=_obs({1, 2, 3}))
    assert result.verdict == "claim_extends_beyond_observation"
    assert not result.allow_purchase
    assert result.is_attack_signal
    assert result.extra_in_claim == {99}


def test_cross_check_validator_blind_when_signal_unknown():
    obs = ObservedAvailability(observed_indices=set(), source="empty", line_count=0)
    result = cross_check(claimed_indices=[1, 2, 3], observed=obs)
    assert result.verdict == "validator_blind"
    assert result.allow_purchase
    assert not result.is_attack_signal


def test_cross_check_validator_blind_when_no_miners_reachable():
    obs = ObservedAvailability(observed_indices=set(), source="stored", line_count=5)
    result = cross_check(claimed_indices=[1, 2, 3], observed=obs)
    assert result.verdict == "validator_blind"
    assert result.allow_purchase


def test_cross_check_with_empty_claim():
    result = cross_check(claimed_indices=[], observed=_obs({1, 2, 3}))
    assert result.verdict == "narrowed"
    assert result.allow_purchase
    assert result.missing_from_claim == {1, 2, 3}


def test_cross_check_attack_with_partial_extra():
    """Buyer claims indices that include some real and some fabricated.

    This is the canonical binary-search probe: the attacker takes a
    valid subset and adds one or two extras to test which complete.
    """
    result = cross_check(claimed_indices=[1, 2, 3, 47, 99], observed=_obs({1, 2, 3, 4, 5}))
    assert result.verdict == "claim_extends_beyond_observation"
    assert not result.allow_purchase
    assert result.extra_in_claim == {47, 99}


def test_cross_check_disjoint_claim_is_attack():
    result = cross_check(claimed_indices=[10, 20, 30], observed=_obs({1, 2, 3}))
    assert result.verdict == "claim_extends_beyond_observation"
    assert not result.allow_purchase
    assert result.extra_in_claim == {10, 20, 30}


# ----------------------------------------------------------------------
# Integration: combined helper + cross check
# ----------------------------------------------------------------------


def test_integration_attack_caught():
    """Full path: validator observes 3 lines available, buyer tries to
    sneak a 4th index in. Cross-check rejects."""
    signal = _make_signal(-110, -110, -110, -110, -110)
    miner_data = [
        _miner_response(
            {
                1: [("draftkings", 1.95)],
                2: [("draftkings", 1.95)],
                3: [("draftkings", 1.95)],
                4: [("draftkings", 1.85)],  # below committed, not executable
                5: [("draftkings", 1.85)],  # below committed, not executable
            }
        )
    ]
    obs = _compute_observed_indices(
        signal_meta=signal,
        miner_data=miner_data,
        buyer_books=["draftkings"],
        line_count=5,
        miner_source="miner",
    )
    assert obs.observed_indices == {1, 2, 3}
    result = cross_check(claimed_indices=[1, 2, 3, 5], observed=obs)
    assert not result.allow_purchase
    assert result.is_attack_signal
    assert result.extra_in_claim == {5}


def test_integration_honest_buyer_passes():
    signal = _make_signal(-110, -110, -110)
    miner_data = [
        _miner_response(
            {
                1: [("draftkings", 1.95)],
                2: [("draftkings", 1.95)],
                3: [("draftkings", 1.95)],
            }
        )
    ]
    obs = _compute_observed_indices(
        signal_meta=signal,
        miner_data=miner_data,
        buyer_books=["draftkings"],
        line_count=3,
        miner_source="miner",
    )
    result = cross_check(claimed_indices=[1, 2, 3], observed=obs)
    assert result.verdict == "pass"
    assert result.allow_purchase


def test_integration_miner_outage_falls_back_gracefully():
    """When miners are down, validator can't observe anything. Don't
    deny service to honest buyers — fall back to trusting the claim
    with a warning."""
    signal = _make_signal(-110, -110)
    obs = _compute_observed_indices(
        signal_meta=signal,
        miner_data=[],  # miner outage
        buyer_books=["draftkings"],
        line_count=2,
        miner_source="miner",  # tried, but got nothing
    )
    assert obs.observed_indices == set()
    result = cross_check(claimed_indices=[1, 2], observed=obs)
    assert result.verdict == "validator_blind"
    assert result.allow_purchase
