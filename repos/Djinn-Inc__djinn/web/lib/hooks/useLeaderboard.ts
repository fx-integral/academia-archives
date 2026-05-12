"use client";

import { useCallback, useMemo } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  fetchLeaderboard,
  isSubgraphConfigured,
  type SubgraphGeniusEntry,
} from "../subgraph";
import type { GeniusLeaderboardEntry } from "../types";

const LEADERBOARD_POLL_MS = 60_000;
const LEADERBOARD_KEY = ["leaderboard"] as const;
const LEADERBOARD_LIMIT = 100;

function toLeaderboardEntry(g: SubgraphGeniusEntry): GeniusLeaderboardEntry {
  const totalGain = Number(g.aggregateQualityScore) / 1e6;
  const totalVolume = Number(g.totalVolume) / 1e6;
  const roi = totalVolume > 0 ? (totalGain / totalVolume) * 100 : 0;

  return {
    address: g.id,
    qualityScore: totalGain,
    totalSignals: Number(g.totalSignals),
    auditCount: Number(g.totalAudits),
    roi,
    proofCount: 0,
    favCount: Number(g.totalFavorable || 0),
    unfavCount: Number(g.totalUnfavorable || 0),
    voidCount: Number(g.totalVoid || 0),
  };
}

async function fetchViaProxy(): Promise<SubgraphGeniusEntry[] | null> {
  try {
    const resp = await fetch(`/api/leaderboard?limit=${LEADERBOARD_LIMIT}`, {
      headers: { accept: "application/json" },
    });
    if (!resp.ok) return null;
    const json = (await resp.json()) as { geniuses?: SubgraphGeniusEntry[] };
    return json.geniuses ?? [];
  } catch {
    return null;
  }
}

export function useLeaderboard() {
  const configured = isSubgraphConfigured();
  const queryClient = useQueryClient();

  const query = useQuery({
    queryKey: LEADERBOARD_KEY,
    queryFn: async () => {
      const cached = await fetchViaProxy();
      const entries = cached ?? (await fetchLeaderboard(LEADERBOARD_LIMIT));
      return entries.map(toLeaderboardEntry);
    },
    enabled: configured,
    refetchInterval: LEADERBOARD_POLL_MS,
    refetchIntervalInBackground: false,
    staleTime: LEADERBOARD_POLL_MS / 2,
  });

  const refresh = useCallback(
    () => queryClient.invalidateQueries({ queryKey: LEADERBOARD_KEY }),
    [queryClient],
  );

  const data = useMemo(() => query.data ?? [], [query.data]);
  const error =
    query.error instanceof Error
      ? query.error.message
      : query.error
        ? "Failed to fetch leaderboard"
        : null;

  return {
    data,
    loading: configured && query.isPending,
    error,
    configured,
    refresh,
  };
}
