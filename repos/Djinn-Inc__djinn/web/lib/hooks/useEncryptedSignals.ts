"use client";

import { useCallback } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useAccount, useWalletClient } from "wagmi";
import {
  isMasterSeedCached,
  getCachedMasterSeed,
  deriveMasterSeedTyped,
} from "../crypto";
import {
  getSavedSignalsEncrypted,
  saveSavedSignalsEncrypted,
  type SavedSignalData,
} from "./useSettledSignals";

const ENCRYPTED_SIGNALS_KEY = (address?: string) =>
  ["encrypted-signals", address ?? "none"] as const;

interface UseEncryptedSignalsResult {
  signals: SavedSignalData[];
  loading: boolean;
  locked: boolean;
  seedReady: boolean;
  unlock: () => Promise<void>;
  save: (signals: SavedSignalData[]) => Promise<void>;
  refresh: () => Promise<void>;
}

type LoadedData = { signals: SavedSignalData[]; locked: boolean };

export function useEncryptedSignals(): UseEncryptedSignalsResult {
  const { address } = useAccount();
  const { data: walletClient } = useWalletClient();
  const queryClient = useQueryClient();
  const key = ENCRYPTED_SIGNALS_KEY(address);

  const query = useQuery<LoadedData>({
    queryKey: key,
    queryFn: async () => {
      const seed = getCachedMasterSeed();
      return getSavedSignalsEncrypted(address!, seed);
    },
    enabled: Boolean(address),
    staleTime: Infinity,
  });

  const signals = query.data?.signals ?? [];
  const locked = query.data?.locked ?? false;
  const seedReady = isMasterSeedCached();

  const refresh = useCallback(async () => {
    await queryClient.invalidateQueries({ queryKey: key });
  }, [queryClient, key]);

  const unlock = useCallback(async () => {
    if (!walletClient || !address) return;
    const seed = await deriveMasterSeedTyped((params) =>
      walletClient.signTypedData(params),
    );
    const result = await getSavedSignalsEncrypted(address, seed);
    queryClient.setQueryData<LoadedData>(key, result);
  }, [walletClient, address, queryClient, key]);

  const save = useCallback(
    async (newSignals: SavedSignalData[]) => {
      if (!address) return;
      const seed = getCachedMasterSeed();
      await saveSavedSignalsEncrypted(address, newSignals, seed);
      queryClient.setQueryData<LoadedData>(key, { signals: newSignals, locked: false });
    },
    [address, queryClient, key],
  );

  return {
    signals,
    loading: Boolean(address) && query.isPending,
    locked,
    seedReady,
    unlock,
    save,
    refresh,
  };
}
