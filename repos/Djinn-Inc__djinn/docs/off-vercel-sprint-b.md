# Sprint (B): Cloudflare Pages + IPFS Static Cutover

Part of the off-Vercel migration mandated after the 2026-04-19 Vercel security incident. User constraint: no central Go node, no VPS shim — only validators + client-side + static/IPFS. Status: plan filed; execution queued after Sprint A lands validator endpoints.

## 1. Starting State (already on disk)

Static-export infra exists but is partial. Build script today works by stashing the problem, not fixing it.

- `web/next.config.js` — server build; delegates to `next.config.ipfs.js` when `NEXT_BUILD_TARGET=ipfs`; bakes `NEXT_PUBLIC_GIT_VERSION` from git; validates NEXT_PUBLIC_*_ADDRESS envs.
- `web/next.config.ipfs.js` — `output:"export"`, `trailingSlash:true`, `distDir:".next-ipfs"`, `images.unoptimized`, webpack aliases to stub indexedDB/wagmi during SSR. Typechecking+lint off.
- `web/scripts/build-ipfs.sh` — "stash then build then restore" that `mv`s `app/api` and the 4 dynamic `[...]` dirs out of the tree before `next build`, then restores. The stash IS the signal that blockers have never been structurally fixed.
- `package.json`: `"build:ipfs": "bash scripts/build-ipfs.sh"`, `engines.pnpm>=9`.

## 2. Dynamic-Route Inventory (page routes)

Four page dynamic dirs. All `"use client"`. None have `generateStaticParams`. Build script currently deletes all four for the build.

| Route | Param universe | Bounded? | Prerender strategy |
|---|---|---|---|
| `/idiot/signal/[id]` | on-chain signal IDs (BigInt, growing) | unbounded | Restructure to `/idiot/signal/?id=...` query route |
| `/genius/signal/[id]` | same | unbounded | same — query-string routing |
| `/network/miner/[uid]` | SN103, uid 0..255 | bounded 256 | `generateStaticParams` returns `Array.from({length:256},(_,i)=>({uid:String(i)}))` |
| `/network/validator/[uid]` | same 0..255 | bounded 256 | same |

API-route dynamic dirs are irrelevant once `app/api/` is deleted in Stage 3.

## 3. Middleware Inventory

`web/middleware.ts` has 3 concerns, all replaceable outside Next:

1. **OFAC geo-block + `/blocked` redirect for CU/IR/KP/SY/SD/MM.** CF Firewall Rules or Transform Rule matching `ip.geoip.country in {"CU","IR","KP","SY","SD","MM"}`; return redirect to `/blocked`. Or a CF Pages Function `functions/_middleware.ts` (CF Pages supports this natively).
2. **In-memory IP rate limit (200/min).** Replace with CF Rate Limiting rules on the zone. Better than current map-in-memory.
3. **Security headers + CSP.** Move to `web/public/_headers` (CF Pages reads it). Strip Vercel bits from `connect-src`; keep `https://*.djinn.gg`, `https://*.base.org wss://*.base.org`, walletconnect, subgraph, web3modal, CF challenges. Drop CORS headers (no more `/api/*`).

CORS is moot post-migration; browsers call `*.djinn.gg` validators directly and each validator must send `Access-Control-Allow-Origin`. Verify in validator HTTP layer before cutover.

## 4. API-Route Disposition (43 routes)

**A — Replaced by direct validator call:** `idiot/browse`, `genius/signals`, `network/status`, `network/matrix`, `network/miner/[uid]`, `network/miner/[uid]/history`, `network/validator/[uid]`, `validators/discover`, `miners/discover`, `validator/[...path]`, `miner/[...path]`, `validators/[uid]/[...path]`, `miners/[uid]/[...path]`, `idiot/genius/[address]`, `genius/signal/[id]`, `settlement/[genius]/[idiot]`, `network/config`, `debug/metagraph`, `health`. Metagraph discovery (`lib/bt-metagraph.ts`, substrate RPC) must move client-side OR be replaced by `/v1/discover` against any validator. **Recommended: have validators expose `/v1/discover` and `/v1/network/matrix`, drop client-side substrate RPC.**

**B — Direct on-chain read via viem/ethers from browser:** chain-scan routes (`idiot/browse`, `genius/signals`) can also fall back to direct RPC — slower but no validator dependency. Client already uses viem.

**C — Client-side tx prep (per Sprint A mandate):** `attest`, `auth/*`, `genius/claim`, `genius/collateral/*`, `genius/earnings`, `idiot/balance`, `idiot/deposit`, `idiot/withdraw`, `idiot/purchase`, `idiot/purchases`, `genius/signal/commit` — all become wallet-signed operations in-browser using wagmi + ABIs in `lib/contracts.ts`.

**D — Third-party proxy (API-key hiding):** `odds`, `odds/alt` (Odds API), `delegates` (Taostats), `sports`. HARD BLOCKER for pure client. Two options:
- **Recommended:** validator-host (any validator with key serves `/v1/odds`, `/v1/delegates`). Hinted in `next.config.ipfs.js` comments already. **COVERED BY SPRINT A** for odds + sports + metagraph. ADD to Sprint A: `/v1/delegates` (Taostats).
- Alternative: single CF Pages Function in `functions/api/odds.ts`. Violates "no central server" strictly but is zero-cost.

**E — Platform-unique → DELETE:** `admin/auth`, `admin/errors`, `admin/feedback`, `admin/clear-cache`, `admin/latest-version`, `cron/warm`, `report-error`, `hash/[...path]`. Admin becomes client-side (wallet-sig challenge against hardcoded admin address list). Error reporting → validator `/v1/report-error` or just `console.error`. Cron warm is dead. `hash/[...path]` → SubtleCrypto in browser.

**HARD blockers needing user decision:**
- API-key proxies: validator-host (+ add `/v1/delegates`, `/v1/report-error` to Sprint A scope) OR CF Pages Function?
- Admin auth: wallet-sig against admin address list OR CF Access SSO on `/admin`? Current `ADMIN_PASSWORD` env-var pattern is dead regardless.

## 5. Build-time Env Vars

All component env reads are `NEXT_PUBLIC_*`; no server-only reads leak into components. IPFS build needs:
- Address envs (already validated by `next.config.js`): `NEXT_PUBLIC_USDC_ADDRESS`, `NEXT_PUBLIC_ESCROW_ADDRESS`, `NEXT_PUBLIC_SIGNAL_COMMITMENT_ADDRESS`, `NEXT_PUBLIC_COLLATERAL_ADDRESS`, `NEXT_PUBLIC_CREDIT_LEDGER_ADDRESS`, `NEXT_PUBLIC_ACCOUNT_ADDRESS`.
- Network: `NEXT_PUBLIC_CHAIN_ID`, `NEXT_PUBLIC_BASE_RPC_URL`, `NEXT_PUBLIC_WALLETCONNECT_PROJECT_ID`, `NEXT_PUBLIC_DEPLOY_BLOCK`, `NEXT_PUBLIC_AUDIT_ADDRESS`, `NEXT_PUBLIC_GRAFANA_URL` (opt), `NEXT_PUBLIC_BASE_EXPLORER`.
- Git version via `execSync` — works in CF Pages build container; verify.

## 6. Staged Cutover Plan

**Stage 0 — Land plan, archive `build-ipfs.sh` workarounds into TODO (0.5h)** ✅ landed.

**Stage 1 — Make dynamic routes buildable (4-6h)**
- Add server-side `generateStaticParams` to each of 4 dynamic `page.tsx`. Because they are `"use client"`, split each into `page.tsx` (server RSC, returns `generateStaticParams` + renders client shell) and `view.tsx` (client component with current code).
- `/network/miner/[uid]` and `/network/validator/[uid]`: return 256 UIDs each.
- `/idiot/signal/[id]` and `/genius/signal/[id]`: structural change → `/idiot/signal/?id=...`. Drop `[id]` dir; read `useSearchParams()`. Update `router.push` and `<Link>` call sites (handful per grep). Stub redirect can preserve old URLs.

**Stage 2 — Replace middleware (2-3h)**
- `public/_headers` with CSP + security headers from `middleware.ts` L70-91.
- CF Pages Function `functions/_middleware.ts` for geo-block (port OFAC; read `request.cf.country`). OR CF dashboard WAF rule.
- CF Rate Limit rule on zone for 200/min/IP.
- Delete `middleware.ts` (or keep for the `build` target; `output:"export"` refuses middleware bundling anyway — that's why it's currently stashed).

**Stage 3 — Delete API routes + client migration (20-30h; admin page is most of this)**
- Prereq: Sprint A Stage A-1 lands validator `/v1/odds`, `/v1/odds/alt`, `/v1/sports`, `/v1/debug/metagraph`, PLUS new additions `/v1/delegates`, `/v1/network/matrix`, `/v1/report-error`, `/v1/discover`. Without these, Stage 3 stalls.
- Migrate client callers off `/api/*` to validator hostname helper or in-browser libs. ~80 call sites.
- Decide odds/delegates/sports path: validator-hosted (Sprint A) or CF Pages Function.
- Delete `web/app/api/` entirely. Delete `web/lib/admin-auth.ts`, `web/lib/api-auth.ts`, `web/lib/error-store.ts`, `web/lib/rate-limit.ts`, `web/lib/oddsKeys.ts`. Verify no client imports leak.
- Admin dashboard (`app/admin/page.tsx`, 3400 lines) is the biggest single sub-task. Migrates to signed-message auth + direct validator calls.

**Stage 4 — Permanent static export (1-2h)**
- Collapse `next.config.js` + `next.config.ipfs.js` into one with `output:"export"` always on. Delete `NEXT_BUILD_TARGET=ipfs` branch and server `headers()`. Delete `scripts/build-ipfs.sh` and `scripts/indexeddb-stub.js` (verify indexedDB stub not needed post-cleanup).
- `package.json`: `"build": "next build"`, drop `build:ipfs`.
- Run `next build`; fix breakage. Typical gotchas: `dynamic = "force-dynamic"`, `export const revalidate`, `next/headers` imports, `cookies()` in components.

**Stage 5 — Cloudflare Pages deploy + cutover (2-4h)**
- CF Pages project; build `pnpm --filter djinn-web build`, output `.next-ipfs` or `out/` (verify Next 14 behavior with `distDir`).
- Wire `NEXT_PUBLIC_*` envs in Pages dashboard.
- Add `_headers`, `_redirects`, `functions/_middleware.ts`.
- Parallel: pin `.next-ipfs/` to IPFS, record CID, optionally set ENS content hash for `djinn.eth`.
- CNAME cutover: `djinn.gg` + `www.djinn.gg` → CF Pages. Keep `*.djinn.gg` wildcard router (validators unchanged).
- Validate with `npm run test:live` Playwright pointed at new origin.
- Vercel teardown: delete project, remove Vercel envs from any CI.

## 7. Risks & Workarounds

- **ISR / on-demand revalidation:** none in use — zero `revalidate` in pages except `/api/network/status` (deleted). OK.
- **Webhook routes:** none present.
- **OG image generation (`/opengraph-image.tsx`):** check; pre-generate at build or drop.
- **`dynamic = "force-dynamic"`** in any page: blocks export. Grep before Stage 4.
- **Metagraph discovery from browser:** `lib/bt-metagraph.ts` uses substrate RPC. Works in theory; CORS on public substrate endpoints is inconsistent. Prefer `/v1/discover` on validators (ship first).
- **Admin dashboard:** biggest Stage 3 work. Post-migration: signed-message auth + direct validator calls.
- **`next.config.ipfs.js` indexedDB stub:** keep if any route imports client code during SSR/RSC boundaries; harmless.
- **WalletConnect project id:** must exist at build time or wagmi throws at runtime.
- **Trailing-slash drift:** `trailingSlash:true` means `/idiot` redirects `/idiot/`. `_redirects` tolerance required; verify `<Link>` usage.

## 8. Estimate

| Stage | Hours |
|---|---|
| 0 — inventory/plan | 0.5 |
| 1 — dynamic routes | 4-6 |
| 2 — middleware replacement | 2-3 |
| 3 — API-route deletion + client migration | 20-30 (admin is most) |
| 4 — permanent export config | 1-2 |
| 5 — CF Pages deploy + cutover | 2-4 |
| **Total** | **30-45 engineering hours** |

Prior "1-2 week" estimate is correct if admin migration is included. If admin stays on a gated path (CF Access + thin Pages Function), trim ~15h off Stage 3 → **3-5 days of focused work**. Key accelerator: validators must expose `/v1/discover`, `/v1/odds`, `/v1/delegates`, `/v1/network/matrix`, `/v1/report-error` *before* Stage 3 starts.

## 9. Critical Files
- `web/next.config.ipfs.js`
- `web/scripts/build-ipfs.sh`
- `web/middleware.ts`
- `web/app/admin/page.tsx` (biggest migration target)
- `web/lib/validatorHostnames.ts`
- `web/lib/bt-metagraph.ts`

## 10. Sprint A scope extensions identified here
- Add `/v1/delegates` (Taostats) to validator endpoint list.
- Add `/v1/network/matrix` (currently Next API, must move).
- Add `/v1/report-error` (lightweight, any validator can accept client errors).
- Add `/v1/discover` (drop-in for client-side substrate RPC).

These are all additive to Sprint A's Stage A-1 and push the endpoint count from 4 → 8.
