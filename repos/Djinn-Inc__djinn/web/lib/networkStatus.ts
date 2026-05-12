/**
 * Network status fetcher for the /network dashboard.
 *
 * Primary path: hit the wildcard router at v<uid>.djinn.gg/v1/network/overview
 * (bootstrap validator aggregates the view). This keeps the dashboard
 * alive when the Vercel proxy is unavailable, and makes the page work
 * from a static IPFS export (no /api routes).
 *
 * Fallback: the legacy /api/network/status Vercel aggregator. Kept for
 * the production web deploy so the page stays fast when Vercel is up,
 * and for ergonomic differences (CORS preflight, cold-start latency).
 *
 * Order: try the wildcard router first. If it fails or times out within
 * the budget, fall back to /api/network/status. Either path returns the
 * same { summary, validators, miners, ipClusters } shape.
 */
import { DEFAULT_BOOTSTRAP } from "./validatorDiscovery";

export interface NetworkValidatorEntry {
  uid: number;
  ip: string;
  port: number;
  ss58Hotkey?: string;
  coldkey?: string;
  stake: string;
  incentive: number;
  emission: string;
  validatorTrust: number;
  // Validator's published outbound-IP commitments (v1733+). Empty list
  // when this validator hasn't published; auto-detect mode skips when
  // the detected IP equals the axon IP, so most single-NIC validators
  // stay empty here without that being a problem.
  egressIps?: string[];
  // Block of last weight submission on the Bittensor chain. Non-zero
  // means the validator's chain process is alive even if the HTTP API
  // is unreachable.
  lastUpdateBlock?: number;
  // Blocks since the last weight update (current_block - last_update).
  // Cheap "is this validator alive on chain?" probe — under ~1800
  // (≈6h on SN103's 12s blocks) means active. null when the validator
  // serving this response can't compute it.
  chainBlocksSinceUpdate?: number | null;
  health: {
    status: string;
    version: string;
    shares_held?: number;
    chain_connected?: boolean;
    bt_connected?: boolean;
    settlement_registered?: boolean | null;
    settlement_contract?: string | null;
    settlement_diagnosis?: string | null;
    shamir_threshold?: number | null;
    audit_min_batch_size?: number | null;
    batch_settlement_http?: boolean | null;
    batch_settlement_http_submit?: boolean | null;
    service_port?: number;
    // Unix epoch (seconds) of HEAD's commit on the running validator.
    // Lets the UI render "deployed 12m ago" / "deployed 4d ago" so an
    // operator can spot lagging fleet members at a glance. null on
    // non-git installs; render as "unknown" rather than guess.
    git_commit_ts?: number | null;
    // Unix epoch (seconds) when the validator process last (re)started.
    // Useful on the per-validator detail page; not surfaced in the
    // top-level table.
    process_started_ts?: number | null;
  } | null;
}

export interface NetworkMinerEntry {
  uid: number;
  ip: string;
  stake: string;
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
  queries_total?: number;
  queries_correct?: number;
  notary_duties_assigned?: number;
  notary_duties_completed?: number;
}

export interface NetworkSummary {
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

export interface NetworkStatus {
  summary: NetworkSummary | null;
  validators: NetworkValidatorEntry[];
  miners: NetworkMinerEntry[];
  ipClusters: Record<string, number[]>;
  source: "wildcard" | "vercel";
  servedByUid?: number | null;
}

export interface NetworkValidatorHealth {
  status: string;
  version: string;
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
}

export interface NetworkValidatorMetagraph {
  ip: string;
  port: number;
  stake: string;
  incentive: number;
  emission: string;
  validatorTrust: number;
}

export interface NetworkValidatorMiner {
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

export interface NetworkValidatorDetail {
  uid: number;
  found: boolean;
  error?: string;
  metagraph?: NetworkValidatorMetagraph;
  health?: NetworkValidatorHealth | null;
  miners?: NetworkValidatorMiner[];
  validatorUid?: number | null;
  source?: "wildcard" | "vercel";
}

const WILDCARD_TIMEOUT_MS = 8_000;
const VERCEL_TIMEOUT_MS = 12_000;

async function fetchJson<T>(url: string, timeoutMs: number): Promise<T | null> {
  try {
    const r = await fetch(url, {
      signal: AbortSignal.timeout(timeoutMs),
      cache: "no-store",
    });
    if (!r.ok) return null;
    const ct = r.headers.get("content-type") ?? "";
    if (!ct.includes("application/json")) return null;
    return (await r.json()) as T;
  } catch {
    return null;
  }
}

export async function fetchNetworkStatus(
  options: { bootstrap?: string } = {},
): Promise<NetworkStatus | null> {
  const bootstrap = options.bootstrap ?? DEFAULT_BOOTSTRAP;

  const wildcard = await fetchJson<NetworkStatus & { served_by_uid?: number | null }>(
    `${bootstrap}/v1/network/overview`,
    WILDCARD_TIMEOUT_MS,
  );
  if (wildcard && wildcard.summary) {
    return {
      summary: wildcard.summary,
      validators: wildcard.validators ?? [],
      miners: wildcard.miners ?? [],
      ipClusters: wildcard.ipClusters ?? {},
      source: "wildcard",
      servedByUid: wildcard.served_by_uid ?? null,
    };
  }

  const vercel = await fetchJson<NetworkStatus>(
    `/api/network/status`,
    VERCEL_TIMEOUT_MS,
  );
  if (vercel && vercel.summary) {
    return {
      summary: vercel.summary,
      validators: vercel.validators ?? [],
      miners: vercel.miners ?? [],
      ipClusters: vercel.ipClusters ?? {},
      source: "vercel",
    };
  }

  return null;
}

/**
 * Per-validator detail fetcher for /network/validator/[uid].
 *
 * Same wildcard-first, Vercel-fallback pattern as fetchNetworkStatus.
 * The bootstrap validator's `/v1/network/validator/{uid}` endpoint
 * short-circuits when uid matches the serving validator (local state,
 * always fresh) and probes the target peer otherwise.
 */
export async function fetchNetworkValidator(
  uid: number | string,
  options: { bootstrap?: string } = {},
): Promise<NetworkValidatorDetail | null> {
  const bootstrap = options.bootstrap ?? DEFAULT_BOOTSTRAP;
  const uidNum = typeof uid === "string" ? parseInt(uid, 10) : uid;
  if (!Number.isFinite(uidNum) || uidNum < 0 || uidNum > 65535) {
    return { uid: Number(uid), found: false, error: "Invalid UID" };
  }

  const wildcard = await fetchJson<NetworkValidatorDetail>(
    `${bootstrap}/v1/network/validator/${uidNum}`,
    WILDCARD_TIMEOUT_MS,
  );
  if (wildcard && wildcard.found) {
    return { ...wildcard, source: "wildcard" };
  }

  const vercel = await fetchJson<NetworkValidatorDetail>(
    `/api/network/validator/${uidNum}`,
    VERCEL_TIMEOUT_MS,
  );
  if (vercel) {
    return { ...vercel, source: "vercel" };
  }

  // Wildcard returned a found:false response (surface its error) instead
  // of ignoring it when Vercel also failed.
  if (wildcard) {
    return { ...wildcard, source: "wildcard" };
  }

  return {
    uid: uidNum,
    found: false,
    error: "Validator not reachable",
  };
}
