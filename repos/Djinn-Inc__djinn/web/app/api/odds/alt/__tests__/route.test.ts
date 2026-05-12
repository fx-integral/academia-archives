import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { NextRequest } from "next/server";

const mockFetch = vi.fn();
vi.stubGlobal("fetch", mockFetch);

import { GET } from "../route";
import { _resetOddsKeyStateForTests } from "@/lib/oddsKeys";

function makeRequest(params: Record<string, string> = {}): NextRequest {
  const url = new URL("http://localhost:3000/api/odds/alt");
  for (const [k, v] of Object.entries(params)) {
    url.searchParams.set(k, v);
  }
  return new NextRequest(url);
}

describe("GET /api/odds/alt", () => {
  beforeEach(() => {
    vi.stubEnv("ODDS_API_KEY", "test-key-123");
    mockFetch.mockReset();
    _resetOddsKeyStateForTests();
  });

  afterEach(() => {
    vi.unstubAllEnvs();
  });

  it("returns 503 when no API keys configured", async () => {
    vi.stubEnv("ODDS_API_KEY", "");
    const resp = await GET(
      makeRequest({ sport: "basketball_nba", event_id: "evt1" }),
    );
    expect(resp.status).toBe(503);
    const body = await resp.json();
    expect(body.error).toContain("Odds API key not configured");
  });

  it("returns 400 when sport is missing", async () => {
    const resp = await GET(makeRequest({ event_id: "evt1" }));
    expect(resp.status).toBe(400);
    const body = await resp.json();
    expect(body.error).toContain("sport and event_id required");
  });

  it("returns 400 when event_id is missing", async () => {
    const resp = await GET(makeRequest({ sport: "basketball_nba" }));
    expect(resp.status).toBe(400);
    const body = await resp.json();
    expect(body.error).toContain("sport and event_id required");
  });

  it("returns data from upstream on success", async () => {
    const mockData = { event_id: "evt1", bookmakers: [] };
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: async () => mockData,
    });

    const resp = await GET(
      makeRequest({ sport: "basketball_nba", event_id: "evt1" }),
    );
    expect(resp.status).toBe(200);
    const body = await resp.json();
    expect(body).toEqual(mockData);

    expect(mockFetch).toHaveBeenCalledTimes(1);
    const fetchUrl = new URL(mockFetch.mock.calls[0][0]);
    expect(fetchUrl.pathname).toBe(
      "/v4/sports/basketball_nba/events/evt1/odds",
    );
    expect(fetchUrl.searchParams.get("markets")).toBe(
      "alternate_spreads,alternate_totals",
    );
  });

  it("falls through to the next key when one returns 429", async () => {
    vi.stubEnv("ODDS_API_KEYS", "bad-alt,good-alt");
    mockFetch.mockImplementation(async (url: string) => {
      const key = new URL(url).searchParams.get("apiKey");
      if (key === "good-alt") {
        return { ok: true, json: async () => ({ id: "rotated-alt" }) };
      }
      return {
        ok: false,
        status: 429,
        text: async () => "rate limited",
        statusText: "Too Many Requests",
      };
    });

    const resp = await GET(
      makeRequest({ sport: "americanfootball_nfl", event_id: "evtA" }),
    );
    expect(resp.status).toBe(200);
    const body = await resp.json();
    expect(body).toEqual({ id: "rotated-alt" });

    const keysTried = mockFetch.mock.calls.map(
      (c) => new URL(c[0]).searchParams.get("apiKey"),
    );
    expect(keysTried).toContain("good-alt");
  });

  it("returns 502 and primes negative cache when all keys fail", async () => {
    vi.stubEnv("ODDS_API_KEYS", "k1,k2");
    mockFetch.mockResolvedValue({
      ok: false,
      status: 503,
      text: async () => "down",
      statusText: "Service Unavailable",
    });

    const resp = await GET(
      makeRequest({ sport: "baseball_mlb", event_id: "evtB" }),
    );
    expect(resp.status).toBe(502);
    expect(mockFetch).toHaveBeenCalledTimes(2);

    // Second request: should short-circuit via negative cache (no new fetch).
    const resp2 = await GET(
      makeRequest({ sport: "baseball_mlb", event_id: "evtB" }),
    );
    expect(resp2.status).toBe(502);
    const body2 = await resp2.json();
    expect(body2.error).toContain("temporarily unavailable");
    // Still 2 — the short-circuit prevented any upstream calls.
    expect(mockFetch).toHaveBeenCalledTimes(2);
  });

  it("fails fast on 422 without trying the next key", async () => {
    vi.stubEnv("ODDS_API_KEYS", "k-a,k-b");
    mockFetch.mockResolvedValueOnce({
      ok: false,
      status: 422,
      text: async () => "bad event id",
      statusText: "Unprocessable Entity",
    });

    const resp = await GET(
      makeRequest({ sport: "icehockey_nhl", event_id: "nonexistent" }),
    );
    expect(resp.status).toBe(502);
    // 422 is a request-level error, same for every key; don't burn quota.
    expect(mockFetch).toHaveBeenCalledTimes(1);
  });

  it("returns 502 when fetch throws for all keys", async () => {
    vi.stubEnv("ODDS_API_KEYS", "net-1,net-2");
    mockFetch.mockRejectedValue(new Error("Network timeout"));

    const resp = await GET(
      makeRequest({ sport: "soccer_epl", event_id: "evtS" }),
    );
    expect(resp.status).toBe(502);
    const body = await resp.json();
    expect(body.error).toContain("All Odds API keys failed");
    expect(mockFetch).toHaveBeenCalledTimes(2);
  });

  it("shares rotation state with the main /api/odds route", async () => {
    vi.stubEnv("ODDS_API_KEYS", "shared-bad,shared-good");
    // Import the main route handler lazily so its module-level state resets
    // along with the alt route's state via _resetOddsKeyStateForTests above.
    const { GET: mainGet } = await import("../../route");

    // Use key-aware mocks so identity — not order — determines success.
    mockFetch.mockImplementation(async (url: string) => {
      const key = new URL(url).searchParams.get("apiKey");
      if (key === "shared-good") {
        return { ok: true, json: async () => [{ ok: true }] };
      }
      return {
        ok: false,
        status: 429,
        text: async () => "rate limited",
        statusText: "Too Many Requests",
      };
    });

    // First call on /api/odds: lands on shared-good (either directly or via
    // rotation after shared-bad). Rotation pointer held at shared-good.
    const mainUrl = new URL("http://localhost:3000/api/odds");
    mainUrl.searchParams.set("sport", "basketball_nba");
    const resp1 = await mainGet(new NextRequest(mainUrl));
    expect(resp1.status).toBe(200);

    const callsAfterMain = mockFetch.mock.calls.length;

    // Now alt route — should start on the held key (shared-good) on its very
    // first attempt, NOT redo the bad-key probe. That's the whole point of
    // sharing state: alt gets rotated rotation for free.
    const resp2 = await GET(
      makeRequest({ sport: "basketball_nba", event_id: "shared-evt" }),
    );
    expect(resp2.status).toBe(200);

    // Exactly one new fetch for the alt call.
    expect(mockFetch.mock.calls.length).toBe(callsAfterMain + 1);
    const altKey = new URL(
      mockFetch.mock.calls[mockFetch.mock.calls.length - 1][0],
    ).searchParams.get("apiKey");
    expect(altKey).toBe("shared-good");
  });

  it("short-circuits via negative cache without fetching", async () => {
    vi.stubEnv("ODDS_API_KEYS", "a,b");
    // Prime the negative cache by failing all keys.
    mockFetch.mockResolvedValue({
      ok: false,
      status: 503,
      text: async () => "down",
      statusText: "Service Unavailable",
    });
    await GET(
      makeRequest({ sport: "soccer_usa_mls", event_id: "evt-cache" }),
    );
    const afterFirst = mockFetch.mock.calls.length;

    // Subsequent call with same sport+event_id: no upstream fetch.
    const resp = await GET(
      makeRequest({ sport: "soccer_usa_mls", event_id: "evt-cache" }),
    );
    expect(resp.status).toBe(502);
    expect(mockFetch.mock.calls.length).toBe(afterFirst);
  });
});
