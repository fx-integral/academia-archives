import { NextRequest, NextResponse } from "next/server";
import { ethers } from "ethers";
import { createChallenge, buildChallengeMessage } from "@/lib/api-auth";
import { getIp, isRateLimited, rateLimitResponse } from "@/lib/rate-limit";

/**
 * POST /api/auth/connect
 *
 * Initiate an API session. Returns a challenge nonce the client must sign
 * with their wallet to prove ownership.
 *
 * Body: { address: "0x..." }
 * Response: { challenge: "Sign this message...", nonce: "abc123...", expires_in: 300 }
 */
export async function POST(request: NextRequest) {
  if (isRateLimited("auth-connect", getIp(request), 20, 60_000)) {
    return rateLimitResponse();
  }

  try {
    const body = await request.json();
    const { address, scope: rawScope } = body;

    if (!address || typeof address !== "string") {
      return NextResponse.json({ error: "address is required" }, { status: 400 });
    }

    let checksummed: string;
    try {
      checksummed = ethers.getAddress(address);
    } catch {
      return NextResponse.json({ error: "Invalid Ethereum address" }, { status: 400 });
    }

    // v1726: scope is now bound into the nonce at challenge-creation time so
    // the wallet's signature covers it. Parse the same shape the legacy
    // verify route accepted (snake_case fields), preserving backwards-compat
    // for clients that pass scope here. Clients that omit scope get the
    // default (no constraints) baked into the nonce.
    const scope: import("@/lib/api-auth").SessionScope = {};
    if (rawScope && typeof rawScope === "object") {
      if (rawScope.role && ["genius", "idiot", "both"].includes(rawScope.role)) {
        scope.role = rawScope.role;
      }
      if (typeof rawScope.max_spend_usdc === "number" && rawScope.max_spend_usdc > 0) {
        scope.maxSpendUsdc = rawScope.max_spend_usdc;
      }
      if (typeof rawScope.expires_in_hours === "number" && rawScope.expires_in_hours > 0) {
        scope.expiresInHours = Math.min(rawScope.expires_in_hours, 24);
      }
    }

    const { nonce } = await createChallenge(checksummed, scope);
    const challenge = buildChallengeMessage(nonce);

    return NextResponse.json({
      challenge,
      nonce,
      expires_in: 300,
    });
  } catch {
    return NextResponse.json({ error: "Invalid request body" }, { status: 400 });
  }
}
