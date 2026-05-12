import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { NextRequest } from "next/server";

// Mock admin-auth so we can exercise the authorized + unauthorized paths
const mockVerifyAdminRequest = vi.fn();
vi.mock("@/lib/admin-auth", () => ({
  verifyAdminRequest: (...args: unknown[]) => mockVerifyAdminRequest(...args),
}));

const mockGetErrors = vi.fn();
vi.mock("@/lib/error-store", () => ({
  getErrors: (...args: unknown[]) => mockGetErrors(...args),
}));

import { GET } from "../route";

function makeRequest(query = ""): NextRequest {
  return new NextRequest(
    `http://localhost:3000/api/admin/errors${query ? `?${query}` : ""}`,
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

describe("GET /api/admin/errors", () => {
  const ORIGINAL_ENV = { ...process.env };

  beforeEach(() => {
    vi.clearAllMocks();
    mockVerifyAdminRequest.mockResolvedValue(true);
    mockGetErrors.mockReturnValue({ errors: [], total: 0 });
    delete process.env.VALIDATOR_ADMIN_API_KEY;
  });

  afterEach(() => {
    vi.restoreAllMocks();
    process.env = { ...ORIGINAL_ENV };
  });

  it("rejects unauthorized requests with 401", async () => {
    mockVerifyAdminRequest.mockResolvedValue(false);
    const fetchSpy = vi.spyOn(globalThis, "fetch");
    const resp = await GET(makeRequest());
    expect(resp.status).toBe(401);
    expect(fetchSpy).not.toHaveBeenCalled();
    expect(mockGetErrors).not.toHaveBeenCalled();
  });

  it("without validator key → returns Vercel-local store", async () => {
    mockGetErrors.mockReturnValue({
      errors: [{ message: "local one", timestamp: "t" }],
      total: 1,
    });
    const fetchSpy = vi.spyOn(globalThis, "fetch");
    const resp = await GET(makeRequest());
    expect(resp.status).toBe(200);
    expect(fetchSpy).not.toHaveBeenCalled();
    expect(resp.headers.get("x-djinn-source")).toBe("vercel-local");
    const body = await resp.json();
    expect(body.total).toBe(1);
  });

  it("with validator key + validator up → forwards to validator", async () => {
    process.env.VALIDATOR_ADMIN_API_KEY = "test-key";
    mockFetchOnce(200, {
      errors: [{ message: "from validator", timestamp: "t" }],
      total: 42,
    });
    const resp = await GET(makeRequest("limit=25"));
    expect(resp.status).toBe(200);
    expect(resp.headers.get("x-djinn-source")).toBe("validator");
    const body = await resp.json();
    expect(body.total).toBe(42);
    expect(body.errors[0].message).toBe("from validator");
    expect(mockGetErrors).not.toHaveBeenCalled();
  });

  it("validator unreachable → falls back to local store", async () => {
    process.env.VALIDATOR_ADMIN_API_KEY = "test-key";
    mockFetchReject();
    mockGetErrors.mockReturnValue({
      errors: [{ message: "fallback", timestamp: "t" }],
      total: 3,
    });
    const resp = await GET(makeRequest());
    expect(resp.status).toBe(200);
    expect(resp.headers.get("x-djinn-source")).toBe("vercel-local");
    const body = await resp.json();
    expect(body.total).toBe(3);
  });

  it("validator 5xx → falls back to local store", async () => {
    process.env.VALIDATOR_ADMIN_API_KEY = "test-key";
    mockFetchOnce(503, { error: "down" });
    mockGetErrors.mockReturnValue({ errors: [], total: 0 });
    const resp = await GET(makeRequest());
    expect(resp.status).toBe(200);
    expect(resp.headers.get("x-djinn-source")).toBe("vercel-local");
    expect(mockGetErrors).toHaveBeenCalledTimes(1);
  });

  it("validator 401 → falls back to local store", async () => {
    // If Vercel key is wrong or stale, don't surface a 401 to the admin —
    // just degrade to the local store so the admin page stays functional.
    process.env.VALIDATOR_ADMIN_API_KEY = "bad-key";
    mockFetchOnce(401, { error: "Unauthorized" });
    mockGetErrors.mockReturnValue({ errors: [], total: 0 });
    const resp = await GET(makeRequest());
    expect(resp.status).toBe(200);
    expect(resp.headers.get("x-djinn-source")).toBe("vercel-local");
  });

  it("clamps limit at 200", async () => {
    process.env.VALIDATOR_ADMIN_API_KEY = "test-key";
    const fetchSpy = mockFetchOnce(200, { errors: [], total: 0 });
    await GET(makeRequest("limit=9999"));
    expect(fetchSpy).toHaveBeenCalledTimes(1);
    const calledUrl = fetchSpy.mock.calls[0]![0] as string;
    expect(calledUrl).toContain("limit=200");
  });

  it("defaults limit to 50", async () => {
    process.env.VALIDATOR_ADMIN_API_KEY = "test-key";
    const fetchSpy = mockFetchOnce(200, { errors: [], total: 0 });
    await GET(makeRequest());
    const calledUrl = fetchSpy.mock.calls[0]![0] as string;
    expect(calledUrl).toContain("limit=50");
  });

  it("forwards bearer token to validator", async () => {
    process.env.VALIDATOR_ADMIN_API_KEY = "secret-sauce";
    const fetchSpy = mockFetchOnce(200, { errors: [], total: 0 });
    await GET(makeRequest());
    const init = fetchSpy.mock.calls[0]![1] as RequestInit;
    const headers = init.headers as Record<string, string>;
    expect(headers.authorization).toBe("Bearer secret-sauce");
  });
});
