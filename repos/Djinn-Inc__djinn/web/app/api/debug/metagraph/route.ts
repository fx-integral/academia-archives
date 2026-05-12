import { NextRequest, NextResponse } from "next/server";
import { verifyAdminRequest } from "@/lib/admin-auth";
import { discoverMetagraph, discoverMinerUrl } from "@/lib/bt-metagraph";
import { DEFAULT_BOOTSTRAP } from "@/lib/validatorDiscovery";

/**
 * GET /api/debug/metagraph — diagnostic endpoint for metagraph discovery.
 * Returns what the server sees when discovering miners and validators.
 * Protected by admin session cookie (set via POST /api/admin/auth).
 *
 * Sprint-A Stage A-2: when VALIDATOR_ADMIN_API_KEY is set, forward the
 * request to the bootstrap validator's /v1/debug/metagraph (which reads its
 * hot in-memory metagraph with no subtensor RPC). Falls back to the
 * subtensor-RPC path if the validator is down or the key is unset.
 */

const VALIDATOR_TIMEOUT_MS = 5_000;

async function tryValidatorSnapshot(): Promise<Response | null> {
  const adminKey = process.env.VALIDATOR_ADMIN_API_KEY;
  if (!adminKey) return null;
  try {
    const resp = await fetch(`${DEFAULT_BOOTSTRAP}/v1/debug/metagraph`, {
      headers: { authorization: `Bearer ${adminKey}`, accept: "application/json" },
      signal: AbortSignal.timeout(VALIDATOR_TIMEOUT_MS),
    });
    if (resp.ok) return resp;
  } catch {
    // Fall through to subtensor path.
  }
  return null;
}

export async function GET(request: NextRequest) {
  if (!(await verifyAdminRequest(request))) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  }

  const validatorResp = await tryValidatorSnapshot();
  if (validatorResp) {
    const body = await validatorResp.text();
    return new NextResponse(body, {
      status: 200,
      headers: { "content-type": "application/json", "x-djinn-source": "validator" },
    });
  }

  const env = {
    BT_NETUID: process.env.BT_NETUID ?? "(unset)",
    BT_NETWORK: process.env.BT_NETWORK ?? "(unset)",
    BT_RPC_URL: process.env.BT_RPC_URL ?? "(unset)",
    MINER_URL: process.env.MINER_URL ? "(set)" : "(unset)",
    NEXT_PUBLIC_MINER_URL: process.env.NEXT_PUBLIC_MINER_URL ? "(set)" : "(unset)",
  };

  try {
    const start = Date.now();
    const snap = await discoverMetagraph();
    const discoveryMs = Date.now() - start;

    const nodes = snap.nodes;
    const publicNodes = nodes.filter(
      (n) => n.port > 0 && n.ip !== "0.0.0.0" && !n.ip.startsWith("127.") && !n.ip.startsWith("10.") && !n.ip.startsWith("192.168."),
    );
    // ALL validators (including stake-only with no axon)
    const allValidators = nodes.filter((n) => n.isValidator);
    const validators = publicNodes.filter((n) => n.isValidator);
    const miners = publicNodes.filter((n) => !n.isValidator);

    const minerStart = Date.now();
    const minerUrl = await discoverMinerUrl();
    const minerDiscoveryMs = Date.now() - minerStart;

    // Probe top validators + miners for version via /health (parallel, best-effort)
    const probeHealth = async (ip: string, port: number): Promise<string | null> => {
      try {
        const res = await fetch(`http://${ip}:${port}/health`, {
          signal: AbortSignal.timeout(3000),
        });
        const data = await res.json();
        return data.version ?? null;
      } catch {
        return null;
      }
    };

    const topValidators = allValidators
      .sort((a, b) => (b.totalStake > a.totalStake ? 1 : b.totalStake < a.totalStake ? -1 : 0))
      .slice(0, 20);
    const topMiners = miners.slice(0, 10);

    const [valVersions, minerVersions] = await Promise.all([
      Promise.all(topValidators.map((n) => probeHealth(n.ip, n.port))),
      Promise.all(topMiners.map((n) => probeHealth(n.ip, n.port))),
    ]);

    return NextResponse.json({
      env,
      discoveryMs,
      minerDiscoveryMs,
      totalNodes: nodes.length,
      publicNodes: publicNodes.length,
      validators: allValidators.length,
      activeValidators: validators.length,
      miners: miners.length,
      minerUrl,
      cacheAge: snap.fetchedAt ? Date.now() - snap.fetchedAt : null,
      topMiners: topMiners.map((n, i) => ({
        uid: n.uid,
        hotkey: n.hotkey,
        coldkey: n.coldkey,
        ip: n.ip,
        port: n.port,
        stake: n.totalStake.toString(),
        version: minerVersions[i],
      })),
      topValidators: topValidators.map((n, i) => ({
        uid: n.uid,
        hotkey: n.hotkey,
        coldkey: n.coldkey,
        ip: n.ip,
        port: n.port,
        active: n.port > 0 && n.ip !== "0.0.0.0",
        stake: n.totalStake.toString(),
        version: valVersions[i],
      })),
    });
  } catch (err) {
    return NextResponse.json({
      env,
      error: err instanceof Error ? err.message : String(err),
    }, { status: 500 });
  }
}
