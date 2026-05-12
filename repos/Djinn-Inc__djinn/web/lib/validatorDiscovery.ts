/**
 * Validator network discovery via gossip from a bootstrap entry.
 *
 * Static IPFS clients can't bundle a Bittensor RPC client to read the
 * metagraph directly. Instead they ask one validator (the bootstrap)
 * for the validator list, then health-check each entry to build a
 * runtime registry of reachable validators with their advertised
 * hostnames.
 *
 * Flow:
 *   1. Call <bootstrap>/v1/network/validators to get the metagraph
 *      view (uid, ip, port, hotkey for every validator).
 *   2. For each entry, compute the wildcard router URL from the UID.
 *   3. Concurrently call <wildcardURL>/health on each entry.
 *   4. Build a runtime registry of validators that responded healthy,
 *      preferring the operator-advertised public_hostname when present.
 *
 * The runtime registry is what subsequent calls use. A validator is
 * "discovered" only after its /health responds successfully — the
 * client never blindly trusts the bootstrap's view.
 */

import { resolveValidatorBaseUrl, patternBaseUrl } from "./validatorHostnames";

export interface DiscoveredValidator {
  uid: number;
  baseUrl: string; // https URL the client should use for direct calls
  hotkey: string;
  ip: string;
  port: number;
  publicHostname: string;
  sharesHeld: number;
  version: string;
  chainConnected: boolean;
  btConnected: boolean;
  attestCapable: boolean;
  /** RTT to /health in milliseconds. Used for picking the fastest
   * validator for low-stakes calls. */
  healthLatencyMs: number;
}

export interface DiscoveryResult {
  validators: DiscoveredValidator[];
  bootstrapUrl: string;
  servedAtMs: number;
  errorCount: number;
}

interface NetworkValidatorsResponse {
  validators: Array<{
    uid: number;
    ip: string;
    port: number;
    hotkey: string;
  }>;
  served_by_uid: number | null;
  validator_count: number;
  served_at_ms: number;
}

interface HealthResponse {
  status: string;
  version: string;
  uid: number | null;
  shares_held: number;
  chain_connected: boolean;
  bt_connected: boolean;
  attest_capable: boolean;
  public_hostname?: string;
}

const DEFAULT_TIMEOUT_MS = 8_000;

/** Default bootstrap. Static clients can override via the
 * `discoverValidators` parameter. */
export const DEFAULT_BOOTSTRAP = "https://v0.djinn.gg";

export async function discoverValidators(
  options: {
    bootstrap?: string;
    timeoutMs?: number;
  } = {},
): Promise<DiscoveryResult> {
  const bootstrap = options.bootstrap ?? DEFAULT_BOOTSTRAP;
  const timeoutMs = options.timeoutMs ?? DEFAULT_TIMEOUT_MS;
  const servedAtMs = Date.now();

  let listing: NetworkValidatorsResponse;
  try {
    const resp = await fetch(`${bootstrap}/v1/network/validators`, {
      signal: AbortSignal.timeout(timeoutMs),
    });
    if (!resp.ok) {
      return {
        validators: [],
        bootstrapUrl: bootstrap,
        servedAtMs,
        errorCount: 1,
      };
    }
    listing = (await resp.json()) as NetworkValidatorsResponse;
  } catch {
    return {
      validators: [],
      bootstrapUrl: bootstrap,
      servedAtMs,
      errorCount: 1,
    };
  }

  const candidates = listing.validators.filter(
    (v) => v.ip && v.ip !== "0.0.0.0" && v.port > 0,
  );

  const probes = await Promise.all(
    candidates.map((c) => probeValidator(c, timeoutMs)),
  );

  const validators = probes.filter(
    (p): p is DiscoveredValidator => p !== null,
  );
  const errorCount = candidates.length - validators.length;

  return {
    validators: validators.sort((a, b) => a.uid - b.uid),
    bootstrapUrl: bootstrap,
    servedAtMs,
    errorCount,
  };
}

async function probeValidator(
  candidate: { uid: number; ip: string; port: number; hotkey: string },
  timeoutMs: number,
): Promise<DiscoveredValidator | null> {
  const patternUrl = patternBaseUrl(candidate.uid);
  const start = Date.now();

  let health: HealthResponse | null = null;
  try {
    const resp = await fetch(`${patternUrl}/health`, {
      signal: AbortSignal.timeout(timeoutMs),
    });
    if (!resp.ok) return null;
    health = (await resp.json()) as HealthResponse;
  } catch {
    return null;
  }

  if (!health || health.status !== "ok") return null;

  const advertised = health.public_hostname?.trim() || undefined;
  const baseUrl = resolveValidatorBaseUrl(candidate.uid, advertised);

  return {
    uid: candidate.uid,
    baseUrl,
    hotkey: candidate.hotkey,
    ip: candidate.ip,
    port: candidate.port,
    publicHostname: advertised ?? "",
    sharesHeld: health.shares_held ?? 0,
    version: health.version ?? "",
    chainConnected: health.chain_connected ?? false,
    btConnected: health.bt_connected ?? false,
    attestCapable: health.attest_capable ?? false,
    healthLatencyMs: Date.now() - start,
  };
}

/** Pick the fastest healthy validator from a discovery result. Useful
 * for the buyer-facing low-stakes calls (browse, sport list). */
export function fastestValidator(
  result: DiscoveryResult,
): DiscoveredValidator | undefined {
  return result.validators
    .slice()
    .sort((a, b) => a.healthLatencyMs - b.healthLatencyMs)[0];
}

/** Pick the N fastest healthy validators for fan-out / quorum calls. */
export function fastestNValidators(
  result: DiscoveryResult,
  n: number,
): DiscoveredValidator[] {
  return result.validators
    .slice()
    .sort((a, b) => a.healthLatencyMs - b.healthLatencyMs)
    .slice(0, n);
}
