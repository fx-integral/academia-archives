import { describe, it, expect } from "vitest";
import { leaderboardStatus } from "../leaderboardStatus";
import type { GeniusLeaderboardEntry } from "../types";

function makeEntry(
  partial: Partial<GeniusLeaderboardEntry> = {},
): GeniusLeaderboardEntry {
  return {
    address: "0x0000000000000000000000000000000000000001",
    qualityScore: 0,
    totalSignals: 0,
    auditCount: 0,
    roi: 0,
    proofCount: 0,
    favCount: 0,
    unfavCount: 0,
    voidCount: 0,
    ...partial,
  };
}

describe("leaderboardStatus", () => {
  it("reports preAudit + no entries when the list is empty", () => {
    const status = leaderboardStatus([]);
    expect(status.phase).toBe("preAudit");
    expect(status.hasAnyAudits).toBe(false);
    expect(status.hasAnyEntries).toBe(false);
  });

  it("reports preAudit when entries exist but none have audits", () => {
    const status = leaderboardStatus([
      makeEntry({ totalSignals: 1230 }),
      makeEntry({ totalSignals: 20 }),
    ]);
    expect(status.phase).toBe("preAudit");
    expect(status.hasAnyAudits).toBe(false);
    expect(status.hasAnyEntries).toBe(true);
  });

  it("reports active once at least one entry has a resolved audit", () => {
    const status = leaderboardStatus([
      makeEntry({ totalSignals: 1230 }),
      makeEntry({ totalSignals: 20, auditCount: 3 }),
    ]);
    expect(status.phase).toBe("active");
    expect(status.hasAnyAudits).toBe(true);
    expect(status.hasAnyEntries).toBe(true);
  });
});
