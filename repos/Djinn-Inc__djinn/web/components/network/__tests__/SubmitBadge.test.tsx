import { describe, it, expect } from "vitest";
import { render } from "@testing-library/react";
import SubmitBadge from "../SubmitBadge";

describe("SubmitBadge", () => {
  it("green 'submit' when both runtime and submit are ON", () => {
    const { container } = render(<SubmitBadge runtime={true} submit={true} />);
    const span = container.querySelector("span");
    expect(span?.className).toContain("emerald");
    expect(span?.textContent).toBe("submit");
  });

  it("amber 'shadow' when runtime ON but submit OFF (observe-only)", () => {
    const { container } = render(<SubmitBadge runtime={true} submit={false} />);
    const span = container.querySelector("span");
    expect(span?.className).toContain("amber");
    expect(span?.textContent).toBe("shadow");
  });

  it("red 'broken' when submit ON but runtime OFF (incoherent config)", () => {
    const { container } = render(<SubmitBadge runtime={false} submit={true} />);
    const span = container.querySelector("span");
    expect(span?.className).toContain("red");
    expect(span?.textContent).toBe("broken");
  });

  it("slate 'off' when both flags are OFF (default state)", () => {
    const { container } = render(<SubmitBadge runtime={false} submit={false} />);
    const span = container.querySelector("span");
    expect(span?.className).toContain("slate");
    expect(span?.textContent).toBe("off");
  });

  it("renders '-' when either flag is null (pre-v1562 validator)", () => {
    const { container } = render(<SubmitBadge runtime={null} submit={null} />);
    expect(container.textContent).toBe("-");
  });

  it("renders '-' when flags are undefined", () => {
    const { container } = render(<SubmitBadge />);
    expect(container.textContent).toBe("-");
  });

  it("renders '-' when only one flag is present", () => {
    const { container } = render(<SubmitBadge runtime={true} />);
    expect(container.textContent).toBe("-");
  });
});
