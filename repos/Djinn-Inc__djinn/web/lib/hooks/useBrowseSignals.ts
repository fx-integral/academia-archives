"use client";

import { useCallback, useMemo } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import type { SignalEvent } from "../events";
import { fetchFromAnyValidator } from "../api";

const POLL_INTERVAL_MS = 30_000;
const BROWSE_KEY = (sport?: string) => ["idiot-browse", sport ?? "all"] as const;

async function fetchBrowseSignals(sport: string | undefined, bustCache: boolean): Promise<SignalEvent[]> {
  const params = new URLSearchParams();
  if (sport) params.set("sport", sport);
  params.set("limit", "100");
  if (bustCache) params.set("bust", "1");

  const res = await fetchFromAnyValidator(`/v1/idiot/browse?${params}`);
  if (!res.ok) {
    throw new Error(`Browse API returned ${res.status}`);
  }
  const ct = res.headers.get("content-type") ?? "";
  if (!ct.includes("application/json")) {
    throw new Error(`Browse API returned non-JSON (${ct})`);
  }
  const data = await res.json();

  return (data.signals ?? []).map((s: Record<string, unknown>) => ({
    signalId: String(s.signal_id),
    genius: String(s.genius),
    sport: String(s.sport),
    maxPriceBps: BigInt(s.fee_bps as number),
    slaMultiplierBps: BigInt(s.sla_multiplier_bps as number),
    maxNotional: BigInt((s.max_notional as string) || "0"),
    minNotional: BigInt((s.min_notional as string) || "0"),
    expiresAt: BigInt((s.expires_at_unix as number) || 0),
    blockNumber: 0,
  }));
}

export function useBrowseSignals(sport?: string) {
  const queryClient = useQueryClient();
  const key = BROWSE_KEY(sport);

  const query = useQuery({
    queryKey: key,
    queryFn: () => fetchBrowseSignals(sport, false),
    refetchInterval: POLL_INTERVAL_MS,
    refetchIntervalInBackground: false,
    staleTime: POLL_INTERVAL_MS / 2,
  });

  const signals = useMemo(() => query.data ?? [], [query.data]);
  const error =
    query.error instanceof Error
      ? query.error.message
      : query.error
        ? "Failed to fetch signals"
        : null;

  const refresh = useCallback(
    () => queryClient.invalidateQueries({ queryKey: key }),
    [queryClient, key],
  );

  const forceRefresh = useCallback(async () => {
    const fresh = await fetchBrowseSignals(sport, true);
    queryClient.setQueryData(key, fresh);
  }, [queryClient, key, sport]);

  return { signals, loading: query.isPending, error, refresh, forceRefresh };
}
