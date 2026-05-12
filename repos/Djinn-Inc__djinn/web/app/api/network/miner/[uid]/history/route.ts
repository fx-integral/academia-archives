import { NextResponse } from "next/server";
import { discoverMetagraph } from "@/lib/bt-metagraph";
import { DEFAULT_BOOTSTRAP } from "@/lib/validatorDiscovery";

/**
 * GET /api/network/miner/[uid]/history
 *
 * Sprint B Stage 2: forward-first proxy. The bootstrap validator already
 * exposes /v1/miner/{uid}/history with the identical {uid, history}
 * shape. When that responds 200 with non-empty history we pass it through
 * (tagged x-djinn-source: validator). Falls back to the per-validator
 * fan-out scan when the bootstrap is unreachable or returns empty.
 */

const VALIDATOR_FORWARD_TIMEOUT_MS = 12_000;

async function tryValidator(uid: number, hours: number): Promise<Response | null> {
  try {
    const resp = await fetch(
      `${DEFAULT_BOOTSTRAP}/v1/miner/${uid}/history?hours=${hours}`,
      {
        headers: { accept: "application/json" },
        signal: AbortSignal.timeout(VALIDATOR_FORWARD_TIMEOUT_MS),
      },
    );
    if (!resp.ok) return null;
    // Only treat as a valid forward if the bootstrap actually has data;
    // an empty history means telemetry hasn't synced to the bootstrap
    // yet, so the fan-out path might still find it on another validator.
    const data = (await resp.clone().json()) as { history?: unknown[] };
    if (Array.isArray(data.history) && data.history.length > 0) {
      return resp;
    }
  } catch {
    // Fall through to fan-out.
  }
  return null;
}

export async function GET(
  request: Request,
  { params }: { params: Promise<{ uid: string }> },
) {
  const { uid: uidStr } = await params;
  const uid = parseInt(uidStr, 10);
  if (isNaN(uid) || uid < 0 || uid > 65535) {
    return NextResponse.json({ error: "Invalid UID" }, { status: 400 });
  }

  const url = new URL(request.url);
  const hours = parseInt(url.searchParams.get("hours") ?? "168", 10);

  const forwarded = await tryValidator(uid, hours);
  if (forwarded) {
    const body = await forwarded.text();
    return new NextResponse(body, {
      status: 200,
      headers: {
        "content-type": "application/json",
        "cache-control": "public, s-maxage=300, stale-while-revalidate=600",
        "x-djinn-source": "validator",
      },
    });
  }

  try {
    const { nodes } = await discoverMetagraph();

    const validators = nodes.filter(
      (n) =>
        n.isValidator &&
        n.port > 0 &&
        n.ip !== "0.0.0.0" &&
        !n.ip.startsWith("10.") &&
        !n.ip.startsWith("192.168.") &&
        !n.ip.startsWith("127."),
    );

    if (validators.length === 0) {
      return NextResponse.json(
        { uid, history: [] },
        {
          headers: {
            "Cache-Control": "public, s-maxage=300, stale-while-revalidate=600",
            "x-djinn-source": "vercel-local",
          },
        },
      );
    }

    // Query validators by stake (highest first), return first non-empty result.
    const sorted = validators.sort((a, b) =>
      b.totalStake > a.totalStake ? 1 : -1,
    );

    let history: unknown[] = [];
    for (const v of sorted) {
      try {
        const controller = new AbortController();
        const timeout = setTimeout(() => controller.abort(), 10000);
        const res = await fetch(
          `http://${v.ip}:${v.port}/v1/miner/${uid}/history?hours=${hours}`,
          { signal: controller.signal, cache: "no-store" },
        );
        clearTimeout(timeout);
        if (!res.ok) continue;
        const data = await res.json();
        const h = data.history ?? [];
        if (h.length > 0) {
          history = h;
          break;
        }
      } catch {
        continue;
      }
    }

    return NextResponse.json(
      { uid, history },
      {
        headers: {
          "Cache-Control": "public, s-maxage=300, stale-while-revalidate=600",
          "x-djinn-source": "vercel-local",
        },
      },
    );
  } catch (err) {
    console.error("[network/miner/history] Failed:", err);
    return NextResponse.json(
      { uid, history: [] },
      { status: 500, headers: { "x-djinn-source": "vercel-local" } },
    );
  }
}
