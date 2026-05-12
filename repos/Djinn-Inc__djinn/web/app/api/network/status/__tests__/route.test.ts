import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";

const mockDiscoverMetagraph = vi.fn();
const mockProbeDjinnValidator = vi.fn();
vi.mock("@/lib/bt-metagraph", () => ({
  discoverMetagraph: (...args: unknown[]) => mockDiscoverMetagraph(...args),
  probeDjinnValidator: (...args: unknown[]) => mockProbeDjinnValidator(...args),
}));

vi.mock("@/lib/ss58", () => ({
  hexToSs58: (hex: string) => `ss58-${hex}`,
}));

import { GET } from "../route";

/**
 * Mock fetch for: (a) the primary /v1/network/overview call and (b) any
 * follow-up /v1/network/miners scoring-data fetch the local fallback
 * path makes. Without handling (b), the real fetch hangs against the
 * fake test IP and trips the test timeout.
 */
function installFetchMock(primary: { status: number; body: unknown } | { error: unknown }) {
  return vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
    const url = typeof input === "string" ? input : (input as Request).url;
    if (url.includes("/v1/network/overview")) {
      if ("error" in primary) throw primary.error;
      return new Response(JSON.stringify(primary.body), {
        status: primary.status,
        headers: { "Content-Type": "application/json" },
      });
    }
    if (url.includes("/v1/network/miners")) {
      // Local fallback path fetches scoring data from top-stake validator.
      return new Response(JSON.stringify({ miners: [] }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    }
    throw new Error(`Unmocked fetch: ${url}`);
  });
}

const SAMPLE_NODES = [
  {
    uid: 0,
    hotkey: "0xV0",
    coldkey: "0xC0",
    ip: "45.79.88.1",
    port: 8421,
    isValidator: true,
    stake: 10_000n,
    alphaStake: 10_000n,
    taoStake: 0n,
    totalStake: 10_000n,
    rank: 0,
    emission: 100n,
    incentive: 0.0,
    consensus: 0.9,
    trust: 0,
    validatorTrust: 0.9,
    dividends: 0.3,
  },
  {
    uid: 5,
    hotkey: "0xM5",
    coldkey: "0xCM5",
    ip: "167.150.153.11",
    port: 8100,
    isValidator: false,
    stake: 0n,
    alphaStake: 0n,
    taoStake: 0n,
    totalStake: 0n,
    rank: 0,
    emission: 50n,
    incentive: 0.4,
    consensus: 0,
    trust: 0,
    validatorTrust: 0,
    dividends: 0,
  },
];

describe("GET /api/network/status (forward-first)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockDiscoverMetagraph.mockResolvedValue({ nodes: SAMPLE_NODES });
    mockProbeDjinnValidator.mockResolvedValue({
      port: 8421,
      health: { status: "ok", version: "1348", shares_held: 10, chain_connected: true },
    });
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("validator responds → forwards verbatim with validator source header", async () => {
    installFetchMock({
      status: 200,
      body: {
        summary: { totalValidators: 5, totalMiners: 200, burnPercent: 90.1 },
        validators: [{ uid: 0, stake: "10000" }],
        miners: [],
        ipClusters: {},
        served_by_uid: 0,
      },
    });
    const resp = await GET();
    expect(resp.status).toBe(200);
    expect(resp.headers.get("x-djinn-source")).toBe("validator");
    const body = await resp.json();
    expect(body.summary.totalValidators).toBe(5);
    expect(body.served_by_uid).toBe(0);
    expect(mockDiscoverMetagraph).not.toHaveBeenCalled();
  });

  it("validator unreachable → falls back to local metagraph", async () => {
    installFetchMock({ error: new Error("down") });
    const resp = await GET();
    expect(resp.status).toBe(200);
    expect(resp.headers.get("x-djinn-source")).toBe("vercel-local");
    const body = await resp.json();
    expect(body.summary.totalValidators).toBe(1);
    expect(body.summary.totalMiners).toBe(1);
    expect(mockDiscoverMetagraph).toHaveBeenCalledTimes(1);
  });

  it("validator 5xx → falls back to local metagraph", async () => {
    installFetchMock({ status: 503, body: { error: "down" } });
    const resp = await GET();
    expect(resp.status).toBe(200);
    expect(resp.headers.get("x-djinn-source")).toBe("vercel-local");
    expect(mockDiscoverMetagraph).toHaveBeenCalledTimes(1);
  });

  it("validator 404 → falls back to local metagraph", async () => {
    installFetchMock({ status: 404, body: { error: "not found" } });
    const resp = await GET();
    expect(resp.status).toBe(200);
    expect(resp.headers.get("x-djinn-source")).toBe("vercel-local");
    expect(mockDiscoverMetagraph).toHaveBeenCalledTimes(1);
  });

  it("local fallback: metagraph error returns 500", async () => {
    installFetchMock({ error: new Error("down") });
    mockDiscoverMetagraph.mockRejectedValueOnce(new Error("rpc down"));
    const resp = await GET();
    expect(resp.status).toBe(500);
    expect(resp.headers.get("x-djinn-source")).toBe("vercel-local");
    const body = await resp.json();
    expect(body.summary).toBeNull();
    expect(body.validators).toEqual([]);
  });
});
