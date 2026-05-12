import type { GeniusLeaderboardEntry } from "./types";

export type LeaderboardPhase = "preAudit" | "active";

export interface LeaderboardStatus {
  phase: LeaderboardPhase;
  hasAnyAudits: boolean;
  hasAnyEntries: boolean;
}

export function leaderboardStatus(
  entries: ReadonlyArray<GeniusLeaderboardEntry>,
): LeaderboardStatus {
  const hasAnyEntries = entries.length > 0;
  const hasAnyAudits = entries.some((e) => e.auditCount > 0);
  return {
    phase: hasAnyAudits ? "active" : "preAudit",
    hasAnyAudits,
    hasAnyEntries,
  };
}
