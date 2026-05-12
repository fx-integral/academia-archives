import { test, expect, type Page } from "@playwright/test";
import { installMockWallet } from "@johanneskares/wallet-mock";
import { privateKeyToAccount } from "viem/accounts";
import { baseSepolia } from "viem/chains";
import { keccak256, toHex } from "viem";

/**
 * Parallel wallet-connect concurrency spec.
 *
 * Each test instance runs in its own worker / browser context with a unique
 * derived private key, then drives the full Get Started → RainbowKit → mock
 * wallet connect flow. Surfaces:
 *   - wagmi hook races (duplicate connector init, lingering pending state)
 *   - RainbowKit modal disambiguation bugs when many EIP-6963 wallets race
 *   - sessionStorage / localStorage collisions inside wallet-mock
 *   - connect timeout regressions under load
 *
 * The browse-parallel spec explicitly skips wallet-mock because its internal
 * state is per-page and we didn't want cross-context bleed. Here we isolate
 * by deriving a unique PK per (worker, iteration) so every page has its own
 * address, and we mock the RPC layer so we never hit Base Sepolia.
 *
 * LOADTEST_WALLET_ITERATIONS env var controls total count (default 15).
 * Lower than browse-parallel (30) because each wallet test takes 10-20s.
 */

const ITERATIONS = Number(process.env.LOADTEST_WALLET_ITERATIONS ?? 15);

// Deterministic per-(worker, iter) PK derivation. Same iter always gets same
// PK, so retries stay consistent; different iter or worker gets a unique addr.
function derivePrivateKey(workerIndex: number, iter: number): `0x${string}` {
  return keccak256(toHex(`djinn-loadtest-wallet-${workerIndex}-${iter}`));
}

// Mock RPC + subgraph + odds so the wallet flow doesn't depend on live chain.
// We're stressing the client wallet-connect path, not the network.
async function mockBackends(page: Page) {
  // USDC 1000 balance (6 decimals, big-endian padded 32 bytes)
  const USDC_1000 =
    "0x00000000000000000000000000000000000000000000000000000000" +
    "3b9aca00".padStart(8, "0");

  await page.route("**/sepolia.base.org**", async (route) => {
    let body: { method?: string; id?: number } | null = null;
    try {
      body = route.request().postDataJSON();
    } catch {
      /* GETs / non-JSON */
    }
    if (!body) {
      await route.continue();
      return;
    }
    if (body.method === "eth_call") {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ jsonrpc: "2.0", id: body.id, result: USDC_1000 }),
      });
    } else if (body.method === "eth_chainId") {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ jsonrpc: "2.0", id: body.id, result: "0x14a34" }),
      });
    } else {
      await route.continue();
    }
  });

  await page.route("**/subgraphs/**", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        data: {
          protocolStats: {
            totalVolume: "0",
            totalSignals: "0",
            totalPurchases: "0",
          },
        },
      }),
    });
  });
}

test.describe.configure({ mode: "parallel" });

test.describe("concurrent wallet-connect load", () => {
  for (let i = 0; i < ITERATIONS; i++) {
    test(`wallet-connect iteration ${i}`, async ({ page }, testInfo) => {
      const pk = derivePrivateKey(testInfo.workerIndex, i);
      const account = privateKeyToAccount(pk);

      const pageErrors: string[] = [];
      page.on("pageerror", (err) => {
        const msg = err.message;
        // Same Suspense+hydration recovery allowlist as resilience.spec.ts:
        // production-minified React errors omit "hydrat" and just embed
        // the error number, so the substring check has to look for the
        // numbered form too.
        if (
          msg.includes("hydrat") ||
          msg.includes("ChunkLoadError") ||
          msg.includes("ResizeObserver") ||
          msg.includes("favicon") ||
          msg.includes("walletconnect") ||
          msg.includes("Minified React error #418") ||
          msg.includes("Minified React error #422") ||
          msg.includes("Minified React error #423") ||
          msg.includes("Minified React error #425")
        )
          return;
        pageErrors.push(msg);
      });

      const consoleErrors: string[] = [];
      page.on("console", (m) => {
        if (m.type() === "error") {
          const txt = m.text();
          if (
            txt.includes("favicon") ||
            txt.includes("walletconnect") ||
            txt.includes("hydrat") ||
            // wagmi's "multiple wagmi config" is noisy but benign under parallel
            txt.includes("multiple wagmi") ||
            // Next.js prefetches RSC payloads on link hover/click; under
            // 15-context parallel load these races, falls back to a normal
            // navigation, and logs an error. Same allowlist that
            // browse-parallel.spec.ts uses.
            txt.includes("Failed to fetch RSC payload") ||
            // Same backend-API proxy noise: 502 (upstream timeout) or 429
            // (our own rate limiter) under heavy parallel load.
            (txt.startsWith("Failed to load resource") &&
              (txt.includes("502") || txt.includes("429")))
          )
            return;
          consoleErrors.push(txt);
        }
      });

      await installMockWallet({
        page,
        account,
        defaultChain: baseSepolia,
      });
      await mockBackends(page);

      const start = Date.now();
      const resp = await page.goto("/", {
        waitUntil: "domcontentloaded",
        timeout: 30_000,
      });
      const ttfb = Date.now() - start;
      expect(resp, `no response (iter ${i})`).not.toBeNull();
      expect(
        resp!.status(),
        `homepage status ${resp!.status()} (iter ${i})`,
      ).toBeLessThan(400);

      // Wait for the header WalletButton to mount in EITHER state.
      // ConnectButton.Custom returns null until wagmi/RainbowKit hydrate;
      // under 15 parallel browser contexts on one CI runner that takes
      // 10-25s. After hydration the header renders ONE OF:
      //   (a) Connect Wallet button (disconnected — we click it)
      //   (b) data-testid="wallet-address" (auto-connected via the mock
      //       wallet's EIP-6963 provider — skip the click)
      // Race both with the same 25s budget; whichever resolves first wins.
      const cta = page.getByRole("button", { name: /get started|connect wallet/i }).first();
      const connectedAddrLocator = page.locator('[data-testid="wallet-address"]');
      const handle = await Promise.race([
        cta.waitFor({ state: "visible", timeout: 25_000 }).then(() => "cta" as const).catch(() => null),
        connectedAddrLocator.waitFor({ state: "visible", timeout: 25_000 }).then(() => "connected" as const).catch(() => null),
      ]);
      if (handle === null) {
        throw new Error(`no Connect Wallet on / (iter ${i})`);
      }
      if (handle === "cta") {
        await cta.click();
      }

      // Terms modal may appear — accept if so
      const termsCheckbox = page.locator("input[type='checkbox']").first();
      if (
        await termsCheckbox.isVisible({ timeout: 3_000 }).catch(() => false)
      ) {
        await termsCheckbox.check();
        const accept = page
          .getByRole("button", { name: /accept|agree|continue/i })
          .first();
        if (await accept.isVisible({ timeout: 2_000 }).catch(() => false)) {
          await accept.click();
        }
      }

      // Click the mock wallet in RainbowKit — up to 3 attempts because
      // EIP-6963 sometimes auto-connects before the modal renders.
      let connected = false;
      for (let a = 0; a < 3; a++) {
        const mockBtn = page.getByRole("button", { name: /mock/i });
        try {
          await mockBtn.waitFor({ state: "visible", timeout: 4_000 });
          await mockBtn.click({ timeout: 4_000 });
          connected = true;
          break;
        } catch {
          // May have auto-connected; break out and verify below
          if (
            await page
              .getByText(new RegExp(account.address.slice(0, 6), "i"))
              .isVisible({ timeout: 1_000 })
              .catch(() => false)
          ) {
            connected = true;
            break;
          }
          await page.waitForTimeout(500);
        }
      }

      // Verify connected: wallet address prefix visible in header OR Get Started gone.
      const connectDeadline = Date.now() + 10_000;
      let addressVisible = false;
      while (Date.now() < connectDeadline) {
        if (
          await page
            .getByText(new RegExp(account.address.slice(2, 8), "i"))
            .isVisible({ timeout: 500 })
            .catch(() => false)
        ) {
          addressVisible = true;
          break;
        }
        // Fallback: connect CTA should be gone
        if (
          !(await page
            .getByRole("button", { name: /connect wallet|get started/i })
            .isVisible({ timeout: 500 })
            .catch(() => false))
        ) {
          addressVisible = true;
          break;
        }
        await page.waitForTimeout(250);
      }

      expect(
        addressVisible,
        `wallet did not connect within 10s (iter ${i}, addr ${account.address.slice(0, 10)}, connected-click=${connected}, ttfb ${ttfb}ms)`,
      ).toBe(true);

      expect(
        pageErrors,
        `page errors after connect (iter ${i}): ${pageErrors.slice(0, 3).join(" | ")}`,
      ).toHaveLength(0);

      expect(
        consoleErrors.length,
        `console errors after connect (iter ${i}): ${consoleErrors.slice(0, 3).join(" | ")}`,
      ).toBeLessThan(5);
    });
  }
});
