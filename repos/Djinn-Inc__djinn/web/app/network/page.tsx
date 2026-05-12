"use client";

import { useCallback, useMemo, useState } from "react";
import Image from "next/image";
import Link from "next/link";
import { useRouter } from "next/navigation";
import dynamic from "next/dynamic";
import { useQuery } from "@tanstack/react-query";
import Tooltip from "@/components/Tooltip";
import StatCard from "@/components/network/StatCard";
import MetricDropdown from "@/components/network/MetricDropdown";
import OvBadge, { CANONICAL_OV } from "@/components/network/OvBadge";
import ShamirBadge from "@/components/network/ShamirBadge";
import SubmitBadge from "@/components/network/SubmitBadge";
import CopyTableButton, { useCopyTable } from "@/components/CopyTableButton";
import { formatTao, normalizedToPercent, useSortable, formatRelativeAge, ageClass, type SortDir } from "@/components/network/helpers";
import { fetchNetworkStatus } from "@/lib/networkStatus";
import { resolveVersion, useVersionManifest, versionDrifts, type VersionManifest } from "@/lib/versionManifest";

// Lazy-load chart (needs canvas/window)
const IncentiveChart = dynamic(() => import("@/components/network/IncentiveChart"), {
  ssr: false,
  loading: () => <div className="h-80 bg-slate-50 rounded-lg animate-pulse" />,
});

// Lazy-load scoring matrix (heavy, fetches own data)
const ScoringMatrix = dynamic(() => import("@/components/network/ScoringMatrix"), {
  ssr: false,
  loading: () => <div className="h-40 bg-slate-50 rounded-lg animate-pulse" />,
});

// ---------- Types ----------

interface ValidatorData {
  uid: number;
  ip: string;
  port: number;
  stake: string;
  ss58Hotkey?: string;
  coldkey?: string;
  validatorTrust: number;
  egressIps?: string[];
  // Block of last weight submission on the Bittensor chain. Distinct
  // from API liveness — a validator can be alive on chain (still
  // setting weights, still earning emissions) while their HTTP API
  // is unreachable.
  lastUpdateBlock?: number;
  chainBlocksSinceUpdate?: number | null;
  health: {
    status: string;
    version: string;
    git_sha?: string;
    shares_held?: number;
    chain_connected?: boolean;
    bt_connected?: boolean;
    settlement_registered?: boolean | null;
    settlement_contract?: string | null;
    settlement_diagnosis?: string | null;
    shamir_threshold?: number | null;
    batch_settlement_http?: boolean | null;
    batch_settlement_http_submit?: boolean | null;
    git_commit_ts?: number | null;
    process_started_ts?: number | null;
  } | null;
}

interface MinerData {
  uid: number;
  ip: string;
  incentive: number;
  emission: string;
  weight?: number;
  attestations_total?: number;
  attestations_valid?: number;
  lifetime_attestations?: number;
  lifetime_attestations_valid?: number;
  proactive_proof_verified?: boolean;
  uptime?: number;
  accuracy?: number;
}

interface Summary {
  totalValidators: number;
  totalMiners: number;
  validatorsHealthy: number;
  validatorsHoldingShares: number;
  totalShares: number;
  highestVersion: number;
  timestamp: number;
  uniqueIps: number;
  gini: number;
  burnPercent: number;
}

// ---------- Small components ----------

function StatusBadge({ status }: { status: string }) {
  const color =
    status === "ok"
      ? "bg-emerald-100 text-emerald-700"
      : status === "unreachable"
        ? "bg-slate-100 text-slate-500"
        : "bg-red-100 text-red-700";
  return (
    <span className={`text-[11px] font-medium px-2 py-0.5 rounded-full ${color}`}>
      {status === "ok" ? "Healthy" : status === "unreachable" ? "Offline" : "Error"}
    </span>
  );
}

// Chain liveness: did this validator submit weights recently? The block
// threshold is generous (≈6h on SN103's 12s blocks / 360-block tempo).
// Validators who haven't submitted in this window have probably exited.
const CHAIN_ALIVE_BLOCK_THRESHOLD = 1800;

function ChainAliveBadge({ blocksSince }: { blocksSince: number | null | undefined }) {
  if (blocksSince === null || blocksSince === undefined) {
    return <span className="text-slate-300">-</span>;
  }
  const alive = blocksSince <= CHAIN_ALIVE_BLOCK_THRESHOLD;
  const minutesAgo = Math.round(blocksSince * 12 / 60);
  const label = alive ? "live" : "stale";
  const color = alive ? "bg-emerald-100 text-emerald-700" : "bg-amber-100 text-amber-700";
  const title = `Last weight update ${minutesAgo}m ago (${blocksSince} blocks)`;
  return (
    <span className={`text-[11px] font-medium px-2 py-0.5 rounded-full ${color}`} title={title}>
      {label}
    </span>
  );
}

function Check({ ok }: { ok: boolean | undefined }) {
  if (ok === undefined) return <span className="text-slate-300">-</span>;
  return ok ? <span className="text-emerald-500">&#10003;</span> : <span className="text-red-400">&#10005;</span>;
}

function SortArrow({ active, dir }: { active: boolean; dir: SortDir }) {
  if (!active) return <span className="text-slate-300 ml-0.5">&#8597;</span>;
  return <span className="text-slate-600 ml-0.5">{dir === "asc" ? "\u25B2" : "\u25BC"}</span>;
}

// ---------- Tables ----------

function lookupName(names: Record<string, string>, ss58Hotkey?: string, coldkey?: string): string | null {
  if (!ss58Hotkey && !coldkey) return null;
  // The delegate map uses hex keys; ss58Hotkey needs conversion.
  // But the map may also contain ss58 keys directly. Check both.
  for (const key of [ss58Hotkey, coldkey]) {
    if (key && names[key]) return names[key];
  }
  return null;
}

function ValidatorTable({ validators, names, manifest }: { validators: ValidatorData[]; names: Record<string, string>; manifest: VersionManifest | undefined }) {
  const router = useRouter();
  const { ref: tableRef, copy, copied } = useCopyTable();
  const getVal = useCallback((v: ValidatorData, key: string): number | string => {
    switch (key) {
      case "uid": return v.uid;
      case "status": return v.health?.status === "ok" ? 1 : 0;
      case "version": {
        const resolved = resolveVersion(manifest, v.health?.git_sha);
        const source = resolved ? resolved.replace(/^v/, "").replace(/\+$/, "") : v.health?.version || "0";
        return parseInt(source, 10);
      }
      case "stake": return parseFloat(v.stake);
      case "vtrust": return v.validatorTrust;
      case "shares": return v.health?.shares_held ?? 0;
      case "deployed": return v.health?.git_commit_ts ?? 0;
      default: return 0;
    }
  }, [manifest]);
  const { sorted, sortKey, sortDir, toggle } = useSortable(validators, "stake", "desc", getVal);
  if (!validators.length) return <p className="text-sm text-slate-400 py-4 px-3">No validators discovered.</p>;
  const Th = ({ k, children, align }: { k: string; children: React.ReactNode; align?: string }) => (
    <th className={`px-3 py-2 cursor-pointer select-none hover:text-slate-600 ${align || ""}`} onClick={() => toggle(k)}>
      {children}<SortArrow active={sortKey === k} dir={sortDir} />
    </th>
  );
  return (
    <div className="overflow-x-auto" ref={tableRef}>
      <div className="flex justify-end px-3 pt-2">
        <CopyTableButton onClick={copy} copied={copied} />
      </div>
      <table className="w-full text-sm">
        <thead>
          <tr className="text-left text-xs text-slate-400 uppercase tracking-wide border-b">
            <Th k="uid">UID</Th>
            <th className="px-3 py-2">Name</th>
            <th className="px-3 py-2 text-center" title="API liveness: can buyers reach this validator's HTTP /health endpoint?">API</th>
            <th className="px-3 py-2 text-center" title="Chain liveness: did this validator submit weights to subtensor in the last ~6h? A validator can be alive on chain (collecting emissions) while their HTTP API is down.">Chain</th>
            <Th k="version" align="text-right">Version</Th>
            <Th k="deployed" align="text-right">Deployed</Th>
            <Th k="stake" align="text-right">Stake</Th>
            <Th k="vtrust" align="text-right">VTrust</Th>
            <Th k="shares" align="text-right">Shares</Th>
            <th className="px-3 py-2 text-center" title="Registered on canonical OutcomeVoting for settlement quorum">OV</th>
            <th className="px-3 py-2 text-center"><Tooltip term="Shamir's Secret Sharing">Shamir</Tooltip></th>
            <th className="px-3 py-2 text-center" title="Batch-settlement submit state. green=submit-on-chain, amber=shadow-observe-only, off=flag not set. P0-01 closure needs 4+ validators at submit.">Submit</th>
            <th className="px-3 py-2 text-center" title="Chain RPC connection from this validator's process (in /health). Distinct from the Chain column to the left, which probes the Bittensor weight ledger.">RPC</th>
            <th className="px-3 py-2 text-center" title="Bittensor wallet/subtensor connection from this validator's process (in /health).">BT</th>
          </tr>
        </thead>
        <tbody>
          {sorted.map((v) => {
            const sha = v.health?.git_sha;
            const reported = v.health?.version;
            const effective = resolveVersion(manifest, sha);
            const drifts = versionDrifts(reported, effective);
            const title = sha
              ? drifts
                ? `git ${sha} — actually ${effective} (validator reports v${reported})`
                : `git ${sha}${effective ? ` (${effective})` : ""}`
              : undefined;
            return (
            <tr key={v.uid} className="border-b border-slate-100 hover:bg-slate-50 cursor-pointer" onClick={() => router.push(`/network/validator/${v.uid}`)}>
              <td className="px-3 py-2 font-mono font-medium">
                <Link href={`/network/validator/${v.uid}`} className="text-blue-600 hover:text-blue-800 hover:underline" onClick={(e) => e.stopPropagation()}>
                  {v.uid}
                </Link>
              </td>
              <td className="px-3 py-2 text-slate-700 text-xs truncate max-w-[140px]">{lookupName(names, v.ss58Hotkey, v.coldkey) || <span className="text-slate-300">-</span>}</td>
              <td className="px-3 py-2 text-center"><StatusBadge status={v.health?.status || "unreachable"} /></td>
              <td className="px-3 py-2 text-center"><ChainAliveBadge blocksSince={v.chainBlocksSinceUpdate} /></td>
              <td className="px-3 py-2 text-right font-mono text-slate-600" title={title}>
                {drifts ? (
                  <span className="text-amber-600" title={title}>{effective}</span>
                ) : (
                  reported || "-"
                )}
                {sha && <span className="text-slate-400 text-[10px] ml-1">{sha.slice(0, 7)}</span>}
              </td>
              <td className={`px-3 py-2 text-right text-xs ${ageClass(v.health?.git_commit_ts)}`} title={v.health?.git_commit_ts ? new Date(v.health.git_commit_ts * 1000).toISOString() : "non-git install or unknown"}>
                {formatRelativeAge(v.health?.git_commit_ts)}
              </td>
              <td className="px-3 py-2 text-right">{formatTao(v.stake)}</td>
              <td className="px-3 py-2 text-right">{normalizedToPercent(v.validatorTrust)}</td>
              <td className="px-3 py-2 text-right font-mono">{v.health?.shares_held ?? "-"}</td>
              <td className="px-3 py-2 text-center"><OvBadge registered={v.health?.settlement_registered} contract={v.health?.settlement_contract} diagnosis={v.health?.settlement_diagnosis} /></td>
              <td className="px-3 py-2 text-center"><ShamirBadge threshold={v.health?.shamir_threshold} /></td>
              <td className="px-3 py-2 text-center"><SubmitBadge runtime={v.health?.batch_settlement_http} submit={v.health?.batch_settlement_http_submit} /></td>
              <td className="px-3 py-2 text-center"><Check ok={v.health?.chain_connected} /></td>
              <td className="px-3 py-2 text-center"><Check ok={v.health?.bt_connected} /></td>
            </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function AttestBadge({ valid, total, proactive }: { valid: number; total: number; proactive?: boolean }) {
  if (total === 0 && !proactive) return <span className="text-slate-300">-</span>;
  const rate = total > 0 ? valid / total : 0;
  const color =
    proactive && valid === 0
      ? "text-amber-600" // proactive proof only, no challenge results yet
      : rate >= 0.8
        ? "text-emerald-600"
        : rate >= 0.5
          ? "text-amber-600"
          : total > 0
            ? "text-red-500"
            : "text-slate-400";
  return (
    <span className={`font-mono ${color}`}>
      {valid}/{total}
      {proactive && valid === 0 && <span className="text-[10px] ml-1" title="Proactive proof verified">P</span>}
    </span>
  );
}

function MinerTable({ miners }: { miners: MinerData[] }) {
  const router = useRouter();
  const { ref: tableRef, copy, copied } = useCopyTable();
  const getVal = useCallback((m: MinerData, key: string): number | string => {
    switch (key) {
      case "uid": return m.uid;
      case "ip": return m.ip;
      case "incentive": return m.incentive;
      case "emission": return parseFloat(m.emission);
      case "weight": return m.weight ?? 0;
      case "attest": {
        const t = m.lifetime_attestations ?? m.attestations_total ?? 0;
        const v = m.lifetime_attestations_valid ?? m.attestations_valid ?? 0;
        return t > 0 ? v / t : -1;
      }
      case "uptime": return m.uptime ?? 0;
      default: return 0;
    }
  }, []);
  const { sorted, sortKey, sortDir, toggle } = useSortable(miners, "incentive", "desc", getVal);
  if (!miners.length) return <p className="text-sm text-slate-400 py-4 px-3">No miners discovered.</p>;
  const hasScoring = miners.some((m) => m.weight !== undefined);
  const Th = ({ k, children, align }: { k: string; children: React.ReactNode; align?: string }) => (
    <th className={`px-3 py-2 cursor-pointer select-none hover:text-slate-600 ${align || ""}`} onClick={() => toggle(k)}>
      {children}<SortArrow active={sortKey === k} dir={sortDir} />
    </th>
  );
  return (
    <div className="overflow-x-auto" ref={tableRef}>
      <div className="flex justify-end px-3 pt-2">
        <CopyTableButton onClick={copy} copied={copied} />
      </div>
      <table className="w-full text-sm">
        <thead>
          <tr className="text-left text-xs text-slate-400 uppercase tracking-wide border-b">
            <Th k="uid">UID</Th>
            <Th k="ip">IP</Th>
            <Th k="incentive" align="text-right">Incentive</Th>
            <Th k="emission" align="text-right">Emission</Th>
            {hasScoring && <Th k="weight" align="text-right">Weight</Th>}
            {hasScoring && <Th k="uptime" align="text-right">Uptime</Th>}
            {hasScoring && <Th k="attest" align="text-right">Attest</Th>}
          </tr>
        </thead>
        <tbody>
          {sorted.map((m) => {
            const aTotal = m.lifetime_attestations ?? m.attestations_total ?? 0;
            const aValid = m.lifetime_attestations_valid ?? m.attestations_valid ?? 0;
            return (
              <tr key={m.uid} className="border-b border-slate-100 hover:bg-slate-50 cursor-pointer" onClick={() => router.push(`/network/miner/${m.uid}`)}>
                <td className="px-3 py-2 font-mono font-medium">
                  <Link href={`/network/miner/${m.uid}`} className="text-blue-600 hover:text-blue-800 hover:underline" onClick={(e) => e.stopPropagation()}>
                    {m.uid}
                  </Link>
                </td>
                <td className="px-3 py-2 font-mono text-xs text-slate-500">{m.ip !== "0.0.0.0" ? m.ip : "-"}</td>
                <td className="px-3 py-2 text-right">{normalizedToPercent(m.incentive)}</td>
                <td className="px-3 py-2 text-right font-mono">{formatTao(m.emission)}</td>
                {hasScoring && (
                  <td className="px-3 py-2 text-right font-mono">
                    {m.weight !== undefined ? m.weight.toFixed(4) : "-"}
                  </td>
                )}
                {hasScoring && (
                  <td className="px-3 py-2 text-right">
                    {m.uptime !== undefined ? `${(m.uptime * 100).toFixed(0)}%` : "-"}
                  </td>
                )}
                {hasScoring && (
                  <td className="px-3 py-2 text-right">
                    <AttestBadge valid={aValid} total={aTotal} proactive={m.proactive_proof_verified} />
                  </td>
                )}
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

// ---------- Main Page ----------

const METRIC_OPTIONS = [
  { value: "incentive", label: "Incentive" },
  { value: "emission", label: "Emission" },
];

export default function NetworkPage() {
  const [metric, setMetric] = useState<"incentive" | "emission">("incentive");
  const [showAll, setShowAll] = useState(false);

  const { data, isLoading: loading } = useQuery({
    queryKey: ["network-status"],
    queryFn: () => fetchNetworkStatus(),
    staleTime: 60_000,
    refetchInterval: 120_000,
    refetchOnWindowFocus: false,
  });

  const { data: manifest } = useVersionManifest();

  const { data: delegateNames = {} } = useQuery<Record<string, string>>({
    queryKey: ["delegates"],
    queryFn: async () => {
      const r = await fetch("/api/delegates");
      if (!r.ok) return {};
      const ct = r.headers.get("content-type") ?? "";
      if (!ct.includes("application/json")) return {};
      return (await r.json()) as Record<string, string>;
    },
    staleTime: 10 * 60_000,
    refetchOnWindowFocus: false,
  });

  const lastUpdate = useMemo(() => {
    if (!data?.summary?.timestamp) return "";
    return new Date(data.summary.timestamp).toLocaleTimeString();
  }, [data?.summary?.timestamp]);

  if (loading) {
    return (
      <div className="max-w-6xl mx-auto py-12 text-center">
        <div className="animate-spin w-8 h-8 border-2 border-slate-300 border-t-slate-600 rounded-full mx-auto mb-4" />
        <p className="text-slate-500">Loading network status...</p>
      </div>
    );
  }

  if (!data?.summary) {
    return (
      <div className="max-w-6xl mx-auto py-12 text-center">
        <p className="text-slate-500">Network data unavailable. Try again shortly.</p>
      </div>
    );
  }

  const s = data.summary;

  // Quorum = validators that are both registered AND on canonical OV.
  // Settlement requires ceil(2/3 * total) of writing validators to vote.
  const effectiveSigners = data.validators.filter(
    (v) =>
      v.health?.settlement_registered === true &&
      (v.health?.settlement_contract ?? "").toLowerCase() === CANONICAL_OV,
  ).length;
  const quorumRequired = Math.ceil((2 * s.totalValidators) / 3);
  const quorumOk = effectiveSigners >= quorumRequired;

  return (
    <div className="max-w-6xl mx-auto">
      {/* Header */}
      <div className="mb-8">
        <div className="flex items-center gap-3 mb-2">
          <Image src="/djinn-logo.png" alt="Djinn" width={36} height={36} />
          <h1 className="text-2xl font-bold text-slate-900">Network Status</h1>
        </div>
        <p className="text-slate-500">
          Live infrastructure status for Bittensor Subnet 103.
          {lastUpdate && <span className="text-slate-400 ml-2">Updated {lastUpdate}</span>}
        </p>
      </div>

      {/* Summary cards */}
      <div className="grid grid-cols-2 sm:grid-cols-6 gap-3 mb-8">
        <StatCard label="Miners" value={String(s.totalMiners)} sub="registered" />
        <StatCard label="Unique IPs" value={String(s.uniqueIps)} sub={`${s.totalMiners - s.uniqueIps} shared`} />
        <StatCard label="Gini" value={s.gini.toFixed(3)} sub="incentive concentration" />
        <StatCard label="Burn" value={`${s.burnPercent}%`} sub="to UID 0" />
        <StatCard
          label="Validators"
          value={`${s.validatorsHealthy}/${s.totalValidators}`}
          sub="healthy"
          href="validators-section"
        />
        <StatCard
          label="Quorum"
          value={`${effectiveSigners}/${quorumRequired}`}
          sub={quorumOk ? "can settle" : "below threshold"}
          tone={quorumOk ? "ok" : "warn"}
        />
      </div>

      {/* Incentive curve chart */}
      <section className="mb-8">
        <div className="card">
          <div className="flex items-center justify-between mb-4">
            <div>
              <h2 className="text-lg font-semibold text-slate-900">Miner Rank</h2>
              <p className="text-sm text-slate-500">
                Sorted by {metric}, color-coded by IP cluster
              </p>
            </div>
            <div className="flex items-center gap-3">
              <MetricDropdown
                options={METRIC_OPTIONS}
                selected={metric}
                onChange={(v) => setMetric(v as "incentive" | "emission")}
              />
              <button
                onClick={() => setShowAll(!showAll)}
                className="text-xs text-slate-500 hover:text-slate-700 transition-colors"
              >
                {showAll ? "Top 50" : `All ${s.totalMiners}`}
              </button>
            </div>
          </div>
          <IncentiveChart
            miners={data.miners}
            ipClusters={data.ipClusters}
            metric={metric}
            showAll={showAll}
          />
        </div>
      </section>

      {/* Scoring Matrix */}
      <section className="mb-8">
        <h2 className="text-lg font-semibold text-slate-900 mb-3">Scoring Matrix</h2>
        <p className="text-sm text-slate-500 mb-3">
          Each cell shows how a validator (row) scores a miner (column). Color = weight relative to that validator&apos;s median.
        </p>
        <div className="card p-4 overflow-hidden">
          <ScoringMatrix />
        </div>
      </section>

      {/* Miner table */}
      <section className="mb-8">
        <h2 className="text-lg font-semibold text-slate-900 mb-3">
          Miners <span className="text-sm font-normal text-slate-400">{s.totalMiners} registered</span>
        </h2>
        <div className="card p-0 overflow-hidden">
          <MinerTable miners={data.miners} />
        </div>
      </section>

      {/* Validator table */}
      <section id="validators-section" className="mb-8 scroll-mt-4">
        <h2 className="text-lg font-semibold text-slate-900 mb-3">
          Validators <span className="text-sm font-normal text-slate-400">{s.validatorsHealthy}/{s.totalValidators} healthy</span>
        </h2>
        <div className="card p-0 overflow-hidden">
          <ValidatorTable validators={data.validators} names={delegateNames} manifest={manifest} />
        </div>
      </section>

    </div>
  );
}
