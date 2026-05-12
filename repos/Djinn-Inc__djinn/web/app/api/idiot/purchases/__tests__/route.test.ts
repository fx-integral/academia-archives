import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { NextRequest } from "next/server";

vi.mock("@/lib/contracts", () => ({
  ADDRESSES: {
    escrow: "0xb43BA175a6784973eB3825acF801Cd7920ac692a",
  },
  ESCROW_ABI: [],
}));

vi.mock("@/lib/rate-limit", () => ({
  getIp: () => "127.0.0.1",
  isRateLimited: () => false,
  rateLimitResponse: () => new Response("rate limited", { status: 429 }),
}));

const BUYER = "0xD717b5fbA93F123f6ad530ae2Ab327B4DcDa1e37";

vi.mock("@/lib/api-auth", () => ({
  authenticateRequest: vi.fn(async () => ({ address: BUYER })),
}));

vi.mock("ethers", async () => {
  const actual = await vi.importActual<typeof import("ethers")>("ethers");
  return {
    ...actual,
    ethers: {
      ...actual.ethers,
      JsonRpcProvider: vi.fn(() => ({})),
      Contract: vi.fn(),
    },
  };
});

import { GET } from "../route";
import { authenticateRequest } from "@/lib/api-auth";

function req(path: string = ""): NextRequest {
  return new NextRequest(`http://localhost/api/idiot/purchases${path}`);
}

describe("GET /api/idiot/purchases (forward-first)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(authenticateRequest).mockResolvedValue({
      address: BUYER,
      expiresAt: Date.now() + 3600_000,
    } as any);
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("unauthenticated → 401", async () => {
    vi.mocked(authenticateRequest).mockResolvedValueOnce(null);
    const resp = await GET(req());
    expect(resp.status).toBe(401);
  });

  it("invalid status → 400", async () => {
    const resp = await GET(req("?status=bogus"));
    expect(resp.status).toBe(400);
  });

  it("validator responds → forwards verbatim with validator source header", async () => {
    const validatorBody = {
      purchases: [
        {
          purchase_id: 1,
          signal_id: "42",
          notional_usdc: 10.0,
          fee_usdc: 0.1,
          credit_used_usdc: 0,
          usdc_paid: 10.1,
          outcome: "pending",
          status: "pending",
          purchased_at: "2026-04-18T12:00:00Z",
        },
      ],
      total: 1,
      offset: 0,
      limit: 20,
    };

    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const url = typeof input === "string" ? input : (input as Request).url;
      if (url.includes(`/v1/idiot/${BUYER}/purchases`)) {
        return new Response(JSON.stringify(validatorBody), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        });
      }
      throw new Error(`Unmocked: ${url}`);
    });

    const resp = await GET(req());
    expect(resp.status).toBe(200);
    expect(resp.headers.get("x-djinn-source")).toBe("validator");
    const body = await resp.json();
    expect(body.total).toBe(1);
    expect(body.purchases[0].purchase_id).toBe(1);
  });

  it("forwards query string (status, limit, offset) to validator", async () => {
    const spy = vi.spyOn(globalThis, "fetch").mockImplementation(async () => {
      return new Response(
        JSON.stringify({ purchases: [], total: 0, offset: 5, limit: 10 }),
        { status: 200 },
      );
    });
    await GET(req("?status=settled&limit=10&offset=5"));
    const calledUrl = (spy.mock.calls[0][0] as string) || "";
    expect(calledUrl).toContain("status=settled");
    expect(calledUrl).toContain("limit=10");
    expect(calledUrl).toContain("offset=5");
  });

  it("validator unreachable → falls back to local path", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const url = typeof input === "string" ? input : (input as Request).url;
      if (url.includes("/v1/idiot/")) {
        throw new Error("ECONNREFUSED");
      }
      throw new Error(`Unmocked: ${url}`);
    });
    const resp = await GET(req());
    expect(resp.headers.get("x-djinn-source")).not.toBe("validator");
  });

  it("validator 503 → falls back to local path", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const url = typeof input === "string" ? input : (input as Request).url;
      if (url.includes("/v1/idiot/")) {
        return new Response(JSON.stringify({ error: "down" }), { status: 503 });
      }
      throw new Error(`Unmocked: ${url}`);
    });
    const resp = await GET(req());
    expect(resp.headers.get("x-djinn-source")).not.toBe("validator");
  });

  it("cache-control is private (not public) on forwarded response", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async () => {
      return new Response(
        JSON.stringify({ purchases: [], total: 0, offset: 0, limit: 20 }),
        { status: 200 },
      );
    });
    const resp = await GET(req());
    const cc = resp.headers.get("cache-control") || "";
    expect(cc).toContain("private");
    expect(cc).not.toContain("public");
  });
});
