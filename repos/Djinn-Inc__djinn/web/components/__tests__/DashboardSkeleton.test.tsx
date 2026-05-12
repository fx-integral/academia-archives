import { describe, it, expect } from "vitest";
import { render } from "@testing-library/react";
import DashboardSkeleton, { StatCardSkeleton, TableRowSkeleton, TableSkeleton } from "../DashboardSkeleton";

describe("DashboardSkeleton", () => {
  it("renders without crashing", () => {
    const { container } = render(<DashboardSkeleton />);
    expect(container.firstChild).toBeTruthy();
  });

  it("contains pulse animation class", () => {
    const { container } = render(<DashboardSkeleton />);
    const animatedEl = container.querySelector(".animate-pulse");
    expect(animatedEl).toBeTruthy();
  });

  it("renders stat card skeletons", () => {
    const { container } = render(<DashboardSkeleton />);
    // Should have 4 stat card placeholders in the grid
    const grid = container.querySelector(".grid");
    expect(grid).toBeTruthy();
    expect(grid!.children.length).toBe(4);
  });
});

describe("StatCardSkeleton", () => {
  it("renders without crashing", () => {
    const { container } = render(<StatCardSkeleton />);
    expect(container.firstChild).toBeTruthy();
  });
});

describe("TableRowSkeleton", () => {
  it("renders without crashing", () => {
    const { container } = render(<TableRowSkeleton />);
    expect(container.firstChild).toBeTruthy();
  });
});

describe("TableSkeleton", () => {
  it("renders default 3 rows", () => {
    const { container } = render(<TableSkeleton />);
    const animatedEl = container.querySelector(".animate-pulse");
    expect(animatedEl).toBeTruthy();
    expect(animatedEl!.children.length).toBe(3);
  });

  it("renders custom row count", () => {
    const { container } = render(<TableSkeleton rows={5} />);
    const animatedEl = container.querySelector(".animate-pulse");
    expect(animatedEl!.children.length).toBe(5);
  });
});
