import { useEffect, useState, useCallback, useRef } from 'react';

const API_BASE = 'https://gateway.constantinople.cloud';

interface MinerDetail {
  alive: boolean;
  reliability: number;
  avg_ttft_ms: number;
  avg_tps: number;
}

interface HealthData {
  miners_alive: number;
  total_organic: number;
  total_synthetic: number;
  miners_detail: MinerDetail[];
}

interface Metrics {
  latency: string;
  throughput: string;
  reliability: string;
  endpoints: string;
  queries: string;
  organic: string;
  synthetic: string;
}

function compute(data: HealthData): Metrics {
  const alive = data.miners_detail.filter(m => m.alive);
  const withData = alive.filter(m => m.avg_tps > 0);
  const n = withData.length;
  const avgTtft = n > 0 ? withData.reduce((s, m) => s + m.avg_ttft_ms, 0) / n : 0;
  const avgTps = n > 0 ? withData.reduce((s, m) => s + m.avg_tps, 0) / n : 0;
  const avgRel = n > 0 ? withData.reduce((s, m) => s + m.reliability, 0) / n * 100 : 0;
  const total = data.total_organic + data.total_synthetic;

  return {
    latency: `${avgTtft.toFixed(0)}ms`,
    throughput: `${avgTps.toFixed(0)} tok/s`,
    reliability: `${avgRel.toFixed(0)}%`,
    endpoints: `${data.miners_alive}`,
    queries: total.toLocaleString(),
    organic: data.total_organic.toLocaleString(),
    synthetic: data.total_synthetic.toLocaleString(),
  };
}

const LABELS = ['Latency', 'Throughput', 'Reliability', 'Endpoints', 'Queries', 'Organic', 'Synthetic'] as const;
const KEYS: (keyof Metrics)[] = ['latency', 'throughput', 'reliability', 'endpoints', 'queries', 'organic', 'synthetic'];

export function TickerBar() {
  const [metrics, setMetrics] = useState<Metrics | null>(null);
  const prev = useRef<Metrics | null>(null);

  const fetchHealth = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE}/health`, { signal: AbortSignal.timeout(4000) });
      if (!res.ok) return;
      const data: HealthData = await res.json();
      const m = compute(data);
      prev.current = metrics;
      setMetrics(m);
    } catch { /* silent */ }
  }, [metrics]);

  useEffect(() => {
    fetchHealth();
    const id = setInterval(fetchHealth, 5000);
    return () => clearInterval(id);
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <div className="flex items-center gap-5 lg:gap-6 overflow-x-auto scrollbar-none">
      {LABELS.map((label, i) => {
        const key = KEYS[i];
        const val = metrics ? metrics[key] : '—';
        return (
          <div key={label} className="flex items-center gap-1.5 shrink-0">
            <span className="font-sans text-[11px] text-g3-text-muted tracking-wide">{label}</span>
            <span className="font-mono text-[12px] text-g3-text font-medium tabular-nums">{val}</span>
          </div>
        );
      })}
    </div>
  );
}
