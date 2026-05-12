import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";

const mockDiscoverMetagraph = vi.fn();
vi.mock("@/lib/bt-metagraph", () => ({
  discoverMetagraph: (...args: unknown[]) => mockDiscoverMetagraph(...args),
}));

import { GET } from "../route";

function installFetchMock(primary: { status: number; body: unknown } | { error: unknown }) {
  return vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
    const url = typeof input === "string" ? input : (input as Request).url;
    if (url.includes("/v1/miner/") && url.includes("/history")) {
      if ("error" in primary) throw primary.error;
      return new Response(JSON.stringify(primary.body), {
        status: primary.status,
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

function mkParams(uid: string) {
  return { params: Promise.resolve({ uid }) };
}

describe("GET /api/network/miner/[uid]/history (forward-first)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockDiscoverMetagraph.mockResolvedValue({ nodes: SAMPLE_NODES });
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("validator responds with non-empty history → forwards verbatim", async () => {
    installFetchMock({
      status: 200,
      body: {
        uid: 5,
        history: [
          { epoch: 100, weight: 0.01 },
          { epoch: 101, weight: 0.012 },
        ],
      },
    });
    const resp = await GET(
      new Request("http://localhost/api/network/miner/5/history?hours=24"),
      mkParams("5"),
    );
    expect(resp.status).toBe(200);
    expect(resp.headers.get("x-djinn-source")).toBe("validator");
    const body = await resp.json();
    expect(body.uid).toBe(5);
    expect(body.history).toHaveLength(2);
    expect(mockDiscoverMetagraph).not.toHaveBeenCalled();
  });

  it("validator empty history → falls through to fan-out", async () => {
    installFetchMock({ status: 200, body: { uid: 5, history: [] } });
    const resp = await GET(
      new Request("http://localhost/api/network/miner/5/history"),
      mkParams("5"),
    );
    expect(resp.status).toBe(200);
    expect(resp.headers.get("x-djinn-source")).toBe("vercel-local");
    expect(mockDiscoverMetagraph).toHaveBeenCalledTimes(1);
  });

  it("validator unreachable → falls back to fan-out", async () => {
    installFetchMock({ error: new Error("down") });
    const resp = await GET(
      new Request("http://localhost/api/network/miner/5/history"),
      mkParams("5"),
    );
    expect(resp.status).toBe(200);
    expect(resp.headers.get("x-djinn-source")).toBe("vercel-local");
    expect(mockDiscoverMetagraph).toHaveBeenCalledTimes(1);
  });

  it("invalid UID rejected before forwarding", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch");
    const resp = await GET(
      new Request("http://localhost/api/network/miner/notanumber/history"),
      mkParams("notanumber"),
    );
    expect(resp.status).toBe(400);
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it("hours query forwarded to validator", async () => {
    let capturedUrl = "";
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const url = typeof input === "string" ? input : (input as Request).url;
      if (url.includes("/v1/miner/") && url.includes("/history")) {
        capturedUrl = url;
        return new Response(JSON.stringify({ uid: 5, history: [{ e: 1 }] }), { status: 200 });
      }
      throw new Error(`Unmocked: ${url}`);
    });
    await GET(
      new Request("http://localhost/api/network/miner/5/history?hours=48"),
      mkParams("5"),
    );
    expect(capturedUrl).toContain("hours=48");
  });
});
