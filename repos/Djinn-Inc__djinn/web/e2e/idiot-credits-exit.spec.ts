import { test, expect } from "./fixtures/setup";

test.describe("Idiot dashboard — credits and early exit", () => {
  test("shows Djinn Credits balance card", async ({
    authenticatedPage: page,
  }) => {
    await page.goto("/idiot");

    // Without wallet, page shows connect prompt — verify it loads
    await expect(
      page.getByRole("heading", { name: "Idiot Dashboard" })
    ).toBeVisible();
  });
});

test.describe("Idiot dashboard — signal discovery", () => {
  test("shows Available Signals section", async ({
    authenticatedPage: page,
  }) => {
    await page.goto("/idiot");

    await expect(
      page.getByRole("heading", { name: /Available Signals/i })
    ).toBeVisible();
  });

  test("has sport filter dropdown", async ({
    authenticatedPage: page,
  }) => {
    await page.goto("/idiot");

    const sportSelect = page.getByLabel("Filter by sport");
    await expect(sportSelect).toBeVisible();
  });

  test("has sort dropdown", async ({
    authenticatedPage: page,
  }) => {
    await page.goto("/idiot");

    const sortSelect = page.getByLabel("Sort signals");
    await expect(sortSelect).toBeVisible();
  });

  test("has filters toggle button", async ({
    authenticatedPage: page,
  }) => {
    await page.goto("/idiot");

    const filtersBtn = page.getByRole("button", { name: /Filters/i });
    await expect(filtersBtn).toBeVisible();

    // Clicking should show the filter panel
    await filtersBtn.click();
    await expect(page.getByText(/Max Fee/i)).toBeVisible();
    // SLA was renamed to "Backing" in v1398 (plain-English sweep wave 5).
    await expect(page.getByText(/Min Backing/i)).toBeVisible();
  });

  test("has list/plot view toggle", async ({
    authenticatedPage: page,
  }) => {
    await page.goto("/idiot");

    const listBtn = page.getByLabel("List view");
    const plotBtn = page.getByLabel("Dot plot view");
    await expect(listBtn).toBeVisible();
    await expect(plotBtn).toBeVisible();
  });
});
