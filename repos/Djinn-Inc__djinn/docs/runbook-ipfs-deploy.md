# IPFS Static Client Deploy Runbook

This document tracks the migration of the Djinn web client from server-rendered Next.js (Vercel) to a fully static bundle that ships from IPFS. The endgame is a client that runs purely in the browser, with no Djinn-operated server in the data path.

## Why

Right now `djinn.gg` is a Next.js app on Vercel. If Vercel suspends the account, the app dies. If Djinn-Inc disappears, the app dies. The on-chain protocol survives both, but the human-readable interface to it is gone. IPFS hosting fixes this: the bundle is content-addressed, anyone can pin it, anyone can serve it, and the bundle's hash is verifiable.

Pair with ENS for a friendly name (`djinn.eth`) and the protocol is end-to-end ungovernable: contracts on Base, validators on SN103, client served from IPFS via ENS, no Djinn-Inc in any path.

## Current state

Building with `bash web/scripts/build-ipfs.sh` runs the static export. The build script:

1. Stashes `app/api/` (server-only routes that can't be statically generated)
2. Stashes `app/idiot/signal/[id]/`, `app/genius/signal/[id]/`, `app/network/validator/[uid]/`, `app/network/miner/[uid]/` (dynamic routes that need migration)
3. Runs `next build` with `NEXT_BUILD_TARGET=ipfs` (sets `output: "export"`)
4. Restores all stashed directories on exit (success or failure)

After the static-mode dynamic routes are stashed, the build progresses past route compilation but hits the next blocker.

## Known blockers (in order)

### 1. ✅ FIXED: api/* routes can't statically generate

Server-only by design. Workaround: stash during build, restore after. Done.

### 2. ✅ FIXED: dynamic page routes need generateStaticParams

Stashing the dirs during build is the temporary fix. The real fix is to convert them to client-side query-string routing (`/idiot/signal?id=X` instead of `/idiot/signal/X`). Each conversion is a focused PR.

### 3. CURRENT BLOCKER: indexedDB at module-import time

`wagmi` and `walletconnect` import IndexedDB at the top of the module to persist wallet connection state. During Next.js static prerender, the page is rendered in Node.js where IndexedDB doesn't exist. The build fails with `ReferenceError: indexedDB is not defined`.

**Fix paths:**

- **Lazy-load wallet code.** Move all wagmi/walletconnect imports into `useEffect` or dynamic `import()` calls so they only run in the browser. The wallet provider context becomes a client-only component that only renders after hydration. Cleanest fix; non-trivial refactor.

- **Build-time polyfill.** Add a webpack alias that maps `indexedDB` to a no-op stub during the static build. The page renders empty wallet state, then hydrates client-side. Less invasive but feels hacky.

- **Mark every wallet-using page as `dynamic = "force-dynamic"`.** This keeps the page in client-only mode even in static export. Works only if Next.js export honors the directive (it doesn't always).

### 4. UPCOMING: replace api/ proxy calls with direct validator calls

After the build runs, every page that previously called `/api/idiot/browse` etc. will fail at runtime in the browser (no api/ exists in the static bundle). Each call needs to be replaced with a direct validator call via `resolveValidatorBaseUrl(uid)` from `web/lib/validatorHostnames.ts`.

The validator hostnames are:
- `https://v0.djinn.gg` for UID 0 (live, configured)
- `https://v<uid>.djinn.gg` for any other UID (pattern-based, requires operator to set up nginx + Let's Encrypt per `runbook-validator-https.md`)
- Operator override via `/health.public_hostname` if a validator advertises its own domain

### 5. UPCOMING: middleware

`middleware.ts` runs on the Vercel edge. Static export doesn't support middleware. Anything middleware does (CSP headers, auth checks, redirects) needs an alternative: meta tags in HTML for CSP, client-side auth in React, server-rendered redirects don't apply.

### 6. UPCOMING: NEXT_PUBLIC_GIT_VERSION at runtime

The current build embeds the git commit count + hash via `execSync` at build time. That works for IPFS too — the version is baked into the bundle. No change needed.

## Verification path

When the static build succeeds:

1. `out/` directory exists with `index.html` and `_next/static/...` assets
2. Total size should be < 5 MB (typical for a Next.js app of this size)
3. Open `out/index.html` directly in a browser (`file://...`) — most pages should at least render their shell, even if the data calls fail
4. Pin to IPFS: `ipfs add -r out`
5. Note the resulting CID
6. Test via gateway: `https://ipfs.io/ipfs/<CID>/`
7. (Eventually) update ENS pointer: `djinn.eth` → `ipfs://<CID>`

## Acceptance criteria for the IPFS deploy task

- [ ] `bash web/scripts/build-ipfs.sh` exits 0 with `out/` populated
- [ ] Static `out/` opens in a browser and the homepage renders
- [ ] At least one full user flow (browse signals → see detail) works against a real validator over HTTPS
- [ ] `ipfs add -r out` produces a CID that loads via a public gateway
- [ ] All blockers above either fixed or documented as "fine to ship without"

## Status (2026-04-11)

- Build script done, blocker #1 (api/) and #2 (dynamic routes) fixed via stash
- Blocker #3 (indexedDB) is the next stop — open
- Blockers #4 (api/ replacements) and #5 (middleware) are next after #3
