"use client";

import { useCallback, useEffect, useMemo, useRef } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ethers } from "ethers";
import { getReadProvider } from "../hooks";
import { getAuditsByGenius, getAuditsByIdiot, resolveDeployBlock, queryFilterChunked } from "../events";
import {
  ADDRESSES,
  ACCOUNT_ABI,
  AUDIT_ABI,
  getAccountContract,
  detectContractVersion,
  type ContractVersion,
} from "../contracts";

const RELATIONSHIPS_POLL_MS = 60_000;
const EVENT_REFRESH_DEBOUNCE_MS = 300;
const RELATIONSHIPS_KEY = (address?: string, role?: string) =>
  ["active-relationships", address ?? "none", role ?? "genius"] as const;

export interface ActiveRelationship {
  genius: string;
  idiot: string;
  signalCount: number;
  qualityScore: number;
  currentCycle: number;
  isAuditReady: boolean;
  resolvedCount?: number;
  auditedCount?: number;
  contractVersion: ContractVersion;
}

async function fetchRelationships(
  address: string,
  role: "genius" | "idiot",
): Promise<ActiveRelationship[]> {
  const provider = getReadProvider();
  const counterparties = new Set<string>();

  await Promise.allSettled([
    (async () => {
      const contract = new ethers.Contract(ADDRESSES.account!, ACCOUNT_ABI, provider);
      const fromBlock = await resolveDeployBlock(provider);
      const filter = role === "genius"
        ? contract.filters.PurchaseRecorded(address)
        : contract.filters.PurchaseRecorded(null, address);
      const events = await queryFilterChunked(contract, filter, fromBlock);
      for (const event of events) {
        const log = event as ethers.EventLog;
        if (!log.args) continue;
        const other = role === "genius" ? log.args[1] : log.args[0];
        if (other && typeof other === "string") counterparties.add(other.toLowerCase());
      }
    })(),
    (async () => {
      const audits = role === "genius"
        ? await getAuditsByGenius(provider, address)
        : await getAuditsByIdiot(provider, address);
      for (const a of audits) {
        const other = role === "genius" ? a.idiot : a.genius;
        counterparties.add(other.toLowerCase());
      }
    })(),
  ]);

  if (counterparties.size === 0) return [];

  const version = await detectContractVersion(provider);
  const accountContract = getAccountContract(provider);
  const cpArray = Array.from(counterparties).slice(0, 50);
  const BATCH = 10;
  const results: PromiseSettledResult<ActiveRelationship | null>[] = [];

  for (let i = 0; i < cpArray.length; i += BATCH) {
    const batch = cpArray.slice(i, i + BATCH);
    const batchResults = await Promise.allSettled(
      batch.map(async (cp) => {
        const genius = role === "genius" ? address : cp;
        const idiot = role === "genius" ? cp : address;

        if (version === 2) {
          const qs = await accountContract.getQueueState(genius, idiot);
          const totalPurchases = Number(qs.totalPurchases);
          if (totalPurchases > 0) {
            const resolved = Number(qs.resolvedCount);
            const audited = Number(qs.auditedCount);
            const batchCount = Number(qs.auditBatchCount);
            return {
              genius,
              idiot,
              signalCount: totalPurchases,
              qualityScore: 0,
              currentCycle: batchCount,
              isAuditReady: (resolved - audited) >= 10,
              resolvedCount: resolved,
              auditedCount: audited,
              contractVersion: 2,
            } as ActiveRelationship;
          }
          return null;
        }

        const state = await accountContract.getAccountState(genius, idiot);
        const signalCount = Number(state.signalCount);
        if (signalCount > 0) {
          return {
            genius,
            idiot,
            signalCount,
            qualityScore: Number(state.outcomeBalance) / 1e6,
            currentCycle: Number(state.currentCycle),
            isAuditReady: signalCount >= 10,
            contractVersion: 1,
          } as ActiveRelationship;
        }
        return null;
      }),
    );
    results.push(...batchResults);
  }

  return results
    .filter((r): r is PromiseFulfilledResult<ActiveRelationship | null> => r.status === "fulfilled")
    .map((r) => r.value)
    .filter((r): r is ActiveRelationship => r !== null)
    .sort((a, b) => b.signalCount - a.signalCount);
}

export function useActiveRelationships(
  address?: string,
  role: "genius" | "idiot" = "genius",
) {
  const queryClient = useQueryClient();
  const key = useMemo(() => RELATIONSHIPS_KEY(address, role), [address, role]);

  const query = useQuery({
    queryKey: key,
    queryFn: () => fetchRelationships(address!, role),
    enabled: Boolean(address && ADDRESSES.account),
    refetchInterval: RELATIONSHIPS_POLL_MS,
    refetchIntervalInBackground: false,
    staleTime: RELATIONSHIPS_POLL_MS / 2,
  });

  const relationships = useMemo<ActiveRelationship[]>(() => query.data ?? [], [query.data]);
  const error =
    query.error instanceof Error
      ? query.error.message
      : query.error
        ? "Failed to load relationships"
        : null;

  const refresh = useCallback(
    () => queryClient.invalidateQueries({ queryKey: key }),
    [queryClient, key],
  );

  const refreshTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    if (!address || !ADDRESSES.account || !ADDRESSES.audit) return;

    let purchaseContract: ethers.Contract | null = null;
    let auditContract: ethers.Contract | null = null;

    const debouncedRefresh = () => {
      if (refreshTimerRef.current) clearTimeout(refreshTimerRef.current);
      refreshTimerRef.current = setTimeout(() => {
        refreshTimerRef.current = null;
        queryClient.invalidateQueries({ queryKey: key });
      }, EVENT_REFRESH_DEBOUNCE_MS);
    };

    try {
      const provider = getReadProvider();

      purchaseContract = new ethers.Contract(ADDRESSES.account, ACCOUNT_ABI, provider);
      const purchaseFilter = role === "genius"
        ? purchaseContract.filters.PurchaseRecorded(address)
        : purchaseContract.filters.PurchaseRecorded(null, address);
      purchaseContract.on(purchaseFilter, debouncedRefresh);

      auditContract = new ethers.Contract(ADDRESSES.audit, AUDIT_ABI, provider);
      const auditFilter = role === "genius"
        ? auditContract.filters.AuditSettled(address)
        : auditContract.filters.AuditSettled(null, address);
      const earlyExitFilter = role === "genius"
        ? auditContract.filters.EarlyExitSettled(address)
        : auditContract.filters.EarlyExitSettled(null, address);
      auditContract.on(auditFilter, debouncedRefresh);
      auditContract.on(earlyExitFilter, debouncedRefresh);
    } catch (err) {
      console.warn("[useActiveRelationships] event subscribe failed", err);
    }

    return () => {
      if (refreshTimerRef.current) clearTimeout(refreshTimerRef.current);
      try {
        purchaseContract?.removeAllListeners();
        auditContract?.removeAllListeners();
      } catch {
        // Listener cleanup errors are non-fatal; provider teardown is idempotent
      }
    };
  }, [address, role, queryClient, key]);

  return { relationships, loading: query.isPending, error, refresh };
}
