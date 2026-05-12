"""v1747 Phase 2b — canonical_outcome_for_line + LineKey + LineResolution.

The pure function ``canonical_outcome_for_line`` is the authoritative
ESPN→outcome mapping per docs/v1747-line-schema.md §5. These tests pin the
per-sport rules (NBA STATUS_FINAL, soccer FT-only spread, NHL shootout
exclusion, MLB STATUS_END_OF_REGULATION, postponed→Void after 7d, integer
push, etc.) using frozen ESPN payload fixtures so a schema drift surfaces
here before it ships.

Cross-checked: see contracts/test/fixtures/v1747_golden_vectors.json and
tests/test_outcome_signer.py for byte-identical agreement with Solidity.
"""

from __future__ import annotations

import time

import pytest

from djinn_validator.chain.outcome_signer import LineKey, line_hash
from djinn_validator.core.outcomes import (
    LineResolution,
    Outcome,
    OutcomeAttestor,
    ParsedPick,
    SignalMetadata,
    _canonicalize_line_value,
    canonical_outcome_for_line,
    parsed_pick_to_line_key,
)


# ---------------------------------------------------------------------------
# ESPN payload fixtures (frozen — match the canonical endpoint shape pinned
# in docs/v1747-line-schema.md §5)
# ---------------------------------------------------------------------------


def _espn_event(
    *,
    status_name: str,
    home_score: int | None = None,
    away_score: int | None = None,
    date: str = "2026-04-04T02:00Z",
    home_winner: bool = False,
    away_winner: bool = False,
    home_linescores: list[int] | None = None,
    away_linescores: list[int] | None = None,
) -> dict:
    """Build a frozen ESPN event payload at the canonical endpoint shape.

    Produces the exact shape the schema doc pins:
    competitions[0].status.type.name + competitions[0].competitors[*]
    with homeAway / score / linescores / winner fields.
    """
    home_competitor: dict = {"homeAway": "home"}
    away_competitor: dict = {"homeAway": "away"}
    if home_score is not None:
        home_competitor["score"] = str(home_score)
    if away_score is not None:
        away_competitor["score"] = str(away_score)
    if home_linescores is not None:
        home_competitor["linescores"] = [{"value": v} for v in home_linescores]
    if away_linescores is not None:
        away_competitor["linescores"] = [{"value": v} for v in away_linescores]
    if home_winner:
        home_competitor["winner"] = True
    if away_winner:
        away_competitor["winner"] = True
    return {
        "id": "test-event",
        "competitions": [
            {
                "date": date,
                "status": {"type": {"name": status_name}},
                "competitors": [home_competitor, away_competitor],
            }
        ],
    }


# ---------------------------------------------------------------------------
# Basketball — STATUS_FINAL, OT counts toward all markets
# ---------------------------------------------------------------------------


class TestBasketballNBA:
    def test_spread_home_covers(self) -> None:
        event = _espn_event(status_name="STATUS_FINAL", home_score=110, away_score=105)
        # Lakers home -3.5: 110-105=5 > 3.5 → cover → Favorable
        assert (
            canonical_outcome_for_line("basketball_nba", "spread", "home", "-3.5", event)
            == Outcome.FAVORABLE
        )

    def test_spread_home_pushes_integer(self) -> None:
        event = _espn_event(status_name="STATUS_FINAL", home_score=110, away_score=105)
        # Home -5.0: exactly the margin → push → Void
        assert (
            canonical_outcome_for_line("basketball_nba", "spread", "home", "-5.0", event)
            == Outcome.VOID
        )

    def test_spread_away_dog_covers(self) -> None:
        event = _espn_event(status_name="STATUS_FINAL", home_score=110, away_score=105)
        # Away +3.5: -5+3.5=-1.5 < 0 → loses → Unfavorable
        assert (
            canonical_outcome_for_line("basketball_nba", "spread", "away", "+3.5", event)
            == Outcome.UNFAVORABLE
        )

    def test_total_over_hits(self) -> None:
        event = _espn_event(status_name="STATUS_FINAL", home_score=110, away_score=105)
        # Total 215.0; over 220.5 → 215 < 220.5 → Unfavorable
        assert (
            canonical_outcome_for_line("basketball_nba", "total", "over", "220.5", event)
            == Outcome.UNFAVORABLE
        )
        # Over 210.5 → 215 > 210.5 → Favorable
        assert (
            canonical_outcome_for_line("basketball_nba", "total", "over", "210.5", event)
            == Outcome.FAVORABLE
        )

    def test_total_push_integer(self) -> None:
        event = _espn_event(status_name="STATUS_FINAL", home_score=110, away_score=105)
        assert (
            canonical_outcome_for_line("basketball_nba", "total", "over", "215.0", event)
            == Outcome.VOID
        )

    def test_moneyline_home_wins(self) -> None:
        event = _espn_event(status_name="STATUS_FINAL", home_score=110, away_score=105)
        assert (
            canonical_outcome_for_line("basketball_nba", "moneyline", "home", "", event)
            == Outcome.FAVORABLE
        )
        assert (
            canonical_outcome_for_line("basketball_nba", "moneyline", "away", "", event)
            == Outcome.UNFAVORABLE
        )

    def test_in_progress_returns_pending(self) -> None:
        event = _espn_event(status_name="STATUS_IN_PROGRESS", home_score=55, away_score=50)
        assert (
            canonical_outcome_for_line("basketball_nba", "spread", "home", "-3.5", event)
            == Outcome.PENDING
        )

    def test_ncaab_uses_status_final(self) -> None:
        event = _espn_event(status_name="STATUS_FINAL", home_score=88, away_score=82)
        assert (
            canonical_outcome_for_line("basketball_ncaab", "moneyline", "home", "", event)
            == Outcome.FAVORABLE
        )


# ---------------------------------------------------------------------------
# American football — STATUS_FINAL, OT counts toward all markets
# ---------------------------------------------------------------------------


class TestAmericanFootball:
    def test_nfl_spread(self) -> None:
        event = _espn_event(status_name="STATUS_FINAL", home_score=24, away_score=21)
        # Home -3.5: 3 - 3.5 = -0.5 → Unfavorable (didn't cover by enough)
        assert (
            canonical_outcome_for_line("americanfootball_nfl", "spread", "home", "-3.5", event)
            == Outcome.UNFAVORABLE
        )
        # Home -2.5: 3 - 2.5 = +0.5 → Favorable
        assert (
            canonical_outcome_for_line("americanfootball_nfl", "spread", "home", "-2.5", event)
            == Outcome.FAVORABLE
        )

    def test_ncaaf_total_over(self) -> None:
        event = _espn_event(status_name="STATUS_FINAL", home_score=42, away_score=35)
        # Total 77; over 70.5 → Favorable
        assert (
            canonical_outcome_for_line("americanfootball_ncaaf", "total", "over", "70.5", event)
            == Outcome.FAVORABLE
        )

    def test_pre_game_returns_pending(self) -> None:
        event = _espn_event(status_name="STATUS_SCHEDULED")
        assert (
            canonical_outcome_for_line("americanfootball_nfl", "moneyline", "home", "", event)
            == Outcome.PENDING
        )


# ---------------------------------------------------------------------------
# Baseball MLB — STATUS_FINAL or STATUS_END_OF_REGULATION (weather-shortened)
# ---------------------------------------------------------------------------


class TestBaseballMLB:
    def test_status_final(self) -> None:
        event = _espn_event(status_name="STATUS_FINAL", home_score=7, away_score=4)
        assert (
            canonical_outcome_for_line("baseball_mlb", "moneyline", "home", "", event)
            == Outcome.FAVORABLE
        )

    def test_status_end_of_regulation_resolves(self) -> None:
        """Weather-shortened ≥5 innings: STATUS_END_OF_REGULATION acts terminal."""
        event = _espn_event(status_name="STATUS_END_OF_REGULATION", home_score=3, away_score=2)
        assert (
            canonical_outcome_for_line("baseball_mlb", "moneyline", "home", "", event)
            == Outcome.FAVORABLE
        )
        assert (
            canonical_outcome_for_line("baseball_mlb", "total", "under", "8.5", event)
            == Outcome.FAVORABLE
        )

    def test_total_under_misses(self) -> None:
        event = _espn_event(status_name="STATUS_FINAL", home_score=7, away_score=4)
        # Total 11; under 8.5 → 11 > 8.5 → Unfavorable
        assert (
            canonical_outcome_for_line("baseball_mlb", "total", "under", "8.5", event)
            == Outcome.UNFAVORABLE
        )

    def test_in_progress_returns_pending(self) -> None:
        event = _espn_event(status_name="STATUS_IN_PROGRESS", home_score=3, away_score=2)
        assert (
            canonical_outcome_for_line("baseball_mlb", "moneyline", "home", "", event)
            == Outcome.PENDING
        )


# ---------------------------------------------------------------------------
# Hockey NHL — STATUS_FINAL or STATUS_AFTER_SHOOTOUT
# Schema rule: shootout goal does NOT count toward total/spread; ML uses
# raw final score (winner determination including shootout).
# ---------------------------------------------------------------------------


class TestHockeyNHL:
    def test_status_final_regular_or_ot(self) -> None:
        event = _espn_event(status_name="STATUS_FINAL", home_score=4, away_score=3)
        assert (
            canonical_outcome_for_line("icehockey_nhl", "moneyline", "home", "", event)
            == Outcome.FAVORABLE
        )
        assert (
            canonical_outcome_for_line("icehockey_nhl", "spread", "home", "-0.5", event)
            == Outcome.FAVORABLE
        )

    def test_shootout_excluded_from_spread(self) -> None:
        """STATUS_AFTER_SHOOTOUT: subtract the shootout goal from the winner
        for spread/total. ESPN reports the post-shootout final score; the
        regulation+OT score = final - 1 for the winner.
        """
        # Home wins 4-3 in shootout. Reg+OT was 3-3.
        event = _espn_event(status_name="STATUS_AFTER_SHOOTOUT", home_score=4, away_score=3)
        # Home -0.5: reg+OT 3-3 = 0; 0 + (-0.5) = -0.5 → Unfavorable
        assert (
            canonical_outcome_for_line("icehockey_nhl", "spread", "home", "-0.5", event)
            == Outcome.UNFAVORABLE
        )
        # Away +0.5: reg+OT 3-3; 0 + 0.5 = 0.5 → Favorable
        assert (
            canonical_outcome_for_line("icehockey_nhl", "spread", "away", "+0.5", event)
            == Outcome.FAVORABLE
        )

    def test_shootout_excluded_from_total(self) -> None:
        # Home wins 4-3 SO; reg+OT 3-3 = total 6
        event = _espn_event(status_name="STATUS_AFTER_SHOOTOUT", home_score=4, away_score=3)
        # Total 5.5: 6 > 5.5 → over Favorable
        assert (
            canonical_outcome_for_line("icehockey_nhl", "total", "over", "5.5", event)
            == Outcome.FAVORABLE
        )
        # Total 6.5: 6 < 6.5 → under Favorable
        assert (
            canonical_outcome_for_line("icehockey_nhl", "total", "under", "6.5", event)
            == Outcome.FAVORABLE
        )

    def test_shootout_moneyline_includes_shootout(self) -> None:
        """ML uses the raw final score: shootout winner takes ML."""
        event = _espn_event(status_name="STATUS_AFTER_SHOOTOUT", home_score=4, away_score=3)
        assert (
            canonical_outcome_for_line("icehockey_nhl", "moneyline", "home", "", event)
            == Outcome.FAVORABLE
        )
        assert (
            canonical_outcome_for_line("icehockey_nhl", "moneyline", "away", "", event)
            == Outcome.UNFAVORABLE
        )


# ---------------------------------------------------------------------------
# Soccer — STATUS_FULL_TIME, STATUS_AFTER_EXTRA_TIME, STATUS_AFTER_PENALTIES
# Schema rule: spread/total settle at full-time only (90'). Moneyline
# includes ET and penalties for winner determination.
# ---------------------------------------------------------------------------


class TestSoccer:
    def test_full_time_resolves_all_markets(self) -> None:
        event = _espn_event(status_name="STATUS_FULL_TIME", home_score=2, away_score=1)
        assert (
            canonical_outcome_for_line("soccer_epl", "moneyline", "home", "", event)
            == Outcome.FAVORABLE
        )
        # Home -0.5: 1 - 0.5 = 0.5 → Favorable
        assert (
            canonical_outcome_for_line("soccer_epl", "spread", "home", "-0.5", event)
            == Outcome.FAVORABLE
        )
        # Total 2.5: 3 > 2.5 → over Favorable
        assert (
            canonical_outcome_for_line("soccer_epl", "total", "over", "2.5", event)
            == Outcome.FAVORABLE
        )

    def test_after_extra_time_uses_ft_linescores_for_spread(self) -> None:
        """ET played → FT was tied. Spread/total settle at FT (sum first 2
        linescores). FT 1-1 here; spread at +0.0 push → Void."""
        event = _espn_event(
            status_name="STATUS_AFTER_EXTRA_TIME",
            home_score=3,  # post-ET
            away_score=2,  # post-ET
            home_linescores=[1, 0, 1, 1],  # period 1=1, period 2=0 → FT 1
            away_linescores=[0, 1, 1, 0],  # period 1=0, period 2=1 → FT 1
        )
        # FT 1-1. Spread +0.0 → push → Void
        assert (
            canonical_outcome_for_line("soccer_epl", "spread", "home", "+0.0", event)
            == Outcome.VOID
        )
        # Total at FT = 2; under 2.5 → Favorable
        assert (
            canonical_outcome_for_line("soccer_epl", "total", "under", "2.5", event)
            == Outcome.FAVORABLE
        )

    def test_after_extra_time_moneyline_uses_full_score(self) -> None:
        """ML includes ET. Home wins 3-2 after ET → home ML wins."""
        event = _espn_event(
            status_name="STATUS_AFTER_EXTRA_TIME",
            home_score=3,
            away_score=2,
            home_linescores=[1, 0, 1, 1],
            away_linescores=[0, 1, 1, 0],
        )
        assert (
            canonical_outcome_for_line("soccer_epl", "moneyline", "home", "", event)
            == Outcome.FAVORABLE
        )

    def test_after_penalties_moneyline_uses_winner_field(self) -> None:
        """Penalty shootout: ESPN reports tied score after ET; winner via
        ``winner`` flag. ML resolves to that flag."""
        event = _espn_event(
            status_name="STATUS_AFTER_PENALTIES",
            home_score=2,
            away_score=2,
            home_winner=True,
            home_linescores=[1, 1, 0, 0],
            away_linescores=[1, 1, 0, 0],
        )
        assert (
            canonical_outcome_for_line("soccer_usa_mls", "moneyline", "home", "", event)
            == Outcome.FAVORABLE
        )
        assert (
            canonical_outcome_for_line("soccer_usa_mls", "moneyline", "away", "", event)
            == Outcome.UNFAVORABLE
        )

    def test_after_penalties_spread_uses_ft_linescores(self) -> None:
        event = _espn_event(
            status_name="STATUS_AFTER_PENALTIES",
            home_score=2,
            away_score=2,
            home_winner=True,
            home_linescores=[1, 1, 0, 0],
            away_linescores=[1, 1, 0, 0],
        )
        # FT 2-2. Spread home +0.0 → push → Void
        assert (
            canonical_outcome_for_line("soccer_epl", "spread", "home", "+0.0", event)
            == Outcome.VOID
        )

    def test_after_extra_time_void_when_linescores_missing(self) -> None:
        """ET without linescore data → can't determine FT → VOID for spread/total."""
        event = _espn_event(
            status_name="STATUS_AFTER_EXTRA_TIME",
            home_score=3,
            away_score=2,
            # no linescores
        )
        assert (
            canonical_outcome_for_line("soccer_epl", "spread", "home", "-0.5", event)
            == Outcome.VOID
        )
        assert (
            canonical_outcome_for_line("soccer_epl", "total", "over", "2.5", event)
            == Outcome.VOID
        )
        # ML still resolves from raw score
        assert (
            canonical_outcome_for_line("soccer_epl", "moneyline", "home", "", event)
            == Outcome.FAVORABLE
        )

    def test_in_progress_returns_pending(self) -> None:
        event = _espn_event(status_name="STATUS_HALFTIME", home_score=1, away_score=0)
        assert (
            canonical_outcome_for_line("soccer_epl", "moneyline", "home", "", event)
            == Outcome.PENDING
        )


# ---------------------------------------------------------------------------
# Edge cases — postponed (7d cutoff), cancelled, void statuses
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_postponed_within_7d_returns_pending(self) -> None:
        """Postponed: PENDING until 7d after the scheduled date."""
        # Game scheduled "now" → postponed 1 day later → still PENDING
        now = time.time()
        # ISO date = scheduled time
        iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now))
        event = _espn_event(status_name="STATUS_POSTPONED", date=iso)
        assert (
            canonical_outcome_for_line(
                "basketball_nba", "moneyline", "home", "", event, now=now + 86400
            )
            == Outcome.PENDING
        )

    def test_postponed_after_7d_returns_void(self) -> None:
        """After 7 days have elapsed since scheduled date: VOID."""
        now = time.time()
        iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now))
        event = _espn_event(status_name="STATUS_POSTPONED", date=iso)
        # 8 days later → void
        assert (
            canonical_outcome_for_line(
                "basketball_nba", "moneyline", "home", "", event, now=now + 8 * 86400
            )
            == Outcome.VOID
        )

    def test_cancelled_returns_void(self) -> None:
        event = _espn_event(status_name="STATUS_CANCELED")
        assert (
            canonical_outcome_for_line("basketball_nba", "moneyline", "home", "", event)
            == Outcome.VOID
        )

    def test_abandoned_returns_void(self) -> None:
        event = _espn_event(status_name="STATUS_ABANDONED")
        assert (
            canonical_outcome_for_line("baseball_mlb", "spread", "home", "-1.5", event)
            == Outcome.VOID
        )

    def test_forfeit_returns_void(self) -> None:
        event = _espn_event(status_name="STATUS_FORFEIT")
        assert (
            canonical_outcome_for_line("americanfootball_nfl", "total", "over", "45.5", event)
            == Outcome.VOID
        )

    def test_unknown_sport_returns_pending(self) -> None:
        """Unknown sport: not in terminal-status table → PENDING."""
        event = _espn_event(status_name="STATUS_FINAL", home_score=10, away_score=8)
        assert (
            canonical_outcome_for_line("cricket_ipl", "moneyline", "home", "", event)
            == Outcome.PENDING
        )

    def test_missing_score_returns_pending(self) -> None:
        event = _espn_event(status_name="STATUS_FINAL")
        assert (
            canonical_outcome_for_line("basketball_nba", "moneyline", "home", "", event)
            == Outcome.PENDING
        )

    def test_unknown_market_returns_void(self) -> None:
        event = _espn_event(status_name="STATUS_FINAL", home_score=10, away_score=8)
        assert (
            canonical_outcome_for_line("basketball_nba", "futures", "home", "", event)
            == Outcome.VOID
        )

    def test_status_name_normalized(self) -> None:
        """Display-name and lowercase variants should normalize to canonical."""
        event_lower = _espn_event(status_name="status_final", home_score=10, away_score=8)
        event_display = _espn_event(status_name="Final", home_score=10, away_score=8)
        for evt in (event_lower, event_display):
            assert (
                canonical_outcome_for_line("basketball_nba", "moneyline", "home", "", evt)
                == Outcome.FAVORABLE
            )

    def test_tie_moneyline_returns_void(self) -> None:
        """Tied final score on moneyline → VOID (rare in NBA, possible in soccer FT)."""
        event = _espn_event(status_name="STATUS_FULL_TIME", home_score=1, away_score=1)
        assert (
            canonical_outcome_for_line("soccer_epl", "moneyline", "home", "", event)
            == Outcome.VOID
        )

    def test_invalid_line_value_returns_void(self) -> None:
        """Malformed line_value → VOID (defensive)."""
        event = _espn_event(status_name="STATUS_FINAL", home_score=10, away_score=8)
        assert (
            canonical_outcome_for_line("basketball_nba", "spread", "home", "not-a-number", event)
            == Outcome.VOID
        )


# ---------------------------------------------------------------------------
# LineKey + line_hash sanity
# ---------------------------------------------------------------------------


class TestLineKey:
    def test_canonical_string_format(self) -> None:
        lk = LineKey(
            sport="basketball_nba",
            event_id="401584293",
            market="spread",
            side="home",
            line_value="-3.5",
        )
        assert (
            lk.canonical_string()
            == "DJINN_LINE_V1|basketball_nba|401584293|spread|home|-3.5"
        )

    def test_moneyline_trailing_pipe(self) -> None:
        lk = LineKey(
            sport="basketball_nba",
            event_id="401584293",
            market="moneyline",
            side="home",
            line_value="",
        )
        assert lk.canonical_string().endswith("|moneyline|home|")

    def test_line_hash_deterministic(self) -> None:
        lk = LineKey(
            sport="basketball_nba",
            event_id="401584293",
            market="spread",
            side="home",
            line_value="-3.5",
        )
        h1 = line_hash(lk, 84532, "0x000000000000000000000000000000000000C0DE")
        h2 = line_hash(lk, 84532, "0x000000000000000000000000000000000000C0DE")
        assert h1 == h2
        assert len(h1) == 32

    def test_line_hash_chain_id_changes_hash(self) -> None:
        lk = LineKey(
            sport="basketball_nba",
            event_id="401584293",
            market="spread",
            side="home",
            line_value="-3.5",
        )
        h1 = line_hash(lk, 84532, "0x000000000000000000000000000000000000C0DE")
        h2 = line_hash(lk, 8453, "0x000000000000000000000000000000000000C0DE")
        assert h1 != h2  # chain binding works


# ---------------------------------------------------------------------------
# parsed_pick_to_line_key bridge
# ---------------------------------------------------------------------------


class TestParsedPickBridge:
    def test_spread_home_pick(self) -> None:
        pick = ParsedPick(market="spreads", team="Lakers", line=-3.5, odds=-110)
        lk = parsed_pick_to_line_key(
            pick, "basketball_nba", "401584293", "Los Angeles Lakers", "Boston Celtics"
        )
        assert lk is not None
        assert lk.market == "spread"
        assert lk.side == "home"
        assert lk.line_value == "-3.5"

    def test_spread_away_pick(self) -> None:
        pick = ParsedPick(market="spreads", team="Celtics", line=3.5, odds=-110)
        lk = parsed_pick_to_line_key(
            pick, "basketball_nba", "401584293", "Los Angeles Lakers", "Boston Celtics"
        )
        assert lk is not None
        assert lk.side == "away"
        assert lk.line_value == "+3.5"

    def test_total_over(self) -> None:
        pick = ParsedPick(market="totals", side="Over", line=215.0, odds=-110)
        lk = parsed_pick_to_line_key(
            pick, "basketball_nba", "401584293", "Los Angeles Lakers", "Boston Celtics"
        )
        assert lk is not None
        assert lk.market == "total"
        assert lk.side == "over"
        assert lk.line_value == "215.0"

    def test_moneyline(self) -> None:
        pick = ParsedPick(market="h2h", team="Lakers", odds=-150)
        lk = parsed_pick_to_line_key(
            pick, "basketball_nba", "401584293", "Los Angeles Lakers", "Boston Celtics"
        )
        assert lk is not None
        assert lk.market == "moneyline"
        assert lk.side == "home"
        assert lk.line_value == ""

    def test_unknown_team_returns_none(self) -> None:
        pick = ParsedPick(market="spreads", team="76ers", line=-3.5, odds=-110)
        lk = parsed_pick_to_line_key(
            pick, "basketball_nba", "401584293", "Lakers", "Celtics"
        )
        assert lk is None

    def test_zero_spread_canonicalized_with_plus(self) -> None:
        """Schema §1: zero-line spread is "+0.0", never "-0.0" or "0.0"."""
        pick = ParsedPick(market="spreads", team="Lakers", line=0.0, odds=-110)
        lk = parsed_pick_to_line_key(
            pick, "basketball_nba", "401584293", "Lakers", "Celtics"
        )
        assert lk is not None
        assert lk.line_value == "+0.0"

    def test_canonicalize_line_value_total_unsigned(self) -> None:
        assert _canonicalize_line_value(220.5, "total") == "220.5"
        assert _canonicalize_line_value(8.0, "total") == "8.0"

    def test_canonicalize_line_value_spread_signed(self) -> None:
        assert _canonicalize_line_value(-3.5, "spread") == "-3.5"
        assert _canonicalize_line_value(7.5, "spread") == "+7.5"
        assert _canonicalize_line_value(0.0, "spread") == "+0.0"


# ---------------------------------------------------------------------------
# OutcomeAttestor line-keyed storage (Phase 2b dual-resolve)
# ---------------------------------------------------------------------------


class TestLineKeyedStorage:
    """Verify _line_resolutions populates correctly from resolve_signal."""

    def test_no_population_without_chain_config(self) -> None:
        """Without chain_id/registry_address, line-keyed storage stays empty."""
        attestor = OutcomeAttestor()
        # No chain config → _line_resolutions stays empty regardless
        assert attestor._chain_id is None or attestor._registry_address is None
        assert attestor._line_resolutions == {}

    def test_construction_with_chain_config(self) -> None:
        attestor = OutcomeAttestor(
            chain_id=84532,
            registry_address="0x000000000000000000000000000000000000C0DE",
        )
        assert attestor._chain_id == 84532
        assert attestor._registry_address == "0x000000000000000000000000000000000000C0DE"
        assert attestor._line_resolutions == {}

    def test_get_line_resolution_returns_none_for_unknown_hash(self) -> None:
        attestor = OutcomeAttestor()
        assert attestor.get_line_resolution(b"\x00" * 32) is None

    def test_iter_line_resolutions_sorted_empty(self) -> None:
        attestor = OutcomeAttestor()
        assert attestor.iter_line_resolutions_sorted() == []

    def test_iter_line_resolutions_sorted_returns_ordered(self) -> None:
        """Privacy §11: iteration must be in sorted-lineHash order regardless
        of insertion order."""
        attestor = OutcomeAttestor()
        # Manually inject two resolutions with deliberately out-of-order hashes
        lk1 = LineKey("basketball_nba", "evt1", "moneyline", "home", "")
        lk2 = LineKey("basketball_nba", "evt2", "moneyline", "home", "")
        h1 = b"\xff" + b"\x00" * 31  # high hash
        h2 = b"\x00" + b"\xff" * 31  # low hash
        attestor._line_resolutions[h1] = LineResolution(
            line_key=lk1, outcome=Outcome.FAVORABLE,
            home_score=1, away_score=0, espn_status="STATUS_FINAL",
            resolved_at=100.0,
        )
        attestor._line_resolutions[h2] = LineResolution(
            line_key=lk2, outcome=Outcome.FAVORABLE,
            home_score=2, away_score=1, espn_status="STATUS_FINAL",
            resolved_at=200.0,
        )
        ordered = attestor.iter_line_resolutions_sorted()
        assert [k for k, _ in ordered] == [h2, h1]


class TestPopulateLineResolutionsFromESPN:
    """End-to-end: resolve_signal populates _line_resolutions when chain
    config is set and ESPN raw_data is available.
    """

    @pytest.mark.asyncio
    async def test_resolve_signal_populates_line_resolutions(self) -> None:
        from unittest.mock import AsyncMock

        from djinn_validator.core.espn import ESPNClient, ESPNGame

        # Frozen ESPN payload that canonical_outcome_for_line will accept.
        raw = _espn_event(status_name="STATUS_FINAL", home_score=110, away_score=105)
        game = ESPNGame(
            espn_id="evt1",
            home_team="Lakers",
            away_team="Celtics",
            home_score=110,
            away_score=105,
            status="final",
            raw_data=raw,
        )
        espn = AsyncMock(spec=ESPNClient)
        espn.get_scoreboard = AsyncMock(return_value=[game])
        espn.close = AsyncMock()

        attestor = OutcomeAttestor(
            espn_client=espn,
            chain_id=84532,
            registry_address="0x000000000000000000000000000000000000C0DE",
        )
        meta = SignalMetadata(
            signal_id="sig1",
            sport="basketball_nba",
            event_id="401584293",
            home_team="Lakers",
            away_team="Celtics",
            lines=[
                ParsedPick(market="spreads", team="Lakers", line=-3.5, odds=-110),
                ParsedPick(market="totals", side="Over", line=210.5, odds=-110),
            ],
        )
        attestor.register_signal(meta)
        result = await attestor.resolve_signal("sig1", "v1")
        assert result == "sig1"

        # Both lines should have populated _line_resolutions.
        assert len(attestor._line_resolutions) == 2

        # Lookup by lineHash works.
        lk_spread = LineKey(
            sport="basketball_nba",
            event_id="401584293",
            market="spread",
            side="home",
            line_value="-3.5",
        )
        h_spread = line_hash(lk_spread, 84532, "0x000000000000000000000000000000000000C0DE")
        res = attestor.get_line_resolution(h_spread)
        assert res is not None
        assert res.outcome == Outcome.FAVORABLE
        assert res.home_score == 110
        assert res.away_score == 105
        assert res.espn_status == "STATUS_FINAL"

    @pytest.mark.asyncio
    async def test_two_signals_share_line_resolution_row(self) -> None:
        """v1747 core promise: 100 signals containing 'Lakers -3.5' share
        one resolution row keyed by lineHash."""
        from unittest.mock import AsyncMock

        from djinn_validator.core.espn import ESPNClient, ESPNGame

        raw = _espn_event(status_name="STATUS_FINAL", home_score=110, away_score=105)
        game = ESPNGame(
            espn_id="evt1",
            home_team="Lakers",
            away_team="Celtics",
            home_score=110,
            away_score=105,
            status="final",
            raw_data=raw,
        )
        espn = AsyncMock(spec=ESPNClient)
        espn.get_scoreboard = AsyncMock(return_value=[game])
        espn.close = AsyncMock()

        attestor = OutcomeAttestor(
            espn_client=espn,
            chain_id=84532,
            registry_address="0x000000000000000000000000000000000000C0DE",
        )
        # Two signals with overlapping lines (one shared, two unique).
        for sid in ("sig-A", "sig-B"):
            meta = SignalMetadata(
                signal_id=sid,
                sport="basketball_nba",
                event_id="401584293",
                home_team="Lakers",
                away_team="Celtics",
                lines=[
                    # shared line — same canonical key in both signals
                    ParsedPick(market="spreads", team="Lakers", line=-3.5, odds=-110),
                    # unique-per-signal line
                    ParsedPick(
                        market="totals",
                        side="Over",
                        line=200.5 if sid == "sig-A" else 215.5,
                        odds=-110,
                    ),
                ],
            )
            attestor.register_signal(meta)
            await attestor.resolve_signal(sid, "v1")

        # 3 unique lineHashes total: 1 shared spread + 2 unique totals.
        assert len(attestor._line_resolutions) == 3

    @pytest.mark.asyncio
    async def test_population_skipped_when_raw_data_missing(self) -> None:
        """When ESPN mock returns ESPNGame without raw_data, line-keyed
        storage stays empty. Legacy meta.outcomes still populates."""
        from unittest.mock import AsyncMock

        from djinn_validator.core.espn import ESPNClient, ESPNGame

        # No raw_data on the mock game
        game = ESPNGame(
            espn_id="evt1",
            home_team="Lakers",
            away_team="Celtics",
            home_score=110,
            away_score=105,
            status="final",
        )
        espn = AsyncMock(spec=ESPNClient)
        espn.get_scoreboard = AsyncMock(return_value=[game])
        espn.close = AsyncMock()

        attestor = OutcomeAttestor(
            espn_client=espn,
            chain_id=84532,
            registry_address="0x000000000000000000000000000000000000C0DE",
        )
        meta = SignalMetadata(
            signal_id="sig1",
            sport="basketball_nba",
            event_id="401584293",
            home_team="Lakers",
            away_team="Celtics",
            lines=[ParsedPick(market="spreads", team="Lakers", line=-3.5, odds=-110)],
        )
        attestor.register_signal(meta)
        result = await attestor.resolve_signal("sig1", "v1")
        # Legacy path still works
        assert result == "sig1"
        assert meta.outcomes is not None
        # Line-keyed path skipped (no raw_data)
        assert attestor._line_resolutions == {}
