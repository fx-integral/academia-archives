"use client";

import { useEffect, useState } from "react";
import { fetchFromAnyValidator } from "@/lib/api";

interface Stats {
  validators: number;
  miners: number;
  shares: number;
}

const CACHE_KEY = "djinn:network_stats_v1";
const CACHE_TTL_MS = 7 * 24 * 60 * 60 * 1000;

interface CacheEntry {
  stats: Stats;
  fetchedAt: number;
}

function readCache(): Stats | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = window.localStorage.getItem(CACHE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as CacheEntry;
    if (!parsed?.stats || typeof parsed.fetchedAt !== "number") return null;
    if (Date.now() - parsed.fetchedAt > CACHE_TTL_MS) return null;
    return parsed.stats;
  } catch {
    return null;
  }
}

function writeCache(stats: Stats) {
  if (typeof window === "undefined") return;
  try {
    const entry: CacheEntry = { stats, fetchedAt: Date.now() };
    window.localStorage.setItem(CACHE_KEY, JSON.stringify(entry));
  } catch {
    // Quota / private mode; the cache is decorative.
  }
}

export function NetworkStats() {
  const [stats, setStats] = useState<Stats | null>(null);
  const [stale, setStale] = useState(false);

  useEffect(() => {
    let cancelled = false;
    const cached = readCache();
    if (cached) {
      setStats(cached);
      setStale(true);
    }
    async function load() {
      try {
        const res = await fetchFromAnyValidator("/v1/network/overview");
        if (!res.ok) return;
        const data = await res.json();
        if (cancelled || !data.summary) return;
        const next: Stats = {
          validators: data.summary.validatorsHealthy ?? data.summary.totalValidators ?? 0,
          miners: data.summary.totalMiners ?? 0,
          shares: data.summary.totalShares ?? 0,
        };
        setStats(next);
        setStale(false);
        writeCache(next);
      } catch {
        // Silent fail; we'll keep the cached value if any.
      }
    }
    load();
    return () => { cancelled = true; };
  }, []);

  if (!stats) {
    return (
      <div
        className="flex items-center justify-center text-center mb-10 sm:mb-14"
        aria-live="polite"
      >
        <span className="text-xs sm:text-sm text-slate-400">
          Live network stats unavailable.{" "}
          <a href="/network" className="underline hover:text-slate-600 transition-colors">
            View network status
          </a>
        </span>
      </div>
    );
  }

  const items = [
    { label: "Validators", value: stats.validators },
    { label: "Miners", value: stats.miners },
    { label: "Signals Tracked", value: stats.shares.toLocaleString() },
  ];

  return (
    <div
      className="flex items-center justify-center gap-6 sm:gap-10 text-center mb-10 sm:mb-14 motion-safe:animate-in motion-safe:fade-in motion-safe:duration-500"
      title={stale ? "Showing last known values; live network unreachable." : undefined}
    >
      {items.map((item) => (
        <div key={item.label} className="flex flex-col items-center">
          <span className="text-2xl sm:text-3xl font-bold text-slate-900 tabular-nums">
            {item.value}
          </span>
          <span className="text-xs sm:text-sm text-slate-400 mt-0.5">
            {item.label}
          </span>
        </div>
      ))}
    </div>
  );
}
