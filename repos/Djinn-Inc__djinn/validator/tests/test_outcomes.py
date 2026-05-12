"""Tests for outcome attestation — pick parsing, outcome determination, and resolution."""

from __future__ import annotations

import time
from unittest.mock import AsyncMock

import pytest

from djinn_validator.core.espn import ESPNClient, ESPNGame
from djinn_validator.core.outcomes import (
    SUPPORTED_SPORTS,
    EventResult,
    Outcome,
    OutcomeAttestor,
    ParsedPick,
    SignalMetadata,
    _team_matches,
    determine_all_outcomes,
    determine_outcome,
    parse_pick,
)


# 10 representative decoy lines (mix of spreads, totals, h2h)
SAMPLE_LINES: list[str] = [
    "Lakers -3.5 (-110)",
    "Celtics +3.5 (-110)",
    "Over 218.5 (-110)",
    "Under 218.5 (-110)",
    "Lakers ML (-150)",
    "Celtics ML (+130)",
    "Lakers -1.5 (-105)",
    "Celtics +1.5 (-115)",
    "Over 215.0 (-110)",
    "Under 215.0 (-110)",
]
SAMPLE_PARSED = [parse_pick(l) for l in SAMPLE_LINES]


# ---------------------------------------------------------------------------
# Pick Parsing
# ---------------------------------------------------------------------------


class TestParsePick:
    def test_spread_favorite(self) -> None:
        pick = parse_pick("Lakers -3.5 (-110)")
        assert pick.market == "spreads"
        assert pick.team == "Lakers"
        assert pick.line == -3.5
        assert pick.odds == -110

    def test_spread_underdog(self) -> None:
        pick = parse_pick("Celtics +5.5 (-110)")
        assert pick.market == "spreads"
        assert pick.team == "Celtics"
        assert pick.line == 5.5
        assert pick.odds == -110

    def test_spread_pk(self) -> None:
        pick = parse_pick("Warriors 0 (-105)")
        assert pick.market == "spreads"
        assert pick.team == "Warriors"
        assert pick.line == 0.0

    def test_total_over(self) -> None:
        pick = parse_pick("Over 218.5 (-110)")
        assert pick.market == "totals"
        assert pick.side == "Over"
        assert pick.line == 218.5
        assert pick.odds == -110

    def test_total_under(self) -> None:
        pick = parse_pick("Under 210.0 (-115)")
        assert pick.market == "totals"
        assert pick.side == "Under"
        assert pick.line == 210.0
        assert pick.odds == -115

    def test_moneyline(self) -> None:
        pick = parse_pick("Celtics ML (-150)")
        assert pick.market == "h2h"
        assert pick.team == "Celtics"
        assert pick.odds == -150

    def test_moneyline_plus(self) -> None:
        pick = parse_pick("Knicks ML (+200)")
        assert pick.market == "h2h"
        assert pick.team == "Knicks"
        assert pick.odds == 200

    def test_fallback_unknown_format(self) -> None:
        pick = parse_pick("Some Weird Pick")
        assert pick.market == "h2h"
        assert pick.team == "Some Weird Pick"


# ---------------------------------------------------------------------------
# Team Matching
# ---------------------------------------------------------------------------


class TestTeamMatches:
    def test_exact_match(self) -> None:
        assert _team_matches("Los Angeles Lakers", "Los Angeles Lakers")

    def test_mascot_match(self) -> None:
        assert _team_matches("Lakers", "Los Angeles Lakers")

    def test_city_match(self) -> None:
        assert _team_matches("Los Angeles", "Los Angeles Lakers")

    def test_no_match(self) -> None:
        assert not _team_matches("Celtics", "Los Angeles Lakers")

    def test_case_insensitive(self) -> None:
        assert _team_matches("lakers", "Los Angeles Lakers")


# ---------------------------------------------------------------------------
# Outcome Determination — Spreads
# ---------------------------------------------------------------------------


class TestDetermineSpread:
    def _result(self, home: int, away: int) -> EventResult:
        return EventResult(event_id="test", home_score=home, away_score=away, status="final")

    def test_favorite_covers(self) -> None:
        pick = ParsedPick(market="spreads", team="Lakers", line=-3.5, odds=-110)
        # Lakers 110, Celtics 105 → Lakers won by 5, covers -3.5
        result = determine_outcome(pick, self._result(110, 105), "Lakers", "Celtics")
        assert result == Outcome.FAVORABLE

    def test_favorite_fails_to_cover(self) -> None:
        pick = ParsedPick(market="spreads", team="Lakers", line=-7.5, odds=-110)
        # Lakers 110, Celtics 105 → Lakers won by 5, doesn't cover -7.5
        result = determine_outcome(pick, self._result(110, 105), "Lakers", "Celtics")
        assert result == Outcome.UNFAVORABLE

    def test_underdog_covers(self) -> None:
        pick = ParsedPick(market="spreads", team="Celtics", line=5.5, odds=-110)
        # Lakers 110, Celtics 105 → Celtics lost by 5, covered +5.5
        result = determine_outcome(pick, self._result(110, 105), "Lakers", "Celtics")
        assert result == Outcome.FAVORABLE

    def test_underdog_fails(self) -> None:
        pick = ParsedPick(market="spreads", team="Celtics", line=3.5, odds=-110)
        # Lakers 110, Celtics 105 → Celtics lost by 5, didn't cover +3.5
        result = determine_outcome(pick, self._result(110, 105), "Lakers", "Celtics")
        assert result == Outcome.UNFAVORABLE

    def test_push(self) -> None:
        pick = ParsedPick(market="spreads", team="Lakers", line=-5.0, odds=-110)
        # Lakers 110, Celtics 105 → won by exactly 5, push
        result = determine_outcome(pick, self._result(110, 105), "Lakers", "Celtics")
        assert result == Outcome.VOID

    def test_away_team_spread(self) -> None:
        pick = ParsedPick(market="spreads", team="Celtics", line=-2.0, odds=-110)
        # Lakers 100, Celtics 105 → Celtics won by 5, covers -2.0
        result = determine_outcome(pick, self._result(100, 105), "Lakers", "Celtics")
        assert result == Outcome.FAVORABLE


# ---------------------------------------------------------------------------
# Outcome Determination — Totals
# ---------------------------------------------------------------------------


class TestDetermineTotal:
    def _result(self, home: int, away: int) -> EventResult:
        return EventResult(event_id="test", home_score=home, away_score=away, status="final")

    def test_over_hits(self) -> None:
        pick = ParsedPick(market="totals", side="Over", line=210.5, odds=-110)
        # 110 + 105 = 215 > 210.5
        result = determine_outcome(pick, self._result(110, 105), "Lakers", "Celtics")
        assert result == Outcome.FAVORABLE

    def test_over_misses(self) -> None:
        pick = ParsedPick(market="totals", side="Over", line=220.5, odds=-110)
        # 110 + 105 = 215 < 220.5
        result = determine_outcome(pick, self._result(110, 105), "Lakers", "Celtics")
        assert result == Outcome.UNFAVORABLE

    def test_under_hits(self) -> None:
        pick = ParsedPick(market="totals", side="Under", line=220.5, odds=-110)
        # 110 + 105 = 215 < 220.5
        result = determine_outcome(pick, self._result(110, 105), "Lakers", "Celtics")
        assert result == Outcome.FAVORABLE

    def test_under_misses(self) -> None:
        pick = ParsedPick(market="totals", side="Under", line=210.5, odds=-110)
        # 110 + 105 = 215 > 210.5
        result = determine_outcome(pick, self._result(110, 105), "Lakers", "Celtics")
        assert result == Outcome.UNFAVORABLE

    def test_push(self) -> None:
        pick = ParsedPick(market="totals", side="Over", line=215.0, odds=-110)
        # 110 + 105 = 215 == 215.0
        result = determine_outcome(pick, self._result(110, 105), "Lakers", "Celtics")
        assert result == Outcome.VOID


# ---------------------------------------------------------------------------
# Outcome Determination — H2H
# ---------------------------------------------------------------------------


class TestDetermineH2H:
    def _result(self, home: int, away: int) -> EventResult:
        return EventResult(event_id="test", home_score=home, away_score=away, status="final")

    def test_home_win_pick_home(self) -> None:
        pick = ParsedPick(market="h2h", team="Lakers", odds=-150)
        result = determine_outcome(pick, self._result(110, 105), "Lakers", "Celtics")
        assert result == Outcome.FAVORABLE

    def test_home_win_pick_away(self) -> None:
        pick = ParsedPick(market="h2h", team="Celtics", odds=200)
        result = determine_outcome(pick, self._result(110, 105), "Lakers", "Celtics")
        assert result == Outcome.UNFAVORABLE

    def test_away_win_pick_away(self) -> None:
        pick = ParsedPick(market="h2h", team="Celtics", odds=-130)
        result = determine_outcome(pick, self._result(100, 105), "Lakers", "Celtics")
        assert result == Outcome.FAVORABLE

    def test_tie(self) -> None:
        pick = ParsedPick(market="h2h", team="Lakers", odds=-110)
        result = determine_outcome(pick, self._result(105, 105), "Lakers", "Celtics")
        assert result == Outcome.VOID


# ---------------------------------------------------------------------------
# Edge Cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_postponed_game(self) -> None:
        pick = ParsedPick(market="spreads", team="Lakers", line=-3.5, odds=-110)
        result = EventResult(event_id="test", status="postponed")
        assert determine_outcome(pick, result, "Lakers", "Celtics") == Outcome.VOID

    def test_cancelled_game(self) -> None:
        pick = ParsedPick(market="h2h", team="Lakers", odds=-110)
        result = EventResult(event_id="test", status="cancelled")
        assert determine_outcome(pick, result, "Lakers", "Celtics") == Outcome.VOID

    def test_pending_game(self) -> None:
        pick = ParsedPick(market="h2h", team="Lakers", odds=-110)
        result = EventResult(event_id="test", status="pending")
        assert determine_outcome(pick, result, "Lakers", "Celtics") == Outcome.PENDING

    def test_team_not_found(self) -> None:
        pick = ParsedPick(market="spreads", team="76ers", line=-3.5, odds=-110)
        result = EventResult(event_id="test", home_score=110, away_score=105, status="final")
        assert determine_outcome(pick, result, "Lakers", "Celtics") == Outcome.VOID

    def test_missing_scores(self) -> None:
        pick = ParsedPick(market="h2h", team="Lakers", odds=-110)
        result = EventResult(event_id="test", status="final")  # no scores
        assert determine_outcome(pick, result, "Lakers", "Celtics") == Outcome.PENDING

    def test_spread_none_line(self) -> None:
        """Spread with no line should return VOID."""
        pick = ParsedPick(market="spreads", team="Lakers", line=None, odds=-110)
        result = EventResult(event_id="test", home_score=110, away_score=105, status="final")
        assert determine_outcome(pick, result, "Lakers", "Celtics") == Outcome.VOID

    def test_total_none_line(self) -> None:
        """Total with no line should return VOID."""
        pick = ParsedPick(market="totals", side="Over", line=None, odds=-110)
        result = EventResult(event_id="test", home_score=110, away_score=105, status="final")
        assert determine_outcome(pick, result, "Lakers", "Celtics") == Outcome.VOID

    def test_unknown_market(self) -> None:
        """Unknown market type returns PENDING."""
        pick = ParsedPick(market="unknown", team="Lakers")
        result = EventResult(event_id="test", home_score=110, away_score=105, status="final")
        assert determine_outcome(pick, result, "Lakers", "Celtics") == Outcome.PENDING


# ---------------------------------------------------------------------------
# Blind Resolution: determine_all_outcomes
# ---------------------------------------------------------------------------


class TestDetermineAllOutcomes:
    def _result(self, home: int, away: int) -> EventResult:
        return EventResult(event_id="test", home_score=home, away_score=away, status="final")

    def test_returns_10_outcomes(self) -> None:
        result = self._result(110, 105)
        outcomes = determine_all_outcomes(SAMPLE_PARSED, result, "Lakers", "Celtics")
        assert len(outcomes) == 10
        assert all(isinstance(o, Outcome) for o in outcomes)

    def test_each_outcome_correct(self) -> None:
        """Each outcome matches what determine_outcome would return individually."""
        result = self._result(110, 105)
        outcomes = determine_all_outcomes(SAMPLE_PARSED, result, "Lakers", "Celtics")
        for i, parsed in enumerate(SAMPLE_PARSED):
            expected = determine_outcome(parsed, result, "Lakers", "Celtics")
            assert outcomes[i] == expected, f"Line {i}: {outcomes[i]} != {expected}"

    def test_pending_game_returns_all_pending(self) -> None:
        result = EventResult(event_id="test", status="pending")
        outcomes = determine_all_outcomes(SAMPLE_PARSED, result, "Lakers", "Celtics")
        assert all(o == Outcome.PENDING for o in outcomes)


# ---------------------------------------------------------------------------
# OutcomeAttestor
# ---------------------------------------------------------------------------


def _mock_espn_client(
    game: ESPNGame | None = None,
) -> ESPNClient:
    """Create a mock ESPN client that returns a specific game."""
    mock = AsyncMock(spec=ESPNClient)
    mock.get_game_by_teams = AsyncMock(return_value=game)
    mock.get_scoreboard = AsyncMock(return_value=[game] if game else [])
    mock.close = AsyncMock()
    return mock


class TestOutcomeAttestor:
    def test_register_and_get_pending(self) -> None:
        attestor = OutcomeAttestor()
        meta = SignalMetadata(
            signal_id="sig1",
            sport="basketball_nba",
            event_id="evt1",
            home_team="Lakers",
            away_team="Celtics",
            lines=SAMPLE_PARSED,
        )
        attestor.register_signal(meta)
        pending = attestor.get_pending_signals()
        assert len(pending) == 1
        assert pending[0].signal_id == "sig1"

    def test_attest_and_consensus(self) -> None:
        attestor = OutcomeAttestor()
        result = EventResult(event_id="evt1", home_score=110, away_score=105, status="final")

        # 3 validators, ≥2/3 quorum → threshold = ceil(3*2/3) = 2
        attestor.attest("sig1", "v1", Outcome.FAVORABLE, result)
        assert attestor.check_consensus("sig1", 3) is None  # 1 < 2

        attestor.attest("sig1", "v2", Outcome.FAVORABLE, result)
        assert attestor.check_consensus("sig1", 3) == Outcome.FAVORABLE  # 2 >= 2

    def test_consensus_zero_validators(self) -> None:
        attestor = OutcomeAttestor()
        result = EventResult(event_id="evt1", home_score=110, away_score=105, status="final")
        attestor.attest("sig1", "v1", Outcome.FAVORABLE, result)
        # Zero validators — should return None, not crash
        assert attestor.check_consensus("sig1", 0) is None

    def test_consensus_disagreement(self) -> None:
        attestor = OutcomeAttestor()
        result = EventResult(event_id="evt1", home_score=110, away_score=105, status="final")

        attestor.attest("sig1", "v1", Outcome.FAVORABLE, result)
        attestor.attest("sig1", "v2", Outcome.UNFAVORABLE, result)
        attestor.attest("sig1", "v3", Outcome.FAVORABLE, result)
        # 2 favorable, 1 unfavorable — threshold for 3 is 2, so consensus reached
        assert attestor.check_consensus("sig1", 3) == Outcome.FAVORABLE

    @pytest.mark.asyncio
    async def test_resolve_signal_with_espn_final(self) -> None:
        """Signal resolves when ESPN returns a final game — stores outcomes."""
        game = ESPNGame(
            espn_id="1",
            home_team="Lakers",
            away_team="Celtics",
            home_score=110,
            away_score=105,
            status="final",
        )
        espn = _mock_espn_client(game)
        attestor = OutcomeAttestor(espn_client=espn)
        meta = SignalMetadata(
            signal_id="sig1",
            sport="basketball_nba",
            event_id="evt1",
            home_team="Lakers",
            away_team="Celtics",
            lines=SAMPLE_PARSED,
        )
        attestor.register_signal(meta)
        result = await attestor.resolve_signal("sig1", "v1")
        assert result == "sig1"
        assert meta.resolved
        assert meta.outcomes is not None
        assert len(meta.outcomes) == 10

    @pytest.mark.asyncio
    async def test_resolve_signal_pending_game(self) -> None:
        """Signal stays pending when ESPN returns an in-progress game."""
        game = ESPNGame(
            espn_id="1",
            home_team="Lakers",
            away_team="Celtics",
            home_score=55,
            away_score=50,
            status="in_progress",
        )
        espn = _mock_espn_client(game)
        attestor = OutcomeAttestor(espn_client=espn)
        meta = SignalMetadata(
            signal_id="sig1",
            sport="basketball_nba",
            event_id="evt1",
            home_team="Lakers",
            away_team="Celtics",
            lines=SAMPLE_PARSED,
        )
        attestor.register_signal(meta)
        result = await attestor.resolve_signal("sig1", "v1")
        assert result is None
        assert not meta.resolved

    @pytest.mark.asyncio
    async def test_resolve_signal_game_not_found(self) -> None:
        """Signal stays pending when ESPN doesn't have the game."""
        espn = _mock_espn_client(None)
        attestor = OutcomeAttestor(espn_client=espn)
        meta = SignalMetadata(
            signal_id="sig1",
            sport="basketball_nba",
            event_id="evt1",
            home_team="Lakers",
            away_team="Celtics",
            lines=SAMPLE_PARSED,
        )
        attestor.register_signal(meta)
        result = await attestor.resolve_signal("sig1", "v1")
        assert result is None

    @pytest.mark.asyncio
    async def test_cleanup_resolved_removes_old_signals(self) -> None:
        attestor = OutcomeAttestor()
        meta = SignalMetadata(
            signal_id="sig1",
            sport="basketball_nba",
            event_id="evt1",
            home_team="Lakers",
            away_team="Celtics",
            lines=SAMPLE_PARSED,
            purchased_at=0.0,  # Very old timestamp
        )
        meta.resolved = True
        attestor.register_signal(meta)

        # Also add an attestation so we verify it gets cleaned too
        result = EventResult(event_id="evt1", home_score=110, away_score=105, status="final")
        attestor.attest("sig1", "v1", Outcome.FAVORABLE, result)

        removed = await attestor.cleanup_resolved(max_age_seconds=1)
        assert removed == 1
        assert attestor.get_pending_signals() == []
        assert attestor.check_consensus("sig1", 3) is None  # Attestations gone too

    @pytest.mark.asyncio
    async def test_cleanup_resolved_keeps_recent(self) -> None:
        attestor = OutcomeAttestor()
        meta = SignalMetadata(
            signal_id="sig1",
            sport="basketball_nba",
            event_id="evt1",
            home_team="Lakers",
            away_team="Celtics",
            lines=SAMPLE_PARSED,
        )
        meta.resolved = True
        attestor.register_signal(meta)

        removed = await attestor.cleanup_resolved(max_age_seconds=86400)
        assert removed == 0  # Still recent, not cleaned

    @pytest.mark.asyncio
    async def test_cleanup_resolved_ignores_unresolved(self) -> None:
        attestor = OutcomeAttestor()
        meta = SignalMetadata(
            signal_id="sig1",
            sport="basketball_nba",
            event_id="evt1",
            home_team="Lakers",
            away_team="Celtics",
            lines=SAMPLE_PARSED,
            purchased_at=0.0,  # Very old
        )
        # Not resolved — should not be cleaned even if old
        attestor.register_signal(meta)

        removed = await attestor.cleanup_resolved(max_age_seconds=1)
        assert removed == 0

    @pytest.mark.asyncio
    async def test_cleanup_resolved_skips_protected_signals(self) -> None:
        """v1620 invariant: a resolved+old signal must NOT be cleaned if it's
        still referenced by an unsettled audit_set (passed via protected_ids).
        Pre-v1620 this signal would have been wiped → MPC abstains forever.
        """
        attestor = OutcomeAttestor()
        meta = SignalMetadata(
            signal_id="sig_protected",
            sport="basketball_nba",
            event_id="evt1",
            home_team="Lakers",
            away_team="Celtics",
            lines=SAMPLE_PARSED,
            purchased_at=0.0,  # Very old (would normally be wiped)
        )
        meta.resolved = True
        attestor.register_signal(meta)

        # Caller (main.py) passes protected_ids derived from
        # audit_set_store.protected_signal_ids(). Simulate that here.
        removed = await attestor.cleanup_resolved(
            max_age_seconds=1,
            protected_ids={"sig_protected"},
        )
        assert removed == 0, "Protected signal must survive cleanup"
        # Use the internal store directly — get_pending_signals() filters to
        # unresolved which would exclude our resolved-and-protected signal.
        assert "sig_protected" in attestor._pending_signals, (
            "outcome metadata must remain available for MPC at settle time"
        )

    @pytest.mark.asyncio
    async def test_cleanup_resolved_cleans_unprotected_neighbors(self) -> None:
        """v1620: protected_ids only shields THE listed signals. Other
        resolved+old signals in the same store still get cleaned normally
        (memory bound is preserved)."""
        attestor = OutcomeAttestor()
        for sid in ("sig_keep", "sig_drop"):
            meta = SignalMetadata(
                signal_id=sid,
                sport="basketball_nba",
                event_id="evt1",
                home_team="Lakers",
                away_team="Celtics",
                lines=SAMPLE_PARSED,
                purchased_at=0.0,
            )
            meta.resolved = True
            attestor.register_signal(meta)

        removed = await attestor.cleanup_resolved(
            max_age_seconds=1,
            protected_ids={"sig_keep"},
        )
        assert removed == 1, "Exactly the unprotected old signal should clean"
        remaining = set(attestor._pending_signals.keys())
        assert remaining == {"sig_keep"}

    def test_consensus_threshold_rounding(self) -> None:
        """Threshold = ceil(n * 2/3). For n=3: ceil(2.0) = 2."""
        attestor = OutcomeAttestor()
        result = EventResult(event_id="evt1", status="final", home_score=100, away_score=90)

        # With 3 validators, threshold is ceil(3*2/3) = 2 → need 2/3
        attestor.attest("sig1", "v1", Outcome.FAVORABLE, result)
        assert attestor.check_consensus("sig1", 3) is None  # 1 < 2
        attestor.attest("sig1", "v2", Outcome.FAVORABLE, result)
        assert attestor.check_consensus("sig1", 3) == Outcome.FAVORABLE  # 2 >= 2

    def test_consensus_with_4_validators(self) -> None:
        """For n=4: ceil(4*2/3) = ceil(2.66) = 3 → need 3 of 4."""
        attestor = OutcomeAttestor()
        result = EventResult(event_id="evt1", status="final", home_score=100, away_score=90)

        attestor.attest("sig1", "v1", Outcome.FAVORABLE, result)
        attestor.attest("sig1", "v2", Outcome.FAVORABLE, result)
        assert attestor.check_consensus("sig1", 4) is None  # 2 < 3
        attestor.attest("sig1", "v3", Outcome.FAVORABLE, result)
        assert attestor.check_consensus("sig1", 4) == Outcome.FAVORABLE  # 3 >= 3

    def test_consensus_negative_validators(self) -> None:
        """Negative validator count should not crash."""
        attestor = OutcomeAttestor()
        result = EventResult(event_id="evt1", status="final", home_score=100, away_score=90)
        attestor.attest("sig1", "v1", Outcome.FAVORABLE, result)
        assert attestor.check_consensus("sig1", -1) is None

    @pytest.mark.asyncio
    async def test_resolve_unregistered_signal(self) -> None:
        """Resolving a signal that was never registered returns None."""
        attestor = OutcomeAttestor()
        result = await attestor.resolve_signal("nonexistent", "v1")
        assert result is None

    @pytest.mark.asyncio
    async def test_resolve_already_resolved(self) -> None:
        """Resolving an already-resolved signal returns None."""
        attestor = OutcomeAttestor()
        meta = SignalMetadata(
            signal_id="sig1",
            sport="basketball_nba",
            event_id="evt1",
            home_team="Lakers",
            away_team="Celtics",
            lines=SAMPLE_PARSED,
        )
        meta.resolved = True
        attestor.register_signal(meta)
        result = await attestor.resolve_signal("sig1", "v1")
        assert result is None

    @pytest.mark.asyncio
    async def test_close(self) -> None:
        attestor = OutcomeAttestor()
        await attestor.close()  # Should not raise

    @pytest.mark.asyncio
    async def test_resolve_all_pending_no_games(self) -> None:
        """resolve_all returns empty when ESPN has no matching games."""
        espn = _mock_espn_client(None)
        attestor = OutcomeAttestor(espn_client=espn)
        for i in range(3):
            meta = SignalMetadata(
                signal_id=f"sig-{i}",
                sport="basketball_nba",
                event_id=f"evt-{i}",
                home_team="Lakers",
                away_team="Celtics",
                lines=SAMPLE_PARSED,
            )
            attestor.register_signal(meta)

        resolved = await attestor.resolve_all_pending("v1")
        assert resolved == []
        assert len(attestor.get_pending_signals()) == 3

    def test_consensus_split_vote_no_consensus(self) -> None:
        """3-way split: no outcome reaches threshold."""
        attestor = OutcomeAttestor()
        result = EventResult(event_id="evt1", status="final", home_score=100, away_score=90)

        attestor.attest("sig1", "v1", Outcome.FAVORABLE, result)
        attestor.attest("sig1", "v2", Outcome.UNFAVORABLE, result)
        attestor.attest("sig1", "v3", Outcome.VOID, result)

        assert attestor.check_consensus("sig1", 3) is None

    def test_consensus_no_attestations(self) -> None:
        """Signal with no attestations returns None."""
        attestor = OutcomeAttestor()
        assert attestor.check_consensus("nonexistent", 10) is None

    def test_register_duplicate_rejects_overwrite_by_default(self) -> None:
        """v1724: re-registering same signal_id with DIFFERENT metadata is
        rejected by default. Idempotent re-registration with identical fields
        returns "duplicate". allow_overwrite=True bypasses for trusted paths."""
        attestor = OutcomeAttestor()
        meta1 = SignalMetadata(
            signal_id="sig1",
            sport="basketball_nba",
            event_id="evt1",
            home_team="Lakers",
            away_team="Celtics",
            lines=SAMPLE_PARSED,
        )
        meta2 = SignalMetadata(
            signal_id="sig1",
            sport="americanfootball_nfl",
            event_id="evt2",
            home_team="Chiefs",
            away_team="Bills",
            lines=SAMPLE_PARSED,
        )
        assert attestor.register_signal(meta1) == "added"
        # Different fields → rejected
        assert attestor.register_signal(meta2) == "overwrite_rejected"
        pending = attestor.get_pending_signals()
        assert len(pending) == 1
        assert pending[0].sport == "basketball_nba", "first-writer-wins"

        # Idempotent re-register with identical fields → duplicate (no-op)
        assert attestor.register_signal(meta1) == "duplicate"

        # allow_overwrite=True (validator-hotkey-signed path) → overwrites
        assert attestor.register_signal(meta2, allow_overwrite=True) == "added"
        pending = attestor.get_pending_signals()
        assert pending[0].sport == "americanfootball_nfl"

    @pytest.mark.asyncio
    async def test_cleanup_multiple_resolved(self) -> None:
        """Cleanup removes all old resolved signals."""
        attestor = OutcomeAttestor()
        for i in range(5):
            meta = SignalMetadata(
                signal_id=f"sig-{i}",
                sport="basketball_nba",
                event_id=f"evt-{i}",
                home_team="A",
                away_team="B",
                lines=SAMPLE_PARSED,
                purchased_at=0.0,
            )
            meta.resolved = True
            attestor.register_signal(meta)

        removed = await attestor.cleanup_resolved(max_age_seconds=1)
        assert removed == 5
        assert attestor.get_pending_signals() == []


# ---------------------------------------------------------------------------
# fetch_event_result via ESPN
# ---------------------------------------------------------------------------


class TestFetchEventResultESPN:
    """Tests for fetch_event_result using ESPN backend."""

    @pytest.mark.asyncio
    async def test_final_game_returns_scores(self) -> None:
        game = ESPNGame(
            espn_id="1",
            home_team="Los Angeles Lakers",
            away_team="Boston Celtics",
            home_score=115,
            away_score=108,
            status="final",
        )
        espn = _mock_espn_client(game)
        attestor = OutcomeAttestor(espn_client=espn)

        result = await attestor.fetch_event_result(
            "evt1",
            "basketball_nba",
            home_team="Lakers",
            away_team="Celtics",
        )

        assert result.status == "final"
        assert result.home_team == "Los Angeles Lakers"
        assert result.away_team == "Boston Celtics"
        assert result.home_score == 115
        assert result.away_score == 108

    @pytest.mark.asyncio
    async def test_pending_game(self) -> None:
        game = ESPNGame(
            espn_id="1",
            home_team="Lakers",
            away_team="Celtics",
            status="in_progress",
        )
        espn = _mock_espn_client(game)
        attestor = OutcomeAttestor(espn_client=espn)

        result = await attestor.fetch_event_result(
            "evt1",
            "basketball_nba",
            home_team="Lakers",
            away_team="Celtics",
        )

        assert result.status == "pending"

    @pytest.mark.asyncio
    async def test_postponed_game(self) -> None:
        game = ESPNGame(
            espn_id="1",
            home_team="Lakers",
            away_team="Celtics",
            status="postponed",
        )
        espn = _mock_espn_client(game)
        attestor = OutcomeAttestor(espn_client=espn)

        result = await attestor.fetch_event_result(
            "evt1",
            "basketball_nba",
            home_team="Lakers",
            away_team="Celtics",
        )

        assert result.status == "postponed"

    @pytest.mark.asyncio
    async def test_cancelled_game(self) -> None:
        game = ESPNGame(
            espn_id="1",
            home_team="Lakers",
            away_team="Celtics",
            status="cancelled",
        )
        espn = _mock_espn_client(game)
        attestor = OutcomeAttestor(espn_client=espn)

        result = await attestor.fetch_event_result(
            "evt1",
            "basketball_nba",
            home_team="Lakers",
            away_team="Celtics",
        )

        assert result.status == "cancelled"

    @pytest.mark.asyncio
    async def test_game_not_found(self) -> None:
        espn = _mock_espn_client(None)
        attestor = OutcomeAttestor(espn_client=espn)

        result = await attestor.fetch_event_result(
            "evt1",
            "basketball_nba",
            home_team="Bulls",
            away_team="Heat",
        )

        assert result.status == "pending"

    @pytest.mark.asyncio
    async def test_invalid_event_id(self) -> None:
        attestor = OutcomeAttestor()

        result = await attestor.fetch_event_result(
            "evil;drop table",
            "basketball_nba",
            home_team="Lakers",
            away_team="Celtics",
        )

        assert result.status == "error"

    @pytest.mark.asyncio
    async def test_unsupported_sport(self) -> None:
        attestor = OutcomeAttestor()

        result = await attestor.fetch_event_result(
            "evt1",
            "cricket_ipl",
            home_team="A",
            away_team="B",
        )

        assert result.status == "error"

    @pytest.mark.asyncio
    async def test_missing_team_names_returns_pending(self) -> None:
        attestor = OutcomeAttestor()

        result = await attestor.fetch_event_result(
            "evt1",
            "basketball_nba",
            home_team="",
            away_team="",
        )

        assert result.status == "pending"

    @pytest.mark.asyncio
    async def test_walks_back_to_find_historical_game(self) -> None:
        """Regression: games from prior days must resolve via date back-walk.

        Root cause of zero-settlement gap (2026-04-20): ESPN scoreboard with
        date=None returns only today's games. Signals for games played days
        ago stuck in pending forever. Fix: when meta.game_date is None, walk
        back up to 30 days until a match is found.
        """
        from datetime import datetime, timedelta, timezone

        today = datetime.now(timezone.utc).date()
        target_date = (today - timedelta(days=5)).strftime("%Y%m%d")

        game = ESPNGame(
            espn_id="1",
            home_team="Lakers",
            away_team="Celtics",
            home_score=115,
            away_score=108,
            status="final",
        )

        async def fake_scoreboard(sport, date=None):
            # Game exists ONLY on target date; all other dates empty.
            if date == target_date:
                return [game]
            return []

        espn = AsyncMock(spec=ESPNClient)
        espn.get_scoreboard = AsyncMock(side_effect=fake_scoreboard)
        espn.close = AsyncMock()
        attestor = OutcomeAttestor(espn_client=espn)

        result = await attestor.fetch_event_result(
            "evt1",
            "basketball_nba",
            home_team="Lakers",
            away_team="Celtics",
            game_date=None,
        )

        assert result.status == "final"
        assert result.home_score == 115

    @pytest.mark.asyncio
    async def test_uses_cached_game_date_when_known(self) -> None:
        """When meta.game_date is set, only probe that date (no back-walk)."""
        game = ESPNGame(
            espn_id="1",
            home_team="Lakers",
            away_team="Celtics",
            home_score=115,
            away_score=108,
            status="final",
        )

        call_dates: list[str | None] = []

        async def fake_scoreboard(sport, date=None):
            call_dates.append(date)
            return [game] if date == "20260404" else []

        espn = AsyncMock(spec=ESPNClient)
        espn.get_scoreboard = AsyncMock(side_effect=fake_scoreboard)
        espn.close = AsyncMock()
        attestor = OutcomeAttestor(espn_client=espn)

        result = await attestor.fetch_event_result(
            "evt1",
            "basketball_nba",
            home_team="Lakers",
            away_team="Celtics",
            game_date="20260404",
        )

        assert result.status == "final"
        # Only ONE probe (the exact date) — no back-walk when date is known.
        assert call_dates == ["20260404"]

    @pytest.mark.asyncio
    async def test_espn_fetch_error_returns_pending(self) -> None:
        espn = AsyncMock(spec=ESPNClient)
        espn.get_game_by_teams = AsyncMock(side_effect=Exception("network error"))
        espn.get_scoreboard = AsyncMock(side_effect=Exception("network error"))
        espn.close = AsyncMock()
        attestor = OutcomeAttestor(espn_client=espn)

        result = await attestor.fetch_event_result(
            "evt1",
            "basketball_nba",
            home_team="Lakers",
            away_team="Celtics",
        )

        assert result.status == "pending"


# ---------------------------------------------------------------------------
# Backwards Compatibility
# ---------------------------------------------------------------------------


class TestBackwardsCompat:
    def test_sports_api_key_param_deprecated(self) -> None:
        """Passing sports_api_key still works but is ignored."""
        attestor = OutcomeAttestor(sports_api_key="old-key")
        assert attestor._espn is not None  # Uses ESPN internally

    def test_default_construction(self) -> None:
        """Default construction creates an ESPN client."""
        attestor = OutcomeAttestor()
        assert attestor._espn is not None


class TestOutcomePersistence:
    """Regression tests for v1417: outcomes must survive validator restart."""

    def _make_meta(self, signal_id: str = "sig-persist-1") -> SignalMetadata:
        return SignalMetadata(
            signal_id=signal_id,
            sport="basketball_nba",
            event_id="evt-42",
            home_team="Lakers",
            away_team="Celtics",
            lines=SAMPLE_PARSED,
            purchased_at=time.time(),
        )

    def test_resolution_persists_to_db(self, tmp_path) -> None:
        """After resolve, outcomes_json + resolved=1 are written to SQLite."""
        db = tmp_path / "outcomes.sqlite"
        attestor = OutcomeAttestor(db_path=str(db))
        meta = self._make_meta()
        attestor.register_signal(meta)

        meta.resolved = True
        meta.outcomes = [Outcome.FAVORABLE, Outcome.UNFAVORABLE, Outcome.VOID] * 3 + [Outcome.FAVORABLE]
        attestor._persist_resolution(meta)

        row = attestor._db.execute(
            "SELECT resolved, outcomes_json FROM signal_registrations WHERE signal_id = ?",
            (meta.signal_id,),
        ).fetchone()
        assert row is not None
        assert row[0] == 1
        assert row[1] is not None
        import json as _json
        assert _json.loads(row[1]) == [int(o) for o in meta.outcomes]

    def test_outcomes_survive_restart(self, tmp_path) -> None:
        """Reloading the attestor rehydrates meta.outcomes from SQLite."""
        db = tmp_path / "outcomes.sqlite"
        attestor = OutcomeAttestor(db_path=str(db))
        meta = self._make_meta()
        attestor.register_signal(meta)
        outcomes = [Outcome.FAVORABLE] * 10
        meta.resolved = True
        meta.outcomes = outcomes
        attestor._persist_resolution(meta)
        attestor._db.close()

        attestor2 = OutcomeAttestor(db_path=str(db))
        reloaded = attestor2.get_signal(meta.signal_id)
        assert reloaded is not None
        assert reloaded.resolved is True
        assert reloaded.outcomes == outcomes

    def test_alter_table_idempotent(self, tmp_path) -> None:
        """Reopening the DB twice doesn't crash from duplicate-column ALTER."""
        db = tmp_path / "outcomes.sqlite"
        a1 = OutcomeAttestor(db_path=str(db))
        a1._db.close()
        # Second open must not raise
        a2 = OutcomeAttestor(db_path=str(db))
        assert a2._db is not None

    def test_ghost_resolved_reset_to_pending(self, tmp_path) -> None:
        """v1418: a pre-v1417 row with resolved=1 but outcomes_json NULL is a
        ghost — the in-memory outcomes were lost on restart. Such signals must
        load as pending so resolve_all_pending can reclaim them, otherwise
        get_pending_signals filters them out forever and record_outcomes is
        never called, leaving audit_set_store.resolved_signals stuck at 0.
        """
        db = tmp_path / "outcomes.sqlite"
        attestor = OutcomeAttestor(db_path=str(db))
        meta = self._make_meta("sig-ghost-1")
        attestor.register_signal(meta)
        # Simulate pre-v1417: resolved bit set but outcomes column NULL.
        attestor._db.execute(
            "UPDATE signal_registrations SET resolved = 1, outcomes_json = NULL "
            "WHERE signal_id = ?",
            (meta.signal_id,),
        )
        attestor._db.commit()
        attestor._db.close()

        attestor2 = OutcomeAttestor(db_path=str(db))
        reloaded = attestor2.get_signal(meta.signal_id)
        assert reloaded is not None
        # The ghost is reset so it flows back into pending-signals
        # iteration and resolve_all_pending can retry it.
        assert reloaded.resolved is False
        assert reloaded.outcomes is None
        pending_ids = {m.signal_id for m in attestor2.get_pending_signals()}
        assert meta.signal_id in pending_ids
