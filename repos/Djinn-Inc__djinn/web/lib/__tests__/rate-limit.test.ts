import { describe, it, expect, vi, beforeEach } from "vitest";

// Mock NextRequest/NextResponse before importing
vi.mock("next/server", () => ({
  NextRequest: class {},
  NextResponse: {
    json: (body: unknown, init?: { status?: number }) => ({
      body,
      status: init?.status ?? 200,
    }),
  },
}));

import { isRateLimited, rateLimitResponse } from "../rate-limit";

describe("rate-limit", () => {
  beforeEach(() => {
    // Rate limiter uses module-level state, so we test with unique route names
  });

  it("allows requests under the limit", () => {
    const route = `test-allow-${Date.now()}`;
    for (let i = 0; i < 5; i++) {
      expect(isRateLimited(route, "1.2.3.4", 10)).toBe(false);
    }
  });

  it("blocks requests over the limit", () => {
    const route = `test-block-${Date.now()}`;
    for (let i = 0; i < 10; i++) {
      isRateLimited(route, "1.2.3.4", 10);
    }
    expect(isRateLimited(route, "1.2.3.4", 10)).toBe(true);
  });

  it("tracks IPs independently", () => {
    const route = `test-independent-${Date.now()}`;
    for (let i = 0; i < 5; i++) {
      isRateLimited(route, "1.1.1.1", 5);
    }
    // IP 1.1.1.1 is now rate-limited
    expect(isRateLimited(route, "1.1.1.1", 5)).toBe(true);
    // IP 2.2.2.2 should still be allowed
    expect(isRateLimited(route, "2.2.2.2", 5)).toBe(false);
  });

  it("tracks routes independently", () => {
    const route1 = `test-route1-${Date.now()}`;
    const route2 = `test-route2-${Date.now()}`;
    for (let i = 0; i < 5; i++) {
      isRateLimited(route1, "1.1.1.1", 5);
    }
    expect(isRateLimited(route1, "1.1.1.1", 5)).toBe(true);
    expect(isRateLimited(route2, "1.1.1.1", 5)).toBe(false);
  });

  it("rateLimitResponse returns 429", () => {
    const res = rateLimitResponse();
    expect(res.status).toBe(429);
  });
});
