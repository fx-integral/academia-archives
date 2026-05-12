import { NextRequest, NextResponse } from "next/server";
import { ethers } from "ethers";
import { ADDRESSES, ESCROW_ABI, ERC20_ABI, CREDIT_LEDGER_ABI } from "@/lib/contracts";
import { getIp, isRateLimited, rateLimitResponse } from "@/lib/rate-limit";
import { DEFAULT_BOOTSTRAP } from "@/lib/validatorDiscovery";

/**
 * GET /api/idiot/balance?address=0x...
 *
 * Sprint B Stage 5: forward-first proxy. Bootstrap validator exposes
 * /v1/idiot/{address}/balance with the same shape. Falls back to direct
 * RPC reads (Escrow.getBalance + USDC.balanceOf + CreditLedger.balanceOf)
 * so the route keeps working while validators roll out.
 */

const RPC_URL = process.env.BASE_RPC_URL || process.env.NEXT_PUBLIC_BASE_RPC_URL || "https://sepolia.base.org";
const VALIDATOR_FORWARD_TIMEOUT_MS = 12_000;

async function tryValidator(checksumAddr: string): Promise<Response | null> {
  try {
    const resp = await fetch(`${DEFAULT_BOOTSTRAP}/v1/idiot/${checksumAddr}/balance`, {
      headers: { accept: "application/json" },
      signal: AbortSignal.timeout(VALIDATOR_FORWARD_TIMEOUT_MS),
    });
    if (resp.ok) return resp;
  } catch {
    // Fall through to local RPC reads.
  }
  return null;
}

export async function GET(request: NextRequest) {
  if (isRateLimited("idiot-balance", getIp(request), 120)) {
    return rateLimitResponse();
  }

  const { searchParams } = new URL(request.url);
  const raw = searchParams.get("address");

  if (!raw || !ethers.isAddress(raw)) {
    return NextResponse.json(
      { error: "invalid_address", message: "Provide a valid Ethereum address as ?address=0x..." },
      { status: 400 },
    );
  }

  const checksumAddr = ethers.getAddress(raw);

  const forwarded = await tryValidator(checksumAddr);
  if (forwarded) {
    const body = await forwarded.text();
    return new NextResponse(body, {
      status: 200,
      headers: {
        "content-type": "application/json",
        "x-djinn-source": "validator",
      },
    });
  }

  if (ADDRESSES.escrow === "0x0000000000000000000000000000000000000000") {
    return NextResponse.json(
      {
        address: checksumAddr,
        escrow_balance_usdc: 0,
        wallet_usdc: 0,
        credits: 0,
      },
      { headers: { "x-djinn-source": "vercel-local" } },
    );
  }

  try {
    const provider = new ethers.JsonRpcProvider(RPC_URL);

    const [escrowBalance, walletUsdc, credits] = await Promise.all([
      new ethers.Contract(ADDRESSES.escrow, ESCROW_ABI, provider)
        .getBalance(checksumAddr)
        .catch(() => 0n),
      new ethers.Contract(ADDRESSES.usdc, ERC20_ABI, provider)
        .balanceOf(checksumAddr)
        .catch(() => 0n),
      ADDRESSES.creditLedger !== "0x0000000000000000000000000000000000000000"
        ? new ethers.Contract(ADDRESSES.creditLedger, CREDIT_LEDGER_ABI, provider)
            .balanceOf(checksumAddr)
            .catch(() => 0n)
        : Promise.resolve(0n),
    ]);

    return NextResponse.json(
      {
        address: checksumAddr,
        escrow_balance_usdc: Number(escrowBalance) / 1e6,
        wallet_usdc: Number(walletUsdc) / 1e6,
        credits: Number(credits) / 1e6,
      },
      { headers: { "x-djinn-source": "vercel-local" } },
    );
  } catch (error) {
    console.error("balance_error", error);
    return NextResponse.json(
      { error: "internal_error", message: "Failed to fetch balance" },
      { status: 500 },
    );
  }
}
