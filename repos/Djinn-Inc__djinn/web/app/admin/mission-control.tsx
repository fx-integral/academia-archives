"use client";

import { useEffect, useState } from "react";
import { formatUsdc } from "@/lib/types";
import type {
  SubgraphRecentSignal,
  SubgraphRecentPurchase,
  SubgraphRecentAudit,
  SubgraphProtocolStats,
} from "@/lib/subgraph";

interface ContractProbe {
  name: string;
  address: string;
  paused: boolean | null;
  reason?: string;
}

interface ContractStatusResponse {
  chainId: number;
  rpcUrl: string;
  blockNumber: number | null;
  blockTimestamp: number | null;
  blockLagSeconds: number | null;
  contracts: ContractProbe[];
  probedAt: number;
  elapsedMs: number;
  rpcError?: string;
}

const BASE_EXPLORER = process.env.NEXT_PUBLIC_BASE_EXPLORER || "https://sepolia.basescan.org";

interface ErrorReport {
  message: string;
  url: string;
  errorMessage: string;
  source: string;
  timestamp: string;
  wallet: string;
}

interface ValidatorHealth {
  uid: number;
  status: string;
  shares_held: number;
  chain_connected: boolean;
  bt_connected: boolean;
  version: string;
  error?: string;
}

interface MinerHealth {
  uid: number;
  status: string;
  odds_api_connected: boolean;
  bt_connected: boolean;
  version: string;
  error?: string;
}

export type DataStatus = "pending" | "done" | "error";

export interface MissionControlProps {
  validators: ValidatorHealth[];
  miners: MinerHealth[];
  errorReports: ErrorReport[];
  recentSignals: SubgraphRecentSignal[];
  recentPurchases: SubgraphRecentPurchase[];
  recentAudits: SubgraphRecentAudit[];
  stats: SubgraphProtocolStats | null;
  lastRefresh: Date | null;
  // Per-section fetch status from parent's refresh loop. Lets us distinguish
  // "0 because fetch failed" from "0 because no data yet" — the NASA-HQ
  // hallucination class we've been closing. If omitted (e.g., callers that
  // haven't plumbed status yet), behaves as if every section is "done".
  dataStatus?: Partial<Record<"validators" | "miners" | "subgraph" | "errors" | "signals" | "purchases" | "audits", DataStatus>>;
}

type Severity = "ok" | "warn" | "crit";

function SeverityDot({ level }: { level: Severity }) {
  const color =
    level === "ok" ? "bg-green-500 shadow-[0_0_8px_rgba(34,197,94,0.8)]"
    : level === "warn" ? "bg-amber-400 shadow-[0_0_8px_rgba(251,191,36,0.8)]"
    : "bg-red-500 shadow-[0_0_8px_rgba(239,68,68,0.8)] animate-pulse";
  return <span className={`inline-block w-2.5 h-2.5 rounded-full ${color}`} />;
}

function StatusLight({ label, level, detail, hint }: { label: string; level: Severity; detail: string; hint?: string }) {
  const border =
    level === "ok" ? "border-green-500/30 bg-green-500/5"
    : level === "warn" ? "border-amber-500/30 bg-amber-500/5"
    : "border-red-500/30 bg-red-500/5";
  return (
    <div className={`rounded-lg border ${border} p-3 flex items-start gap-3`} title={hint}>
      <SeverityDot level={level} />
      <div className="flex-1 min-w-0">
        <div className="text-[11px] text-slate-400 uppercase tracking-wider font-semibold">{label}</div>
        <div className="text-lg font-bold text-white leading-tight mt-0.5">{detail}</div>
      </div>
    </div>
  );
}

function KpiTile({ label, value, sub, accent }: { label: string; value: string; sub?: string; accent?: "green" | "blue" | "orange" | "purple" }) {
  const color =
    accent === "green" ? "text-green-400"
    : accent === "orange" ? "text-orange-400"
    : accent === "purple" ? "text-purple-400"
    : "text-blue-400";
  return (
    <div className="bg-white/5 rounded-lg p-3">
      <div className="text-[10px] text-slate-400 uppercase tracking-wider font-semibold">{label}</div>
      <div className={`text-2xl font-bold ${color} leading-tight mt-1`}>{value}</div>
      {sub && <div className="text-[10px] text-slate-500 mt-0.5">{sub}</div>}
    </div>
  );
}

function bucketByHour(timestamps: number[], hours = 24): number[] {
  const nowSec = Math.floor(Date.now() / 1000);
  const bucketSec = 3600;
  const buckets = new Array(hours).fill(0) as number[];
  for (const ts of timestamps) {
    const ageSec = nowSec - ts;
    if (ageSec < 0 || ageSec >= hours * bucketSec) continue;
    const idx = hours - 1 - Math.floor(ageSec / bucketSec);
    if (idx >= 0 && idx < hours) buckets[idx]++;
  }
  return buckets;
}

function Sparkline({ signalBuckets, purchaseBuckets }: { signalBuckets: number[]; purchaseBuckets: number[] }) {
  const width = 480;
  const height = 80;
  const hours = signalBuckets.length;
  const barW = width / hours;
  const maxVal = Math.max(1, ...signalBuckets, ...purchaseBuckets);
  return (
    <svg viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="none" className="w-full h-20">
      {Array.from({ length: hours }).map((_, i) => {
        const sig = signalBuckets[i];
        const buy = purchaseBuckets[i];
        const sigH = (sig / maxVal) * (height - 10);
        const buyH = (buy / maxVal) * (height - 10);
        const x = i * barW;
        return (
          <g key={i}>
            {sig > 0 && <rect x={x + 1} y={height - sigH} width={barW / 2 - 1} height={sigH} fill="#10b981" opacity="0.9" />}
            {buy > 0 && <rect x={x + barW / 2} y={height - buyH} width={barW / 2 - 1} height={buyH} fill="#60a5fa" opacity="0.9" />}
          </g>
        );
      })}
      <line x1="0" y1={height - 0.5} x2={width} y2={height - 0.5} stroke="rgba(255,255,255,0.1)" strokeWidth="1" />
    </svg>
  );
}

function categorizeErrors(errors: ErrorReport[]) {
  const bySource: Record<string, ErrorReport[]> = {};
  for (const e of errors) {
    const src = e.source || "unknown";
    if (!bySource[src]) bySource[src] = [];
    bySource[src].push(e);
  }
  const hints: Record<string, { severity: Severity; hint: string }> = {
    "error-boundary": { severity: "crit", hint: "React UI crash. Check most recent deploy + browser console. Fix: revert or patch client code." },
    "api-error": { severity: "warn", hint: "API call failed. Check validator fan-out + Vercel logs. Fix: retry endpoint or check CORS/auth." },
    "network-timeout": { severity: "warn", hint: "Slow network / proxy timeout. Check Vercel edge + validator uptime. Fix: retry or bypass proxy." },
    "hook-error": { severity: "crit", hint: "React hook crashed. Likely a data shape mismatch. Fix: check subgraph schema + hook deps." },
    "purchase-failure": { severity: "crit", hint: "On-chain purchase failed. Check Escrow allowance + gas + MPC quorum." },
    "signal-failure": { severity: "crit", hint: "Signal commit failed. Check Shamir dealer + SignalCommitment paused state." },
  };
  return Object.entries(bySource).map(([source, reports]) => ({
    source,
    count: reports.length,
    severity: hints[source]?.severity ?? "warn",
    hint: hints[source]?.hint ?? "Inspect report details + route logs.",
    mostRecent: reports[0],
  })).sort((a, b) => {
    const order: Record<Severity, number> = { crit: 0, warn: 1, ok: 2 };
    return order[a.severity] - order[b.severity] || b.count - a.count;
  });
}

function summarizeAudits(audits: SubgraphRecentAudit[], totalAudits?: string) {
  const nowSec = Math.floor(Date.now() / 1000);
  const h24 = audits.filter(a => Number(a.settledAt) > nowSec - 86400);
  const h1 = audits.filter(a => Number(a.settledAt) > nowSec - 3600);
  const totalSettled = audits.length;
  const earlyExit = audits.filter(a => a.isEarlyExit).length;
  let totalFees = 0n;
  for (const a of audits) {
    try { totalFees += BigInt(a.protocolFee || "0"); } catch {}
  }
  return {
    settled24h: h24.length,
    settled1h: h1.length,
    recentSample: totalSettled,
    earlyExit,
    fees: totalFees,
    totalAll: totalAudits ?? "-",
  };
}

interface ContractStatusResult {
  status: ContractStatusResponse | null;
  error: string | null;
  probed: boolean;
}

function useContractStatus(intervalMs: number): ContractStatusResult {
  const [status, setStatus] = useState<ContractStatusResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [probed, setProbed] = useState(false);
  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        const res = await fetch("/api/admin/contracts", { credentials: "same-origin" });
        if (!res.ok) {
          if (!cancelled) {
            // Drop stale status on failure. Otherwise OnChainStatus would
            // render the last-known-good contract grid as though it were
            // fresh (the render path is `if (!status)`), silently turning
            // a post-recovery regression into invisible staleness.
            setStatus(null);
            setError(`/api/admin/contracts returned ${res.status}`);
            setProbed(true);
          }
          return;
        }
        const data = (await res.json()) as ContractStatusResponse;
        if (!cancelled) {
          setStatus(data);
          setError(null);
          setProbed(true);
        }
      } catch (e) {
        if (!cancelled) {
          setStatus(null);
          setError(e instanceof Error ? e.message : "probe threw");
          setProbed(true);
        }
      }
    }
    load();
    const id = setInterval(load, intervalMs);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, [intervalMs]);
  return { status, error, probed };
}

function addressShort(addr: string): string {
  if (!addr || addr.length < 10) return addr;
  return `${addr.slice(0, 6)}...${addr.slice(-4)}`;
}

function OnChainStatus({ status, error, probed }: ContractStatusResult) {
  if (!status) {
    // Distinguish "still probing" from "probe finished with an error". Showing
    // an endless "Probing…" spinner when the endpoint is actually 500'ing was
    // itself a form of the NASA-HQ hallucination class — silence ≠ healthy.
    if (error && probed) {
      return (
        <div className="mb-5 bg-amber-500/5 border border-amber-500/30 rounded-lg p-4">
          <div className="text-[11px] text-amber-300 uppercase tracking-wider font-semibold mb-2 flex items-center gap-2">
            <SeverityDot level="warn" /> On-Chain Status · Probe Failed
          </div>
          <div className="text-xs text-amber-200/80 font-mono">{error}</div>
          <div className="text-[10px] text-slate-500 mt-1">Contract pause state unknown. Next retry in ≤30s.</div>
        </div>
      );
    }
    return (
      <div className="mb-5 bg-white/5 border border-slate-700/50 rounded-lg p-4">
        <div className="text-[11px] text-slate-400 uppercase tracking-wider font-semibold mb-2">
          On-Chain Status · Probing…
        </div>
        <div className="text-xs text-slate-500">Querying Base RPC and contract pause state…</div>
      </div>
    );
  }

  const pausedContracts = status.contracts.filter(c => c.paused === true);
  const anyPaused = pausedContracts.length > 0;
  const chainDown = status.blockNumber === null || Boolean(status.rpcError);
  const lagWarn = status.blockLagSeconds !== null && status.blockLagSeconds > 30;

  let bannerLevel: Severity = "ok";
  let bannerMsg = `Chain healthy · block ${status.blockNumber?.toLocaleString() ?? "?"} · all contracts live`;
  if (chainDown) {
    bannerLevel = "crit";
    bannerMsg = `RPC unreachable · ${status.rpcError ?? "no block returned"}`;
  } else if (anyPaused) {
    bannerLevel = "crit";
    bannerMsg = `${pausedContracts.length} contract${pausedContracts.length !== 1 ? "s" : ""} PAUSED · ${pausedContracts.map(c => c.name).join(", ")}`;
  } else if (lagWarn) {
    bannerLevel = "warn";
    bannerMsg = `Chain lag ${status.blockLagSeconds}s — RPC may be stale`;
  }

  const bannerStyle =
    bannerLevel === "crit" ? "bg-red-500/10 border-red-500/40 text-red-200"
    : bannerLevel === "warn" ? "bg-amber-500/10 border-amber-500/40 text-amber-200"
    : "bg-green-500/10 border-green-500/20 text-green-200";

  return (
    <div className="mb-5">
      {/* Top banner */}
      <div className={`rounded-lg border ${bannerStyle} px-4 py-2 flex items-center gap-3 mb-3`}>
        <SeverityDot level={bannerLevel} />
        <div className="flex-1 text-sm font-medium">{bannerMsg}</div>
        <div className="text-[10px] font-mono text-slate-400 hidden md:block">
          chainId {status.chainId} · lag {status.blockLagSeconds ?? "?"}s · probed {status.elapsedMs}ms
        </div>
      </div>

      {/* Contract grid */}
      <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-7 gap-2">
        {status.contracts.map(c => {
          const level: Severity =
            c.paused === true ? "crit"
            : c.paused === false ? "ok"
            : "warn";
          const label =
            c.paused === true ? "PAUSED"
            : c.paused === false ? "live"
            : "unknown";
          const cellStyle =
            level === "crit" ? "border-red-500/40 bg-red-500/5"
            : level === "ok" ? "border-green-500/20 bg-green-500/[0.02]"
            : "border-amber-500/30 bg-amber-500/5";
          const labelColor =
            level === "crit" ? "text-red-300"
            : level === "ok" ? "text-green-400"
            : "text-amber-300";
          return (
            <a
              key={c.name}
              href={`${BASE_EXPLORER}/address/${c.address}`}
              target="_blank"
              rel="noopener noreferrer"
              className={`block rounded border ${cellStyle} px-2 py-1.5 hover:bg-white/5 transition-colors`}
              title={c.reason || `${c.name}: ${c.address}`}
            >
              <div className="text-[10px] text-slate-400 uppercase tracking-wider font-semibold truncate">{c.name}</div>
              <div className="flex items-baseline justify-between gap-1">
                <span className={`text-xs font-bold ${labelColor}`}>{label}</span>
                <span className="text-[9px] font-mono text-slate-500">{addressShort(c.address)}</span>
              </div>
            </a>
          );
        })}
      </div>
    </div>
  );
}

export default function MissionControl({
  validators,
  miners,
  errorReports,
  recentSignals,
  recentPurchases,
  recentAudits,
  stats,
  lastRefresh,
  dataStatus = {},
}: MissionControlProps) {
  const nowSec = Math.floor(Date.now() / 1000);
  const nowMs = Date.now();
  const onChain = useContractStatus(30_000);

  // Per-section unknown flags. A section is "unknown" when the parent's
  // fetch failed OR hasn't finished yet OR hasn't been plumbed at all
  // (undefined — cold start before the first refresh completes). ONLY a
  // confirmed "done" means "the zero is real". Otherwise we'd recreate the
  // NASA-HQ hallucination during the 1-10s gap between auth and first
  // snapshot, when dataStatus is {} and every KPI would render as green-zero.
  const isDone = (s: DataStatus | undefined) => s === "done";
  const signalsUnknown = !isDone(dataStatus.signals);
  const purchasesUnknown = !isDone(dataStatus.purchases);
  const auditsUnknown = !isDone(dataStatus.audits);
  const errorsUnknown = !isDone(dataStatus.errors);
  const subgraphUnknown = !isDone(dataStatus.subgraph);
  const validatorsUnknown = !isDone(dataStatus.validators);
  const minersUnknown = !isDone(dataStatus.miners);

  // Validator quorum: Shamir min=2, so >=4 healthy is a strong quorum, >=2 minimum
  const healthyVals = validators.filter(v => !v.error && v.status === "ok");
  const chainConnectedVals = healthyVals.filter(v => v.chain_connected && v.bt_connected);
  // Only count shares from validators that actually reported a number. If every
  // validator is unreachable (v.error set), a naive sum would render "0 held"
  // with a CRIT light, conflating "network down" with "protocol frozen at zero
  // shares". Surface the unknown state instead.
  const reportingShareVals = validators.filter(v => !v.error && typeof v.shares_held === "number");
  const sharesTotal = reportingShareVals.reduce((sum, v) => sum + v.shares_held, 0);
  const sharesUnknown = reportingShareVals.length === 0;

  const fullyOpMiners = miners.filter(m => !m.error && m.status === "ok" && m.odds_api_connected && m.bt_connected && m.version && m.version !== "-" && m.version !== "0");
  const attestCapableMiners = miners.filter(m => !m.error && m.version && parseInt(m.version, 10) >= 512);

  // 1h error count (errorReports timestamp is ISO string)
  const errors1h = errorReports.filter(e => {
    const t = Date.parse(e.timestamp);
    return !isNaN(t) && t > nowMs - 3600_000;
  });
  const errors24h = errorReports.filter(e => {
    const t = Date.parse(e.timestamp);
    return !isNaN(t) && t > nowMs - 86400_000;
  });

  // 24h activity windows
  const signals24h = recentSignals.filter(s => Number(s.createdAt) > nowSec - 86400);
  const signals1h = recentSignals.filter(s => Number(s.createdAt) > nowSec - 3600);
  const purchases24h = recentPurchases.filter(p => Number(p.purchasedAt) > nowSec - 86400);
  const purchases1h = recentPurchases.filter(p => Number(p.purchasedAt) > nowSec - 3600);
  let volume24h = 0n;
  for (const p of purchases24h) {
    try { volume24h += BigInt(p.notional || "0"); } catch {}
  }

  const auditSummary = summarizeAudits(recentAudits, stats?.totalAudits);

  // Traffic-light decisions. "unknown" (section failed to fetch) → warn, not
  // crit: we don't know if the thing is broken, only that we can't see it.
  const validatorLevel: Severity =
    validatorsUnknown ? "warn"
    : chainConnectedVals.length >= 4 ? "ok"
    : chainConnectedVals.length >= 2 ? "warn"
    : "crit";
  const minerLevel: Severity =
    minersUnknown ? "warn"
    : fullyOpMiners.length >= 3 ? "ok"
    : fullyOpMiners.length >= 1 ? "warn"
    : "crit";
  const sharesLevel: Severity =
    sharesUnknown ? "warn"
    : sharesTotal >= 1000 ? "ok"
    : sharesTotal > 0 ? "warn"
    : "crit";
  const errorLevel: Severity =
    errorsUnknown ? "warn"
    : errors1h.length === 0 ? "ok"
    : errors1h.length <= 5 ? "warn"
    : "crit";
  const attestLevel: Severity =
    minersUnknown ? "warn"
    : attestCapableMiners.length >= 3 ? "ok"
    : attestCapableMiners.length >= 1 ? "warn"
    : "crit";

  // On-chain contributes: any contract paused = crit; RPC lag > 30s = warn
  const onChainLevel: Severity = (() => {
    if (!onChain.status) return "warn";
    if (onChain.status.rpcError || onChain.status.blockNumber === null) return "crit";
    if (onChain.status.contracts.some(c => c.paused === true)) return "crit";
    if ((onChain.status.blockLagSeconds ?? 0) > 30) return "warn";
    return "ok";
  })();

  const overall: Severity =
    [validatorLevel, minerLevel, sharesLevel, errorLevel, attestLevel, onChainLevel].some(l => l === "crit") ? "crit"
    : [validatorLevel, minerLevel, sharesLevel, errorLevel, attestLevel, onChainLevel].some(l => l === "warn") ? "warn"
    : "ok";

  const overallLabel =
    overall === "ok" ? "ALL SYSTEMS NOMINAL"
    : overall === "warn" ? "DEGRADED"
    : "CRITICAL";
  const overallColor =
    overall === "ok" ? "text-green-400"
    : overall === "warn" ? "text-amber-400"
    : "text-red-400 animate-pulse";

  const sigBuckets = bucketByHour(recentSignals.map(s => Number(s.createdAt)));
  const buyBuckets = bucketByHour(recentPurchases.map(p => Number(p.purchasedAt)));

  const categorized = categorizeErrors(errors24h);
  const ageStr = lastRefresh ? `${Math.floor((nowMs - lastRefresh.getTime()) / 1000)}s ago` : "pending";

  return (
    <div className="mb-8 bg-gradient-to-br from-[#0a0f1e] via-slate-900 to-slate-950 rounded-xl border border-slate-700/50 p-6 text-white shadow-2xl">
      {/* Header */}
      <div className="flex items-center justify-between mb-5 pb-4 border-b border-slate-700/50">
        <div className="flex items-center gap-3">
          <div className="text-[10px] font-mono text-slate-500 uppercase tracking-widest">Djinn · Mission Control</div>
          <span className="text-slate-700">|</span>
          <div className={`text-sm font-bold tracking-wider ${overallColor}`}>
            <SeverityDot level={overall} /> <span className="ml-2">{overallLabel}</span>
          </div>
          <span
            className="px-2 py-0.5 rounded-sm text-[10px] font-mono font-bold tracking-widest bg-amber-500/20 text-amber-300 border border-amber-500/40"
            title="This dashboard reflects Base Sepolia testnet data. Mainnet launch pending — see MAINNET_BLOCKERS.md."
          >
            TESTNET · BASE SEPOLIA
          </span>
        </div>
        <div className="text-[10px] font-mono text-slate-500">
          last sync: {ageStr}
        </div>
      </div>

      {/* On-chain contract status — first, because a paused contract trumps everything */}
      <OnChainStatus status={onChain.status} error={onChain.error} probed={onChain.probed} />

      {/* Traffic lights row */}
      <div className="grid grid-cols-2 md:grid-cols-5 gap-3 mb-5">
        <StatusLight
          label="Validator Quorum"
          level={validatorLevel}
          detail={validatorsUnknown ? "— (fetch failed)" : `${chainConnectedVals.length}/${validators.length} online`}
          hint={validatorsUnknown ? "Admin page failed to fetch validator health this cycle; quorum state unknown." : "Healthy + chain + BT connected. Shamir min=2; need >=4 for robust quorum."}
        />
        <StatusLight
          label="Miner Pool"
          level={minerLevel}
          detail={minersUnknown ? "— (fetch failed)" : `${fullyOpMiners.length}/${miners.length} operational`}
          hint={minersUnknown ? "Admin page failed to fetch miner health this cycle; pool state unknown." : "Healthy + Odds API + BT + Djinn-version reported"}
        />
        <StatusLight
          label="Key Shares"
          level={sharesLevel}
          detail={sharesUnknown ? "— (no validator reporting)" : `${sharesTotal.toLocaleString()} held`}
          hint={sharesUnknown ? "Every validator unreachable; unable to read Shamir share count." : "Total Shamir key shares across all validators. Zero means protocol is frozen."}
        />
        <StatusLight
          label="Attestation"
          level={attestLevel}
          detail={minersUnknown ? "— (fetch failed)" : `${attestCapableMiners.length} capable`}
          hint={minersUnknown ? "Miner health fetch failed; attestation capability unknown." : "Miners on v512+ with TLSNotary prover support"}
        />
        <StatusLight
          label="Errors (1h)"
          level={errorLevel}
          detail={errorsUnknown ? "— (fetch failed)" : `${errors1h.length} reports`}
          hint={errorsUnknown ? "Error-report fetch failed; unable to count recent crashes." : errors1h.length > 0 ? "See Error Severity panel below for categorization" : "No user-facing errors reported"}
        />
      </div>

      {/* 24h KPIs */}
      <div className="grid grid-cols-2 md:grid-cols-5 gap-3 mb-5">
        <KpiTile
          label="Signals / 24h"
          value={signalsUnknown ? "—" : signals24h.length.toString()}
          sub={signalsUnknown ? "fetch failed" : signals1h.length > 0 ? `+${signals1h.length} in last hour` : "none in last hour"}
          accent="green"
        />
        <KpiTile
          label="Purchases / 24h"
          value={purchasesUnknown ? "—" : purchases24h.length.toString()}
          sub={purchasesUnknown ? "fetch failed" : purchases1h.length > 0 ? `+${purchases1h.length} in last hour` : "none in last hour"}
          accent="blue"
        />
        <KpiTile
          label="Volume / 24h"
          value={purchasesUnknown ? "—" : volume24h > 0n ? formatUsdc(volume24h) : "-"}
          sub={purchasesUnknown ? "fetch failed" : "USDC notional"}
          accent="purple"
        />
        <KpiTile
          label="Audits Settled"
          value={auditsUnknown ? "—" : auditSummary.settled24h.toString()}
          sub={auditsUnknown ? "fetch failed" : `${auditSummary.settled1h} in last hour`}
          accent="orange"
        />
        <KpiTile
          label="Total Signals"
          value={subgraphUnknown ? "—" : stats?.totalSignals ?? "-"}
          sub={subgraphUnknown ? "subgraph fetch failed" : `${stats?.totalPurchases ?? "-"} purchases lifetime`}
          accent="green"
        />
      </div>

      {/* Activity sparkline */}
      <div className="mb-5 bg-white/5 rounded-lg p-4">
        <div className="flex items-baseline justify-between mb-2">
          <div className="text-[11px] text-slate-400 uppercase tracking-wider font-semibold">
            Last 24h Activity · <span className="text-green-400">signals</span> / <span className="text-blue-400">purchases</span>
          </div>
          <div className="text-[10px] text-slate-500 font-mono">1h buckets, -24h → now</div>
        </div>
        <Sparkline signalBuckets={sigBuckets} purchaseBuckets={buyBuckets} />
      </div>

      {/* Audit breakdown + errors side-by-side */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {/* Audit breakdown */}
        <div className="bg-white/5 rounded-lg p-4">
          <div className="text-[11px] text-slate-400 uppercase tracking-wider font-semibold mb-3">
            Audit Settlement Pipeline
          </div>
          <div className="space-y-2">
            <div className="flex justify-between items-baseline">
              <span className="text-slate-300 text-sm">Settled (lifetime)</span>
              <span className="font-mono text-lg font-bold text-white">{subgraphUnknown ? "—" : auditSummary.totalAll}</span>
            </div>
            <div className="flex justify-between items-baseline">
              <span className="text-slate-300 text-sm">Settled (24h)</span>
              <span className="font-mono text-lg font-bold text-orange-300">{auditsUnknown ? "—" : auditSummary.settled24h}</span>
            </div>
            <div className="flex justify-between items-baseline">
              <span className="text-slate-300 text-sm">Early-exit (recent)</span>
              <span className="font-mono text-sm text-slate-400">{auditsUnknown ? "—" : `${auditSummary.earlyExit} / ${auditSummary.recentSample}`}</span>
            </div>
            <div className="flex justify-between items-baseline pt-2 border-t border-slate-700/50">
              <span className="text-slate-300 text-sm">Protocol fees (recent)</span>
              <span className="font-mono text-sm text-green-400">
                {auditsUnknown ? "—" : auditSummary.fees > 0n ? formatUsdc(auditSummary.fees) : "-"}
              </span>
            </div>
          </div>
          {!auditsUnknown && !subgraphUnknown && auditSummary.settled24h === 0 && Number(stats?.totalSignals ?? "0") > 0 && (
            <div className="mt-3 text-[10px] text-amber-300 bg-amber-500/10 border border-amber-500/20 rounded p-2">
              No settlements in 24h. Check OutcomeVoting.paused() + validator /v1/audit/summary.
            </div>
          )}
        </div>

        {/* Error categorization */}
        <div className="bg-white/5 rounded-lg p-4">
          <div className="text-[11px] text-slate-400 uppercase tracking-wider font-semibold mb-3">
            Error Severity · 24h
          </div>
          {errorsUnknown ? (
            <div className="text-amber-300 text-sm py-4 text-center">
              Error-report fetch failed. Unknown whether users are crashing.
            </div>
          ) : categorized.length === 0 ? (
            <div className="text-green-400 text-sm py-4 text-center">No errors reported in the last 24h.</div>
          ) : (
            <div className="space-y-2">
              {categorized.slice(0, 4).map(c => (
                <div key={c.source} className="group">
                  <div className="flex items-center justify-between gap-2">
                    <div className="flex items-center gap-2 min-w-0 flex-1">
                      <SeverityDot level={c.severity} />
                      <span className="text-sm text-slate-200 font-medium truncate">{c.source}</span>
                      <span className="text-xs text-slate-500 font-mono">× {c.count}</span>
                    </div>
                  </div>
                  <div className="text-[10px] text-slate-500 ml-4 mt-0.5 leading-snug">{c.hint}</div>
                </div>
              ))}
              {categorized.length > 4 && (
                <div className="text-[10px] text-slate-500 text-center pt-1">+{categorized.length - 4} more categories · see Error Reports below</div>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
