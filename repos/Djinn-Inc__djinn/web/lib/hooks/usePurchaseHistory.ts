"use client";

import { useCallback, useMemo } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { getReadProvider } from "../hooks";
import { getPurchasesByBuyer } from "../events";
import type { PurchaseEvent } from "../events";

const PURCHASE_POLL_MS = 30_000;
const PURCHASE_KEY = (buyerAddress?: string) => ["purchase-history", buyerAddress ?? "none"] as const;

export function usePurchaseHistory(buyerAddress?: string) {
  const queryClient = useQueryClient();
  const key = PURCHASE_KEY(buyerAddress);

  const query = useQuery({
    queryKey: key,
    queryFn: async () => {
      const provider = getReadProvider();
      return getPurchasesByBuyer(provider, buyerAddress!);
    },
    enabled: Boolean(buyerAddress),
    refetchInterval: PURCHASE_POLL_MS,
    refetchIntervalInBackground: false,
    staleTime: PURCHASE_POLL_MS / 2,
  });

  const purchases = useMemo<PurchaseEvent[]>(() => query.data ?? [], [query.data]);
  const error =
    query.error instanceof Error
      ? query.error.message
      : query.error
        ? "Failed to fetch purchases"
        : null;

  const refresh = useCallback(
    () => queryClient.invalidateQueries({ queryKey: key }),
    [queryClient, key],
  );

  return {
    purchases,
    loading: Boolean(buyerAddress) && query.isPending,
    error,
    refresh,
  };
}
