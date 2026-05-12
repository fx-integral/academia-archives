/**
 * Shared multi-key rotation + negative-cache state for The Odds API.
 *
 * Both `/api/odds` (main) and `/api/odds/alt` (alternate markets) proxy
 * through the same set of API keys. Prior to this module, each route
 * kept a separate rotation pointer, so a 429 observed by the main route
 * would not inform the alt route's choice of starting key on the next
 * request — doubling our chance of tripping the upstream rate limit
 * during signal-creation flows that fire both endpoints back-to-back.
 *
 * This module centralizes:
 *  - the ordered list of keys (env -> `ODDS_API_KEYS` preferred; legacy
 *    `ODDS_API_KEY` single-key fallback)
 *  - the rotation pointer shared across routes
 *  - a short "all keys exhausted" negative cache keyed by endpoint path,
 *    to prevent rate-limit amplification under upstream outage
 *    (caller at 120 req/min × N keys -> 600 upstream calls/min without it)
 *
 * See MAINNET_BLOCKERS.md P1-03 for context.
 */

export interface OddsKeyFailure {
  status: number;
}

export function getOddsApiKeys(): string[] {
  const multi = process.env.ODDS_API_KEYS;
  if (multi) {
    const keys = multi.split(",").map((s) => s.trim()).filter(Boolean);
    if (keys.length > 0) return keys;
  }
  const single = process.env.ODDS_API_KEY;
  return single ? [single] : [];
}

export function isOddsKeyFailure(status: number): boolean {
  return status === 401 || status === 403 || status === 429 || status >= 500;
}

// Shared rotation pointer. Mutated on every upstream call; see
// `advanceRotation` / `holdRotation`. Torn reads across concurrent
// handlers are benign in Node (single-threaded isolate) — the cost is
// only slightly-suboptimal rotation, never lost data.
let _rotationStart = 0;

export function rotationStart(n: number): number {
  if (n <= 0) return 0;
  return _rotationStart % n;
}

// Call on success: leave the pointer on the working key so the next
// request prefers it.
export function holdRotation(keyIdx: number) {
  _rotationStart = keyIdx;
}

// Call on 401/403/429/5xx: advance past the failing key so the next
// request doesn't hit it first.
export function advanceRotation(keyIdx: number) {
  _rotationStart = keyIdx + 1;
}

// --- Negative cache ---
//
// When every key fails with a retriable status (429, 503, etc.), we cache
// the failure briefly so subsequent callers don't re-fan-out an exhaustive
// N-key probe for each inbound request. TTL is deliberately short; upstream
// rate limits are sliding-window and may recover within seconds.

const NEG_TTL_MS = 30_000;
const _negCache = new Map<string, number>();

export function negCacheKey(scope: string, sport: string, extra = ""): string {
  return `${scope}\u0001${sport}\u0001${extra}`;
}

export function getNegCache(key: string): boolean {
  const until = _negCache.get(key);
  if (!until) return false;
  if (until <= Date.now()) {
    _negCache.delete(key);
    return false;
  }
  return true;
}

export function setNegCache(key: string) {
  _negCache.set(key, Date.now() + NEG_TTL_MS);
  // Cap to avoid unbounded growth under adversarial sport-string input.
  if (_negCache.size > 128) {
    const keys = Array.from(_negCache.keys());
    // Drop the oldest half.
    for (const k of keys.slice(0, 64)) _negCache.delete(k);
  }
}

// Test-only reset hook — not exported for general use, only for vitest.
export function _resetOddsKeyStateForTests() {
  _rotationStart = 0;
  _negCache.clear();
}
