import { NextRequest, NextResponse } from "next/server";
import { createToken, verifyToken } from "@/lib/admin-auth";
import { getIp, isRateLimited, rateLimitResponse } from "@/lib/rate-limit";

/**
 * GET /api/admin/auth
 *
 * Check if the user has a valid admin session (via httpOnly cookie).
 */
export async function GET(request: NextRequest) {
  const token = request.cookies.get("djinn_admin_token")?.value;
  if (token && (await verifyToken(token))) {
    return NextResponse.json({ authenticated: true });
  }
  return NextResponse.json({ authenticated: false }, { status: 401 });
}

/**
 * POST /api/admin/auth
 *
 * Verify admin password server-side. The password is never sent to the client.
 * Returns an HMAC-signed session token stored as an httpOnly cookie.
 *
 * v1727: hardened per Codex audit (2026-05-05) Medium #1.
 *   - Per-route rate limit: 5 attempts / IP / 60s. Pre-fix, the route only
 *     fell under the global 200 req/min middleware, which was effectively
 *     wide open for online password guessing.
 *   - Constant-time compare uses HMAC-of-each-side comparison so input-length
 *     mismatch no longer short-circuits early (which leaked password length
 *     via timing).
 */
export async function POST(request: NextRequest) {
  if (isRateLimited("admin-auth-login", getIp(request), 5, 60_000)) {
    return rateLimitResponse();
  }

  const expected = process.env.ADMIN_PASSWORD;
  if (!expected) {
    return NextResponse.json(
      { error: "Admin authentication not configured" },
      { status: 503 },
    );
  }

  let body: { password?: string };
  try {
    body = await request.json();
  } catch {
    return NextResponse.json({ error: "Invalid JSON" }, { status: 400 });
  }

  const submitted = typeof body.password === "string" ? body.password : "";
  if (!(await constantTimeStringEqual(submitted, expected))) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  }

  const token = await createToken();

  const response = NextResponse.json({ ok: true });
  response.cookies.set("djinn_admin_token", token, {
    httpOnly: true,
    secure: process.env.NODE_ENV === "production",
    sameSite: "strict",
    maxAge: 60 * 60 * 4, // 4 hours
    path: "/",
  });

  return response;
}

/**
 * Constant-time string compare that runs in time independent of either
 * input's length. Both sides are HMAC'd under a per-process random key,
 * then the resulting fixed-length 32-byte tags are compared. An attacker
 * timing the request cannot learn whether they got the length right vs
 * the bytes right, vs a partial-prefix match.
 */
async function constantTimeStringEqual(a: string, b: string): Promise<boolean> {
  // Per-process random key seeds the comparison HMAC. New each cold start;
  // doesn't need to persist across requests for this check to be sound.
  const key = await getCompareKey();
  const enc = new TextEncoder();
  const ah = await crypto.subtle.sign("HMAC", key, enc.encode(a).buffer as ArrayBuffer);
  const bh = await crypto.subtle.sign("HMAC", key, enc.encode(b).buffer as ArrayBuffer);
  const aArr = new Uint8Array(ah);
  const bArr = new Uint8Array(bh);
  let diff = 0;
  // Both arrays are 32 bytes (SHA-256). Loop is constant.
  for (let i = 0; i < 32; i++) diff |= aArr[i] ^ bArr[i];
  return diff === 0;
}

let _compareKey: CryptoKey | null = null;
async function getCompareKey(): Promise<CryptoKey> {
  if (_compareKey) return _compareKey;
  const raw = crypto.getRandomValues(new Uint8Array(32)).buffer;
  _compareKey = await crypto.subtle.importKey(
    "raw",
    raw as ArrayBuffer,
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["sign"],
  );
  return _compareKey;
}
