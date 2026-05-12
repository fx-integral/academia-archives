import { NextResponse } from "next/server";
import { discoverMetagraph, isPublicIp } from "@/lib/bt-metagraph";
import { DEFAULT_BOOTSTRAP } from "@/lib/validatorDiscovery";

/**
 * GET /api/network/matrix
 *
 * Sprint A Stage A-3: forward-first proxy. When the bootstrap validator
 * responds 200 on /v1/network/matrix, pass it through verbatim (tagged
 * x-djinn-source: validator). The validator-side aggregator computes
 * the same shape this Next handler produced (validators[], minerUids[],
 * timestamp), so no field mapping is needed.
 *
 * Falls back to the local metagraph fan-out path when the bootstrap is
 * unreachable, returns non-200, or times out.
 */

const VALIDATOR_TIMEOUT_MS = 15_000;

export interface MatrixMinerEntry {
  uid: number;
  hotkey: string;
  status: string;
  weight: number;
  accuracy: number;
  uptime: number;
  queries_total: number;
  queries_correct: number;
  attestations_total: number;
  attestations_valid: number;
  proactive_proof_verified: boolean;
  notary_duties_assigned: number;
  notary_duties_completed: number;
  notary_reliability: number;
}

export interface MatrixValidator {
  uid: number;
  ip: string;
  port: number;
  stake: string;
  version: string | null;
  healthy: boolean;
  miners: Record<number, MatrixMinerEntry>;
}

async function tryValidator(): Promise<Response | null> {
  try {
    const resp = await fetch(`${DEFAULT_BOOTSTRAP}/v1/network/matrix`, {
      headers: { accept: "application/json" },
      signal: AbortSignal.timeout(VALIDATOR_TIMEOUT_MS),
    });
    if (resp.ok) return resp;
  } catch {
    // Fall through.
  }
  return null;
}

async function fetchValidatorMiners(
  ip: string,
  port: number,
): Promise<MatrixMinerEntry[]> {
  try {
    const res = await fetch(`http://${ip}:${port}/v1/network/miners`, {
      signal: AbortSignal.timeout(12_000),
      cache: "no-store",
    });
    if (!res.ok) return [];
    const data = await res.json();
    return (data.miners || []) as MatrixMinerEntry[];
  } catch {
    return [];
  }
}

async function fetchHealth(
  ip: string,
  port: number,
): Promise<{ status: string; version: string } | null> {
  try {
    const res = await fetch(`http://${ip}:${port}/health`, {
      signal: AbortSignal.timeout(8_000),
      cache: "no-store",
    });
    if (!res.ok) return null;
    return await res.json();
  } catch {
    return null;
  }
}

export async function GET() {
  const forwarded = await tryValidator();
  if (forwarded) {
    const body = await forwarded.text();
    return new NextResponse(body, {
      status: 200,
      headers: {
        "content-type": "application/json",
        "cache-control": "public, s-maxage=60, stale-while-revalidate=120",
        "x-djinn-source": "validator",
      },
    });
  }

  try {
    const { nodes } = await discoverMetagraph();

    const valNodes = nodes.filter(
      (n) =>
        n.isValidator &&
        n.port > 0 &&
        n.ip !== "0.0.0.0" &&
        isPublicIp(n.ip),
    );

    const results = await Promise.all(
      valNodes.map(async (v) => {
        const [health, minerList] = await Promise.all([
          fetchHealth(v.ip, v.port),
          fetchValidatorMiners(v.ip, v.port),
        ]);

        const miners: Record<number, MatrixMinerEntry> = {};
        for (const m of minerList) {
          miners[m.uid] = m;
        }

        return {
          uid: v.uid,
          ip: v.ip,
          port: v.port,
          stake: v.totalStake.toString(),
          version: health?.version ?? null,
          healthy: health?.status === "ok",
          miners,
        } satisfies MatrixValidator;
      }),
    );

    const minerUids = new Set<number>();
    for (const v of results) {
      for (const uid of Object.keys(v.miners)) {
        minerUids.add(Number(uid));
      }
    }

    return NextResponse.json(
      {
        validators: results,
        minerUids: [...minerUids].sort((a, b) => a - b),
        timestamp: Date.now(),
      },
      {
        headers: {
          "Cache-Control": "public, s-maxage=60, stale-while-revalidate=120",
          "x-djinn-source": "vercel-local",
        },
      },
    );
  } catch (err) {
    console.error("[network/matrix] Failed:", err);
    return NextResponse.json(
      { error: "Failed to load matrix data", validators: [], minerUids: [], timestamp: Date.now() },
      { status: 500, headers: { "x-djinn-source": "vercel-local" } },
    );
  }
}
