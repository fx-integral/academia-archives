import { NextResponse } from "next/server";
import { ADDRESSES } from "@/lib/contracts";
import { discoverMetagraph, isPublicIp } from "@/lib/bt-metagraph";
import { DEFAULT_BOOTSTRAP } from "@/lib/validatorDiscovery";

/**
 * GET /api/network/config
 *
 * Returns validator endpoints, Shamir parameters, and contract addresses
 * needed by the SDK for signal creation.
 *
 * Sprint B Stage 4: forward-first proxy. The bootstrap validator exposes
 * /v1/network/config with the same shape — static clients can hit it
 * directly. Falls back to the legacy metagraph + per-validator probe flow
 * when the bootstrap is unreachable so the route stays functional during
 * validator upgrades.
 */

const VALIDATOR_FORWARD_TIMEOUT_MS = 12_000;

const DEFAULT_VALIDATOR_ENDPOINTS = [
  "0:Djinn:https://v0.djinn.gg",
  "1:GeneralTensor:https://v1.djinn.gg",
  "2:Yuma:https://v2.djinn.gg",
  "86:Rizzo:https://v86.djinn.gg",
  "189:Kooltek68:http://161.97.150.248:8421",
  "213:TAO.com:https://v213.djinn.gg",
];

function parseFallbackValidators(): { uid: number; name: string; endpoint: string }[] {
  const raw = process.env.VALIDATOR_ENDPOINTS;
  const entries = raw ? raw.split(",").map((s) => s.trim()).filter(Boolean) : DEFAULT_VALIDATOR_ENDPOINTS;
  return entries.map((entry) => {
    const [uid, name, ...rest] = entry.split(":");
    return { uid: parseInt(uid, 10), name, endpoint: rest.join(":") };
  });
}

async function discoverValidators(): Promise<{ uid: number; name: string; endpoint: string }[]> {
  try {
    const { nodes } = await discoverMetagraph();
    const validators = nodes
      .filter((n) => n.isValidator && n.port > 0 && isPublicIp(n.ip))
      .sort((a, b) => (b.totalStake > a.totalStake ? 1 : b.totalStake < a.totalStake ? -1 : 0));
    if (validators.length > 0) {
      return validators.map((v) => ({
        uid: v.uid,
        name: `UID ${v.uid}`,
        endpoint: `http://${v.ip}:${v.port}`,
      }));
    }
  } catch (err) {
    console.warn("[network/config] Metagraph discovery failed, using fallback:", err);
  }
  return parseFallbackValidators();
}

let cachedConfig: { data: unknown; expiresAt: number } | null = null;
const CACHE_TTL = 5 * 60 * 1000;

async function fetchValidatorIdentity(v: { uid: number; name: string; endpoint: string }) {
  try {
    const controller = new AbortController();
    // 10s timeout (was 5s). Cold connections from Vercel edge to a sleepy
    // operator VPS occasionally exceed 5s; transient timeouts at this layer
    // marked the validator `online: false`, which then got 5-min-cached and
    // dropped the validator from /api/network/config responses for that
    // window. Stress runs and the web purchase flow then fanned out to a
    // smaller set than the actual fleet, missing one validator's bundle +
    // BPA/WPA. 10s is comfortably under the parent request's wall-clock
    // budget while catching most cold-start tails.
    const timeout = setTimeout(() => controller.abort(), 10_000);
    const resp = await fetch(`${v.endpoint}/v1/identity`, {
      signal: controller.signal,
    });
    clearTimeout(timeout);
    if (!resp.ok) return { ...v, online: false, pubkey: null };
    const data = await resp.json();
    return {
      ...v,
      online: true,
      pubkey: data.pubkey || data.public_key || null,
    };
  } catch {
    return { ...v, online: false, pubkey: null };
  }
}

async function tryValidator(): Promise<Response | null> {
  try {
    const resp = await fetch(`${DEFAULT_BOOTSTRAP}/v1/network/config`, {
      headers: { accept: "application/json" },
      signal: AbortSignal.timeout(VALIDATOR_FORWARD_TIMEOUT_MS),
    });
    if (resp.ok) return resp;
  } catch {
    // Fall through to local discovery.
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
        "cache-control": "public, max-age=300",
        "x-djinn-source": "validator",
      },
    });
  }

  const now = Date.now();
  if (cachedConfig && now < cachedConfig.expiresAt) {
    return NextResponse.json(cachedConfig.data, {
      headers: {
        "Cache-Control": "public, max-age=300",
        "x-djinn-source": "vercel-local",
      },
    });
  }

  const validators = await discoverValidators();
  const results = await Promise.all(validators.map(fetchValidatorIdentity));

  const config = {
    validators: results
      .filter((v) => v.online)
      .map((v) => ({
        uid: v.uid,
        name: v.name,
        endpoint: v.endpoint,
        pubkey: v.pubkey,
      })),
    chain_id: parseInt(
      process.env.NEXT_PUBLIC_BASE_CHAIN_ID || "84532",
      10,
    ),
    contracts: {
      signal_commitment: ADDRESSES.signalCommitment,
      escrow: ADDRESSES.escrow,
      collateral: ADDRESSES.collateral,
      account: ADDRESSES.account,
      audit: ADDRESSES.audit,
      credit_ledger: ADDRESSES.creditLedger,
      key_recovery: ADDRESSES.keyRecovery,
      usdc: ADDRESSES.usdc,
    },
    shamir: {
      n: parseInt(process.env.SHAMIR_MAX || "10", 10),
      k: parseInt(process.env.SHAMIR_MIN || "3", 10),
    },
    cached_at: new Date().toISOString(),
  };

  cachedConfig = { data: config, expiresAt: now + CACHE_TTL };
  return NextResponse.json(config, {
    headers: {
      "Cache-Control": "public, max-age=300",
      "x-djinn-source": "vercel-local",
    },
  });
}
