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

// vi.mock factories hoist to top of file, so any classes used inside
// must be defined INSIDE the factory (or via vi.hoisted). Provide
// JsonRpcProvider + Contract as classes so `new ethers.Contract(...)`
// produces an object with the filters + queryFilter methods the route
// reaches via the local-fallback path.
vi.mock("ethers", () => {
  class MockProvider {
    async getBlockNumber() {
      return 1000;
    }
  }
  class MockContract {
    filters = {
      SignalCommitted: (..._args: unknown[]) => ({}),
    };
    async queryFilter(_filter: unknown, _from: number, _to: number) {
      return [] as unknown[];
    }
  }
  return {
    ethers: {
      isAddress: (a: string) => /^0x[0-9a-fA-F]{40}$/.test(a),
      JsonRpcProvider: MockProvider,
      Contract: MockContract,
      getAddress: (a: string) => a,
    },
  };
});

import { GET } from "../route";

const GENIUS = "0xD717b5fbA93F123f6ad530ae2Ab327B4DcDa1e37";

function installForwardMock(
  primary: { status: number; body: unknown } | { error: unknown },
) {
  return vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
    const url = typeof input === "string" ? input : (input as Request).url;
    if (url.includes("/v1/genius/") && url.includes("/signals")) {
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
  return new NextRequest(`http://localhost/api/genius/signals${qs}`);
}

describe("GET /api/genius/signals (forward-first)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("requires address query param", async () => {
    const resp = await GET(makeReq());
    expect(resp.status).toBe(400);
  });

  it("rejects invalid address", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch");
    const resp = await GET(makeReq("?address=not-an-address"));
    expect(resp.status).toBe(400);
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it("validator responds → forwards verbatim with validator source header", async () => {
    installForwardMock({
      status: 200,
      body: {
        signals: [
          {
            signal_id: "42",
            genius: GENIUS,
            sport: "basketball_nba",
            fee_bps: 500,
            sla_multiplier_bps: 10000,
            max_notional: "100000000",
            min_notional: "0",
            expires_at_unix: 1800000000,
            status: "active",
            block_number: 12345,
          },
        ],
        total: 1,
        offset: 0,
        limit: 20,
      },
    });
    const resp = await GET(makeReq(`?address=${GENIUS}`));
    expect(resp.status).toBe(200);
    expect(resp.headers.get("x-djinn-source")).toBe("validator");
    const body = await resp.json();
    expect(body.total).toBe(1);
    expect(body.signals[0].signal_id).toBe("42");
    expect(body.signals[0].status).toBe("active");
  });

  it("forwards limit/offset/include_all but drops address from query string", async () => {
    let capturedUrl = "";
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const url = typeof input === "string" ? input : (input as Request).url;
      if (url.includes("/v1/genius/")) {
        capturedUrl = url;
        return new Response(
          JSON.stringify({ signals: [], total: 0, offset: 0, limit: 20 }),
          { status: 200 },
        );
      }
      throw new Error(`Unmocked: ${url}`);
    });

    await GET(makeReq(`?address=${GENIUS}&limit=10&offset=5&include_all=1`));
    expect(capturedUrl).toContain(`/v1/genius/${GENIUS}/signals`);
    expect(capturedUrl).toContain("limit=10");
    expect(capturedUrl).toContain("offset=5");
    expect(capturedUrl).toContain("include_all=1");
    // Address must not appear as a query param — it's a path segment.
    expect(capturedUrl).not.toMatch(/[?&]address=/);
  });

  it("validator unreachable → attempts local fallback", async () => {
    installForwardMock({ error: new Error("network") });
    const resp = await GET(makeReq(`?address=${GENIUS}`));
    expect(resp.status).toBeGreaterThanOrEqual(200);
    expect(resp.headers.get("x-djinn-source")).toBe("vercel-local");
  });

  it("validator 503 → attempts local fallback", async () => {
    installForwardMock({ status: 503, body: { error: "down" } });
    const resp = await GET(makeReq(`?address=${GENIUS}`));
    expect(resp.headers.get("x-djinn-source")).toBe("vercel-local");
  });
});
