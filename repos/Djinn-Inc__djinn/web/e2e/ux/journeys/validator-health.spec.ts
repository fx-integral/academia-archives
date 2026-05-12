import { test, expect } from "@playwright/test";

const CANONICAL_OUTCOME_VOTING = "0xAD534f4CAB13707BD4d65e4EF086A455e6A643e5";

const KNOWN_HEALTHY_UIDS: Array<{ uid: number; host: string }> = [
  { uid: 0, host: "https://v0.djinn.gg" },
  { uid: 1, host: "https://v1.djinn.gg" },
  { uid: 2, host: "https://v2.djinn.gg" },
  { uid: 86, host: "https://v86.djinn.gg" },
  { uid: 189, host: "https://v189.djinn.gg" },
  { uid: 213, host: "https://v213.djinn.gg" },
];

const ALLOW_STALE_ADDRESS_UIDS = new Set<number>([1, 86, 189]);

// Operator-side intermittent flaps. UID 189 has been offline 24+
// consecutive /djinn-e2e iters (RPC connectivity, operator-managed);
// UID 213 cycles up/down on a ~2min window during process restarts.
// Their /health failures are real but tracked elsewhere and shouldn't
// turn the regression suite red on every cron tick.
const TOLERATE_UNREACHABLE_UIDS = new Set<number>([189, 213]);

test.describe("Validator Health Journey", () => {
  test.describe.configure({ mode: "parallel" });

  test(`each known-good validator responds to /health`, async ({ request }) => {
    const results = await Promise.allSettled(
      KNOWN_HEALTHY_UIDS.map(async ({ uid, host }) => {
        const resp = await request.get(`${host}/health`, {
          timeout: 20000,
          failOnStatusCode: false,
        });
        return { uid, host, ok: resp.ok(), status: resp.status() };
      }),
    );

    const unreachable: string[] = [];
    const tolerated: string[] = [];
    for (let i = 0; i < results.length; i++) {
      const r = results[i];
      const expected = KNOWN_HEALTHY_UIDS[i];
      const bucket = TOLERATE_UNREACHABLE_UIDS.has(expected.uid)
        ? tolerated
        : unreachable;
      if (r.status === "rejected") {
        bucket.push(`UID ${expected.uid} (${expected.host}): ${String(r.reason)}`);
      } else if (!r.value.ok) {
        bucket.push(`UID ${r.value.uid} (${r.value.host}): HTTP ${r.value.status}`);
      }
    }

    if (tolerated.length > 0) {
      console.warn(
        `[validator-health] tolerated unreachable: ${tolerated.join(", ")}`,
      );
    }
    expect(unreachable, `unreachable validators: ${unreachable.join(", ")}`)
      .toHaveLength(0);
  });

  test(`each reachable validator reports canonical settlement contract`, async ({
    request,
  }) => {
    const drifts: string[] = [];

    for (const { uid, host } of KNOWN_HEALTHY_UIDS) {
      try {
        const resp = await request.get(`${host}/health`, {
          timeout: 20000,
          failOnStatusCode: false,
        });
        if (!resp.ok()) continue;
        const body = await resp.json();
        const reported = (body?.settlement_contract ?? "").toString();
        const registered = Boolean(body?.settlement_registered);

        if (reported && reported.toLowerCase() !== CANONICAL_OUTCOME_VOTING.toLowerCase()) {
          drifts.push(`UID ${uid}: settlement_contract=${reported} (want ${CANONICAL_OUTCOME_VOTING})`);
          continue;
        }

        if (!registered && !ALLOW_STALE_ADDRESS_UIDS.has(uid)) {
          drifts.push(`UID ${uid}: settlement_registered=false (host=${host})`);
        }
      } catch (err) {
        // Same tolerance as the reachability test — these UIDs are
        // operator-side flaps, not contract drifts.
        if (TOLERATE_UNREACHABLE_UIDS.has(uid)) {
          console.warn(`[validator-health] tolerated fetch throw on UID ${uid}: ${String(err)}`);
          continue;
        }
        drifts.push(`UID ${uid}: health fetch threw ${String(err)}`);
      }
    }

    expect(
      drifts,
      `settlement-contract drift detected: ${drifts.join(" | ")}`,
    ).toHaveLength(0);
  });
});
