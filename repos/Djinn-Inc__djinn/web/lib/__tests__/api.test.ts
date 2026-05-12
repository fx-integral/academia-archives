import { describe, it, expect, vi, beforeEach } from "vitest";
import { ValidatorClient, MinerClient, ApiError, fetchFromAnyValidator } from "../api";

// Mock fetch globally
const mockFetch = vi.fn();
vi.stubGlobal("fetch", mockFetch);

function jsonResponse(data: unknown, status = 200) {
  return {
    ok: status >= 200 && status < 300,
    status,
    statusText: status === 200 ? "OK" : "Error",
    json: () => Promise.resolve(data),
    text: () => Promise.resolve(JSON.stringify(data)),
  };
}

beforeEach(() => {
  mockFetch.mockReset();
});

// ---------------------------------------------------------------------------
// ValidatorClient
// ---------------------------------------------------------------------------

describe("ValidatorClient", () => {
  const client = new ValidatorClient("http://localhost:8421");

  // storeShare describe block removed 2026-05-04: legacy /v1/signal
  // endpoint deleted along with the storeShare client method. Bundle
  // endpoint coverage lives in storeShareBundle test below + server-side
  // tests in validator/tests/test_share_bundle.py.

  describe("purchaseSignal", () => {
    it("sends POST to /v1/signal/{id}/purchase", async () => {
      mockFetch.mockResolvedValueOnce(
        jsonResponse({
          signal_id: "sig1",
          status: "complete",
          available: true,
          encrypted_key_share: "cafe",
          message: "Key share released",
        }),
      );

      const result = await client.purchaseSignal("sig1", {
        buyer_address: "0xBuyer",
        sportsbook: "DraftKings",
        available_indices: [1, 3, 5],
      });

      expect(mockFetch).toHaveBeenCalledWith(
        "http://localhost:8421/v1/signal/sig1/purchase",
        expect.objectContaining({ method: "POST" }),
      );

      expect(result.status).toBe("complete");
      expect(result.available).toBe(true);
      expect(result.encrypted_key_share).toBe("cafe");
    });

    it("handles unavailable response", async () => {
      mockFetch.mockResolvedValueOnce(
        jsonResponse({
          signal_id: "sig1",
          status: "unavailable",
          available: false,
          encrypted_key_share: null,
          message: "Signal not available",
        }),
      );

      const result = await client.purchaseSignal("sig1", {
        buyer_address: "0xBuyer",
        sportsbook: "FanDuel",
        available_indices: [2],
      });

      expect(result.available).toBe(false);
      expect(result.encrypted_key_share).toBeNull();
    });
  });

  describe("health", () => {
    it("sends GET to /health", async () => {
      mockFetch.mockResolvedValueOnce(
        jsonResponse({
          status: "ok",
          version: "0.1.0",
          uid: null,
          shares_held: 5,
          chain_connected: false,
          bt_connected: false,
        }),
      );

      const result = await client.health();
      expect(mockFetch).toHaveBeenCalledWith(
        "http://localhost:8421/health",
        expect.objectContaining({ signal: expect.anything() }),
      );
      expect(result.status).toBe("ok");
      expect(result.shares_held).toBe(5);
    });
  });
});

// ---------------------------------------------------------------------------
// MinerClient
// ---------------------------------------------------------------------------

describe("MinerClient", () => {
  const client = new MinerClient("http://localhost:8422");

  describe("checkLines", () => {
    it("sends POST to /v1/check with candidate lines", async () => {
      mockFetch.mockResolvedValueOnce(
        jsonResponse({
          results: [
            { index: 1, available: true, bookmakers: [{ bookmaker: "DraftKings", odds: 1.91 }] },
            { index: 2, available: false, bookmakers: [] },
          ],
          available_indices: [1],
          response_time_ms: 42.5,
        }),
      );

      const result = await client.checkLines({
        lines: [
          {
            index: 1,
            sport: "basketball_nba",
            event_id: "evt1",
            home_team: "Lakers",
            away_team: "Celtics",
            market: "spreads",
            line: -3.5,
            side: "Lakers",
          },
          {
            index: 2,
            sport: "basketball_nba",
            event_id: "evt1",
            home_team: "Lakers",
            away_team: "Celtics",
            market: "spreads",
            line: -5.5,
            side: "Lakers",
          },
        ],
      });

      expect(mockFetch).toHaveBeenCalledWith(
        "http://localhost:8422/v1/check",
        expect.objectContaining({ method: "POST" }),
      );

      expect(result.available_indices).toEqual([1]);
      expect(result.results[0].available).toBe(true);
      expect(result.results[0].bookmakers[0].bookmaker).toBe("DraftKings");
    });

    it("throws on client error (no retry for 4xx)", async () => {
      mockFetch.mockResolvedValueOnce(
        jsonResponse({ detail: "bad request" }, 400),
      );

      await expect(
        client.checkLines({ lines: [] }),
      ).rejects.toThrow("400");
    });
  });

  describe("health", () => {
    it("sends GET to /health", async () => {
      mockFetch.mockResolvedValueOnce(
        jsonResponse({
          status: "ok",
          version: "0.1.0",
          uid: 7,
          odds_api_connected: true,
          bt_connected: false,
          uptime_seconds: 3600,
        }),
      );

      const result = await client.health();
      expect(mockFetch).toHaveBeenCalledWith(
        "http://localhost:8422/health",
        expect.objectContaining({ signal: expect.anything() }),
      );
      expect(result.uid).toBe(7);
      expect(result.odds_api_connected).toBe(true);
    });
  });
});

// ---------------------------------------------------------------------------
// Error handling
// ---------------------------------------------------------------------------

describe("Error handling", () => {
  it("includes status code in error message", async () => {
    const client = new ValidatorClient("http://localhost:8421");
    mockFetch.mockResolvedValueOnce(
      jsonResponse({ detail: "not found" }, 404),
    );
    await expect(client.health()).rejects.toThrow("404");
  });

  it("propagates network errors after retries", async () => {
    const client = new MinerClient("http://localhost:8422");
    // Network errors (TypeError) are retried
    mockFetch
      .mockRejectedValueOnce(new TypeError("Failed to fetch"))
      .mockRejectedValueOnce(new TypeError("Failed to fetch"))
      .mockRejectedValueOnce(new TypeError("Failed to fetch"));
    await expect(client.health()).rejects.toThrow("Failed to fetch");
  });

  it("wraps abort errors as timeout (no retry)", async () => {
    const client = new MinerClient("http://localhost:8422");
    const abortError = new DOMException("The operation was aborted", "AbortError");
    mockFetch.mockRejectedValueOnce(abortError);
    await expect(client.health()).rejects.toThrow("timed out");
    // Timeout should NOT be retried — only 1 fetch call
    expect(mockFetch).toHaveBeenCalledTimes(1);
  });

  it("does not retry 4xx errors", async () => {
    const client = new ValidatorClient("http://localhost:8421");
    mockFetch.mockResolvedValueOnce(jsonResponse({ detail: "not found" }, 404));
    await expect(client.health()).rejects.toThrow("404");
    // 4xx should NOT be retried — only 1 fetch call
    expect(mockFetch).toHaveBeenCalledTimes(1);
  });

  it("retries then succeeds on transient 500", async () => {
    const client = new ValidatorClient("http://localhost:8421");
    // First call 500, second call succeeds
    mockFetch
      .mockResolvedValueOnce(jsonResponse({ detail: "error" }, 500))
      .mockResolvedValueOnce(
        jsonResponse({ status: "ok", version: "0.1.0", uid: null, shares_held: 0, chain_connected: false, bt_connected: false }),
      );

    const result = await client.health();
    expect(result.status).toBe("ok");
    expect(mockFetch).toHaveBeenCalledTimes(2);
  });

  it("ApiError has correct properties", () => {
    const err = new ApiError(503, "Service unavailable", "http://test");
    expect(err.status).toBe(503);
    expect(err.retryable).toBe(true);
    expect(err.rateLimited).toBe(false);
    expect(err.name).toBe("ApiError");

    const rateLimited = new ApiError(429, "Too many requests", "http://test");
    expect(rateLimited.rateLimited).toBe(true);
    expect(rateLimited.retryable).toBe(false);
  });
});

describe("fetchFromAnyValidator", () => {
  it("returns the first fast 2xx even when others are slow or failing", async () => {
    // v0 is slow, v1 fails, v2 is fast — v2 should win under Promise.any.
    mockFetch.mockImplementation((url: string) => {
      if (url.startsWith("https://v0.djinn.gg")) {
        return new Promise((resolve) =>
          setTimeout(() => resolve(jsonResponse({ slow: true })), 200),
        );
      }
      if (url.startsWith("https://v1.djinn.gg")) {
        return Promise.resolve(jsonResponse({ detail: "boom" }, 502));
      }
      if (url.startsWith("https://v2.djinn.gg")) {
        return Promise.resolve(jsonResponse({ winner: "v2" }));
      }
      // v189 and v213: slow too, should lose the race
      return new Promise((resolve) =>
        setTimeout(() => resolve(jsonResponse({})), 500),
      );
    });

    const res = await fetchFromAnyValidator("/v1/idiot/browse");
    const body = (await res.json()) as { winner?: string };
    expect(body.winner).toBe("v2");
    // All 5 hosts must have been probed — this is the whole point of parallel race.
    expect(mockFetch).toHaveBeenCalledTimes(5);
  });

  it("throws only when every host fails", async () => {
    mockFetch.mockImplementation(() =>
      Promise.resolve(jsonResponse({ detail: "boom" }, 502)),
    );
    await expect(fetchFromAnyValidator("/v1/idiot/browse")).rejects.toThrow(
      /All validators unreachable/,
    );
  });

  it("passes 4xx through without treating as error (client-side status)", async () => {
    // 4xx should NOT be treated like a 5xx failure; it's a legit response from
    // whichever host responded first. We return it so callers can decide.
    mockFetch.mockImplementation((url: string) => {
      if (url.startsWith("https://v0.djinn.gg")) {
        return Promise.resolve(jsonResponse({ detail: "not found" }, 404));
      }
      return new Promise((resolve) =>
        setTimeout(() => resolve(jsonResponse({})), 500),
      );
    });
    const res = await fetchFromAnyValidator("/v1/idiot/browse");
    expect(res.status).toBe(404);
  });

  it("winner's signal is not aborted after race (regression: shared-controller abort killed body stream)", async () => {
    // Regression test for iter-41 UX finding: previous impl used a single
    // shared AbortController for all probes, then aborted it on race-win.
    // That killed the winner's body stream too, causing downstream
    // `await res.json()` to throw DOMException "The user aborted a request."
    // which rendered into /network and /idiot/browse as visible error text.
    const signalsPerHost = new Map<string, AbortSignal>();
    mockFetch.mockImplementation((url: string, init?: RequestInit) => {
      signalsPerHost.set(url, init!.signal as AbortSignal);
      if (url.startsWith("https://v0.djinn.gg")) {
        return Promise.resolve(jsonResponse({ winner: "v0" }));
      }
      return new Promise((resolve) =>
        setTimeout(() => resolve(jsonResponse({})), 500),
      );
    });

    const res = await fetchFromAnyValidator("/v1/network/matrix");

    // Give microtasks a turn to let race_won abort propagate to losers.
    await new Promise((r) => setTimeout(r, 0));

    const winnerSignal = signalsPerHost.get("https://v0.djinn.gg/v1/network/matrix");
    const loserSignal = signalsPerHost.get("https://v1.djinn.gg/v1/network/matrix");
    expect(winnerSignal?.aborted).toBe(false);
    expect(loserSignal?.aborted).toBe(true);

    // And — proving the user-visible fix — the winner's body is still usable.
    const body = (await res.json()) as { winner?: string };
    expect(body.winner).toBe("v0");
  });

  it("ejects a chronically-failing host after passive threshold is crossed", async () => {
    // Regression for UX_FINDINGS L52/L137/L199: v189's 60-90% failure rate
    // was holding Vercel edge sockets open for the full 20s timeout on every
    // fan-out. After N failures the breaker should drop it from the pool so
    // subsequent calls fan out to the remaining healthy hosts only.
    const probedHosts: Set<string> = new Set();
    mockFetch.mockImplementation((url: string) => {
      const host = new URL(url).origin;
      probedHosts.add(host);
      if (host === "https://v189.djinn.gg") {
        return Promise.resolve(jsonResponse({ detail: "upstream" }, 502));
      }
      return Promise.resolve(jsonResponse({ ok: true }));
    });
    // Warm the breaker: 5 consecutive calls. v189 fails each one; after
    // 5/5 samples it should be ejected.
    for (let i = 0; i < 5; i++) {
      await fetchFromAnyValidator(`/v1/idiot/browse?warmup=${i}`);
    }
    probedHosts.clear();
    mockFetch.mockClear();
    await fetchFromAnyValidator("/v1/idiot/browse?post");
    // v189 should have been filtered out of the fan-out by getActiveHosts().
    expect(probedHosts.has("https://v189.djinn.gg")).toBe(false);
    // At least 2 other hosts must still have been probed.
    expect(probedHosts.size).toBeGreaterThanOrEqual(2);
  });
});
