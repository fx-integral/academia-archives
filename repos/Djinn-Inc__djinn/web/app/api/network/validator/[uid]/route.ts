import { NextResponse } from "next/server";
import { discoverMetagraph, isPublicIp, probeDjinnValidator } from "@/lib/bt-metagraph";
import { DEFAULT_BOOTSTRAP } from "@/lib/validatorDiscovery";

/**
 * GET /api/network/validator/[uid]
 *
 * Sprint B Stage 2: forward-first proxy. The bootstrap validator already
 * exposes /v1/network/validator/{uid} with the identical response shape
 * (metagraph + health + miners + validatorUid). When that responds 200
 * we pass it through verbatim (tagged x-djinn-source: validator). Falls
 * back to the local metagraph-probe path when the bootstrap is
 * unreachable or returns a non-200.
 */

const VALIDATOR_FORWARD_TIMEOUT_MS = 15_000;

async function tryValidator(uid: number): Promise<Response | null> {
  try {
    const resp = await fetch(`${DEFAULT_BOOTSTRAP}/v1/network/validator/${uid}`, {
      headers: { accept: "application/json" },
      signal: AbortSignal.timeout(VALIDATOR_FORWARD_TIMEOUT_MS),
    });
    if (resp.ok) return resp;
  } catch {
    // Fall through to local scan.
  }
  return null;
}

export async function GET(
  _request: Request,
  { params }: { params: Promise<{ uid: string }> },
) {
  const { uid: uidStr } = await params;
  const uid = parseInt(uidStr, 10);
  if (isNaN(uid) || uid < 0 || uid > 65535) {
    return NextResponse.json({ error: "Invalid UID" }, { status: 400 });
  }

  const forwarded = await tryValidator(uid);
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

    const valNode = nodes.find(
      (n) =>
        n.uid === uid &&
        n.isValidator &&
        n.port > 0 &&
        n.ip !== "0.0.0.0" &&
        isPublicIp(n.ip),
    );

    if (!valNode) {
      return NextResponse.json(
        { uid, found: false, error: "Validator not found or unreachable" },
        { status: 404, headers: { "x-djinn-source": "vercel-local" } },
      );
    }

    // Probe health (with port-fallback for validators that publish a
    // non-Djinn axon port in the metagraph).
    const probe = await probeDjinnValidator(valNode.ip, valNode.port, 10000);
    const servicePort = probe?.port ?? valNode.port;
    const health = probe?.health ?? null;

    const metagraph = {
      ip: valNode.ip,
      port: servicePort,
      stake: valNode.totalStake.toString(),
      incentive: valNode.incentive,
      emission: valNode.emission.toString(),
      validatorTrust: valNode.validatorTrust,
    };

    // Fetch all miners this validator scores (using the service port that
    // actually responded to /health, not necessarily the metagraph axon port).
    let miners: Record<string, unknown>[] = [];
    let validatorUid: number | null = null;
    try {
      const controller = new AbortController();
      const timeout = setTimeout(() => controller.abort(), 10000);
      const res = await fetch(
        `http://${valNode.ip}:${servicePort}/v1/network/miners`,
        { signal: controller.signal, cache: "no-store" },
      );
      clearTimeout(timeout);
      if (res.ok) {
        const data = await res.json();
        miners = data.miners || [];
        validatorUid = data.validator_uid ?? null;
      }
    } catch {
      // Miner data fetch failed, continue with empty list
    }

    return NextResponse.json(
      { uid, found: true, metagraph, health, miners, validatorUid },
      {
        headers: {
          "Cache-Control": "public, s-maxage=60, stale-while-revalidate=120",
          "x-djinn-source": "vercel-local",
        },
      },
    );
  } catch (err) {
    console.error("[network/validator] Failed:", err);
    return NextResponse.json(
      { uid, found: false, error: "Failed to load validator data" },
      { status: 500, headers: { "x-djinn-source": "vercel-local" } },
    );
  }
}
