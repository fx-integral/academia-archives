import { describe, it, expect } from "vitest";
import {
  WIN_RATE_MIN_AUDITS_DEFAULT,
  WIN_RATE_SMALL_SAMPLE_THRESHOLD,
  classifySample,
  meetsMinAudits,
  winRateLowerBound,
  winRatePercent,
  winRateSampleSize,
} from "../winRateConfidence";

describe("winRateSampleSize", () => {
  it("sums favorable + unfavorable, ignoring void", () => {
    expect(winRateSampleSize({ favCount: 3, unfavCount: 2 })).toBe(5);
  });

  it("returns 0 when no audits resolved", () => {
    expect(winRateSampleSize({ favCount: 0, unfavCount: 0 })).toBe(0);
  });
});

describe("winRatePercent", () => {
  it("returns 0 for empty samples (no divide-by-zero)", () => {
    expect(winRatePercent({ favCount: 0, unfavCount: 0 })).toBe(0);
  });

  it("renders raw favorable/total percentage", () => {
    expect(winRatePercent({ favCount: 130, unfavCount: 70 })).toBeCloseTo(65, 5);
    expect(winRatePercent({ favCount: 2, unfavCount: 0 })).toBe(100);
  });
});

describe("classifySample", () => {
  it("flags zero-audit entries as none", () => {
    expect(classifySample({ favCount: 0, unfavCount: 0 })).toBe("none");
  });

  it("flags <5 settled audits as small", () => {
    expect(classifySample({ favCount: 2, unfavCount: 0 })).toBe("small");
    expect(classifySample({ favCount: 4, unfavCount: 0 })).toBe("small");
  });

  it("flags 5..9 as modest", () => {
    expect(classifySample({ favCount: 5, unfavCount: 0 })).toBe("modest");
    expect(classifySample({ favCount: 5, unfavCount: 4 })).toBe("modest");
  });

  it("flags >=10 as reliable", () => {
    expect(classifySample({ favCount: 7, unfavCount: 3 })).toBe("reliable");
    expect(classifySample({ favCount: 130, unfavCount: 70 })).toBe("reliable");
  });
});

describe("winRateLowerBound", () => {
  it("returns 0 on empty samples", () => {
    expect(winRateLowerBound({ favCount: 0, unfavCount: 0 })).toBe(0);
  });

  it("never returns negative", () => {
    expect(winRateLowerBound({ favCount: 0, unfavCount: 100 })).toBeGreaterThanOrEqual(0);
  });

  it("ranks a 130/70 sample above a noisy 2/0 sample (the marquee finding)", () => {
    const big = winRateLowerBound({ favCount: 130, unfavCount: 70 });
    const small = winRateLowerBound({ favCount: 2, unfavCount: 0 });
    expect(big).toBeGreaterThan(small);
  });

  it("ranks a 200/100 sample (66.7%) above a 70/30 sample (70%) once shrinkage applies", () => {
    const high = winRateLowerBound({ favCount: 200, unfavCount: 100 });
    const low = winRateLowerBound({ favCount: 7, unfavCount: 3 });
    expect(high).toBeGreaterThan(low);
  });

  it("matches the Wilson 95% formula on a known sample", () => {
    const lb = winRateLowerBound({ favCount: 50, unfavCount: 50 });
    expect(lb).toBeGreaterThan(0.39);
    expect(lb).toBeLessThan(0.41);
  });

  it("is monotonic when adding wins to the same total", () => {
    const a = winRateLowerBound({ favCount: 6, unfavCount: 4 });
    const b = winRateLowerBound({ favCount: 7, unfavCount: 3 });
    expect(b).toBeGreaterThan(a);
  });
});

describe("meetsMinAudits", () => {
  it("treats a min of 0 as no filter", () => {
    expect(meetsMinAudits({ favCount: 0, unfavCount: 0 }, 0)).toBe(true);
    expect(meetsMinAudits({ favCount: 1, unfavCount: 0 }, 0)).toBe(true);
  });

  it("requires sample size >= min when min > 0", () => {
    expect(meetsMinAudits({ favCount: 4, unfavCount: 0 }, 5)).toBe(false);
    expect(meetsMinAudits({ favCount: 5, unfavCount: 0 }, 5)).toBe(true);
    expect(meetsMinAudits({ favCount: 7, unfavCount: 3 }, 10)).toBe(true);
  });
});

describe("constants", () => {
  it("defaults are calibrated for the leaderboard fix", () => {
    expect(WIN_RATE_MIN_AUDITS_DEFAULT).toBe(10);
    expect(WIN_RATE_SMALL_SAMPLE_THRESHOLD).toBe(5);
  });
});
