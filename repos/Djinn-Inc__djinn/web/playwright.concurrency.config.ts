import { defineConfig } from "@playwright/test";

/**
 * Concurrency / load-simulation config.
 *
 * Unlike playwright.ux.config.ts (workers=1, happy-path, production target),
 * this config spawns N parallel browser contexts to simulate concurrent users.
 * Finds wallet-mock races, MPC contention, session-storage collisions, and
 * UI race conditions that never surface in single-worker runs.
 *
 * IMPORTANT: do NOT point this at https://djinn.gg without VERCEL_BYPASS_SECRET —
 * Vercel's bot-challenge will 403 parallel traffic from the same IP and the
 * run will devolve into noise. Target staging, localhost:3000, or a bypass-
 * enabled production run.
 *
 * Usage:
 *   LOADTEST_TARGET=http://localhost:3000 pnpm test:concurrency
 *   LOADTEST_TARGET=https://staging.djinn.gg LOADTEST_WORKERS=30 pnpm test:concurrency
 *   LOADTEST_TARGET=https://djinn.gg VERCEL_BYPASS_SECRET=xxx LOADTEST_WORKERS=20 pnpm test:concurrency
 *
 * Env:
 *   LOADTEST_TARGET    - Required. Base URL to hit.
 *   LOADTEST_WORKERS   - Optional. Default 10. Parallel contexts.
 *   VERCEL_BYPASS_SECRET - Required when LOADTEST_TARGET is djinn.gg.
 */

const TARGET = process.env.LOADTEST_TARGET;
const WORKERS = Number(process.env.LOADTEST_WORKERS ?? 10);

if (!TARGET) {
  console.error(
    "ERROR: LOADTEST_TARGET env var not set. Refusing to default to production — set LOADTEST_TARGET=http://localhost:3000 or similar.",
  );
  process.exit(1);
}

export default defineConfig({
  testDir: "./e2e/concurrency",

  fullyParallel: true,
  workers: WORKERS,
  retries: 0,
  reporter: [["list"], ["html", { open: "never" }]],

  timeout: 120_000,
  globalTimeout: 900_000,

  use: {
    baseURL: TARGET,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    video: "off",
    navigationTimeout: 30_000,
    actionTimeout: 15_000,
    channel: "chrome",
    launchOptions: {
      args: [
        "--disable-blink-features=AutomationControlled",
        "--disable-features=IsolateOrigins,site-per-process",
      ],
    },
    headless: true,
    viewport: { width: 1440, height: 900 },
    extraHTTPHeaders: process.env.VERCEL_BYPASS_SECRET
      ? {
          "x-vercel-protection-bypass": process.env.VERCEL_BYPASS_SECRET,
          "x-vercel-set-bypass-cookie": "samesitenone",
        }
      : undefined,
  },

  projects: [
    {
      name: "concurrency",
      testMatch: /\.spec\.ts$/,
    },
  ],
});
