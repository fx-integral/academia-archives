import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { NextRequest } from "next/server";

// Mock error-store
const mockStoreError = vi.fn();
vi.mock("@/lib/error-store", () => ({
  storeError: (...args: unknown[]) => mockStoreError(...args),
}));

function makeRequest(body: Record<string, unknown>, ip: string): NextRequest {
  return new NextRequest("http://localhost:3000/api/report-error", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "x-forwarded-for": ip,
    },
    body: JSON.stringify(body),
  });
}

function mockGitHub(status: number, body: unknown = {}): ReturnType<typeof vi.spyOn> {
  const resp = new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
  return vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(resp);
}

function mockGitHubReject(err: unknown = new Error("econnrefused")): ReturnType<typeof vi.spyOn> {
  return vi.spyOn(globalThis, "fetch").mockRejectedValueOnce(err);
}

describe("POST /api/report-error", () => {
  beforeEach(async () => {
    vi.clearAllMocks();
    vi.resetModules();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("503 when GITHUB_ERROR_TOKEN unset (caller should fall back to validator)", async () => {
    vi.stubEnv("GITHUB_ERROR_TOKEN", "");
    const { POST } = await import("../route");
    const resp = await POST(
      makeRequest({ message: "no token here" }, "10.0.0.1"),
    );
    expect(resp.status).toBe(503);
    const body = await resp.json();
    expect(body.ok).toBe(false);
    expect(body.forwarded).toBe(false);
    expect(body.error).toContain("GITHUB_ERROR_TOKEN");
    // Local mirror still happens so the admin dashboard can see it.
    expect(mockStoreError).toHaveBeenCalledTimes(1);
    vi.unstubAllEnvs();
  });

  it("200 when GitHub returns 201 — issue created", async () => {
    vi.stubEnv("GITHUB_ERROR_TOKEN", "fake-token");
    mockGitHub(201, { number: 42 });
    const { POST } = await import("../route");
    const resp = await POST(
      makeRequest(
        { message: "happy path", source: "report-button" },
        "10.0.0.2",
      ),
    );
    expect(resp.status).toBe(200);
    const body = await resp.json();
    expect(body.ok).toBe(true);
    expect(body.forwarded).toBe(true);
    expect(body.issue_number).toBe(42);
    expect(mockStoreError).toHaveBeenCalledTimes(1);
    vi.unstubAllEnvs();
  });

  it("503 when GitHub returns 4xx (e.g. bad token, missing label)", async () => {
    vi.stubEnv("GITHUB_ERROR_TOKEN", "fake-token");
    mockGitHub(401, { message: "Bad credentials" });
    const { POST } = await import("../route");
    const resp = await POST(
      makeRequest({ message: "bad token path" }, "10.0.0.3"),
    );
    expect(resp.status).toBe(503);
    const body = await resp.json();
    expect(body.ok).toBe(false);
    expect(body.forwarded).toBe(false);
    expect(body.error).toContain("GitHub forward failed");
    vi.unstubAllEnvs();
  });

  it("503 when GitHub returns 5xx (transient — caller can retry via validator)", async () => {
    vi.stubEnv("GITHUB_ERROR_TOKEN", "fake-token");
    mockGitHub(502, { message: "Bad Gateway" });
    const { POST } = await import("../route");
    const resp = await POST(
      makeRequest({ message: "github transient" }, "10.0.0.4"),
    );
    expect(resp.status).toBe(503);
    vi.unstubAllEnvs();
  });

  it("503 when GitHub network call rejects", async () => {
    vi.stubEnv("GITHUB_ERROR_TOKEN", "fake-token");
    mockGitHubReject(new Error("network down"));
    const { POST } = await import("../route");
    const resp = await POST(
      makeRequest({ message: "github unreachable" }, "10.0.0.5"),
    );
    expect(resp.status).toBe(503);
    const body = await resp.json();
    expect(body.error).toContain("GitHub forward failed");
    vi.unstubAllEnvs();
  });

  it("rejects missing message before any GitHub call", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch");
    const { POST } = await import("../route");
    const resp = await POST(
      makeRequest({ url: "/genius" }, "10.0.0.6"),
    );
    expect(resp.status).toBe(400);
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it("rejects oversized message before any GitHub call", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch");
    const { POST } = await import("../route");
    const resp = await POST(
      makeRequest({ message: "x".repeat(2001) }, "10.0.0.7"),
    );
    expect(resp.status).toBe(400);
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it("rejects invalid JSON before any GitHub call", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch");
    const req = new NextRequest("http://localhost:3000/api/report-error", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "x-forwarded-for": "10.0.0.8",
      },
      body: "not json",
    });
    const { POST } = await import("../route");
    const resp = await POST(req);
    expect(resp.status).toBe(400);
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it("rate limiter caps at 5 per IP regardless of GitHub status", async () => {
    vi.stubEnv("GITHUB_ERROR_TOKEN", "fake-token");
    // Each request mocks a new GitHub call. We don't care which status —
    // the rate limit is enforced before the GitHub call.
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response("{}", { status: 201 }),
    );
    const { POST } = await import("../route");
    const ip = "192.168.99.99";
    for (let i = 0; i < 5; i++) {
      const resp = await POST(makeRequest({ message: `r${i}` }, ip));
      expect([200, 503]).toContain(resp.status);
    }
    const resp = await POST(makeRequest({ message: "too many" }, ip));
    expect(resp.status).toBe(429);
    vi.unstubAllEnvs();
  });
});
