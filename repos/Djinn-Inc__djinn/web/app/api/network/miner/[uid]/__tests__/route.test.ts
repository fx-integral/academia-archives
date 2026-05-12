import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";

const mockDiscoverMetagraph = vi.fn();
vi.mock("@/lib/bt-metagraph", () => ({
  discoverMetagraph: (...args: unknown[]) => mockDiscoverMetagraph(...args),
}));

import { GET } from "../route";

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
    emission: 200n,
    incentive: 0.4,
    consensus: 0,
    trust: 0,
    validatorTrust: 0,
    dividends: 0,
  },
];

function mkParams(uid: string) {
  return { params: Promise.resolve({ uid }) };
}

describe("GET /api/network/miner/[uid] (forward-first)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockDiscoverMetagraph.mockResolvedValue({ nodes: SAMPLE_NODES });
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("validator responds → forwards verbatim with validator source header", async () => {
    const validatorBody = {
      uid: 5,
      scores: [
        { validatorUid: 0, uid: 5, found: true, hotkey: "0xM5", accuracy: 0.9 },
        { validatorUid: 1, uid: 5, found: true, hotkey: "0xM5", accuracy: 0.88 },
      ],
      metagraph: { ip: "167.150.153.11", isValidator: false, incentive: 0.4, emission: "200", stake: "0" },
    };
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const url = typeof input === "string" ? input : (input as Request).url;
      if (url.includes("/v1/network/miner/5")) {
        return new Response(JSON.stringify(validatorBody), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        });
      }
      throw new Error(`Unmocked: ${url}`);
    });

    const resp = await GET(new Request("http://localhost/api/network/miner/5"), mkParams("5"));
    expect(resp.status).toBe(200);
    expect(resp.headers.get("x-djinn-source")).toBe("validator");
    const body = await resp.json();
    expect(body.uid).toBe(5);
    expect(body.scores).toHaveLength(2);
    expect(mockDiscoverMetagraph).not.toHaveBeenCalled();
  });

  it("validator unreachable → falls back to metagraph-based fan-out", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const url = typeof input === "string" ? input : (input as Request).url;
      if (url.includes("/v1/network/miner/5")) {
        throw new Error("ECONNREFUSED");
      }
      if (url.includes("/v1/miner/5/scores")) {
        return new Response(
          JSON.stringify({ uid: 5, found: true, hotkey: "0xM5", accuracy: 0.9 }),
          { status: 200 },
        );
      }
      throw new Error(`Unmocked: ${url}`);
    });

    const resp = await GET(new Request("http://localhost/api/network/miner/5"), mkParams("5"));
    expect(resp.status).toBe(200);
    expect(resp.headers.get("x-djinn-source")).toBe("vercel-local");
    expect(mockDiscoverMetagraph).toHaveBeenCalledTimes(1);
    const body = await resp.json();
    expect(body.uid).toBe(5);
    expect(body.metagraph).not.toBeNull();
  });

  it("validator 503 → falls back to fan-out", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const url = typeof input === "string" ? input : (input as Request).url;
      if (url.includes("/v1/network/miner/5")) {
        return new Response(JSON.stringify({ error: "down" }), { status: 503 });
      }
      if (url.includes("/v1/miner/5/scores")) {
        return new Response(JSON.stringify({ uid: 5, found: true }), { status: 200 });
      }
      throw new Error(`Unmocked: ${url}`);
    });
    const resp = await GET(new Request("http://localhost/api/network/miner/5"), mkParams("5"));
    expect(resp.headers.get("x-djinn-source")).toBe("vercel-local");
    expect(mockDiscoverMetagraph).toHaveBeenCalledTimes(1);
  });

  it("invalid UID rejected before any fetch", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch");
    const resp = await GET(
      new Request("http://localhost/api/network/miner/notanumber"),
      mkParams("notanumber"),
    );
    expect(resp.status).toBe(400);
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it("out-of-range UID rejected", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch");
    const resp = await GET(
      new Request("http://localhost/api/network/miner/99999"),
      mkParams("99999"),
    );
    expect(resp.status).toBe(400);
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it("cache-control header carried on forwarded response", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async () => {
      return new Response(
        JSON.stringify({ uid: 5, scores: [], metagraph: null }),
        { status: 200 },
      );
    });
    const resp = await GET(new Request("http://localhost/api/network/miner/5"), mkParams("5"));
    expect(resp.headers.get("cache-control")).toContain("s-maxage=30");
  });
});
