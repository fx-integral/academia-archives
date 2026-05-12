"""Tests for the canonical odds schema and Odds API -> canonical mapper."""

from __future__ import annotations

import pytest

from djinn_miner.data.canonical import (
    CanonicalOdds,
    Market,
    Side,
    Sport,
    bookmaker_odds_to_canonical,
    events_to_canonical,
    map_market_key,
    map_outcome_to_side,
    _parse_commence_time_ms,
)
from djinn_miner.data.provider import BookmakerOdds


class TestMarketKeyMapping:
    def test_odds_api_h2h_maps_to_moneyline(self) -> None:
        assert map_market_key("h2h") is Market.MONEYLINE

    def test_odds_api_spreads_maps_to_spread(self) -> None:
        assert map_market_key("spreads") is Market.SPREAD

    def test_odds_api_totals_maps_to_total(self) -> None:
        assert map_market_key("totals") is Market.TOTAL

    def test_case_insensitive(self) -> None:
        assert map_market_key("H2H") is Market.MONEYLINE
        assert map_market_key("  Spreads  ") is Market.SPREAD

    def test_canonical_keys_also_accepted(self) -> None:
        """So a provider that already uses canonical keys round-trips cleanly."""
        assert map_market_key("moneyline") is Market.MONEYLINE
        assert map_market_key("spread") is Market.SPREAD
        assert map_market_key("total") is Market.TOTAL

    def test_unknown_returns_none(self) -> None:
        assert map_market_key("futures") is None
        assert map_market_key("") is None


class TestOutcomeToSide:
    def test_total_over(self) -> None:
        assert map_outcome_to_side("Over", Market.TOTAL, None, None) is Side.OVER
        assert map_outcome_to_side("over", Market.TOTAL, None, None) is Side.OVER
        assert map_outcome_to_side("O", Market.TOTAL, None, None) is Side.OVER

    def test_total_under(self) -> None:
        assert map_outcome_to_side("Under", Market.TOTAL, None, None) is Side.UNDER
        assert map_outcome_to_side("U", Market.TOTAL, None, None) is Side.UNDER

    def test_moneyline_home_team(self) -> None:
        assert (
            map_outcome_to_side("Boston Celtics", Market.MONEYLINE, "Boston Celtics", "Los Angeles Lakers") is Side.HOME
        )

    def test_moneyline_away_team(self) -> None:
        assert (
            map_outcome_to_side("Los Angeles Lakers", Market.MONEYLINE, "Boston Celtics", "Los Angeles Lakers")
            is Side.AWAY
        )

    def test_moneyline_case_insensitive(self) -> None:
        assert (
            map_outcome_to_side("boston celtics", Market.MONEYLINE, "Boston Celtics", "Los Angeles Lakers") is Side.HOME
        )

    def test_spread_home_team(self) -> None:
        assert map_outcome_to_side("Celtics", Market.SPREAD, "Celtics", "Lakers") is Side.HOME

    def test_moneyline_unknown_team_returns_none(self) -> None:
        assert map_outcome_to_side("Brooklyn Nets", Market.MONEYLINE, "Celtics", "Lakers") is None

    def test_total_bad_label_returns_none(self) -> None:
        assert map_outcome_to_side("Even", Market.TOTAL, None, None) is None


class TestCommenceTimeParsing:
    def test_iso_8601_with_z(self) -> None:
        from datetime import datetime, timezone

        ms = _parse_commence_time_ms("2026-04-12T22:00:00Z")
        expected = int(datetime(2026, 4, 12, 22, 0, 0, tzinfo=timezone.utc).timestamp() * 1000)
        assert ms == expected

    def test_iso_8601_with_offset(self) -> None:
        ms = _parse_commence_time_ms("2026-04-12T22:00:00+00:00")
        assert ms > 0

    def test_seconds_since_epoch(self) -> None:
        ms = _parse_commence_time_ms(1_776_240_000)
        assert ms == 1_776_240_000_000

    def test_milliseconds_since_epoch(self) -> None:
        ms = _parse_commence_time_ms(1_776_240_000_000)
        assert ms == 1_776_240_000_000

    def test_none_returns_zero(self) -> None:
        assert _parse_commence_time_ms(None) == 0

    def test_garbage_returns_zero(self) -> None:
        assert _parse_commence_time_ms("not a date") == 0
        assert _parse_commence_time_ms("") == 0


class TestBookmakerOddsToCanonical:
    def test_basic_moneyline_conversion(self) -> None:
        odds = [
            BookmakerOdds(
                bookmaker_key="draftkings",
                bookmaker_title="DraftKings",
                market="h2h",
                name="Boston Celtics",
                price=1.91,
                point=None,
            ),
            BookmakerOdds(
                bookmaker_key="draftkings",
                bookmaker_title="DraftKings",
                market="h2h",
                name="Los Angeles Lakers",
                price=1.95,
                point=None,
            ),
        ]
        canonical = bookmaker_odds_to_canonical(
            odds,
            event_id="evt1",
            sport=Sport.NBA,
            home_team="Boston Celtics",
            away_team="Los Angeles Lakers",
            commence_time_ms=1_776_240_000_000,
            fetched_at_ms=1_776_240_100_000,
            source="the_odds_api",
        )
        assert len(canonical) == 2
        assert canonical[0].sport is Sport.NBA
        assert canonical[0].market is Market.MONEYLINE
        assert canonical[0].side is Side.HOME
        assert canonical[0].decimal_price == 1.91
        assert canonical[0].bookmaker == "draftkings"
        assert canonical[1].side is Side.AWAY

    def test_spread_with_line_preserved(self) -> None:
        odds = [
            BookmakerOdds(
                bookmaker_key="fanduel",
                bookmaker_title="FanDuel",
                market="spreads",
                name="Celtics",
                price=1.91,
                point=-5.5,
            ),
        ]
        canonical = bookmaker_odds_to_canonical(
            odds,
            event_id="evt1",
            sport=Sport.NBA,
            home_team="Celtics",
            away_team="Lakers",
            commence_time_ms=0,
            fetched_at_ms=0,
            source="the_odds_api",
        )
        assert len(canonical) == 1
        assert canonical[0].market is Market.SPREAD
        assert canonical[0].line == -5.5

    def test_total_over_under(self) -> None:
        odds = [
            BookmakerOdds(
                bookmaker_key="pinnacle",
                bookmaker_title="Pinnacle",
                market="totals",
                name="Over",
                price=1.91,
                point=224.5,
            ),
            BookmakerOdds(
                bookmaker_key="pinnacle",
                bookmaker_title="Pinnacle",
                market="totals",
                name="Under",
                price=1.91,
                point=224.5,
            ),
        ]
        canonical = bookmaker_odds_to_canonical(
            odds,
            event_id="evt1",
            sport=Sport.NBA,
            home_team="Celtics",
            away_team="Lakers",
            commence_time_ms=0,
            fetched_at_ms=0,
            source="the_odds_api",
        )
        assert len(canonical) == 2
        assert canonical[0].market is Market.TOTAL
        assert canonical[0].side is Side.OVER
        assert canonical[0].line == 224.5
        assert canonical[1].side is Side.UNDER

    def test_unknown_market_skipped(self) -> None:
        odds = [
            BookmakerOdds(
                bookmaker_key="book",
                bookmaker_title="Book",
                market="futures",  # not in canonical set
                name="Celtics",
                price=3.5,
                point=None,
            ),
        ]
        canonical = bookmaker_odds_to_canonical(
            odds,
            event_id="evt1",
            sport=Sport.NBA,
            home_team="Celtics",
            away_team="Lakers",
            commence_time_ms=0,
            fetched_at_ms=0,
            source="the_odds_api",
        )
        assert canonical == []

    def test_unresolved_side_skipped(self) -> None:
        odds = [
            BookmakerOdds(
                bookmaker_key="book",
                bookmaker_title="Book",
                market="h2h",
                name="Brooklyn Nets",  # neither home nor away
                price=2.0,
                point=None,
            ),
        ]
        canonical = bookmaker_odds_to_canonical(
            odds,
            event_id="evt1",
            sport=Sport.NBA,
            home_team="Celtics",
            away_team="Lakers",
            commence_time_ms=0,
            fetched_at_ms=0,
            source="the_odds_api",
        )
        assert canonical == []

    def test_invalid_price_skipped(self) -> None:
        odds = [
            BookmakerOdds(
                bookmaker_key="book",
                bookmaker_title="Book",
                market="h2h",
                name="Celtics",
                price=0.0,
                point=None,
            ),
            BookmakerOdds(
                bookmaker_key="book",
                bookmaker_title="Book",
                market="h2h",
                name="Celtics",
                price=float("inf"),
                point=None,
            ),
        ]
        canonical = bookmaker_odds_to_canonical(
            odds,
            event_id="evt1",
            sport=Sport.NBA,
            home_team="Celtics",
            away_team="Lakers",
            commence_time_ms=0,
            fetched_at_ms=0,
            source="the_odds_api",
        )
        assert canonical == []

    def test_canonical_odds_is_hashable(self) -> None:
        """Consensus layer needs to dedupe observations; frozen dataclass
        must be hashable even if we don't currently use set()."""
        o = CanonicalOdds(
            event_id="evt1",
            sport=Sport.NBA,
            home_team="Celtics",
            away_team="Lakers",
            commence_time_ms=0,
            market=Market.MONEYLINE,
            side=Side.HOME,
            decimal_price=1.91,
            line=None,
            bookmaker="draftkings",
            fetched_at_ms=0,
            source="the_odds_api",
        )
        # frozen=True makes instances hashable
        assert hash(o) == hash(o)


class TestEventsToCanonical:
    def test_full_event_translation(self) -> None:
        """Round-trip a realistic Odds API event through
        events_to_canonical using the real OddsApiClient parser."""
        from djinn_miner.data.odds_api import OddsApiClient

        client = OddsApiClient(api_key="")  # no real calls; just parser
        events = [
            {
                "id": "odds-api-evt-1",
                "home_team": "Boston Celtics",
                "away_team": "Los Angeles Lakers",
                "commence_time": "2026-04-12T22:00:00Z",
                "bookmakers": [
                    {
                        "key": "draftkings",
                        "title": "DraftKings",
                        "markets": [
                            {
                                "key": "h2h",
                                "outcomes": [
                                    {"name": "Boston Celtics", "price": 1.91},
                                    {"name": "Los Angeles Lakers", "price": 1.95},
                                ],
                            },
                            {
                                "key": "spreads",
                                "outcomes": [
                                    {"name": "Boston Celtics", "price": 1.91, "point": -5.5},
                                    {"name": "Los Angeles Lakers", "price": 1.91, "point": 5.5},
                                ],
                            },
                            {
                                "key": "totals",
                                "outcomes": [
                                    {"name": "Over", "price": 1.91, "point": 224.5},
                                    {"name": "Under", "price": 1.91, "point": 224.5},
                                ],
                            },
                        ],
                    },
                ],
            }
        ]
        canonical = events_to_canonical(
            events,
            sport=Sport.NBA,
            source="the_odds_api",
            fetched_at_ms=1_776_240_100_000,
            provider_parser=client.parse_bookmaker_odds,
        )
        assert len(canonical) == 6
        markets = {o.market for o in canonical}
        assert markets == {Market.MONEYLINE, Market.SPREAD, Market.TOTAL}
        # Every observation should carry the event_id and sport.
        assert all(o.event_id == "odds-api-evt-1" for o in canonical)
        assert all(o.sport is Sport.NBA for o in canonical)
        assert all(o.home_team == "Boston Celtics" for o in canonical)
        assert all(o.bookmaker == "draftkings" for o in canonical)
        assert all(o.commence_time_ms > 0 for o in canonical)

    def test_events_without_id_skipped(self) -> None:
        from djinn_miner.data.odds_api import OddsApiClient

        client = OddsApiClient(api_key="")
        events = [{"home_team": "A", "away_team": "B", "bookmakers": []}]
        canonical = events_to_canonical(
            events,
            sport=Sport.NBA,
            source="the_odds_api",
            fetched_at_ms=0,
            provider_parser=client.parse_bookmaker_odds,
        )
        assert canonical == []
