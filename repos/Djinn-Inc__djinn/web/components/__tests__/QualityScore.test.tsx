import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import QualityScore from "../QualityScore";

describe("QualityScore", () => {
  it("renders the score with + prefix and $ formatting for positive scores", () => {
    const { container } = render(<QualityScore score={42.5} />);
    const text = container.textContent ?? "";
    expect(text).toContain("+");
    expect(text).toContain("$42.50");
    expect(text).toContain("QS");
  });

  it("renders QS label", () => {
    render(<QualityScore score={3} />);
    expect(screen.getByText("QS")).toBeInTheDocument();
  });

  it("exposes a tooltip explaining the metric", () => {
    const { container } = render(<QualityScore score={0} />);
    const wrapper = container.firstChild as HTMLElement;
    expect(wrapper.title).toMatch(/quality score is the net realized usdc/i);
  });

  describe("positive scores", () => {
    it("renders strong positive (≥ $100) with green-600 styling", () => {
      const { container } = render(<QualityScore score={250} />);
      const wrapper = container.firstChild as HTMLElement;
      expect(wrapper.className).toContain("text-green-600");
      expect(wrapper.className).toContain("bg-green-100");
    });

    it("renders mild positive (0 < score < $100) with green-500 styling", () => {
      const { container } = render(<QualityScore score={15} />);
      const wrapper = container.firstChild as HTMLElement;
      expect(wrapper.className).toContain("text-green-500");
      expect(wrapper.className).toContain("bg-green-50");
    });

    it("shows + prefix for positive scores", () => {
      const { container } = render(<QualityScore score={10} />);
      expect(container.textContent).toContain("+");
      expect(container.textContent).toContain("$10");
    });
  });

  describe("negative scores", () => {
    it("renders mild negative (-$100 < score < 0) with genius-500 styling", () => {
      const { container } = render(<QualityScore score={-25} />);
      const wrapper = container.firstChild as HTMLElement;
      expect(wrapper.className).toContain("text-genius-500");
      expect(wrapper.className).toContain("bg-orange-50");
    });

    it("renders strong negative (≤ -$100) with red styling", () => {
      const { container } = render(<QualityScore score={-150} />);
      const wrapper = container.firstChild as HTMLElement;
      expect(wrapper.className).toContain("text-red-600");
      expect(wrapper.className).toContain("bg-red-100");
    });

    it("renders exactly -$100 with red styling", () => {
      const { container } = render(<QualityScore score={-100} />);
      const wrapper = container.firstChild as HTMLElement;
      expect(wrapper.className).toContain("text-red-600");
    });

    it("uses unicode minus, no + prefix, on negative scores", () => {
      const { container } = render(<QualityScore score={-25} />);
      const text = container.textContent ?? "";
      expect(text).not.toMatch(/\+/);
      expect(text).toContain("−"); // unicode minus
      expect(text).toContain("$25");
    });
  });

  describe("zero score", () => {
    it("renders zero with slate styling and $0.00", () => {
      const { container } = render(<QualityScore score={0} />);
      const wrapper = container.firstChild as HTMLElement;
      expect(wrapper.className).toContain("text-slate-500");
      expect(wrapper.className).toContain("bg-slate-100");
      expect(container.textContent).toContain("$0.00");
    });

    it("does not show + prefix for zero", () => {
      const { container } = render(<QualityScore score={0} />);
      const text = container.textContent ?? "";
      expect(text).not.toMatch(/\+/);
    });
  });

  describe("size variants", () => {
    it("uses md size by default", () => {
      const { container } = render(<QualityScore score={5} />);
      const wrapper = container.firstChild as HTMLElement;
      expect(wrapper.className).toContain("text-2xl");
      expect(wrapper.className).toContain("px-4");
      expect(wrapper.className).toContain("py-2");
    });

    it("uses sm size when specified", () => {
      const { container } = render(<QualityScore score={5} size="sm" />);
      const wrapper = container.firstChild as HTMLElement;
      expect(wrapper.className).toContain("text-lg");
      expect(wrapper.className).toContain("px-3");
      expect(wrapper.className).toContain("py-1");
    });

    it("uses lg size when specified", () => {
      const { container } = render(<QualityScore score={5} size="lg" />);
      const wrapper = container.firstChild as HTMLElement;
      expect(wrapper.className).toContain("text-4xl");
      expect(wrapper.className).toContain("px-6");
      expect(wrapper.className).toContain("py-3");
    });
  });

  describe("boundary values", () => {
    it("renders exactly $100 with green-600 (strong positive bucket)", () => {
      const { container } = render(<QualityScore score={100} />);
      const wrapper = container.firstChild as HTMLElement;
      expect(wrapper.className).toContain("text-green-600");
    });

    it("renders $99.99 with green-500 (mild positive bucket)", () => {
      const { container } = render(<QualityScore score={99.99} />);
      const wrapper = container.firstChild as HTMLElement;
      expect(wrapper.className).toContain("text-green-500");
    });

    it("renders -$99.99 with genius-500 (mild negative bucket)", () => {
      const { container } = render(<QualityScore score={-99.99} />);
      const wrapper = container.firstChild as HTMLElement;
      expect(wrapper.className).toContain("text-genius-500");
    });

    it("formats large negative correctly with commas", () => {
      const { container } = render(<QualityScore score={-12345.67} />);
      expect(container.textContent).toContain("$12,345.67");
    });
  });
});
