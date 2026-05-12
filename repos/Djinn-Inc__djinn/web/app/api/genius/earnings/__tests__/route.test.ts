import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { NextRequest } from "next/server";

vi.mock("@/lib/contracts", () => ({
  ADDRESSES: {
    collateral: "0x71F0a8c6BBFc4C83c5203807fAdd305B0C0F4C88",
    audit: "0xCa7e642FE31BA83a7a857644E8894c1B93a2a44E",
  },
  COLLATERAL_ABI: [],
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
      // Fallback path fails cleanly; tests only assert source tag.
      JsonRpcProvider: vi.fn(() => ({})),
      Contract: vi.fn(),
    },
  };
});

import { GET } from "../route";

const GENIUS = "0x68fc8eeC9E5551d4c93a89b6d861f0a05e0A2A1d";

function req(addr: string | null): NextRequest {
  const qs = addr === null ? "" : `?address=${addr}`;
  return new NextRequest(`http://localhost/api/genius/earnings${qs}`);
}

describe("GET /api/genius/earnings (forward-first)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("validator responds → forwards verbatim with validator source header", async () => {
    const validatorBody = {
      address: GENIUS,
      collateral_deposited_usdc: 5.0,
      collateral_locked_usdc: 1.5,
      collateral_available_usdc: 3.5,
      settled_batches: 3,
      quality_score_avg: 300,
      recent_settlements: [
        { batch_id: 3, quality_score: 500, block_number: 3 },
      ],
    };

    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const url = typeof input === "string" ? input : (input as Request).url;
      if (url.includes(`/v1/genius/${GENIUS}/earnings`)) {
        return new Response(JSON.stringify(validatorBody), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        });
      }
      throw new Error(`Unmocked: ${url}`);
    });

    const resp = await GET(req(GENIUS));
    expect(resp.status).toBe(200);
    expect(resp.headers.get("x-djinn-source")).toBe("validator");
    const body = await resp.json();
    expect(body.collateral_deposited_usdc).toBe(5.0);
    expect(body.collateral_available_usdc).toBe(3.5);
    expect(body.settled_batches).toBe(3);
  });

  it("invalid address → 400 before any fetch", async () => {
    const spy = vi.spyOn(globalThis, "fetch");
    const resp = await GET(req("not-an-address"));
    expect(resp.status).toBe(400);
    expect(spy).not.toHaveBeenCalled();
  });

  it("missing address → 400", async () => {
    const resp = await GET(req(null));
    expect(resp.status).toBe(400);
  });

  it("validator unreachable → falls back to local path", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const url = typeof input === "string" ? input : (input as Request).url;
      if (url.includes("/v1/genius/")) {
        throw new Error("ECONNREFUSED");
      }
      throw new Error(`Unmocked: ${url}`);
    });
    const resp = await GET(req(GENIUS));
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
    const resp = await GET(req(GENIUS));
    expect(resp.headers.get("x-djinn-source")).not.toBe("validator");
  });

  it("cache-control header carried on forwarded response", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async () => {
      return new Response(
        JSON.stringify({
          address: GENIUS,
          collateral_deposited_usdc: 0,
          collateral_locked_usdc: 0,
          collateral_available_usdc: 0,
          settled_batches: 0,
          quality_score_avg: 0,
          recent_settlements: [],
        }),
        { status: 200 },
      );
    });
    const resp = await GET(req(GENIUS));
    expect(resp.headers.get("cache-control")).toContain("s-maxage=30");
  });
});
