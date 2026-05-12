import { motion } from 'framer-motion';
import { useEffect, useState, useCallback, useMemo } from 'react';

const GATEWAY_URL = 'https://gateway.constantinople.cloud';
const API_URL = 'https://api.constantinople.cloud';
const POLL_INTERVAL = 8000;
const HISTORY_LEN = 60;
const CHAIN_POLL = 60000;

// ─── Types ──────────────────────────────────────────────────────────────

interface MinerDetail {
  uid: number;
  alive: boolean;
  reliability: number;
  served: number;
  failed: number;
  avg_ttft_ms: number;
  avg_tps: number;
  active: number;
  score?: number;
  weight?: number;
  pass_rate?: number;
  divergence?: number;
  is_suspect?: boolean;
}

interface GatewayHealth {
  status: string;
  version: string;
  uptime_s: number;
  model: string;
  miners_total: number;
  miners_alive: number;
  epoch: number;
  epoch_elapsed_s: number;
  epoch_length_s: number;
  total_organic: number;
  total_synthetic: number;
  last_weight_set: number;
  weights: Record<string, number>;
  challenges: { total: number; passed: number; failed: number };
  errors: { timeouts: number; miner_errors: number; failovers: number };
  miners_detail: MinerDetail[];
  chain?: { enabled: boolean; netuid: number; network: string; total_weight_sets: number; total_failures: number };
  discovery?: { enabled: boolean; netuid: number; network: string; last_sync: number };
}

interface NetworkInfo {
  netuid: number;
  network: string;
  n_neurons: number;
  n_validators: number;
  n_miners: number;
  registration_cost_tao: number | null;
  hyperparameters: Record<string, unknown>;
  total_emission: number;
  validators: Array<{
    uid: number; hotkey: string; active: boolean; stake: number;
    incentive: number; emission: number; dividend: number; trust: number; vtrust: number;
  }>;
  top_miners: Array<{
    uid: number; hotkey: string; active: boolean; stake: number;
    incentive: number; emission: number; trust: number;
  }>;
  timestamp: number;
}

interface ApiHealth {
  status: string;
  version: string;
  users: number;
  active_keys: number;
  pricing: { input_per_1m_tokens: number; output_per_1m_tokens: number; free_tier_credits: number };
}

interface DatasetStats {
  total_audit_records: number;
  total_epochs: number;
}

// ─── Data hooks ─────────────────────────────────────────────────────────

function usePolledData<T>(url: string, interval: number, enabled = true) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [failures, setFailures] = useState(0);

  const fetch_ = useCallback(async () => {
    try {
      const res = await fetch(url, { signal: AbortSignal.timeout(8000) });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const json = await res.json();
      setData(json);
      setError(null);
      setFailures(0);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Failed');
      setFailures(p => p + 1);
    }
  }, [url]);

  useEffect(() => {
    if (!enabled) return;
    fetch_();
    const id = setInterval(fetch_, interval);
    return () => clearInterval(id);
  }, [fetch_, interval, enabled]);

  return { data, error, failures };
}

interface SubnetPool { alpha_out: number; alpha_in: number; tao_in: number; volume: number; price: number }
interface SubnetData {
  netuid: number; network: string; block: number; n: number; max_n: number;
  registration_cost: number | null; tempo: number; immunity_period: number;
  max_validators: number; weights_rate_limit: number; commit_reveal_enabled: boolean;
  registration_allowed: boolean; total_stake: number; total_emission: number;
  validator_permits: number; pool: SubnetPool | null;
  neurons: Array<{ uid: number; incentive: number; stake: number; emission: number; dividends: number; vtrust: number }>;
}
interface AuditorMiner {
  uid: number; avg_cosine: number; passed_challenges: number; failed_challenges: number;
  voided_challenges: number; is_suspect: boolean; avg_tps: number; avg_ttft_ms: number;
}
interface AuditorData { epoch: number; total_audits: number; miners: AuditorMiner[] }

function useGatewayDashboard() {
  const { data: health, error, failures } = usePolledData<GatewayHealth>(`${GATEWAY_URL}/health`, POLL_INTERVAL);
  const { data: network } = usePolledData<NetworkInfo>(`${GATEWAY_URL}/v1/network`, 60000);
  const { data: apiHealth } = usePolledData<ApiHealth>(`${API_URL}/health`, 30000);
  const { data: datasetStats } = usePolledData<DatasetStats>(`${API_URL}/v1/dataset/stats`, 60000);
  const { data: subnet } = usePolledData<SubnetData>(`${API_URL}/v1/subnet`, CHAIN_POLL);
  const { data: auditor } = usePolledData<AuditorData>(`${API_URL}/v1/auditor`, POLL_INTERVAL);
  // History buffers
  const [tpsHistory, setTpsHistory] = useState<number[]>([]);
  const [latencyHistory, setLatencyHistory] = useState<number[]>([]);
  const [minerHistory, setMinerHistory] = useState<number[]>([]);
  const [reliabilityHistory, setReliabilityHistory] = useState<number[]>([]);
  const [organicHistory, setOrganicHistory] = useState<number[]>([]);

  useEffect(() => {
    if (!health) return;
    const alive = health.miners_detail.filter(m => m.alive && m.avg_tps > 0);
    const avgTps = alive.length > 0 ? alive.reduce((s, m) => s + m.avg_tps, 0) / alive.length : 0;
    const avgTtft = alive.length > 0 ? alive.reduce((s, m) => s + m.avg_ttft_ms, 0) / alive.length : 0;
    const avgRel = alive.length > 0 ? alive.reduce((s, m) => s + m.reliability, 0) / alive.length * 100 : 0;
    setTpsHistory(p => [...p.slice(-(HISTORY_LEN - 1)), avgTps]);
    setLatencyHistory(p => [...p.slice(-(HISTORY_LEN - 1)), avgTtft]);
    setMinerHistory(p => [...p.slice(-(HISTORY_LEN - 1)), health.miners_alive]);
    setReliabilityHistory(p => [...p.slice(-(HISTORY_LEN - 1)), avgRel]);
    setOrganicHistory(p => [...p.slice(-(HISTORY_LEN - 1)), health.total_organic]);
  }, [health]);

  return { health, network, apiHealth, datasetStats, subnet, auditor, error, failures, tpsHistory, latencyHistory, minerHistory, reliabilityHistory, organicHistory };
}

// ─── Utility ────────────────────────────────────────────────────────────

function fmt(n: number, decimals = 0): string {
  if (n >= 1_000_000) return (n / 1_000_000).toFixed(1) + 'M';
  if (n >= 1_000) return (n / 1_000).toFixed(1) + 'K';
  return n.toFixed(decimals);
}

function fmtUptime(s: number): string {
  if (s < 60) return `${s}s`;
  if (s < 3600) return `${Math.floor(s / 60)}m ${s % 60}s`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ${Math.floor((s % 3600) / 60)}m`;
  return `${Math.floor(s / 86400)}d ${Math.floor((s % 86400) / 3600)}h`;
}

function fmtAgo(ts: number): string {
  if (!ts) return 'never';
  const ago = Math.floor(Date.now() / 1000 - ts);
  if (ago < 0) return 'just now';
  return fmtUptime(ago) + ' ago';
}

// ─── Components ─────────────────────────────────────────────────────────

function SparkLine({ data, color = '#c9a962', height = 40 }: { data: number[]; color?: string; height?: number }) {
  if (data.length < 2) return <div style={{ height }} />;
  const max = Math.max(...data);
  const min = Math.min(...data);
  const range = max - min || 1;
  const w = 240;
  const pts = data.map((v, i) => `${(i / (data.length - 1)) * w},${height - ((v - min) / range) * (height - 4) - 2}`).join(' ');
  const area = `0,${height} ${pts} ${w},${height}`;
  return (
    <svg viewBox={`0 0 ${w} ${height}`} className="w-full" style={{ height }} preserveAspectRatio="none">
      <polygon points={area} fill={`${color}15`} />
      <polyline points={pts} fill="none" stroke={color} strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

function Dot({ ok, pulse }: { ok: boolean; pulse?: boolean }) {
  return (
    <span className={`inline-block w-2 h-2 rounded-full flex-shrink-0 ${ok ? 'bg-emerald-400' : 'bg-red-400'} ${pulse ? 'animate-pulse' : ''}`} />
  );
}

function Card({ children, className = '' }: { children: React.ReactNode; className?: string }) {
  return (
    <div className={`border border-white/[0.08] rounded-lg p-4 sm:p-5 bg-white/[0.02] backdrop-blur-sm ${className}`}>
      {children}
    </div>
  );
}

function SectionTitle({ children }: { children: React.ReactNode }) {
  return <h3 className="font-sans text-xs font-medium text-g3-text-secondary tracking-widest uppercase mb-4">{children}</h3>;
}

function MetricCard({ label, value, sub, data, color, small }: {
  label: string; value: string; sub?: string; data?: number[]; color?: string; small?: boolean;
}) {
  return (
    <Card>
      <div className="flex items-start justify-between gap-2 mb-1">
        <span className={`font-sans ${small ? 'text-[11px]' : 'text-xs'} text-g3-text-muted`}>{label}</span>
        <span className={`font-mono ${small ? 'text-lg' : 'text-xl sm:text-2xl'} font-semibold text-g3-text text-right leading-tight`}>{value}</span>
      </div>
      {sub && <p className="font-sans text-[10px] text-g3-text-muted mt-0.5">{sub}</p>}
      {data && data.length > 1 && (
        <div className="mt-3 border-t border-white/[0.06] pt-2">
          <SparkLine data={data} color={color || '#c9a962'} height={36} />
        </div>
      )}
    </Card>
  );
}

function StatRow({ label, value, ok }: { label: string; value: string; ok?: boolean }) {
  return (
    <div className="flex items-center justify-between py-1.5 border-b border-white/[0.04] last:border-0">
      <span className="font-sans text-xs text-g3-text-muted">{label}</span>
      <span className="font-mono text-xs text-g3-text flex items-center gap-1.5">
        {ok !== undefined && <Dot ok={ok} />}
        {value}
      </span>
    </div>
  );
}

function ProgressBar({ value, max, color = 'from-amber-500/60 to-amber-400/80' }: { value: number; max: number; color?: string }) {
  const pct = max > 0 ? Math.min((value / max) * 100, 100) : 0;
  return (
    <div className="h-2 rounded-full overflow-hidden bg-white/[0.06]">
      <div className={`h-full rounded-full bg-gradient-to-r ${color} transition-all duration-700`} style={{ width: `${pct}%` }} />
    </div>
  );
}

type SortKey = 'uid' | 'avg_tps' | 'avg_ttft_ms' | 'reliability' | 'served' | 'weight' | 'pass_rate';

// ─── Main Page ──────────────────────────────────────────────────────────

export function StatusPage() {
  const { health, network, apiHealth, datasetStats, subnet, auditor, error, failures, tpsHistory, latencyHistory, minerHistory, reliabilityHistory, organicHistory } = useGatewayDashboard();

  const [sortKey, setSortKey] = useState<SortKey>('weight');
  const [sortAsc, setSortAsc] = useState(false);
  const [showOffline, setShowOffline] = useState(false);

  const isOnline = health?.status === 'ok' && failures === 0;
  const isDown = failures >= 3;

  // Derived metrics
  const aliveMiners = useMemo(() => health?.miners_detail.filter(m => m.alive) ?? [], [health]);
  const activeMiners = useMemo(() => aliveMiners.filter(m => m.avg_tps > 0), [aliveMiners]);
  const avgTps = activeMiners.length > 0 ? activeMiners.reduce((s, m) => s + m.avg_tps, 0) / activeMiners.length : 0;
  const maxTps = activeMiners.length > 0 ? Math.max(...activeMiners.map(m => m.avg_tps)) : 0;
  const totalTps = activeMiners.reduce((s, m) => s + m.avg_tps, 0);
  const avgTtft = activeMiners.length > 0 ? activeMiners.reduce((s, m) => s + m.avg_ttft_ms, 0) / activeMiners.length : 0;
  const p50Ttft = useMemo(() => {
    if (activeMiners.length === 0) return 0;
    const sorted = [...activeMiners].sort((a, b) => a.avg_ttft_ms - b.avg_ttft_ms);
    return sorted[Math.floor(sorted.length / 2)]?.avg_ttft_ms ?? 0;
  }, [activeMiners]);
  const avgReliability = activeMiners.length > 0 ? activeMiners.reduce((s, m) => s + m.reliability, 0) / activeMiners.length * 100 : 0;
  const challengeRate = health && health.challenges.total > 0 ? health.challenges.passed / health.challenges.total * 100 : 0;
  const totalServed = health?.miners_detail.reduce((s, m) => s + m.served, 0) ?? 0;
  const totalFailed = health?.miners_detail.reduce((s, m) => s + m.failed, 0) ?? 0;
  const successRate = totalServed + totalFailed > 0 ? totalServed / (totalServed + totalFailed) * 100 : 100;

  // Sorted miner list
  const sortedMiners = useMemo(() => {
    const list = showOffline ? (health?.miners_detail ?? []) : aliveMiners;
    return [...list].sort((a, b) => {
      const va = a[sortKey] ?? 0;
      const vb = b[sortKey] ?? 0;
      return sortAsc ? (va as number) - (vb as number) : (vb as number) - (va as number);
    });
  }, [health, aliveMiners, sortKey, sortAsc, showOffline]);

  const handleSort = (key: SortKey) => {
    if (sortKey === key) setSortAsc(!sortAsc);
    else { setSortKey(key); setSortAsc(false); }
  };

  const SortButton = ({ k, children }: { k: SortKey; children: React.ReactNode }) => (
    <button onClick={() => handleSort(k)} className="flex items-center gap-0.5 hover:text-g3-text transition-colors">
      {children}
      {sortKey === k && <span className="text-[8px]">{sortAsc ? '\u25B2' : '\u25BC'}</span>}
    </button>
  );

  // Color palette for weight bars
  const weightColors = ['#6ec896', '#968cdc', '#c9a962', '#c87878', '#78b4c8', '#c896c8', '#96c8b4', '#dca06c', '#6c9cdc', '#dc96a0'];

  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      transition={{ duration: 0.4 }}
      className="relative z-20 min-h-screen pt-20 sm:pt-28 pb-16 px-4 sm:px-8 lg:px-16"
    >
      <div className="max-w-7xl mx-auto">

        {/* ── Down Banner ── */}
        {isDown && (
          <div className="mb-6 border border-red-500/30 rounded-lg p-3 sm:p-4 bg-red-500/10">
            <div className="flex items-center gap-2">
              <Dot ok={false} pulse />
              <span className="font-sans text-sm text-red-300 font-medium">Gateway unreachable</span>
            </div>
            <p className="font-sans text-[11px] text-red-400/70 mt-1 ml-4">
              {failures} failures{error && ` \u00B7 ${error}`}
            </p>
          </div>
        )}

        {/* ── Header ── */}
        <div className="mb-8 sm:mb-12">
          <div className="flex items-center gap-3 mb-3">
            <div className="w-5 h-px bg-g3-text-secondary" />
            <span className="font-sans text-[10px] sm:text-xs text-g3-text-secondary tracking-widest uppercase">SN97 Network Dashboard</span>
          </div>
          <div className="flex items-center gap-3 flex-wrap">
            <Dot ok={isOnline} pulse={!isOnline && !isDown} />
            <h2 className="font-serif text-2xl sm:text-4xl lg:text-5xl text-g3-text leading-tight tracking-[-0.02em]">
              {isOnline ? 'All systems operational' : isDown ? 'Gateway unreachable' : 'Connecting...'}
            </h2>
          </div>
          <p className="font-sans text-[11px] text-g3-text-muted mt-2">
            {health && `Gateway v${health.version} \u00B7 Up ${fmtUptime(health.uptime_s)} \u00B7 `}
            Auto-refresh every {POLL_INTERVAL / 1000}s
            {network && ` \u00B7 Subnet ${network.netuid} on ${network.network}`}
          </p>
        </div>

        {/* ── Service Health Strip ── */}
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-8">
          <ServicePill label="Gateway" ok={isOnline} detail={health ? `v${health.version}` : undefined} />
          <ServicePill label="Auditor" ok={health?.challenges?.total ? health.challenges.total > 0 : false} detail={health ? `${health.challenges.total} audits` : undefined} />
          <ServicePill label="API" ok={apiHealth?.status === 'ok'} detail={apiHealth ? `v${apiHealth.version}` : undefined} />
          <ServicePill label="On-chain" ok={!!health?.chain?.enabled} detail={health?.chain ? `${health.chain.total_weight_sets} commits` : undefined} />
        </div>

        {/* ── Primary Metrics ── */}
        <SectionTitle>Performance</SectionTitle>
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-3 sm:gap-4 mb-8">
          <MetricCard label="Avg TTFT" value={health ? `${avgTtft.toFixed(0)}ms` : '\u2014'} sub={health ? `P50: ${p50Ttft.toFixed(0)}ms` : undefined} data={latencyHistory} color="#c9a962" />
          <MetricCard label="Avg TPS" value={health ? `${avgTps.toFixed(0)}` : '\u2014'} sub={health ? `Peak: ${maxTps.toFixed(0)} \u00B7 Total: ${fmt(totalTps, 0)}` : undefined} data={tpsHistory} color="#6ec896" />
          <MetricCard label="Active Miners" value={health ? `${health.miners_alive}/${health.miners_total}` : '\u2014'} sub={network ? `${network.n_neurons} on-chain` : undefined} data={minerHistory} color="#968cdc" />
          <MetricCard label="Reliability" value={health ? `${avgReliability.toFixed(1)}%` : '\u2014'} sub={health ? `Success rate: ${successRate.toFixed(1)}%` : undefined} data={reliabilityHistory} color="#c8b664" />
        </div>

        {/* ── Request & Challenge Stats ── */}
        <SectionTitle>Requests & Verification</SectionTitle>
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-3 sm:gap-4 mb-8">
          <MetricCard label="Organic Requests" value={health ? fmt(health.total_organic) : '\u2014'} sub="User inference requests" data={organicHistory} color="#78b4c8" />
          <MetricCard label="Synthetic Probes" value={health ? fmt(health.total_synthetic) : '\u2014'} sub="Validator test queries" />
          <MetricCard label="Challenge Pass Rate" value={health ? `${challengeRate.toFixed(1)}%` : '\u2014'} sub={health ? `${health.challenges.passed} pass / ${health.challenges.failed} fail` : undefined} color="#6ec896" />
          <MetricCard label="Errors" value={health ? `${health.errors.timeouts + health.errors.miner_errors}` : '\u2014'} sub={health ? `${health.errors.timeouts} timeouts \u00B7 ${health.errors.failovers} failovers` : undefined} color="#c87878" />
        </div>

        {/* ── Epoch Progress ── */}
        {health && (
          <>
            <SectionTitle>Epoch Progress</SectionTitle>
            <Card className="mb-8">
              <div className="flex items-center justify-between mb-2">
                <span className="font-sans text-sm font-medium text-g3-text">Epoch {health.epoch}</span>
                <span className="font-mono text-xs text-g3-text-muted">
                  {Math.floor(health.epoch_elapsed_s / 60)}m / {Math.floor(health.epoch_length_s / 60)}m
                </span>
              </div>
              <ProgressBar value={health.epoch_elapsed_s} max={health.epoch_length_s} />
              <div className="flex flex-wrap gap-x-4 gap-y-1 mt-3">
                <span className="font-sans text-[10px] text-g3-text-muted">
                  {((health.epoch_elapsed_s / health.epoch_length_s) * 100).toFixed(0)}% complete
                </span>
                {health.last_weight_set > 0 && (
                  <span className="font-sans text-[10px] text-g3-text-muted">
                    Weights committed {fmtAgo(health.last_weight_set)}
                  </span>
                )}
                {health.chain && (
                  <span className="font-sans text-[10px] text-g3-text-muted">
                    {health.chain.total_weight_sets} total commits
                  </span>
                )}
              </div>
            </Card>
          </>
        )}

        {/* ── Weight Distribution ── */}
        {health && Object.keys(health.weights).length > 0 && (
          <>
            <SectionTitle>Weight Distribution</SectionTitle>
            <Card className="mb-8">
              <div className="flex h-5 sm:h-6 rounded-full overflow-hidden bg-white/[0.04] mb-3">
                {Object.entries(health.weights)
                  .sort(([, a], [, b]) => b - a)
                  .map(([uid, weight], i) => (
                    <div
                      key={uid}
                      style={{ width: `${weight * 100}%`, backgroundColor: weightColors[i % weightColors.length] }}
                      className="h-full flex items-center justify-center transition-all duration-500 min-w-0"
                      title={`UID ${uid}: ${(weight * 100).toFixed(1)}%`}
                    >
                      {weight > 0.06 && (
                        <span className="font-mono text-[9px] sm:text-[10px] text-white/90 font-medium truncate px-0.5">
                          {uid}
                        </span>
                      )}
                    </div>
                  ))}
              </div>
              <div className="flex gap-x-3 gap-y-1 flex-wrap">
                {Object.entries(health.weights)
                  .sort(([, a], [, b]) => b - a)
                  .map(([uid, weight], i) => (
                    <div key={uid} className="flex items-center gap-1">
                      <div className="w-2 h-2 rounded-full flex-shrink-0" style={{ backgroundColor: weightColors[i % weightColors.length] }} />
                      <span className="font-mono text-[10px] text-g3-text-muted">UID {uid}: {(weight * 100).toFixed(1)}%</span>
                    </div>
                  ))}
              </div>
            </Card>
          </>
        )}

        {/* ── Subnet Economics ── */}
        {subnet?.pool && (
          <>
            <SectionTitle>Subnet Economics</SectionTitle>
            <div className="grid grid-cols-2 lg:grid-cols-4 gap-3 sm:gap-4 mb-8">
              <MetricCard label="Alpha Price" value={`${subnet.pool.price.toFixed(6)} \u03C4`} sub="Moving average" small />
              <MetricCard label="Pool Volume" value={`${fmt(subnet.pool.volume, 0)} \u03C4`} sub="24h subnet volume" small />
              <MetricCard label="Alpha Supply" value={fmt(subnet.pool.alpha_out, 0)} sub="In circulation" small />
              <MetricCard label="TAO Locked" value={`${subnet.pool.tao_in.toFixed(2)} \u03C4`} sub="In AMM pool" small />
            </div>
          </>
        )}

        {/* ── Hidden State Verification ── */}
        {auditor && auditor.total_audits > 0 && (
          <>
            <SectionTitle>Hidden State Verification</SectionTitle>
            <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-3 sm:gap-4 mb-8">
              <MetricCard label="Total Audits" value={fmt(auditor.total_audits)} sub={`Auditor epoch ${auditor.epoch}`} small />
              <MetricCard label="Avg Cosine" value={auditor.miners.length > 0 ? (auditor.miners.reduce((s, m) => s + m.avg_cosine, 0) / auditor.miners.length).toFixed(4) : '\u2014'} sub="Cross-miner similarity" small />
              <MetricCard label="Passed" value={`${auditor.miners.reduce((s, m) => s + m.passed_challenges, 0)}`} sub="Challenges passed" small />
              <MetricCard label="Failed" value={`${auditor.miners.reduce((s, m) => s + m.failed_challenges, 0)}`} sub="Challenges failed" small />
              <MetricCard label="Voided" value={`${auditor.miners.reduce((s, m) => s + m.voided_challenges, 0)}`} sub="Inconclusive (CPU/GPU)" small />
            </div>
          </>
        )}

        {/* ── On-Chain & Network Info ── */}
        {(network || apiHealth || datasetStats) && (
          <>
            <SectionTitle>Network & Subnet Info</SectionTitle>
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3 sm:gap-4 mb-8">
              {/* Registration */}
              <Card>
                <h4 className="font-sans text-xs font-medium text-g3-text mb-3">Registration</h4>
                {network ? (
                  <>
                    <StatRow label="Subnet" value={`SN${network.netuid}`} />
                    <StatRow label="Network" value={network.network} />
                    <StatRow label="Reg cost" value={subnet?.registration_cost != null ? `${subnet.registration_cost.toFixed(4)} TAO` : network.registration_cost_tao != null ? `${network.registration_cost_tao.toFixed(4)} TAO` : 'N/A'} />
                    <StatRow label="Neurons" value={subnet ? `${subnet.n} / ${subnet.max_n}` : `${network.n_neurons}`} />
                    <StatRow label="Validators" value={`${network.n_validators}`} />
                    <StatRow label="Miners" value={`${network.n_miners}`} />
                    {subnet && <StatRow label="Block" value={`#${subnet.block.toLocaleString()}`} />}
                  </>
                ) : <p className="text-xs text-g3-text-muted">Loading...</p>}
              </Card>

              {/* Hyperparameters */}
              <Card>
                <h4 className="font-sans text-xs font-medium text-g3-text mb-3">Hyperparameters</h4>
                {network?.hyperparameters ? (
                  <>
                    <StatRow label="Tempo" value={`${network.hyperparameters.tempo ?? '?'} blocks`} />
                    <StatRow label="Max validators" value={`${network.hyperparameters.max_validators ?? '?'}`} />
                    <StatRow label="Immunity period" value={`${network.hyperparameters.immunity_period ?? '?'}`} />
                    <StatRow label="Weights rate limit" value={`${network.hyperparameters.weights_rate_limit ?? '?'} blocks`} />
                    <StatRow label="Commit-reveal" value={network.hyperparameters.commit_reveal_weights_enabled ? 'Enabled' : 'Disabled'} ok={!!network.hyperparameters.commit_reveal_weights_enabled} />
                    <StatRow label="Registration" value={network.hyperparameters.registration_allowed ? 'Open' : 'Closed'} ok={!!network.hyperparameters.registration_allowed} />
                    <StatRow label="Liquid alpha" value={network.hyperparameters.liquid_alpha_enabled ? 'Enabled' : 'Disabled'} />
                  </>
                ) : <p className="text-xs text-g3-text-muted">Loading...</p>}
              </Card>

              {/* Platform Stats */}
              <Card>
                <h4 className="font-sans text-xs font-medium text-g3-text mb-3">Platform</h4>
                {apiHealth && (
                  <>
                    <StatRow label="API users" value={`${apiHealth.users}`} />
                    <StatRow label="Active API keys" value={`${apiHealth.active_keys}`} />
                    <StatRow label="Pricing (input)" value={`$${apiHealth.pricing.input_per_1m_tokens}/M tok`} />
                    <StatRow label="Pricing (output)" value={`$${apiHealth.pricing.output_per_1m_tokens}/M tok`} />
                    <StatRow label="Free credits" value={`$${apiHealth.pricing.free_tier_credits}`} />
                  </>
                )}
                {datasetStats && (
                  <>
                    <StatRow label="Audit records" value={fmt(datasetStats.total_audit_records)} />
                    <StatRow label="Epochs completed" value={`${datasetStats.total_epochs}`} />
                  </>
                )}
              </Card>
            </div>
          </>
        )}

        {/* ── Top Validators (on-chain) ── */}
        {network && network.validators.length > 0 && (
          <>
            <SectionTitle>Top Validators (On-chain)</SectionTitle>
            <Card className="mb-8 overflow-hidden !p-0">
              <div className="overflow-x-auto">
                <table className="w-full text-left min-w-[480px]">
                  <thead>
                    <tr className="border-b border-white/[0.06]">
                      <Th>UID</Th><Th>Hotkey</Th><Th>Stake</Th><Th>Dividend</Th><Th>vTrust</Th><Th>Active</Th>
                    </tr>
                  </thead>
                  <tbody>
                    {network.validators.slice(0, 10).map(v => (
                      <Tr key={v.uid}>
                        <Td mono>{v.uid}</Td>
                        <Td mono muted>{v.hotkey}</Td>
                        <Td mono>{fmt(v.stake, 1)}</Td>
                        <Td mono>{(v.dividend * 100).toFixed(2)}%</Td>
                        <Td mono>{v.vtrust.toFixed(4)}</Td>
                        <Td><Dot ok={v.active} /></Td>
                      </Tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </Card>
          </>
        )}

        {/* ── Top Miners (on-chain incentive) ── */}
        {network && network.top_miners.length > 0 && (
          <>
            <SectionTitle>Top Miners by Incentive (On-chain)</SectionTitle>
            <Card className="mb-8 overflow-hidden !p-0">
              <div className="overflow-x-auto">
                <table className="w-full text-left min-w-[480px]">
                  <thead>
                    <tr className="border-b border-white/[0.06]">
                      <Th>UID</Th><Th>Hotkey</Th><Th>Incentive</Th><Th>Emission</Th><Th>Trust</Th><Th>Active</Th>
                    </tr>
                  </thead>
                  <tbody>
                    {network.top_miners.slice(0, 15).map(m => (
                      <Tr key={m.uid}>
                        <Td mono>{m.uid}</Td>
                        <Td mono muted>{m.hotkey}</Td>
                        <Td mono>{(m.incentive * 100).toFixed(2)}%</Td>
                        <Td mono>{m.emission.toFixed(6)}</Td>
                        <Td mono>{m.trust.toFixed(4)}</Td>
                        <Td><Dot ok={m.active} /></Td>
                      </Tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </Card>
          </>
        )}

        {/* ── Miner Fleet Table ── */}
        {health && health.miners_detail.length > 0 && (
          <>
            <div className="flex items-center justify-between mb-4 flex-wrap gap-2">
              <SectionTitle>Miner Fleet</SectionTitle>
              <label className="flex items-center gap-2 cursor-pointer">
                <input
                  type="checkbox"
                  checked={showOffline}
                  onChange={() => setShowOffline(!showOffline)}
                  className="rounded border-white/20 bg-white/[0.05] text-g3-accent focus:ring-g3-accent/50 w-3.5 h-3.5"
                />
                <span className="font-sans text-[11px] text-g3-text-muted">Show offline</span>
              </label>
            </div>
            <Card className="mb-8 overflow-hidden !p-0">
              <div className="px-4 py-3 sm:px-5 border-b border-white/[0.06]">
                <p className="font-sans text-[11px] text-g3-text-muted">
                  {health.model} \u00B7 {aliveMiners.length} alive / {health.miners_total} registered \u00B7 Tap column headers to sort
                </p>
              </div>
              <div className="overflow-x-auto">
                <table className="w-full text-left min-w-[640px]">
                  <thead>
                    <tr className="border-b border-white/[0.06]">
                      <Th><SortButton k="uid">UID</SortButton></Th>
                      <Th>Status</Th>
                      <Th><SortButton k="avg_tps">TPS</SortButton></Th>
                      <Th><SortButton k="avg_ttft_ms">TTFT</SortButton></Th>
                      <Th><SortButton k="reliability">Rel%</SortButton></Th>
                      <Th><SortButton k="served">Served</SortButton></Th>
                      <Th><SortButton k="weight">Weight</SortButton></Th>
                      <Th><SortButton k="pass_rate">Audit</SortButton></Th>
                    </tr>
                  </thead>
                  <tbody>
                    {sortedMiners.map(m => (
                      <Tr key={m.uid} dimmed={!m.alive}>
                        <Td mono>
                          {m.uid}
                          {m.is_suspect && <span className="ml-1 text-[9px] text-amber-400" title="Under elevated monitoring">!</span>}
                        </Td>
                        <Td>
                          <span className={`inline-flex items-center gap-1 text-[11px] ${m.alive ? 'text-emerald-400' : 'text-red-400'}`}>
                            <Dot ok={m.alive} />
                            {m.alive ? 'Online' : 'Off'}
                          </span>
                        </Td>
                        <Td mono>{m.avg_tps.toFixed(0)}</Td>
                        <Td mono>{m.avg_ttft_ms.toFixed(0)}<span className="text-g3-text-muted text-[9px]">ms</span></Td>
                        <Td mono>{(m.reliability * 100).toFixed(0)}%</Td>
                        <Td mono muted>{m.served}</Td>
                        <Td mono>
                          {m.weight != null ? (
                            <span className="inline-flex items-center gap-1">
                              <span className="inline-block h-1.5 rounded-full bg-g3-accent/60" style={{ width: `${Math.max(m.weight * 200, 2)}px` }} />
                              {(m.weight * 100).toFixed(1)}%
                            </span>
                          ) : '\u2014'}
                        </Td>
                        <Td mono>{m.pass_rate != null ? `${(m.pass_rate * 100).toFixed(0)}%` : '\u2014'}</Td>
                      </Tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </Card>

            {/* Mobile cards */}
            <div className="sm:hidden space-y-2 mb-4">
              {sortedMiners.map(m => (
                <div key={m.uid} className={`border border-white/[0.08] rounded-lg p-3 bg-white/[0.02] ${!m.alive ? 'opacity-40' : ''}`}>
                  <div className="flex items-center justify-between mb-2">
                    <div className="flex items-center gap-2">
                      <Dot ok={m.alive} />
                      <span className="font-mono text-sm font-semibold text-g3-text">UID {m.uid}</span>
                      {m.is_suspect && <span className="text-[10px] text-amber-400">!</span>}
                    </div>
                    {m.weight != null && m.weight > 0 && (
                      <span className="font-mono text-xs text-g3-accent font-medium">{(m.weight * 100).toFixed(1)}%</span>
                    )}
                  </div>
                  <div className="grid grid-cols-4 gap-1.5">
                    <MobileStat label="TPS" value={m.avg_tps > 0 ? m.avg_tps.toFixed(0) : '\u2014'} />
                    <MobileStat label="TTFT" value={m.avg_ttft_ms > 0 ? `${m.avg_ttft_ms.toFixed(0)}ms` : '\u2014'} />
                    <MobileStat label="Rel" value={`${(m.reliability * 100).toFixed(0)}%`} />
                    <MobileStat label="Audit" value={m.pass_rate != null ? `${(m.pass_rate * 100).toFixed(0)}%` : '\u2014'} />
                  </div>
                </div>
              ))}
            </div>
          </>
        )}

        {/* ── Footer ── */}
        <div className="text-center mt-12">
          <p className="font-sans text-[10px] text-g3-text-muted">
            Constantinople \u00B7 SN97 \u00B7 Decentralized Inference
            {network && ` \u00B7 ${network.n_neurons} neurons`}
            {datasetStats && ` \u00B7 ${fmt(datasetStats.total_audit_records)} audit records`}
          </p>
          <p className="font-sans text-[10px] text-g3-text-muted mt-1">
            Data refreshes every {POLL_INTERVAL / 1000}s \u00B7 On-chain data refreshes every 60s
          </p>
        </div>
      </div>
    </motion.div>
  );
}

// ─── Table primitives ───────────────────────────────────────────────────

function Th({ children }: { children?: React.ReactNode }) {
  return <th className="px-3 sm:px-4 py-2.5 font-sans text-[10px] sm:text-[11px] text-g3-text-muted font-medium tracking-wider uppercase whitespace-nowrap">{children}</th>;
}

function Td({ children, mono, muted }: { children?: React.ReactNode; mono?: boolean; muted?: boolean }) {
  return (
    <td className={`px-3 sm:px-4 py-2 text-xs sm:text-sm whitespace-nowrap ${mono ? 'font-mono' : 'font-sans'} ${muted ? 'text-g3-text-secondary' : 'text-g3-text'}`}>
      {children}
    </td>
  );
}

function Tr({ children, dimmed }: { children: React.ReactNode; dimmed?: boolean }) {
  return <tr className={`border-b border-white/[0.04] hover:bg-white/[0.02] transition-colors ${dimmed ? 'opacity-40' : ''}`}>{children}</tr>;
}

function MobileStat({ label, value }: { label: string; value: string }) {
  return (
    <div className="bg-white/[0.03] rounded px-2 py-1 text-center">
      <p className="font-mono text-xs text-g3-text">{value}</p>
      <p className="font-sans text-[9px] text-g3-text-muted">{label}</p>
    </div>
  );
}

function ServicePill({ label, ok, detail }: { label: string; ok: boolean; detail?: string }) {
  return (
    <div className={`flex items-center gap-2 rounded-lg px-3 py-2.5 border ${ok ? 'border-emerald-500/20 bg-emerald-500/[0.05]' : 'border-red-500/20 bg-red-500/[0.05]'}`}>
      <Dot ok={ok} pulse={!ok} />
      <div className="min-w-0">
        <p className="font-sans text-xs font-medium text-g3-text truncate">{label}</p>
        {detail && <p className="font-sans text-[10px] text-g3-text-muted truncate">{detail}</p>}
      </div>
    </div>
  );
}
