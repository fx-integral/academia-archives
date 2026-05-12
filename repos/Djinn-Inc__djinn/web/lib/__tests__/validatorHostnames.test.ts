import { describe, expect, it } from "vitest";

import {
  VALIDATOR_HOSTNAMES,
  getValidatorBaseUrl,
  getValidatorHostname,
  hasDirectHttps,
  patternBaseUrl,
  patternHostname,
  resolveValidatorBaseUrl,
} from "../validatorHostnames";

describe("validator hostname registry", () => {
  it("registry is empty by default (wildcard router covers everything)", () => {
    expect(VALIDATOR_HOSTNAMES).toEqual([]);
  });

  it("returns undefined for any UID since registry is empty", () => {
    expect(getValidatorHostname(0)).toBeUndefined();
    expect(getValidatorHostname(9999)).toBeUndefined();
    expect(getValidatorBaseUrl(0)).toBeUndefined();
  });

  it("hasDirectHttps reports false for empty registry", () => {
    expect(hasDirectHttps(0)).toBe(false);
  });

  it("each registry entry has required fields when populated", () => {
    for (const entry of VALIDATOR_HOSTNAMES) {
      expect(entry.uid).toBeGreaterThanOrEqual(0);
      expect(entry.hostname).toMatch(/^[a-z0-9.-]+\.[a-z]+$/);
      expect(typeof entry.operatorControlled).toBe("boolean");
    }
  });

  it("hostnames are unique across entries", () => {
    const seen = new Set<string>();
    for (const entry of VALIDATOR_HOSTNAMES) {
      expect(seen.has(entry.hostname)).toBe(false);
      seen.add(entry.hostname);
    }
  });

  it("UIDs are unique across entries", () => {
    const seen = new Set<number>();
    for (const entry of VALIDATOR_HOSTNAMES) {
      expect(seen.has(entry.uid)).toBe(false);
      seen.add(entry.uid);
    }
  });
});

describe("pattern-based hostname resolution", () => {
  it("patternHostname returns v<uid>.djinn.gg", () => {
    expect(patternHostname(0)).toBe("v0.djinn.gg");
    expect(patternHostname(213)).toBe("v213.djinn.gg");
    expect(patternHostname(86)).toBe("v86.djinn.gg");
  });

  it("patternBaseUrl returns https URL", () => {
    expect(patternBaseUrl(0)).toBe("https://v0.djinn.gg");
    expect(patternBaseUrl(213)).toBe("https://v213.djinn.gg");
  });

  it("resolveValidatorBaseUrl uses advertised hostname when present", () => {
    expect(resolveValidatorBaseUrl(213, "validator.tao.com")).toBe(
      "https://validator.tao.com",
    );
  });

  it("resolveValidatorBaseUrl falls back to pattern when no override", () => {
    expect(resolveValidatorBaseUrl(213)).toBe("https://v213.djinn.gg");
    expect(resolveValidatorBaseUrl(0)).toBe("https://v0.djinn.gg");
  });

  it("resolveValidatorBaseUrl handles empty advertised hostname", () => {
    expect(resolveValidatorBaseUrl(213, "")).toBe("https://v213.djinn.gg");
  });
});
