import { NextResponse } from "next/server";
import { discoverMetagraph, probeDjinnValidator } from "@/lib/bt-metagraph";
import { hexToSs58 } from "@/lib/ss58";
import { DEFAULT_BOOTSTRAP } from "@/lib/validatorDiscovery";

// No edge / fetch caching: every call must reflect the validator's
// current state. The previous `revalidate = 120` interacted with
// Next's fetch cache to publish multi-week-old version numbers when
// the bootstrap was briefly slow (the wildcard router has its own
// 120s cache; doubling up here only adds staleness with no upside).
export const revalidate = 0;
export const dynamic = "force-dynamic";

/**
 * GET /api/network/status
 *
 * Sprint A Stage A-3: forward-first proxy. When the bootstrap validator
 * responds with 200 on /v1/network/overview, pass it through verbatim
 * (tagged x-djinn-source: validator). The validator-side aggregator
 * already computes the same shape this Next handler produced (summary,
 * validators, miners, ipClusters) plus served_by_uid/served_at_ms, so
 * no field mapping is needed.
 *
 * Falls back to the local metagraph + peer-probe path when the
 * bootstrap is unreachable, returns non-200, or times out — same
 * semantics as the /discover proxies above.
 */

const VALIDATOR_TIMEOUT_MS = 8_000;

async function tryValidator(): Promise<Response | null> {
  try {
    const resp = await fetch(`${DEFAULT_BOOTSTRAP}/v1/network/overview`, {
      headers: { accept: "application/json" },
      signal: AbortSignal.timeout(VALIDATOR_TIMEOUT_MS),
      cache: "no-store",
    });
    if (resp.ok) return resp;
  } catch {
    // Fall through.
  }
  return null;
}

interface HealthResult {
  uid: number;
  status: string;
  version: string;
  shares_held?: number;
  chain_connected?: boolean;
  bt_connected?: boolean;
  settlement_registered?: boolean | null;
  settlement_contract?: string | null;
  settlement_diagnosis?: string | null;
  service_port?: number;
}

async function probeHealth(
  ip: string,
  axonPort: number,
  uid: number,
): Promise<HealthResult> {
  // 8s timeout (was 5s): Yuma/UID 2 sits on Google Cloud and the
  // Vercel-edge → GCP path occasionally exceeds 5s on cold connections,
  // making Yuma flap as "unreachable" on /admin even when UID 0's box
  // probes it in <1.3s. 8s is comfortably under the 10s outer
  // VALIDATOR_TIMEOUT_MS so we never starve the parent request.
  const result = await probeDjinnValidator(ip, axonPort, 8000);
  if (!result) return { uid, status: "unreachable", version: "" };
  return { uid, service_port: result.port, ...(result.health as Omit<HealthResult, "uid">) };
}

function computeGini(values: number[]): number {
  if (values.length === 0) return 0;
  const sorted = [...values].sort((a, b) => a - b);
  const n = sorted.length;
  const total = sorted.reduce((a, b) => a + b, 0);
  if (total === 0) return 0;
  let weightedSum = 0;
  for (let i = 0; i < n; i++) weightedSum += (i + 1) * sorted[i];
  return (2 * weightedSum) / (n * total) - (n + 1) / n;
}

interface ScoringEntry {
  weight: number;
  attestations_total: number;
  attestations_valid: number;
  lifetime_attestations: number;
  lifetime_attestations_valid: number;
  proactive_proof_verified: boolean;
  uptime: number;
  accuracy: number;
  queries_total: number;
  queries_correct: number;
  notary_duties_assigned: number;
  notary_duties_completed: number;
}
let scoringCache: { data: Record<number, ScoringEntry>; fetchedAt: number } | null = null;
const SCORING_CACHE_TTL = 120_000;

async function fetchScoringData(
  ip: string,
  port: number,
): Promise<Record<number, ScoringEntry>> {
  const now = Date.now();
  if (scoringCache && now - scoringCache.fetchedAt < SCORING_CACHE_TTL) {
    return scoringCache.data;
  }
  const result: Record<number, ScoringEntry> = {};
  try {
    const res = await fetch(
      `http://${ip}:${port}/v1/network/miners`,
      { signal: AbortSignal.timeout(5000), cache: "no-store" },
    );
    if (res.ok) {
      const data = await res.json();
      for (const m of data.miners || []) {
        result[m.uid] = {
          weight: m.weight ?? 0,
          attestations_total: m.attestations_total ?? 0,
          attestations_valid: m.attestations_valid ?? 0,
          lifetime_attestations: m.lifetime_attestations ?? 0,
          lifetime_attestations_valid: m.lifetime_attestations_valid ?? 0,
          proactive_proof_verified: m.proactive_proof_verified ?? false,
          uptime: m.uptime ?? 0,
          accuracy: m.accuracy ?? 0,
          queries_total: m.queries_total ?? 0,
          queries_correct: m.queries_correct ?? 0,
          notary_duties_assigned: m.notary_duties_assigned ?? 0,
          notary_duties_completed: m.notary_duties_completed ?? 0,
        };
      }
      scoringCache = { data: result, fetchedAt: now };
    }
  } catch {
    if (scoringCache) return scoringCache.data;
  }
  return result;
}

export async function GET() {
  const forwarded = await tryValidator();
  if (forwarded) {
    const body = await forwarded.text();
    return new NextResponse(body, {
      status: 200,
      headers: {
        "content-type": "application/json",
        "cache-control": "public, s-maxage=30, stale-while-revalidate=60",
        "x-djinn-source": "validator",
      },
    });
  }

  try {
    const { nodes } = await discoverMetagraph();

    const reachable = nodes.filter(
      (n) =>
        n.port > 0 &&
        n.ip !== "0.0.0.0" &&
        !n.ip.startsWith("10.") &&
        !n.ip.startsWith("192.168.") &&
        !n.ip.startsWith("127."),
    );

    // Probe-eligible validators (have a public axon we can reach).
    const validators = reachable.filter((n) => n.isValidator);
    const miners = reachable.filter((n) => !n.isValidator);

    // Operator visibility: include validators with validator_permit but
    // NO published axon (ip=0.0.0.0 or port=0). They're still validators
    // on the metagraph; surfacing them lets the operator follow up with
    // whoever owns that hotkey to start their djinn-validator. We skip
    // probeHealth on these and synthesize a "no_axon" status entry.
    const noAxonValidators = nodes.filter(
      (n) =>
        n.isValidator &&
        (n.port === 0 || n.ip === "0.0.0.0"),
    );

    const allMiners = nodes.filter((n) => !n.isValidator);

    const topStakeVal = [...validators].sort(
      (a, b) => (b.totalStake > a.totalStake ? 1 : -1),
    )[0];

    const [valHealthResults, scoringData] = await Promise.all([
      Promise.allSettled(
        validators.map((v) => probeHealth(v.ip, v.port, v.uid)),
      ),
      topStakeVal
        ? fetchScoringData(topStakeVal.ip, topStakeVal.port)
        : Promise.resolve({} as Record<number, ScoringEntry>),
    ]);

    const healthMap: Record<number, HealthResult> = {};
    for (const r of valHealthResults) {
      if (r.status === "fulfilled") healthMap[r.value.uid] = r.value;
    }

    const validatorHealth = validators.map((v) => healthMap[v.uid]).filter(Boolean);

    const ipClusters: Record<string, number[]> = {};
    const uniqueIps = new Set<string>();
    for (const m of allMiners) {
      const ip = m.ip;
      if (ip && ip !== "0.0.0.0") {
        uniqueIps.add(ip);
        const subnet = ip.split(".").slice(0, 3).join(".");
        (ipClusters[subnet] ??= []).push(m.uid);
      }
    }

    const incentiveValues = allMiners
      .filter((m) => m.uid !== 0)
      .map((m) => m.incentive);
    const giniCoeff = computeGini(incentiveValues);

    const totalIncentive = nodes.reduce((s, n) => s + n.incentive, 0);
    const uid0 = nodes.find((n) => n.uid === 0);
    const burnPercent =
      totalIncentive > 0 && uid0
        ? (uid0.incentive / totalIncentive) * 100
        : 0;

    const summary = {
      totalValidators: validators.length,
      totalMiners: allMiners.length,
      validatorsHealthy: validatorHealth.filter((h) => h.status === "ok").length,
      validatorsHoldingShares: validatorHealth.filter((h) => (h.shares_held ?? 0) > 0).length,
      totalShares: validatorHealth.reduce((sum, h) => sum + (h.shares_held ?? 0), 0),
      highestVersion: Math.max(
        0,
        ...validatorHealth
          .map((h) => parseInt(h.version || "0", 10))
          .filter((v) => !isNaN(v)),
      ),
      timestamp: Date.now(),
      uniqueIps: uniqueIps.size,
      gini: Math.round(giniCoeff * 1000) / 1000,
      burnPercent: Math.round(burnPercent * 10) / 10,
    };

    // Probed validators get a real health entry; no-axon validators get
    // a synthetic { status: "no_axon" } so the admin UI can surface
    // them without lying about reachability.
    const probedList = validators.map((n) => {
      const health = healthMap[n.uid] || null;
      const port = health?.service_port ?? n.port;
      return {
        uid: n.uid,
        ip: n.ip,
        port,
        ss58Hotkey: hexToSs58(n.hotkey),
        stake: n.totalStake.toString(),
        incentive: n.incentive,
        emission: n.emission.toString(),
        validatorTrust: n.validatorTrust,
        health,
      };
    });
    const noAxonList = noAxonValidators.map((n) => ({
      uid: n.uid,
      ip: n.ip || "0.0.0.0",
      port: n.port,
      ss58Hotkey: hexToSs58(n.hotkey),
      stake: n.totalStake.toString(),
      incentive: n.incentive,
      emission: n.emission.toString(),
      validatorTrust: n.validatorTrust,
      health: { uid: n.uid, status: "no_axon", version: "" } as HealthResult,
    }));
    const validatorList = [...probedList, ...noAxonList].sort(
      (a, b) => (BigInt(b.stake) > BigInt(a.stake) ? 1 : -1),
    );

    const minerList = allMiners
      .sort((a, b) => b.incentive - a.incentive)
      .map((n) => ({
        uid: n.uid,
        ip: n.ip || "0.0.0.0",
        stake: n.totalStake.toString(),
        incentive: n.incentive,
        emission: n.emission.toString(),
        ...(scoringData[n.uid] || {}),
      }));

    return NextResponse.json(
      { summary, validators: validatorList, miners: minerList, ipClusters },
      {
        headers: {
          "Cache-Control": "public, s-maxage=30, stale-while-revalidate=60",
          "x-djinn-source": "vercel-local",
        },
      },
    );
  } catch (err) {
    console.error("[network/status] Failed:", err);
    return NextResponse.json(
      { error: "Network status unavailable", summary: null, validators: [], miners: [], ipClusters: {} },
      { status: 500, headers: { "x-djinn-source": "vercel-local" } },
    );
  }
}
