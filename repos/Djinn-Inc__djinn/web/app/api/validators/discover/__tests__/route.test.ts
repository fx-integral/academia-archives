import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { NextRequest } from "next/server";

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

function makeRequest(query = ""): NextRequest {
  return new NextRequest(
    `http://localhost:3000/api/validators/discover${query ? `?${query}` : ""}`,
  );
}

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

const SAMPLE_NODES = [
  {
    uid: 0,
    hotkey: "0xV0",
    coldkey: "0xC0",
    ip: "45.79.88.1",
    port: 8421,
    isValidator: true,
    stake: 10_000n,
    alphaStake: 6_000n,
    taoStake: 4_000n,
    totalStake: 10_000n,
    rank: 0.5,
    emission: 100n,
    incentive: 0.1,
    consensus: 0.9,
    trust: 0.8,
    validatorTrust: 0.95,
    dividends: 0.4,
  },
  {
    uid: 1,
    hotkey: "0xM1",
    coldkey: "0xCM1",
    ip: "45.79.88.2",
    port: 8100,
    isValidator: false,
    stake: 0n,
    alphaStake: 0n,
    taoStake: 0n,
    totalStake: 0n,
    rank: 0.1,
    emission: 50n,
    incentive: 0.3,
    consensus: 0.0,
    trust: 0.0,
    validatorTrust: 0.0,
    dividends: 0.0,
  },
];

describe("GET /api/validators/discover (forward-first)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockDiscoverMetagraph.mockResolvedValue({ nodes: SAMPLE_NODES });
    mockProbeDjinnValidator.mockResolvedValue({ port: 8421 });
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("validator responds → forwards verbatim with validator source header", async () => {
    mockFetchOnce(200, { validators: [{ uid: 42, hotkey: "5V" }], validator_count: 1 });
    const resp = await GET(makeRequest());
    expect(resp.status).toBe(200);
    expect(resp.headers.get("x-djinn-source")).toBe("validator");
    const body = await resp.json();
    expect(body.validator_count).toBe(1);
    expect(body.validators[0].uid).toBe(42);
    expect(mockDiscoverMetagraph).not.toHaveBeenCalled();
  });

  it("validator unreachable → falls back to local metagraph", async () => {
    mockFetchReject();
    const resp = await GET(makeRequest("all=true"));
    expect(resp.status).toBe(200);
    expect(resp.headers.get("x-djinn-source")).toBe("vercel-local");
    const body = await resp.json();
    expect(body.validators).toHaveLength(1);
    expect(body.validators[0].uid).toBe(0);
  });

  it("validator 5xx → falls back to local metagraph", async () => {
    mockFetchOnce(503, { error: "down" });
    const resp = await GET(makeRequest("all=true"));
    expect(resp.status).toBe(200);
    expect(resp.headers.get("x-djinn-source")).toBe("vercel-local");
    expect(mockDiscoverMetagraph).toHaveBeenCalledTimes(1);
  });

  it("validator 404 → falls back to local metagraph", async () => {
    mockFetchOnce(404, { error: "not found" });
    const resp = await GET(makeRequest("all=true"));
    expect(resp.status).toBe(200);
    expect(resp.headers.get("x-djinn-source")).toBe("vercel-local");
    expect(mockDiscoverMetagraph).toHaveBeenCalledTimes(1);
  });

  it("local fallback: all=true skips probing", async () => {
    mockFetchReject();
    await GET(makeRequest("all=true"));
    expect(mockProbeDjinnValidator).not.toHaveBeenCalled();
  });

  it("local fallback: default mode health-checks validators", async () => {
    mockFetchReject();
    await GET(makeRequest());
    expect(mockProbeDjinnValidator).toHaveBeenCalled();
  });

  it("local fallback: ss58Hotkey is derived via hexToSs58", async () => {
    mockFetchReject();
    const resp = await GET(makeRequest("all=true"));
    const body = await resp.json();
    expect(body.validators[0].ss58Hotkey).toBe("ss58-0xV0");
  });

  it("local fallback: metagraph error returns 500", async () => {
    mockFetchReject();
    mockDiscoverMetagraph.mockRejectedValueOnce(new Error("rpc down"));
    const resp = await GET(makeRequest("all=true"));
    expect(resp.status).toBe(500);
    expect(resp.headers.get("x-djinn-source")).toBe("vercel-local");
    const body = await resp.json();
    expect(body.validators).toEqual([]);
  });
});
