import { NextRequest, NextResponse } from "next/server";
import {
  getOddsApiKeys,
  rotationStart,
  holdRotation,
  advanceRotation,
  isOddsKeyFailure,
  getNegCache,
  setNegCache,
  negCacheKey,
} from "@/lib/oddsKeys";

/**
 * Proxies requests to The Odds API, keeping the API key server-side.
 *
 * GET /api/odds?sport=basketball_nba&markets=spreads,totals,h2h
 *
 * Query params:
 *   sport   — The Odds API sport key (required)
 *   markets — Comma-separated markets (default: "spreads,totals,h2h")
 *
 * Returns the raw event array from The Odds API.
 *
 * Key rotation + negative caching live in `@/lib/oddsKeys` so the main
 * and `/alt` routes share rotation state — a 429 seen here rotates the
 * pointer for the alt route too, instead of both routes dogpiling the
 * same rate-limited key.
 */

const ODDS_API_BASE = "https://api.the-odds-api.com";

const ALLOWED_SPORTS = new Set([
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
]);
const ALLOWED_MARKETS = new Set(["spreads", "totals", "h2h"]);
const CACHE_TTL_SECONDS = 60;
const STALE_TTL_SECONDS = 300; // Serve stale data for up to 5 min while revalidating

let cachedData: Map<string, { data: unknown; expiresAt: number; staleAt: number }> = new Map();
// Track in-flight background revalidations to avoid duplicate fetches
const revalidating: Set<string> = new Set();

// Simple sliding-window rate limiter per IP
const RATE_LIMIT_WINDOW_MS = 60_000; // 1 minute
const RATE_LIMIT_MAX_REQUESTS = 120; // 120 requests per minute per IP (v2 signal creation fetches alt lines per game)
const rateLimitMap: Map<string, number[]> = new Map();

function getRateLimitKey(request: NextRequest): string {
  // Prefer Next.js-provided IP (set by trusted proxy/platform), fall back to
  // x-real-ip (single value, harder to spoof than x-forwarded-for).
  // Avoid x-forwarded-for as primary source since it is trivially spoofable.
  return (
    request.ip ||
    request.headers.get("x-real-ip") ||
    request.headers.get("x-forwarded-for")?.split(",")[0]?.trim() ||
    "unknown"
  );
}

function isRateLimited(ip: string): boolean {
  const now = Date.now();
  const timestamps = rateLimitMap.get(ip) || [];
  const recent = timestamps.filter((t) => t > now - RATE_LIMIT_WINDOW_MS);
  if (recent.length >= RATE_LIMIT_MAX_REQUESTS) return true;
  recent.push(now);
  rateLimitMap.set(ip, recent);
  // Evict stale IPs periodically
  if (rateLimitMap.size > 1000) {
    for (const [key, ts] of rateLimitMap) {
      if (ts.every((t) => t <= now - RATE_LIMIT_WINDOW_MS)) {
        rateLimitMap.delete(key);
      }
    }
  }
  return false;
}

function evictStale() {
  const now = Date.now();
  for (const [key, entry] of cachedData) {
    if (entry.staleAt <= now) cachedData.delete(key);
  }
  if (cachedData.size > 50) {
    const keys = [...cachedData.keys()];
    for (const k of keys.slice(0, keys.length - 50)) cachedData.delete(k);
  }
}

export async function GET(request: NextRequest) {
  if (isRateLimited(getRateLimitKey(request))) {
    return NextResponse.json(
      { error: "Too many requests. Please try again later." },
      { status: 429 },
    );
  }

  const apiKeys = getOddsApiKeys();
  if (apiKeys.length === 0) {
    return NextResponse.json(
      { error: "Odds API key not configured (set ODDS_API_KEYS or ODDS_API_KEY env var)" },
      { status: 503 },
    );
  }

  const { searchParams } = new URL(request.url);
  const sport = searchParams.get("sport");
  if (!sport || !ALLOWED_SPORTS.has(sport)) {
    return NextResponse.json(
      {
        error: `Invalid sport. Allowed: ${[...ALLOWED_SPORTS].join(", ")}`,
      },
      { status: 400 },
    );
  }

  const rawMarkets = searchParams.get("markets") || "spreads,totals,h2h";
  const markets = rawMarkets
    .split(",")
    .filter((m) => ALLOWED_MARKETS.has(m))
    .join(",");
  if (!markets) {
    return NextResponse.json(
      { error: "No valid markets specified" },
      { status: 400 },
    );
  }

  const cacheKey = `${sport}:${markets}`;
  evictStale();
  const cached = cachedData.get(cacheKey);
  const now = Date.now();

  // Short-circuit when a recent exhaustive key probe already failed —
  // prevents rate-limit amplification (120 inbound req/min × N keys).
  const negKey = negCacheKey("odds", sport, markets);
  if (!cached && getNegCache(negKey)) {
    return NextResponse.json(
      { error: "Odds provider temporarily unavailable (all keys failed recently)" },
      { status: 502 },
    );
  }

  if (cached) {
    if (cached.expiresAt > now) {
      // Fresh cache hit
      return NextResponse.json(cached.data);
    }
    if (cached.staleAt > now) {
      // Stale but usable: serve immediately and revalidate in background.
      // This prevents 502s when The Odds API is slow during hourly refreshes.
      if (!revalidating.has(cacheKey)) {
        revalidating.add(cacheKey);
        fetchOdds(apiKeys, sport, markets, cacheKey).finally(() =>
          revalidating.delete(cacheKey),
        );
      }
      return NextResponse.json(cached.data);
    }
  }

  // No cache or fully expired: fetch synchronously
  try {
    const data = await fetchOdds(apiKeys, sport, markets, cacheKey);
    return NextResponse.json(data);
  } catch (e) {
    const msg = e instanceof Error ? e.message : "Failed to fetch odds from provider";
    return NextResponse.json({ error: msg }, { status: 502 });
  }
}

async function fetchOdds(
  apiKeys: string[],
  sport: string,
  markets: string,
  cacheKey: string,
): Promise<unknown> {
  if (apiKeys.length === 0) throw new Error("No Odds API keys configured");

  const n = apiKeys.length;
  const start = rotationStart(n);
  let lastErr: Error | null = null;

  for (let i = 0; i < n; i++) {
    const keyIdx = (start + i) % n;
    const apiKey = apiKeys[keyIdx];
    const url = new URL(`/v4/sports/${sport}/odds`, ODDS_API_BASE);
    url.searchParams.set("apiKey", apiKey);
    url.searchParams.set("regions", "us");
    url.searchParams.set("markets", markets);
    url.searchParams.set("oddsFormat", "decimal");
    // Only fetch upcoming games; The Odds API rejects milliseconds (422)
    url.searchParams.set(
      "commenceTimeFrom",
      new Date().toISOString().replace(/\.\d{3}Z$/, "Z"),
    );

    let resp: Response;
    try {
      resp = await fetch(url.toString(), { signal: AbortSignal.timeout(30_000) });
    } catch (e) {
      lastErr = e instanceof Error ? e : new Error(String(e));
      console.error(`[odds-api] key[${keyIdx}] fetch threw: ${lastErr.message}`);
      advanceRotation(keyIdx);
      continue;
    }

    if (resp.ok) {
      const data = await resp.json();
      const now = Date.now();
      cachedData.set(cacheKey, {
        data,
        expiresAt: now + CACHE_TTL_SECONDS * 1000,
        staleAt: now + STALE_TTL_SECONDS * 1000,
      });
      holdRotation(keyIdx);
      return data;
    }

    const body = await resp.text().catch(() => "");
    console.error(
      `[odds-api] key[${keyIdx}] ${resp.status} ${resp.statusText}: ${body.slice(0, 200)}`,
    );
    lastErr = new Error(`Odds provider returned an error (${resp.status})`);

    if (isOddsKeyFailure(resp.status)) {
      advanceRotation(keyIdx);
      continue;
    }
    // 400/404/422 etc. — same across all keys, don't burn quota.
    throw lastErr;
  }

  // All keys tried and all failed with retriable statuses — prime the
  // negative cache so the next inbound request doesn't fan out again.
  setNegCache(negCacheKey("odds", sport, markets));
  throw lastErr ?? new Error("All Odds API keys failed");
}
