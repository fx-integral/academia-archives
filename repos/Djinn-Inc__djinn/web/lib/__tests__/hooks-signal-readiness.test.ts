import { describe, it, expect, vi, beforeEach } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { createElement } from "react";

const mockDiscover = vi.fn();
vi.mock("../api", () => ({
  discoverValidatorClients: () => mockDiscover(),
}));

import { useSignalReadiness } from "../hooks/useSignalReadiness";

function makeWrapper() {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  const Wrapper = ({ children }: { children: ReactNode }) =>
    createElement(QueryClientProvider, { client: qc }, children);
  Wrapper.displayName = "TestQueryClientWrapper";
  return Wrapper;
}

function mockFetchResponses(
  byUrl: Record<string, { ok: boolean; body?: unknown }>,
) {
  global.fetch = vi.fn(async (url: RequestInfo | URL) => {
    const key = String(url);
    const match =
      byUrl[key] ??
      Object.entries(byUrl).find(([prefix]) => key.startsWith(prefix))?.[1];
    if (!match) {
      throw new Error(`unexpected fetch: ${key}`);
    }
    return {
      ok: match.ok,
      status: match.ok ? 200 : 500,
      json: async () => match.body ?? {},
    } as Response;
  }) as typeof fetch;
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe("useSignalReadiness", () => {
  it("returns 'ready' when validator confirms has_shares=true", async () => {
    mockDiscover.mockResolvedValue([{ baseUrl: "http://v0", uid: 0 }]);
    mockFetchResponses({
      "http://v0/v1/signal/sigA/status": { ok: true, body: { has_shares: true } },
    });

    const { result } = renderHook(() => useSignalReadiness(["sigA"]), {
      wrapper: makeWrapper(),
    });

    await waitFor(() => {
      expect(result.current.readiness.get("sigA")).toBe("ready");
    });
  });

  it("returns 'preparing' when validator reports has_shares=false", async () => {
    mockDiscover.mockResolvedValue([{ baseUrl: "http://v0", uid: 0 }]);
    mockFetchResponses({
      "http://v0/v1/signal/sigB/status": { ok: true, body: { has_shares: false } },
    });

    const { result } = renderHook(() => useSignalReadiness(["sigB"]), {
      wrapper: makeWrapper(),
    });

    await waitFor(() => {
      expect(result.current.readiness.get("sigB")).toBe("preparing");
    });
  });

  it("returns 'unknown' on network error so the listing isn't blocked", async () => {
    mockDiscover.mockResolvedValue([{ baseUrl: "http://v0", uid: 0 }]);
    global.fetch = vi.fn(async () => {
      throw new Error("network down");
    }) as typeof fetch;

    const { result } = renderHook(() => useSignalReadiness(["sigC"]), {
      wrapper: makeWrapper(),
    });

    await waitFor(() => {
      expect(result.current.readiness.get("sigC")).toBe("unknown");
    });
  });

  it("returns empty map for empty input (and skips the query)", () => {
    const { result } = renderHook(() => useSignalReadiness([]), {
      wrapper: makeWrapper(),
    });
    expect(result.current.readiness.size).toBe(0);
    expect(result.current.loading).toBe(false);
    expect(mockDiscover).not.toHaveBeenCalled();
  });

  it("round-robins signals across multiple validators", async () => {
    mockDiscover.mockResolvedValue([
      { baseUrl: "http://v0", uid: 0 },
      { baseUrl: "http://v1", uid: 1 },
    ]);
    const calls: string[] = [];
    global.fetch = vi.fn(async (url: RequestInfo | URL) => {
      calls.push(String(url));
      const sid = String(url).match(/\/v1\/signal\/([^/]+)\/status/)?.[1];
      return {
        ok: true,
        status: 200,
        json: async () => ({ has_shares: sid === "s1" }),
      } as Response;
    }) as typeof fetch;

    const { result } = renderHook(
      () => useSignalReadiness(["s0", "s1", "s2"]),
      { wrapper: makeWrapper() },
    );

    await waitFor(() => {
      expect(result.current.readiness.size).toBe(3);
    });
    // Each validator was hit at least once (round-robin).
    expect(calls.some((c) => c.startsWith("http://v0"))).toBe(true);
    expect(calls.some((c) => c.startsWith("http://v1"))).toBe(true);
    expect(result.current.readiness.get("s1")).toBe("ready");
    expect(result.current.readiness.get("s0")).toBe("preparing");
  });

  it("falls back to 'unknown' when no validators are discoverable", async () => {
    mockDiscover.mockResolvedValue([]);

    const { result } = renderHook(() => useSignalReadiness(["sigZ"]), {
      wrapper: makeWrapper(),
    });

    await waitFor(() => {
      expect(result.current.readiness.get("sigZ")).toBe("unknown");
    });
  });
});
