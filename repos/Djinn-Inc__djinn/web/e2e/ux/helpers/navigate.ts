import { expect, type Page } from "@playwright/test";
import { humanClick, humanDelay, waitForIdle, scrollToTop } from "./human";
import * as fs from "fs";
import * as path from "path";

/**
 * Click-based navigation that uses the site's own UI.
 *
 * After the initial page.goto(), all navigation happens through clicks.
 * This triggers Next.js client-side routing (no full page reload),
 * which avoids Vercel's bot protection that triggers on rapid goto() calls.
 *
 * Three layers of Vercel checkpoint handling:
 * 1. VERCEL_BYPASS_SECRET env var -> sends x-vercel-protection-bypass header
 * 2. Persistent cookie state -> reuses checkpoint cookies from previous runs
 * 3. Checkpoint detection + wait -> waits for JS challenge to auto-resolve
 */

const STORAGE_STATE_PATH = path.join(
  __dirname,
  "..",
  ".vercel-session.json",
);

/**
 * Save browser cookies/storage after passing the checkpoint.
 * Subsequent runs will load these to skip the challenge.
 */
async function saveSessionState(page: Page): Promise<void> {
  try {
    const state = await page.context().storageState();
    fs.writeFileSync(STORAGE_STATE_PATH, JSON.stringify(state, null, 2));
    console.log("[ux] Session state saved for future runs");
  } catch {
    // Non-critical; just log
    console.log("[ux] Could not save session state");
  }
}

/**
 * Load saved session state (cookies from a previous successful run).
 * Returns true if state was loaded.
 */
export function getSavedStorageStatePath(): string | undefined {
  if (fs.existsSync(STORAGE_STATE_PATH)) {
    try {
      const stat = fs.statSync(STORAGE_STATE_PATH);
      // Expire after 12 hours (Vercel challenge cookies have limited lifetime)
      const ageHours = (Date.now() - stat.mtimeMs) / 3_600_000;
      if (ageHours < 12) {
        return STORAGE_STATE_PATH;
      }
      console.log("[ux] Saved session state expired, will re-authenticate");
    } catch {
      // Ignore
    }
  }
  return undefined;
}

// Playwright's config-level storageState only seeds the default `page`
// fixture. Spec files that call `browser.newContext()` directly (e.g.
// purchase.spec.ts spawning separate genius/idiot contexts) start with
// a fresh cookie jar and therefore trip Vercel's hard-403 fingerprint
// block on the first landOnSite. Spread this into those newContext
// calls so every context inherits the saved challenge cookies.
// Iter-62 regression: 3 hard-403 failures at navigate.ts:142 all came
// from contexts without storageState.
export function getVercelContextOptions(): { storageState?: string } {
  const path = getSavedStorageStatePath();
  return path ? { storageState: path } : {};
}

/**
 * Wait for the Vercel Security Checkpoint to auto-resolve.
 * Returns true if checkpoint was detected (regardless of resolution).
 */
async function waitForCheckpoint(
  page: Page,
  timeoutMs = 15_000,
): Promise<boolean> {
  const title = await page.title();
  if (!title.includes("Vercel Security Checkpoint")) return false;

  console.log(
    "[ux] Vercel Security Checkpoint detected, waiting for resolution...",
  );

  // Wait for the title to change (checkpoint resolved and redirected)
  const resolved = await page
    .waitForFunction(
      () => !document.title.includes("Vercel Security Checkpoint"),
      { timeout: timeoutMs },
    )
    .then(() => true)
    .catch(() => false);

  if (resolved) {
    console.log("[ux] Checkpoint resolved");
    await page.waitForLoadState("domcontentloaded");
    await waitForIdle(page);
    await saveSessionState(page);
  }

  return true;
}

/**
 * Detect Vercel's hard-403 "Error: Forbidden" page (distinct from the
 * JS challenge). Title is "403: Forbidden" and body has no challenge JS.
 * Curl from the same runner immediately after usually still gets the
 * normal soft challenge, so a 30–60s cooldown + reload often clears it.
 * Returns true if the page is the hard-403.
 */
async function isVercelHardBlock(page: Page): Promise<boolean> {
  const title = await page.title().catch(() => "");
  return title.includes("403: Forbidden") || title === "Forbidden";
}

/**
 * Land on the site. This is the ONLY goto call per journey.
 *
 * Handles Vercel's Security Checkpoint via:
 * 1. Bypass header (if VERCEL_BYPASS_SECRET is set)
 * 2. Saved session cookies (from previous runs)
 * 3. Waiting for JS challenge to resolve
 * 4. Retry after cooldown
 */
export async function landOnSite(page: Page, baseUrl: string): Promise<void> {
  // Layer 1: Set bypass header if secret is available
  const bypassSecret = process.env.VERCEL_BYPASS_SECRET;
  if (bypassSecret) {
    await page.setExtraHTTPHeaders({
      "x-vercel-protection-bypass": bypassSecret,
    });
    console.log("[ux] Using Vercel bypass header");
  }

  // Navigate
  await page.goto(baseUrl, { waitUntil: "domcontentloaded" });

  // Layer 2.5: Detect hard-403 "Error: Forbidden" page (Vercel's escalation
  // past the JS challenge). 90s cooldown + reload usually drops back to the
  // soft challenge that waitForCheckpoint() can resolve. If the second try
  // is still hard-blocked, fail-fast with an actionable error so iteration
  // reports don't present as confusing "toHaveTitle: got '403: Forbidden'".
  // Iter-49/51 empirical evidence: 30s cooldown was insufficient; visitor
  // tests that naturally ran post-cooldown (45-60s later) recovered, so the
  // WAF release window lands in the 60-90s band.
  if (await isVercelHardBlock(page)) {
    // Attempt 1: 90s cooldown with saved cookies intact. Iter-49/51
    // placed the WAF release window at 60-90s for the soft challenge.
    console.log("[ux] Vercel hard-403 detected (attempt 1/2); cooling 90s then reloading...");
    await page.waitForTimeout(90_000);
    await page.reload({ waitUntil: "domcontentloaded" });

    if (await isVercelHardBlock(page)) {
      // Attempt 2: iter-62 showed the 90s window now exceeds the WAF
      // release for Playwright fingerprints at tail-of-run. Clearing
      // cookies drops back to an un-tainted fingerprint; a fresh JS
      // challenge is more likely to succeed than another reload under
      // the same fingerprint that just tripped the block.
      console.log(
        "[ux] Vercel hard-403 persists (attempt 2/2); clearing cookies + cooling 120s then reloading...",
      );
      await page.context().clearCookies();
      await page.waitForTimeout(120_000);
      await page.reload({ waitUntil: "domcontentloaded" });

      if (await isVercelHardBlock(page)) {
        throw new Error(
          "Vercel hard-403 'Error: Forbidden' persisted after 2 cooldown+reload attempts (90s + 120s, cookies cleared on 2nd).\n" +
            "This is a Playwright-class fingerprint block distinct from\n" +
            "the JS challenge. Wait 5-10 minutes for the WAF cooldown or\n" +
            "set VERCEL_BYPASS_SECRET (project Settings > Security).\n" +
            `URL: ${page.url()}`,
        );
      }
    }
  }

  // Layer 3: Detect and wait for checkpoint
  const hitCheckpoint = await waitForCheckpoint(page);

  if (hitCheckpoint) {
    const currentTitle = await page.title();
    if (currentTitle.includes("Vercel Security Checkpoint")) {
      // Checkpoint didn't resolve. Try once more after a cooldown.
      console.log("[ux] Checkpoint not resolved. Retrying after 10s cooldown...");
      await page.waitForTimeout(10_000);
      await page.reload({ waitUntil: "domcontentloaded" });
      const stillBlocked = await waitForCheckpoint(page, 20_000);

      if (stillBlocked) {
        const finalTitle = await page.title();
        if (finalTitle.includes("Vercel Security Checkpoint")) {
          throw new Error(
            "Vercel Security Checkpoint could not be resolved.\n" +
              "Solutions (in order of reliability):\n" +
              "  1. Set VERCEL_BYPASS_SECRET (from Vercel project Settings > Security)\n" +
              "  2. Run once in headed mode (UX_HEADED=1) to pass checkpoint manually\n" +
              "  3. Wait a few minutes for rate limiting to expire\n" +
              "  4. Use UX_BASE_URL to point at a preview deployment",
          );
        }
      }
    }

    // After checkpoint resolution, verify we're on the right domain
    const url = page.url();
    if (!url.includes(new URL(baseUrl).hostname)) {
      await page.goto(baseUrl, { waitUntil: "domcontentloaded" });
    }
  }

  await waitForIdle(page);
  await humanDelay(page, 1500, 3000);

  // Save state for future runs (even if no checkpoint was hit)
  await saveSessionState(page);
}

/** Click a nav link by its label text. */
export async function clickNav(page: Page, label: string): Promise<void> {
  await scrollToTop(page);
  // Desktop nav links are <a> inside the nav
  const navLink = page.locator("nav").getByRole("link", { name: label });
  // If desktop nav is hidden (mobile), open hamburger first
  if (!(await navLink.isVisible().catch(() => false))) {
    const hamburger = page
      .locator("button[aria-label*='menu' i], button[aria-label*='Menu' i]")
      .first();
    if (await hamburger.isVisible().catch(() => false)) {
      await humanClick(hamburger);
      await page.waitForTimeout(500);
    }
  }
  const link = page.getByRole("link", { name: label }).first();
  await expect(link).toBeVisible({ timeout: 5_000 });
  await humanClick(link);
  await waitForIdle(page);
  await humanDelay(page, 1000, 2000);
}

/** Click the logo/home link to go back to the homepage. */
export async function goHome(page: Page): Promise<void> {
  const logo = page.locator('a[href="/"]').first();
  await humanClick(logo);
  await waitForIdle(page);
  await humanDelay(page);
}

/** Click "Connect Wallet" (formerly "Get Started") to open the wallet connection modal. */
export async function clickGetStarted(page: Page): Promise<void> {
  const btn = page.getByRole("button", { name: /connect wallet|get started/i });
  if (await btn.isVisible({ timeout: 5_000 }).catch(() => false)) {
    await humanClick(btn);
    await page.waitForTimeout(1000);
  }
}

/**
 * Connect the mock wallet through the RainbowKit modal.
 * The wallet-mock library injects via EIP-6963, so RainbowKit shows it.
 */
export async function connectWalletViaUI(page: Page): Promise<void> {
  await clickGetStarted(page);

  // Handle terms modal if it appears
  const termsCheckbox = page.locator("input[type='checkbox']").first();
  if (await termsCheckbox.isVisible({ timeout: 3_000 }).catch(() => false)) {
    await termsCheckbox.check();
    await page.waitForTimeout(500);
    const acceptBtn = page
      .getByRole("button", { name: /accept|agree|continue/i })
      .first();
    if (await acceptBtn.isVisible({ timeout: 2_000 }).catch(() => false)) {
      await humanClick(acceptBtn);
      await page.waitForTimeout(1000);
    }
  }

  // Click the mock wallet option in RainbowKit
  for (let attempt = 0; attempt < 3; attempt++) {
    try {
      const mockBtn = page.getByRole("button", { name: /mock/i });
      await mockBtn.waitFor({ state: "visible", timeout: 5_000 });
      await page.waitForTimeout(500);
      await mockBtn.click({ timeout: 5_000 });
      break;
    } catch {
      if (attempt === 2) {
        // Maybe wallet auto-connected (EIP-6963 can do that)
        break;
      }
      await page.waitForTimeout(1_000);
    }
  }

  // Wait for connection to settle
  await page.waitForTimeout(2_000);
}

/** Check if the wallet appears connected (no "Connect Wallet" / "Get Started" visible). */
export async function isWalletConnected(page: Page): Promise<boolean> {
  const connectBtn = page.getByRole("button", { name: /connect wallet|get started/i });
  return !(await connectBtn.isVisible({ timeout: 2_000 }).catch(() => false));
}

/** Click a link by visible text anywhere on the page. */
export async function clickLink(
  page: Page,
  text: string | RegExp,
): Promise<void> {
  const link = page.getByRole("link", { name: text }).first();
  await expect(link).toBeVisible({ timeout: 10_000 });
  await humanClick(link);
  await waitForIdle(page);
  await humanDelay(page);
}

/** Click a button by visible text. */
export async function clickButton(
  page: Page,
  text: string | RegExp,
): Promise<void> {
  const btn = page.getByRole("button", { name: text }).first();
  await expect(btn).toBeVisible({ timeout: 10_000 });
  await humanClick(btn);
}
