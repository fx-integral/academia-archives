# v1744 — Durable outbound peer-gossip retry queue

## Problem

After purchase, the originating validator gossips `(signal_id, buyer, BPA, WPA, bpa_mode)` to every other registered validator so any validator can run batch settlement on the audit set. Pre-v1721 this was fire-and-forget; v1721 added 3 in-memory retry rounds (30s, 90s, 240s ≈ 6 min total) so transient 5xx and brief peer restarts recover automatically.

What v1721 does **not** cover: a peer offline for **longer** than ~6 minutes during the gossip window. The originating validator gives up, the offline peer permanently lacks the data, and at audit time it 404s on `/v1/purchase_odds/{signal_id}/{buyer}`. Once 10 abstain ticks accumulate the audit_set is permanent_abstain-evicted (v1716/v1736) and never settles. Quorum becomes mathematically unreachable for that cohort.

Empirical evidence (from `project_audit_state_2026_05_08.md`): on UID 0 with no fresh traffic, `purchase_odds_prefetch peer_404=56 / peer_unreachable=50 / recovered=0` — recovery never works because the data is genuinely missing from peers, not because the recovery code is broken.

## Solution

Persist every non-acked-non-permanent peer to a SQLite-backed queue at the end of the in-memory retry budget. A background worker drains the queue continuously with exponential backoff (5 min → 1 hour cap), so a peer that recovers any time within the next 24 hours still receives the gossip and can participate in the audit. Beyond 24 h the row is marked `failed_terminal` and dropped.

Design mirrors v1743 (`error_reports.py`):

- One SQLite file: `~/.djinn-validator/gossip_outbox.db`
- One row per `(peer_uid, endpoint, payload_hash)` tuple — UNIQUE constraint prevents duplicate enqueues from re-tries.
- States: `pending` → `acked` | `failed_terminal`.
- 200 → `acked`. 4xx → `failed_terminal` (peer rejected; retry won't help). 5xx / network error → stays `pending`, `next_attempt_ts` pushed by exponential backoff.

## Files

- `validator/djinn_validator/core/gossip_outbox.py` — new module (queue + worker).
- `validator/djinn_validator/api/server.py` — `_gossip_purchase_odds_to_peers` enqueues stragglers after the in-memory budget exhausts.
- `validator/djinn_validator/api/server.py` — `/v1/audit/summary` surfaces `gossip_outbox_pending/acked/failed_terminal` so operators see queue depth.
- `validator/djinn_validator/api/models.py` — `AuditSummaryResponse` adds the three fields with default 0 (back-compat for non-git operators).
- `validator/djinn_validator/main.py` — wires `configure(...)` with the live wallet signer and starts the drain worker on the running event loop.
- `validator/tests/test_gossip_outbox.py` — 14 unit tests covering enqueue, dedup, drain outcomes, lifetime cap, backoff.

## Why this layer

P0-01 has three layers:
1. **Share distribution** — fixed by v1670/v1671 (SealedBox bundle fan-out + share recovery).
2. **Outcome divergence** — open. Validators see different subsets of resolved purchase IDs in the same batch, so `batchKey` diverges and 4-of-5 quorum can't agree on a bucket.
3. **purchase_odds availability** — partly mitigated by v1721 (in-memory retry) and v1740 (bootstrap pull). v1744 closes the remaining gap: peers that miss the original gossip AND recover after the 6-min in-memory budget AND remain offline through the next bootstrap window.

Layer 3 is now end-to-end durable. Layer 2 (outcome divergence) is the next architectural problem; v1744 doesn't address it but the same machinery (`gossip_outbox` is `path_label`-keyed) can later wrap outcome gossip without a copy-paste rebuild.

## Operator visibility

```sh
$ curl -s https://v0.djinn.gg/v1/audit/summary | jq
{
  "total": 102,
  "waiting_for_outcomes": 5,
  "ready_for_settlement": 71,
  "permanently_abstained": 71,
  "settled": 26,
  "total_signals": 973,
  "resolved_signals": 951,
  "gossip_outbox_pending": 0,         # v1744: in-flight to recovering peers
  "gossip_outbox_acked": 0,           # v1744: lifetime-acked count (resets per DB)
  "gossip_outbox_failed_terminal": 0  # v1744: 4xx rejections + 24h timeouts
}
```

`gossip_outbox_pending > 0` over multiple polls means at least one peer is still down at gossip time; the queue will keep retrying. `gossip_outbox_failed_terminal > 0` means at least one peer rejected the payload (e.g. peer is on a pre-v1573 version that doesn't have `/v1/purchase_odds/record`) or the 24h horizon was hit.

## Tunables

All env-driven; defaults in `gossip_outbox.py`:

| Env var | Default | Meaning |
|---------|---------|---------|
| `DJINN_GOSSIP_OUTBOX_POLL_SEC` | `60` | Drain loop cadence |
| `DJINN_GOSSIP_OUTBOX_BATCH` | `20` | Rows per drain pass |
| `DJINN_GOSSIP_OUTBOX_HTTP_TIMEOUT` | `10` | Per-POST timeout |
| `DJINN_GOSSIP_OUTBOX_INITIAL_INTERVAL` | `300` | First-retry delay (s) after enqueue |
| `DJINN_GOSSIP_OUTBOX_MAX_INTERVAL` | `3600` | Cap on exponential backoff |
| `DJINN_GOSSIP_OUTBOX_MAX_LIFETIME` | `86400` | 24h horizon before terminal |
| `DJINN_GOSSIP_OUTBOX_BACKOFF_BASE` | `2.0` | Exponent base |

## Forward path

- v1745: extend `path_label` to outcome gossip so the same machinery covers Layer 2's transport gap. **Shipped same day.**
- v1746: bump `DJINN_AUDIT_PERMANENT_ABSTAIN_THRESHOLD` default 10 → 600 to align with v1744's retry profile. Without v1746 the eviction window (2 min) is shorter than v1744's first outbox retry (11 min after gossip start), so v1744 could never save fresh batches. **Shipped same day.**
- The queue is per-validator local; if many validators are simultaneously offline at gossip time, all originators carry their own queues and converge independently. No coordination needed.

## v1744+v1745+v1746 timing reconciliation

```
T=0     gossip fires (first round)
T=30s   in-memory retry round 1
T=2m    in-memory retry round 2  ← old threshold=10 evicts here (12s × 10 = 2min)
T=6m    in-memory budget exhausts → enqueue to gossip_outbox
T=11m   outbox first retry (5min after enqueue)
T=21m   outbox second retry (~10min backoff)
T=41m   outbox third retry (~20min backoff)
T=1h    outbox retries continue with capped 1h backoff
T=2h    new threshold=600 evicts here (12s × 600 = 2h) if data still missing
T=24h   max_lifetime_sec — outbox row goes failed_terminal
```

The v1746 threshold was chosen so the eviction window sits *between* v1744's
3rd-4th retry attempt and v1744's lifetime horizon. Operators can tune
either side via env vars if their fleet's failure profile demands it.
