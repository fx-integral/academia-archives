import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { NextRequest } from "next/server";

vi.mock("@/lib/contracts", () => ({
  ADDRESSES: {
    audit: "0xCa7e642FE31BA83a7a857644E8894c1B93a2a44E",
  },
  AUDIT_ABI: [],
}));

vi.mock("@/lib/rate-limit", () => ({
  getIp: () => "127.0.0.1",
  isRateLimited: () => false,
  rateLimitResponse: () => new Response("rate limited", { status: 429 }),
}));

vi.mock("ethers", async () => {
  const actual = await vi.importActual<typeof import("ethers")>("ethers");
  return {
    ...actual,
    ethers: {
      ...actual.ethers,
      // Force fallback to blow up cleanly; tests assert only that the route
      // did NOT come from the validator on fallback paths.
      JsonRpcProvider: vi.fn(() => ({})),
      Contract: vi.fn(),
    },
  };
});

import { GET } from "../route";

const GENIUS = "0xD717b5fbA93F123f6ad530ae2Ab327B4DcDa1e37";

function mkReq(): NextRequest {
  return new NextRequest(`http://localhost/api/idiot/genius/${GENIUS}`);
}

function mkParams(addr: string) {
  return { params: Promise.resolve({ address: addr }) };
}

describe("GET /api/idiot/genius/[address] (forward-first)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("validator responds → forwards verbatim with validator source header", async () => {
    const validatorBody = {
      address: GENIUS,
      quality_score_avg: 250,
      total_signals: 4,
      settled_batches: 4,
      win_rate: 0.75,
      favorable: 3,
      unfavorable: 1,
      void: 0,
      recent_settlements: [
        {
          batch_id: 4,
          quality_score: 1000,
          tranche_a: 50000000,
          tranche_b: 50000000,
          protocol_fee: 500000,
          block_number: 104,
        },
      ],
    };

    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const url = typeof input === "string" ? input : (input as Request).url;
      if (url.includes(`/v1/genius/${GENIUS}/track_record`)) {
        return new Response(JSON.stringify(validatorBody), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        });
      }
      throw new Error(`Unmocked: ${url}`);
    });

    const resp = await GET(mkReq(), mkParams(GENIUS));
    expect(resp.status).toBe(200);
    expect(resp.headers.get("x-djinn-source")).toBe("validator");
    const body = await resp.json();
    expect(body.address).toBe(GENIUS);
    expect(body.settled_batches).toBe(4);
    expect(body.win_rate).toBe(0.75);
  });

  it("invalid address → 400 before any fetch", async () => {
    const spy = vi.spyOn(globalThis, "fetch");
    const resp = await GET(mkReq(), mkParams("not-an-address"));
    expect(resp.status).toBe(400);
    expect(spy).not.toHaveBeenCalled();
  });

  it("validator unreachable → falls back to local path", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const url = typeof input === "string" ? input : (input as Request).url;
      if (url.includes("/v1/genius/")) {
        throw new Error("ECONNREFUSED");
      }
      throw new Error(`Unmocked: ${url}`);
    });
    const resp = await GET(mkReq(), mkParams(GENIUS));
    expect(resp.headers.get("x-djinn-source")).not.toBe("validator");
  });

  it("validator 503 → falls back to local path", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const url = typeof input === "string" ? input : (input as Request).url;
      if (url.includes("/v1/genius/")) {
        return new Response(JSON.stringify({ error: "down" }), { status: 503 });
      }
      throw new Error(`Unmocked: ${url}`);
    });
    const resp = await GET(mkReq(), mkParams(GENIUS));
    expect(resp.headers.get("x-djinn-source")).not.toBe("validator");
  });

  it("cache-control header carried on forwarded response", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async () => {
      return new Response(
        JSON.stringify({
          address: GENIUS,
          quality_score_avg: 0,
          total_signals: 0,
          settled_batches: 0,
          win_rate: 0,
          favorable: 0,
          unfavorable: 0,
          void: 0,
          recent_settlements: [],
        }),
        { status: 200 },
      );
    });
    const resp = await GET(mkReq(), mkParams(GENIUS));
    expect(resp.headers.get("cache-control")).toContain("s-maxage=30");
  });
});
