import { describe, it, expect } from "vitest";
import {
  SignalStatus,
  Outcome,
  formatUsdc,
  parseUsdc,
  formatBps,
  truncateAddress,
  signalStatusLabel,
  outcomeLabel,
} from "../types";

describe("SignalStatus enum", () => {
  it("has correct numeric values", () => {
    expect(SignalStatus.Active).toBe(0);
    expect(SignalStatus.Cancelled).toBe(1);
    expect(SignalStatus.Settled).toBe(2);
  });
});

describe("Outcome enum", () => {
  it("has correct numeric values", () => {
    expect(Outcome.Pending).toBe(0);
    expect(Outcome.Favorable).toBe(1);
    expect(Outcome.Unfavorable).toBe(2);
    expect(Outcome.Void).toBe(3);
  });
});

describe("formatUsdc", () => {
  it("formats whole USDC amounts without trailing decimals", () => {
    expect(formatUsdc(1_000_000n)).toBe("1");
    expect(formatUsdc(100_000_000n)).toBe("100");
    expect(formatUsdc(0n)).toBe("0");
  });

  it("formats fractional USDC amounts correctly", () => {
    expect(formatUsdc(1_500_000n)).toBe("1.5");
    expect(formatUsdc(1_230_000n)).toBe("1.23");
    expect(formatUsdc(1_000_001n)).toBe("1.000001");
  });

  it("formats sub-dollar amounts", () => {
    expect(formatUsdc(500_000n)).toBe("0.5");
    expect(formatUsdc(1n)).toBe("0.000001");
    expect(formatUsdc(10n)).toBe("0.00001");
  });

  it("handles large amounts", () => {
    expect(formatUsdc(1_000_000_000_000n)).toBe("1,000,000");
  });
});

describe("parseUsdc", () => {
  it("parses whole amounts", () => {
    expect(parseUsdc("1")).toBe(1_000_000n);
    expect(parseUsdc("100")).toBe(100_000_000n);
    expect(parseUsdc("0")).toBe(0n);
  });

  it("parses fractional amounts", () => {
    expect(parseUsdc("1.5")).toBe(1_500_000n);
    expect(parseUsdc("1.23")).toBe(1_230_000n);
    expect(parseUsdc("1.000001")).toBe(1_000_001n);
  });

  it("truncates beyond 6 decimal places", () => {
    expect(parseUsdc("1.1234567")).toBe(1_123_456n);
  });

  it("handles sub-dollar amounts", () => {
    expect(parseUsdc("0.5")).toBe(500_000n);
    expect(parseUsdc("0.000001")).toBe(1n);
  });

  it("roundtrips with formatUsdc", () => {
    const values = ["1", "100", "0.5", "1.23", "0.000001"];
    for (const v of values) {
      expect(formatUsdc(parseUsdc(v))).toBe(v);
    }
  });

  it("rejects empty string", () => {
    expect(() => parseUsdc("")).toThrow("Invalid USDC amount");
  });

  it("rejects non-numeric input", () => {
    expect(() => parseUsdc("abc")).toThrow("Invalid USDC amount");
  });

  it("rejects negative amounts", () => {
    expect(() => parseUsdc("-1")).toThrow("Invalid USDC amount");
  });

  it("trims whitespace before parsing", () => {
    expect(parseUsdc("  1.5  ")).toBe(1_500_000n);
  });
});

describe("formatBps", () => {
  it("converts basis points to percentage", () => {
    expect(formatBps(500n)).toBe("5%");
    expect(formatBps(100n)).toBe("1%");
    expect(formatBps(10000n)).toBe("100%");
    expect(formatBps(0n)).toBe("0%");
  });

  it("handles fractional percentages", () => {
    expect(formatBps(50n)).toBe("0.5%");
    expect(formatBps(1n)).toBe("0.01%");
    expect(formatBps(250n)).toBe("2.5%");
  });
});

describe("truncateAddress", () => {
  it("truncates a standard Ethereum address", () => {
    expect(truncateAddress("0x1234567890abcdef1234567890abcdef12345678")).toBe(
      "0x1234...5678"
    );
  });

  it("preserves the first 6 and last 4 characters", () => {
    const addr = "0xAbCdEf0123456789AbCdEf0123456789AbCdEf01";
    const result = truncateAddress(addr);
    expect(result.startsWith("0xAbCd")).toBe(true);
    expect(result.endsWith("Ef01")).toBe(true);
    expect(result).toContain("...");
  });
});

describe("signalStatusLabel", () => {
  it("returns correct label for each status", () => {
    expect(signalStatusLabel(SignalStatus.Active)).toBe("Active");
    expect(signalStatusLabel(SignalStatus.Cancelled)).toBe("Cancelled");
    expect(signalStatusLabel(SignalStatus.Settled)).toBe("Settled");
  });
});

describe("outcomeLabel", () => {
  it("returns correct label for each outcome", () => {
    expect(outcomeLabel(Outcome.Pending)).toBe("Pending");
    expect(outcomeLabel(Outcome.Favorable)).toBe("Favorable");
    expect(outcomeLabel(Outcome.Unfavorable)).toBe("Unfavorable");
    expect(outcomeLabel(Outcome.Void)).toBe("Void");
  });
});
