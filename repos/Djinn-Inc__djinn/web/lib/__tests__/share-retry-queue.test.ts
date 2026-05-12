import { afterEach, beforeEach, describe, it, expect } from "vitest";
import {
  enqueue,
  dequeue,
  pending,
  processQueue,
  expireStale,
} from "@/lib/share-retry-queue";
import type { ShareBundle } from "@/lib/share-bundle";

const STORAGE_KEY = "djinn_share_retry_queue_v1";

beforeEach(() => {
  window.localStorage.clear();
});

afterEach(() => {
  window.localStorage.clear();
});

function fakeBundle(signalId: string): ShareBundle {
  return {
    signal_id: signalId,
    genius_address: "0xgenius",
    shamir_threshold: 2,
    bundle: [],
  };
}

describe("share-retry-queue", () => {
  it("enqueue persists to localStorage", () => {
    enqueue("sig1", "https://v0.example", fakeBundle("sig1"));
    const raw = window.localStorage.getItem(STORAGE_KEY);
    expect(raw).not.toBeNull();
    const parsed = JSON.parse(raw!);
    expect(parsed).toHaveLength(1);
    expect(parsed[0].signalId).toBe("sig1");
  });

  it("enqueue is idempotent on (signal, url)", () => {
    enqueue("sig1", "https://v0.example", fakeBundle("sig1"));
    enqueue("sig1", "https://v0.example", fakeBundle("sig1"));
    expect(pending()).toHaveLength(1);
  });

  it("enqueue tolerates same signal across different URLs", () => {
    enqueue("sig1", "https://v0.example", fakeBundle("sig1"));
    enqueue("sig1", "https://v1.example", fakeBundle("sig1"));
    expect(pending()).toHaveLength(2);
  });

  it("dequeue removes a single entry by id", () => {
    enqueue("sig1", "https://v0.example", fakeBundle("sig1"));
    enqueue("sig2", "https://v0.example", fakeBundle("sig2"));
    dequeue("sig1::https://v0.example");
    const left = pending();
    expect(left).toHaveLength(1);
    expect(left[0].signalId).toBe("sig2");
  });

  it("processQueue calls deliverFn for ready entries and dequeues on success", async () => {
    enqueue("sig1", "https://v0.example", fakeBundle("sig1"));
    // Make it ready: backdate nextRetryAt
    const e = pending();
    e[0].nextRetryAt = Date.now() - 1000;
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(e));

    const calls: string[] = [];
    const result = await processQueue(async (url) => {
      calls.push(url);
    });
    expect(calls).toEqual(["https://v0.example"]);
    expect(result.succeeded).toBe(1);
    expect(pending()).toHaveLength(0);
  });

  it("processQueue increments attempts and reschedules on failure", async () => {
    enqueue("sig1", "https://v0.example", fakeBundle("sig1"));
    const e = pending();
    e[0].nextRetryAt = Date.now() - 1000;
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(e));

    const result = await processQueue(async () => {
      throw new Error("nope");
    });
    expect(result.failed).toBe(1);
    const remaining = pending();
    expect(remaining).toHaveLength(1);
    expect(remaining[0].attempts).toBe(1);
    expect(remaining[0].nextRetryAt).toBeGreaterThan(Date.now());
  });

  it("processQueue skips entries whose nextRetryAt is in the future", async () => {
    enqueue("sig1", "https://v0.example", fakeBundle("sig1"));
    let called = false;
    const result = await processQueue(async () => {
      called = true;
    });
    expect(called).toBe(false);
    expect(result.skipped).toBe(1);
  });

  it("expireStale drops entries past TTL", () => {
    enqueue("sig1", "https://v0.example", fakeBundle("sig1"));
    const e = pending();
    e[0].createdAt = Date.now() - 11 * 60_000; // 11 minutes ago, past 10m TTL
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(e));
    expireStale();
    expect(pending()).toHaveLength(0);
  });
});
