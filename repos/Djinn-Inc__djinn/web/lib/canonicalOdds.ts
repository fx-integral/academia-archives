/**
 * Canonical internal odds schema.
 *
 * Djinn currently reads The Odds API's exact response shape directly. That
 * makes it impossible to switch providers without rewriting every layer that
 * touches odds. This module defines a provider-neutral canonical schema and
 * an adapter interface that translators implement once per provider. After
 * the migration, every layer (validator, miner, web client, audit) speaks
 * canonical odds and the adapter is the only place that knows about a
 * specific provider's quirks.
 *
 * Critically: miners (not geniuses) pick the source. A genius doesn't say
 * "use The Odds API for this signal" — the protocol picks via miner consensus
 * across whatever providers each miner has adapters for. Adding a new
 * provider is just a new adapter file. See
 * ~/.claude/projects/-home-user-djinn/memory/project_canonical_odds_schema.md.
 *
 * This file is the schema + interface only, plus the first adapter (The Odds
 * API). The integration into validator and web client paths lands behind the
 * DJINN_FF_CANONICAL_ODDS feature flag in follow-up commits.
 */

// ---------------------------------------------------------------------------
// Canonical types
// ---------------------------------------------------------------------------

/** Sport identifier in canonical form. The string values are deliberately
 * stable and provider-independent — no "basketball_nba" leaking from The
 * Odds API. */
export type CanonicalSport =
  | "nba"
  | "nfl"
  | "mlb"
  | "nhl"
  | "ncaaf"
  | "ncaab"
  | "epl"
  | "mls"
  | "other";

/** Market type. Stable across providers. */
export type CanonicalMarket = "moneyline" | "spread" | "total" | "other";

/** Side of a market. For moneyline, this is "home" or "away". For spreads,
 * also "home"/"away" with a separate `line` field. For totals, "over" or
 * "under". */
export type CanonicalSide = "home" | "away" | "over" | "under";

/** A bookmaker (sportsbook) the price came from, in canonical form.
 * Uppercase, no spaces, stable across providers. */
export type CanonicalBookmaker = string;

/** A normalized event. */
export interface CanonicalEvent {
  /** Stable identifier across providers. Adapters mint this from the
   * provider's event_id; if multiple providers describe the same game with
   * different ids, the validator deduplicates by (sport, home, away,
   * commenceTime). */
  id: string;
  sport: CanonicalSport;
  homeTeam: string;
  awayTeam: string;
  /** Unix milliseconds since epoch. */
  commenceTime: number;
}

/** A single price observation from one bookmaker on one market on one event
 * at one moment in time. */
export interface CanonicalOdds {
  event: CanonicalEvent;
  market: CanonicalMarket;
  side: CanonicalSide;
  /** Decimal price (e.g. 1.95). Adapters convert from American/fractional. */
  decimalPrice: number;
  /** Optional spread or total line value (e.g. -3.5 for a spread, 220.5 for
   * a total). Null/undefined for moneyline. */
  line?: number | null;
  bookmaker: CanonicalBookmaker;
  /** Unix milliseconds when this observation was fetched from the upstream
   * source. NOT when the adapter ran — adapters copy through the upstream
   * timestamp when present, or use the current time as a fallback. */
  fetchedAt: number;
  /** Provider tag for traceability. Used by the consensus circuit breaker
   * to score per-source accuracy. */
  source: string;
}

/** A canonical odds query: ask "what are the prices for this event/market
 * across these bookmakers?" Adapters use this to issue provider-specific
 * fetches. */
export interface CanonicalOddsQuery {
  sport: CanonicalSport;
  market: CanonicalMarket;
  /** If provided, restrict the query to this set of bookmakers. */
  bookmakers?: CanonicalBookmaker[];
  /** If provided, restrict to this specific event. */
  eventId?: string;
}

// ---------------------------------------------------------------------------
// Provider adapter interface
// ---------------------------------------------------------------------------

/** An OddsAdapter knows how to talk to one upstream odds source and
 * translate its responses into canonical types. Each adapter is a single
 * file that lives miner-side. Adding a new provider is one new adapter
 * file plus an entry in the adapter registry. */
export interface OddsAdapter {
  /** Stable provider tag, used as the `source` field on every CanonicalOdds
   * this adapter produces. Examples: "the-odds-api", "pinnacle", "oddsjam". */
  readonly source: string;

  /** Whether this adapter can fetch data for the given canonical sport.
   * Returns false if the upstream provider does not cover the sport. */
  supportsSport(sport: CanonicalSport): boolean;

  /** Fetch current odds matching the query. Returns canonical observations,
   * one per (event, market, side, bookmaker) tuple. May return an empty
   * array. Throws if the upstream is unreachable or returns malformed
   * data; adapters do NOT silently swallow errors. */
  fetchOdds(query: CanonicalOddsQuery): Promise<CanonicalOdds[]>;
}

// ---------------------------------------------------------------------------
// Sport key translation (provider-neutral)
// ---------------------------------------------------------------------------

const ODDS_API_SPORT_TO_CANONICAL: Record<string, CanonicalSport> = {
  basketball_nba: "nba",
  americanfootball_nfl: "nfl",
  baseball_mlb: "mlb",
  icehockey_nhl: "nhl",
  americanfootball_ncaaf: "ncaaf",
  basketball_ncaab: "ncaab",
  soccer_epl: "epl",
  soccer_usa_mls: "mls",
};

const CANONICAL_TO_ODDS_API_SPORT: Record<CanonicalSport, string> = {
  nba: "basketball_nba",
  nfl: "americanfootball_nfl",
  mlb: "baseball_mlb",
  nhl: "icehockey_nhl",
  ncaaf: "americanfootball_ncaaf",
  ncaab: "basketball_ncaab",
  epl: "soccer_epl",
  mls: "soccer_usa_mls",
  other: "other",
};

const ODDS_API_MARKET_TO_CANONICAL: Record<string, CanonicalMarket> = {
  h2h: "moneyline",
  spreads: "spread",
  totals: "total",
};

const CANONICAL_TO_ODDS_API_MARKET: Record<CanonicalMarket, string> = {
  moneyline: "h2h",
  spread: "spreads",
  total: "totals",
  other: "other",
};

export function oddsApiSportToCanonical(key: string): CanonicalSport {
  return ODDS_API_SPORT_TO_CANONICAL[key] ?? "other";
}

export function canonicalToOddsApiSport(sport: CanonicalSport): string {
  return CANONICAL_TO_ODDS_API_SPORT[sport];
}

export function oddsApiMarketToCanonical(key: string): CanonicalMarket {
  return ODDS_API_MARKET_TO_CANONICAL[key] ?? "other";
}

export function canonicalToOddsApiMarket(market: CanonicalMarket): string {
  return CANONICAL_TO_ODDS_API_MARKET[market];
}

// ---------------------------------------------------------------------------
// American/decimal conversion
// ---------------------------------------------------------------------------

export function americanToDecimal(american: number): number {
  if (american === 0) return 0;
  if (american > 0) return 1 + american / 100;
  return 1 + 100 / Math.abs(american);
}

export function decimalToAmerican(decimal: number): number {
  if (decimal <= 1) return 0;
  if (decimal >= 2) return Math.round((decimal - 1) * 100);
  return Math.round(-100 / (decimal - 1));
}

// ---------------------------------------------------------------------------
// Bookmaker normalization
// ---------------------------------------------------------------------------

const BOOKMAKER_ALIASES: Record<string, string> = {
  draftkings: "DRAFTKINGS",
  fanduel: "FANDUEL",
  betmgm: "BETMGM",
  caesars: "CAESARS",
  pinnacle: "PINNACLE",
  pointsbetus: "POINTSBET",
  pointsbet: "POINTSBET",
  bet365: "BET365",
  williamhill_us: "WILLIAMHILL",
  williamhill: "WILLIAMHILL",
  espnbet: "ESPNBET",
  fanatics: "FANATICS",
};

/** Normalize a bookmaker key from any provider into the canonical form.
 * Adapters call this on every price observation so the rest of the system
 * never sees provider-specific spellings. */
export function canonicalBookmaker(key: string): CanonicalBookmaker {
  if (!key) return "UNKNOWN";
  const lower = key.toLowerCase().trim();
  const alias = BOOKMAKER_ALIASES[lower];
  if (alias) return alias;
  return lower.toUpperCase();
}

// ---------------------------------------------------------------------------
// Adapter: The Odds API
// ---------------------------------------------------------------------------

/** Subset of The Odds API response shape we need to translate. The full
 * type lives in web/lib/odds.ts; we re-declare the bits we touch here so
 * the adapter is self-contained and can be unit-tested without importing
 * the rest of the codebase. */
export interface OddsApiResponseEvent {
  id: string;
  sport_key: string;
  commence_time: string; // ISO 8601
  home_team: string;
  away_team: string;
  bookmakers?: Array<{
    key: string;
    title?: string;
    last_update?: string;
    markets?: Array<{
      key: string;
      outcomes?: Array<{
        name: string;
        price: number;
        point?: number;
      }>;
    }>;
  }>;
}

/** Convert The Odds API event JSON into a list of canonical odds observations. */
export function theOddsApiToCanonical(
  event: OddsApiResponseEvent,
  options: { fetchedAt?: number } = {},
): CanonicalOdds[] {
  const sport = oddsApiSportToCanonical(event.sport_key);
  const canonicalEvent: CanonicalEvent = {
    id: event.id,
    sport,
    homeTeam: event.home_team,
    awayTeam: event.away_team,
    commenceTime: Date.parse(event.commence_time),
  };

  const fetchedAt = options.fetchedAt ?? Date.now();
  const result: CanonicalOdds[] = [];

  for (const book of event.bookmakers ?? []) {
    const bookmaker = canonicalBookmaker(book.key);
    const bookFetchedAt = book.last_update
      ? Date.parse(book.last_update)
      : fetchedAt;

    for (const market of book.markets ?? []) {
      const canonicalMarket = oddsApiMarketToCanonical(market.key);
      if (canonicalMarket === "other") continue;

      for (const outcome of market.outcomes ?? []) {
        const side = inferSide(canonicalMarket, outcome.name, event);
        if (side === null) continue;
        result.push({
          event: canonicalEvent,
          market: canonicalMarket,
          side,
          decimalPrice: outcome.price,
          line: outcome.point ?? null,
          bookmaker,
          fetchedAt: bookFetchedAt,
          source: "the-odds-api",
        });
      }
    }
  }

  return result;
}

function inferSide(
  market: CanonicalMarket,
  outcomeName: string,
  event: OddsApiResponseEvent,
): CanonicalSide | null {
  if (market === "total") {
    const lower = outcomeName.toLowerCase();
    if (lower === "over") return "over";
    if (lower === "under") return "under";
    return null;
  }
  if (outcomeName === event.home_team) return "home";
  if (outcomeName === event.away_team) return "away";
  return null;
}

/** Reference implementation of the OddsAdapter interface for The Odds API.
 * The actual fetcher lives elsewhere; this class is the canonical
 * translation glue. */
export class TheOddsApiAdapter implements OddsAdapter {
  readonly source = "the-odds-api";

  constructor(
    private readonly fetcher: (
      query: CanonicalOddsQuery,
    ) => Promise<OddsApiResponseEvent[]>,
  ) {}

  supportsSport(sport: CanonicalSport): boolean {
    return sport !== "other";
  }

  async fetchOdds(query: CanonicalOddsQuery): Promise<CanonicalOdds[]> {
    const events = await this.fetcher(query);
    const observations: CanonicalOdds[] = [];
    for (const event of events) {
      observations.push(...theOddsApiToCanonical(event));
    }
    return filterByQuery(observations, query);
  }
}

function filterByQuery(
  observations: CanonicalOdds[],
  query: CanonicalOddsQuery,
): CanonicalOdds[] {
  return observations.filter((o) => {
    if (o.event.sport !== query.sport) return false;
    if (query.market && o.market !== query.market) return false;
    if (query.eventId && o.event.id !== query.eventId) return false;
    if (query.bookmakers && query.bookmakers.length > 0) {
      const allowed = new Set(query.bookmakers.map((b) => canonicalBookmaker(b)));
      if (!allowed.has(o.bookmaker)) return false;
    }
    return true;
  });
}

// ---------------------------------------------------------------------------
// Adapter registry (for future use; not consumed yet)
// ---------------------------------------------------------------------------

/** Adapters register themselves here so the validator can iterate over all
 * known providers when fanning out a query. The registry is global because
 * adapters are stateless modules; if you need per-instance state, build
 * your own registry locally. */
export class AdapterRegistry {
  private adapters = new Map<string, OddsAdapter>();

  register(adapter: OddsAdapter): void {
    if (this.adapters.has(adapter.source)) {
      throw new Error(`adapter ${adapter.source} already registered`);
    }
    this.adapters.set(adapter.source, adapter);
  }

  get(source: string): OddsAdapter | undefined {
    return this.adapters.get(source);
  }

  all(): OddsAdapter[] {
    return Array.from(this.adapters.values());
  }

  supportingSport(sport: CanonicalSport): OddsAdapter[] {
    return this.all().filter((a) => a.supportsSport(sport));
  }
}
