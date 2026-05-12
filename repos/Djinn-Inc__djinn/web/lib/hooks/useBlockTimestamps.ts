"use client";

import { useMemo } from "react";
import { useQueries } from "@tanstack/react-query";
import { getReadProvider } from "../hooks";
import { dedupeBlockNumbers } from "../blockTime";

const TIMESTAMP_KEY = (blockNumber: number) =>
  ["block-timestamp", blockNumber] as const;

/**
 * Fetch unix timestamps (seconds) for a set of block numbers via
 * `eth_getBlockByNumber`. Block timestamps are immutable, so each query is
 * cached forever (no refetch, no retries that double-charge the RPC).
 *
 * Returns a Map from blockNumber to timestamp in seconds. Missing entries mean
 * the call is still pending or the RPC failed; callers should fall back to
 * the raw block number label in that case.
 */
export function useBlockTimestamps(
  blockNumbers: readonly number[] | undefined,
): { timestamps: Map<number, number>; loading: boolean } {
  const ordered = useMemo(
    () => dedupeBlockNumbers(blockNumbers ?? []),
    [blockNumbers],
  );

  const queries = useQueries({
    queries: ordered.map((blockNumber) => ({
      queryKey: TIMESTAMP_KEY(blockNumber),
      queryFn: async (): Promise<number> => {
        const provider = getReadProvider();
        const block = await provider.getBlock(blockNumber);
        if (!block) throw new Error(`Block ${blockNumber} not found`);
        return Number(block.timestamp);
      },
      staleTime: Infinity,
      gcTime: Infinity,
      retry: 1,
    })),
  });

  const timestamps = useMemo(() => {
    const map = new Map<number, number>();
    ordered.forEach((blockNumber, i) => {
      const data = queries[i]?.data;
      if (typeof data === "number" && data > 0) {
        map.set(blockNumber, data);
      }
    });
    return map;
  }, [ordered, queries]);

  const loading = queries.some((q) => q.isPending);

  return { timestamps, loading };
}
