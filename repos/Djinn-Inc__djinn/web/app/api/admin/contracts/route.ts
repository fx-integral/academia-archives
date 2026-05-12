import { NextResponse, type NextRequest } from "next/server";
import { ethers } from "ethers";
import { verifyAdminRequest } from "@/lib/admin-auth";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

interface ContractProbe {
  name: string;
  address: string;
  paused: boolean | null;
  reason?: string;
}

interface ContractStatusResponse {
  chainId: number;
  rpcUrl: string;
  blockNumber: number | null;
  blockTimestamp: number | null;
  blockLagSeconds: number | null;
  contracts: ContractProbe[];
  probedAt: number;
  elapsedMs: number;
  rpcError?: string;
}

const PAUSED_ABI = ["function paused() external view returns (bool)"];

const CONTRACTS: ReadonlyArray<{ name: string; envKey: string }> = [
  { name: "SignalCommitment", envKey: "NEXT_PUBLIC_SIGNAL_COMMITMENT_ADDRESS" },
  { name: "Escrow", envKey: "NEXT_PUBLIC_ESCROW_ADDRESS" },
  { name: "Collateral", envKey: "NEXT_PUBLIC_COLLATERAL_ADDRESS" },
  { name: "Account", envKey: "NEXT_PUBLIC_ACCOUNT_ADDRESS" },
  { name: "Audit", envKey: "NEXT_PUBLIC_AUDIT_ADDRESS" },
  { name: "OutcomeVoting", envKey: "NEXT_PUBLIC_OUTCOME_VOTING_ADDRESS" },
  { name: "CreditLedger", envKey: "NEXT_PUBLIC_CREDIT_LEDGER_ADDRESS" },
];

const ZERO = "0x0000000000000000000000000000000000000000";

async function probePaused(
  provider: ethers.Provider,
  name: string,
  address: string,
): Promise<ContractProbe> {
  if (!address || address === ZERO) {
    return { name, address: ZERO, paused: null, reason: "not configured" };
  }
  try {
    const contract = new ethers.Contract(address, PAUSED_ABI, provider);
    const paused = (await contract.paused()) as boolean;
    return { name, address, paused };
  } catch (err) {
    return {
      name,
      address,
      paused: null,
      reason: err instanceof Error ? err.message.slice(0, 140) : "call reverted",
    };
  }
}

export async function GET(request: NextRequest) {
  if (!(await verifyAdminRequest(request))) {
    return NextResponse.json({ error: "unauthorized" }, { status: 401 });
  }

  const started = Date.now();
  const rpcUrl =
    process.env.BASE_RPC_URL ||
    process.env.NEXT_PUBLIC_BASE_RPC_URL ||
    "https://sepolia.base.org";
  const chainId = Number(process.env.NEXT_PUBLIC_CHAIN_ID ?? "84532");

  const provider = new ethers.JsonRpcProvider(rpcUrl, chainId, {
    staticNetwork: true,
  });

  let blockNumber: number | null = null;
  let blockTimestamp: number | null = null;
  let rpcError: string | undefined;

  try {
    const block = await provider.getBlock("latest");
    blockNumber = block?.number ?? null;
    blockTimestamp = block?.timestamp ?? null;
  } catch (err) {
    rpcError = err instanceof Error ? err.message.slice(0, 140) : "rpc error";
  }

  const contracts = await Promise.all(
    CONTRACTS.map((c) =>
      probePaused(provider, c.name, process.env[c.envKey] ?? ZERO),
    ),
  );

  const nowSec = Math.floor(Date.now() / 1000);
  const blockLagSeconds =
    blockTimestamp !== null ? nowSec - blockTimestamp : null;

  const response: ContractStatusResponse = {
    chainId,
    rpcUrl: rpcUrl.replace(/\/v2\/[^/]+/, "/v2/***"),
    blockNumber,
    blockTimestamp,
    blockLagSeconds,
    contracts,
    probedAt: Date.now(),
    elapsedMs: Date.now() - started,
    rpcError,
  };

  return NextResponse.json(response, {
    headers: { "cache-control": "no-store, max-age=0" },
  });
}
