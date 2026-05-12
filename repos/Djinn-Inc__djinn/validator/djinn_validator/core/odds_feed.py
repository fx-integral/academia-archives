"""The Odds API proxy with multi-key rotation, cache, and negative cache.

Ported 1:1 from `web/lib/oddsKeys.ts` + `web/app/api/odds/route.ts` +
`web/app/api/odds/alt/route.ts` so behavior stays identical to the Next
implementation during Sprint-A cutover. Both /v1/odds and /v1/odds/{sport}/
events/{event_id}/alt share rotation state because The Odds API quota is
per-key, not per-endpoint; a 429 seen on one endpoint must advance the
pointer for the other.

Module-level state is intentional (single-process validator; mirrors TS
module singleton semantics). Torn reads under concurrency are benign --
the cost is at most a slightly-suboptimal rotation choice, never lost data.
"""

from __future__ import annotations

import asyncio
import os
import time
from dataclasses import dataclass
from typing import Any

import httpx

ODDS_API_BASE = "https://api.the-odds-api.com"

ALLOWED_SPORTS = frozenset(
    {
        "basketball_nba",
        "americanfootball_nfl",
        "americanfootball_ncaaf",
        "basketball_ncaab",
        "baseball_mlb",
        "icehockey_nhl",
        "soccer_epl",
        "soccer_spain_la_liga",
        "soccer_germany_bundesliga",
        "soccer_italy_serie_a",
        "soccer_france_ligue_one",
        "soccer_uefa_champs_league",
        "soccer_usa_mls",
        "mma_mixed_martial_arts",
        "tennis_atp_french_open",
        "golf_pga_championship_winner",
        "boxing_boxing",
    }
)

ALLOWED_MARKETS = frozenset({"spreads", "totals", "h2h"})

SPORTS_CATALOG = (
    {"key": "basketball_nba", "name": "NBA", "category": "Basketball"},
    {"key": "basketball_ncaab", "name": "NCAA Basketball", "category": "Basketball"},
    {"key": "americanfootball_nfl", "name": "NFL", "category": "Football"},
    {"key": "americanfootball_ncaaf", "name": "NCAA Football", "category": "Football"},
    {"key": "baseball_mlb", "name": "MLB", "category": "Baseball"},
    {"key": "icehockey_nhl", "name": "NHL", "category": "Hockey"},
    {"key": "soccer_epl", "name": "Premier League", "category": "Soccer"},
    {"key": "soccer_usa_mls", "name": "MLS", "category": "Soccer"},
)

# Cache TTLs (seconds) — mirror Next exactly.
FRESH_TTL_S = 60
STALE_TTL_S = 300  # /v1/odds
STALE_ALT_TTL_S = 120  # /v1/odds/{sport}/events/{id}/alt
NEG_TTL_S = 30  # shared negative cache
UPSTREAM_TIMEOUT_S = 30.0
UPSTREAM_TIMEOUT_ALT_S = 10.0


@dataclass
class CacheEntry:
    data: Any
    expires_at: float  # monotonic seconds
    stale_at: float


# Shared rotation pointer across /v1/odds and /v1/odds/*/alt.
_rotation_start: int = 0

# Cache: (sport, markets) -> entry. Separate cache keyspace for main vs alt
# because their payload shape and TTL differ.
_cache_main: dict[str, CacheEntry] = {}
_cache_alt: dict[str, CacheEntry] = {}

# Negative cache: scope-key -> expiry (monotonic seconds).
_neg_cache: dict[str, float] = {}

# Track in-flight background revalidations so we don't dogpile the same
# upstream URL while serving stale content.
_revalidating: set[str] = set()


def _env_keys() -> list[str]:
    """Read rotation keys. Prefer ODDS_API_KEYS (comma-split), fall back to legacy ODDS_API_KEY."""
    multi = os.getenv("ODDS_API_KEYS", "")
    if multi:
        keys = [k.strip() for k in multi.split(",") if k.strip()]
        if keys:
            return keys
    single = os.getenv("ODDS_API_KEY", "").strip()
    return [single] if single else []


def get_api_keys() -> list[str]:
    """Public accessor; patched in tests."""
    return _env_keys()


def is_key_failure(status: int) -> bool:
    """A status that justifies advancing past the current key."""
    return status == 401 or status == 403 or status == 429 or status >= 500


def _rotation_start_for(n: int) -> int:
    if n <= 0:
        return 0
    return _rotation_start % n


def _hold_rotation(idx: int) -> None:
    global _rotation_start
    _rotation_start = idx


def _advance_rotation(idx: int) -> None:
    global _rotation_start
    _rotation_start = idx + 1


def _neg_key(scope: str, sport: str, extra: str = "") -> str:
    return f"{scope}\x01{sport}\x01{extra}"


def _neg_get(key: str) -> bool:
    until = _neg_cache.get(key)
    if until is None:
        return False
    if until <= time.monotonic():
        _neg_cache.pop(key, None)
        return False
    return True


def _neg_set(key: str) -> None:
    _neg_cache[key] = time.monotonic() + NEG_TTL_S
    if len(_neg_cache) > 128:
        # Drop oldest half to bound memory.
        for k in list(_neg_cache.keys())[:64]:
            _neg_cache.pop(k, None)


def _evict_stale(cache: dict[str, CacheEntry]) -> None:
    now = time.monotonic()
    for key in list(cache.keys()):
        if cache[key].stale_at <= now:
            cache.pop(key, None)
    if len(cache) > 50:
        for key in list(cache.keys())[: len(cache) - 50]:
            cache.pop(key, None)


def validate_sport(sport: str | None) -> str:
    if not sport or sport not in ALLOWED_SPORTS:
        raise _InvalidRequest(f"Invalid sport. Allowed: {', '.join(sorted(ALLOWED_SPORTS))}")
    return sport


def validate_markets(raw: str | None) -> str:
    markets_csv = raw or "spreads,totals,h2h"
    filtered = [m for m in markets_csv.split(",") if m in ALLOWED_MARKETS]
    if not filtered:
        raise _InvalidRequest("No valid markets specified")
    return ",".join(filtered)


class _InvalidRequest(Exception):
    """Raised for 400-bad-request style input errors."""


class _NoKeysConfigured(Exception):
    """Raised when ODDS_API_KEYS (or legacy ODDS_API_KEY) is unset."""


class _UpstreamFailed(Exception):
    """All keys exhausted with retriable failures."""

    def __init__(self, last_status: int, message: str):
        super().__init__(message)
        self.last_status = last_status


async def fetch_upcoming(sport: str, markets: str, client: httpx.AsyncClient | None = None) -> Any:
    """Fetch upcoming odds for `sport`. Fresh-or-stale cache with background revalidation.

    Raises _NoKeysConfigured / _UpstreamFailed on failure. Returns raw Odds-API
    JSON (shape: `OddsEvent[]` per `web/lib/odds.ts`).
    """
    keys = get_api_keys()
    if not keys:
        raise _NoKeysConfigured("Odds API key not configured (set ODDS_API_KEYS or ODDS_API_KEY)")

    cache_key = f"{sport}:{markets}"
    _evict_stale(_cache_main)

    neg_key = _neg_key("odds", sport, markets)
    cached = _cache_main.get(cache_key)
    if cached is None and _neg_get(neg_key):
        raise _UpstreamFailed(502, "Odds provider temporarily unavailable (all keys failed recently)")

    now = time.monotonic()
    if cached is not None:
        if cached.expires_at > now:
            return cached.data
        if cached.stale_at > now:
            # Serve stale; revalidate in background if no revalidation in flight.
            if cache_key not in _revalidating:
                _revalidating.add(cache_key)
                asyncio.create_task(_revalidate_main(keys, sport, markets, cache_key, client))
            return cached.data

    return await _fetch_main(keys, sport, markets, cache_key, client)


async def _revalidate_main(
    keys: list[str], sport: str, markets: str, cache_key: str, client: httpx.AsyncClient | None
) -> None:
    try:
        await _fetch_main(keys, sport, markets, cache_key, client)
    except Exception:
        # Swallow revalidation errors — stale data is already served.
        pass
    finally:
        _revalidating.discard(cache_key)


async def _fetch_main(
    keys: list[str], sport: str, markets: str, cache_key: str, client: httpx.AsyncClient | None
) -> Any:
    n = len(keys)
    start = _rotation_start_for(n)
    last_status = 0
    owns_client = client is None
    c = client or httpx.AsyncClient(timeout=UPSTREAM_TIMEOUT_S)
    try:
        # Keep upcoming-only filter identical to Next (no milliseconds in ISO timestamp).
        commence = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        for i in range(n):
            idx = (start + i) % n
            params = {
                "apiKey": keys[idx],
                "regions": "us",
                "markets": markets,
                "oddsFormat": "decimal",
                "commenceTimeFrom": commence,
            }
            try:
                resp = await c.get(f"{ODDS_API_BASE}/v4/sports/{sport}/odds", params=params)
            except (httpx.TimeoutException, httpx.TransportError):
                _advance_rotation(idx)
                continue

            if resp.status_code == 200:
                data = resp.json()
                now = time.monotonic()
                _cache_main[cache_key] = CacheEntry(
                    data=data,
                    expires_at=now + FRESH_TTL_S,
                    stale_at=now + STALE_TTL_S,
                )
                _hold_rotation(idx)
                return data

            last_status = resp.status_code
            if is_key_failure(resp.status_code):
                _advance_rotation(idx)
                continue
            # 400/404/422 etc. — same across all keys, don't burn quota.
            raise _UpstreamFailed(resp.status_code, f"Odds provider error ({resp.status_code})")

        _neg_set(_neg_key("odds", sport, markets))
        raise _UpstreamFailed(last_status or 502, f"All Odds API keys failed (last status {last_status})")
    finally:
        if owns_client:
            await c.aclose()


async def fetch_event_alt(sport: str, event_id: str, client: httpx.AsyncClient | None = None) -> Any:
    """Fetch alternate spreads + totals for a specific event.

    Shares rotation + negative cache with `fetch_upcoming` so quota
    accounting is unified. Cache TTLs are shorter (60s fresh / 120s stale)
    to match `s-maxage=60, stale-while-revalidate=120` from the Next alt route.
    """
    keys = get_api_keys()
    if not keys:
        raise _NoKeysConfigured("Odds API key not configured (set ODDS_API_KEYS or ODDS_API_KEY)")

    if not sport or not event_id:
        raise _InvalidRequest("sport and event_id required")

    cache_key = f"{sport}:{event_id}"
    _evict_stale(_cache_alt)

    neg_key = _neg_key("odds-alt", sport, event_id)
    cached = _cache_alt.get(cache_key)
    if cached is None and _neg_get(neg_key):
        raise _UpstreamFailed(502, "Odds provider temporarily unavailable (all keys failed recently)")

    now = time.monotonic()
    if cached is not None:
        if cached.expires_at > now:
            return cached.data
        if cached.stale_at > now:
            rev_key = f"alt:{cache_key}"
            if rev_key not in _revalidating:
                _revalidating.add(rev_key)
                asyncio.create_task(_revalidate_alt(keys, sport, event_id, cache_key, client))
            return cached.data

    return await _fetch_alt(keys, sport, event_id, cache_key, client)


async def _revalidate_alt(
    keys: list[str], sport: str, event_id: str, cache_key: str, client: httpx.AsyncClient | None
) -> None:
    try:
        await _fetch_alt(keys, sport, event_id, cache_key, client)
    except Exception:
        pass
    finally:
        _revalidating.discard(f"alt:{cache_key}")


async def _fetch_alt(
    keys: list[str], sport: str, event_id: str, cache_key: str, client: httpx.AsyncClient | None
) -> Any:
    n = len(keys)
    start = _rotation_start_for(n)
    last_status = 0
    owns_client = client is None
    c = client or httpx.AsyncClient(timeout=UPSTREAM_TIMEOUT_ALT_S)
    try:
        for i in range(n):
            idx = (start + i) % n
            params = {
                "apiKey": keys[idx],
                "regions": "us",
                "markets": "alternate_spreads,alternate_totals",
                "oddsFormat": "decimal",
            }
            try:
                resp = await c.get(
                    f"{ODDS_API_BASE}/v4/sports/{sport}/events/{event_id}/odds",
                    params=params,
                )
            except (httpx.TimeoutException, httpx.TransportError):
                _advance_rotation(idx)
                continue

            if resp.status_code == 200:
                data = resp.json()
                now = time.monotonic()
                _cache_alt[cache_key] = CacheEntry(
                    data=data,
                    expires_at=now + FRESH_TTL_S,
                    stale_at=now + STALE_ALT_TTL_S,
                )
                _hold_rotation(idx)
                return data

            last_status = resp.status_code
            if is_key_failure(resp.status_code):
                _advance_rotation(idx)
                continue
            raise _UpstreamFailed(resp.status_code, f"Odds provider error ({resp.status_code})")

        _neg_set(_neg_key("odds-alt", sport, event_id))
        raise _UpstreamFailed(last_status or 502, f"All Odds API keys failed (last status {last_status})")
    finally:
        if owns_client:
            await c.aclose()


def reset_state_for_tests() -> None:
    global _rotation_start
    _rotation_start = 0
    _cache_main.clear()
    _cache_alt.clear()
    _neg_cache.clear()
    _revalidating.clear()
