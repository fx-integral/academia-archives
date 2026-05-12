"use client";

import { useCallback } from "react";
import Image from "next/image";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import StatCard from "@/components/network/StatCard";
import { formatTao, normalizedToPercent, useSortable, formatRelativeAge, ageClass, type SortDir } from "@/components/network/helpers";
import { fetchNetworkValidator, type NetworkValidatorDetail } from "@/lib/networkStatus";
import { resolveVersion, useVersionManifest, versionDrifts } from "@/lib/versionManifest";

// ---------- Types ----------

interface MinerRow {
  uid: number;
  hotkey: string;
  status: string;
  weight: number;
  uptime: number;
  accuracy: number;
  queries_total: number;
  queries_correct: number;
  attestations_total: number;
  attestations_valid: number;
  lifetime_attestations: number;
  lifetime_attestations_valid: number;
  proactive_proof_verified: boolean;
  notary_duties_assigned: number;
  notary_duties_completed: number;
  notary_reliability: number;
}

interface Health {
  status: string;
  version: string;
  git_sha?: string;
  uid?: number;
  shares_held?: number;
  pending_outcomes?: number;
  chain_connected?: boolean;
  bt_connected?: boolean;
  attest_capable?: boolean;
  settlement_registered?: boolean | null;
  settlement_contract?: string | null;
  settlement_diagnosis?: string | null;
  settlement_remediation?: string | null;
  shamir_threshold?: number | null;
  audit_min_batch_size?: number | null;
  batch_settlement_http?: boolean | null;
  batch_settlement_http_submit?: boolean | null;
  git_commit_ts?: number | null;
  process_started_ts?: number | null;
  // Self-detected outbound IP from a public reflector (api.ipify.org).
  // Operator diagnostic: distinct from the axon IP advertised on the
  // metagraph and from the egress commitment consumed by miners.
  egress_ip_self_reported?: string | null;
}

interface Metagraph {
  ip: string;
  port: number;
  stake: string;
  incentive: number;
  emission: string;
  validatorTrust: number;
  // On-chain Bittensor commitment: validator-published outbound IPs
  // (auto-detected each epoch + env override). Empty when validator
  // hasn't published, or detected egress IP equals the axon IP and
  // the axon-match skip suppressed the write.
  egressIps?: string[];
  // Block of last on-chain weight submission. Populated when this
  // validator's metagraph snapshot was returned by the bootstrap
  // peer (v1737+). Distinguishes weight-only validators (chain-alive
  // but HTTP-dead) from genuinely-offline ones.
  lastUpdateBlock?: number;
  chainBlocksSinceUpdate?: number | null;
}

// ---------- Small components ----------

function SortArrow({ active, dir }: { active: boolean; dir: SortDir }) {
  if (!active) return <span className="text-slate-300 ml-0.5">&#8597;</span>;
  return <span className="text-slate-600 ml-0.5">{dir === "asc" ? "\u25B2" : "\u25BC"}</span>;
}

function StatusDot({ ok }: { ok: boolean }) {
  return (
    <span className={`inline-block w-2 h-2 rounded-full ${ok ? "bg-emerald-400" : "bg-slate-300"}`} />
  );
}

function AttestCell({ valid, total, proactive }: { valid: number; total: number; proactive: boolean }) {
  if (total === 0 && !proactive) return <span className="text-slate-300">-</span>;
  const rate = total > 0 ? valid / total : 0;
  const color =
    proactive && total === 0
      ? "text-amber-600"
      : rate >= 0.8
        ? "text-emerald-600"
        : rate >= 0.5
          ? "text-amber-600"
          : total > 0
            ? "text-red-500"
            : "text-slate-400";
  return (
    <div>
      <span className={`font-mono ${color}`}>{valid}/{total}</span>
      {proactive && total === 0 && (
        <span className="text-[10px] text-amber-500 ml-1" title="Proactive proof verified">P</span>
      )}
      {total > 0 && (
        <span className="text-[10px] text-slate-400 ml-1">
          ({(rate * 100).toFixed(0)}%)
        </span>
      )}
    </div>
  );
}

// ---------- Miner Table ----------

function MinerScoringTable({ miners }: { miners: MinerRow[] }) {
  const getVal = useCallback((m: MinerRow, key: string): number | string => {
    switch (key) {
      case "uid": return m.uid;
      case "status": return m.status === "ok" ? 1 : 0;
      case "weight": return m.weight;
      case "uptime": return m.uptime;
      case "accuracy": return m.accuracy;
      case "attest": {
        const t = m.lifetime_attestations || m.attestations_total;
        const v = m.lifetime_attestations_valid || m.attestations_valid;
        return t > 0 ? v / t : -1;
      }
      case "notary": return m.notary_reliability;
      case "queries": return m.queries_correct;
      default: return 0;
    }
  }, []);

  const { sorted, sortKey, sortDir, toggle } = useSortable(miners, "weight", "desc", getVal);

  if (!miners.length) {
    return <p className="text-sm text-slate-400 py-4 px-3">No miners tracked by this validator.</p>;
  }

  const Th = ({ k, children, align }: { k: string; children: React.ReactNode; align?: string }) => (
    <th className={`px-3 py-2 cursor-pointer select-none hover:text-slate-600 ${align || ""}`} onClick={() => toggle(k)}>
      {children}<SortArrow active={sortKey === k} dir={sortDir} />
    </th>
  );

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="text-left text-xs text-slate-400 uppercase tracking-wide border-b">
            <Th k="uid">UID</Th>
            <Th k="status">Status</Th>
            <Th k="weight" align="text-right">Weight</Th>
            <Th k="uptime" align="text-right">Uptime</Th>
            <Th k="accuracy" align="text-right">Accuracy</Th>
            <Th k="queries" align="text-right">Queries</Th>
            <Th k="attest" align="text-right">Attest</Th>
            <Th k="notary" align="text-right">Notary</Th>
          </tr>
        </thead>
        <tbody>
          {sorted.map((m) => {
            const aTotal = m.lifetime_attestations || m.attestations_total;
            const aValid = m.lifetime_attestations_valid || m.attestations_valid;
            return (
              <tr key={m.uid} className="border-b border-slate-100 hover:bg-slate-50 cursor-pointer" onClick={() => window.location.href = `/network/miner/${m.uid}`}>
                <td className="px-3 py-2 font-mono font-medium">
                  <Link href={`/network/miner/${m.uid}`} className="text-blue-600 hover:text-blue-800 hover:underline" onClick={(e) => e.stopPropagation()}>
                    {m.uid}
                  </Link>
                </td>
                <td className="px-3 py-2">
                  <StatusDot ok={m.status === "ok"} />
                </td>
                <td className="px-3 py-2 text-right font-mono">{m.weight.toFixed(4)}</td>
                <td className="px-3 py-2 text-right">{(m.uptime * 100).toFixed(0)}%</td>
                <td className="px-3 py-2 text-right">{(m.accuracy * 100).toFixed(0)}%</td>
                <td className="px-3 py-2 text-right font-mono text-xs">
                  {m.queries_correct}/{m.queries_total}
                </td>
                <td className="px-3 py-2 text-right">
                  <AttestCell valid={aValid} total={aTotal} proactive={m.proactive_proof_verified} />
                </td>
                <td className="px-3 py-2 text-right font-mono text-xs">
                  {m.notary_duties_assigned > 0
                    ? `${m.notary_duties_completed}/${m.notary_duties_assigned}`
                    : <span className="text-slate-300">-</span>}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

// ---------- Main Page ----------

export default function ValidatorPage() {
  const params = useParams();
  const uid = params.uid as string;

  // Keyed by uid so a slow fetch from a previous UID can't race and overwrite
  // the current UID's data — React Query caches by queryKey, so a stale
  // response lands in the old cache slot and is never read by this render.
  const validatorQuery = useQuery<NetworkValidatorDetail | null>({
    queryKey: ["network-validator", uid] as const,
    queryFn: () => fetchNetworkValidator(uid),
    enabled: Boolean(uid),
    staleTime: 15_000,
  });

  const loading = validatorQuery.isFetching;
  const data = validatorQuery.data;
  const metagraph: Metagraph | null = data?.found ? data.metagraph ?? null : null;
  const health: Health | null = data?.found ? data.health ?? null : null;
  const miners: MinerRow[] = data?.found ? data.miners ?? [] : [];

  const { data: manifest } = useVersionManifest();
  const effectiveVersion = resolveVersion(manifest, health?.git_sha);
  const showEffective = versionDrifts(health?.version, effectiveVersion);

  let error = "";
  if (validatorQuery.isError) {
    error = "Failed to load validator data.";
  } else if (data && !data.found) {
    error = data.error || "Validator not found.";
  }

  const lastUpdate = validatorQuery.dataUpdatedAt
    ? new Date(validatorQuery.dataUpdatedAt).toLocaleTimeString()
    : "";

  const { refetch } = validatorQuery;
  const load = useCallback(() => {
    refetch();
  }, [refetch]);

  const onlineMiners = miners.filter((m) => m.status === "ok").length;
  const totalWeight = miners.reduce((s, m) => s + (m.weight || 0), 0);
  const attestingMiners = miners.filter(
    (m) => (m.lifetime_attestations || m.attestations_total) > 0,
  ).length;
  const totalAttempts = miners.reduce(
    (s, m) => s + (m.lifetime_attestations || m.attestations_total || 0),
    0,
  );
  const totalValid = miners.reduce(
    (s, m) => s + (m.lifetime_attestations_valid || m.attestations_valid || 0),
    0,
  );

  return (
    <div className="max-w-6xl mx-auto">
      {/* Breadcrumb */}
      <div className="flex items-center gap-2 mb-6">
        <Link href="/network" className="text-slate-400 hover:text-slate-600 text-sm">
          Network
        </Link>
        <span className="text-slate-300">/</span>
        <span className="text-sm text-slate-600">Validator {uid}</span>
      </div>

      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <div className="flex items-center gap-3">
          <Image src="/djinn-logo.png" alt="Djinn" width={32} height={32} />
          <div>
            <h1 className="text-2xl font-bold text-slate-900">Validator UID {uid}</h1>
            <p className="text-sm text-slate-400">
              {metagraph && `${metagraph.ip}:${metagraph.port}`}
              {health?.version && (
                showEffective ? (
                  <span title={`reported v${health.version}; git_sha ${health.git_sha} resolves to ${effectiveVersion}`}>
                    {" | "}<span className="text-amber-600">{effectiveVersion}</span>
                    {health.git_sha && <span className="text-slate-400"> ({health.git_sha.slice(0, 7)})</span>}
                  </span>
                ) : (
                  <>{" | "}v{health.version}{health.git_sha && ` (${health.git_sha.slice(0, 7)})`}</>
                )
              )}
              {metagraph && ` | Stake: ${formatTao(metagraph.stake)}`}
              {lastUpdate && ` | Updated ${lastUpdate}`}
            </p>
          </div>
        </div>
        <button
          onClick={load}
          disabled={loading}
          className="rounded-lg border border-slate-200 px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-50"
        >
          {loading ? "Loading..." : "Refresh"}
        </button>
      </div>

      {error && <p className="text-sm text-red-600 mb-4">{error}</p>}

      {!loading && health && (
        <>
          {/* Health cards */}
          <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3 mb-8">
            <StatCard
              label="Status"
              value={health.status === "ok" ? "Healthy" : "Down"}
              sub={
                health.version
                  ? showEffective
                    ? `${effectiveVersion}${health.git_sha ? ` (${health.git_sha.slice(0, 7)})` : ""} — reports v${health.version}`
                    : `v${health.version}${health.git_sha ? ` (${health.git_sha.slice(0, 7)})` : ""}`
                  : "unknown version"
              }
            />
            <StatCard
              label="Shares"
              value={String(health.shares_held ?? 0)}
              sub="MPC key shares held"
            />
            <StatCard
              label="Miners"
              value={`${onlineMiners}/${miners.length}`}
              sub="online / tracked"
            />
            <StatCard
              label="Attestations"
              value={totalAttempts > 0 ? `${((totalValid / totalAttempts) * 100).toFixed(0)}%` : "-"}
              sub={`${totalValid}/${totalAttempts} across ${attestingMiners} miners`}
            />
            <StatCard
              label="Connectivity"
              value={
                health.chain_connected && health.bt_connected
                  ? "Full"
                  : health.chain_connected || health.bt_connected
                    ? "Partial"
                    : "None"
              }
              sub={`Chain: ${health.chain_connected ? "yes" : "no"} | BT: ${health.bt_connected ? "yes" : "no"}`}
            />
            {/* Chain-alive: did this validator submit weights to subtensor
                recently? Distinct from API liveness (Status card above).
                A weight-only validator (Kooltek pattern) shows Down on
                Status but Live here. */}
            {metagraph?.chainBlocksSinceUpdate !== undefined && metagraph?.chainBlocksSinceUpdate !== null && (
              <StatCard
                label="Chain"
                value={metagraph.chainBlocksSinceUpdate <= 1800 ? "Live" : "Stale"}
                sub={`Last weight ${Math.round((metagraph.chainBlocksSinceUpdate || 0) * 12 / 60)}m ago`}
              />
            )}
          </div>

          {/* Quick info row */}
          <div className="card mb-8">
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-4 text-sm">
              <div>
                <p className="text-[11px] text-slate-400 uppercase">VTrust</p>
                <p className="font-mono font-semibold">
                  {metagraph ? normalizedToPercent(metagraph.validatorTrust) : "-"}
                </p>
              </div>
              <div>
                <p className="text-[11px] text-slate-400 uppercase">Pending Outcomes</p>
                <p className="font-mono font-semibold">{health.pending_outcomes ?? 0}</p>
              </div>
              <div>
                <p className="text-[11px] text-slate-400 uppercase">Attest Capable</p>
                <p className="font-semibold">{health.attest_capable ? "Yes" : "No"}</p>
              </div>
              <div>
                <p className="text-[11px] text-slate-400 uppercase">Total Weight Sum</p>
                <p className="font-mono font-semibold">{totalWeight.toFixed(4)}</p>
              </div>
              <div>
                <p className="text-[11px] text-slate-400 uppercase">Deployed</p>
                <p className={`font-semibold ${ageClass(health.git_commit_ts)}`} title={health.git_commit_ts ? new Date(health.git_commit_ts * 1000).toISOString() : "non-git install or unknown"}>
                  {formatRelativeAge(health.git_commit_ts)}
                </p>
              </div>
              <div>
                <p className="text-[11px] text-slate-400 uppercase">Process Started</p>
                <p className="font-semibold text-slate-700" title={health.process_started_ts ? new Date(health.process_started_ts * 1000).toISOString() : "unknown"}>
                  {formatRelativeAge(health.process_started_ts)}
                </p>
              </div>
            </div>
          </div>

          {/* Egress IPs: chain commitment that lets miners whitelist this
              validator's outbound IPs. Single block covers four operator
              questions: what's published, what's self-detected, do they
              match the axon, and is anything actually committed. */}
          <div className="card mb-8">
            <div className="flex items-start justify-between gap-4">
              <div className="flex-1">
                <p className="text-[11px] text-slate-400 uppercase mb-2">Egress IPs (Bittensor commitment)</p>
                {metagraph?.egressIps && metagraph.egressIps.length > 0 ? (
                  <div className="flex flex-wrap gap-2">
                    {metagraph.egressIps.map((ip) => {
                      const isAxon = metagraph.ip === ip;
                      return (
                        <span
                          key={ip}
                          className={`inline-block px-2 py-1 rounded text-xs font-mono ${
                            isAxon
                              ? "bg-slate-100 text-slate-500"
                              : "bg-emerald-50 text-emerald-700"
                          }`}
                          title={isAxon ? "Same as axon IP — already on miner allowlists" : "Published outbound IP — miners union this into their firewall"}
                        >
                          {ip}{isAxon && <span className="ml-1 text-[10px]">(=axon)</span>}
                        </span>
                      );
                    })}
                  </div>
                ) : (
                  <p className="text-sm text-slate-500">
                    None published.{" "}
                    {health.egress_ip_self_reported && metagraph?.ip === health.egress_ip_self_reported && (
                      <span>Self-detected egress equals the axon IP, so the validator skipped the commitment write (already on miner allowlists).</span>
                    )}
                    {health.egress_ip_self_reported && metagraph?.ip !== health.egress_ip_self_reported && (
                      <span className="text-amber-600">
                        Validator detected outbound IP <span className="font-mono">{health.egress_ip_self_reported}</span> which differs from axon — but no commitment is on chain. Miners may refuse this validator&apos;s calls until v1733+ is running.
                      </span>
                    )}
                    {!health.egress_ip_self_reported && (
                      <span>Validator hasn&apos;t reported a self-detected egress IP (likely v1732 or earlier).</span>
                    )}
                  </p>
                )}
                {health.egress_ip_self_reported && (
                  <p className="text-[11px] text-slate-400 mt-2">
                    Self-detected: <span className="font-mono">{health.egress_ip_self_reported}</span>
                    {" · "}Axon: <span className="font-mono">{metagraph?.ip || "?"}</span>
                  </p>
                )}
              </div>
            </div>
          </div>

          {/* Settlement registration: only show when the validator publishes a
              writing signer. Red when misconfigured; the remediation string
              surfaces the exact one-line operator fix. */}
          {health.settlement_registered !== null && health.settlement_registered !== undefined && (
            <div className="card mb-8">
              <div className="flex items-start justify-between gap-4">
                <div>
                  <p className="text-[11px] text-slate-400 uppercase mb-1">Settlement Registration</p>
                  <p className="font-semibold">
                    {health.settlement_registered ? (
                      <span className="text-emerald-600">Registered on canonical OutcomeVoting</span>
                    ) : health.settlement_diagnosis === "stale_env_override" ? (
                      <span className="text-red-600">Misconfigured: stale OUTCOME_VOTING_ADDRESS in .env</span>
                    ) : health.settlement_diagnosis === "missing_bootstrap" ? (
                      <span className="text-amber-600">Signer not registered on OutcomeVoting</span>
                    ) : (
                      <span className="text-slate-500">Not registered (probe inconclusive)</span>
                    )}
                  </p>
                  {health.settlement_remediation && (
                    <p className="text-sm text-slate-600 mt-2">{health.settlement_remediation}</p>
                  )}
                  {health.settlement_contract && (
                    <p className="text-xs font-mono text-slate-400 mt-1 break-all">
                      Reading from: {health.settlement_contract}
                    </p>
                  )}
                </div>
              </div>
            </div>
          )}

          {/* Settlement-path configuration: surfaces the env knobs that
              silently block P0-01 (shamir_threshold drift, audit batch
              size mismatch, batch-settlement HTTP flags). Operator sees
              the whole tuple in one card instead of SSH+grep on .env. */}
          {(health.shamir_threshold !== null && health.shamir_threshold !== undefined) ||
          (health.audit_min_batch_size !== null && health.audit_min_batch_size !== undefined) ||
          (health.batch_settlement_http !== null && health.batch_settlement_http !== undefined) ||
          (health.batch_settlement_http_submit !== null && health.batch_settlement_http_submit !== undefined) ? (
            <div className="card mb-8">
              <p className="text-[11px] text-slate-400 uppercase mb-3">Settlement Configuration</p>
              <div className="grid grid-cols-2 sm:grid-cols-4 gap-4 text-sm">
                <div>
                  <p className="text-[11px] text-slate-400 uppercase">Shamir Threshold</p>
                  <p className="font-mono font-semibold">
                    {health.shamir_threshold ?? "-"}
                    {health.shamir_threshold !== null &&
                      health.shamir_threshold !== undefined &&
                      health.shamir_threshold !== 2 && (
                        <span className="text-amber-600 text-xs ml-2">(client=2)</span>
                      )}
                  </p>
                </div>
                <div>
                  <p className="text-[11px] text-slate-400 uppercase">Audit Min Batch</p>
                  <p className="font-mono font-semibold">{health.audit_min_batch_size ?? "-"}</p>
                </div>
                <div>
                  <p className="text-[11px] text-slate-400 uppercase">Batch HTTP</p>
                  <p className="font-semibold">
                    {health.batch_settlement_http === true ? (
                      <span className="text-emerald-600">On</span>
                    ) : health.batch_settlement_http === false ? (
                      <span className="text-slate-500">Off</span>
                    ) : (
                      <span className="text-slate-300">-</span>
                    )}
                  </p>
                </div>
                <div>
                  <p className="text-[11px] text-slate-400 uppercase">Batch Submit</p>
                  <p className="font-semibold">
                    {health.batch_settlement_http_submit === true ? (
                      <span className="text-emerald-600">On</span>
                    ) : health.batch_settlement_http_submit === false ? (
                      <span className="text-slate-500">Off</span>
                    ) : (
                      <span className="text-slate-300">-</span>
                    )}
                  </p>
                </div>
              </div>
            </div>
          ) : null}

          {/* Miner scoring table */}
          <section className="mb-8">
            <h2 className="text-lg font-semibold text-slate-900 mb-3">
              Miner Scoring{" "}
              <span className="text-sm font-normal text-slate-400">
                {miners.length} miners tracked
              </span>
            </h2>
            <div className="card p-0 overflow-hidden">
              <MinerScoringTable miners={miners} />
            </div>
          </section>
        </>
      )}

      {loading && (
        <div className="text-center py-12">
          <div className="animate-spin w-8 h-8 border-2 border-slate-300 border-t-slate-600 rounded-full mx-auto mb-4" />
          <p className="text-slate-500">Loading validator data...</p>
        </div>
      )}
    </div>
  );
}
