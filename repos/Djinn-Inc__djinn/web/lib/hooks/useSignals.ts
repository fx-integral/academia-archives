"use client";

import { useCallback, useMemo } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { getReadProvider } from "../hooks";
import { getActiveSignals, getSignalsByGenius, invalidateSignalCache } from "../events";
import type { SignalEvent } from "../events";
import { fetchFromAnyValidator } from "../api";

const POLL_INTERVAL_MS = 10_000;
const SIGNALS_KEY = (sport?: string, geniusAddress?: string, includeAll?: boolean) =>
  ["active-signals", sport ?? "all", geniusAddress ?? "none", includeAll ? "all" : "active"] as const;

function mapSignalRow(s: Record<string, unknown>): SignalEvent {
  return {
    signalId: String(s.signal_id ?? s.signalId ?? ""),
    genius: String(s.genius ?? ""),
    sport: String(s.sport ?? ""),
    maxPriceBps: BigInt(Number(s.fee_bps ?? s.maxPriceBps ?? 0)),
    slaMultiplierBps: BigInt(Number(s.sla_multiplier_bps ?? s.slaMultiplierBps ?? 0)),
    maxNotional: BigInt((s.max_notional as string) || String(s.maxNotional ?? "0")),
    minNotional: BigInt((s.min_notional as string) || String(s.minNotional ?? "0")),
    expiresAt: BigInt(Number(s.expires_at_unix ?? s.expiresAt ?? 0)),
    blockNumber: 0,
  };
}

async function fetchSignals(
  sport: string | undefined,
  geniusAddress: string | undefined,
  includeAll: boolean,
  bustCache: boolean,
): Promise<SignalEvent[]> {
  let result: SignalEvent[];

  if (geniusAddress) {
    try {
      const params = new URLSearchParams({ limit: "100" });
      if (includeAll) params.set("include_all", "1");
      if (bustCache) params.set("bust", "1");
      const res = await fetchFromAnyValidator(
        `/v1/genius/${geniusAddress}/signals?${params}`,
      );
      if (res.ok) {
        const ct = res.headers.get("content-type") ?? "";
        if (!ct.includes("application/json")) {
          throw new Error(`Non-JSON response (${ct})`);
        }
        const data = await res.json();
        result = (data.signals ?? []).map(mapSignalRow);
      } else {
        const provider = getReadProvider();
        result = await getSignalsByGenius(provider, geniusAddress, undefined, includeAll);
      }
    } catch {
      const provider = getReadProvider();
      result = await getSignalsByGenius(provider, geniusAddress, undefined, includeAll);
    }
  } else {
    try {
      const params = new URLSearchParams({ limit: "100" });
      if (sport) params.set("sport", sport);
      if (bustCache) params.set("bust", "1");
      const res = await fetchFromAnyValidator(`/v1/idiot/browse?${params}`);
      if (res.ok) {
        const ct = res.headers.get("content-type") ?? "";
        if (!ct.includes("application/json")) {
          throw new Error(`Non-JSON response (${ct})`);
        }
        const data = await res.json();
        result = (data.signals ?? []).map(mapSignalRow);
      } else {
        const provider = getReadProvider();
        result = await getActiveSignals(provider);
      }
    } catch {
      const provider = getReadProvider();
      result = await getActiveSignals(provider);
    }
  }

  if (sport) {
    result = result.filter((s) => s.sport === sport);
  }

  return result;
}

export function useActiveSignals(
  sport?: string,
  geniusAddress?: string,
  includeAll: boolean = false,
) {
  const queryClient = useQueryClient();
  const key = SIGNALS_KEY(sport, geniusAddress, includeAll);

  const query = useQuery({
    queryKey: key,
    queryFn: () => fetchSignals(sport, geniusAddress, includeAll, false),
    refetchInterval: POLL_INTERVAL_MS,
    refetchIntervalInBackground: false,
    staleTime: POLL_INTERVAL_MS / 2,
  });

  const signals = useMemo<SignalEvent[]>(() => query.data ?? [], [query.data]);
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
    invalidateSignalCache(geniusAddress);
    const fresh = await fetchSignals(sport, geniusAddress, includeAll, true);
    queryClient.setQueryData(key, fresh);
  }, [queryClient, key, sport, geniusAddress, includeAll]);

  return { signals, loading: query.isPending, error, refresh, forceRefresh };
}
