import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";

const mockDiscoverMetagraph = vi.fn();
const mockProbeDjinnValidator = vi.fn();
const mockIsPublicIp = vi.fn((ip: string) => !!ip && !ip.startsWith("10.") && !ip.startsWith("192.168.") && !ip.startsWith("127."));
vi.mock("@/lib/bt-metagraph", () => ({
  discoverMetagraph: (...args: unknown[]) => mockDiscoverMetagraph(...args),
  probeDjinnValidator: (...args: unknown[]) => mockProbeDjinnValidator(...args),
  isPublicIp: (ip: string) => mockIsPublicIp(ip),
}));

import { GET } from "../route";

function installFetchMock(primary: { status: number; body: unknown } | { error: unknown }) {
  return vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
    const url = typeof input === "string" ? input : (input as Request).url;
    if (url.includes("/v1/network/validator/")) {
      if ("error" in primary) throw primary.error;
      return new Response(JSON.stringify(primary.body), {
        status: primary.status,
        headers: { "Content-Type": "application/json" },
      });
    }
    if (url.includes("/v1/network/miners")) {
      return new Response(JSON.stringify({ miners: [], validator_uid: 0 }), {
        status: 200,
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

describe("GET /api/network/validator/[uid] (forward-first)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockDiscoverMetagraph.mockResolvedValue({ nodes: SAMPLE_NODES });
    mockProbeDjinnValidator.mockResolvedValue({
      port: 8421,
      health: { status: "ok", version: "1356" },
    });
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("validator responds → forwards verbatim with validator source header", async () => {
    installFetchMock({
      status: 200,
      body: {
        uid: 0,
        found: true,
        metagraph: { ip: "45.79.88.1", port: 8421, stake: "10000", incentive: 0, emission: "100", validatorTrust: 0.9 },
        health: { status: "ok", version: "1356" },
        miners: [{ uid: 5, hotkey: "0xM5" }],
        validatorUid: 0,
      },
    });
    const resp = await GET(new Request("http://localhost/api/network/validator/0"), mkParams("0"));
    expect(resp.status).toBe(200);
    expect(resp.headers.get("x-djinn-source")).toBe("validator");
    const body = await resp.json();
    expect(body.uid).toBe(0);
    expect(body.found).toBe(true);
    expect(body.miners).toHaveLength(1);
    expect(mockDiscoverMetagraph).not.toHaveBeenCalled();
  });

  it("validator 5xx → falls back to local metagraph", async () => {
    installFetchMock({ status: 503, body: { error: "down" } });
    const resp = await GET(new Request("http://localhost/api/network/validator/0"), mkParams("0"));
    expect(resp.status).toBe(200);
    expect(resp.headers.get("x-djinn-source")).toBe("vercel-local");
    const body = await resp.json();
    expect(body.uid).toBe(0);
    expect(body.found).toBe(true);
    expect(mockDiscoverMetagraph).toHaveBeenCalledTimes(1);
  });

  it("validator unreachable → falls back to local metagraph", async () => {
    installFetchMock({ error: new Error("down") });
    const resp = await GET(new Request("http://localhost/api/network/validator/0"), mkParams("0"));
    expect(resp.status).toBe(200);
    expect(resp.headers.get("x-djinn-source")).toBe("vercel-local");
    expect(mockDiscoverMetagraph).toHaveBeenCalledTimes(1);
  });

  it("local fallback returns 404 when validator missing from metagraph", async () => {
    installFetchMock({ error: new Error("down") });
    mockDiscoverMetagraph.mockResolvedValueOnce({ nodes: [] });
    const resp = await GET(new Request("http://localhost/api/network/validator/99"), mkParams("99"));
    expect(resp.status).toBe(404);
    expect(resp.headers.get("x-djinn-source")).toBe("vercel-local");
    const body = await resp.json();
    expect(body.found).toBe(false);
  });

  it("invalid UID rejected before forwarding", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch");
    const resp = await GET(new Request("http://localhost/api/network/validator/abc"), mkParams("abc"));
    expect(resp.status).toBe(400);
    expect(fetchSpy).not.toHaveBeenCalled();
  });
});
