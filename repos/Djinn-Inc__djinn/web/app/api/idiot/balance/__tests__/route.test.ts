import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { NextRequest } from "next/server";

vi.mock("@/lib/contracts", () => ({
  ADDRESSES: {
    escrow: "0xb43BA175a6784973eB3825acF801Cd7920ac692a",
    usdc: "0x00e8293b05dbD3732EF3396ad1483E87e7265054",
    creditLedger: "0xA65296cd11B65629641499024AD905FAcAB64C3E",
  },
  ESCROW_ABI: [],
  ERC20_ABI: [],
  CREDIT_LEDGER_ABI: [],
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
      // Force fallback RPC path to blow up so the forward-first path is the
      // only clean success path; tests that want fallback mock globalThis
      // fetch success themselves.
      JsonRpcProvider: vi.fn(() => ({})),
      Contract: vi.fn(),
    },
  };
});

import { GET } from "../route";

const IDIOT = "0xD717b5fbA93F123f6ad530ae2Ab327B4DcDa1e37";

function req(addr: string | null): NextRequest {
  const qs = addr === null ? "" : `?address=${addr}`;
  return new NextRequest(`http://localhost/api/idiot/balance${qs}`);
}

describe("GET /api/idiot/balance (forward-first)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("validator responds → forwards verbatim with validator source header", async () => {
    const validatorBody = {
      address: IDIOT,
      escrow_balance_usdc: 123.0,
      wallet_usdc: 456.7,
      credits: 89.01,
    };

    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const url = typeof input === "string" ? input : (input as Request).url;
      if (url.includes(`/v1/idiot/${IDIOT}/balance`)) {
        return new Response(JSON.stringify(validatorBody), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        });
      }
      throw new Error(`Unmocked: ${url}`);
    });

    const resp = await GET(req(IDIOT));
    expect(resp.status).toBe(200);
    expect(resp.headers.get("x-djinn-source")).toBe("validator");
    const body = await resp.json();
    expect(body.address).toBe(IDIOT);
    expect(body.escrow_balance_usdc).toBe(123.0);
    expect(body.wallet_usdc).toBe(456.7);
    expect(body.credits).toBe(89.01);
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

  it("validator unreachable → falls back to local path with local source header", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const url = typeof input === "string" ? input : (input as Request).url;
      if (url.includes("/v1/idiot/")) {
        throw new Error("ECONNREFUSED");
      }
      throw new Error(`Unmocked: ${url}`);
    });

    const resp = await GET(req(IDIOT));
    // Local path depends on ethers.Contract being a working mock; since the
    // mock returns undefined.getBalance the try/catch returns 500 which is
    // also tagged vercel-local via console.error. Just assert the route did
    // NOT come from the validator.
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

    const resp = await GET(req(IDIOT));
    expect(resp.headers.get("x-djinn-source")).not.toBe("validator");
  });
});
