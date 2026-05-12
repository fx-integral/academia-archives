import { describe, it, expect } from "vitest";
import { formatBlockDate, formatRelative, dedupeBlockNumbers } from "../blockTime";

describe("formatBlockDate", () => {
  it("returns a localized date when timestamp is present", () => {
    const ts = Date.UTC(2026, 0, 2, 15, 4) / 1000;
    const out = formatBlockDate(ts, 23912844);
    expect(out).not.toBe("Block 23912844");
    expect(out.length).toBeGreaterThan(0);
  });

  it("falls back to block label when timestamp is missing", () => {
    expect(formatBlockDate(undefined, 23912844)).toBe("Block 23912844");
    expect(formatBlockDate(null, 100)).toBe("Block 100");
  });

  it("falls back to block label when timestamp is zero or negative", () => {
    expect(formatBlockDate(0, 7)).toBe("Block 7");
    expect(formatBlockDate(-5, 7)).toBe("Block 7");
  });
});

describe("formatRelative", () => {
  const now = 1_700_000_000_000;

  it("returns null when timestamp is unknown", () => {
    expect(formatRelative(undefined, now)).toBeNull();
    expect(formatRelative(0, now)).toBeNull();
  });

  it("returns 'just now' for under a minute", () => {
    expect(formatRelative(now / 1000 - 30, now)).toBe("just now");
  });

  it("returns minutes for under an hour", () => {
    expect(formatRelative(now / 1000 - 60, now)).toBe("1 minute ago");
    expect(formatRelative(now / 1000 - 600, now)).toBe("10 minutes ago");
  });

  it("returns hours for under a day", () => {
    expect(formatRelative(now / 1000 - 3600, now)).toBe("1 hour ago");
    expect(formatRelative(now / 1000 - 4 * 3600, now)).toBe("4 hours ago");
  });

  it("returns days for >= 1 day", () => {
    expect(formatRelative(now / 1000 - 86400, now)).toBe("1 day ago");
    expect(formatRelative(now / 1000 - 3 * 86400, now)).toBe("3 days ago");
  });
});

describe("dedupeBlockNumbers", () => {
  it("removes duplicates and sorts ascending", () => {
    expect(dedupeBlockNumbers([100, 50, 100, 75])).toEqual([50, 75, 100]);
  });

  it("filters out zero, negative, and non-finite values", () => {
    expect(dedupeBlockNumbers([0, -1, NaN, Infinity, 5])).toEqual([5]);
  });

  it("returns an empty array for empty input", () => {
    expect(dedupeBlockNumbers([])).toEqual([]);
  });
});
