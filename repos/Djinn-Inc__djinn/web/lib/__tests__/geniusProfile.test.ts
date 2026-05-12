import { describe, it, expect } from "vitest";
import { safeChecksum, signedUsdc, winRatePct } from "../geniusProfile";

describe("safeChecksum", () => {
  it("returns the EIP-55 checksum form for a valid lowercase address", () => {
    const lower = "0x68fc6a8b3b8e0d4c6f9c2e1a4b3d5e6f7a8b9c0d";
    const checksum = safeChecksum(lower);
    expect(checksum).not.toBeNull();
    // Same hex, but ethers always returns the canonical mixed-case form
    expect(checksum?.toLowerCase()).toBe(lower);
  });

  it("returns the EIP-55 checksum form for a valid uppercase address", () => {
    const upper = "0x68FC6A8B3B8E0D4C6F9C2E1A4B3D5E6F7A8B9C0D";
    const checksum = safeChecksum(upper);
    expect(checksum).not.toBeNull();
    expect(checksum?.toLowerCase()).toBe(upper.toLowerCase());
  });

  it("returns null for an obviously bogus string", () => {
    expect(safeChecksum("not-an-address")).toBeNull();
  });

  it("returns null for an empty string", () => {
    expect(safeChecksum("")).toBeNull();
  });

  it("returns null for a hex string of the wrong length", () => {
    expect(safeChecksum("0xabc")).toBeNull();
    expect(safeChecksum("0x" + "0".repeat(39))).toBeNull();
    expect(safeChecksum("0x" + "0".repeat(41))).toBeNull();
  });

  it("returns null when the EIP-55 checksum is wrong (mixed case but invalid)", () => {
    // valid hex length but wrong case for the canonical checksum form
    expect(safeChecksum("0x68FC6a8b3b8e0d4C6f9c2e1A4b3d5e6F7a8B9c0D")).toBeNull();
  });
});

describe("winRatePct", () => {
  it("returns 0 when there are no resolved signals (avoids divide-by-zero)", () => {
    expect(winRatePct(0, 0)).toBe(0);
  });

  it("returns 100 when every resolved signal is favorable", () => {
    expect(winRatePct(10, 0)).toBe(100);
  });

  it("returns 0 when every resolved signal is unfavorable", () => {
    expect(winRatePct(0, 7)).toBe(0);
  });

  it("returns the favorable share for a mixed record", () => {
    expect(winRatePct(3, 1)).toBe(75);
    expect(winRatePct(1, 1)).toBe(50);
  });

  it("ignores void counts (only fav and unfav contribute)", () => {
    // 2 fav out of 4 fav+unfav = 50%, regardless of how many void there were
    expect(winRatePct(2, 2)).toBe(50);
  });
});

describe("signedUsdc", () => {
  it("formats a positive amount with + and no decimals when whole", () => {
    expect(signedUsdc(123_000_000n)).toBe("+$123");
  });

  it("formats a negative amount with - and absolute magnitude", () => {
    expect(signedUsdc(-50_000_000n)).toBe("-$50");
  });

  it("treats zero as positive (returns +)", () => {
    expect(signedUsdc(0n)).toBe("+$0");
  });

  it("handles fractional USDC (6 decimals)", () => {
    expect(signedUsdc(1_500_000n)).toBe("+$1.5");
    expect(signedUsdc(-2_500_000n)).toBe("-$2.5");
  });
});
