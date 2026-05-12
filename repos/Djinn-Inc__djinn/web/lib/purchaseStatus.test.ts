import { describe, expect, it } from "vitest";
import {
  buildSignalLookup,
  purchaseStatusClasses,
  resolvePurchaseStatus,
} from "./purchaseStatus";
import type { AuditEvent, SignalEvent } from "./events";

const signal = (overrides: Partial<SignalEvent> = {}): SignalEvent => ({
  signalId: "1",
  genius: "0xabc",
  sport: "NFL",
  maxPriceBps: 0n,
  slaMultiplierBps: 0n,
  maxNotional: 0n,
  minNotional: 0n,
  expiresAt: 9_999_999_999n,
  blockNumber: 100,
  ...overrides,
});

const audit = (overrides: Partial<AuditEvent> = {}): AuditEvent => ({
  genius: "0xabc",
  idiot: "0x123",
  cycle: 1n,
  qualityScore: 100n,
  trancheA: 0n,
  trancheB: 0n,
  protocolFee: 0n,
  isEarlyExit: false,
  blockNumber: 200,
  ...overrides,
});

describe("resolvePurchaseStatus", () => {
  it("returns Active when signal is alive and no covering audit", () => {
    const status = resolvePurchaseStatus({ signalId: "1", blockNumber: 100 }, signal(), [], 1000n);
    expect(status.kind).toBe("active");
    expect(status.label).toBe("Active");
    expect(status.tone).toBe("sky");
  });

  it("returns Expired when expiresAt has passed and no audit", () => {
    const status = resolvePurchaseStatus(
      { signalId: "1", blockNumber: 100 },
      signal({ expiresAt: 999n }),
      [],
      1000n,
    );
    expect(status.kind).toBe("expired");
    expect(status.tone).toBe("slate");
  });

  it("returns Pending when signal is unknown and no audit", () => {
    const status = resolvePurchaseStatus(
      { signalId: "1", blockNumber: 100 },
      undefined,
      [],
      1000n,
    );
    expect(status.kind).toBe("pending");
    expect(status.label).toBe("Pending");
  });

  it("matches a covering audit and reports settled-favorable on non-negative qualityScore", () => {
    const status = resolvePurchaseStatus(
      { signalId: "1", blockNumber: 100 },
      signal(),
      [audit({ blockNumber: 200, qualityScore: 50n })],
      1000n,
    );
    expect(status.kind).toBe("settled-favorable");
    expect(status.tone).toBe("green");
    expect(status.label).toBe("Favorable");
  });

  it("returns settled-unfavorable when qualityScore is negative", () => {
    const status = resolvePurchaseStatus(
      { signalId: "1", blockNumber: 100 },
      signal(),
      [audit({ qualityScore: -50n })],
      1000n,
    );
    expect(status.kind).toBe("settled-unfavorable");
    expect(status.tone).toBe("red");
  });

  it("returns early-exit when audit isEarlyExit overrides quality sign", () => {
    const status = resolvePurchaseStatus(
      { signalId: "1", blockNumber: 100 },
      signal(),
      [audit({ isEarlyExit: true, qualityScore: -1n })],
      1000n,
    );
    expect(status.kind).toBe("early-exit");
    expect(status.tone).toBe("amber");
  });

  it("ignores audits at or before the purchase block", () => {
    const status = resolvePurchaseStatus(
      { signalId: "1", blockNumber: 200 },
      signal(),
      [audit({ blockNumber: 100 }), audit({ blockNumber: 200 })],
      1000n,
    );
    expect(status.kind).toBe("active");
  });

  it("ignores audits for a different genius", () => {
    const status = resolvePurchaseStatus(
      { signalId: "1", blockNumber: 100 },
      signal({ genius: "0xabc" }),
      [audit({ genius: "0xdef", blockNumber: 200 })],
      1000n,
    );
    expect(status.kind).toBe("active");
  });

  it("matches case-insensitively on genius address", () => {
    const status = resolvePurchaseStatus(
      { signalId: "1", blockNumber: 100 },
      signal({ genius: "0xABC" }),
      [audit({ genius: "0xabc", blockNumber: 200 })],
      1000n,
    );
    expect(status.kind).toBe("settled-favorable");
  });

  it("picks the earliest covering audit when multiple cycles exist", () => {
    const status = resolvePurchaseStatus(
      { signalId: "1", blockNumber: 100 },
      signal(),
      [
        audit({ blockNumber: 300, qualityScore: -50n, cycle: 2n }),
        audit({ blockNumber: 200, qualityScore: 50n, cycle: 1n }),
      ],
      1000n,
    );
    expect(status.kind).toBe("settled-favorable");
  });

  it("treats qualityScore=0 as favorable (non-negative)", () => {
    const status = resolvePurchaseStatus(
      { signalId: "1", blockNumber: 100 },
      signal(),
      [audit({ qualityScore: 0n })],
      1000n,
    );
    expect(status.kind).toBe("settled-favorable");
  });
});

describe("buildSignalLookup", () => {
  it("maps signalId to SignalEvent", () => {
    const m = buildSignalLookup([signal({ signalId: "a" }), signal({ signalId: "b" })]);
    expect(m.get("a")?.signalId).toBe("a");
    expect(m.get("b")?.signalId).toBe("b");
    expect(m.size).toBe(2);
  });

  it("returns empty map for empty input", () => {
    expect(buildSignalLookup([]).size).toBe(0);
  });
});

describe("purchaseStatusClasses", () => {
  it("returns sky classes for active status", () => {
    const classes = purchaseStatusClasses(
      resolvePurchaseStatus({ signalId: "1", blockNumber: 100 }, signal(), [], 1000n),
    );
    expect(classes).toContain("sky");
  });

  it("returns green classes for settled-favorable", () => {
    const classes = purchaseStatusClasses(
      resolvePurchaseStatus({ signalId: "1", blockNumber: 100 }, signal(), [audit()], 1000n),
    );
    expect(classes).toContain("green");
  });

  it("returns red classes for settled-unfavorable", () => {
    const classes = purchaseStatusClasses(
      resolvePurchaseStatus(
        { signalId: "1", blockNumber: 100 },
        signal(),
        [audit({ qualityScore: -1n })],
        1000n,
      ),
    );
    expect(classes).toContain("red");
  });
});
