import { test, expect, APIRequestContext } from "@playwright/test";

// Third-party-consumer regression for the public API surface. Acts as an
// external SDK or monitoring tool would: no browser-driven session, just
// HTTP + bypass header. Catches regressions where a route returns a new
// shape that would break existing integrations, or where Vercel's bot
// challenge starts blocking routes that were previously whitelisted.
//
// Gating: requires VERCEL_BYPASS_SECRET because djinn.gg runs Vercel
// Attack Challenge Mode (see VULNERABILITY_REPORT.md C-2) which 403s
// every non-browser request by default. Without the bypass, every assertion
// here devolves into "Vercel returned a challenge page", which is already
// tracked as C-2 — running without the bypass would just generate noise.
// With the bypass, this becomes a genuine third-party-API contract test.
//
// Cron install: set VERCEL_BYPASS_SECRET on the cron box (from Vercel
// project Settings → Security → Protection Bypass for Automation).
// scripts/staging-e2e.sh does NOT need this — it targets the staging fork,
// which has no Vercel layer.

const BASE_URL = process.env.UX_BASE_URL ?? "https://djinn.gg";
const BYPASS_SECRET = process.env.VERCEL_BYPASS_SECRET;

// Sport keys come from web/lib/odds.ts SPORT_GROUPS. We assert the top three
// by volume (NBA + NFL + MLB) rather than all eight to keep the journey
// under 10s — a full-fanout would eat rate limits during cron runs.
const SPORT_KEYS = ["basketball_nba", "americanfootball_nfl", "baseball_mlb"];

test.skip(
  !BYPASS_SECRET,
  "VERCEL_BYPASS_SECRET not set — skipping API-health journey. See spec header for rationale.",
);

async function jsonGet(request: APIRequestContext, path: string) {
  const res = await request.get(path);
  const status = res.status();
  const ct = res.headers()["content-type"] ?? "";
  let body: unknown = null;
  try {
    body = await res.json();
  } catch {
    body = await res.text();
  }
  return { status, ct, body };
}

test.describe("Public API Health Journey", () => {
  // Each endpoint is independent — a regression in one shouldn't mask the
  // others. Leave mode at default (parallel-within-worker; the config sets
  // workers=1 for the UX config, so this effectively runs sequentially but
  // without the serial-mode cascade-on-first-failure behavior).

  let api: APIRequestContext;

  test.beforeAll(async ({ playwright }) => {
    const extraHTTPHeaders: Record<string, string> = {
      // Identify ourselves as an automated consumer so Vercel Analytics can
      // separate bot traffic from real users — doesn't bypass challenges,
      // just annotates the request.
      "User-Agent": "djinn-e2e-api-health/1.0",
    };
    if (BYPASS_SECRET) {
      extraHTTPHeaders["x-vercel-protection-bypass"] = BYPASS_SECRET;
      extraHTTPHeaders["x-vercel-set-bypass-cookie"] = "true";
    }
    api = await playwright.request.newContext({
      baseURL: BASE_URL,
      extraHTTPHeaders,
      timeout: 20_000,
    });
  });

  test.afterAll(async () => {
    await api.dispose();
  });

  test("GET /api/health → 200 + status field", async () => {
    const { status, ct, body } = await jsonGet(api, "/api/health");
    expect(status, `/api/health status (body: ${JSON.stringify(body).slice(0, 200)})`).toBe(200);
    expect(ct).toContain("application/json");
    expect(body).toMatchObject({ status: expect.any(String) });
  });

  test("GET /api/idiot/browse → 200 + signals array", async () => {
    const { status, body } = await jsonGet(api, "/api/idiot/browse?limit=5");
    expect(status, `/api/idiot/browse status (body: ${JSON.stringify(body).slice(0, 200)})`).toBe(200);
    expect(body).toHaveProperty("signals");
    expect(Array.isArray((body as { signals: unknown[] }).signals)).toBe(true);
  });

  test("GET /api/validators/discover → 200 + non-empty array", async () => {
    const { status, body } = await jsonGet(api, "/api/validators/discover");
    expect(status, `/api/validators/discover status (body: ${JSON.stringify(body).slice(0, 200)})`).toBe(200);
    // Shape is either { nodes: [...] } or a bare array — both historically
    // used. Accept either and count elements.
    const nodes = Array.isArray(body)
      ? body
      : Array.isArray((body as { nodes?: unknown[] }).nodes)
        ? (body as { nodes: unknown[] }).nodes
        : [];
    expect(nodes.length, "no validators discovered — metagraph read failing?").toBeGreaterThan(0);
  });

  test("GET /api/miners/discover → 200 + non-empty array", async () => {
    const { status, body } = await jsonGet(api, "/api/miners/discover");
    expect(status, `/api/miners/discover status (body: ${JSON.stringify(body).slice(0, 200)})`).toBe(200);
    const nodes = Array.isArray(body)
      ? body
      : Array.isArray((body as { nodes?: unknown[] }).nodes)
        ? (body as { nodes: unknown[] }).nodes
        : Array.isArray((body as { miners?: unknown[] }).miners)
          ? (body as { miners: unknown[] }).miners
          : [];
    expect(nodes.length, "no miners discovered").toBeGreaterThan(0);
  });

  test("GET /api/network/status → 200 + validator + miner sections", async () => {
    const { status, body } = await jsonGet(api, "/api/network/status");
    expect(status, `/api/network/status status (body: ${JSON.stringify(body).slice(0, 200)})`).toBe(200);
    // The wildcard-router primary path now serves this; we assert the shape
    // the /network page depends on rather than any single field name so the
    // spec tolerates future additions.
    const b = body as Record<string, unknown>;
    const hasNetwork = "validators" in b || "summary" in b || "miners" in b;
    expect(hasNetwork, `unexpected /network/status shape: ${JSON.stringify(b).slice(0, 200)}`).toBe(true);
  });

  test("GET /api/network/config → 200 + contract addresses", async () => {
    const { status, body } = await jsonGet(api, "/api/network/config");
    expect(status, `/api/network/config status (body: ${JSON.stringify(body).slice(0, 200)})`).toBe(200);
    // Must surface the canonical contract addresses so third-party tooling
    // can pin its reads to the same proxies the site uses.
    const b = body as Record<string, unknown>;
    const hasAddresses =
      "signalCommitment" in b ||
      "escrow" in b ||
      "addresses" in b ||
      "contracts" in b;
    expect(hasAddresses, `/api/network/config missing addresses: ${JSON.stringify(b).slice(0, 200)}`).toBe(true);
  });

  test("GET /api/sports → 200 + sport list", async () => {
    const { status, body } = await jsonGet(api, "/api/sports");
    expect(status, `/api/sports status (body: ${JSON.stringify(body).slice(0, 200)})`).toBe(200);
    const sports = Array.isArray(body)
      ? body
      : Array.isArray((body as { sports?: unknown[] }).sports)
        ? (body as { sports: unknown[] }).sports
        : [];
    expect(sports.length, "no sports returned — odds adapter broken?").toBeGreaterThan(0);
  });

  for (const sport of SPORT_KEYS) {
    test(`GET /api/odds?sport=${sport} → 200 + array`, async () => {
      const { status, body } = await jsonGet(api, `/api/odds?sport=${sport}`);
      // Upstream odds providers go quiet off-season — NBA in June, NFL in
      // April etc. Empty array is a valid response; missing API key is not.
      expect(status, `/api/odds?sport=${sport} status (body: ${JSON.stringify(body).slice(0, 200)})`).toBe(200);
      const games = Array.isArray(body)
        ? body
        : Array.isArray((body as { games?: unknown[] }).games)
          ? (body as { games: unknown[] }).games
          : (body as { events?: unknown[] }).events ?? [];
      expect(Array.isArray(games), `/api/odds response is not iterable: ${JSON.stringify(body).slice(0, 200)}`).toBe(true);
    });
  }
});
