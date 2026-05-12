import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";

vi.mock("@/lib/contracts", () => ({
  ADDRESSES: {
    signalCommitment: "0x4712479Ba57c9ED40405607b2B18967B359209C0",
    escrow: "0xb43BA175a6784973eB3825acF801Cd7920ac692a",
    collateral: "0x71F0a8c6BBFc4C83c5203807fAdd305B0C0F4C88",
    account: "0x4546354Dd32a613B76Abf530F81c8359e7cE440B",
    audit: "0xCa7e642FE31BA83a7a857644E8894c1B93a2a44E",
    creditLedger: "0xA65296cd11B65629641499024AD905FAcAB64C3E",
    keyRecovery: "0x496919DB9BC4590323cd019fE874311AC6116525",
    usdc: "0x00e8293b05dbD3732EF3396ad1483E87e7265054",
  },
}));

vi.mock("@/lib/bt-metagraph", () => ({
  discoverMetagraph: vi.fn(async () => ({ nodes: [] })),
  isPublicIp: () => true,
}));

import { GET } from "../route";

describe("GET /api/network/config (forward-first)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("validator responds → forwards verbatim with validator source header", async () => {
    const validatorBody = {
      validators: [
        {
          uid: 0,
          name: "UID 0",
          endpoint: "http://45.79.88.1:8421",
          pubkey: null,
        },
      ],
      chain_id: 84532,
      contracts: {
        signal_commitment: "0x4712479Ba57c9ED40405607b2B18967B359209C0",
        escrow: "0xb43BA175a6784973eB3825acF801Cd7920ac692a",
        collateral: "0x71F0a8c6BBFc4C83c5203807fAdd305B0C0F4C88",
        account: "0x4546354Dd32a613B76Abf530F81c8359e7cE440B",
        audit: "0xCa7e642FE31BA83a7a857644E8894c1B93a2a44E",
        credit_ledger: "0xA65296cd11B65629641499024AD905FAcAB64C3E",
        key_recovery: "0x496919DB9BC4590323cd019fE874311AC6116525",
        usdc: "0x00e8293b05dbD3732EF3396ad1483E87e7265054",
      },
      shamir: { n: 10, k: 3 },
      cached_at: "2026-04-19T19:40:00Z",
    };

    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const url = typeof input === "string" ? input : (input as Request).url;
      if (url.includes("/v1/network/config")) {
        return new Response(JSON.stringify(validatorBody), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        });
      }
      throw new Error(`Unmocked: ${url}`);
    });

    const resp = await GET();
    expect(resp.status).toBe(200);
    expect(resp.headers.get("x-djinn-source")).toBe("validator");
    const body = await resp.json();
    expect(body.validators).toHaveLength(1);
    expect(body.contracts.signal_commitment).toBe(
      "0x4712479Ba57c9ED40405607b2B18967B359209C0",
    );
    expect(body.shamir.n).toBe(10);
  });

  it("validator unreachable → falls back to local discovery + identity probe", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const url = typeof input === "string" ? input : (input as Request).url;
      if (url.includes("/v1/network/config")) {
        throw new Error("ECONNREFUSED");
      }
      // Fallback probes to each validator's /v1/identity (return minimal ok response).
      if (url.includes("/v1/identity")) {
        return new Response(
          JSON.stringify({ base_address: "0x0", hotkey: "5V0", version: "test" }),
          { status: 200, headers: { "Content-Type": "application/json" } },
        );
      }
      throw new Error(`Unmocked: ${url}`);
    });

    const resp = await GET();
    expect(resp.status).toBe(200);
    expect(resp.headers.get("x-djinn-source")).toBe("vercel-local");
    const body = await resp.json();
    // Local config blob has the SAME structural shape as the validator output.
    expect(body.contracts.signal_commitment).toBe(
      "0x4712479Ba57c9ED40405607b2B18967B359209C0",
    );
    expect(body.shamir).toBeDefined();
    expect(body.chain_id).toBeGreaterThan(0);
  });

  it("validator 503 → falls back to local discovery", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const url = typeof input === "string" ? input : (input as Request).url;
      if (url.includes("/v1/network/config")) {
        return new Response(JSON.stringify({ error: "down" }), { status: 503 });
      }
      if (url.includes("/v1/identity")) {
        return new Response(
          JSON.stringify({ base_address: "0x0", hotkey: "5V0", version: "test" }),
          { status: 200 },
        );
      }
      throw new Error(`Unmocked: ${url}`);
    });

    const resp = await GET();
    expect(resp.headers.get("x-djinn-source")).toBe("vercel-local");
  });

  it("forwarded response carries cache-control", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const url = typeof input === "string" ? input : (input as Request).url;
      if (url.includes("/v1/network/config")) {
        return new Response(
          JSON.stringify({
            validators: [],
            chain_id: 84532,
            contracts: {},
            shamir: { n: 10, k: 3 },
            cached_at: "",
          }),
          { status: 200 },
        );
      }
      throw new Error(`Unmocked: ${url}`);
    });
    const resp = await GET();
    expect(resp.headers.get("cache-control")).toContain("max-age=300");
  });
});
