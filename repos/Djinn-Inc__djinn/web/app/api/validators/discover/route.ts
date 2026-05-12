import { NextRequest, NextResponse } from "next/server";
import { discoverMetagraph, probeDjinnValidator } from "@/lib/bt-metagraph";
import { hexToSs58 } from "@/lib/ss58";
import { DEFAULT_BOOTSTRAP } from "@/lib/validatorDiscovery";

/**
 * Returns validator nodes from the metagraph.
 *
 * Sprint A Stage A-3: forward-first proxy. When the bootstrap validator
 * responds with 200, return its view verbatim (tagged
 * x-djinn-source: validator). Falls back to the local bt-metagraph
 * sync when the bootstrap is unreachable, returns non-200, or times
 * out — so this route keeps working during validator version skew.
 *
 * Default behavior (no `?all=true`) on the fallback path health-checks
 * validators and only returns responsive ones (used by client for
 * Shamir share distribution). Pass `?all=true` to skip health checks
 * and return all validators with permits (used by admin page).
 *
 * When forwarding to the validator, its response already reflects the
 * full validator list (no per-proxy health probing); this matches the
 * `?all=true` semantics, which the admin page uses anyway.
 */

const VALIDATOR_TIMEOUT_MS = 5_000;

async function tryValidator(): Promise<Response | null> {
  try {
    const resp = await fetch(`${DEFAULT_BOOTSTRAP}/v1/network/validators`, {
      headers: { accept: "application/json" },
      signal: AbortSignal.timeout(VALIDATOR_TIMEOUT_MS),
    });
    if (resp.ok) return resp;
  } catch {
    // Fall through.
  }
  return null;
}

export async function GET(req: NextRequest) {
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
    const skipHealthCheck = req.nextUrl.searchParams.get("all") === "true";
    const { nodes } = await discoverMetagraph();

    const reachable = nodes.filter((n) => n.port > 0 && n.ip !== "0.0.0.0" && !n.ip.startsWith("10.") && !n.ip.startsWith("192.168.") && !n.ip.startsWith("127."));

    const withPermit = reachable.filter((n) => n.isValidator);
    const pool = withPermit.length > 0 ? withPermit : reachable;

    const sorted = pool.sort((a, b) => (b.totalStake > a.totalStake ? 1 : b.totalStake < a.totalStake ? -1 : 0));

    let finalPool: Array<typeof sorted[0] & { servicePort: number }> = [];
    if (skipHealthCheck) {
      finalPool = sorted.map((n) => ({ ...n, servicePort: n.port }));
    } else {
      const probes = await Promise.all(
        sorted.map(async (n) => {
          const result = await probeDjinnValidator(n.ip, n.port, 8000);
          return result ? { ...n, servicePort: result.port } : null;
        }),
      );
      const healthy = probes.filter((p): p is typeof sorted[0] & { servicePort: number } => p !== null);
      finalPool = healthy.length > 0 ? healthy : sorted.map((n) => ({ ...n, servicePort: n.port }));
    }

    const validators = finalPool
      .map((n) => ({ uid: n.uid, ip: n.ip, port: n.servicePort, hotkey: n.hotkey, coldkey: n.coldkey, ss58Hotkey: hexToSs58(n.hotkey), stake: n.totalStake.toString(), alphaStake: n.alphaStake.toString(), taoStake: n.taoStake.toString(), incentive: n.incentive, emission: n.emission.toString(), consensus: n.consensus, trust: n.trust, validatorTrust: n.validatorTrust, dividends: n.dividends, rank: n.rank }));

    return NextResponse.json({ validators }, {
      headers: {
        "Cache-Control": "public, s-maxage=30, stale-while-revalidate=60",
        "x-djinn-source": "vercel-local",
      },
    });
  } catch (err) {
    console.error("[discover] Metagraph discovery failed:", err);
    return NextResponse.json(
      { error: "Metagraph discovery failed", validators: [] },
      { status: 500, headers: { "x-djinn-source": "vercel-local" } },
    );
  }
}
