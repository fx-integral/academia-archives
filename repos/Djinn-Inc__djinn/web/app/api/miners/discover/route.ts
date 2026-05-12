import { NextResponse } from "next/server";
import { discoverMiners } from "@/lib/bt-metagraph";
import { hexToSs58 } from "@/lib/ss58";
import { DEFAULT_BOOTSTRAP } from "@/lib/validatorDiscovery";

/**
 * Returns all reachable miner nodes from the metagraph.
 * Used by the admin dashboard to probe each miner's health individually.
 *
 * Sprint A Stage A-3: forward-first proxy. When the bootstrap validator
 * responds with 200, return its view verbatim (tagged
 * x-djinn-source: validator). Falls back to the local bt-metagraph
 * sync on network failure, non-200, or timeout.
 */

const VALIDATOR_TIMEOUT_MS = 5_000;

async function tryValidator(): Promise<Response | null> {
  try {
    const resp = await fetch(`${DEFAULT_BOOTSTRAP}/v1/network/metagraph/miners`, {
      headers: { accept: "application/json" },
      signal: AbortSignal.timeout(VALIDATOR_TIMEOUT_MS),
    });
    if (resp.ok) return resp;
  } catch {
    // Fall through.
  }
  return null;
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
    const nodes = await discoverMiners();

    const miners = nodes.map((n) => ({ uid: n.uid, ip: n.ip, port: n.port, hotkey: n.hotkey, coldkey: n.coldkey, ss58Hotkey: hexToSs58(n.hotkey), stake: n.totalStake.toString(), alphaStake: n.alphaStake.toString(), taoStake: n.taoStake.toString(), incentive: n.incentive, emission: n.emission.toString(), rank: n.rank }));

    return NextResponse.json({ miners }, {
      headers: {
        "Cache-Control": "public, s-maxage=30, stale-while-revalidate=60",
        "x-djinn-source": "vercel-local",
      },
    });
  } catch (err) {
    console.error("[discover-miners] Metagraph discovery failed:", err);
    return NextResponse.json(
      { error: "Metagraph discovery failed", miners: [] },
      { status: 500, headers: { "x-djinn-source": "vercel-local" } },
    );
  }
}
