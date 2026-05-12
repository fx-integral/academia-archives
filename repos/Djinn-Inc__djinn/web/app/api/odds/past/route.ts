import { NextRequest, NextResponse } from "next/server";
import {
  getOddsApiKeys,
  rotationStart,
  holdRotation,
  advanceRotation,
  isOddsKeyFailure,
} from "@/lib/oddsKeys";

/**
 * Past-games endpoint for fast-iteration testing of the audit settlement
 * pipeline. Production users hit /api/odds (upcoming games only); this
 * route hits The Odds API's `/v4/sports/{sport}/scores` endpoint which
 * returns games from the last 1-3 days, including FINAL games.
 *
 * Key difference from /api/odds: past games don't have closing-odds data
 * (the lines are pruned shortly after game start), so this route
 * synthesizes a minimal bookmakers structure at standard prices so the
 * stress-scale script can build a coherent decoy line set without code
 * changes upstream of the network call. The synthesized prices are
 * deterministic and only used for stress testing — they have no
 * meaning to the on-chain audit settlement (BPA/WPA vectors are a
 * commitment between the genius and the buyer at purchase time).
 *
 * GET /api/odds/past?sport=baseball_mlb&daysFrom=2
 *
 * Returns events shaped identically to /api/odds, but with a
 * synthesized bookmaker (key="djinn-test", h2h+spreads markets at
 * 1.91/1.91 + ±1.5 spread). Only FINAL games from the requested
 * window are returned.
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
  "soccer_usa_mls",
  "mma_mixed_martial_arts",
]);

interface OddsApiScoreEvent {
  id: string;
  sport_key: string;
  commence_time: string;
  completed: boolean;
  home_team: string;
  away_team: string;
  scores?: Array<{ name: string; score: string }> | null;
}

interface SynthesizedEvent {
  id: string;
  sport_key: string;
  commence_time: string;
  home_team: string;
  away_team: string;
  bookmakers: Array<{
    key: string;
    title: string;
    markets: Array<{
      key: string;
      outcomes: Array<{ name: string; price: number; point?: number }>;
    }>;
  }>;
}

function synthesizeBookmaker(g: OddsApiScoreEvent): SynthesizedEvent {
  // Standard h2h at 1.91/1.91 (5% vig), spread at ±1.5 / 1.91/1.91, total 8.5.
  // Real value is irrelevant — the BPA/WPA at purchase time is the actual
  // economic commitment, and these synthesized lines just give
  // stress-scale a coherent shape to build a decoy set on top of.
  return {
    id: g.id,
    sport_key: g.sport_key,
    commence_time: g.commence_time,
    home_team: g.home_team,
    away_team: g.away_team,
    bookmakers: [
      {
        key: "djinn-test",
        title: "Djinn Test (synthesized)",
        markets: [
          {
            key: "h2h",
            outcomes: [
              { name: g.home_team, price: 1.91 },
              { name: g.away_team, price: 1.91 },
            ],
          },
          {
            key: "spreads",
            outcomes: [
              { name: g.home_team, price: 1.91, point: -1.5 },
              { name: g.away_team, price: 1.91, point: 1.5 },
            ],
          },
          {
            key: "totals",
            outcomes: [
              { name: "Over", price: 1.91, point: 8.5 },
              { name: "Under", price: 1.91, point: 8.5 },
            ],
          },
        ],
      },
    ],
  };
}

async function fetchPastScores(
  apiKeys: string[],
  sport: string,
  daysFrom: number,
): Promise<OddsApiScoreEvent[]> {
  if (apiKeys.length === 0) throw new Error("No Odds API keys configured");

  const n = apiKeys.length;
  const start = rotationStart(n);
  let lastErr: Error | null = null;

  for (let i = 0; i < n; i++) {
    const keyIdx = (start + i) % n;
    const apiKey = apiKeys[keyIdx];
    const url = new URL(`/v4/sports/${sport}/scores`, ODDS_API_BASE);
    url.searchParams.set("apiKey", apiKey);
    url.searchParams.set("daysFrom", String(daysFrom));

    let resp: Response;
    try {
      resp = await fetch(url.toString(), { signal: AbortSignal.timeout(30_000) });
    } catch (e) {
      lastErr = e instanceof Error ? e : new Error(String(e));
      advanceRotation(keyIdx);
      continue;
    }

    if (resp.ok) {
      const data: OddsApiScoreEvent[] = await resp.json();
      holdRotation(keyIdx);
      return data;
    }

    if (isOddsKeyFailure(resp.status)) {
      advanceRotation(keyIdx);
      lastErr = new Error(`HTTP ${resp.status}`);
      continue;
    }

    lastErr = new Error(`HTTP ${resp.status}`);
    break;
  }

  throw lastErr ?? new Error("All Odds API keys failed");
}

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
  if (!sport || !ALLOWED_SPORTS.has(sport)) {
    return NextResponse.json(
      { error: `Invalid sport. Allowed: ${[...ALLOWED_SPORTS].join(", ")}` },
      { status: 400 },
    );
  }

  const daysRaw = searchParams.get("daysFrom") ?? "2";
  const daysFrom = Math.max(1, Math.min(3, parseInt(daysRaw, 10) || 2));

  try {
    const events = await fetchPastScores(apiKeys, sport, daysFrom);
    const completed = events.filter((g) => g.completed === true);
    const synthesized = completed.map(synthesizeBookmaker);
    return NextResponse.json(synthesized);
  } catch (e) {
    const msg = e instanceof Error ? e.message : "Failed to fetch past scores";
    return NextResponse.json({ error: msg }, { status: 502 });
  }
}
