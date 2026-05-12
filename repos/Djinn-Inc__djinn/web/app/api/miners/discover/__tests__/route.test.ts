import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";

const mockDiscoverMiners = vi.fn();
vi.mock("@/lib/bt-metagraph", () => ({
  discoverMiners: (...args: unknown[]) => mockDiscoverMiners(...args),
}));

vi.mock("@/lib/ss58", () => ({
  hexToSs58: (hex: string) => `ss58-${hex}`,
}));

import { GET } from "../route";

function mockFetchOnce(status: number, body: unknown) {
  const resp = new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
  return vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(resp);
}

function mockFetchReject(err: unknown = new Error("down")) {
  return vi.spyOn(globalThis, "fetch").mockRejectedValueOnce(err);
}

const SAMPLE_MINERS = [
  {
    uid: 10,
    hotkey: "0xM10",
    coldkey: "0xCM10",
    ip: "167.150.153.11",
    port: 8100,
    isValidator: false,
    stake: 0n,
    alphaStake: 0n,
    taoStake: 0n,
    totalStake: 0n,
    rank: 0.2,
    emission: 50n,
    incentive: 0.4,
    consensus: 0.0,
    trust: 0.0,
    validatorTrust: 0.0,
    dividends: 0.0,
  },
];

describe("GET /api/miners/discover (forward-first)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockDiscoverMiners.mockResolvedValue(SAMPLE_MINERS);
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("validator responds → forwards verbatim with validator source header", async () => {
    mockFetchOnce(200, { miners: [{ uid: 99, hotkey: "5M" }], miner_count: 1 });
    const resp = await GET();
    expect(resp.status).toBe(200);
    expect(resp.headers.get("x-djinn-source")).toBe("validator");
    const body = await resp.json();
    expect(body.miner_count).toBe(1);
    expect(body.miners[0].uid).toBe(99);
    expect(mockDiscoverMiners).not.toHaveBeenCalled();
  });

  it("validator unreachable → falls back to local metagraph", async () => {
    mockFetchReject();
    const resp = await GET();
    expect(resp.status).toBe(200);
    expect(resp.headers.get("x-djinn-source")).toBe("vercel-local");
    const body = await resp.json();
    expect(body.miners).toHaveLength(1);
    expect(body.miners[0].uid).toBe(10);
  });

  it("validator 5xx → falls back to local metagraph", async () => {
    mockFetchOnce(503, { error: "down" });
    const resp = await GET();
    expect(resp.status).toBe(200);
    expect(resp.headers.get("x-djinn-source")).toBe("vercel-local");
    expect(mockDiscoverMiners).toHaveBeenCalledTimes(1);
  });

  it("validator 404 → falls back to local metagraph", async () => {
    mockFetchOnce(404, { error: "not found" });
    const resp = await GET();
    expect(resp.status).toBe(200);
    expect(resp.headers.get("x-djinn-source")).toBe("vercel-local");
    expect(mockDiscoverMiners).toHaveBeenCalledTimes(1);
  });

  it("local fallback: ss58Hotkey is derived via hexToSs58", async () => {
    mockFetchReject();
    const resp = await GET();
    const body = await resp.json();
    expect(body.miners[0].ss58Hotkey).toBe("ss58-0xM10");
  });

  it("local fallback: metagraph error returns 500", async () => {
    mockFetchReject();
    mockDiscoverMiners.mockRejectedValueOnce(new Error("rpc down"));
    const resp = await GET();
    expect(resp.status).toBe(500);
    expect(resp.headers.get("x-djinn-source")).toBe("vercel-local");
    const body = await resp.json();
    expect(body.miners).toEqual([]);
  });
});
