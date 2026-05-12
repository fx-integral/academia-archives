import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { NextRequest } from "next/server";

vi.mock("@/lib/contracts", () => ({
  ADDRESSES: {
    account: "0x4546354Dd32a613B76Abf530F81c8359e7cE440B",
  },
  ACCOUNT_ABI: [],
  detectContractVersion: vi.fn(async () => 2),
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

const GENIUS = "0x68fc8eeC9E5551d4c93a89b6d861f0a05e0A2A1d";
const IDIOT = "0xD717b5fbA93F123f6ad530ae2Ab327B4DcDa1e37";

function paramsPromise(g: string, i: string) {
  return Promise.resolve({ genius: g, idiot: i });
}

function req(): NextRequest {
  return new NextRequest(`http://localhost/api/settlement/${GENIUS}/${IDIOT}`);
}

describe("GET /api/settlement/[genius]/[idiot] (forward-first)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("validator responds → forwards verbatim with validator source header", async () => {
    const validatorBody = {
      genius: GENIUS,
      idiot: IDIOT,
      contract_version: 2,
      total_purchases: 12,
      resolved_count: 11,
      audited_count: 0,
      audit_batch_count: 0,
      ready_for_settlement: true,
      current_cycle: 0,
      signals_in_cycle: 12,
    };

    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const url = typeof input === "string" ? input : (input as Request).url;
      if (url.includes(`/v1/settlement/${GENIUS}/${IDIOT}`)) {
        return new Response(JSON.stringify(validatorBody), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        });
      }
      throw new Error(`Unmocked: ${url}`);
    });

    const resp = await GET(req(), { params: paramsPromise(GENIUS, IDIOT) });
    expect(resp.status).toBe(200);
    expect(resp.headers.get("x-djinn-source")).toBe("validator");
    const body = await resp.json();
    expect(body.ready_for_settlement).toBe(true);
    expect(body.total_purchases).toBe(12);
    expect(body.contract_version).toBe(2);
  });

  it("invalid genius → 400 before any fetch", async () => {
    const spy = vi.spyOn(globalThis, "fetch");
    const resp = await GET(req(), { params: paramsPromise("not-an-address", IDIOT) });
    expect(resp.status).toBe(400);
    expect(spy).not.toHaveBeenCalled();
  });

  it("invalid idiot → 400", async () => {
    const resp = await GET(req(), { params: paramsPromise(GENIUS, "not-an-address") });
    expect(resp.status).toBe(400);
  });

  it("validator unreachable → falls back to local path", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const url = typeof input === "string" ? input : (input as Request).url;
      if (url.includes("/v1/settlement/")) {
        throw new Error("ECONNREFUSED");
      }
      throw new Error(`Unmocked: ${url}`);
    });
    const resp = await GET(req(), { params: paramsPromise(GENIUS, IDIOT) });
    expect(resp.headers.get("x-djinn-source")).not.toBe("validator");
  });

  it("validator 503 → falls back to local path", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const url = typeof input === "string" ? input : (input as Request).url;
      if (url.includes("/v1/settlement/")) {
        return new Response(JSON.stringify({ error: "down" }), { status: 503 });
      }
      throw new Error(`Unmocked: ${url}`);
    });
    const resp = await GET(req(), { params: paramsPromise(GENIUS, IDIOT) });
    expect(resp.headers.get("x-djinn-source")).not.toBe("validator");
  });

  it("cache-control header carried on forwarded response", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async () => {
      return new Response(
        JSON.stringify({
          genius: GENIUS,
          idiot: IDIOT,
          contract_version: 1,
          current_cycle: 0,
          signals_in_cycle: 0,
          total_purchases: 0,
          resolved_count: 0,
          audited_count: 0,
          audit_batch_count: 0,
          ready_for_settlement: false,
        }),
        { status: 200 },
      );
    });
    const resp = await GET(req(), { params: paramsPromise(GENIUS, IDIOT) });
    expect(resp.headers.get("cache-control")).toContain("s-maxage=30");
  });
});
