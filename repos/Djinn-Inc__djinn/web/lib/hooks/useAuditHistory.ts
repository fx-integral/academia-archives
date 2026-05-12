"use client";

import { useCallback, useMemo } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { getReadProvider } from "../hooks";
import { getAuditsByGenius, getAuditsByIdiot } from "../events";
import type { AuditEvent } from "../events";

const AUDIT_POLL_MS = 30_000;
const GENIUS_AUDIT_KEY = (geniusAddress?: string) => ["audit-history-genius", geniusAddress ?? "none"] as const;
const IDIOT_AUDIT_KEY = (idiotAddress?: string) => ["audit-history-idiot", idiotAddress ?? "none"] as const;

export function useAuditHistory(geniusAddress?: string) {
  const queryClient = useQueryClient();
  const key = GENIUS_AUDIT_KEY(geniusAddress);

  const query = useQuery({
    queryKey: key,
    queryFn: async () => {
      const provider = getReadProvider();
      return getAuditsByGenius(provider, geniusAddress!);
    },
    enabled: Boolean(geniusAddress),
    refetchInterval: AUDIT_POLL_MS,
    refetchIntervalInBackground: false,
    staleTime: AUDIT_POLL_MS / 2,
  });

  const audits = useMemo<AuditEvent[]>(() => query.data ?? [], [query.data]);
  const error =
    query.error instanceof Error
      ? query.error.message
      : query.error
        ? "Failed to fetch audit history"
        : null;

  const refresh = useCallback(
    () => queryClient.invalidateQueries({ queryKey: key }),
    [queryClient, key],
  );

  const aggregateQualityScore = useMemo(
    () =>
      Number(audits.reduce((sum, a) => sum + a.qualityScore, 0n)) / 1e6,
    [audits],
  );

  return {
    audits,
    loading: Boolean(geniusAddress) && query.isPending,
    error,
    refresh,
    aggregateQualityScore,
  };
}

export function useIdiotAuditHistory(idiotAddress?: string) {
  const queryClient = useQueryClient();
  const key = IDIOT_AUDIT_KEY(idiotAddress);

  const query = useQuery({
    queryKey: key,
    queryFn: async () => {
      const provider = getReadProvider();
      return getAuditsByIdiot(provider, idiotAddress!);
    },
    enabled: Boolean(idiotAddress),
    refetchInterval: AUDIT_POLL_MS,
    refetchIntervalInBackground: false,
    staleTime: AUDIT_POLL_MS / 2,
  });

  const audits = useMemo<AuditEvent[]>(() => query.data ?? [], [query.data]);
  const error =
    query.error instanceof Error
      ? query.error.message
      : query.error
        ? "Failed to fetch audit history"
        : null;

  const refresh = useCallback(
    () => queryClient.invalidateQueries({ queryKey: key }),
    [queryClient, key],
  );

  return {
    audits,
    loading: Boolean(idiotAddress) && query.isPending,
    error,
    refresh,
  };
}
