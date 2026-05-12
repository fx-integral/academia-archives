import { useCallback, useMemo, useState } from "react";

export type SortDir = "asc" | "desc";

export function formatTao(raw: string | number): string {
  const tao = typeof raw === "string" ? parseFloat(raw) : raw;
  if (!isFinite(tao)) return "-";
  if (tao >= 1_000_000) return `${(tao / 1_000_000).toFixed(2)}M`;
  if (tao >= 1_000) return `${(tao / 1_000).toFixed(1)}k`;
  if (tao >= 1) return tao.toFixed(1);
  return tao.toFixed(4);
}

export function normalizedToPercent(val: number): string {
  if (!isFinite(val)) return "-";
  return (val * 100).toFixed(2) + "%";
}

// Relative-time formatter for /health.git_commit_ts. Caller passes the
// commit's unix-epoch seconds; we emit a compact string like "<1m ago"
// / "12m ago" / "4h ago" / "3d ago". Returns "unknown" for null/missing
// values (non-git installs publish git_commit_ts=null).
export function formatRelativeAge(epochSeconds: number | null | undefined, nowMs: number = Date.now()): string {
  if (epochSeconds == null || !isFinite(epochSeconds)) return "unknown";
  const ageS = Math.max(0, Math.floor(nowMs / 1000 - epochSeconds));
  if (ageS < 60) return "<1m ago";
  if (ageS < 3600) return `${Math.floor(ageS / 60)}m ago`;
  if (ageS < 86400) return `${Math.floor(ageS / 3600)}h ago`;
  return `${Math.floor(ageS / 86400)}d ago`;
}

// Color cue paired with formatRelativeAge: stale code (>7d) renders red,
// week-old slate, recent emerald. Returns the Tailwind class for the
// "Last deployed" cell so the table tells fleet drift at a glance
// without needing a tooltip.
export function ageClass(epochSeconds: number | null | undefined, nowMs: number = Date.now()): string {
  if (epochSeconds == null) return "text-slate-400";
  const ageS = Math.max(0, Math.floor(nowMs / 1000 - epochSeconds));
  if (ageS > 7 * 86400) return "text-red-600";
  if (ageS > 86400) return "text-slate-500";
  return "text-emerald-700";
}

export function gini(values: number[]): number {
  if (values.length === 0) return 0;
  const sorted = [...values].sort((a, b) => a - b);
  const n = sorted.length;
  const total = sorted.reduce((a, b) => a + b, 0);
  if (total === 0) return 0;
  let weightedSum = 0;
  for (let i = 0; i < n; i++) weightedSum += (i + 1) * sorted[i];
  return (2 * weightedSum) / (n * total) - (n + 1) / n;
}

export function useSortable<T>(
  items: T[],
  defaultKey: string,
  defaultDir: SortDir,
  getVal: (item: T, key: string) => number | string,
) {
  const [sortKey, setSortKey] = useState(defaultKey);
  const [sortDir, setSortDir] = useState<SortDir>(defaultDir);
  const toggle = useCallback(
    (key: string) => {
      if (sortKey === key) setSortDir((d) => (d === "asc" ? "desc" : "asc"));
      else {
        setSortKey(key);
        setSortDir("desc");
      }
    },
    [sortKey],
  );
  const sorted = useMemo(() => {
    const copy = [...items];
    copy.sort((a, b) => {
      const va = getVal(a, sortKey);
      const vb = getVal(b, sortKey);
      const cmp =
        typeof va === "number" && typeof vb === "number"
          ? va - vb
          : String(va).localeCompare(String(vb));
      return sortDir === "asc" ? cmp : -cmp;
    });
    return copy;
  }, [items, sortKey, sortDir, getVal]);
  return { sorted, sortKey, sortDir, toggle };
}
