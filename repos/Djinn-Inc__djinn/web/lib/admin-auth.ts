import type { NextRequest } from "next/server";

const TOKEN_TTL_MS = 4 * 60 * 60 * 1000; // 4 hours

/**
 * v1727: separate ADMIN_SESSION_SECRET from ADMIN_PASSWORD per the
 * Codex audit. Pre-fix, sessions were signed with ADMIN_PASSWORD itself,
 * so rotating the password invalidated every active session AND a leak
 * of either had identical blast radius. With separation, the operator
 * can rotate the password without nuking sessions, and a session-secret
 * leak doesn't expose the login password.
 *
 * Falls back to ADMIN_PASSWORD only when ADMIN_SESSION_SECRET is unset
 * — preserves backward compat for existing deployments until operators
 * provision the new env var. New deployments should set
 * ADMIN_SESSION_SECRET (32+ random bytes, e.g.
 * `openssl rand -hex 32`).
 */
export function getSecret(): string {
  return process.env.ADMIN_SESSION_SECRET || process.env.ADMIN_PASSWORD || "";
}

// --- Web Crypto helpers (works on Vercel, Cloudflare, Deno, etc.) ---

function encode(s: string): Uint8Array {
  return new TextEncoder().encode(s);
}

function decode(buf: Uint8Array): string {
  return new TextDecoder().decode(buf);
}

function toBase64(s: string): string {
  // btoa works in all modern runtimes
  return btoa(s);
}

function fromBase64(b64: string): string {
  return atob(b64);
}

function toHex(buf: ArrayBuffer): string {
  return Array.from(new Uint8Array(buf))
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");
}

async function hmacSha256(key: string, data: string): Promise<string> {
  const keyBuf = encode(key).buffer as ArrayBuffer;
  const cryptoKey = await crypto.subtle.importKey(
    "raw",
    keyBuf,
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["sign"],
  );
  const dataBuf = encode(data).buffer as ArrayBuffer;
  const sig = await crypto.subtle.sign("HMAC", cryptoKey, dataBuf);
  return toHex(sig);
}

/** Constant-time string comparison using Web Crypto. */
function constantTimeEqual(a: string, b: string): boolean {
  if (a.length !== b.length) return false;
  const ab = encode(a);
  const bb = encode(b);
  let diff = 0;
  for (let i = 0; i < ab.length; i++) {
    diff |= ab[i] ^ bb[i];
  }
  return diff === 0;
}

export async function signToken(payload: string): Promise<string> {
  return hmacSha256(getSecret(), payload);
}

export async function createToken(): Promise<string> {
  const payload = `djinn-admin:${Date.now()}`;
  const sig = await signToken(payload);
  return toBase64(`${payload}:${sig}`);
}

export async function verifyToken(token: string): Promise<boolean> {
  const secret = getSecret();
  if (!secret) return false;
  try {
    const decoded = fromBase64(token);
    const parts = decoded.split(":");
    if (parts.length !== 3) return false;

    const [prefix, timestampStr, sig] = parts;
    if (prefix !== "djinn-admin") return false;

    const timestamp = parseInt(timestampStr, 10);
    if (isNaN(timestamp) || Date.now() - timestamp > TOKEN_TTL_MS) return false;

    const expectedSig = await signToken(`${prefix}:${timestampStr}`);
    return constantTimeEqual(sig, expectedSig);
  } catch {
    return false;
  }
}

/**
 * Verify an admin request via the httpOnly session cookie.
 *
 * v1727: removed the Bearer raw-password fallback. Pre-fix, an attacker
 * who learned the admin password (e.g., from any of the operator's
 * scripts that grep `.env`, or from a leak) could authenticate to any
 * admin endpoint without going through /api/admin/auth — defeating the
 * point of the session-token model. Now the only path is the cookie:
 * legitimate operators login through /api/admin/auth (which is rate-
 * limited per IP since v1727), receive a signed token, and use it via
 * the cookie.
 *
 * Server-to-server / scripted access should mint a token via /auth
 * rather than presenting the raw password.
 */
export async function verifyAdminRequest(request: NextRequest): Promise<boolean> {
  const cookie = request.cookies.get("djinn_admin_token")?.value;
  return Boolean(cookie && (await verifyToken(cookie)));
}
