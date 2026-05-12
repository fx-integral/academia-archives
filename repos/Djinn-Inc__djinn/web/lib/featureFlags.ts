/**
 * Runtime feature flags for staged protocol rollouts.
 *
 * Each flag is a single boolean that controls whether a piece of new behavior
 * is enabled in this client build. Flags default to OFF on the `main` branch
 * and can be flipped ON via:
 *
 *   1. Build-time env var: NEXT_PUBLIC_DJINN_FF_<NAME>=true
 *   2. Runtime override: localStorage.setItem("djinn_ff_<name>", "true")
 *
 * The runtime override only affects the current browser. It is intended for
 * preview deploys, QA, and developer testing. Production traffic uses the
 * build-time value.
 *
 * Every active flag must be listed in docs/feature-flags.md with a removal
 * plan. Dead flags accumulate.
 */

export type FeatureFlagName =
  | "circuitBreaker"
  | "canonicalOdds"
  | "appealMechanism"
  | "purchaseV2"
  | "newMinerZeroWeight"
  // Per-call quorum flags. quorumStrict is the umbrella ON-flips-everything
  // toggle; the granular flags let operators flip strict mode on for the
  // high-stakes calls (purchase, check-odds) without paying the ~400ms
  // latency cost on low-stakes UI reads (browse, network status).
  | "quorumStrict"
  | "quorumStrictCheckOdds"
  | "quorumStrictPurchase";

const ENV_KEYS: Record<FeatureFlagName, string> = {
  circuitBreaker: "NEXT_PUBLIC_DJINN_FF_CIRCUIT_BREAKER",
  canonicalOdds: "NEXT_PUBLIC_DJINN_FF_CANONICAL_ODDS",
  appealMechanism: "NEXT_PUBLIC_DJINN_FF_APPEAL_MECHANISM",
  purchaseV2: "NEXT_PUBLIC_DJINN_FF_PURCHASE_V2",
  newMinerZeroWeight: "NEXT_PUBLIC_DJINN_FF_NEW_MINER_ZERO_WEIGHT",
  quorumStrict: "NEXT_PUBLIC_DJINN_FF_QUORUM_STRICT",
  quorumStrictCheckOdds: "NEXT_PUBLIC_DJINN_FF_QUORUM_STRICT_CHECK_ODDS",
  quorumStrictPurchase: "NEXT_PUBLIC_DJINN_FF_QUORUM_STRICT_PURCHASE",
};

const STORAGE_KEYS: Record<FeatureFlagName, string> = {
  circuitBreaker: "djinn_ff_circuit_breaker",
  canonicalOdds: "djinn_ff_canonical_odds",
  appealMechanism: "djinn_ff_appeal_mechanism",
  purchaseV2: "djinn_ff_purchase_v2",
  newMinerZeroWeight: "djinn_ff_new_miner_zero_weight",
  quorumStrict: "djinn_ff_quorum_strict",
  quorumStrictCheckOdds: "djinn_ff_quorum_strict_check_odds",
  quorumStrictPurchase: "djinn_ff_quorum_strict_purchase",
};

const TRUTHY = new Set(["1", "true", "yes", "on"]);

function parseBoolean(value: string | null | undefined): boolean {
  if (value == null) return false;
  return TRUTHY.has(value.trim().toLowerCase());
}

function readEnv(name: FeatureFlagName): boolean {
  const key = ENV_KEYS[name];
  const value = process.env[key];
  return parseBoolean(value);
}

function readOverride(name: FeatureFlagName): boolean | null {
  if (typeof window === "undefined") return null;
  try {
    const value = window.localStorage.getItem(STORAGE_KEYS[name]);
    if (value == null) return null;
    return parseBoolean(value);
  } catch {
    return null;
  }
}

export function isFlagEnabled(name: FeatureFlagName): boolean {
  const override = readOverride(name);
  if (override !== null) return override;
  return readEnv(name);
}

export function setFlagOverride(name: FeatureFlagName, enabled: boolean | null): void {
  if (typeof window === "undefined") return;
  try {
    if (enabled === null) {
      window.localStorage.removeItem(STORAGE_KEYS[name]);
    } else {
      window.localStorage.setItem(STORAGE_KEYS[name], enabled ? "true" : "false");
    }
  } catch {
    // localStorage unavailable, ignore.
  }
}

export function getAllFlags(): Record<FeatureFlagName, boolean> {
  return {
    circuitBreaker: isFlagEnabled("circuitBreaker"),
    canonicalOdds: isFlagEnabled("canonicalOdds"),
    appealMechanism: isFlagEnabled("appealMechanism"),
    purchaseV2: isFlagEnabled("purchaseV2"),
    newMinerZeroWeight: isFlagEnabled("newMinerZeroWeight"),
    quorumStrict: isFlagEnabled("quorumStrict"),
    quorumStrictCheckOdds: isFlagEnabled("quorumStrictCheckOdds"),
    quorumStrictPurchase: isFlagEnabled("quorumStrictPurchase"),
  };
}

/** Resolve whether quorum-strict mode applies to a specific call type.
 * The umbrella `quorumStrict` flag enables it for everything; the
 * per-call flags allow opting into strict mode for one call type
 * without slowing down the others. */
export function isQuorumStrictFor(
  callType: "checkOdds" | "purchase",
): boolean {
  if (isFlagEnabled("quorumStrict")) return true;
  if (callType === "checkOdds" && isFlagEnabled("quorumStrictCheckOdds")) return true;
  if (callType === "purchase" && isFlagEnabled("quorumStrictPurchase")) return true;
  return false;
}

export function getEnabledFlags(): FeatureFlagName[] {
  const all = getAllFlags();
  return (Object.keys(all) as FeatureFlagName[]).filter((k) => all[k]);
}
