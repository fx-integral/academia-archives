import { test, expect, type Page } from "@playwright/test";

/**
 * Parameterized Journeys: High-volume anonymous-visitor coverage.
 *
 * The hand-written journeys (visitor / idiot / genius / ...) are a dozen or
 * so curated flows. This spec multiplies coverage by iterating over cartesian
 * products of (pages × sports × viewports × ...). It catches the "every page
 * that happens to share the same broken hook" class of bug — e.g. v1380's
 * AbortError, which rendered on multiple pages but only one journey asserted
 * on its DOM.
 *
 * Scale via `E2E_SCALE` env var (default 1). `E2E_SCALE=10` ≈ ~300 tests,
 * `E2E_SCALE=100` ≈ ~3000 tests. Each test is cheap (one navigate + body
 * text scan) so wall-clock stays tractable even at 1000s.
 *
 * Every test runs the same bug detector: if any of FORBIDDEN_PHRASES leaks
 * into the DOM, the test fails. The phrase list is the repository of known
 * user-visible bugs — add to it whenever you fix one, so that bug can never
 * silently regress.
 */

const BASE_URL = process.env.UX_BASE_URL ?? "https://www.djinn.gg";
const SCALE = Math.max(1, Number(process.env.E2E_SCALE ?? "1"));

// Forbidden phrases: any of these appearing in the DOM is a regression. Every
// fixed bug should add its signature here so future copies of it are caught.
const FORBIDDEN_PHRASES: ReadonlyArray<RegExp> = [
  /The user aborted a request/i, // v1386 AbortError fix
  /AbortError/i,
  /Failed to load signals/i, // iter-41
  /\bundefined\b(?!\s*\()/i, // "undefined" in text, not a function call
  /\bNaN\b/i,
  /\[object Object\]/i,
  /Cannot read propert/i, // JS error leaking to DOM
  /ChunkLoadError/i,
  /ReferenceError/i,
  // "bet size" and friends: Djinn is an information marketplace, not a
  // sportsbook. The whitepaper explicitly says "Djinn does not accept bets"
  // and defines notional as a reference amount that "does not need to match
  // any actual wager". Any user-surface copy that calls this a bet positions
  // us as a betting platform and contradicts our legal framing.
  /\bbet\s*size\b/i, // v1402 legal positioning — use "notional" or "capacity"
  /\bbet-size\b/i,   // same, hyphenated
  /\bBps\b/, // v1391 — "Bps" should always be rendered via formatBps() as a %
  /\bSLA\b/, // v1398 — "SLA" replaced by "Backing" on user surfaces (legal/docs exempt)
];

// Exception phrases: substrings that are allowed even if they'd match above.
// E.g. the docs page has prose that legitimately says "undefined behavior".
//
// urlPath is anchored to the pathname (no query string, no substring hazard
// like `/docsearch` falsely matching `/\/docs/`). Each exception is
// deliberately narrow: the allowlist is keyed on the *page's jargon
// reputation* (docs = heavy protocol prose, research = math papers), not
// on a prefix that could silently inherit to unrelated new routes.
const ALLOWED_EXCEPTIONS: ReadonlyArray<{ urlPath: RegExp; phrase: RegExp }> = [
  // Docs articles can discuss undefined/NaN in code examples.
  { urlPath: /^\/docs(\/|$)/, phrase: /\bundefined\b/i },
  { urlPath: /^\/docs(\/|$)/, phrase: /\bNaN\b/i },
  // Docs + research pages legitimately use protocol jargon.
  { urlPath: /^\/docs(\/|$)/, phrase: /\bBps\b/ },
  { urlPath: /^\/research(\/|$)/, phrase: /\bBps\b/ },
  // SLA is a defined legal term on /terms and /risk + a documented contract
  // parameter on /docs — leave it there, ban it from product surfaces.
  { urlPath: /^\/terms(\/|$)/, phrase: /\bSLA\b/ },
  { urlPath: /^\/risk(\/|$)/, phrase: /\bSLA\b/ },
  { urlPath: /^\/docs(\/|$)/, phrase: /\bSLA\b/ },
];

const PAGES: ReadonlyArray<{ path: string; label: string }> = [
  { path: "/", label: "home" },
  { path: "/network", label: "network" },
  { path: "/idiot", label: "idiot-dashboard" },
  { path: "/idiot/browse", label: "idiot-browse" },
  { path: "/genius", label: "genius-landing" },
  { path: "/genius/signal/new", label: "genius-new-signal" },
  { path: "/leaderboard", label: "leaderboard" },
  { path: "/attest", label: "attest" },
  { path: "/docs", label: "docs" },
  { path: "/education", label: "education" },
  { path: "/research", label: "research" },
  { path: "/about", label: "about" },
  { path: "/press", label: "press" },
  { path: "/terms", label: "terms" },
  { path: "/privacy", label: "privacy" },
  { path: "/risk", label: "risk" },
  { path: "/acceptable-use", label: "acceptable-use" },
  { path: "/dmca", label: "dmca" },
  { path: "/support", label: "support" },
];

const SPORTS: ReadonlyArray<string> = [
  "basketball_nba",
  "icehockey_nhl",
  "baseball_mlb",
  "americanfootball_nfl",
  "soccer_epl",
  "soccer_usa_mls",
];

// Viewports: catch mobile-only regressions without shipping a separate
// mobile suite.
const VIEWPORTS: ReadonlyArray<{ name: string; width: number; height: number }> = [
  { name: "desktop", width: 1440, height: 900 },
  { name: "mobile", width: 390, height: 844 },
];

async function assertNoForbiddenPhrases(page: Page, label: string) {
  const body = await page.locator("body").innerText({ timeout: 5_000 });
  const fullUrl = page.url();
  // Match against pathname, not the full URL. Query strings like
  // `?from=/docs` must never widen the allowlist for unrelated pages.
  const pathname = (() => {
    try { return new URL(fullUrl).pathname; } catch { return fullUrl; }
  })();
  for (const phrase of FORBIDDEN_PHRASES) {
    const allowed = ALLOWED_EXCEPTIONS.some(
      (ex) => ex.urlPath.test(pathname) && ex.phrase.source === phrase.source,
    );
    if (allowed) continue;
    expect(
      body,
      `[${label}] "${phrase.source}" leaked into DOM at ${fullUrl}`,
    ).not.toMatch(phrase);
  }
}

test.describe("Parameterized: forbidden-phrase sweep across all pages × viewports", () => {
  for (let iter = 1; iter <= SCALE; iter++) {
    for (const vp of VIEWPORTS) {
      for (const pg of PAGES) {
        test(`iter-${iter} ${vp.name} ${pg.label}`, async ({ page }) => {
          await page.setViewportSize({ width: vp.width, height: vp.height });
          await page.goto(`${BASE_URL}${pg.path}`, {
            waitUntil: "domcontentloaded",
            timeout: 30_000,
          });
          // Give client-side data fetches a moment to resolve — the whole
          // point is to catch hook-level regressions that only appear
          // after the post-SSR hydration.
          await page.waitForLoadState("networkidle", { timeout: 15_000 }).catch(() => {});
          await assertNoForbiddenPhrases(page, `${vp.name} ${pg.label}`);
        });
      }
    }
  }
});

test.describe("Parameterized: /idiot/browse × sport filter", () => {
  // Per-sport filtered browse pages. Catches filter-specific errors like a
  // sport whose odds-API name differs from the internal key.
  for (let iter = 1; iter <= SCALE; iter++) {
    for (const sport of SPORTS) {
      test(`iter-${iter} browse sport=${sport}`, async ({ page }) => {
        await page.goto(`${BASE_URL}/idiot/browse?sport=${sport}`, {
          waitUntil: "domcontentloaded",
          timeout: 30_000,
        });
        await page.waitForLoadState("networkidle", { timeout: 15_000 }).catch(() => {});
        await assertNoForbiddenPhrases(page, `browse-${sport}`);
      });
    }
  }
});

test.describe("Parameterized: /api read endpoints", () => {
  // Headless API sweep — contract shape only, not payload content. Catches
  // 5xx regressions across the public read surface.
  const API_PATHS: ReadonlyArray<string> = [
    "/api/health",
    "/api/network/status",
    "/api/network/config",
    "/api/validators/discover",
    "/api/miners/discover",
    "/api/idiot/browse",
    "/api/sports",
  ];
  for (let iter = 1; iter <= SCALE; iter++) {
    for (const path of API_PATHS) {
      test(`iter-${iter} ${path}`, async ({ request }) => {
        const res = await request.get(`${BASE_URL}${path}`);
        // 200/304 ok, 403 is the Vercel challenge (known, C-2), 404 for
        // static-export paths is fine. Fail only on 5xx.
        expect(res.status(), `${path} returned ${res.status()}`).toBeLessThan(500);
      });
    }
  }
});
