"""Canonical odds schema + provider-agnostic mapper.

The Djinn protocol deliberately decouples from any single odds
provider. Miners pick their own data source (The Odds API, OddsJam,
Pinnacle API, direct book scraping, ...) and implement a provider
adapter that maps their source's native shape into THIS canonical
schema. Validators run Yuma consensus on canonical observations
across miners; no single party dictates the source.

This module defines:

  Sport    — canonical sport enum (NBA, NFL, ...)
  Market   — canonical market enum (MONEYLINE, SPREAD, TOTAL, ...)
  Side     — canonical side enum (HOME, AWAY, OVER, UNDER)
  CanonicalOdds — one observation: (event, market, side, price, line,
    bookmaker, fetched_at, source)

Plus a mapper that translates the existing ``BookmakerOdds`` shape
(used by ``data/provider.py::SportsDataProvider``) into canonical
observations. Providers that already produce ``BookmakerOdds`` get
canonical compatibility for free via ``bookmaker_odds_to_canonical``;
providers with native shapes can either emit ``BookmakerOdds`` and
reuse the same mapper, or emit ``CanonicalOdds`` directly if their
ontology is cleaner.

The canonical schema is intentionally small — sports and markets
the protocol actually supports today, nothing more. Adding a sport
or market is a one-line enum addition + a mapper entry.
"""

from __future__ import annotations

import enum
import math
from dataclasses import dataclass
from typing import Any

from djinn_miner.data.provider import BookmakerOdds


class Sport(enum.Enum):
    """Canonical sport identifier.

    Values match the internal sport keys used by the rest of the
    Djinn codebase (see ``validator/djinn_validator/core/outcomes.py``
    and ``web/lib/odds.ts``) so the canonical schema can be dropped
    in without breaking existing references.
    """

    NBA = "basketball_nba"
    NHL = "icehockey_nhl"
    MLB = "baseball_mlb"
    NFL = "americanfootball_nfl"
    EPL = "soccer_epl"
    MLS = "soccer_usa_mls"
    NCAAB = "basketball_ncaab"
    NCAAF = "americanfootball_ncaaf"


class Market(enum.Enum):
    """Canonical market identifier.

    The three markets the Djinn protocol currently scores against:
    moneyline (head-to-head), point spread, and over/under total.
    """

    MONEYLINE = "moneyline"
    SPREAD = "spread"
    TOTAL = "total"


class Side(enum.Enum):
    """Canonical side identifier for a market outcome.

    HOME/AWAY apply to moneyline and spread; OVER/UNDER apply to
    totals. Providers that use team names or book-specific labels
    must resolve to one of these four values.
    """

    HOME = "home"
    AWAY = "away"
    OVER = "over"
    UNDER = "under"


@dataclass(frozen=True)
class CanonicalOdds:
    """One canonical odds observation.

    Immutable so the consensus layer can hash and dedupe these
    without worrying about aliasing.
    """

    event_id: str
    sport: Sport
    home_team: str
    away_team: str
    commence_time_ms: int
    market: Market
    side: Side
    decimal_price: float
    line: float | None
    bookmaker: str
    fetched_at_ms: int
    source: str


# ---------------------------------------------------------------------------
# Provider mapping tables
# ---------------------------------------------------------------------------
#
# The legacy provider surface (``BookmakerOdds``) uses Odds API's
# market keys (h2h/spreads/totals) and raw team/over/under names as
# outcome labels. The tables below translate those into the canonical
# enums. Adding a new market or provider means extending these
# tables, not rewriting callers.


_MARKET_KEY_TO_CANONICAL: dict[str, Market] = {
    "h2h": Market.MONEYLINE,
    "moneyline": Market.MONEYLINE,
    "spreads": Market.SPREAD,
    "spread": Market.SPREAD,
    "totals": Market.TOTAL,
    "total": Market.TOTAL,
}


def map_market_key(market_key: str) -> Market | None:
    """Translate a provider's market key into the canonical Market
    enum. Unknown markets return None (caller decides whether to
    log-and-skip or raise).
    """
    return _MARKET_KEY_TO_CANONICAL.get(market_key.strip().lower())


def map_outcome_to_side(
    outcome_name: str,
    market: Market,
    home_team: str | None,
    away_team: str | None,
) -> Side | None:
    """Resolve a provider's outcome label into the canonical Side.

    For moneyline/spread: match the outcome name to home_team or
    away_team (case-insensitive). For totals: match against
    Over/Under. Returns None if nothing resolves.
    """
    name = (outcome_name or "").strip().lower()
    if market is Market.TOTAL:
        if name in ("over", "o"):
            return Side.OVER
        if name in ("under", "u"):
            return Side.UNDER
        return None

    if market in (Market.MONEYLINE, Market.SPREAD):
        if home_team and name == home_team.strip().lower():
            return Side.HOME
        if away_team and name == away_team.strip().lower():
            return Side.AWAY
        return None

    return None


def _parse_commence_time_ms(raw: Any) -> int:
    """Best-effort parse of a commence_time into milliseconds since
    epoch. Accepts int/float seconds, int/float milliseconds, and
    ISO-8601 strings. Returns 0 on failure (observation stays usable
    but its ordering in time is unknown).
    """
    if raw is None:
        return 0
    if isinstance(raw, (int, float)):
        if not math.isfinite(raw):
            return 0
        # Heuristic: anything > 10^12 is already milliseconds.
        return int(raw) if raw > 1e12 else int(raw * 1000)
    if isinstance(raw, str):
        try:
            from datetime import datetime

            # Accept both naive and tz-aware ISO strings; add Z if missing.
            s = raw.strip()
            if not s:
                return 0
            # Python fromisoformat handles "2026-04-12T22:00:00+00:00" directly.
            if s.endswith("Z"):
                s = s[:-1] + "+00:00"
            return int(datetime.fromisoformat(s).timestamp() * 1000)
        except (ValueError, TypeError):
            return 0
    return 0


def bookmaker_odds_to_canonical(
    odds: list[BookmakerOdds],
    *,
    event_id: str,
    sport: Sport,
    home_team: str,
    away_team: str,
    commence_time_ms: int,
    fetched_at_ms: int,
    source: str,
) -> list[CanonicalOdds]:
    """Translate a list of legacy ``BookmakerOdds`` into canonical
    observations.

    Drops entries whose market key or outcome name cannot be resolved
    to the canonical enums (and logs the skip). The caller passes the
    event-level metadata (event_id, sport, teams, commence time) since
    ``BookmakerOdds`` is single-outcome and doesn't carry event context.
    """
    import structlog

    log = structlog.get_logger()

    out: list[CanonicalOdds] = []
    for bo in odds:
        market = map_market_key(bo.market)
        if market is None:
            log.debug(
                "canonical_skip_unknown_market",
                raw_market=bo.market,
                bookmaker=bo.bookmaker_key,
            )
            continue
        side = map_outcome_to_side(bo.name, market, home_team, away_team)
        if side is None:
            log.debug(
                "canonical_skip_unresolved_side",
                raw_name=bo.name,
                market=market.value,
                bookmaker=bo.bookmaker_key,
            )
            continue
        if bo.price <= 0 or not math.isfinite(bo.price):
            log.debug(
                "canonical_skip_invalid_price",
                price=bo.price,
                bookmaker=bo.bookmaker_key,
            )
            continue
        out.append(
            CanonicalOdds(
                event_id=event_id,
                sport=sport,
                home_team=home_team,
                away_team=away_team,
                commence_time_ms=commence_time_ms,
                market=market,
                side=side,
                decimal_price=bo.price,
                line=bo.point,
                bookmaker=bo.bookmaker_key,
                fetched_at_ms=fetched_at_ms,
                source=source,
            )
        )
    return out


def events_to_canonical(
    events: list[dict[str, Any]],
    *,
    sport: Sport,
    source: str,
    fetched_at_ms: int,
    provider_parser: Any,
) -> list[CanonicalOdds]:
    """Translate a full Odds-API-shaped event list into canonical
    observations.

    Walks each event, calls the provider's ``parse_bookmaker_odds``
    to get ``BookmakerOdds`` for that event, then
    ``bookmaker_odds_to_canonical`` to map to canonical form. The
    event-level metadata (id, teams, commence time) is pulled from
    each event dict directly.

    This is the top-level entry point a provider adapter calls to
    produce canonical observations from its native event shape.
    """
    all_canonical: list[CanonicalOdds] = []
    for ev in events:
        if not isinstance(ev, dict):
            continue
        event_id = str(ev.get("id") or "")
        if not event_id:
            continue
        home_team = str(ev.get("home_team") or "")
        away_team = str(ev.get("away_team") or "")
        commence_time_ms = _parse_commence_time_ms(ev.get("commence_time"))
        bo_list = provider_parser([ev])
        all_canonical.extend(
            bookmaker_odds_to_canonical(
                bo_list,
                event_id=event_id,
                sport=sport,
                home_team=home_team,
                away_team=away_team,
                commence_time_ms=commence_time_ms,
                fetched_at_ms=fetched_at_ms,
                source=source,
            )
        )
    return all_canonical
