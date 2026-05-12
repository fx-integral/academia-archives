/**
 * Validator hostname resolution.
 *
 * The web client needs an HTTPS hostname for every validator UID it
 * discovers from the metagraph. Two layers:
 *
 * 1. **Wildcard router (default)**: every validator at UID N is
 *    reachable at `https://v${N}.djinn.gg`. The wildcard router
 *    (docs/runbook-wildcard-router.md) terminates TLS and proxies
 *    to whichever IP that UID currently reports to the metagraph.
 *    New validators auto-appear, deregistered ones auto-disappear,
 *    zero operator coordination. Validators stay on plain HTTP
 *    port 8421 with no nginx, no certs, no DNS work.
 *
 * 2. **Operator override**: any validator can advertise its own
 *    hostname via the `public_hostname` field in `/health`. If
 *    present, the client uses that instead of the pattern. Useful
 *    for operators who want to bypass our router with their own
 *    domain (e.g. `validator.tao.com`).
 *
 * Trust model: the pattern trusts the wildcard router operator
 * (Djinn-Inc) to faithfully proxy v<uid>.djinn.gg → the metagraph IP.
 * Mitigations: validator response signing (TBD), client quorum
 * across multiple validators (already in place via validatorQuorum.ts),
 * and the ability for anyone to run their own router and have the
 * client point at it.
 */

export interface ValidatorHostname {
  uid: number;
  hostname: string; // FQDN, no scheme
  /** Whether the validator owner controls the DNS (vs. djinn.gg
   * sub-issued). Useful for trust signaling in the UI. */
  operatorControlled: boolean;
  /** Free-form notes about the operator (Twitter handle, website, etc.) */
  operator?: string;
}

export const VALIDATOR_HOSTNAMES: ValidatorHostname[] = [
  // The wildcard router handles every UID via the pattern function
  // below, so this list is intentionally empty in the default config.
  // Add an entry only when a specific operator wants to override
  // the wildcard pattern with their own controlled domain. Most
  // operators won't need to.
];

const _byUid = new Map(
  VALIDATOR_HOSTNAMES.map((entry) => [entry.uid, entry] as const),
);

export function getValidatorHostname(uid: number): ValidatorHostname | undefined {
  return _byUid.get(uid);
}

export function getValidatorBaseUrl(uid: number): string | undefined {
  const entry = _byUid.get(uid);
  return entry ? `https://${entry.hostname}` : undefined;
}

export function hasDirectHttps(uid: number): boolean {
  return _byUid.has(uid);
}

/** Compute the pattern-based hostname for any UID. Used as the default
 * when no override exists in the registry and no operator
 * self-advertisement has been received yet. Operators get this for
 * free as long as they configure nginx + Let's Encrypt for the
 * matching subdomain (Djinn provisions the DNS). */
export function patternHostname(uid: number): string {
  return `v${uid}.djinn.gg`;
}

/** Compute the pattern-based base URL for any UID. */
export function patternBaseUrl(uid: number): string {
  return `https://${patternHostname(uid)}`;
}

/** Resolve a UID to its best-known HTTPS base URL. Resolution order:
 *  1. Hardcoded override in this file (highest priority)
 *  2. Operator override from /health.public_hostname (must be passed in)
 *  3. Pattern-based default v<uid>.djinn.gg
 */
export function resolveValidatorBaseUrl(
  uid: number,
  advertisedHostname?: string,
): string {
  const hardcoded = getValidatorBaseUrl(uid);
  if (hardcoded) return hardcoded;
  if (advertisedHostname) return `https://${advertisedHostname}`;
  return patternBaseUrl(uid);
}
