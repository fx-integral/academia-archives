import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";

const mockDiscoverMetagraph = vi.fn();
const mockIsPublicIp = vi.fn();
vi.mock("@/lib/bt-metagraph", () => ({
  discoverMetagraph: (...args: unknown[]) => mockDiscoverMetagraph(...args),
  isPublicIp: (...args: unknown[]) => mockIsPublicIp(...args),
}));

import { GET } from "../route";

/**
 * URL-pattern fetch mock. Primary path: /v1/network/matrix on the bootstrap.
 * Fallback path makes N parallel /health + /v1/network/miners fetches against
 * every public validator, so we need to handle those too.
 */
function installFetchMock(primary: { status: number; body: unknown } | { error: unknown }) {
  return vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
    const url = typeof input === "string" ? input : (input as Request).url;
    if (url.includes("/v1/network/matrix")) {
      if ("error" in primary) throw primary.error;
      return new Response(JSON.stringify(primary.body), {
        status: primary.status,
        headers: { "Content-Type": "application/json" },
      });
    }
    if (url.includes("/health")) {
      return new Response(JSON.stringify({ status: "ok", version: "1350" }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    }
    if (url.includes("/v1/network/miners")) {
      return new Response(JSON.stringify({ miners: [{ uid: 5, hotkey: "5M5", weight: 0.5 }] }), {
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
];

describe("GET /api/network/matrix (forward-first)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockDiscoverMetagraph.mockResolvedValue({ nodes: SAMPLE_NODES });
    mockIsPublicIp.mockReturnValue(true);
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("validator responds → forwards verbatim with validator source header", async () => {
    installFetchMock({
      status: 200,
      body: {
        validators: [{ uid: 42, ip: "1.2.3.4", port: 8421, miners: {} }],
        minerUids: [],
        timestamp: 1234,
      },
    });
    const resp = await GET();
    expect(resp.status).toBe(200);
    expect(resp.headers.get("x-djinn-source")).toBe("validator");
    const body = await resp.json();
    expect(body.validators[0].uid).toBe(42);
    expect(body.timestamp).toBe(1234);
    expect(mockDiscoverMetagraph).not.toHaveBeenCalled();
  });

  it("validator unreachable → falls back to local fan-out", async () => {
    installFetchMock({ error: new Error("down") });
    const resp = await GET();
    expect(resp.status).toBe(200);
    expect(resp.headers.get("x-djinn-source")).toBe("vercel-local");
    const body = await resp.json();
    expect(body.validators).toHaveLength(1);
    expect(body.validators[0].uid).toBe(0);
    expect(body.validators[0].healthy).toBe(true);
    expect(body.validators[0].version).toBe("1350");
    expect(mockDiscoverMetagraph).toHaveBeenCalledTimes(1);
  });

  it("validator 5xx → falls back to local fan-out", async () => {
    installFetchMock({ status: 503, body: { error: "down" } });
    const resp = await GET();
    expect(resp.status).toBe(200);
    expect(resp.headers.get("x-djinn-source")).toBe("vercel-local");
    expect(mockDiscoverMetagraph).toHaveBeenCalledTimes(1);
  });

  it("validator 404 → falls back to local fan-out", async () => {
    installFetchMock({ status: 404, body: { error: "not found" } });
    const resp = await GET();
    expect(resp.status).toBe(200);
    expect(resp.headers.get("x-djinn-source")).toBe("vercel-local");
    expect(mockDiscoverMetagraph).toHaveBeenCalledTimes(1);
  });

  it("local fallback: minerUids aggregated across validators", async () => {
    installFetchMock({ error: new Error("down") });
    const resp = await GET();
    const body = await resp.json();
    expect(body.minerUids).toEqual([5]);
  });

  it("local fallback: metagraph error returns 500", async () => {
    installFetchMock({ error: new Error("down") });
    mockDiscoverMetagraph.mockRejectedValueOnce(new Error("rpc down"));
    const resp = await GET();
    expect(resp.status).toBe(500);
    expect(resp.headers.get("x-djinn-source")).toBe("vercel-local");
    const body = await resp.json();
    expect(body.validators).toEqual([]);
    expect(body.minerUids).toEqual([]);
  });
});
