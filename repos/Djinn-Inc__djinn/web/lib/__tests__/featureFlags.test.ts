import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const ENV_KEYS = [
  "NEXT_PUBLIC_DJINN_FF_CIRCUIT_BREAKER",
  "NEXT_PUBLIC_DJINN_FF_CANONICAL_ODDS",
  "NEXT_PUBLIC_DJINN_FF_APPEAL_MECHANISM",
  "NEXT_PUBLIC_DJINN_FF_PURCHASE_V2",
  "NEXT_PUBLIC_DJINN_FF_NEW_MINER_ZERO_WEIGHT",
  "NEXT_PUBLIC_DJINN_FF_QUORUM_STRICT",
  "NEXT_PUBLIC_DJINN_FF_QUORUM_STRICT_CHECK_ODDS",
  "NEXT_PUBLIC_DJINN_FF_QUORUM_STRICT_PURCHASE",
] as const;

function clearEnv() {
  for (const key of ENV_KEYS) {
    delete process.env[key];
  }
}

function clearStorage() {
  if (typeof window !== "undefined" && window.localStorage) {
    window.localStorage.clear();
  }
}

async function freshImport() {
  vi.resetModules();
  return await import("../featureFlags");
}

describe("featureFlags", () => {
  beforeEach(() => {
    clearEnv();
    clearStorage();
  });

  afterEach(() => {
    clearEnv();
    clearStorage();
  });

  it("defaults all flags to false", async () => {
    const { getAllFlags } = await freshImport();
    const flags = getAllFlags();
    expect(flags.circuitBreaker).toBe(false);
    expect(flags.canonicalOdds).toBe(false);
    expect(flags.appealMechanism).toBe(false);
    expect(flags.purchaseV2).toBe(false);
    expect(flags.newMinerZeroWeight).toBe(false);
    expect(flags.quorumStrict).toBe(false);
  });

  it("reads truthy env values as true", async () => {
    process.env.NEXT_PUBLIC_DJINN_FF_CIRCUIT_BREAKER = "true";
    const { isFlagEnabled } = await freshImport();
    expect(isFlagEnabled("circuitBreaker")).toBe(true);
  });

  it("reads various truthy strings", async () => {
    for (const value of ["1", "true", "yes", "on", "TRUE", "Yes", "ON"]) {
      process.env.NEXT_PUBLIC_DJINN_FF_PURCHASE_V2 = value;
      const { isFlagEnabled } = await freshImport();
      expect(isFlagEnabled("purchaseV2")).toBe(true);
    }
  });

  it("reads falsy and unknown strings as false", async () => {
    for (const value of ["0", "false", "no", "off", "", "garbage"]) {
      process.env.NEXT_PUBLIC_DJINN_FF_PURCHASE_V2 = value;
      const { isFlagEnabled } = await freshImport();
      expect(isFlagEnabled("purchaseV2")).toBe(false);
    }
  });

  it("localStorage override beats env", async () => {
    process.env.NEXT_PUBLIC_DJINN_FF_CANONICAL_ODDS = "false";
    window.localStorage.setItem("djinn_ff_canonical_odds", "true");
    const { isFlagEnabled } = await freshImport();
    expect(isFlagEnabled("canonicalOdds")).toBe(true);
  });

  it("localStorage override can disable an env-enabled flag", async () => {
    process.env.NEXT_PUBLIC_DJINN_FF_CANONICAL_ODDS = "true";
    window.localStorage.setItem("djinn_ff_canonical_odds", "false");
    const { isFlagEnabled } = await freshImport();
    expect(isFlagEnabled("canonicalOdds")).toBe(false);
  });

  it("setFlagOverride writes to localStorage", async () => {
    const { setFlagOverride, isFlagEnabled } = await freshImport();
    setFlagOverride("appealMechanism", true);
    expect(isFlagEnabled("appealMechanism")).toBe(true);
    setFlagOverride("appealMechanism", false);
    expect(isFlagEnabled("appealMechanism")).toBe(false);
  });

  it("setFlagOverride with null clears the override", async () => {
    process.env.NEXT_PUBLIC_DJINN_FF_QUORUM_STRICT = "true";
    const { setFlagOverride, isFlagEnabled } = await freshImport();
    setFlagOverride("quorumStrict", false);
    expect(isFlagEnabled("quorumStrict")).toBe(false);
    setFlagOverride("quorumStrict", null);
    expect(isFlagEnabled("quorumStrict")).toBe(true);
  });

  it("getEnabledFlags lists only on flags", async () => {
    process.env.NEXT_PUBLIC_DJINN_FF_CIRCUIT_BREAKER = "true";
    process.env.NEXT_PUBLIC_DJINN_FF_PURCHASE_V2 = "true";
    const { getEnabledFlags } = await freshImport();
    const enabled = getEnabledFlags().sort();
    expect(enabled).toEqual(["circuitBreaker", "purchaseV2"].sort());
  });
});

describe("isQuorumStrictFor", () => {
  beforeEach(() => {
    clearEnv();
    clearStorage();
  });

  it("umbrella quorumStrict enables all call types", async () => {
    process.env.NEXT_PUBLIC_DJINN_FF_QUORUM_STRICT = "true";
    const { isQuorumStrictFor } = await freshImport();
    expect(isQuorumStrictFor("checkOdds")).toBe(true);
    expect(isQuorumStrictFor("purchase")).toBe(true);
  });

  it("per-call quorumStrictCheckOdds only enables checkOdds", async () => {
    process.env.NEXT_PUBLIC_DJINN_FF_QUORUM_STRICT_CHECK_ODDS = "true";
    const { isQuorumStrictFor } = await freshImport();
    expect(isQuorumStrictFor("checkOdds")).toBe(true);
    expect(isQuorumStrictFor("purchase")).toBe(false);
  });

  it("per-call quorumStrictPurchase only enables purchase", async () => {
    process.env.NEXT_PUBLIC_DJINN_FF_QUORUM_STRICT_PURCHASE = "true";
    const { isQuorumStrictFor } = await freshImport();
    expect(isQuorumStrictFor("checkOdds")).toBe(false);
    expect(isQuorumStrictFor("purchase")).toBe(true);
  });

  it("everything off returns false for all call types", async () => {
    const { isQuorumStrictFor } = await freshImport();
    expect(isQuorumStrictFor("checkOdds")).toBe(false);
    expect(isQuorumStrictFor("purchase")).toBe(false);
  });

  it("per-call flags compose with the umbrella flag", async () => {
    process.env.NEXT_PUBLIC_DJINN_FF_QUORUM_STRICT = "true";
    process.env.NEXT_PUBLIC_DJINN_FF_QUORUM_STRICT_PURCHASE = "false";
    const { isQuorumStrictFor } = await freshImport();
    // Umbrella overrides — both stay true even though purchase is set false
    expect(isQuorumStrictFor("checkOdds")).toBe(true);
    expect(isQuorumStrictFor("purchase")).toBe(true);
  });
});
