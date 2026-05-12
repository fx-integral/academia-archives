import { NextRequest, NextResponse } from "next/server";
import { ethers } from "ethers";
import { ADDRESSES, ACCOUNT_ABI, detectContractVersion } from "@/lib/contracts";
import { DEFAULT_BOOTSTRAP } from "@/lib/validatorDiscovery";

/**
 * GET /api/settlement/{genius}/{idiot}
 *
 * Sprint B Stage 9: forward-first proxy. Bootstrap validator exposes
 * /v1/settlement/{genius}/{idiot} with the same shape. Falls back to
 * direct Account reads so the route keeps working while validators
 * roll out.
 */

const RPC_URL = process.env.BASE_RPC_URL || process.env.NEXT_PUBLIC_BASE_RPC_URL || "https://sepolia.base.org";
const VALIDATOR_FORWARD_TIMEOUT_MS = 12_000;

async function tryValidator(genius: string, idiot: string): Promise<Response | null> {
  try {
    const resp = await fetch(
      `${DEFAULT_BOOTSTRAP}/v1/settlement/${genius}/${idiot}`,
      {
        headers: { accept: "application/json" },
        signal: AbortSignal.timeout(VALIDATOR_FORWARD_TIMEOUT_MS),
      },
    );
    if (resp.ok) return resp;
  } catch {
    // Fall through to local RPC reads.
  }
  return null;
}

export async function GET(
  _request: NextRequest,
  { params }: { params: Promise<{ genius: string; idiot: string }> },
) {
  const { genius, idiot } = await params;

  if (!ethers.isAddress(genius) || !ethers.isAddress(idiot)) {
    return NextResponse.json(
      { error: "invalid_address", message: "Both genius and idiot must be valid Ethereum addresses" },
      { status: 400 },
    );
  }

  const geniusAddr = ethers.getAddress(genius);
  const idiotAddr = ethers.getAddress(idiot);

  const forwarded = await tryValidator(geniusAddr, idiotAddr);
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

  if (ADDRESSES.account === "0x0000000000000000000000000000000000000000") {
    return NextResponse.json(
      {
        genius: geniusAddr,
        idiot: idiotAddr,
        contract_version: 1,
        current_cycle: 0,
        signals_in_cycle: 0,
        total_purchases: 0,
        resolved_count: 0,
        audited_count: 0,
        audit_batch_count: 0,
        ready_for_settlement: false,
      },
      { headers: { "x-djinn-source": "vercel-local" } },
    );
  }

  try {
    const provider = new ethers.JsonRpcProvider(RPC_URL);

    const accountContract = new ethers.Contract(
      ADDRESSES.account,
      ACCOUNT_ABI,
      provider,
    );

    const version = await detectContractVersion(provider);

    if (version === 2) {
      const qs = await accountContract.getQueueState(geniusAddr, idiotAddr);
      const totalPurchases = Number(qs.totalPurchases);
      const resolvedCount = Number(qs.resolvedCount);
      const auditedCount = Number(qs.auditedCount);
      const batchCount = Number(qs.auditBatchCount);

      return NextResponse.json(
        {
          genius: geniusAddr,
          idiot: idiotAddr,
          contract_version: 2,
          total_purchases: totalPurchases,
          resolved_count: resolvedCount,
          audited_count: auditedCount,
          audit_batch_count: batchCount,
          ready_for_settlement: (resolvedCount - auditedCount) >= 10,
          current_cycle: batchCount,
          signals_in_cycle: totalPurchases,
        },
        { headers: { "x-djinn-source": "vercel-local" } },
      );
    }

    const [currentCycle, purchaseIds] = await Promise.all([
      accountContract.getCurrentCycle(geniusAddr, idiotAddr).catch(() => 0n),
      accountContract.getPurchaseIds(geniusAddr, idiotAddr).catch(() => []),
    ]);

    const cycle = Number(currentCycle);
    const signalsInCycle = Array.isArray(purchaseIds) ? purchaseIds.length : 0;
    const readyForSettlement = signalsInCycle >= 10;

    return NextResponse.json(
      {
        genius: geniusAddr,
        idiot: idiotAddr,
        contract_version: 1,
        current_cycle: cycle,
        signals_in_cycle: signalsInCycle,
        total_purchases: signalsInCycle,
        resolved_count: 0,
        audited_count: 0,
        audit_batch_count: cycle,
        ready_for_settlement: readyForSettlement,
      },
      { headers: { "x-djinn-source": "vercel-local" } },
    );
  } catch (error) {
    console.error("settlement_status_error", error);
    return NextResponse.json(
      { error: "internal_error", message: "Failed to fetch settlement status" },
      { status: 500 },
    );
  }
}
