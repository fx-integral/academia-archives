"""Consensus reducer for canonical odds observations from multiple miners.

The validator queries N miners for the same (sport, markets) tuple
via /v1/odds/canonical. Each miner returns its provider's
observations projected into the canonical schema. This module
takes all those observations and emits ONE consensus observation
per (event_id, market, side, bookmaker) tuple, using the median
decimal_price across miners that reported it.

Median is chosen over trimmed mean because:
  - The number of miners reporting any given tuple is typically
    small (3-7 today on SN103). Trimming is noisy at that size.
  - Median is naturally robust to one outlier miner without
    needing a trim parameter.
  - Median matches the behavior of the existing miner-fanout
    /v1/check which already takes union-of-available.

Scoring policy (used by scoring.py later): each miner's reported
price is compared to the consensus price, and distance contributes
to a per-miner accuracy score. This module doesn't do that scoring
itself — it just produces the consensus output.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from statistics import median


@dataclass(frozen=True)
class CanonicalObservationLite:
    """Subset of CanonicalOdds used by the consensus reducer.

    The miner-side canonical module defines the full dataclass;
    this module takes dict-shaped observations (as returned by
    /v1/odds/canonical) so the reducer doesn't depend on the miner
    package for its types.
    """

    event_id: str
    sport: str
    home_team: str
    away_team: str
    commence_time_ms: int
    market: str
    side: str
    decimal_price: float
    line: float | None
    bookmaker: str
    fetched_at_ms: int
    source: str


@dataclass
class ConsensusObservation:
    """One consensus observation after the reducer runs.

    ``consensus_price`` is the median across ``miner_prices``.
    ``miner_count`` is how many miners contributed a price to this
    group (lets downstream code require e.g. >=3 miners).
    """

    event_id: str
    sport: str
    home_team: str
    away_team: str
    commence_time_ms: int
    market: str
    side: str
    bookmaker: str
    consensus_price: float
    consensus_line: float | None
    miner_count: int
    miner_prices: list[float] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)
    latest_fetched_at_ms: int = 0


def reduce_observations_to_consensus(
    per_miner: list[list[dict]],
    min_miners: int = 1,
) -> list[ConsensusObservation]:
    """Group observations by (event, market, side, bookmaker) and
    return one consensus observation per group.

    Args:
        per_miner: list (one per miner) of lists of observation dicts
            in the shape returned by the miner-side /v1/odds/canonical
            endpoint.
        min_miners: drop groups where fewer than this many miners
            contributed a price. Defaults to 1 so the reducer is
            usable even in single-miner test environments; production
            should set this to at least 3.

    Returns:
        list of ConsensusObservation, sorted by (event_id, market,
        side, bookmaker) for determinism.
    """
    # group_key -> list of (miner_idx, observation dict)
    groups: dict[
        tuple[str, str, str, str, str],
        list[tuple[int, dict]],
    ] = defaultdict(list)

    for miner_idx, obs_list in enumerate(per_miner):
        if not isinstance(obs_list, list):
            continue
        for obs in obs_list:
            if not isinstance(obs, dict):
                continue
            try:
                key = (
                    str(obs.get("event_id", "")),
                    str(obs.get("sport", "")),
                    str(obs.get("market", "")),
                    str(obs.get("side", "")),
                    str(obs.get("bookmaker", "")),
                )
            except Exception:
                continue
            if "" in (key[0], key[2], key[3], key[4]):
                # Drop malformed entries missing a group key component.
                continue
            groups[key].append((miner_idx, obs))

    results: list[ConsensusObservation] = []
    for key, entries in groups.items():
        prices: list[float] = []
        sources: list[str] = []
        latest_ts = 0
        home_team = ""
        away_team = ""
        commence_time_ms = 0
        line: float | None = None
        line_disagree = False

        for _, obs in entries:
            try:
                price = float(obs.get("decimal_price", 0))
            except (TypeError, ValueError):
                continue
            if price <= 0:
                continue
            prices.append(price)
            src = str(obs.get("source", ""))
            if src:
                sources.append(src)
            try:
                ts = int(obs.get("fetched_at_ms", 0))
                if ts > latest_ts:
                    latest_ts = ts
            except (TypeError, ValueError):
                pass
            if not home_team:
                home_team = str(obs.get("home_team", ""))
            if not away_team:
                away_team = str(obs.get("away_team", ""))
            if commence_time_ms == 0:
                try:
                    commence_time_ms = int(obs.get("commence_time_ms", 0))
                except (TypeError, ValueError):
                    pass
            raw_line = obs.get("line")
            if raw_line is not None:
                try:
                    line_val = float(raw_line)
                except (TypeError, ValueError):
                    continue
                if line is None:
                    line = line_val
                elif line != line_val:
                    # Miners disagree on the line value for the same
                    # (event, market, side, book). Keep the first
                    # reported line but mark the group as disagreeing
                    # so downstream code can decide whether to accept
                    # or drop the group.
                    line_disagree = True

        if len(prices) < min_miners:
            continue

        consensus_price = float(median(prices))
        # Use unique source names to report HOW it was sourced.
        unique_sources = sorted(set(sources))

        results.append(
            ConsensusObservation(
                event_id=key[0],
                sport=key[1],
                home_team=home_team,
                away_team=away_team,
                commence_time_ms=commence_time_ms,
                market=key[2],
                side=key[3],
                bookmaker=key[4],
                consensus_price=consensus_price,
                consensus_line=line if not line_disagree else None,
                miner_count=len(prices),
                miner_prices=sorted(prices),
                sources=unique_sources,
                latest_fetched_at_ms=latest_ts,
            )
        )

    results.sort(key=lambda c: (c.event_id, c.market, c.side, c.bookmaker))
    return results


def miner_distance_scores(
    per_miner: list[list[dict]],
    consensus: list[ConsensusObservation],
) -> list[float]:
    """Score each miner by average relative distance from consensus.

    Lower is better (0 = exact match on every group). Miners that
    reported no observations in common with the consensus get a
    neutral score of 1.0 (one full decimal-price away, which is
    the natural scale of the numbers being compared).

    Returns a list of floats with length == len(per_miner).
    """
    # Build a fast lookup: (event, market, side, bookmaker) -> consensus price
    consensus_by_key: dict[tuple[str, str, str, str], float] = {
        (c.event_id, c.market, c.side, c.bookmaker): c.consensus_price for c in consensus
    }

    scores: list[float] = []
    for obs_list in per_miner:
        if not isinstance(obs_list, list) or not obs_list:
            scores.append(1.0)
            continue
        distances: list[float] = []
        for obs in obs_list:
            if not isinstance(obs, dict):
                continue
            key = (
                str(obs.get("event_id", "")),
                str(obs.get("market", "")),
                str(obs.get("side", "")),
                str(obs.get("bookmaker", "")),
            )
            cons_price = consensus_by_key.get(key)
            if cons_price is None or cons_price <= 0:
                continue
            try:
                miner_price = float(obs.get("decimal_price", 0))
            except (TypeError, ValueError):
                continue
            if miner_price <= 0:
                continue
            distances.append(abs(miner_price - cons_price) / cons_price)
        if not distances:
            scores.append(1.0)
        else:
            scores.append(sum(distances) / len(distances))
    return scores
