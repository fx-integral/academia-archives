/**
 * localStorage-backed retry queue for share-bundle fan-out (Phase 3).
 *
 * When a genius creates a signal, the SAME bundle is POSTed to every OV
 * validator URL. Some POSTs may fail transiently (validator HTTP down,
 * 504, etc.). This queue persists pending POSTs across page refreshes and
 * retries with exponential backoff for up to 10 minutes per entry.
 *
 * The bundle is genius-signed in spirit (the genius's private key
 * authorizes the on-chain signal commit), so the validator endpoint
 * is idempotent on (signal_id, target). Retrying after success is
 * harmless — the validator returns 200 with own_share_stored=true on
 * the first call and 200 / 409 on subsequent ones.
 */

import type { ShareBundle } from "@/lib/share-bundle";

const STORAGE_KEY = "djinn_share_retry_queue_v1";
const MAX_ATTEMPTS = 12; // ~12 attempts at 30s ⇒ ~6 minutes
const BASE_DELAY_MS = 5_000;
const MAX_DELAY_MS = 60_000;
const ENTRY_TTL_MS = 10 * 60_000;

export interface RetryEntry {
  id: string; // unique: signal_id + url
  signalId: string;
  validatorUrl: string;
  bundle: ShareBundle;
  attempts: number;
  nextRetryAt: number;
  createdAt: number;
}

function isBrowser(): boolean {
  return typeof window !== "undefined" && typeof window.localStorage !== "undefined";
}

function loadAll(): RetryEntry[] {
  if (!isBrowser()) return [];
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

function saveAll(entries: RetryEntry[]): void {
  if (!isBrowser()) return;
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(entries));
  } catch {
    // Storage full / unavailable — drop silently. Failed retries are not
    // worth crashing the page over.
  }
}

export function enqueue(signalId: string, validatorUrl: string, bundle: ShareBundle): void {
  const id = `${signalId}::${validatorUrl}`;
  const entries = loadAll();
  if (entries.some((e) => e.id === id)) return; // already queued
  entries.push({
    id,
    signalId,
    validatorUrl,
    bundle,
    attempts: 0,
    nextRetryAt: Date.now() + BASE_DELAY_MS,
    createdAt: Date.now(),
  });
  saveAll(entries);
}

export function dequeue(id: string): void {
  const entries = loadAll().filter((e) => e.id !== id);
  saveAll(entries);
}

export function pending(): RetryEntry[] {
  return loadAll();
}

export function expireStale(): void {
  const now = Date.now();
  const entries = loadAll().filter((e) => now - e.createdAt < ENTRY_TTL_MS && e.attempts < MAX_ATTEMPTS);
  saveAll(entries);
}

function nextDelay(attempts: number): number {
  const exp = Math.min(MAX_DELAY_MS, BASE_DELAY_MS * Math.pow(2, attempts));
  // Jitter +/- 20% so a stampede of geniuses doesn't all retry the same second.
  const jitter = exp * 0.4 * (Math.random() - 0.5);
  return Math.max(BASE_DELAY_MS, Math.round(exp + jitter));
}

/**
 * Try to deliver every queued entry whose nextRetryAt <= now.
 * `deliverFn(url, bundle)` should resolve on success (any 2xx) and reject
 * on retryable failure. The caller wires this to ValidatorClient.storeShareBundle.
 */
export async function processQueue(
  deliverFn: (url: string, bundle: ShareBundle) => Promise<void>,
): Promise<{ succeeded: number; failed: number; skipped: number }> {
  expireStale();
  const entries = loadAll();
  const now = Date.now();
  let succeeded = 0;
  let failed = 0;
  let skipped = 0;

  for (const entry of entries) {
    if (entry.nextRetryAt > now) {
      skipped++;
      continue;
    }
    try {
      await deliverFn(entry.validatorUrl, entry.bundle);
      dequeue(entry.id);
      succeeded++;
    } catch {
      entry.attempts += 1;
      entry.nextRetryAt = Date.now() + nextDelay(entry.attempts);
      if (entry.attempts >= MAX_ATTEMPTS) {
        dequeue(entry.id);
      } else {
        const others = loadAll().filter((e) => e.id !== entry.id);
        saveAll([...others, entry]);
      }
      failed++;
    }
  }

  return { succeeded, failed, skipped };
}

/**
 * Start a background interval that processes the queue every `intervalMs`.
 * Returns a stop function. Safe to call multiple times — only the latest
 * interval keeps running.
 */
let _activeIntervalId: ReturnType<typeof setInterval> | null = null;
export function startBackgroundProcessor(
  deliverFn: (url: string, bundle: ShareBundle) => Promise<void>,
  intervalMs = 15_000,
): () => void {
  if (!isBrowser()) return () => {};
  if (_activeIntervalId !== null) clearInterval(_activeIntervalId);
  _activeIntervalId = setInterval(() => {
    processQueue(deliverFn).catch(() => {});
  }, intervalMs);
  return () => {
    if (_activeIntervalId !== null) {
      clearInterval(_activeIntervalId);
      _activeIntervalId = null;
    }
  };
}
