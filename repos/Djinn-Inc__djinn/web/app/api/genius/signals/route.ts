import { NextRequest, NextResponse } from "next/server";
import { ethers } from "ethers";
import { ADDRESSES, SIGNAL_COMMITMENT_ABI } from "@/lib/contracts";
import { getIp, isRateLimited, rateLimitResponse } from "@/lib/rate-limit";
import { DEFAULT_BOOTSTRAP } from "@/lib/validatorDiscovery";

/**
 * GET /api/genius/signals?address=0x...&limit=20&offset=0&include_all=1
 *
 * Sprint B Stage 3: forward-first proxy. The bootstrap validator exposes
 * /v1/genius/{address}/signals with identical shape (signals with status
 * field, total, offset, limit). When that responds 200 we pass it through
 * (tagged x-djinn-source: validator). Falls back to the legacy 1.5M-block
 * SignalCommitted scan when the bootstrap is unreachable or returns 5xx,
 * so the route stays functional during validator upgrades.
 */

const RPC_URL = process.env.BASE_RPC_URL || process.env.NEXT_PUBLIC_BASE_RPC_URL || "https://sepolia.base.org";
const MAX_LIMIT = 100;
const SCAN_BLOCKS = 1_500_000;
const CHUNK_SIZE = 9_999;
const CONCURRENCY = 10;
const VALIDATOR_FORWARD_TIMEOUT_MS = 15_000;

async function tryValidator(address: string, search: string): Promise<Response | null> {
  try {
    const resp = await fetch(
      `${DEFAULT_BOOTSTRAP}/v1/genius/${address}/signals${search}`,
      {
        headers: { accept: "application/json" },
        signal: AbortSignal.timeout(VALIDATOR_FORWARD_TIMEOUT_MS),
      },
    );
    if (resp.ok) return resp;
  } catch {
    // Fall through to local scan.
  }
  return null;
}

export async function GET(request: NextRequest) {
  // Each fallback call triggers a 1.5M-block range scan. Cap per-IP traffic.
  if (isRateLimited("genius-signals", getIp(request), 30)) {
    return rateLimitResponse();
  }

  const url = new URL(request.url);
  const { searchParams } = url;
  const address = searchParams.get("address");
  const limit = Math.min(parseInt(searchParams.get("limit") || "20", 10), MAX_LIMIT);
  const offset = parseInt(searchParams.get("offset") || "0", 10);
  const includeAll = searchParams.get("include_all") === "1";

  if (!address || !ethers.isAddress(address)) {
    return NextResponse.json(
      { error: "invalid_address", message: "Provide a valid Ethereum address as ?address=0x..." },
      { status: 400 },
    );
  }

  const checksumAddr = ethers.getAddress(address);

  // Build the validator search string (strip address from querystring; it's
  // now a path param). Preserve limit, offset, include_all.
  const forwardParams = new URLSearchParams();
  forwardParams.set("limit", String(limit));
  forwardParams.set("offset", String(offset));
  if (includeAll) forwardParams.set("include_all", "1");
  const forwardSearch = `?${forwardParams.toString()}`;

  const forwarded = await tryValidator(checksumAddr, forwardSearch);
  if (forwarded) {
    const body = await forwarded.text();
    return new NextResponse(body, {
      status: 200,
      headers: {
        "content-type": "application/json",
        "cache-control": "public, s-maxage=15, stale-while-revalidate=60",
        "x-djinn-source": "validator",
      },
    });
  }

  if (ADDRESSES.signalCommitment === "0x0000000000000000000000000000000000000000") {
    return NextResponse.json({ signals: [], total: 0, offset, limit });
  }

  try {
    const provider = new ethers.JsonRpcProvider(RPC_URL);
    const contract = new ethers.Contract(ADDRESSES.signalCommitment, SIGNAL_COMMITMENT_ABI, provider);

    const filter = contract.filters.SignalCommitted(null, checksumAddr);
    const currentBlock = await provider.getBlockNumber();
    const fromBlock = Math.max(0, currentBlock - SCAN_BLOCKS);
    const chunkRanges: [number, number][] = [];
    for (let start = fromBlock; start <= currentBlock; start += CHUNK_SIZE) {
      chunkRanges.push([start, Math.min(start + CHUNK_SIZE - 1, currentBlock)]);
    }

    const events: (ethers.EventLog | ethers.Log)[] = [];
    for (let i = 0; i < chunkRanges.length; i += CONCURRENCY) {
      const batch = chunkRanges.slice(i, i + CONCURRENCY);
      const results = await Promise.allSettled(
        batch.map(([start, end]) => contract.queryFilter(filter, start, end)),
      );
      for (const result of results) {
        if (result.status === "fulfilled") events.push(...result.value);
      }
    }

    const now = Math.floor(Date.now() / 1000);
    const signals: Record<string, unknown>[] = [];

    const ENRICH = 15;
    const enrichFns = events.reverse().map((event) => async () => {
      const args = (event as ethers.EventLog).args;
      if (!args) return null;

      const expiresAt = Number(args.expiresAt);
      let status = "active";
      if (expiresAt < now) status = "expired";

      if (status === "active") {
        try {
          const isActive = await contract.isActive(args.signalId);
          if (!isActive) status = "cancelled";
        } catch {
          status = "unknown";
        }
      }

      return {
        signal_id: args.signalId.toString(),
        genius: checksumAddr,
        sport: args.sport,
        fee_bps: Number(args.maxPriceBps),
        sla_multiplier_bps: Number(args.slaMultiplierBps),
        max_notional: args.maxNotional.toString(),
        min_notional: "0",
        expires_at_unix: expiresAt,
        status,
        block_number: event.blockNumber,
      };
    });

    for (let i = 0; i < enrichFns.length; i += ENRICH) {
      const batch = enrichFns.slice(i, i + ENRICH);
      const results = await Promise.all(batch.map((fn) => fn()));
      for (const s of results) {
        if (s) signals.push(s);
      }
    }

    const filtered = includeAll
      ? signals
      : signals.filter((s) => s.status === "active");

    const paged = filtered.slice(offset, offset + limit);

    return NextResponse.json(
      { signals: paged, total: filtered.length, offset, limit },
      {
        headers: {
          "Cache-Control": "public, s-maxage=15, stale-while-revalidate=60",
          "x-djinn-source": "vercel-local",
        },
      },
    );
  } catch (error) {
    console.error("genius_signals_error", error);
    return NextResponse.json(
      { error: "internal_error", message: "Failed to fetch signals" },
      { status: 500, headers: { "x-djinn-source": "vercel-local" } },
    );
  }
}
