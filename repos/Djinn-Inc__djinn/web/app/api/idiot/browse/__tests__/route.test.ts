import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { NextRequest } from "next/server";

vi.mock("@/lib/contracts", () => ({
  ADDRESSES: { signalCommitment: "0x4712479Ba57c9ED40405607b2B18967B359209C0" },
  SIGNAL_COMMITMENT_ABI: [],
}));

vi.mock("@/lib/rate-limit", () => ({
  getIp: () => "127.0.0.1",
  isRateLimited: () => false,
  rateLimitResponse: () =>
    new Response(JSON.stringify({ error: "rate_limited" }), { status: 429 }),
}));

vi.mock("ethers", () => ({
  ethers: {
    isAddress: (a: string) => /^0x[0-9a-fA-F]{40}$/.test(a),
    JsonRpcProvider: vi.fn(),
    Contract: vi.fn(),
    getAddress: (a: string) => a,
  },
}));

import { GET } from "../route";

function installForwardMock(primary: { status: number; body: unknown } | { error: unknown }) {
  return vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
    const url = typeof input === "string" ? input : (input as Request).url;
    if (url.includes("/v1/idiot/browse")) {
      if ("error" in primary) throw primary.error;
      return new Response(JSON.stringify(primary.body), {
        status: primary.status,
        headers: { "Content-Type": "application/json" },
      });
    }
    throw new Error(`Unmocked fetch: ${url}`);
  });
}

function makeReq(qs: string = ""): NextRequest {
  return new NextRequest(`http://localhost/api/idiot/browse${qs}`);
}

describe("GET /api/idiot/browse (forward-first)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("validator responds → forwards verbatim with validator source header", async () => {
    installForwardMock({
      status: 200,
      body: {
        signals: [
          {
            signal_id: "622313",
            genius: "0x68fc8eeC9E5551d4c93a89b6d861f0a05e0A2A1d",
            sport: "basketball_nba",
            fee_bps: 500,
            sla_multiplier_bps: 10000,
            max_notional: "100000000",
            min_notional: "0",
            expires_at_unix: 1747000000,
            max_notional_usdc: 100.0,
            expires_at: "2026-05-12T00:00:00Z",
          },
        ],
        total: 1,
        offset: 0,
        limit: 20,
      },
    });
    const resp = await GET(makeReq());
    expect(resp.status).toBe(200);
    expect(resp.headers.get("x-djinn-source")).toBe("validator");
    const body = await resp.json();
    expect(body.total).toBe(1);
    expect(body.signals[0].signal_id).toBe("622313");
  });

  it("forwards query string to the validator", async () => {
    let capturedUrl = "";
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const url = typeof input === "string" ? input : (input as Request).url;
      if (url.includes("/v1/idiot/browse")) {
        capturedUrl = url;
        return new Response(JSON.stringify({ signals: [], total: 0, offset: 0, limit: 20 }), {
          status: 200,
        });
      }
      throw new Error(`Unmocked: ${url}`);
    });

    await GET(makeReq("?sport=basketball_nba&sort=fee&limit=5"));
    expect(capturedUrl).toContain("sport=basketball_nba");
    expect(capturedUrl).toContain("sort=fee");
    expect(capturedUrl).toContain("limit=5");
  });

  it("validator unreachable → attempts local fallback", async () => {
    installForwardMock({ error: new Error("network") });
    const resp = await GET(makeReq());
    expect(resp.status).toBeGreaterThanOrEqual(200);
    expect(resp.headers.get("x-djinn-source")).toBe("vercel-local");
  });

  it("validator 503 → attempts local fallback", async () => {
    installForwardMock({ status: 503, body: { error: "down" } });
    const resp = await GET(makeReq());
    expect(resp.headers.get("x-djinn-source")).toBe("vercel-local");
  });

  it("invalid genius rejected before forwarding", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch");
    const resp = await GET(makeReq("?genius=not-an-address"));
    expect(resp.status).toBe(400);
    expect(fetchSpy).not.toHaveBeenCalled();
  });
});
