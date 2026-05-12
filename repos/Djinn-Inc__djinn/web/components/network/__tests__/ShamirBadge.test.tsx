import { describe, it, expect } from "vitest";
import { render } from "@testing-library/react";
import ShamirBadge from "../ShamirBadge";

describe("ShamirBadge", () => {
  it("green when threshold matches client target (2)", () => {
    const { container } = render(<ShamirBadge threshold={2} />);
    const span = container.querySelector("span");
    expect(span?.className).toContain("emerald");
    expect(span?.textContent).toBe("st=2");
  });

  it("amber when threshold is 7 (stranded)", () => {
    const { container } = render(<ShamirBadge threshold={7} />);
    const span = container.querySelector("span");
    expect(span?.className).toContain("amber");
    expect(span?.textContent).toBe("st=7 !");
    expect(span?.getAttribute("title")).toContain("Pull v1556+");
  });

  it("amber even at threshold=3 (any non-match)", () => {
    const { container } = render(<ShamirBadge threshold={3} />);
    const span = container.querySelector("span");
    expect(span?.className).toContain("amber");
    expect(span?.textContent).toBe("st=3 !");
  });

  it("renders '-' when threshold is null", () => {
    const { container } = render(<ShamirBadge threshold={null} />);
    expect(container.textContent).toBe("-");
  });

  it("renders '-' when threshold is undefined (pre-v1454 validator)", () => {
    const { container } = render(<ShamirBadge />);
    expect(container.textContent).toBe("-");
  });
});
