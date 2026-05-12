import { NextResponse } from "next/server";
import { DEFAULT_BOOTSTRAP } from "@/lib/validatorDiscovery";

/**
 * GET /api/sports
 *
 * Sprint-A Stage A-2: forwards to the validator's /v1/sports (which holds the
 * canonical catalog derived from ESPN-resolvable sports). Falls back to a
 * pinned local list so the route stays available if the bootstrap validator
 * is temporarily down; the fallback is the same 8-entry list the validator
 * serves, so behavior is indistinguishable for clients.
 *
 * The fallback remains acceptable because this list only changes once per
 * season — a brief stale-serve during a validator hiccup is not user-facing.
 */

const SPORTS_FALLBACK = [
  { key: "basketball_nba", name: "NBA", category: "Basketball" },
  { key: "basketball_ncaab", name: "NCAA Basketball", category: "Basketball" },
  { key: "americanfootball_nfl", name: "NFL", category: "Football" },
  { key: "americanfootball_ncaaf", name: "NCAA Football", category: "Football" },
  { key: "baseball_mlb", name: "MLB", category: "Baseball" },
  { key: "icehockey_nhl", name: "NHL", category: "Hockey" },
  { key: "soccer_epl", name: "Premier League", category: "Soccer" },
  { key: "soccer_usa_mls", name: "MLS", category: "Soccer" },
] as const;

const VALIDATOR_TIMEOUT_MS = 3_000;

export async function GET() {
  try {
    const resp = await fetch(`${DEFAULT_BOOTSTRAP}/v1/sports`, {
      signal: AbortSignal.timeout(VALIDATOR_TIMEOUT_MS),
      headers: { accept: "application/json" },
    });
    if (resp.ok) {
      const data = (await resp.json()) as {
        sports?: Array<{ key: string; name: string; category: string }>;
        total?: number;
      };
      // Defense-in-depth: never widen the allowlist client-side even if the
      // validator does. Keys not in the pinned fallback are dropped.
      const allowedKeys = new Set<string>(SPORTS_FALLBACK.map((s) => s.key));
      const filtered = (data.sports ?? []).filter((s) => allowedKeys.has(s.key));
      if (filtered.length > 0) {
        return NextResponse.json({ sports: filtered, total: filtered.length });
      }
    }
  } catch {
    // Validator unreachable — fall through to pinned list.
  }
  return NextResponse.json({
    sports: SPORTS_FALLBACK,
    total: SPORTS_FALLBACK.length,
  });
}
