import { test, expect } from "./fixtures/setup";

test.describe("Idiot dashboard (wallet connected)", () => {
  test("shows dashboard content instead of connect prompt", async ({
    authenticatedPage: page,
  }) => {
    await page.goto("/idiot");

    // With mock wallet connected, should NOT show the connect prompt
    await expect(page.getByText(/connect your wallet/i)).not.toBeVisible();

    // Should show the authenticated dashboard
    await expect(
      page.getByRole("heading", { name: "Idiot Dashboard" })
    ).toBeVisible();
  });

  test("shows wallet address in header", async ({
    authenticatedPage: page,
  }) => {
    await page.goto("/idiot");

    await expect(page.getByTestId("wallet-address")).toBeVisible();
    await expect(page.getByTestId("wallet-address")).toContainText("0xf39F");
  });

  test("shows escrow balance section", async ({
    authenticatedPage: page,
  }) => {
    await page.goto("/idiot");

    // Multiple elements on /idiot mention "Escrow" (heading, balance
    // label, deposit button); the strict-mode .first() picks the
    // first visible occurrence — that's enough to assert the section
    // rendered without coupling to a specific role.
    await expect(page.getByText("Escrow").first()).toBeVisible();
  });

  test("shows available signals section", async ({
    authenticatedPage: page,
  }) => {
    await page.goto("/idiot");

    // The signals list should be visible (may show "No signals" or loading)
    await expect(page.getByText(/signal/i).first()).toBeVisible();
  });

  test("deposit form accepts input", async ({
    authenticatedPage: page,
  }) => {
    await page.goto("/idiot");

    const depositInput = page.getByPlaceholder("Amount").first();
    await expect(depositInput).toBeVisible();
    await depositInput.fill("100");
    expect(await depositInput.inputValue()).toBe("100");
  });
});
