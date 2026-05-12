import { test, expect } from "@playwright/test";

/**
 * Parallel-browse concurrency spec.
 *
 * Each test instance runs in its own worker / browser context, so N workers =
 * N concurrent virtual users. We don't parameterize test names by worker
 * because Playwright auto-shards the same describe block across workers when
 * workers > 1 in the config.
 *
 * Actual concurrency comes from the per-worker browser context: each worker
 * is an isolated Chromium launch with its own cookies, localStorage, and
 * network stack. Shared state bugs (server-side session leaks, DB locks,
 * rate limits, CDN cold-start spikes) surface here but not in the single-
 * worker suite.
 *
 * We purposefully DO NOT use wallet-mock here — that path mutates sessionStorage
 * in ways that can collide cross-worker even within separate contexts. This
 * test covers the anonymous-visitor concurrent load, which is the dominant
 * Cup-kickoff traffic pattern. Wallet-concurrent tests live in a separate
 * spec with explicit isolation.
 *
 * To spread load across N virtual users, we use a `for...of` loop of
 * `test("iter-N", ...)` calls — Playwright distributes them across workers.
 * Set LOADTEST_ITERATIONS env var to control the total count (default 30).
 */

const ITERATIONS = Number(process.env.LOADTEST_ITERATIONS ?? 30);
// Only routes that exist as `web/app/<route>/page.tsx`. The marketplace
// browse page lives at `/idiot/browse`, not `/browse`. Mismatch was a
// test-author typo from when this spec was first added.
const PATHS = [
  "/",
  "/idiot/browse",
  "/leaderboard",
  "/network",
  "/docs",
  "/about",
  "/attest",
];

test.describe.configure({ mode: "parallel" });

test.describe("concurrent anonymous visitor load", () => {
  for (let i = 0; i < ITERATIONS; i++) {
    test(`visitor iteration ${i}`, async ({ page }) => {
      const errors: string[] = [];
      page.on("pageerror", (err) => {
        const msg = err.message;
        // Production-minified React errors don't mention "hydrat" in the
        // message — they just embed the error number. 418/422/423/425
        // are the Suspense + hydration recovery family that fire under
        // concurrent load (Next prefetches, RSC payload races) and are
        // recoverable client-side. Same allowlist resilience.spec.ts uses.
        if (
          msg.includes("hydrat") ||
          msg.includes("ChunkLoadError") ||
          msg.includes("ResizeObserver") ||
          msg.includes("favicon") ||
          msg.includes("Minified React error #418") ||
          msg.includes("Minified React error #422") ||
          msg.includes("Minified React error #423") ||
          msg.includes("Minified React error #425")
        ) {
          return;
        }
        errors.push(msg);
      });

      const consoleErrors: string[] = [];
      page.on("console", (m) => {
        if (m.type() === "error") {
          const txt = m.text();
          if (
            txt.includes("favicon") ||
            txt.includes("walletconnect") ||
            txt.includes("hydrat") ||
            // Vercel Analytics injects /_vercel/insights/script.js. The
            // edge rewrite only exists on Vercel infra; off-Vercel
            // builds 404 the script, which trips the browser's strict
            // MIME check. Cosmetic, not a real error.
            txt.includes("_vercel/insights") ||
            // Next.js prefetches linked pages' RSC payloads. Under
            // concurrent load (or a slow CI runner), these can race
            // and fail; Next gracefully falls back to a regular nav.
            txt.includes("Failed to fetch RSC payload") ||
            // Backend-API proxy noise. The Idiot/Genius pages call
            // /api/* routes that forward to the validator network.
            // In CI we have no validators reachable, so these surface
            // as 502 (upstream timeout) or 429 (our own rate limiter
            // tripping under concurrent load). Both are environmental,
            // not JS bugs. Real JS errors show up as TypeError /
            // ReferenceError / SyntaxError, which we still catch via
            // pageerror + non-Failed-to-load console messages.
            (txt.startsWith("Failed to load resource") &&
              (txt.includes("502") || txt.includes("429"))) ||
            // Public Base Sepolia RPC (sepolia.base.org) doesn't return
            // CORS headers for cross-origin browser fetches. CI hits it
            // when contract reads (escrow balance, signal lookup, etc.)
            // bypass our wallet provider and go to the public endpoint.
            // This is environmental — in production the user's wallet
            // proxies the call so CORS doesn't apply.
            txt.includes("sepolia.base.org") ||
            txt.includes("CORS policy")
          ) {
            return;
          }
          consoleErrors.push(txt);
        }
      });

      const path = PATHS[i % PATHS.length];
      const start = Date.now();

      const resp = await page.goto(path, {
        waitUntil: "domcontentloaded",
        timeout: 30_000,
      });

      const ttfb = Date.now() - start;

      expect(resp, `no response for ${path}`).not.toBeNull();
      const status = resp!.status();
      expect(status, `status ${status} on ${path}`).toBeLessThan(400);

      await page.waitForLoadState("networkidle", { timeout: 15_000 }).catch(() => {
        // networkidle can legitimately not fire if a background fetch keeps looping;
        // we only fail if the page itself didn't render.
      });

      const title = await page.title();
      expect(title.length, `empty title on ${path}`).toBeGreaterThan(0);

      expect(
        errors,
        `page errors on ${path} (iter ${i}, ttfb ${ttfb}ms): ${errors.join(" | ")}`,
      ).toHaveLength(0);

      expect(
        consoleErrors.length,
        `console errors on ${path} (iter ${i}): ${consoleErrors.slice(0, 3).join(" | ")}`,
      ).toBeLessThan(3);

      expect(ttfb, `TTFB ${ttfb}ms exceeded 5s budget on ${path}`).toBeLessThan(5000);
    });
  }
});
