/**
 * Block-timestamp helpers shared by Purchase History, Settlement History, and
 * any other event log table that has only a `blockNumber` field on the event.
 *
 * The on-chain timestamp is fetched via `eth_getBlockByNumber`. Until the RPC
 * call resolves, `formatBlockDate` falls back to the block label so the column
 * is never blank.
 */

const ONE_MINUTE = 60_000;
const ONE_HOUR = 60 * ONE_MINUTE;
const ONE_DAY = 24 * ONE_HOUR;

export function formatBlockDate(
  timestampSec: number | undefined | null,
  blockNumber: number,
  now: number = Date.now(),
): string {
  if (timestampSec && timestampSec > 0) {
    return new Date(timestampSec * 1000).toLocaleString();
  }
  return `Block ${blockNumber}`;
}

export function formatRelative(
  timestampSec: number | undefined | null,
  now: number = Date.now(),
): string | null {
  if (!timestampSec || timestampSec <= 0) return null;
  const deltaMs = now - timestampSec * 1000;
  if (deltaMs < ONE_MINUTE) return "just now";
  if (deltaMs < ONE_HOUR) {
    const m = Math.floor(deltaMs / ONE_MINUTE);
    return `${m} ${m === 1 ? "minute" : "minutes"} ago`;
  }
  if (deltaMs < ONE_DAY) {
    const h = Math.floor(deltaMs / ONE_HOUR);
    return `${h} ${h === 1 ? "hour" : "hours"} ago`;
  }
  const d = Math.floor(deltaMs / ONE_DAY);
  return `${d} ${d === 1 ? "day" : "days"} ago`;
}

export function dedupeBlockNumbers(blockNumbers: Iterable<number>): number[] {
  const seen = new Set<number>();
  for (const b of blockNumbers) {
    if (Number.isFinite(b) && b > 0) seen.add(b);
  }
  return [...seen].sort((a, b) => a - b);
}
