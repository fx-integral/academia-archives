import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  DEFAULT_BOOTSTRAP,
  discoverValidators,
  fastestNValidators,
  fastestValidator,
  type DiscoveryResult,
} from "../validatorDiscovery";

const fetchMock = vi.fn();
vi.stubGlobal("fetch", fetchMock);

beforeEach(() => {
  fetchMock.mockReset();
});

afterEach(() => {
  vi.useRealTimers();
});

function jsonResponse(body: unknown, ok = true) {
  return {
    ok,
    json: async () => body,
  } as Response;
}

describe("discoverValidators", () => {
  it("returns empty result when bootstrap is unreachable", async () => {
    fetchMock.mockRejectedValueOnce(new Error("network down"));
    const result = await discoverValidators({ bootstrap: "https://unreachable" });
    expect(result.validators).toHaveLength(0);
    expect(result.errorCount).toBe(1);
  });

  it("returns empty result when bootstrap returns non-200", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse({}, false));
    const result = await discoverValidators({ bootstrap: "https://degraded" });
    expect(result.validators).toHaveLength(0);
    expect(result.errorCount).toBe(1);
  });

  it("filters candidates with empty IP or zero port", async () => {
    fetchMock.mockResolvedValueOnce(
      jsonResponse({
        validators: [
          { uid: 0, ip: "10.0.0.1", port: 8421, hotkey: "5Aa" },
          { uid: 1, ip: "0.0.0.0", port: 8421, hotkey: "5Bb" },
          { uid: 2, ip: "10.0.0.3", port: 0, hotkey: "5Cc" },
          { uid: 3, ip: "", port: 8421, hotkey: "5Dd" },
        ],
        served_by_uid: 0,
        validator_count: 4,
        served_at_ms: 1000,
      }),
    );
    // Probe for uid 0 succeeds, all others should be filtered out
    fetchMock.mockResolvedValueOnce(
      jsonResponse({
        status: "ok",
        version: "1095",
        uid: 0,
        shares_held: 100,
        chain_connected: true,
        bt_connected: true,
        attest_capable: true,
        public_hostname: "",
      }),
    );
    const result = await discoverValidators({ bootstrap: "https://v0.djinn.gg" });
    expect(result.validators).toHaveLength(1);
    expect(result.validators[0].uid).toBe(0);
  });

  it("uses the operator-advertised hostname when present", async () => {
    fetchMock.mockResolvedValueOnce(
      jsonResponse({
        validators: [{ uid: 213, ip: "1.2.3.4", port: 8421, hotkey: "5T" }],
        served_by_uid: 0,
        validator_count: 1,
        served_at_ms: 1000,
      }),
    );
    fetchMock.mockResolvedValueOnce(
      jsonResponse({
        status: "ok",
        version: "999",
        uid: 213,
        shares_held: 1100,
        chain_connected: true,
        bt_connected: true,
        attest_capable: true,
        public_hostname: "validator.tao.com",
      }),
    );
    const result = await discoverValidators({ bootstrap: "https://v0.djinn.gg" });
    expect(result.validators[0].baseUrl).toBe("https://validator.tao.com");
    expect(result.validators[0].publicHostname).toBe("validator.tao.com");
  });

  it("falls back to wildcard pattern when no advertised hostname", async () => {
    fetchMock.mockResolvedValueOnce(
      jsonResponse({
        validators: [{ uid: 86, ip: "1.2.3.4", port: 8421, hotkey: "5R" }],
        served_by_uid: 0,
        validator_count: 1,
        served_at_ms: 1000,
      }),
    );
    fetchMock.mockResolvedValueOnce(
      jsonResponse({
        status: "ok",
        version: "1095",
        uid: 86,
        shares_held: 500,
        chain_connected: true,
        bt_connected: true,
        attest_capable: true,
        public_hostname: "",
      }),
    );
    const result = await discoverValidators({ bootstrap: "https://v0.djinn.gg" });
    expect(result.validators[0].baseUrl).toBe("https://v86.djinn.gg");
  });

  it("skips validators whose health probe fails", async () => {
    fetchMock.mockResolvedValueOnce(
      jsonResponse({
        validators: [
          { uid: 0, ip: "1.2.3.4", port: 8421, hotkey: "5Aa" },
          { uid: 1, ip: "1.2.3.5", port: 8421, hotkey: "5Bb" },
        ],
        served_by_uid: 0,
        validator_count: 2,
        served_at_ms: 1000,
      }),
    );
    fetchMock.mockResolvedValueOnce(
      jsonResponse({
        status: "ok",
        version: "1095",
        uid: 0,
        shares_held: 100,
        chain_connected: true,
        bt_connected: true,
        attest_capable: true,
      }),
    );
    fetchMock.mockRejectedValueOnce(new Error("timeout"));
    const result = await discoverValidators();
    expect(result.validators).toHaveLength(1);
    expect(result.validators[0].uid).toBe(0);
    expect(result.errorCount).toBe(1);
  });

  it("skips validators reporting non-ok status", async () => {
    fetchMock.mockResolvedValueOnce(
      jsonResponse({
        validators: [{ uid: 5, ip: "1.2.3.4", port: 8421, hotkey: "5Aa" }],
        served_by_uid: 0,
        validator_count: 1,
        served_at_ms: 1000,
      }),
    );
    fetchMock.mockResolvedValueOnce(
      jsonResponse({
        status: "degraded",
        version: "1023",
        uid: 5,
        shares_held: 0,
        chain_connected: false,
        bt_connected: false,
        attest_capable: false,
      }),
    );
    const result = await discoverValidators();
    expect(result.validators).toHaveLength(0);
  });
});

describe("fastestValidator / fastestNValidators", () => {
  function makeResult(latencies: number[]): DiscoveryResult {
    return {
      bootstrapUrl: "https://v0.djinn.gg",
      servedAtMs: 1000,
      errorCount: 0,
      validators: latencies.map((ms, i) => ({
        uid: i,
        baseUrl: `https://v${i}.djinn.gg`,
        hotkey: `5key${i}`,
        ip: `10.0.0.${i}`,
        port: 8421,
        publicHostname: "",
        sharesHeld: 100,
        version: "1095",
        chainConnected: true,
        btConnected: true,
        attestCapable: true,
        healthLatencyMs: ms,
      })),
    };
  }

  it("fastestValidator picks the lowest latency", () => {
    const result = makeResult([300, 100, 200]);
    expect(fastestValidator(result)?.uid).toBe(1);
  });

  it("fastestValidator returns undefined when no validators", () => {
    const result = makeResult([]);
    expect(fastestValidator(result)).toBeUndefined();
  });

  it("fastestNValidators returns N sorted by latency", () => {
    const result = makeResult([300, 100, 200, 50, 400]);
    const top3 = fastestNValidators(result, 3);
    expect(top3.map((v) => v.healthLatencyMs)).toEqual([50, 100, 200]);
  });

  it("fastestNValidators handles N > validators count", () => {
    const result = makeResult([100, 200]);
    expect(fastestNValidators(result, 5)).toHaveLength(2);
  });
});

describe("DEFAULT_BOOTSTRAP", () => {
  it("points to v0.djinn.gg over HTTPS", () => {
    expect(DEFAULT_BOOTSTRAP).toBe("https://v0.djinn.gg");
  });
});
