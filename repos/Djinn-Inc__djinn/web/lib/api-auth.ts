import type { NextRequest } from "next/server";
import { ethers } from "ethers";

// ---------------------------------------------------------------------------
// Session token auth for the Djinn API (wallet-signature based)
// ---------------------------------------------------------------------------

const TOKEN_TTL_MS = 24 * 60 * 60 * 1000; // 24 hours
const CHALLENGE_TTL_MS = 5 * 60 * 1000; // 5 minutes

// Challenges are stateless (HMAC-signed) so they work across serverless
// instances. No in-memory state needed.

function encode(s: string): Uint8Array {
  return new TextEncoder().encode(s);
}

function toHex(buf: ArrayBuffer): string {
  return Array.from(new Uint8Array(buf))
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");
}

const _secret = process.env.API_SESSION_SECRET || process.env.ADMIN_PASSWORD;
if (!_secret) throw new Error("API_SESSION_SECRET or ADMIN_PASSWORD must be set");
const secret: string = _secret;

function getSecret(): string {
  return secret;
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

// ---------------------------------------------------------------------------
// Challenge management
// ---------------------------------------------------------------------------

/**
 * Canonicalize a scope object so the same logical scope always serializes
 * to the same string (independent of key insertion order). The serialized
 * form gets embedded in the challenge nonce so the wallet's signature
 * cryptographically binds the scope — preventing the verify-time scope
 * substitution flagged by the 2026-05-05 codex audit (Medium).
 */
function canonicalizeScope(scope: SessionScope | null | undefined): string {
  if (!scope) return "{}";
  const ordered: Record<string, unknown> = {};
  if (scope.role) ordered.role = scope.role;
  if (typeof scope.maxSpendUsdc === "number") ordered.maxSpendUsdc = scope.maxSpendUsdc;
  if (typeof scope.expiresInHours === "number") ordered.expiresInHours = scope.expiresInHours;
  return JSON.stringify(ordered);
}

function b64urlEncode(s: string): string {
  // Base64url over UTF-8 input. Avoids the ":" delimiter colliding with the
  // nonce structure.
  return Buffer.from(s, "utf-8").toString("base64").replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

function b64urlDecode(s: string): string {
  const padded = s.replace(/-/g, "+").replace(/_/g, "/") + "===".slice((s.length + 3) % 4);
  return Buffer.from(padded, "base64").toString("utf-8");
}

/**
 * Create a stateless challenge nonce. The nonce embeds the address,
 * timestamp, and the requested scope (canonicalized + base64url-encoded),
 * all signed with HMAC so any serverless instance can verify it without
 * shared state. The scope is part of the HMAC payload, so a captured
 * signed challenge cannot be replayed with a different scope at /verify
 * time. Codex audit 2026-05-05 Medium #2.
 *
 * Format: {random32hex}:{address}:{timestamp}:{scopeB64url}:{hmac}
 */
export async function createChallenge(
  address: string,
  scope?: SessionScope,
): Promise<{ nonce: string; scope: SessionScope }> {
  const random = toHex(crypto.getRandomValues(new Uint8Array(16)).buffer as ArrayBuffer);
  const ts = Date.now().toString();
  const addr = address.toLowerCase();
  const safeScope = scope ?? {};
  const scopeStr = canonicalizeScope(safeScope);
  const scopeB64 = b64urlEncode(scopeStr);
  const payload = `${random}:${addr}:${ts}:${scopeB64}`;
  const sig = await hmacSha256(getSecret(), payload);
  return { nonce: `${payload}:${sig}`, scope: safeScope };
}

/**
 * Verify a stateless challenge nonce. Returns the scope baked into the
 * nonce when valid, null otherwise. Wallet signature binds scope at sign
 * time; verify route MUST use this scope rather than trusting whatever
 * scope the verify request body claims.
 *
 * "Consuming" is still implicit: nonce TTL is the only replay defense
 * within the 5-minute window. A future revision should add a server-side
 * blacklist (Vercel KV / Redis) keyed by the random component.
 */
export async function consumeChallenge(
  address: string,
  nonce: string,
): Promise<{ random: string; scope: SessionScope } | null> {
  const parts = nonce.split(":");
  if (parts.length !== 5) return null;

  const [random, addr, tsStr, scopeB64, sig] = parts;
  if (addr !== address.toLowerCase()) return null;

  const ts = parseInt(tsStr, 10);
  if (isNaN(ts) || Date.now() - ts > CHALLENGE_TTL_MS) return null;

  const payload = `${random}:${addr}:${tsStr}:${scopeB64}`;
  const expectedSig = await hmacSha256(getSecret(), payload);
  if (!constantTimeEqual(sig, expectedSig)) return null;

  let scope: SessionScope = {};
  try {
    const parsed = JSON.parse(b64urlDecode(scopeB64));
    if (parsed && typeof parsed === "object") {
      if (parsed.role && ["genius", "idiot", "both"].includes(parsed.role)) {
        scope.role = parsed.role;
      }
      if (typeof parsed.maxSpendUsdc === "number" && parsed.maxSpendUsdc > 0) {
        scope.maxSpendUsdc = parsed.maxSpendUsdc;
      }
      if (typeof parsed.expiresInHours === "number" && parsed.expiresInHours > 0) {
        scope.expiresInHours = Math.min(parsed.expiresInHours, 24);
      }
    }
  } catch {
    return null;
  }

  return { random, scope };
}

// ---------------------------------------------------------------------------
// Session tokens
// ---------------------------------------------------------------------------

export interface SessionScope {
  role?: "genius" | "idiot" | "both";
  maxSpendUsdc?: number;
  expiresInHours?: number;
}

interface TokenPayload {
  address: string;
  scope: SessionScope;
  issuedAt: number;
  expiresAt: number;
}

export async function createSessionToken(
  address: string,
  scope: SessionScope = {},
): Promise<{ token: string; expiresAt: number }> {
  const ttlHours = scope.expiresInHours ?? 24;
  const ttlMs = Math.min(ttlHours * 60 * 60 * 1000, TOKEN_TTL_MS);
  const issuedAt = Date.now();
  const expiresAt = issuedAt + ttlMs;

  const payload = JSON.stringify({
    address: address.toLowerCase(),
    scope: { role: scope.role ?? "both", maxSpendUsdc: scope.maxSpendUsdc },
    issuedAt,
    expiresAt,
  });

  const payloadB64 = btoa(payload);
  const sig = await hmacSha256(getSecret(), payloadB64);
  const token = `djn_${payloadB64}.${sig}`;

  return { token, expiresAt };
}

export async function verifySessionToken(token: string): Promise<TokenPayload | null> {
  const secret = getSecret();

  try {
    if (!token.startsWith("djn_")) return null;
    const rest = token.slice(4);
    const dotIdx = rest.lastIndexOf(".");
    if (dotIdx === -1) return null;

    const payloadB64 = rest.slice(0, dotIdx);
    const sig = rest.slice(dotIdx + 1);

    const expectedSig = await hmacSha256(secret, payloadB64);
    if (!constantTimeEqual(sig, expectedSig)) return null;

    const payload: TokenPayload = JSON.parse(atob(payloadB64));
    if (Date.now() > payload.expiresAt) return null;

    return payload;
  } catch {
    return null;
  }
}

// ---------------------------------------------------------------------------
// Request authentication
// ---------------------------------------------------------------------------

export async function authenticateRequest(
  request: NextRequest,
): Promise<{ address: string; scope: SessionScope } | null> {
  const authHeader = request.headers.get("authorization");
  if (!authHeader?.startsWith("Bearer ")) return null;

  const token = authHeader.slice(7);
  const payload = await verifySessionToken(token);
  if (!payload) return null;

  return {
    address: payload.address,
    scope: { role: payload.scope.role, maxSpendUsdc: payload.scope.maxSpendUsdc },
  };
}

// ---------------------------------------------------------------------------
// Signature verification
// ---------------------------------------------------------------------------

const CHALLENGE_MESSAGE_PREFIX = "Sign this message to authenticate with Djinn Protocol.\n\nNonce: ";

export function buildChallengeMessage(nonce: string): string {
  return `${CHALLENGE_MESSAGE_PREFIX}${nonce}`;
}

export function recoverAddress(nonce: string, signature: string): string | null {
  try {
    const message = buildChallengeMessage(nonce);
    return ethers.verifyMessage(message, signature).toLowerCase();
  } catch {
    return null;
  }
}
