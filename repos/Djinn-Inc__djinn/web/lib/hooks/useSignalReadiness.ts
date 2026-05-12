"use client";

import { useQuery } from "@tanstack/react-query";
import { discoverValidatorClients } from "../api";

// Map signalId → readiness. "preparing" means we asked a validator and it
// reported no shares yet (still in the share-distribution window); "ready"
// means at least one validator confirmed it holds shares; "unknown" means
// we couldn't reach any validator or all probes errored. Treating "unknown"
// like "ready" — i.e., letting the listing render the card normally — so a
// transient network blip never blocks the marketplace UX.
export type SignalReadiness = "ready" | "preparing" | "unknown";

const READINESS_KEY = (signalIds: string[]) =>
  ["signal-readiness", [...signalIds].sort().join(",")] as const;
const POLL_INTERVAL_MS = 30_000;
const PROBE_TIMEOUT_MS = 4_000;

async function probeOne(
  baseUrl: string,
  signalId: string,
): Promise<boolean | null> {
  try {
    const res = await fetch(`${baseUrl}/v1/signal/${signalId}/status`, {
      signal: AbortSignal.timeout(PROBE_TIMEOUT_MS),
    });
    if (!res.ok) return null;
    const json = (await res.json()) as { has_shares?: boolean };
    return Boolean(json?.has_shares);
  } catch {
    return null;
  }
}

async function fetchReadiness(
  signalIds: string[],
): Promise<Map<string, SignalReadiness>> {
  const out = new Map<string, SignalReadiness>();
  if (signalIds.length === 0) return out;

  const validators = await discoverValidatorClients();
  if (validators.length === 0) {
    for (const id of signalIds) out.set(id, "unknown");
    return out;
  }

  // Round-robin signals across validators. We ask just one validator per
  // signal — that's enough to learn whether shares are recoverable since
  // any single validator with shares means decryption can succeed (Shamir
  // threshold k=2, but the signal page collects from peers too). Probing
  // every validator for every signal would cost N×M HTTP calls for no
  // additional truth.
  await Promise.all(
    signalIds.map(async (signalId, i) => {
      const v = validators[i % validators.length];
      const has = await probeOne(v.baseUrl, signalId);
      if (has === null) out.set(signalId, "unknown");
      else out.set(signalId, has ? "ready" : "preparing");
    }),
  );
  return out;
}

export function useSignalReadiness(signalIds: string[]) {
  const query = useQuery({
    queryKey: READINESS_KEY(signalIds),
    queryFn: () => fetchReadiness(signalIds),
    enabled: signalIds.length > 0,
    refetchInterval: POLL_INTERVAL_MS,
    refetchIntervalInBackground: false,
    staleTime: POLL_INTERVAL_MS / 2,
  });

  return {
    readiness: query.data ?? new Map<string, SignalReadiness>(),
    loading: signalIds.length > 0 && query.isPending,
  };
}
