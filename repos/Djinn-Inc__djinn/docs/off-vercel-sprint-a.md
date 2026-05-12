# Sprint (A): Move 4 Platform-Unique Routes to Validator `/v1/*`

Part of the off-Vercel migration mandated after the 2026-04-19 Vercel security incident. User constraint: no central Go node, no VPS shim — only validators + client-side + static/IPFS. Status: plan filed; execution queued.

## 0. Current-State Facts (verified, not inferred)

- Validator HTTP surface is one monolith: `/home/user/djinn/validator/djinn_validator/api/server.py` (~5755 lines). All `/v1/*` endpoints are registered as inline closures in `create_app()` (~line 396). New endpoints added there inherit CORS, body-size limit, `RateLimitMiddleware`, `RequestIdMiddleware`, and optional `_admin_auth` (Bearer `ADMIN_API_KEY`, production-gated).
- Validator has no odds-fetching code today. `sports_api_key` in `djinn_validator/config.py:286` is already deprecated (see `core/outcomes.py:373-384` — validator uses ESPN for scores). The 4 routes require adding a new outbound HTTP caller plus env var `ODDS_API_KEYS` to `config.py`.
- Web client discovery already exists: `web/lib/validatorDiscovery.ts` (bootstrap `https://v0.djinn.gg`, gossips via `/v1/network/validators` then health-checks), `web/lib/validatorHostnames.ts` (`v<uid>.djinn.gg` wildcard), `web/lib/validatorQuorum.ts` (Q-of-N bucketing). Sprint (A) reuses all three; no new discovery primitives needed.
- Current `/api/debug/metagraph` does NOT use `TAOSTATS_API_KEY` — it reads via `bt-metagraph.ts` (direct subtensor HTTP RPC). The validator already holds a live `neuron.metagraph`, so the validator version is strictly cheaper. Admin-auth is still required because the endpoint reveals probe results + env-var presence.

## 1. Endpoint Spec (all under `/v1/*`, added to `server.py` between ~L5275 and ~L5320)

### 1.1 `GET /v1/odds/{sport}?markets=spreads,totals,h2h`
- Contract: returns raw Odds-API event array (shape unchanged; `OddsEvent[]` in `web/lib/odds.ts` parses it).
- Params: identical allowlist to `web/app/api/odds/route.ts:32-51` (17 sports, 3 markets). Fold into a module-level constant in new helper `djinn_validator/core/odds_feed.py`.
- Cache: in-process dict keyed by `(sport, markets)`, `fresh_ttl=60s` + `stale_ttl=300s`; serve stale while revalidating. Port the TS pattern 1:1. Cross-validator divergence OK because clients can quorum across 2+.
- Key rotation: port `web/lib/oddsKeys.ts` to Python. Use `ODDS_API_KEYS` (comma-separated) in validator `.env`, mirroring web env-var name.
- Rate limit: `limiter.set_path_limit("/v1/odds", capacity=120, rate=2)` at `server.py:~455` (matches 120/min per-IP).
- Errors: 400 (bad sport/markets), 429 (limiter), 502 (all upstream keys failed, with negative cache), 503 (no keys configured).

### 1.2 `GET /v1/odds/{sport}/events/{event_id}/alt`
- Contract: Odds-API per-event response with `markets=alternate_spreads,alternate_totals`. Same shape as `web/app/api/odds/alt/route.ts` returns.
- Shares rotation state + negative cache with §1.1 (same Python module singleton). Critical: Odds-API quota is per-key not per-endpoint; a 429 on `/odds` must advance the pointer seen by `/odds/alt` too.
- Cache: 60s fresh, 120s stale-while-revalidate.

### 1.3 `GET /v1/sports`
- Contract: `{ sports: [{key, name, category}], total }` — the 8-entry hardcoded list from `web/app/api/sports/route.ts:12-21`.
- Recommended: static, hardcoded in `server.py`. Current TS route hardcodes it. Do the same here; no cache needed.
- Rejected: derive from `/v4/sports` Odds-API call — adds latency + key burn for an endpoint that changes once per season.

### 1.4 `GET /v1/debug/metagraph` (admin-auth gated)
- Contract: full JSON shape of `web/app/api/debug/metagraph/route.ts:64-94` (`env`, `discoveryMs`, `minerDiscoveryMs`, `totalNodes`, `publicNodes`, `validators`, `activeValidators`, `miners`, `minerUrl`, `cacheAge`, `topMiners[]`, `topValidators[]`).
- Data source: `neuron.metagraph` already in memory — no subtensor RPC. `discoveryMs` becomes "time to project the snapshot to JSON"; `cacheAge = now_ms - neuron.metagraph.last_sync_ms` (expose `neuron.metagraph_synced_at` if not present; cheap `neuron.py` addition).
- Version probes: reuse peer-probe pattern from `/v1/network/overview` (`server.py:2723-2960`). Parallel, 3s/peer budget.
- Auth: `dependencies=[_admin_auth]` (identical to `/v1/activity` at `server.py:2370`).
- `TAOSTATS_API_KEY`: NOT wired today and not needed — drop that prompt assumption.

## 2. Files That Change on the Validator

- `validator/djinn_validator/api/server.py` — add 4 route closures (~+220 lines), register `/v1/odds` rate limit, import `odds_feed`.
- `validator/djinn_validator/core/odds_feed.py` — NEW. Holds allowlists, key rotation state, negative cache, in-process odds cache, `fetch_upcoming(sport, markets)` + `fetch_event_alt(sport, event_id)` coroutines. Mirror `web/lib/oddsKeys.ts` one-for-one.
- `validator/djinn_validator/config.py` — add `odds_api_keys: list[str]` (parse `ODDS_API_KEYS`, comma-split), add to `_REDACTED_FIELDS`. Keep deprecated `sports_api_key` untouched.
- `validator/djinn_validator/bt/neuron.py` — add `metagraph_synced_at_ms` timestamp on every `sync_metagraph()` call, for `cacheAge` parity.
- `validator/tests/test_odds_feed.py` — NEW. Mirror `web/app/api/odds/__tests__/*` table-driven cases.

## 3. Client Discovery & Validator Picking

No new primitives. Use `discoverValidators()` from `web/lib/validatorDiscovery.ts` at app init (already wired for other routes), then:
- Low-stakes (odds, sports): `Promise.any()` across 2 fastest, fall back to next 2 on timeout. 60s stale-skew is acceptable for display.
- Debug/metagraph: single validator, admin session already selected. No quorum.
- Quorum-required paths: none of the 4. Odds is read-only display data.

## 4. Staged Rollout (each stage independently shippable)

**Stage A-1 — validator endpoints (no client change).** Ship `server.py` routes + `odds_feed.py` + `config.py`. Operators update `.env` with `ODDS_API_KEYS`. Verify via `curl https://v0.djinn.gg/v1/odds/basketball_nba`. No user-visible change.

**Stage A-2 — Next routes become proxies.** Edit `web/app/api/odds/route.ts`, `/odds/alt/route.ts`, `/sports/route.ts`, `/debug/metagraph/route.ts` to forward to `${DEFAULT_BOOTSTRAP}/v1/...` with 5s timeout. Keep rate limit + allowlist validation client-side so a misbehaving validator can't widen the surface. Flip one route at a time; each reversible in isolation.

**Stage A-3 — client direct fetch.** Update call sites (`web/lib/odds.ts`, components calling `/api/debug/metagraph`) to call `discoverValidators()` first, then hit validator directly. Behind `directValidatorFetch` flag in `web/lib/featureFlags.ts`. Canary 10% → 100%.

**Stage A-4 — delete Next routes.** Once A-3 is 100% stable for 7d, delete the 4 `route.ts` files, `oddsKeys.ts` (Python-only now), and `ODDS_API_KEYS`/`ODDS_API_KEY` from Vercel.

## 5. Risks

- **Odds freshness (§1.1, §1.2):** Odds-API lines move within 60s during live windows. Current Next route caches 60s fresh + 300s stale; validator will do same. Cross-validator client racing 2 validators can see a 60s skew — OK for display but **signal-commit flow must NOT trust stale quotes**. Mitigation: at commit time, `/v1/signal/{id}/check-odds` (server.py:5016) already fans out to miners with contemporaneous TLSN-attested quote; validator-cached `/v1/odds` is decorative for commit. AUDIT that no commit-side code depends on `/api/odds` freshness before A-3.
- **Key-exposure blast radius.** Today `ODDS_API_KEYS` live on one Vercel deployment. Moving to every validator `.env` multiplies exposure by N operators. Mitigation: (a) per-operator key (no shared master across subnet), documented in validator README, (b) Odds-API per-key quota becomes per-operator. Without this, one compromised validator leaks the shared key.
- **Metagraph admin auth shift.** Next session cookie → validator Bearer token. Acceptable (admins have hotkey access). Document in `validator/README.md`; web admin UI needs a token picker, not cookie.
- **No central quorum enforcement.** If 1 validator returns stale/wrong odds, client has no recourse. Mitigation: A-3 ships `fastestTwo()` default; promote to `quorumOf(2, bucketBy=eventIdsHash)` behind flag once agreement rates measured.

## Critical Files (for execution)
- `validator/djinn_validator/api/server.py`
- `validator/djinn_validator/core/odds_feed.py` (new)
- `validator/djinn_validator/config.py`
- `validator/djinn_validator/bt/neuron.py`
- `web/lib/validatorDiscovery.ts`
- `web/lib/oddsKeys.ts`
- `web/app/api/odds/route.ts`
- `web/app/api/odds/alt/route.ts`
- `web/app/api/sports/route.ts`
- `web/app/api/debug/metagraph/route.ts`

## Next Action
Wait for Sprint B (static-export plan) so sequencing is complete, then pick Stage A-1 as the first executable unit.
