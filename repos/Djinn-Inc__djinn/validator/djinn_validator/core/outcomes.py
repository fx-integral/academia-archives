"""Outcome attestation — queries ESPN and builds consensus.

Validators independently query ESPN's free public scoreboard API, then
reach 2/3+ consensus before writing outcomes on-chain.

Outcome determination logic:
- SPREADS: Team must cover the spread (score diff > spread for favorites,
           or lose by fewer than spread for underdogs). Push = VOID.
- TOTALS:  Combined score must be over/under the total. Push = VOID.
- H2H:     Selected team must win outright. Tie = VOID.

v1747 (Phase 2b): line-keyed resolution sharing. The canonical
``canonical_outcome_for_line`` function is the authoritative ESPN→outcome
mapping per docs/v1747-line-schema.md §5; ``LineResolution`` rows in
``OutcomeAttestor._line_resolutions`` are content-addressed by lineHash so
100 signals containing "Lakers -3.5" share one resolution row. The legacy
``determine_outcome`` path is preserved verbatim for back-compat with
existing tests; resolve_signal now dual-resolves and prefers the canonical
result when a LineKey can be derived. Validators iterate lines in sorted
lineHash order so attestation timing cannot leak the real pick (§11).
"""

from __future__ import annotations

import asyncio
import json
import math
import os
import re
import sqlite3
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import IntEnum
from typing import TYPE_CHECKING, Any

import structlog

from djinn_validator.chain.outcome_signer import (
    LineKey,
    line_hash as _compute_line_hash,
)

if TYPE_CHECKING:
    from djinn_validator.core.espn import ESPNClient

log = structlog.get_logger()


# ---------------------------------------------------------------------------
# v1747 canonical schema constants (mirror docs/v1747-line-schema.md §5)
# ---------------------------------------------------------------------------

# Per-sport terminal status set. Mismatches against this set return PENDING
# regardless of score data, so the line stays unresolved until ESPN reports
# a terminal state for that sport.
_TERMINAL_STATUSES_BY_SPORT: dict[str, frozenset[str]] = {
    "basketball_nba": frozenset({"STATUS_FINAL"}),
    "basketball_ncaab": frozenset({"STATUS_FINAL"}),
    "americanfootball_nfl": frozenset({"STATUS_FINAL"}),
    "americanfootball_ncaaf": frozenset({"STATUS_FINAL"}),
    "baseball_mlb": frozenset({"STATUS_FINAL", "STATUS_END_OF_REGULATION"}),
    "icehockey_nhl": frozenset({"STATUS_FINAL", "STATUS_AFTER_SHOOTOUT"}),
    "soccer_epl": frozenset(
        {"STATUS_FULL_TIME", "STATUS_AFTER_EXTRA_TIME", "STATUS_AFTER_PENALTIES"}
    ),
    "soccer_usa_mls": frozenset(
        {"STATUS_FULL_TIME", "STATUS_AFTER_EXTRA_TIME", "STATUS_AFTER_PENALTIES"}
    ),
}

_VOID_STATUSES: frozenset[str] = frozenset(
    {"STATUS_CANCELED", "STATUS_CANCELLED", "STATUS_ABANDONED", "STATUS_FORFEIT"}
)

_POSTPONED_STATUSES: frozenset[str] = frozenset({"STATUS_POSTPONED"})

# Postponed games stay PENDING until 7d past competitions[0].date. After that
# cutoff they're VOID. Defense in depth so a permanently postponed game can
# never lock funds in escrow forever.
_POSTPONED_VOID_AFTER_SECONDS: float = 7 * 86400


def _env_chain_id() -> int | None:
    """Read BASE_CHAIN_ID from env for default lineHash computation."""
    raw = os.environ.get("BASE_CHAIN_ID")
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError:
        return None


# v1747 deployed-address registry, keyed by chain id. When the env var
# LINE_OUTCOME_REGISTRY_ADDRESS is unset, we look up here. Add new chains
# as we deploy. Operators can override via env without code change if needed
# (e.g. pointing at a forked test deployment).
_DEPLOYED_LINE_REGISTRY = {
    84_532: "0x2AB6ef76464D25713dfc3b9613f6AD2d07218352",  # Base Sepolia, deployed 2026-05-09
    # 8453: "0x...",  # Base mainnet — set on mainnet deploy
}


def _env_registry_address() -> str | None:
    """Resolve the LineOutcomeRegistry proxy address.

    Resolution order:
      1. LINE_OUTCOME_REGISTRY_ADDRESS env var (operator override)
      2. Deployed-address lookup keyed on BASE_CHAIN_ID env (or default)
      3. None — resolve_signal degrades gracefully (skips _line_resolutions)
    """
    addr = os.environ.get("LINE_OUTCOME_REGISTRY_ADDRESS", "").strip()
    if addr:
        if not addr.startswith("0x") or len(addr) != 42:
            return None
        return addr

    chain_id_raw = os.environ.get("BASE_CHAIN_ID", "84532").strip()
    try:
        chain_id = int(chain_id_raw)
    except ValueError:
        return None
    return _DEPLOYED_LINE_REGISTRY.get(chain_id)


def _normalize_signal_id(signal_id: str) -> str:
    """Canonicalize a signal_id to decimal uint256 string.

    Must match `audit_set._normalize_signal_id` exactly, so OutcomeAttestor
    and audit_set_store converge on the same key for the same on-chain
    uint256. Without this, bootstrap backfill in audit_bootstrap.py calls
    `outcome_attestor.get_signal(sig_id)` using audit_set_store's
    decimal-normalized id but OutcomeAttestor.register_signal stored
    whatever encoding the chain client produced (sometimes 0x-hex,
    sometimes bare hex), yielding None and skipping the backfill. Root
    cause of v1421 post-deploy observation: resolved_total=39 but
    resolved_signals=0 in audit_set_store despite bootstrap backfill
    code path existing.
    """
    if not signal_id:
        return signal_id
    s = signal_id.strip()
    try:
        if s.startswith(("0x", "0X")):
            return str(int(s, 16))
        return str(int(s, 10))
    except ValueError:
        try:
            return str(int(s, 16))
        except ValueError:
            return s


class Outcome(IntEnum):
    """Signal outcome matching the smart contract enum."""

    PENDING = 0
    FAVORABLE = 1
    UNFAVORABLE = 2
    VOID = 3


@dataclass
class EventResult:
    """Result of a sporting event relevant to a signal."""

    event_id: str
    home_team: str = ""
    away_team: str = ""
    home_score: int | None = None
    away_score: int | None = None
    status: str = "pending"  # pending, final, postponed, cancelled
    raw_data: dict[str, Any] = field(default_factory=dict)


@dataclass
class ParsedPick:
    """A structured representation of a signal pick string.

    Examples:
        "Lakers -3.5 (-110)"  → market=spreads, team=Lakers, line=-3.5
        "Over 218.5 (-110)"   → market=totals, side=Over, line=218.5
        "Celtics ML (-150)"   → market=h2h, team=Celtics
    """

    market: str  # "spreads", "totals", "h2h"
    team: str = ""  # Team name (for spreads/h2h)
    side: str = ""  # "Over"/"Under" (for totals)
    line: float | None = None  # Spread or total line
    odds: int | None = None  # American odds (informational only)


@dataclass
class SignalMetadata:
    """Metadata for a purchased signal, used for blind outcome resolution.

    Stores ALL 10 decoy lines (already public on-chain).  The validator
    resolves every line against game results, producing 10 outcomes.
    The real outcome is selected later by batch MPC at the audit-set level,
    so no individual signal outcome is ever revealed.
    """

    signal_id: str
    sport: str  # The Odds API sport key, e.g., "basketball_nba"
    event_id: str  # The Odds API event ID
    home_team: str
    away_team: str
    lines: list[ParsedPick]  # All 10 public decoy lines
    purchased_at: float = field(default_factory=time.time)
    resolved: bool = False
    outcomes: list[Outcome] | None = None  # 10 outcomes once game resolves
    game_date: str | None = None  # YYYYMMDD, cached after first ESPN match


@dataclass
class OutcomeAttestation:
    """A validator's attestation of a signal's outcome."""

    signal_id: str
    validator_hotkey: str
    outcome: Outcome
    event_result: EventResult
    timestamp: float = field(default_factory=time.time)


@dataclass
class LineResolution:
    """A single canonical line's resolved outcome, content-addressed by lineHash.

    100 signals all referencing the same LineKey share this single row: the
    outcome is computed once from the ESPN payload and cached here, so
    settlement reads are line-keyed not signal-keyed (v1747 §1).

    ``stable_at`` and ``sig`` are populated by ``sign_stable_lines`` when
    a second matching poll lands ≥``STABILITY_SOAK_SECONDS`` after
    ``resolved_at`` — cheap insurance against an ESPN flip during a live
    correction. Once ``sig`` is populated, the line is never re-signed for
    a different outcome (operator ``forceVoid`` is the escape hatch).

    ``home_team`` / ``away_team`` are validator-local fields (NOT in the
    lineHash preimage) so we can re-poll ESPN without holding a
    SignalMetadata reference. Their values are whichever names successfully
    matched ESPN at first-resolution time.
    """

    line_key: LineKey
    outcome: Outcome
    home_score: int | None
    away_score: int | None
    espn_status: str
    resolved_at: float
    home_team: str = ""
    away_team: str = ""
    stable_at: float | None = None
    sig: bytes | None = None


# v1747 Phase 3: minimum gap between first-final and signing. Defends against
# ESPN flipping the score during a live correction. 180s ≈ 3 minutes.
STABILITY_SOAK_SECONDS: float = 180.0


# ---------------------------------------------------------------------------
# v1747 canonical pure functions
# ---------------------------------------------------------------------------


def _normalize_espn_status(status_name: str) -> str:
    """Uppercase and strip ESPN status names so STATUS_FINAL == status_final == Final."""
    s = (status_name or "").strip().upper()
    if not s:
        return ""
    if not s.startswith("STATUS_"):
        # Some ESPN payloads use display names ("Final", "Full Time"). Normalize.
        s = "STATUS_" + s.replace(" ", "_")
    return s


def _read_competition(espn_event: dict) -> dict:
    """Pull competitions[0] safely; ESPN sometimes wraps an event with a list."""
    comps = espn_event.get("competitions") or [{}]
    if not comps:
        return {}
    return comps[0] or {}


def _read_scores_and_lines(
    competition: dict,
) -> tuple[int | None, int | None, bool, bool, list[int], list[int]]:
    """Pull (home_score, away_score, home_winner_flag, away_winner_flag,
    home_linescores, away_linescores) from an ESPN competition payload.

    Linescores are per-period integer scores in canonical order (period 1, 2,
    ..., OT, ET). Used by sport-specific rules (soccer FT-only spread/total,
    NHL shootout exclusion).
    """
    home_score: int | None = None
    away_score: int | None = None
    home_winner = False
    away_winner = False
    home_linescores: list[int] = []
    away_linescores: list[int] = []
    for c in competition.get("competitors") or []:
        raw_score = c.get("score")
        if raw_score is None or raw_score == "":
            score = None
        else:
            try:
                score = int(raw_score)
            except (ValueError, TypeError):
                score = None
        ls = []
        for entry in c.get("linescores") or []:
            try:
                ls.append(int((entry or {}).get("value", 0) or 0))
            except (ValueError, TypeError):
                ls.append(0)
        if c.get("homeAway") == "home":
            home_score = score
            home_winner = bool(c.get("winner"))
            home_linescores = ls
        elif c.get("homeAway") == "away":
            away_score = score
            away_winner = bool(c.get("winner"))
            away_linescores = ls
    return home_score, away_score, home_winner, away_winner, home_linescores, away_linescores


def _resolve_spread(side: str, line_value: str, home: int, away: int) -> Outcome:
    try:
        line = float(line_value)
    except (ValueError, TypeError):
        return Outcome.VOID
    if side == "home":
        diff = (home + line) - away
    elif side == "away":
        diff = (away + line) - home
    else:
        return Outcome.VOID
    if abs(diff) < 1e-9:
        return Outcome.VOID  # push
    return Outcome.FAVORABLE if diff > 0 else Outcome.UNFAVORABLE


def _resolve_total(side: str, line_value: str, home: int, away: int) -> Outcome:
    try:
        line = float(line_value)
    except (ValueError, TypeError):
        return Outcome.VOID
    total = home + away
    if abs(total - line) < 1e-9:
        return Outcome.VOID  # push
    if side == "over":
        return Outcome.FAVORABLE if total > line else Outcome.UNFAVORABLE
    if side == "under":
        return Outcome.FAVORABLE if total < line else Outcome.UNFAVORABLE
    return Outcome.VOID


def canonical_outcome_for_line(
    sport: str,
    market: str,
    side: str,
    line_value: str,
    espn_event: dict,
    *,
    now: float | None = None,
) -> Outcome:
    """Pure deterministic mapping from canonical line + ESPN payload to Outcome.

    Authoritative implementation of docs/v1747-line-schema.md §5. No clock,
    no env, no validator-private state (the optional ``now`` parameter is
    only used for the postponed→Void 7-day cutoff and is part of the schema's
    contract). Same inputs always yield the same outputs across machines.

    Args:
        sport: canonical sport key (e.g. "basketball_nba").
        market: "spread" | "total" | "moneyline".
        side: "home"/"away" for spread/moneyline; "over"/"under" for total.
        line_value: signed decimal one-place (e.g. "-3.5") for spread/total;
            empty string for moneyline.
        espn_event: raw ESPN event payload from
            site.api.espn.com/apis/site/v2/sports/{sport}/events/{event_id}.
        now: epoch seconds for the postponed cutoff. Defaults to time.time().

    Returns:
        ``Outcome.PENDING`` if the game isn't terminal yet.
        ``Outcome.FAVORABLE`` / ``Outcome.UNFAVORABLE`` for resolved bets.
        ``Outcome.VOID`` for pushes, cancellations, ambiguous data, or
        unsupported markets.
    """
    competition = _read_competition(espn_event)
    status_raw = ((competition.get("status") or {}).get("type") or {}).get("name", "")
    status = _normalize_espn_status(status_raw)

    # Postponed: PENDING until 7d after the scheduled date, then VOID.
    if status in _POSTPONED_STATUSES:
        evt_iso = competition.get("date") or ""
        if not evt_iso:
            return Outcome.PENDING
        try:
            evt_dt = datetime.fromisoformat(evt_iso.replace("Z", "+00:00"))
        except ValueError:
            return Outcome.PENDING
        cur = datetime.fromtimestamp(time.time() if now is None else now, tz=UTC)
        cutoff = evt_dt + timedelta(seconds=_POSTPONED_VOID_AFTER_SECONDS)
        return Outcome.VOID if cur >= cutoff else Outcome.PENDING

    if status in _VOID_STATUSES:
        return Outcome.VOID

    terminals = _TERMINAL_STATUSES_BY_SPORT.get(sport, frozenset())
    if status not in terminals:
        return Outcome.PENDING

    home_score, away_score, home_winner, away_winner, home_ls, away_ls = (
        _read_scores_and_lines(competition)
    )
    if home_score is None or away_score is None:
        return Outcome.PENDING

    # Sport-specific score adjustments for spread/total markets only.
    # Moneyline always uses the full final score (incl. OT, shootout, ET).
    spread_total_home, spread_total_away = home_score, away_score
    if sport == "icehockey_nhl" and status == "STATUS_AFTER_SHOOTOUT":
        # Shootout adds exactly 1 goal to the winner. Subtract for spread/total
        # so the regulation+OT score is what those markets settle against.
        if home_score > away_score:
            spread_total_home -= 1
        elif away_score > home_score:
            spread_total_away -= 1
    elif sport in ("soccer_epl", "soccer_usa_mls") and status in (
        "STATUS_AFTER_EXTRA_TIME",
        "STATUS_AFTER_PENALTIES",
    ):
        # Spread/total settle at full-time only. Use first 2 linescores
        # (period 1 + period 2 = 90'). If linescore data isn't available,
        # we can't determine FT score → VOID for spread/total.
        if len(home_ls) >= 2 and len(away_ls) >= 2:
            spread_total_home = sum(home_ls[:2])
            spread_total_away = sum(away_ls[:2])
        elif market in ("spread", "total"):
            return Outcome.VOID

    if market == "spread":
        return _resolve_spread(side, line_value, spread_total_home, spread_total_away)
    if market == "total":
        return _resolve_total(side, line_value, spread_total_home, spread_total_away)
    if market == "moneyline":
        if sport in ("soccer_epl", "soccer_usa_mls") and status == "STATUS_AFTER_PENALTIES":
            # ESPN reports the post-shootout winner via the ``winner`` flag;
            # the score field typically holds 120' (post-ET) score, which is
            # tied. Use the winner flag for ML resolution.
            if home_winner == away_winner:
                return Outcome.VOID
            home_won = home_winner
        else:
            if home_score == away_score:
                return Outcome.VOID
            home_won = home_score > away_score
        if side == "home":
            return Outcome.FAVORABLE if home_won else Outcome.UNFAVORABLE
        if side == "away":
            return Outcome.FAVORABLE if not home_won else Outcome.UNFAVORABLE

    return Outcome.VOID


# ---------------------------------------------------------------------------
# ParsedPick → LineKey bridge (legacy → canonical, opportunistic)
# ---------------------------------------------------------------------------


def _canonicalize_line_value(line: float, market: str) -> str:
    """Render a Python float into v1747 canonical line_value format.

    spread: signed one-decimal-place (sign always present, "+0.0" for zero).
    total:  unsigned one-decimal-place (per schema §1: sign optional, generated as positive).
    moneyline: empty string.
    """
    if market == "moneyline":
        return ""
    if market == "spread":
        if abs(line) < 1e-9:
            return "+0.0"
        return f"{line:+.1f}"
    if market == "total":
        return f"{abs(line):.1f}"
    return ""


def parsed_pick_to_line_key(
    pick: ParsedPick,
    sport: str,
    event_id: str,
    home_team: str,
    away_team: str,
) -> LineKey | None:
    """Best-effort conversion from a legacy ParsedPick to a canonical LineKey.

    Returns None when the pick can't be expressed canonically (unknown team,
    ambiguous market, missing line). Callers fall back to the legacy
    ``determine_outcome`` path for unparseable picks rather than poisoning
    line-keyed storage with malformed entries.
    """
    market_map = {"spreads": "spread", "totals": "total", "h2h": "moneyline"}
    market = market_map.get(pick.market)
    if market is None:
        return None

    if market == "total":
        side = (pick.side or "").lower()
        if side not in ("over", "under"):
            return None
    else:
        is_home = _team_matches(pick.team, home_team)
        is_away = _team_matches(pick.team, away_team)
        if is_home and not is_away:
            side = "home"
        elif is_away and not is_home:
            side = "away"
        else:
            return None

    if market == "moneyline":
        line_value = ""
    elif pick.line is None:
        return None
    else:
        line_value = _canonicalize_line_value(pick.line, market)

    return LineKey(
        sport=sport,
        event_id=str(event_id),
        market=market,
        side=side,
        line_value=line_value,
    )


# ---------------------------------------------------------------------------
# Pick Parsing
# ---------------------------------------------------------------------------

_SAFE_ID_RE = re.compile(r"^[a-zA-Z0-9_\-:.]{1,256}$")


# Supported sport keys — must have an ESPN mapping.
# Import lazily to avoid circular imports at module level.
def _get_supported_sports() -> frozenset[str]:
    from djinn_validator.core.espn import SUPPORTED_SPORTS as _ESPN_SPORTS

    return _ESPN_SPORTS


SUPPORTED_SPORTS: frozenset[str] = frozenset(
    {
        "americanfootball_nfl",
        "americanfootball_ncaaf",
        "basketball_nba",
        "basketball_ncaab",
        "baseball_mlb",
        "icehockey_nhl",
        "soccer_epl",
        "soccer_usa_mls",
    }
)

# Regex patterns for different pick formats
_SPREAD_RE = re.compile(r"^(.+?)\s+([+-]?\d+(?:\.\d+)?)\s*\(([+-]?\d+)\)$")
_TOTAL_RE = re.compile(r"^(Over|Under)\s+(\d+(?:\.\d+)?)\s*\(([+-]?\d+)\)$", re.IGNORECASE)
_ML_RE = re.compile(r"^(.+?)\s+ML\s*\(([+-]?\d+)\)$", re.IGNORECASE)


def _parse_json_pick(obj: dict) -> ParsedPick | None:
    """Parse a JSON-serialized StructuredLine from the web app."""
    market = obj.get("market", "")
    side = obj.get("side", "")
    line = obj.get("line")
    price = obj.get("price")
    # Convert decimal price to American odds for storage
    odds: int | None = None
    if price and isinstance(price, int | float) and price > 1:
        if price >= 2.0:
            odds = round((price - 1) * 100)
        else:
            odds = round(-100 / (price - 1))
    if market == "totals":
        return ParsedPick(market="totals", side=side, line=float(line) if line is not None else None, odds=odds)
    elif market == "spreads":
        return ParsedPick(market="spreads", team=side, line=float(line) if line is not None else None, odds=odds)
    elif market == "h2h":
        return ParsedPick(market="h2h", team=side, odds=odds)
    return None


def parse_pick(pick_str: str) -> ParsedPick:
    """Parse a pick string into structured data.

    Supports two formats:
        1. JSON (from web app v2): {"market":"spreads","side":"Lakers","line":-3.5,"price":1.91,...}
        2. Human-readable: "Lakers -3.5 (-110)", "Over 218.5 (-110)", "Celtics ML (-150)"
    """
    pick_str = pick_str.strip()

    # Try JSON first (v2 web app sends StructuredLine objects)
    if pick_str.startswith("{"):
        try:
            import json

            obj = json.loads(pick_str)
            result = _parse_json_pick(obj)
            if result is not None:
                return result
        except (json.JSONDecodeError, TypeError, ValueError):
            pass

    # Try totals first (Over/Under)
    m = _TOTAL_RE.match(pick_str)
    if m:
        return ParsedPick(
            market="totals",
            side=m.group(1).capitalize(),
            line=float(m.group(2)),
            odds=int(m.group(3)),
        )

    # Try moneyline
    m = _ML_RE.match(pick_str)
    if m:
        return ParsedPick(
            market="h2h",
            team=m.group(1).strip(),
            odds=int(m.group(2)),
        )

    # Try spread (most common)
    m = _SPREAD_RE.match(pick_str)
    if m:
        return ParsedPick(
            market="spreads",
            team=m.group(1).strip(),
            line=float(m.group(2)),
            odds=int(m.group(3)),
        )

    # Fallback: treat as moneyline without explicit ML tag
    return ParsedPick(market="h2h", team=pick_str)


# ---------------------------------------------------------------------------
# Outcome Determination
# ---------------------------------------------------------------------------


def determine_outcome(
    pick: ParsedPick,
    result: EventResult,
    home_team: str,
    away_team: str,
) -> Outcome:
    """Determine signal outcome from pick + game result.

    Returns VOID for postponed/cancelled games or pushes (exact line hit).
    """
    if result.status in ("postponed", "cancelled"):
        return Outcome.VOID

    if result.status != "final":
        return Outcome.PENDING

    if result.home_score is None or result.away_score is None:
        return Outcome.PENDING

    home = result.home_score
    away = result.away_score

    if pick.market == "spreads":
        return _determine_spread(pick, home, away, home_team, away_team)
    elif pick.market == "totals":
        return _determine_total(pick, home, away)
    elif pick.market == "h2h":
        return _determine_h2h(pick, home, away, home_team, away_team)

    return Outcome.PENDING


def determine_all_outcomes(
    lines: list[ParsedPick],
    result: EventResult,
    home_team: str,
    away_team: str,
) -> list[Outcome]:
    """Determine outcomes for ALL decoy lines against a single game result.

    Returns a list of outcomes, one per line.  The real outcome is at the
    secret index, but no single party knows which index that is.
    """
    return [determine_outcome(line, result, home_team, away_team) for line in lines]


def _determine_spread(
    pick: ParsedPick,
    home: int,
    away: int,
    home_team: str,
    away_team: str,
) -> Outcome:
    """Spreads: team + spread vs opponent score."""
    if pick.line is None:
        return Outcome.VOID

    # Determine which team was picked
    is_home = _team_matches(pick.team, home_team)
    is_away = _team_matches(pick.team, away_team)

    if not is_home and not is_away:
        log.warning("team_not_found", pick_team=pick.team, home=home_team, away=away_team)
        return Outcome.VOID
    if is_home and is_away:
        log.warning("ambiguous_team_match", pick_team=pick.team, home=home_team, away=away_team)
        return Outcome.VOID

    if is_home:
        adjusted = home + pick.line
        diff = adjusted - away
    else:
        adjusted = away + pick.line
        diff = adjusted - home

    if abs(diff) < 1e-9:
        return Outcome.VOID  # Push
    return Outcome.FAVORABLE if diff > 0 else Outcome.UNFAVORABLE


def _determine_total(pick: ParsedPick, home: int, away: int) -> Outcome:
    """Totals: combined score over/under the line."""
    if pick.line is None:
        return Outcome.VOID

    total = home + away

    if abs(total - pick.line) < 1e-9:
        return Outcome.VOID  # Push

    if pick.side == "Over":
        return Outcome.FAVORABLE if total > pick.line else Outcome.UNFAVORABLE
    else:
        return Outcome.FAVORABLE if total < pick.line else Outcome.UNFAVORABLE


def _determine_h2h(
    pick: ParsedPick,
    home: int,
    away: int,
    home_team: str,
    away_team: str,
) -> Outcome:
    """Head-to-head (moneyline): picked team must win outright."""
    if home == away:
        return Outcome.VOID  # Tie

    is_home = _team_matches(pick.team, home_team)
    is_away = _team_matches(pick.team, away_team)

    if not is_home and not is_away:
        log.warning("team_not_found", pick_team=pick.team, home=home_team, away=away_team)
        return Outcome.VOID
    if is_home and is_away:
        log.warning("ambiguous_team_match", pick_team=pick.team, home=home_team, away=away_team)
        return Outcome.VOID

    if is_home:
        return Outcome.FAVORABLE if home > away else Outcome.UNFAVORABLE
    else:
        return Outcome.FAVORABLE if away > home else Outcome.UNFAVORABLE


def _team_matches(pick_team: str, full_name: str) -> bool:
    """Word-boundary match: pick might use city or mascot, full_name is "City Mascot"."""
    pick_lower = pick_team.lower()
    full_lower = full_name.lower()
    # Exact match
    if pick_lower == full_lower:
        return True
    # Word-boundary match (e.g., "Lakers" matches "Los Angeles Lakers")
    words = full_lower.split()
    if pick_lower in words:
        return True
    # Multi-word pick (e.g., "Kansas City" in "Kansas City Chiefs")
    if len(pick_lower.split()) > 1 and full_lower.startswith(pick_lower + " "):
        return True
    return False


# ---------------------------------------------------------------------------
# OutcomeAttestor
# ---------------------------------------------------------------------------


class OutcomeAttestor:
    """Manages outcome attestation and consensus building."""

    MAX_PENDING_SIGNALS = 10_000
    MAX_ATTESTATIONS_PER_SIGNAL = 100

    def __init__(
        self,
        espn_client: ESPNClient | None = None,
        sports_api_key: str = "",  # Deprecated, kept for backwards compat
        db_path: str | None = None,
        chain_id: int | None = None,
        registry_address: str | None = None,
        private_key_hex: str | None = None,
    ) -> None:
        if espn_client is not None:
            self._espn = espn_client
        else:
            from djinn_validator.core.espn import ESPNClient as _ESPNClient

            self._espn = _ESPNClient()
        if sports_api_key:
            log.warning(
                "sports_api_key_deprecated", msg="SPORTS_API_KEY is no longer used; validator uses ESPN for scores"
            )
        self._attestations: dict[str, list[OutcomeAttestation]] = {}
        self._pending_signals: dict[str, SignalMetadata] = {}
        self._lock = asyncio.Lock()
        # v1747: line-keyed canonical resolution cache. Multiple signals
        # containing the same line (same lineHash) share one row. Populated
        # opportunistically during resolve_signal whenever a ParsedPick can
        # be expressed as a canonical LineKey. Phase 3 will key gossip and
        # on-chain submission off this map; Phase 2b just lays the storage.
        # Keyed by 32-byte lineHash bytes so iteration in sorted order
        # gives deterministic, content-addressed processing (privacy §11).
        self._line_resolutions: dict[bytes, LineResolution] = {}
        # Chain context for lineHash computation. Defaults from env if not
        # passed; ``_line_resolutions`` only fills when both are present.
        self._chain_id: int | None = chain_id if chain_id is not None else _env_chain_id()
        self._registry_address: str | None = (
            registry_address if registry_address is not None else _env_registry_address()
        )
        # OV signer EOA private key for v1747 line-attestation signing. Same
        # key used for OutcomeVoting.submitVote — one identity per validator,
        # forever (design doc §3, locked decision B). Optional: if absent,
        # sign_stable_lines is a no-op (useful for unit tests / read-only
        # observer instances).
        self._private_key_hex: str | None = private_key_hex
        # v1747 Phase 7b: tracks lineHashes we've already submitted as
        # 1-element bundles, so submit_own_attestations is gas-idempotent
        # across loop iterations. Reset on restart (acceptable; the contract
        # is also idempotent on per-(line, signer) attestation, so worst case
        # is one wasted tx per line per restart).
        self._submitted_own: set[bytes] = set()
        # v1747 Phase 7d (diag): minimal counters surfaced via /v1/diag/v1747
        # so an operator with hotkey access can tell at a glance whether this
        # validator's dual-write path has been firing. Strict allowlist of
        # fields — see project_v1747_diag_2026_05_09 memo for the privacy
        # rationale on what's safe to surface vs not.
        self._diag_submit_status_counts: dict[str, int] = {}
        self._diag_recent_submit_errors: list[tuple[float, str, str]] = []  # (ts, status, error_code)
        self._diag_last_sign_attempt_at: float | None = None
        self._diag_last_submit_attempt_at: float | None = None
        # Phase A1.5 reconciliation tracking: when did this validator
        # last broadcast gossip for each resolved signal? Used by
        # get_resolved_for_reconcile() to round-robin re-broadcast
        # so peers that missed the first gossip (offline, 422 on
        # max_length, transient timeout) self-heal within minutes
        # rather than staying stuck forever.
        self._last_gossiped_at: dict[str, float] = {}
        # Lifetime counter + timestamp, strictly monotonic. Surfaced via
        # /health so external heuristics can distinguish "quiet period"
        # (resolved_total flat because no games finished) from "resolver
        # wedged" (pending climbing AND resolved_total flat across iters).
        # shares_held already surfaces DB record count; these give the
        # scoring/resolution-loop activity signal that was missing.
        self._resolved_total: int = 0
        self._last_resolve_at: float | None = None
        # Scoreboard cache shared across signals within one resolve_all_pending
        # pass. Without this, 72 pending signals × 30 days back-walk would
        # burst ESPN with 2000+ calls per epoch. Keyed by (sport, date-YYYYMMDD
        # or None for "current"), entry is (timestamp, games_list). TTL is
        # 120s — short enough that in-progress games re-poll, long enough to
        # amortize back-walk across one epoch.
        self._scoreboard_cache: dict[tuple[str, str | None], tuple[float, list]] = {}

        # Optional SQLite persistence for signal registrations
        self._db: sqlite3.Connection | None = None
        if db_path:
            import sqlite3 as _sqlite3
            from pathlib import Path as _Path

            _Path(db_path).parent.mkdir(parents=True, exist_ok=True)
            self._db = _sqlite3.connect(db_path, check_same_thread=False)
            self._db.execute("PRAGMA journal_mode=WAL")
            self._db.execute("PRAGMA busy_timeout=5000")
            self._db.execute("""
                CREATE TABLE IF NOT EXISTS signal_registrations (
                    signal_id TEXT PRIMARY KEY,
                    sport TEXT NOT NULL,
                    event_id TEXT NOT NULL,
                    home_team TEXT NOT NULL,
                    away_team TEXT NOT NULL,
                    lines_json TEXT NOT NULL,
                    registered_at REAL NOT NULL,
                    resolved INTEGER NOT NULL DEFAULT 0
                )
            """)
            try:
                self._db.execute("ALTER TABLE signal_registrations ADD COLUMN outcomes_json TEXT")
            except _sqlite3.OperationalError:
                pass
            try:
                self._db.execute("ALTER TABLE signal_registrations ADD COLUMN game_date TEXT")
            except _sqlite3.OperationalError:
                pass
            self._db.execute("""
                CREATE TABLE IF NOT EXISTS buyer_preferences (
                    address TEXT PRIMARY KEY,
                    books_json TEXT NOT NULL DEFAULT '[]',
                    encrypted_data TEXT NOT NULL DEFAULT '',
                    updated_at REAL NOT NULL
                )
            """)
            self._db.commit()
            self._load_persisted_signals()

    def _load_persisted_signals(self) -> None:
        """Load persisted signal registrations from SQLite on startup."""
        if not self._db:
            return
        try:
            cursor = self._db.execute(
                "SELECT signal_id, sport, event_id, home_team, away_team, "
                "lines_json, registered_at, resolved, outcomes_json, game_date FROM signal_registrations"
            )
            loaded = 0
            outcomes_loaded = 0
            ghost_reset = 0
            for row in cursor:
                (
                    signal_id,
                    sport,
                    event_id,
                    home_team,
                    away_team,
                    lines_json,
                    registered_at,
                    resolved,
                    outcomes_json,
                    game_date,
                ) = row
                try:
                    raw_lines = json.loads(lines_json)
                    parsed_lines = [parse_pick(line) for line in raw_lines]
                    outcomes: list[Outcome] | None = None
                    if outcomes_json:
                        try:
                            outcomes = [Outcome(int(x)) for x in json.loads(outcomes_json)]
                            outcomes_loaded += 1
                        except Exception as e:
                            log.debug("outcomes_load_skip", signal_id=signal_id, err=str(e)[:80])
                    # v1418: pre-v1417 validator runs persisted resolved=1 but had no
                    # outcomes_json column, so outcomes were lost on restart. Such
                    # signals are ghost-resolved: they satisfy `resolved=True` but
                    # have `outcomes=None`, so get_pending_signals filters them out
                    # forever and record_outcomes is never called for them. Reset
                    # them to pending so resolve_all_pending picks them back up.
                    resolved_bool = bool(resolved)
                    if resolved_bool and outcomes is None:
                        resolved_bool = False
                        ghost_reset += 1
                    canonical_id = _normalize_signal_id(signal_id)
                    meta = SignalMetadata(
                        signal_id=canonical_id,
                        sport=sport,
                        event_id=event_id,
                        home_team=home_team,
                        away_team=away_team,
                        lines=parsed_lines,
                        purchased_at=registered_at,
                        resolved=resolved_bool,
                        outcomes=outcomes,
                        game_date=game_date,
                    )
                    self._pending_signals[canonical_id] = meta
                    loaded += 1
                except Exception as e:
                    log.debug("signal_load_skip", signal_id=signal_id, err=str(e)[:80])
            if loaded:
                log.info(
                    "signals_loaded_from_db",
                    count=loaded,
                    with_outcomes=outcomes_loaded,
                    ghost_reset=ghost_reset,
                )
        except Exception as e:
            log.error("signal_db_load_failed", err=str(e))

    def _persist_resolution(self, metadata: SignalMetadata) -> None:
        """Persist a resolved signal's outcomes back to SQLite.

        Separate from _persist_signal (which runs at registration) because
        resolution happens hours/days later and must survive validator
        restart. Without this, meta.outcomes is recomputed from memory only,
        which empties on restart and leaves audit_set_store permanently
        waiting_for_outcomes. Root cause of the zero-settled-audits gap
        (v1417, 2026-04-20).
        """
        if not self._db or metadata.outcomes is None:
            return
        try:
            outcomes_json = json.dumps([int(o) for o in metadata.outcomes])
            self._db.execute(
                "UPDATE signal_registrations SET resolved = ?, outcomes_json = ? " "WHERE signal_id = ?",
                (int(metadata.resolved), outcomes_json, metadata.signal_id),
            )
            self._db.commit()
        except Exception as e:
            log.debug("resolution_persist_failed", signal_id=metadata.signal_id, err=str(e)[:80])

    def _persist_signal(self, metadata: SignalMetadata) -> None:
        """Persist a signal registration to SQLite."""
        if not self._db:
            return
        try:
            lines_raw = [
                f"{p.team or p.side} {p.line or ''} ({p.odds})" if p.odds else f"{p.team or p.side} {p.line or ''}"
                for p in metadata.lines
            ]
            self._db.execute(
                "INSERT OR REPLACE INTO signal_registrations "
                "(signal_id, sport, event_id, home_team, away_team, lines_json, registered_at, resolved, game_date) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    metadata.signal_id,
                    metadata.sport,
                    metadata.event_id,
                    metadata.home_team,
                    metadata.away_team,
                    json.dumps(lines_raw),
                    metadata.purchased_at,
                    int(metadata.resolved),
                    metadata.game_date,
                ),
            )
            self._db.commit()
        except Exception as e:
            log.debug("signal_persist_failed", signal_id=metadata.signal_id, err=str(e)[:80])

    def register_signal(self, metadata: SignalMetadata, *, allow_overwrite: bool = False) -> str:
        """Register a purchased signal for outcome tracking.

        v1724: lock-on-first-write. Pre-fix, the endpoint accepted unsigned
        re-registration that overwrote sport/event_id/home_team/away_team/
        lines via INSERT OR REPLACE — letting any unauthenticated caller
        poison resolution metadata for a signal they didn't own. Codex
        audit 2026-05-05 flagged this as the second High finding.

        Now: re-registration that DIFFERS from the existing record is
        rejected unless the caller passes ``allow_overwrite=True`` (only
        validator-hotkey-signed callers reach that path). Idempotent
        re-registration with identical fields returns "duplicate" so the
        gossip / retry paths still work.

        Returns one of: "added", "duplicate", "overwrite_rejected".
        """
        metadata.signal_id = _normalize_signal_id(metadata.signal_id)
        existing = self._pending_signals.get(metadata.signal_id)
        if existing is not None:
            same = (
                existing.sport == metadata.sport
                and existing.event_id == metadata.event_id
                and existing.home_team == metadata.home_team
                and existing.away_team == metadata.away_team
                and len(existing.lines) == len(metadata.lines)
                and all(
                    a.team == b.team and a.side == b.side and a.line == b.line and a.odds == b.odds
                    for a, b in zip(existing.lines, metadata.lines)
                )
            )
            if same:
                return "duplicate"
            if not allow_overwrite:
                log.warning(
                    "signal_register_overwrite_rejected",
                    signal_id=metadata.signal_id,
                    existing_sport=existing.sport,
                    new_sport=metadata.sport,
                    existing_event=existing.event_id,
                    new_event=metadata.event_id,
                )
                return "overwrite_rejected"
        if len(self._pending_signals) >= self.MAX_PENDING_SIGNALS:
            # Synchronous eviction of already-resolved signals at capacity
            now = time.time()
            stale = [
                sid for sid, m in list(self._pending_signals.items()) if m.resolved and now - m.purchased_at > 3600
            ]
            for sid in stale:
                del self._pending_signals[sid]
                self._attestations.pop(sid, None)
            if not stale:
                log.warning("pending_signals_at_capacity", max=self.MAX_PENDING_SIGNALS)
        self._pending_signals[metadata.signal_id] = metadata
        self._persist_signal(metadata)
        log.info(
            "signal_registered_for_outcome",
            signal_id=metadata.signal_id,
            sport=metadata.sport,
            event_id=metadata.event_id,
            lines_count=len(metadata.lines),
        )
        return "added"

    def get_signal(self, signal_id: str) -> SignalMetadata | None:
        """Look up a signal by ID (pending or resolved)."""
        return self._pending_signals.get(_normalize_signal_id(signal_id))

    def get_pending_signals(self) -> list[SignalMetadata]:
        """Return all unresolved signals."""
        return [s for s in self._pending_signals.values() if not s.resolved]

    @property
    def resolved_total(self) -> int:
        """Lifetime count of signals that transitioned pending → resolved."""
        return self._resolved_total

    @property
    def last_resolve_at(self) -> float | None:
        """Epoch seconds of the most recent resolution, or None if never."""
        return self._last_resolve_at

    async def _fetch_scoreboard_cached(
        self,
        sport: str,
        date: str | None,
    ) -> list:
        """Fetch scoreboard for (sport, date) with 120s in-memory cache.

        ESPN's scoreboard endpoint returns games for a single day (today when
        date is None). The per-epoch cache lets many signals of the same sport
        share one HTTP call during one resolve_all_pending pass, and survives
        long enough for multiple consecutive passes.
        """
        now = time.time()
        key = (sport, date)
        entry = self._scoreboard_cache.get(key)
        if entry is not None and now - entry[0] < 120:
            return entry[1]
        games = await self._espn.get_scoreboard(sport, date=date)
        self._scoreboard_cache[key] = (now, games)
        return games

    async def fetch_event_result(
        self,
        event_id: str,
        sport: str = "basketball_nba",
        home_team: str = "",
        away_team: str = "",
        game_date: str | None = None,
    ) -> EventResult:
        """Fetch event result from ESPN's public scoreboard API.

        Matches games by team names + date (ESPN IDs differ from Odds API IDs).
        The event_id is preserved for tracking but not used for ESPN lookup.

        When game_date is provided (YYYYMMDD), queries ESPN for that day only.
        When game_date is None, walks back from today up to 30 days, returning
        the first matched game. This handles signals whose game already happened
        — without it, ESPN's default (today-only) scoreboard causes historical
        signals to stick in pending forever (root cause of zero-settlement
        gap, 2026-04-20).
        """
        if not _SAFE_ID_RE.match(event_id):
            log.warning("invalid_event_id", event_id=event_id[:50])
            return EventResult(event_id=event_id, status="error")
        if sport not in SUPPORTED_SPORTS:
            log.warning("unsupported_sport_key", sport=sport[:50])
            return EventResult(event_id=event_id, status="error")

        if not home_team or not away_team:
            log.warning("missing_team_names", event_id=event_id)
            return EventResult(event_id=event_id, status="pending")

        # Import here to avoid top-level circular imports.
        from datetime import datetime, timedelta

        from djinn_validator.core.espn import match_game

        game = None
        if game_date:
            try:
                games = await self._fetch_scoreboard_cached(sport, game_date)
                game = match_game(games, home_team, away_team)
            except Exception as e:
                log.warning("espn_fetch_error", event_id=event_id, error=str(e))
                return EventResult(event_id=event_id, status="pending")
        else:
            # Walk back from today (0) up to 30 days; stop at first match.
            # Cap at 30d: beyond that, either sport is off-season or signal is
            # stale. Per-(sport,date) cache means this is at most ~31 ESPN calls
            # per sport per 120s, not per-signal.
            today = datetime.now(UTC).date()
            for days_back in range(0, 31):
                probe_date = None if days_back == 0 else (today - timedelta(days=days_back)).strftime("%Y%m%d")
                try:
                    games = await self._fetch_scoreboard_cached(sport, probe_date)
                except Exception as e:
                    log.warning("espn_fetch_error", event_id=event_id, error=str(e), days_back=days_back)
                    continue
                matched = match_game(games, home_team, away_team)
                if matched is not None:
                    game = matched
                    break

        if game is None:
            log.debug("espn_game_not_found", event_id=event_id, home=home_team, away=away_team)
            return EventResult(event_id=event_id, status="pending")

        if game.status in ("postponed",):
            return EventResult(
                event_id=event_id,
                home_team=game.home_team,
                away_team=game.away_team,
                status="postponed",
                raw_data=game.raw_data,
            )
        if game.status in ("cancelled",):
            return EventResult(
                event_id=event_id,
                home_team=game.home_team,
                away_team=game.away_team,
                status="cancelled",
                raw_data=game.raw_data,
            )
        if game.status != "final":
            return EventResult(
                event_id=event_id,
                home_team=game.home_team,
                away_team=game.away_team,
                status="pending",
                raw_data=game.raw_data,
            )

        return EventResult(
            event_id=event_id,
            home_team=game.home_team,
            away_team=game.away_team,
            home_score=game.home_score,
            away_score=game.away_score,
            status="final",
            raw_data=game.raw_data,
        )

    async def resolve_signal(
        self,
        signal_id: str,
        validator_hotkey: str,
    ) -> str | None:
        """Fetch scores and determine all 10 line outcomes for a signal.

        Blind resolution: resolves ALL 10 decoy lines against the game result
        and stores outcomes on the signal metadata.  The real outcome is NOT
        selected here — that happens later during batch MPC settlement at the
        audit-set level, so no individual signal outcome is ever revealed.

        Returns the signal_id if newly resolved, or None.
        """
        # v1707: surfaces resolve outcomes on /metrics. Without this counter,
        # operators see outcomes_resolved_total=0 and can't tell whether
        # validators have nothing pending vs the resolver is silently
        # failing.
        from djinn_validator.api.metrics import (
            RESOLVE_SIGNAL_RESULT,
            safe_label_inc,
        )

        def _resolve_tick(reason: str) -> None:
            safe_label_inc(RESOLVE_SIGNAL_RESULT, outcome=reason)

        signal_id = _normalize_signal_id(signal_id)
        async with self._lock:
            meta = self._pending_signals.get(signal_id)
            if meta is None:
                log.warning("signal_not_registered", signal_id=signal_id)
                _resolve_tick("not_registered")
                return None

            if meta.resolved:
                _resolve_tick("already_resolved")
                return None

        result = await self.fetch_event_result(
            meta.event_id,
            meta.sport,
            home_team=meta.home_team,
            away_team=meta.away_team,
            game_date=meta.game_date,
        )

        # Cache the discovered game date back on the meta so future resolve
        # passes skip the 30-day back-walk. ESPN's scoreboard event payload
        # has a top-level 'date' field in ISO8601 form ("2026-04-04T02:00Z").
        if meta.game_date is None and result.raw_data:
            iso = result.raw_data.get("date", "")
            if iso and len(iso) >= 10:
                # Parse "YYYY-MM-DD..." → "YYYYMMDD"
                d = iso[:10].replace("-", "")
                if d.isdigit() and len(d) == 8:
                    meta.game_date = d

        if result.status not in ("final", "postponed", "cancelled"):
            # Even if the game isn't final yet, we discovered the date;
            # persist it so we don't back-walk again next epoch.
            if meta.game_date is not None:
                self._persist_signal(meta)
            _resolve_tick("not_final")
            return None

        # Blind resolution: resolve ALL lines, not just one
        all_outcomes = determine_all_outcomes(
            meta.lines,
            result,
            meta.home_team,
            meta.away_team,
        )

        # If every line is still PENDING, game isn't truly finished
        if all(o == Outcome.PENDING for o in all_outcomes):
            _resolve_tick("all_pending")
            return None

        # v1747 Phase 2b: dual-resolve. Populate the canonical line-keyed
        # store in sorted-lineHash order so multiple signals containing the
        # same line collapse to one resolution row, and so attestation
        # iteration is content-addressed (privacy §11). The legacy outcomes
        # above remain authoritative for meta.outcomes and downstream
        # signal-keyed paths until Phase 3 wires the gossip layer onto
        # _line_resolutions; this is dual-write, not a flip.
        self._populate_line_resolutions(meta, result)

        async with self._lock:
            if meta.resolved:
                _resolve_tick("race_already_resolved")
                return None  # Another coroutine resolved it while we were fetching
            meta.resolved = True
            meta.outcomes = all_outcomes
            self._resolved_total += 1
            self._last_resolve_at = time.time()
            self._persist_resolution(meta)
            log.info("signal_outcomes_resolved", signal_id=signal_id, outcomes=[o.name for o in all_outcomes])
            _resolve_tick("resolved")
            return signal_id

    def _populate_line_resolutions(
        self,
        meta: SignalMetadata,
        result: EventResult,
    ) -> None:
        """v1747 Phase 2b: cache canonical per-line outcomes by lineHash.

        Iterates meta.lines in sorted-lineHash order (privacy §11) and runs
        the canonical pure function ``canonical_outcome_for_line`` on the
        raw ESPN payload. Skips lines that can't be expressed as canonical
        LineKeys (legacy ParsedPick format with unrecognized team/market) —
        those keep falling through the legacy determine_outcome path. Skips
        entirely when chain_id or registry_address are unset (e.g. unit
        tests without env config); the legacy resolution is unaffected.

        Called inside resolve_signal AFTER determine_all_outcomes and BEFORE
        the meta-mutation lock so this never blocks the legacy path.
        """
        if self._chain_id is None or self._registry_address is None:
            return
        if not result.raw_data:
            return

        indexed: list[tuple[bytes, int, LineKey]] = []
        for idx, pick in enumerate(meta.lines):
            lk = parsed_pick_to_line_key(
                pick, meta.sport, meta.event_id, meta.home_team, meta.away_team
            )
            if lk is None:
                continue
            try:
                lh = _compute_line_hash(lk, self._chain_id, self._registry_address)
            except (ValueError, TypeError):
                continue
            indexed.append((lh, idx, lk))
        indexed.sort(key=lambda t: t[0])

        # Snapshot the ESPN status + score fields up front so every line in
        # the batch records the same trace data (race-free since we hold the
        # raw_data dict by reference but don't mutate it).
        comp = _read_competition(result.raw_data)
        status_raw = ((comp.get("status") or {}).get("type") or {}).get("name", "")
        status_norm = _normalize_espn_status(status_raw)
        home_score, away_score, *_ = _read_scores_and_lines(comp)
        now = time.time()

        for lh, _idx, lk in indexed:
            if lh in self._line_resolutions:
                continue  # already cached from a prior signal sharing this line
            outcome = canonical_outcome_for_line(
                lk.sport, lk.market, lk.side, lk.line_value, result.raw_data, now=now
            )
            if outcome == Outcome.PENDING:
                # Don't pollute the line cache with non-terminal outcomes;
                # next resolve pass will retry. Stable_at + sig populated by
                # the Phase 3 stability loop, never here.
                continue
            self._line_resolutions[lh] = LineResolution(
                line_key=lk,
                outcome=outcome,
                home_score=home_score,
                away_score=away_score,
                espn_status=status_norm,
                resolved_at=now,
                home_team=meta.home_team,
                away_team=meta.away_team,
                stable_at=None,
                sig=None,
            )

    def get_line_resolution(self, line_hash: bytes) -> LineResolution | None:
        """Look up a canonical line outcome by 32-byte lineHash.

        Returns None if the line hasn't been resolved yet (or this validator
        doesn't hold any signal containing it). Used by the Phase 3 gossip
        layer and the Phase 4 MPC orchestrator gate.
        """
        return self._line_resolutions.get(line_hash)

    def iter_line_resolutions_sorted(self) -> list[tuple[bytes, LineResolution]]:
        """Iterate cached line resolutions in sorted-lineHash order.

        Privacy §11: validators MUST process lines in deterministic
        content-addressed order so attestation timing leaks no information
        about the real pick. This is the canonical iteration helper for the
        Phase 3 sign loop and Phase 4 submission loop.
        """
        return sorted(self._line_resolutions.items(), key=lambda kv: kv[0])

    def get_signal_line_sigs(self, signal_id: str) -> list[str | None]:
        """v1747 Phase 7c: return per-line EIP-712 signatures aligned 1:1 with
        ``meta.lines`` for outcome gossip propagation. Each entry is either
        a 0x-prefixed hex sig (this validator has signed that line) or None.

        Returns an empty list when the signal isn't registered, when chain
        context is unwired, or when no lines map to canonical LineKeys
        (legacy ParsedPick format).

        The receiver's ``_store_peer_attestation_sigs`` walks gossip
        ``outcomes[i]`` paired with ``eoa_sigs[i]`` and stores per-line
        sigs in its peer_attestation_store; ``None`` entries (or any
        non-string value) are silently skipped on receive.
        """
        sid = _normalize_signal_id(signal_id)
        meta = self._pending_signals.get(sid)
        if meta is None or self._chain_id is None or self._registry_address is None:
            return []

        sigs: list[str | None] = []
        for pick in meta.lines:
            lk = parsed_pick_to_line_key(
                pick, meta.sport, meta.event_id, meta.home_team, meta.away_team
            )
            if lk is None:
                sigs.append(None)
                continue
            try:
                lh = _compute_line_hash(lk, self._chain_id, self._registry_address)
            except (ValueError, TypeError):
                sigs.append(None)
                continue
            res = self._line_resolutions.get(lh)
            if res is None or res.sig is None:
                sigs.append(None)
            else:
                sigs.append("0x" + res.sig.hex())
        return sigs

    async def sign_stable_lines(self) -> list[bytes]:
        """v1747 Phase 3: re-poll ESPN, sign on second matching poll ≥180s later.

        Iterates ``_line_resolutions`` in sorted-lineHash order (privacy
        §11). For each line where:
          - ``sig`` is None (unsigned),
          - ``resolved_at + STABILITY_SOAK_SECONDS <= now`` (soak elapsed),

        re-fetches ESPN and re-runs ``canonical_outcome_for_line``. If the
        result matches, populates ``stable_at`` + ``sig``. If the result
        diverges, resets ``resolved_at`` to start a new soak window with
        the new outcome — never re-signs an already-signed row.

        Skips silently when ``_chain_id`` / ``_registry_address`` /
        ``_private_key_hex`` are unset (read-only observer mode or unit
        tests). Returns the list of newly-signed lineHashes.
        """
        if (
            self._chain_id is None
            or self._registry_address is None
            or self._private_key_hex is None
        ):
            return []

        now = time.time()
        self._diag_last_sign_attempt_at = now
        newly_signed: list[bytes] = []

        # Snapshot the eligible set under the lock-free read (mutations below
        # only update the snapshot's own LineResolution objects in-place via
        # the dict reference; concurrent _populate_line_resolutions runs may
        # add new rows but never mutate existing ones).
        eligible: list[tuple[bytes, LineResolution]] = []
        for lh, res in self.iter_line_resolutions_sorted():
            if res.sig is not None:
                continue
            if res.outcome == Outcome.PENDING:
                continue
            if res.resolved_at + STABILITY_SOAK_SECONDS > now:
                continue
            eligible.append((lh, res))

        from djinn_validator.chain.outcome_signer import sign_line_outcome

        for lh, res in eligible:
            result = await self.fetch_event_result(
                res.line_key.event_id,
                res.line_key.sport,
                home_team=res.home_team,
                away_team=res.away_team,
            )
            if result.status not in ("final", "postponed", "cancelled"):
                # ESPN regressed (e.g. game un-finalized or transient lookup
                # failure). Stay in soak — next call retries.
                continue
            if not result.raw_data:
                continue

            new_outcome = canonical_outcome_for_line(
                res.line_key.sport,
                res.line_key.market,
                res.line_key.side,
                res.line_key.line_value,
                result.raw_data,
                now=now,
            )
            if new_outcome == Outcome.PENDING:
                continue

            if new_outcome != res.outcome:
                # Outcome flipped during soak — reset window with the new
                # outcome. The old outcome was never signed, so we lose
                # nothing by abandoning it. Soak restarts from now.
                log.warning(
                    "line_outcome_flipped_during_soak",
                    line_hash=lh.hex(),
                    old=res.outcome.name,
                    new=new_outcome.name,
                )
                res.outcome = new_outcome
                res.resolved_at = now
                res.stable_at = None
                continue

            # Stable. Sign.
            try:
                sig = sign_line_outcome(
                    self._private_key_hex,
                    lh,
                    int(new_outcome),
                    self._chain_id,
                    self._registry_address,
                )
            except Exception as e:
                log.warning(
                    "line_sign_failed",
                    line_hash=lh.hex(),
                    err=str(e)[:120],
                )
                continue
            res.stable_at = now
            res.sig = sig
            newly_signed.append(lh)
            log.info(
                "line_signed",
                line_hash=lh.hex(),
                outcome=new_outcome.name,
            )
        return newly_signed

    async def submit_threshold_lines(
        self,
        peer_attestation_store: Any,
        submitter: Any,
        *,
        threshold: int = 4,
    ) -> list[bytes]:
        """v1747 Phase 3: submit signed lines that have reached threshold.

        Iterates ``_line_resolutions`` in sorted-lineHash order. For each
        line where:
          - this validator's own ``sig`` is populated (we've signed it),
          - peer_attestation_store holds ≥ ``threshold-1`` distinct-EOA
            sigs matching the same outcome,

        builds a bundle of (own + peer) sigs and calls
        ``submitter.submit(line_hash, outcome, signers, sigs)``. On
        success or AlreadyFinalized (peer beat us), evicts the line's
        peer-attestation cache. Other errors are left for retry on the
        next loop pass — the existing chain client retry semantics handle
        transient flakes.

        Returns list of lineHashes whose pending bundle was evicted
        (either by us submitting or by a peer finalizing first).
        """
        if (
            self._chain_id is None
            or self._registry_address is None
            or self._private_key_hex is None
        ):
            return []
        if not getattr(submitter, "configured", False):
            return []

        from eth_account import Account

        own_eoa = Account.from_key(self._private_key_hex).address.lower()
        finalized: list[bytes] = []

        for lh, res in self.iter_line_resolutions_sorted():
            if res.sig is None:
                continue  # not yet signed by us; can't include in bundle
            if res.outcome == Outcome.PENDING:
                continue
            outcome_int = int(res.outcome)
            peer_sigs = peer_attestation_store.threshold_bundle(
                lh, outcome_int, threshold=threshold - 1
            ) if peer_attestation_store is not None else None
            if peer_sigs is None:
                continue  # below threshold; wait for more peer gossip

            # Combine own + peer sigs. Ensure no duplicate EOA (defense in
            # depth — peer_attestation_store excludes self, but a misconfigured
            # peer could echo our own sig back). Order: lexicographic by EOA
            # so all submitters produce the same bundle (helps idempotency).
            seen_eoas = {own_eoa}
            bundle: list[tuple[str, bytes]] = [(own_eoa, res.sig)]
            for ps in peer_sigs:
                if ps.peer_eoa in seen_eoas:
                    continue
                seen_eoas.add(ps.peer_eoa)
                bundle.append((ps.peer_eoa, ps.signature))
                if len(bundle) >= threshold:
                    break
            if len(bundle) < threshold:
                continue
            bundle.sort(key=lambda t: t[0])

            signers = [eoa for eoa, _ in bundle]
            sigs = [s for _, s in bundle]
            try:
                result = await submitter.submit(lh, outcome_int, signers, sigs)
            except Exception as e:
                log.warning("line_submit_threw", line_hash=lh.hex(), err=str(e)[:120])
                continue

            log.info(
                "line_submit_attempted",
                line_hash=lh.hex(),
                outcome=res.outcome.name,
                status=result.status,
                tx=result.tx_hash,
            )
            if result.is_terminal:
                if peer_attestation_store is not None:
                    peer_attestation_store.evict_finalized(lh)
                finalized.append(lh)
        return finalized

    async def submit_own_attestations(self, submitter: Any) -> list[bytes]:
        """v1747 Phase 7b: submit own EIP-712 sig as a 1-element bundle for
        any signed line we haven't yet attested on chain.

        Each signed line goes up as a single-signer bundle. The contract
        is idempotent on already-attested (line, signer) pairs (skip-loop,
        no revert), so re-submits are silently dropped — but we still cache
        successful submits in ``_submitted_own`` to avoid burning gas on
        no-op re-sends every loop.

        This complements ``submit_threshold_lines`` rather than replacing
        it: own-only submits emit ``LineAttested`` events even before
        peer validators have upgraded to v1747. Once ≥4 distinct
        validators have attested for the same (line, outcome) — via any
        mix of own-only or threshold bundles — the contract emits
        ``LineFinalized`` and the canonical outcome is locked in.

        Skips silently when chain context (chain_id/registry/private key)
        is unwired or the submitter is misconfigured.

        Returns lineHashes newly submitted in this call.
        """
        if (
            self._chain_id is None
            or self._registry_address is None
            or self._private_key_hex is None
        ):
            return []
        if not getattr(submitter, "configured", False):
            return []

        from eth_account import Account

        own_eoa = Account.from_key(self._private_key_hex).address.lower()
        submitted: list[bytes] = []

        for lh, res in self.iter_line_resolutions_sorted():
            if res.sig is None:
                continue
            if res.outcome == Outcome.PENDING:
                continue
            if lh in self._submitted_own:
                continue
            outcome_int = int(res.outcome)
            self._diag_last_submit_attempt_at = time.time()
            try:
                result = await submitter.submit(lh, outcome_int, [own_eoa], [res.sig])
            except Exception as e:
                log.warning("line_submit_own_threw", line_hash=lh.hex(), err=str(e)[:120])
                self._diag_submit_status_counts["threw"] = self._diag_submit_status_counts.get("threw", 0) + 1
                continue
            self._diag_submit_status_counts[result.status] = (
                self._diag_submit_status_counts.get(result.status, 0) + 1
            )
            if result.error and result.status != "submitted":
                # Keep only the error CODE, not the message body. The first
                # 80 chars of result.error encompass the contract-error name
                # (e.g. "BadSignature", "NotInValidatorSet") but stay below
                # message-body content that could leak private state.
                err_code = (result.error or "")[:80]
                self._diag_recent_submit_errors.append(
                    (time.time(), result.status, err_code)
                )
                # Keep a small ring buffer.
                if len(self._diag_recent_submit_errors) > 32:
                    self._diag_recent_submit_errors = self._diag_recent_submit_errors[-32:]
            log.info(
                "line_submit_own_attempted",
                line_hash=lh.hex(),
                outcome=res.outcome.name,
                status=result.status,
                tx=result.tx_hash,
            )
            if result.is_terminal:
                self._submitted_own.add(lh)
                submitted.append(lh)
        return submitted

    def diag_v1747(self) -> dict[str, Any]:
        """Operator-facing diagnostic snapshot for /v1/diag/v1747.

        ALLOWLIST-DRIVEN. Every field below has been audited for privacy:
        no signal_id, no buyer/purchase data, no raw signatures, no MPC
        share values, no peer IPs, no error message bodies (codes only).
        See project_v1747_first_attestation_2026_05_09 + the privacy
        invariant in CLAUDE.md.

        Designed for hotkey-signed access only. Fields that would expand
        attack surface beyond the v1747 attestation domain (e.g.
        purchase orchestrator state, MPC internals) MUST go through
        their own audit and a separate endpoint, not this one.
        """
        # Latest signed lines. lineHash + outcome + ts are content-addressed
        # public values; their per-validator timing is bounded by the 180s
        # stability soak which doesn't leak which line is the real pick
        # (we sort by lineHash for privacy §11).
        latest_signed: list[dict[str, Any]] = []
        for lh, res in self.iter_line_resolutions_sorted():
            if res.sig is None or res.stable_at is None:
                continue
            latest_signed.append(
                {
                    "line_hash": "0x" + lh.hex(),
                    "outcome": res.outcome.name,
                    "stable_at": res.stable_at,
                    "submitted_own": lh in self._submitted_own,
                }
            )
        # Cap to last 10 by stable_at. Avoids unbounded payloads + makes
        # this endpoint cheap.
        latest_signed.sort(key=lambda r: r["stable_at"], reverse=True)
        latest_signed = latest_signed[:10]

        return {
            "lines_resolutions_total": len(self._line_resolutions),
            "lines_signed_total": sum(
                1 for res in self._line_resolutions.values() if res.sig is not None
            ),
            "lines_submitted_own_total": len(self._submitted_own),
            "submit_status_counts": dict(self._diag_submit_status_counts),
            "recent_submit_errors": [
                {"ts": ts, "status": s, "error_code": c}
                for ts, s, c in self._diag_recent_submit_errors
            ],
            "last_sign_attempt_at": self._diag_last_sign_attempt_at,
            "last_submit_attempt_at": self._diag_last_submit_attempt_at,
            "latest_signed": latest_signed,
        }

    async def resolve_all_pending(
        self,
        validator_hotkey: str,
    ) -> list[str]:
        """Check all pending signals and resolve any with completed games.

        Returns a list of signal_ids that were newly resolved (outcomes stored
        on their metadata).  Settlement happens later at the audit-set level.
        """
        resolved: list[str] = []
        for meta in self.get_pending_signals():
            signal_id = await self.resolve_signal(
                meta.signal_id,
                validator_hotkey,
            )
            if signal_id is not None:
                resolved.append(signal_id)
        return resolved

    def mark_gossiped(self, signal_id: str) -> None:
        """Record that this validator just broadcast gossip for signal_id.

        Used by the reconciliation loop to round-robin re-broadcasts so
        the oldest-gossiped resolved signals get retransmitted first.
        """
        self._last_gossiped_at[_normalize_signal_id(signal_id)] = time.time()

    def get_resolved_for_reconcile(self, limit: int = 50) -> list[str]:
        """Phase A1.5 reconciliation: pick the resolved signals that have
        gone the longest without a gossip broadcast.

        Called every Nth loop iteration in main.py. Broadcasts to peers
        so any validator that missed the original gossip (was offline,
        422'd on a Pydantic cap, transient timeout) gets the outcome
        eventually. Receivers respond `already_resolved` for ones they
        have (cheap memory lookup, no ESPN replay) and `accepted` for
        ones they don't — closing the divergence gap monotonically.

        Returns up to `limit` signal_ids ordered oldest-gossiped-first.
        Signals never gossiped before are sorted ahead of every
        previously-gossiped signal.
        """
        resolved_ids: list[tuple[float, str]] = []
        for sid, meta in self._pending_signals.items():
            if not meta.resolved or not meta.outcomes:
                continue
            ts = self._last_gossiped_at.get(sid, 0.0)
            resolved_ids.append((ts, sid))
        resolved_ids.sort(key=lambda x: x[0])
        return [sid for _, sid in resolved_ids[:limit]]

    async def receive_gossip(
        self,
        signal_id: str,
        gossiped_outcomes: list[int],
        signer_hotkey: str,
        gossiped_game_date: str | None = None,
    ) -> tuple[str, list[int] | None]:
        """Process a peer-validator outcome gossip.

        Phase A2 of the outcome layer (see docs/outcome-layer-plan.md).

        Replay-verifies by independently fetching ESPN for the same game.
        On match, stores the outcomes locally so this validator's audit
        pipeline can advance without waiting for its own ESPN poll.
        On mismatch, logs the dispute and rejects — the divergence is
        queued for rung-3 miner-attestation escalation in Phase B.

        Returns (status, outcomes) where status is one of:
        - "unknown_signal": signal not registered locally yet (sender retries)
        - "already_resolved": idempotent no-op
        - "pending_local": ESPN says game not final yet on this validator
        - "accepted": replay-verify matched, signal now resolved locally
        - "disputed": replay-verify saw different outcomes; signal stays pending
        """
        signal_id = _normalize_signal_id(signal_id)
        async with self._lock:
            meta = self._pending_signals.get(signal_id)
            if meta is None:
                log.info(
                    "outcome_gossip_unknown_signal",
                    signal_id=signal_id,
                    signer=signer_hotkey[:10],
                )
                return "unknown_signal", None
            if meta.resolved:
                # Already resolved locally — idempotent. Return existing
                # outcomes so the caller can decide whether to log a
                # divergence even on the duplicate path.
                existing = [int(o) for o in (meta.outcomes or [])]
                return "already_resolved", existing
            expected_len = len(meta.lines)
            # v1679 (P1-36 partial): if sender provided game_date and we
            # don't have one locally, accept it. Receivers' replay-verify
            # then queries the SAME ESPN scoreboard as the sender, so for
            # signals committed without game_date (back-walk era), all
            # receivers converge on the same matched game and same outcomes.
            # The signature on the gossip request authenticates the sender
            # as a registered validator; a wrong game_date causes the
            # receiver's ESPN replay to find the wrong game (or none) and
            # outcomes will mismatch the gossip → disputed. So a malicious
            # game_date can't poison: it just causes dispute.
            if (
                meta.game_date is None
                and gossiped_game_date
                and len(gossiped_game_date) == 8
                and gossiped_game_date.isdigit()
            ):
                meta.game_date = gossiped_game_date

        if len(gossiped_outcomes) != expected_len:
            log.warning(
                "outcome_gossip_length_mismatch",
                signal_id=signal_id,
                gossiped_len=len(gossiped_outcomes),
                expected_len=expected_len,
                signer=signer_hotkey[:10],
            )
            return "disputed", None

        # Replay-verify by independent ESPN fetch. We do NOT trust the
        # gossiped raw_espn_summary — every receiver re-derives outcomes
        # from a fresh ESPN call so a malicious peer can't poison our
        # state by sending a forged summary.
        try:
            result = await self.fetch_event_result(
                meta.event_id,
                meta.sport,
                home_team=meta.home_team,
                away_team=meta.away_team,
                game_date=meta.game_date,
            )
        except Exception as e:
            log.warning(
                "outcome_gossip_replay_fetch_failed",
                signal_id=signal_id,
                error=str(e)[:120],
                signer=signer_hotkey[:10],
            )
            return "pending_local", None

        # Cache discovered game date back on meta (same as resolve_signal).
        if meta.game_date is None and result.raw_data:
            iso = result.raw_data.get("date", "")
            if iso and len(iso) >= 10:
                d = iso[:10].replace("-", "")
                if d.isdigit() and len(d) == 8:
                    meta.game_date = d

        if result.status not in ("final", "postponed", "cancelled"):
            # Game isn't final from this validator's view of ESPN. Possible
            # causes: regional CDN lag, transient throttling, ESPN's score
            # not yet updated. The sender's view is ahead of ours; we'll
            # pick up via our own resolve_all_pending in a future epoch.
            log.info(
                "outcome_gossip_pending_local",
                signal_id=signal_id,
                local_status=result.status,
                signer=signer_hotkey[:10],
            )
            return "pending_local", None

        derived = determine_all_outcomes(
            meta.lines,
            result,
            meta.home_team,
            meta.away_team,
        )
        derived_ints = [int(o) for o in derived]

        if derived_ints != list(gossiped_outcomes):
            log.warning(
                "outcome_gossip_disputed",
                signal_id=signal_id,
                signer=signer_hotkey[:10],
                gossiped=list(gossiped_outcomes),
                local=derived_ints,
                local_status=result.status,
                home_score=result.home_score,
                away_score=result.away_score,
            )
            return "disputed", derived_ints

        # Match. Store the resolution exactly as our own resolve_signal would.
        async with self._lock:
            meta = self._pending_signals.get(signal_id)
            if meta is None:
                # Race: signal evicted between checks. Bail.
                return "unknown_signal", None
            if meta.resolved:
                return "already_resolved", [int(o) for o in (meta.outcomes or [])]
            meta.resolved = True
            meta.outcomes = derived
            self._resolved_total += 1
            self._last_resolve_at = time.time()
            self._persist_resolution(meta)
            log.info(
                "outcome_gossip_accepted",
                signal_id=signal_id,
                signer=signer_hotkey[:10],
                outcomes=[o.name for o in derived],
            )
        # v1747 Phase 7b: also populate the line-keyed resolution cache for
        # gossip-accepted outcomes. resolve_signal does this for self-resolved
        # signals, but signals first observed via peer gossip skipped the
        # cache entirely — so sign_stable_lines + submit_own_attestations
        # never fired for gossip-only signals. With this call, both the
        # local-resolve path and the gossip-accept path produce signed
        # on-chain attestations.
        self._populate_line_resolutions(meta, result)
        return "accepted", derived_ints

    def attest(
        self,
        signal_id: str,
        validator_hotkey: str,
        outcome: Outcome,
        event_result: EventResult,
    ) -> OutcomeAttestation:
        """Record this validator's outcome attestation."""
        # Check for duplicate attestation from same validator
        existing = self._attestations.get(signal_id, [])
        for att in existing:
            if att.validator_hotkey == validator_hotkey:
                log.warning(
                    "duplicate_attestation_skipped",
                    signal_id=signal_id,
                    validator_hotkey=validator_hotkey,
                    existing_outcome=att.outcome.name,
                )
                return att

        attestation = OutcomeAttestation(
            signal_id=signal_id,
            validator_hotkey=validator_hotkey,
            outcome=outcome,
            event_result=event_result,
        )

        if signal_id not in self._attestations:
            self._attestations[signal_id] = []
        if len(self._attestations[signal_id]) < self.MAX_ATTESTATIONS_PER_SIGNAL:
            self._attestations[signal_id].append(attestation)

        log.info(
            "outcome_attested",
            signal_id=signal_id,
            outcome=outcome.name,
        )
        return attestation

    def check_consensus(
        self,
        signal_id: str,
        total_validators: int,
        quorum: float = 2 / 3,
    ) -> Outcome | None:
        """Check if 2/3+ consensus has been reached for a signal.

        Returns the consensus outcome, or None if not yet reached.
        """
        attestations = self._attestations.get(signal_id, [])
        if not attestations:
            return None

        if total_validators <= 0:
            return None

        # ≥ 2/3 quorum: ceil ensures we round up for non-integer products.
        # Previous formula (int(x) + 1) was off-by-one when total_validators
        # * quorum was exact (e.g. 3 * 2/3 = 2 → required 3/3 instead of 2/3).
        threshold = math.ceil(total_validators * quorum)

        # Count votes per outcome
        votes: dict[Outcome, int] = {}
        for a in attestations:
            votes[a.outcome] = votes.get(a.outcome, 0) + 1

        for outcome, count in votes.items():
            if count >= threshold:
                log.info(
                    "consensus_reached",
                    signal_id=signal_id,
                    outcome=outcome.name,
                    votes=count,
                    threshold=threshold,
                )
                return outcome

        return None

    # Defense-in-depth age cap (60 days). The PRIMARY correctness gate is
    # `protected_ids` — signals still referenced by an unsettled audit_set
    # are NEVER cleaned regardless of age. The age cap only catches signals
    # that have somehow fallen out of audit_set tracking (e.g. malformed
    # registrations, audit_set_store eviction bugs) so memory still bounds
    # eventually. 60 days exceeds Audit V2's 45-day SLA timeout
    # (`autoEarlyExitDelay = 3,888,000s`) so even an untracked signal lives
    # past its on-chain settlement deadline.
    DEFAULT_CLEANUP_MAX_AGE = 60 * 86400  # 60 days

    async def cleanup_resolved(
        self,
        max_age_seconds: float | None = None,
        protected_ids: set[str] | None = None,
    ) -> int:
        """Remove resolved signals and old attestations to prevent memory growth.

        v1620 (correctness-driven cleanup): a signal is removable iff
        ALL of:
          - meta.resolved is True
          - signal_id is NOT in protected_ids (callers pass
            audit_set_store.protected_signal_ids() — the set of signals in
            unsettled audit_sets that MPC may still need outcomes for)
          - now - meta.purchased_at > max_age_seconds (defense in depth so
            misbehaving callers can't make the store unbounded)

        Pre-v1620, only the age check existed. Resolved signals younger
        than 24h old were kept; everything else was wiped. Settlement that
        lagged the age cutoff lost its outcomes silently → MPC abstained
        forever → batch became a zombie. With Audit V2's 45-day SLA timeout
        that bug fired silently at scale; v1618 raised the floor to 60d as
        a stopgap, v1620 makes it actually correct (settlement-state gated).

        Returns count of removed entries. Protected by the same lock as
        resolve_signal to prevent TOCTOU races.
        """
        if max_age_seconds is None:
            max_age_seconds = self.DEFAULT_CLEANUP_MAX_AGE
        if protected_ids is None:
            protected_ids = set()
        async with self._lock:
            now = time.time()
            removed = 0

            stale_ids = [
                sid
                for sid, meta in list(self._pending_signals.items())
                if meta.resolved and sid not in protected_ids and now - meta.purchased_at > max_age_seconds
            ]
            for sid in stale_ids:
                del self._pending_signals[sid]
                self._attestations.pop(sid, None)
                removed += 1

            if removed:
                log.info("outcomes_cleaned", removed=removed, protected_count=len(protected_ids))

            return removed

    async def close(self) -> None:
        try:
            await asyncio.wait_for(self._espn.close(), timeout=5.0)
        except TimeoutError:
            log.warning("outcome_attestor_close_timeout")
        except Exception as e:
            log.warning("outcome_attestor_close_error", error=str(e))
