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
 * GET /api/odds/alt?sport=basketball_nba&event_id=abc123
 *
 * Fetches alternate spreads and totals for a specific event.
 * Uses the per-event Odds API endpoint which supports alt markets.
 *
 * Shares rotation + negative-cache state with the main /api/odds route
 * via `@/lib/oddsKeys`, so a 429 from either route advances the pointer
 * for both. Signal-creation flows often hit both back-to-back — without
 * shared state we'd double our chance of tripping the upstream limit.
 */

const ODDS_API_BASE = "https://api.the-odds-api.com";

export async function GET(request: NextRequest) {
  const apiKeys = getOddsApiKeys();
  if (apiKeys.length === 0) {
    return NextResponse.json(
      { error: "Odds API key not configured" },
      { status: 503 },
    );
  }

  const { searchParams } = new URL(request.url);
  const sport = searchParams.get("sport");
  const eventId = searchParams.get("event_id");

  if (!sport || !eventId) {
    return NextResponse.json(
      { error: "sport and event_id required" },
      { status: 400 },
    );
  }

  const negKey = negCacheKey("odds-alt", sport, eventId);
  if (getNegCache(negKey)) {
    return NextResponse.json(
      { error: "Odds provider temporarily unavailable (all keys failed recently)" },
      { status: 502 },
    );
  }

  const n = apiKeys.length;
  const start = rotationStart(n);
  let lastStatus = 0;

  for (let i = 0; i < n; i++) {
    const keyIdx = (start + i) % n;
    const url = new URL(
      `/v4/sports/${sport}/events/${eventId}/odds`,
      ODDS_API_BASE,
    );
    url.searchParams.set("apiKey", apiKeys[keyIdx]);
    url.searchParams.set("regions", "us");
    url.searchParams.set("markets", "alternate_spreads,alternate_totals");
    url.searchParams.set("oddsFormat", "decimal");

    let resp: Response;
    try {
      resp = await fetch(url.toString(), { signal: AbortSignal.timeout(10_000) });
    } catch {
      console.error(`[odds-alt] key[${keyIdx}] fetch threw`);
      advanceRotation(keyIdx);
      continue;
    }

    if (resp.ok) {
      holdRotation(keyIdx);
      const data = await resp.json();
      return NextResponse.json(data, {
        headers: {
          "Cache-Control": "public, s-maxage=60, stale-while-revalidate=120",
        },
      });
    }

    lastStatus = resp.status;
    console.error(`[odds-alt] key[${keyIdx}] ${resp.status} ${resp.statusText}`);
    if (isOddsKeyFailure(resp.status)) {
      advanceRotation(keyIdx);
      continue;
    }
    // Non-key error (400/404/422): don't waste quota, same across keys.
    return NextResponse.json(
      { error: `Odds provider error (${resp.status})` },
      { status: 502 },
    );
  }

  // All keys failed with retriable statuses — prime negative cache.
  setNegCache(negKey);
  return NextResponse.json(
    { error: `All Odds API keys failed (last status ${lastStatus})` },
    { status: 502 },
  );
}
