import { NextResponse } from "next/server";
import { discoverMetagraph } from "@/lib/bt-metagraph";
import { DEFAULT_BOOTSTRAP } from "@/lib/validatorDiscovery";

/**
 * GET /api/network/miner/[uid]
 *
 * Sprint B Stage 6: forward-first proxy. Bootstrap validator exposes
 * /v1/network/miner/{uid} with the same shape (scores fan-out + metagraph
 * view). Falls back to the legacy metagraph discovery + direct fan-out to
 * each validator's /v1/miner/{uid}/scores.
 */

const VALIDATOR_FORWARD_TIMEOUT_MS = 15_000;

async function tryValidator(uid: number): Promise<Response | null> {
  try {
    const resp = await fetch(`${DEFAULT_BOOTSTRAP}/v1/network/miner/${uid}`, {
      headers: { accept: "application/json" },
      signal: AbortSignal.timeout(VALIDATOR_FORWARD_TIMEOUT_MS),
    });
    if (resp.ok) return resp;
  } catch {
    // Fall through to local fan-out.
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
        "cache-control": "public, s-maxage=30, stale-while-revalidate=60",
        "x-djinn-source": "validator",
      },
    });
  }

  try {
    const { nodes } = await discoverMetagraph();

    const minerNode = nodes.find((n) => n.uid === uid);
    const metagraph = minerNode
      ? {
          ip: minerNode.ip || "0.0.0.0",
          incentive: minerNode.incentive,
          emission: minerNode.emission.toString(),
          isValidator: minerNode.isValidator,
          stake: minerNode.totalStake.toString(),
        }
      : null;

    const validators = nodes.filter(
      (n) =>
        n.isValidator &&
        n.port > 0 &&
        n.ip !== "0.0.0.0" &&
        !n.ip.startsWith("10.") &&
        !n.ip.startsWith("192.168.") &&
        !n.ip.startsWith("127."),
    );

    const results = await Promise.allSettled(
      validators.map(async (v) => {
        const controller = new AbortController();
        const timeout = setTimeout(() => controller.abort(), 6000);
        try {
          const res = await fetch(
            `http://${v.ip}:${v.port}/v1/miner/${uid}/scores`,
            { signal: controller.signal, cache: "no-store" },
          );
          clearTimeout(timeout);
          if (!res.ok) return null;
          const data = await res.json();
          return { validatorUid: v.uid, ...data };
        } catch {
          clearTimeout(timeout);
          return null;
        }
      }),
    );

    const scores = results
      .map((r) => (r.status === "fulfilled" ? r.value : null))
      .filter((r) => r !== null && r.found !== false);

    return NextResponse.json(
      { uid, scores, metagraph },
      {
        headers: {
          "Cache-Control": "public, s-maxage=30, stale-while-revalidate=60",
          "x-djinn-source": "vercel-local",
        },
      },
    );
  } catch (err) {
    console.error("[network/miner] Failed:", err);
    return NextResponse.json(
      { uid, scores: [], metagraph: null },
      { status: 500, headers: { "x-djinn-source": "vercel-local" } },
    );
  }
}
