import { describe, it, expect } from "vitest";
import {
  DASHBOARD_REDIRECTS,
  DASHBOARD_SECTION_IDS,
  findDashboardRedirect,
} from "../dashboardRedirects";

describe("DASHBOARD_REDIRECTS", () => {
  it("covers every guessable returning-user URL flagged in iter-018", () => {
    const sources = DASHBOARD_REDIRECTS.map((r) => r.source);
    expect(sources).toEqual(
      expect.arrayContaining([
        "/idiot/history",
        "/idiot/portfolio",
        "/idiot/purchases",
        "/genius/history",
        "/genius/dashboard",
        "/genius/signals",
        "/dashboard",
        "/profile",
        "/settings",
      ]),
    );
  });

  it("never targets a legacy 404 destination (each destination is a known dashboard route)", () => {
    const knownRoots = new Set(["/idiot", "/genius"]);
    for (const r of DASHBOARD_REDIRECTS) {
      const root = r.destination.split("#")[0];
      expect(knownRoots.has(root)).toBe(true);
    }
  });

  it("uses 307 (permanent: false) so alias paths can be promoted to real routes later", () => {
    for (const r of DASHBOARD_REDIRECTS) {
      expect(r.permanent).toBe(false);
    }
  });

  it("hash anchors only reference declared dashboard section ids", () => {
    const allowed = new Set<string>([
      ...DASHBOARD_SECTION_IDS.idiot,
      ...DASHBOARD_SECTION_IDS.genius,
    ]);
    for (const r of DASHBOARD_REDIRECTS) {
      const [, hash] = r.destination.split("#");
      if (!hash) continue;
      expect(allowed.has(hash)).toBe(true);
    }
  });

  it("has no duplicate sources", () => {
    const sources = DASHBOARD_REDIRECTS.map((r) => r.source);
    expect(new Set(sources).size).toBe(sources.length);
  });
});

describe("next.config.js parity", () => {
  it("next.config.js redirect list matches DASHBOARD_REDIRECTS exactly", async () => {
    const fs = await import("node:fs/promises");
    const path = await import("node:path");
    const configPath = path.resolve(__dirname, "../../next.config.js");
    const src = await fs.readFile(configPath, "utf8");
    for (const r of DASHBOARD_REDIRECTS) {
      const needle = `{ source: "${r.source}", destination: "${r.destination}", permanent: ${r.permanent} }`;
      expect(src.includes(needle)).toBe(true);
    }
  });
});

describe("findDashboardRedirect", () => {
  it("finds a matching redirect by exact pathname", () => {
    const r = findDashboardRedirect("/idiot/history");
    expect(r?.destination).toBe("/idiot#purchase-history");
  });

  it("returns undefined for paths outside the alias list", () => {
    expect(findDashboardRedirect("/idiot")).toBeUndefined();
    expect(findDashboardRedirect("/leaderboard")).toBeUndefined();
    expect(findDashboardRedirect("/")).toBeUndefined();
  });

  it("does not match by prefix or trailing slash", () => {
    expect(findDashboardRedirect("/idiot/history/")).toBeUndefined();
    expect(findDashboardRedirect("/idiot/history?ref=email")).toBeUndefined();
  });
});
