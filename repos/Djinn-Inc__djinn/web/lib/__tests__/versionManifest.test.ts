import { describe, it, expect } from "vitest";
import { resolveVersion, versionDrifts } from "../versionManifest";

const manifest = {
  generated_at: "2026-04-21T10:19:46.440Z",
  count: 2,
  shas: {
    "0230d27": "v1568",
    "ca16977": "v1563+",
  },
};

describe("resolveVersion", () => {
  it("returns null for missing manifest or sha", () => {
    expect(resolveVersion(undefined, "0230d27")).toBeNull();
    expect(resolveVersion(manifest, null)).toBeNull();
    expect(resolveVersion(manifest, undefined)).toBeNull();
  });

  it("matches by 7-char prefix", () => {
    expect(resolveVersion(manifest, "0230d27")).toBe("v1568");
    expect(resolveVersion(manifest, "0230d27750fdb75240691f0f8bd1bb067f6f0ac8")).toBe("v1568");
  });

  it("returns +N annotation for untagged commits", () => {
    expect(resolveVersion(manifest, "ca16977")).toBe("v1563+");
  });

  it("returns null when sha is unknown", () => {
    expect(resolveVersion(manifest, "deadbee")).toBeNull();
  });
});

describe("versionDrifts", () => {
  it("is false when reported and resolved agree on the tag number", () => {
    expect(versionDrifts("1568", "v1568")).toBe(false);
    expect(versionDrifts("1568", "v1568+")).toBe(false);
    expect(versionDrifts("1568+3", "v1568+")).toBe(false);
  });

  it("is true when numeric tags differ", () => {
    expect(versionDrifts("999", "v1568")).toBe(true);
    expect(versionDrifts("1563", "v1568")).toBe(true);
  });

  it("is false when either side is missing or unparseable", () => {
    expect(versionDrifts(null, "v1568")).toBe(false);
    expect(versionDrifts("1568", null)).toBe(false);
    expect(versionDrifts("not-a-version", "v1568")).toBe(false);
  });
});
