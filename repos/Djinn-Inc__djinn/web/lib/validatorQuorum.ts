/**
 * Multi-validator quorum helper.
 *
 * For high-stakes calls (purchase verification, check-odds, settlement
 * attestation lookups), the client should require Q-of-N validators to
 * agree on the response shape before treating the call as authoritative.
 * Racing the first responder is fine for low-stakes UI display, but for
 * anything that affects payment or settlement it lets a single
 * misbehaving validator dictate the outcome.
 *
 * This module provides a small generic helper that handles the parallel
 * fan-out, quorum bucketing, and verdict computation. Call sites pass in
 * the per-validator promises and a `bucketBy` function that produces a
 * stable key for each successful response. The helper waits until either
 * `quorum` distinct validators land in the same bucket (success), or all
 * validators have settled and no bucket reached quorum (failure).
 *
 * The helper is gated upstream by the `quorumStrict` feature flag. With
 * the flag OFF, call sites continue to race the first responder via
 * Promise.any (no behavior change). With the flag ON, high-stakes calls
 * route through this helper.
 */

export type QuorumVerdict = "quorum_reached" | "no_quorum" | "all_failed";

export interface QuorumOptions<T> {
  /** How many distinct validators must produce responses in the same
   * bucket for the call to be considered authoritative. Must be >= 2. */
  quorum: number;
  /** A stable key derived from a successful response. Two validators
   * "agree" iff their bucketBy results are equal. Use a string like
   * "AVAILABLE" or a hash of the meaningful subset of the response. */
  bucketBy: (result: T) => string;
  /** Resolve as soon as quorum is reached, even if some validators are
   * still pending. Default: true. Set to false to always wait for all
   * responses (useful for diagnostics). */
  fastResolve?: boolean;
}

export interface QuorumResult<T> {
  verdict: QuorumVerdict;
  /** The first response from the agreed-upon bucket, or null if no
   * quorum was reached. */
  result: T | null;
  /** All responses that landed in the agreed-upon bucket. */
  agreement: T[];
  /** All successful responses, regardless of bucket. */
  allSuccess: T[];
  /** Number of validators that errored or rejected. */
  errorCount: number;
  /** Total number of validators queried. */
  total: number;
  /** Bucket key that reached quorum, or null. */
  agreedBucket: string | null;
}

/**
 * Run a parallel quorum call across N validators.
 *
 * The function awaits up to `quorum` agreements (when fastResolve is true)
 * or all responses (when false). It always returns a defined QuorumResult
 * even on total failure; it never throws.
 */
export async function quorumCall<T>(
  promises: Promise<T>[],
  options: QuorumOptions<T>,
): Promise<QuorumResult<T>> {
  const { quorum, bucketBy, fastResolve = true } = options;
  if (quorum < 2) {
    throw new Error(`quorum must be >= 2, got ${quorum}`);
  }
  const total = promises.length;
  if (total === 0) {
    return {
      verdict: "all_failed",
      result: null,
      agreement: [],
      allSuccess: [],
      errorCount: 0,
      total: 0,
      agreedBucket: null,
    };
  }

  const allSuccess: T[] = [];
  const buckets = new Map<string, T[]>();
  let errorCount = 0;
  let pending = total;
  let agreedBucket: string | null = null;

  return new Promise<QuorumResult<T>>((resolve) => {
    let settled = false;
    const finalize = () => {
      if (settled) return;
      settled = true;
      const verdict: QuorumVerdict = agreedBucket
        ? "quorum_reached"
        : allSuccess.length === 0
          ? "all_failed"
          : "no_quorum";
      const agreement = agreedBucket ? (buckets.get(agreedBucket) ?? []) : [];
      resolve({
        verdict,
        result: agreement[0] ?? null,
        agreement,
        allSuccess,
        errorCount,
        total,
        agreedBucket,
      });
    };

    promises.forEach((p) => {
      p.then(
        (value) => {
          if (settled) return;
          allSuccess.push(value);
          let key: string;
          try {
            key = bucketBy(value);
          } catch {
            errorCount++;
            pending--;
            if (pending === 0) finalize();
            return;
          }
          const bucket = buckets.get(key) ?? [];
          bucket.push(value);
          buckets.set(key, bucket);
          if (!agreedBucket && bucket.length >= quorum) {
            agreedBucket = key;
            if (fastResolve) {
              finalize();
              return;
            }
          }
          pending--;
          if (pending === 0) finalize();
        },
        () => {
          if (settled) return;
          errorCount++;
          pending--;
          if (pending === 0) finalize();
        },
      );
    });
  });
}

/**
 * Convenience wrapper for the common case where you want to fall back
 * to the first response when the quorum flag is OFF, and use strict
 * quorum when the flag is ON. The flag check is the caller's
 * responsibility — pass `strict: true` when isFlagEnabled("quorumStrict")
 * returns true.
 */
export async function callWithQuorumOrFirst<T>(
  promises: Promise<T>[],
  options: QuorumOptions<T> & { strict: boolean },
): Promise<QuorumResult<T>> {
  if (!options.strict) {
    // First-responder mode: take the first successful response, treat
    // the rest as confirmation if they happen to come in.
    const total = promises.length;
    const allSuccess: T[] = [];
    let errorCount = 0;
    return new Promise<QuorumResult<T>>((resolve) => {
      let settled = false;
      let pending = total;
      const finalize = (first: T | null) => {
        if (settled) return;
        settled = true;
        resolve({
          verdict: first
            ? "quorum_reached"
            : allSuccess.length === 0
              ? "all_failed"
              : "no_quorum",
          result: first,
          agreement: first ? [first] : [],
          allSuccess,
          errorCount,
          total,
          agreedBucket: first ? options.bucketBy(first) : null,
        });
      };
      if (total === 0) {
        finalize(null);
        return;
      }
      promises.forEach((p) => {
        p.then(
          (value) => {
            allSuccess.push(value);
            if (!settled) finalize(value);
            pending--;
          },
          () => {
            errorCount++;
            pending--;
            if (pending === 0 && !settled) finalize(null);
          },
        );
      });
    });
  }
  return quorumCall(promises, options);
}
