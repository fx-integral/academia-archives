import { describe, expect, it } from "vitest";
import { getGeniusOnboardingSteps } from "../geniusOnboarding";

describe("getGeniusOnboardingSteps", () => {
  it("gives publishers concrete test-USDC instructions instead of an undefined swap", () => {
    const steps = getGeniusOnboardingSteps("0x0000000000000000000000000000000000001234");
    const usdcStep = steps.find((step) => step.step === "3");

    expect(usdcStep).toBeDefined();
    expect(usdcStep?.label).toBe("Get test USDC");
    expect(usdcStep?.hint).toContain("Get free test USDC");
    expect(usdcStep?.hint).toContain("0x0000000000000000000000000000000000001234");
    expect(usdcStep?.hint.toLowerCase()).not.toContain("swap");
    expect(usdcStep?.ctas?.map((cta) => cta.label)).toEqual([
      "Open ETH faucet",
      "Need help? Ask Discord",
    ]);
  });
});
