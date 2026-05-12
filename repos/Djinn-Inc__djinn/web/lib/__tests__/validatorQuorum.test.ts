import { describe, expect, it } from "vitest";

import {
  callWithQuorumOrFirst,
  quorumCall,
} from "../validatorQuorum";

const tick = (ms: number) => new Promise((r) => setTimeout(r, ms));

describe("quorumCall", () => {
  it("reaches quorum when 3 validators agree", async () => {
    const promises = [
      Promise.resolve({ odds: 1.95 }),
      Promise.resolve({ odds: 1.95 }),
      Promise.resolve({ odds: 1.95 }),
    ];
    const result = await quorumCall(promises, {
      quorum: 3,
      bucketBy: (r) => r.odds.toString(),
    });
    expect(result.verdict).toBe("quorum_reached");
    expect(result.result?.odds).toBe(1.95);
    expect(result.agreement).toHaveLength(3);
    expect(result.errorCount).toBe(0);
    expect(result.total).toBe(3);
    expect(result.agreedBucket).toBe("1.95");
  });

  it("no quorum when validators disagree", async () => {
    const promises = [
      Promise.resolve({ odds: 1.95 }),
      Promise.resolve({ odds: 2.0 }),
      Promise.resolve({ odds: 2.05 }),
    ];
    const result = await quorumCall(promises, {
      quorum: 3,
      bucketBy: (r) => r.odds.toString(),
    });
    expect(result.verdict).toBe("no_quorum");
    expect(result.result).toBeNull();
    expect(result.agreement).toHaveLength(0);
    expect(result.allSuccess).toHaveLength(3);
  });

  it("reaches quorum at exactly the threshold", async () => {
    const promises = [
      Promise.resolve({ odds: 1.95 }),
      Promise.resolve({ odds: 1.95 }),
      Promise.resolve({ odds: 2.0 }),
      Promise.resolve({ odds: 2.0 }),
      Promise.resolve({ odds: 2.0 }),
    ];
    const result = await quorumCall(promises, {
      quorum: 3,
      bucketBy: (r) => r.odds.toString(),
    });
    expect(result.verdict).toBe("quorum_reached");
    expect(result.agreedBucket).toBe("2");
    expect(result.agreement).toHaveLength(3);
  });

  it("counts errors and ignores them for quorum", async () => {
    const promises = [
      Promise.resolve({ odds: 1.95 }),
      Promise.resolve({ odds: 1.95 }),
      Promise.reject(new Error("boom")),
      Promise.resolve({ odds: 1.95 }),
    ];
    const result = await quorumCall(promises, {
      quorum: 3,
      bucketBy: (r) => r.odds.toString(),
    });
    expect(result.verdict).toBe("quorum_reached");
    expect(result.errorCount).toBe(1);
    expect(result.agreement).toHaveLength(3);
  });

  it("all errors yields all_failed verdict", async () => {
    const promises = [
      Promise.reject(new Error("a")),
      Promise.reject(new Error("b")),
      Promise.reject(new Error("c")),
    ];
    const result = await quorumCall(promises, {
      quorum: 2,
      bucketBy: () => "x",
    });
    expect(result.verdict).toBe("all_failed");
    expect(result.errorCount).toBe(3);
    expect(result.result).toBeNull();
  });

  it("empty input yields all_failed", async () => {
    const result = await quorumCall([], {
      quorum: 2,
      bucketBy: () => "x",
    });
    expect(result.verdict).toBe("all_failed");
    expect(result.total).toBe(0);
  });

  it("rejects quorum < 2", async () => {
    await expect(
      quorumCall([Promise.resolve(1)], {
        quorum: 1,
        bucketBy: () => "x",
      }),
    ).rejects.toThrow(/quorum must be >= 2/);
  });

  it("fast resolves as soon as quorum is reached", async () => {
    let slowResolved = false;
    const slow = tick(500).then(() => {
      slowResolved = true;
      return { odds: 1.95 };
    });
    const promises = [
      Promise.resolve({ odds: 1.95 }),
      Promise.resolve({ odds: 1.95 }),
      slow,
    ];
    const start = Date.now();
    const result = await quorumCall(promises, {
      quorum: 2,
      bucketBy: (r) => r.odds.toString(),
    });
    const elapsed = Date.now() - start;
    expect(result.verdict).toBe("quorum_reached");
    expect(elapsed).toBeLessThan(100);
    expect(slowResolved).toBe(false);
  });

  it("fastResolve false waits for all responses", async () => {
    let slowResolved = false;
    const slow = tick(50).then(() => {
      slowResolved = true;
      return { odds: 2.0 };
    });
    const promises = [
      Promise.resolve({ odds: 1.95 }),
      Promise.resolve({ odds: 1.95 }),
      slow,
    ];
    const result = await quorumCall(promises, {
      quorum: 2,
      bucketBy: (r) => r.odds.toString(),
      fastResolve: false,
    });
    expect(result.verdict).toBe("quorum_reached");
    expect(slowResolved).toBe(true);
    expect(result.allSuccess).toHaveLength(3);
  });

  it("buckets by complex keys derived from odds vectors", async () => {
    const promises = [
      Promise.resolve({ executable: [1, 2, 3] }),
      Promise.resolve({ executable: [1, 2, 3] }),
      Promise.resolve({ executable: [1, 2] }),
    ];
    const result = await quorumCall(promises, {
      quorum: 2,
      bucketBy: (r) => r.executable.slice().sort().join(","),
    });
    expect(result.verdict).toBe("quorum_reached");
    expect(result.result?.executable).toEqual([1, 2, 3]);
  });
});

describe("callWithQuorumOrFirst (flag-gated wrapper)", () => {
  it("strict mode runs the full quorum check", async () => {
    const promises = [
      Promise.resolve({ odds: 1.95 }),
      Promise.resolve({ odds: 1.95 }),
      Promise.resolve({ odds: 2.0 }),
    ];
    const result = await callWithQuorumOrFirst(promises, {
      strict: true,
      quorum: 2,
      bucketBy: (r) => r.odds.toString(),
    });
    expect(result.verdict).toBe("quorum_reached");
    expect(result.result?.odds).toBe(1.95);
  });

  it("non-strict mode takes the first responder", async () => {
    let slowResolved = false;
    const slow = tick(100).then(() => {
      slowResolved = true;
      return { odds: 1.95 };
    });
    const promises = [
      Promise.resolve({ odds: 2.0 }),
      slow,
    ];
    const result = await callWithQuorumOrFirst(promises, {
      strict: false,
      quorum: 2,
      bucketBy: (r) => r.odds.toString(),
    });
    expect(result.result?.odds).toBe(2.0);
    expect(slowResolved).toBe(false);
  });

  it("non-strict mode handles all rejections", async () => {
    const promises = [
      Promise.reject(new Error("a")),
      Promise.reject(new Error("b")),
    ];
    const result = await callWithQuorumOrFirst(promises, {
      strict: false,
      quorum: 2,
      bucketBy: () => "x",
    });
    expect(result.verdict).toBe("all_failed");
    expect(result.result).toBeNull();
    expect(result.errorCount).toBe(2);
  });

  it("non-strict mode falls back to no_quorum if some succeed but no first taken", async () => {
    const result = await callWithQuorumOrFirst([], {
      strict: false,
      quorum: 2,
      bucketBy: () => "x",
    });
    expect(result.verdict).toBe("all_failed");
  });

  it("strict mode no_quorum still returns disagreeing responses for diagnostics", async () => {
    const promises = [
      Promise.resolve({ odds: 1.95 }),
      Promise.resolve({ odds: 2.0 }),
    ];
    const result = await callWithQuorumOrFirst(promises, {
      strict: true,
      quorum: 2,
      bucketBy: (r) => r.odds.toString(),
    });
    expect(result.verdict).toBe("no_quorum");
    expect(result.allSuccess).toHaveLength(2);
  });
});
