/**
 * Typed HTTP clients for the Djinn validator and miner REST APIs.
 */

// ---------------------------------------------------------------------------
// Request / Response types (mirrors Pydantic models)
// ---------------------------------------------------------------------------

export interface BeaverTripleData {
  a: string; // Hex-encoded field element
  b: string;
  c: string; // c = a * b mod p
}

/**
 * Encrypted-bundle fan-out for share recovery (Phase 3, design 2026-05-03).
 * The genius posts the SAME bundle to every OV signer URL; each validator
 * decrypts its own entry and persists the rest as forwarding blobs.
 *
 * Legacy plaintext-share fan-out (StoreShareRequest / storeShare /
 * POST /v1/signal) was removed 2026-05-04; the bundle path is the only
 * way to distribute shares.
 */
export interface ShareBundleEntry {
  target_address: string;
  share_x: number;
  share_ciphertext: string; // hex SealedBox ciphertext
  index_ciphertext: string;
}

export interface StoreShareBundleRequest {
  signal_id: string;
  genius_address: string;
  shamir_threshold: number;
  bundle: ShareBundleEntry[];
  precomputed_triples?: BeaverTripleData[];
}

export interface StoreShareBundleResponse {
  signal_id: string;
  own_share_stored: boolean;
  forwarding_count: number;
}

export interface PurchaseRequest {
  buyer_address: string;
  sportsbook: string;
  available_indices: number[];
  buyer_signature?: string;
  /** MPC batch settlement Phase 1: per-line BPA vector scaled to
   * ODDS_PRECISION (1e6) integer units. Optional; old validators
   * ignore it. New validators record it keyed by (signalId, buyer)
   * for future audit settlement.
   */
  bpas?: number[];
  /** Per-line WPA vector, same encoding as bpas. */
  wpas?: number[];
  /** Whether this purchase was priced in BPA mode (true) or WPA mode
   * (false). Null if the signal's mode is unknown (legacy signals). */
  bpa_mode?: boolean;
}

export interface ShareInfoResponse {
  signal_id: string;
  share_x: number;
  shamir_threshold: number;
}

export interface PurchaseResponse {
  signal_id: string;
  status: string;
  available: boolean | null;
  encrypted_key_share: string | null; // Hex-encoded Shamir share y-value
  share_x: number | null; // Shamir share x-coordinate
  message: string;
}

export interface ValidatorHealthResponse {
  status: string;
  version: string;
  uid: number | null;
  shares_held: number;
  chain_connected: boolean;
  bt_connected: boolean;
  // OV signer registration status. If true, this validator's hotkey is
  // in the OutcomeVoting active signer set and can vote in audit quorum.
  // SDK uses this to filter share-distribution to OV-counted validators
  // only — distributing to non-signers wastes a share on a validator
  // that can never vote at settlement time.
  settlement_registered?: boolean;
}

export interface CandidateLine {
  index: number;
  sport: string;
  event_id: string;
  home_team: string;
  away_team: string;
  market: string;
  line: number | null;
  side: string;
}

export interface RegisterSignalRequest {
  sport: string;
  event_id: string;
  home_team: string;
  away_team: string;
  lines: string[];
  genius_address?: string;
}

export interface CheckRequest {
  lines: CandidateLine[];
}

export interface BookmakerAvailability {
  bookmaker: string;
  odds: number;
}

export interface LineResult {
  index: number;
  available: boolean;
  bookmakers: BookmakerAvailability[];
  unavailable_reason?: string | null;
}

export interface CheckResponse {
  results: LineResult[];
  available_indices: number[];
  response_time_ms: number;
  api_error?: string | null;
}

export interface MinerHealthResponse {
  status: string;
  version: string;
  uid: number | null;
  odds_api_connected: boolean;
  bt_connected: boolean;
  uptime_seconds: number;
}

// ---------------------------------------------------------------------------
// HTTP client helpers
// ---------------------------------------------------------------------------

const DEFAULT_TIMEOUT_MS = 30_000;
const MAX_RETRIES = 2;
const RETRY_BACKOFF_MS = 500;

/** Error subclass for API errors with status code. */
export class ApiError extends Error {
  constructor(
    public readonly status: number,
    public readonly detail: string,
    public readonly url: string,
  ) {
    super(`${status}: ${detail}`);
    this.name = "ApiError";
  }

  /** True if the error is retryable (5xx or network failure). */
  get retryable(): boolean {
    return this.status >= 500;
  }

  /** True if rate-limited. */
  get rateLimited(): boolean {
    return this.status === 429;
  }
}

/** Check if an error is retryable (5xx, network, or timeout). */
function isRetryable(err: unknown): boolean {
  if (err instanceof ApiError) return err.retryable;
  if (err instanceof DOMException && err.name === "AbortError") return false;
  if (err instanceof TypeError) return true; // network errors
  return false;
}

/** Sleep for ms with optional jitter. */
function sleep(ms: number): Promise<void> {
  const jitter = ms * 0.2 * Math.random();
  return new Promise((resolve) => setTimeout(resolve, ms + jitter));
}

async function fetchWithRetry(
  url: string,
  init: RequestInit,
  timeoutMs: number,
  retries = MAX_RETRIES,
): Promise<Response> {
  let lastErr: unknown;
  for (let attempt = 0; attempt <= retries; attempt++) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), timeoutMs);
    try {
      const res = await fetch(url, { ...init, signal: controller.signal });
      if (res.ok || res.status < 500) return res;
      // 5xx — retryable
      lastErr = new ApiError(
        res.status,
        await res.text().catch(() => res.statusText),
        url,
      );
    } catch (err) {
      if (err instanceof DOMException && err.name === "AbortError") {
        lastErr = new Error(`Request to ${url} timed out after ${timeoutMs}ms`);
        // Timeouts are not retried
        throw lastErr;
      }
      lastErr = err;
      if (!isRetryable(err)) throw err;
    } finally {
      clearTimeout(timer);
    }
    if (attempt < retries) {
      await sleep(RETRY_BACKOFF_MS * 2 ** attempt);
    }
  }
  throw lastErr;
}

async function post<T>(url: string, body: unknown, timeoutMs = DEFAULT_TIMEOUT_MS): Promise<T> {
  const res = await fetchWithRetry(
    url,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    },
    timeoutMs,
  );
  if (!res.ok) {
    const detail = await res.text().catch(() => res.statusText);
    throw new ApiError(res.status, detail, url);
  }
  return res.json() as Promise<T>;
}

async function get<T>(url: string, timeoutMs = DEFAULT_TIMEOUT_MS): Promise<T> {
  const res = await fetchWithRetry(url, {}, timeoutMs);
  if (!res.ok) {
    const detail = await res.text().catch(() => res.statusText);
    throw new ApiError(res.status, detail, url);
  }
  return res.json() as Promise<T>;
}

// ---------------------------------------------------------------------------
// ValidatorClient
// ---------------------------------------------------------------------------

const SIGNAL_ID_RE = /^[a-zA-Z0-9_\-]{1,256}$/;

export class ValidatorClient {
  constructor(public readonly baseUrl: string) {}

  async storeShareBundle(req: StoreShareBundleRequest): Promise<StoreShareBundleResponse> {
    return post<StoreShareBundleResponse>(`${this.baseUrl}/v1/signal/bundle`, req);
  }

  async purchaseSignal(
    signalId: string,
    req: PurchaseRequest,
  ): Promise<PurchaseResponse> {
    if (!SIGNAL_ID_RE.test(signalId)) {
      throw new Error("Invalid signal ID format");
    }
    // MPC computation takes 30-45s on the current network. Use 60s timeout
    // (default 30s is too short and causes every purchase to fail).
    return post<PurchaseResponse>(
      `${this.baseUrl}/v1/signal/${encodeURIComponent(signalId)}/purchase`,
      req,
      60_000,
    );
  }

  async checkLines(req: CheckRequest): Promise<CheckResponse> {
    return post<CheckResponse>(`${this.baseUrl}/v1/check`, req);
  }

  async shareInfo(signalId: string): Promise<ShareInfoResponse> {
    if (!SIGNAL_ID_RE.test(signalId)) {
      throw new Error("Invalid signal ID format");
    }
    return get<ShareInfoResponse>(
      `${this.baseUrl}/v1/signal/${encodeURIComponent(signalId)}/share_info`,
    );
  }

  async registerSignal(
    signalId: string,
    req: RegisterSignalRequest,
  ): Promise<{ signal_id: string; registered: boolean; lines_count: number }> {
    if (!SIGNAL_ID_RE.test(signalId)) {
      throw new Error("Invalid signal ID format");
    }
    return post(`${this.baseUrl}/v1/signal/${encodeURIComponent(signalId)}/register`, req);
  }

  async health(): Promise<ValidatorHealthResponse> {
    return get<ValidatorHealthResponse>(`${this.baseUrl}/health`);
  }
}

// ---------------------------------------------------------------------------
// MinerClient
// ---------------------------------------------------------------------------

export class MinerClient {
  constructor(private baseUrl: string) {}

  async checkLines(req: CheckRequest): Promise<CheckResponse> {
    return post<CheckResponse>(`${this.baseUrl}/v1/check`, req);
  }

  async health(): Promise<MinerHealthResponse> {
    return get<MinerHealthResponse>(`${this.baseUrl}/health`);
  }
}

// ---------------------------------------------------------------------------
// Singleton instances (configured from env vars)
// ---------------------------------------------------------------------------

function getEnvOrDefault(envVar: string, devDefault: string): string {
  const val = process.env[envVar];
  if (val) return val;
  return devDefault;
}

/**
 * Bootstrap validator hostnames. The browser fans out through these to fetch
 * the metagraph; the first one that responds wins. All validators on Bittensor
 * Subnet 103 are reachable at https://v<uid>.djinn.gg via the wildcard router
 * which proxies to the current metagraph IP for that UID. There is NO Next.js
 * API in the browser path — the static IPFS build has no server to forward
 * through.
 */
const BROWSER_BOOTSTRAP_HOSTS = [
  "https://v0.djinn.gg",
  "https://v1.djinn.gg",
  "https://v2.djinn.gg",
  "https://v189.djinn.gg",
  "https://v213.djinn.gg",
];

// Per-host passive health tracking for a socket-descriptor circuit breaker.
// When a validator misbehaves (20s timeouts, 5xx bursts), Promise.any still
// resolves fast via the winner — but every loser probe holds a Vercel edge
// socket open for the full timeout window. On v1.5 we observed v189 eating
// 7-of-12 probes with hard 20s timeouts across 10+ consecutive iterations
// (UX_FINDINGS L52/L137/L199, OTF upstream RPC flap). This breaker records
// recent outcomes per host and transiently ejects chronic misbehavers from
// the fan-out. An ejected host is re-probed after EJECT_COOLDOWN_MS and
// can re-join on a single success.
type HostHealth = {
  recent: boolean[]; // rolling window, most recent last; true=success, false=fail
  ejectedUntil: number; // epoch ms; 0 = not ejected
};
const HOST_HEALTH = new Map<string, HostHealth>();
const HOST_HEALTH_WINDOW = 10;
const HOST_EJECT_FAILURE_RATIO = 0.6; // >=60% failures within window
const HOST_EJECT_MIN_SAMPLES = 5; // don't eject on <5 samples
const HOST_EJECT_COOLDOWN_MS = 60_000;
const HOST_EJECT_KEEP_MIN = 2; // never eject below this many hosts

function recordHostOutcome(host: string, success: boolean): void {
  const h = HOST_HEALTH.get(host) ?? { recent: [], ejectedUntil: 0 };
  h.recent.push(success);
  if (h.recent.length > HOST_HEALTH_WINDOW) h.recent.shift();
  if (success) h.ejectedUntil = 0;
  HOST_HEALTH.set(host, h);
  if (!success && h.recent.length >= HOST_EJECT_MIN_SAMPLES) {
    const fails = h.recent.filter((v) => !v).length;
    if (fails / h.recent.length >= HOST_EJECT_FAILURE_RATIO) {
      h.ejectedUntil = Date.now() + HOST_EJECT_COOLDOWN_MS;
    }
  }
}

function getActiveHosts(): string[] {
  const now = Date.now();
  const active = BROWSER_BOOTSTRAP_HOSTS.filter((host) => {
    const h = HOST_HEALTH.get(host);
    return !h || h.ejectedUntil === 0 || h.ejectedUntil <= now;
  });
  if (active.length >= HOST_EJECT_KEEP_MIN) return active;
  // Pool too thin — force-include the hosts closest to recovery so we still
  // fan out to ≥2 endpoints instead of serializing on one.
  return [...BROWSER_BOOTSTRAP_HOSTS]
    .sort((a, b) => (HOST_HEALTH.get(a)?.ejectedUntil ?? 0) - (HOST_HEALTH.get(b)?.ejectedUntil ?? 0))
    .slice(0, Math.max(HOST_EJECT_KEEP_MIN, active.length));
}

function validatorBaseUrl(uid: number): string {
  return `https://v${uid}.djinn.gg`;
}

/**
 * Browser-side base URL for forward-first v1 endpoints that were previously
 * served by Next.js API routes (odds, delegates, report-error, etc.). Static
 * IPFS builds have no server, so we call the validator's /v1/* directly.
 *
 * SSR/Node callers should use the validator/miner URLs from env vars
 * (getValidatorUrls / getMinerUrl) instead.
 */
export function browserV1BaseUrl(): string {
  return BROWSER_BOOTSTRAP_HOSTS[0];
}

/**
 * Race all bootstrap hosts in parallel for a GET and return the first usable
 * response (ok || status<500). The worst-case latency is the *fastest* host,
 * not the sum of timeouts — so one slow/wedged validator in the rotation no
 * longer serially penalizes every request. Static-export safe.
 *
 * Errors from individual hosts are absorbed; we only throw when *every* host
 * rejects. An optional `init.signal` short-circuits the whole race from the
 * caller side.
 */
export async function fetchFromAnyValidator(
  path: string,
  init: RequestInit = {},
  timeoutMs = 8_000,
): Promise<Response> {
  if (typeof window === "undefined") {
    return fetch(`${getValidatorUrls()[0].trim()}${path}`, init);
  }
  // Per-probe AbortControllers so we can cancel losers without killing the
  // winner's response body stream. A single shared controller (previous
  // implementation) aborted the winner's body mid-stream because `Response`
  // bodies are bound to the fetch signal — downstream `await res.json()`
  // then threw DOMException "The user aborted a request." which bubbled
  // into the UI on /network and /idiot/browse.
  const callerSignal = init.signal;
  const hosts = getActiveHosts();
  const perProbe: AbortController[] = hosts.map(() => new AbortController());
  const abortAllExcept = (winnerIdx: number | null, reason: unknown) => {
    perProbe.forEach((c, i) => {
      if (i !== winnerIdx && !c.signal.aborted) c.abort(reason);
    });
  };
  if (callerSignal) {
    if (callerSignal.aborted) abortAllExcept(null, callerSignal.reason);
    else callerSignal.addEventListener(
      "abort",
      () => abortAllExcept(null, callerSignal.reason),
      { once: true },
    );
  }
  const timeoutId = setTimeout(
    () => abortAllExcept(null, new Error(`fetchFromAnyValidator timeout ${timeoutMs}ms`)),
    timeoutMs,
  );

  const probes = hosts.map((host, i) =>
    fetch(`${host}${path}`, { ...init, signal: perProbe[i].signal }).then((res) => {
      if (!res.ok && res.status >= 500) {
        throw new Error(`${host}${path} → ${res.status}`);
      }
      recordHostOutcome(host, true);
      return { res, idx: i, host };
    }).catch((err) => {
      recordHostOutcome(host, false);
      throw err;
    }),
  );

  try {
    const { res, idx } = await Promise.any(probes);
    abortAllExcept(idx, new Error("race_won"));
    return res;
  } catch (err) {
    if (err instanceof AggregateError) {
      throw new Error(`All validators unreachable for ${path}: ${err.errors.map((e) => String(e)).join("; ")}`);
    }
    throw err;
  } finally {
    clearTimeout(timeoutId);
  }
}

function getValidatorUrls(): string[] {
  if (typeof window !== "undefined") return [...BROWSER_BOOTSTRAP_HOSTS];
  return getEnvOrDefault(
    "VALIDATOR_URL",
    getEnvOrDefault("NEXT_PUBLIC_VALIDATOR_URL", "http://localhost:8421"),
  ).split(",").filter((u) => u.trim().length > 0);
}

function getMinerUrl(): string {
  if (typeof window !== "undefined") {
    // Miner endpoints in the browser are served by validators (forward-first).
    return BROWSER_BOOTSTRAP_HOSTS[0];
  }
  return getEnvOrDefault(
    "MINER_URL",
    getEnvOrDefault("NEXT_PUBLIC_MINER_URL", "http://localhost:8422"),
  );
}

/**
 * Discover all validators from the metagraph and return per-validator clients.
 * Each client points directly at https://v<uid>.djinn.gg — no Vercel proxy,
 * no Next.js API. CORS is allowed for djinn.gg + IPFS gateway origins by the
 * wildcard router's nginx config.
 */
let _discoveryCache: { clients: ValidatorClient[]; ts: number } | null = null;
const DISCOVERY_CACHE_MS = 30_000;

async function _bootstrapDiscovery(timeoutMs = 5_000): Promise<
  { uid: number; ip?: string; port?: number }[]
> {
  for (const host of BROWSER_BOOTSTRAP_HOSTS) {
    try {
      const res = await fetch(`${host}/v1/network/validators`, {
        headers: { accept: "application/json" },
        signal: AbortSignal.timeout(timeoutMs),
      });
      if (!res.ok) continue;
      const { validators } = (await res.json()) as {
        validators: { uid: number; ip?: string; port?: number }[];
      };
      if (Array.isArray(validators) && validators.length > 0) return validators;
    } catch {
      // Try next bootstrap.
    }
  }
  return [];
}

export async function discoverValidatorClients(): Promise<ValidatorClient[]> {
  if (typeof window === "undefined") {
    return getValidatorUrls().map((url) => new ValidatorClient(url.trim()));
  }

  if (_discoveryCache && Date.now() - _discoveryCache.ts < DISCOVERY_CACHE_MS) {
    return _discoveryCache.clients;
  }

  const validators = await _bootstrapDiscovery();
  if (validators.length === 0) {
    return BROWSER_BOOTSTRAP_HOSTS.map((u) => new ValidatorClient(u));
  }
  const clients = validators.map((v) => new ValidatorClient(validatorBaseUrl(v.uid)));
  _discoveryCache = { clients, ts: Date.now() };
  return clients;
}

function getValidatorClient(): ValidatorClient {
  return new ValidatorClient(getValidatorUrls()[0].trim());
}

/**
 * Resilient line check that queries validators in parallel.
 *
 * Each validator fans out to up to 15 miners in parallel and merges
 * results (union of available_indices). The client queries multiple
 * validators for redundancy and merges across validators too.
 *
/**
 * Check line availability exclusively through the decentralized miner network.
 * Used for purchase verification where the result must come from the subnet,
 * not the platform's own Odds API.
 */
export async function checkLinesViaSubnet(
  req: CheckRequest,
): Promise<CheckResponse> {
  const result = await _checkViaMinerNetwork(req);
  if (result) return result;

  return {
    results: req.lines.map((l) => ({
      index: l.index,
      available: false,
      bookmakers: [],
    })),
    available_indices: [],
    response_time_ms: 0,
    api_error: "No miners could verify line availability. The miner network may be temporarily down.",
  };
}

/** Internal: query validators/miners for line check data.
 *
 * Returns as soon as ANY validator provides available lines. If no validator
 * finds any available line but some validator successfully responded with a
 * structured "unavailable" answer (e.g. `unavailable_reason: "no_data"`), we
 * return that — callers can surface the specific reason to the user. null
 * is reserved for "every validator errored out" (HTTP failure, api_error, or
 * thrown exception), which means the miner network truly can't be reached.
 */
async function _checkViaMinerNetwork(req: CheckRequest): Promise<CheckResponse | null> {
  let validators: ValidatorClient[];
  try {
    validators = await discoverValidatorClients();
  } catch {
    validators = [getValidatorClient()];
  }

  // First pass: race, return as soon as any validator reports available lines.
  let firstUnavailable: CheckResponse | null = null;
  const firstAvailable = await Promise.any(
    validators.map((v) =>
      v.checkLines(req).then((r) => {
        if (r.api_error) {
          throw new Error(`validator api_error: ${r.api_error}`);
        }
        if (r.available_indices.length === 0) {
          if (!firstUnavailable) firstUnavailable = r;
          throw new Error("no available lines from this validator");
        }
        console.log("[checkLines] Miner network responded:", r.available_indices.length, "lines available");
        return r;
      }),
    ),
  ).catch(() => null);

  if (firstAvailable) return firstAvailable;
  return firstUnavailable;
}
