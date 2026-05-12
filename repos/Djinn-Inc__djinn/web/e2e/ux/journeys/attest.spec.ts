import { test, expect } from "@playwright/test";
import { humanDelay, humanScroll, waitForIdle } from "../helpers/human";
import { landOnSite, clickNav } from "../helpers/navigate";

const BASE_URL = process.env.UX_BASE_URL ?? "https://djinn.gg";

test.describe("Attest Journey", () => {
  test.describe.configure({ mode: "serial" });

  test("anonymous visitor lands on /attest and sees a usable proof form", async ({
    page,
  }) => {
    const errors: string[] = [];
    page.on("pageerror", (err) => {
      if (
        err.message.includes("hydrat") ||
        err.message.includes("ChunkLoadError") ||
        err.message.includes("ResizeObserver") ||
        err.message.includes("Minified React error #418") ||
        err.message.includes("Minified React error #422") ||
        err.message.includes("Minified React error #423") ||
        err.message.includes("Minified React error #425")
      )
        return;
      errors.push(err.message);
    });

    let attestApiCalled = false;
    await page.route("**/api/attest", (route) => {
      attestApiCalled = true;
      return route.fulfill({
        status: 500,
        contentType: "application/json",
        body: JSON.stringify({ error: "journey-should-not-call" }),
      });
    });

    await landOnSite(page, BASE_URL);
    await expect(page).toHaveTitle(/djinn/i, { timeout: 10_000 });

    await clickNav(page, "Verify Picks");
    await expect(page).toHaveURL(/\/attest/, { timeout: 10_000 });
    await waitForIdle(page);

    await expect(
      page.getByRole("heading", { name: "Web Attestation", level: 1 }),
    ).toBeVisible({ timeout: 10_000 });

    await expect(
      page.getByRole("heading", { name: /how it works/i }),
    ).toBeVisible();
    await expect(page.getByText(/enter a url/i)).toBeVisible();
    await expect(page.getByText(/wait for the proof/i)).toBeVisible();
    await expect(page.getByText(/download your proof/i)).toBeVisible();

    const urlInput = page.locator("#attest-url");
    await expect(urlInput).toBeVisible();
    await expect(urlInput).toHaveAttribute(
      "placeholder",
      "https://httpbin.org/get",
    );
    await expect(urlInput).toBeEnabled();

    const submitButton = page.getByRole("button", { name: /^attest$/i });
    await expect(submitButton).toBeVisible();
    await expect(submitButton).toBeDisabled();

    await humanScroll(page);
    await humanDelay(page);

    await urlInput.fill("http://example.com");
    await expect(submitButton).toBeEnabled();
    await submitButton.click();

    await expect(page.getByText(/url must start with https:\/\//i)).toBeVisible(
      { timeout: 5_000 },
    );

    expect(attestApiCalled, "invalid URL should not hit /api/attest").toBe(
      false,
    );

    await expect(
      page.locator('[data-test="attest-result"], .attest-result-card'),
    ).toHaveCount(0);

    expect(errors, `page errors: ${errors.join(" | ")}`).toEqual([]);
  });
});
