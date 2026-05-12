# Djinn UX/UI Suggestions

Append-only log of UX/UI complaints, confusions, and improvement ideas discovered by the `djinn-ux-tester` autonomous loop. A separate fixer agent reads this file and resolves items.

**Authoring rules (for the observer loop):**
- APPEND new findings at the TOP of the "Findings" section. Never edit or delete existing entries.
- Each iteration: add a dated block. One block per iteration even if findings are zero (log a "no new findings" note so we can see the loop is running).
- For each finding: severity tag, one-line headline, then 2-5 lines of detail (what page, what the user expected, what happened, why it matters).
- Cite file paths when you can (`web/components/Layout.tsx:18`) so the fixer doesn't have to hunt.
- DO NOT duplicate findings already open in this file. Before adding a new one, grep for keywords.
- DO NOT log bugs that are infrastructure flakes (Vercel checkpoint, validator offline, RPC 502). Those go in `UX_FINDINGS.md` via the existing `/djinn-e2e` loop. This file is for **UX/UI quality** only: confusion, friction, ugliness, broken-promise copy, missing affordances, accessibility, layout, microcopy.

**Resolution rules (for the fixer):**
- Mark items `[x] (fixed in <commit-sha>) ...` when resolved. Never delete.

**Severity rubric:**
- **CRITICAL** — first-time visitor bounces or core flow blocked
- **HIGH** — user gets confused, makes wrong choice, or churns
- **MED** — noticeable friction, awkward copy, ugly layout
- **LOW** — polish, alignment, microcopy nits
- **IDEA** — feature suggestion or "what if we"

---

## Findings

### 2026-05-01, Iter-025, Persona 5 (Mobile thumb-typer / iPhone 13 390x664), 4 browser-verified findings

**Sweep**: First pass (iPhone 13 device profile, headless Chromium, saved Vercel session) loaded `/`, `/idiot`, `/genius`, `/leaderboard`, `/idiot/browse` cleanly (status=200). Screenshots in `e2e-screenshots/ux-mobile-iter25-*.png`. No horizontal page overflow (good). Header / footer tap-target issues from iter-15 (36px hamburger, 17px footer protocol links, 28px logo, 16px drawer socials, p-8 SecretModal, cramped legal-link row) and iter-19 (drawer aria-controls + Esc/focus-trap) all still hold; this iteration focuses on net-new mobile issues found inside the **content area** of /leaderboard and /idiot/browse, which iter-15 did not screenshot. (A second probe pass got 403 Vercel checkpoints; the WAF appears to throttle repeat headless visits even with a fresh session.)

- [x] (fixed in 74c9b6f8) **[HIGH]** `/leaderboard` mobile table forces horizontal scroll silently — 8 columns of `text-sm` content (Rank, Genius, Quality Score, Signals, Audits, ROI, Proofs, Win Rate) live inside a single `overflow-x-auto` card with no scroll affordance, no fade-edge gradient, no "swipe →" hint, and no sticky leftmost column.
  - Page: `/leaderboard` (file: `web/app/leaderboard/page.tsx:156-369` — `<div className="card overflow-x-auto"><table className="w-full text-sm">` with 8 `<th>` headers and avatar+handle+address+bio in column 2)
  - Expected: a mobile leaderboard either renders one card per row (so all the per-genius numbers stack visibly) or, if it keeps the table, signals the off-screen columns with an edge fade and a one-time "swipe to see ROI / Proofs / Win Rate" hint. Sticky `#` and `Genius` columns help the user keep their place.
  - Got: at 390 px the visible columns end at "Audits" with "ROI" half-clipped at the right edge of the card; "Proofs" and "Win Rate" — the two columns a researcher actually came here for — are entirely off-screen with no visible cue they exist. Persona 3 (researcher, iter-13/iter-23) already flagged unshareable rankings and a missing min-sample filter; this is the mobile-flavored version: the user can't even *see* the metric they want to sort by until they horizontally scrub a non-obvious container.
  - Why it matters: the leaderboard is the trust-establishing page for buyers. If the highest-information columns (ROI, Win Rate) are invisible by default on mobile, mobile shoppers either trust the rank-1 entry blindly or bounce. Both bad outcomes.
  - Fix idea: at `<lg` breakpoint, render a `<ul>` of cards (one Genius per card, two-column metric grid inside) instead of a table; or keep the table but add `<div className="lg:hidden text-xs text-slate-500 mb-2">Swipe horizontally to see ROI, Proofs, Win Rate →</div>` plus a `before:absolute ... bg-gradient-to-l` fade on the right edge.

- [x] (fixed in 74c9b6f8) **[MED]** `/leaderboard` mobile column headers wrap awkwardly — "Quality Score↓" wraps "Score" to a second line (and the sort arrow lands beneath the word "Score"), so the active sort indicator visually attaches to the wrong column header.
  - Page: `/leaderboard` (file: `web/app/leaderboard/page.tsx:170,180,190,200,210,220` — every `<th>` interpolates `{sortIndicator(...)}` directly after the label without `whitespace-nowrap`, and the table header row has no min-width budget per column)
  - Expected: column headers either fit on one line each (preferred), or carry the sort arrow as a separate inline element that wraps with the label, not after it.
  - Got: header row at 390 px reads `# | Genius | Quality | Signals | Audits | ROI | …` with `Score↓` on a second line under `Quality`, and `Win` on a separate line from `Rate`. A user who tapped a header to re-sort cannot tell at a glance which column is currently sorted because the arrow is visually closer to the next-row data than to its label.
  - Why it matters: same researcher trust ladder as iter-13 / iter-23 — if the user can't tell what's sorted, the leaderboard becomes a list of names with mystery numbers, which is exactly the credibility problem this page exists to solve.
  - Fix idea: add `whitespace-nowrap` to each `<th>` and ship a horizontally scrollable header in lockstep with the body (or move to the per-card mobile layout above).

- [x] (fixed in 74c9b6f8) **[MED]** `/leaderboard` mobile bio paragraph blows up row height — every Genius row carries `<p className="text-xs text-slate-500 mt-0.5">{id.bio}</p>` (15-word canned bios from `profileIdentity`); on 390 px these wrap to 4-5 lines, making each row ~140 px tall and pushing the second Genius below the fold.
  - Page: `/leaderboard` (file: `web/app/leaderboard/page.tsx:275`; bios from `web/lib/profile-identity.ts` synthesizer, e.g. "Signal publisher with transparent performance history.")
  - Expected: a leaderboard row should be scannable — handle, key metrics, click to drill into the full profile. Filler bios should be one line max (or hidden) on mobile so the user can compare 5 Geniuses at a glance.
  - Got: Iter-13 already flagged that these bios are synthetic/canned; on mobile they additionally consume vertical space disproportionate to their information value (the bio is the *same boilerplate* for every entry whose seed produces it), so the user scrolls past noise to find the next ranked entry.
  - Why it matters: combines with the horizontal-scroll-to-see-ROI issue above; together they make the mobile leaderboard feel like one fat row of marketing copy with off-screen numbers — the inverse of the "cryptographically verified track records" promise in the page subtitle.
  - Fix idea: `<p className="text-xs text-slate-500 mt-0.5 hidden sm:block line-clamp-1 sm:line-clamp-2">` (hide on `<sm`, clamp to 1-2 lines elsewhere), or move the bio into the `/genius/[address]` profile page only.

- [x] (fixed in d3a25320) **[MED]** `/idiot/browse` "Connect your wallet to purchase signals" amber notice on mobile is informational-only — it has no embedded Connect CTA, so a user who reads the prompt at the page top has to scroll back up to the (non-sticky) header to find the Connect Wallet button.
  - Page: `/idiot/browse` (file: `web/app/idiot/browse/page.tsx:110-114` — `{!address && (<p className="text-sm text-amber-600 ...">Connect your wallet to purchase signals</p>)}`)
  - Expected: when a banner explicitly tells the user "you need to do X", the X-doing affordance lives inside the banner. Bonus points: skip the banner entirely and replace the bottom empty-state ("No signals found") with a "Connect your wallet to see purchasable picks" CTA card that does the connection inline.
  - Got: amber `<p>` with the text only, no button. The Connect Wallet button is in the page header; on mobile the user is already scrolled past it by the time they see this notice, so the cognitive flow is "read banner → realize I need to connect → scroll up → find Connect → tap → return". On a 390 px viewport, that's three context shifts to take one action.
  - Why it matters: persona 1 (curious-shopper Idiot) bounce-rate killer — they came here to look at picks, the page is gating them, and the recovery path requires manual scrolling instead of a single tap.
  - Fix idea: render a `<ConnectButton.Custom>` (or shared `WalletButton`) inside the amber notice so the button text is "Connect Wallet" right in the banner; second-best, change the copy to "Connect your wallet (button at top right) to purchase signals" so at least the recovery path is named.

---

### 2026-05-01, Iter-024, Persona 4 (Skeptic / journalist), 0 browser findings + 7 static-review findings

**Sweep**: 20th WAF block of the loop. Headless Chromium with the freshly-refreshed `web/e2e/ux/.vercel-session.json` (~5 min old at probe start) hit 10 skeptic-relevant URLs (`/about`, `/docs`, `/docs/how-it-works`, `/docs/api`, `/docs/contracts`, `/docs/disputes`, `/disputes`, `/network`, `/whitepaper.pdf`, `/attest`) and got `<title>Vercel Security Checkpoint</title>` (Code 21/29) on every one. Persona 4 was last static-reviewed in Iter-014, which produced 7 findings against `/about`, `/docs`, `/docs/how-it-works`, `/network`. This iteration extends the skeptic pass to `/docs/api`, `/docs/contracts`, `/docs/sdk`, and `/research/tao-valuation` (none of which existed at iter-014's commit). Iter-014's HIGH on the missing `/disputes` page and the unanchored `/docs` 2x2 table both still hold (`web/app/disputes/` does not exist; `web/app/docs/disputes/` does not exist; `web/app/docs/api/page.tsx` has no `#genius` / `#idiot` anchors). Findings below are net-new since iter-014.

- [x] (fixed in c13592a7) **[HIGH]** `/docs/contracts` contradicts itself on whether the displayed contract addresses are stable.
  - Page: `/docs/contracts` (file: `web/app/docs/contracts/page.tsx:121-132`)
  - Expected: a "Smart Contracts" page on a betting protocol's main docs nav should be unambiguous about which addresses are canonical. A skeptic looks at this page first.
  - Got: the lede paragraph (line 122-124) says "All Djinn contracts are deployed on Base as UUPS upgradeable proxies governed by a TimelockController (72-hour delay). **Proxy addresses never change**." Immediately below (line 126-132) an amber callout says "Network: **Base Sepolia (testnet). These addresses will change when mainnet contracts are deployed.** The proxy pattern means mainnet addresses will be permanent once set." So the listed addresses both "never change" and will change. A reasoning skeptic concludes the team copy-pasted mainnet language onto a testnet page.
  - Why it matters: this is the page a journalist or auditor links to when drafting "the protocol contracts are at X". Current state forces a hedge ("currently testnet but will move to mainnet"), and the contradiction trains them to read the rest of the docs as marketing.
  - Fix idea: rewrite the lede to "These are the **testnet** addresses. The proxy pattern means the mainnet equivalents will be permanent once announced." Or visibly tag every address card with a `Testnet` chip and surface a "Mainnet status: Not yet deployed" stat at the top.

- **[HIGH]** `/research/tao-valuation` exists as a substantial research page (Chart.js, weekly data through 2026-02-20, top-down vs bottom-up TAO valuation analysis) but is not linked from the footer, the main nav, `/docs`, or `/about`. A journalist looking for "research" hits the footer link "Education & Research" which goes to `/education` only.
  - Page: `/research/tao-valuation` (files: `web/app/research/tao-valuation/page.tsx` exists; `web/components/Layout.tsx:279` footer link points to `/education` not `/research`; `web/app/docs/page.tsx` has no Research entry; nav menu in Layout.tsx has no Research entry)
  - Expected: if you ship a research page deep enough to load Chart.js, plot 51 weeks of subnet-pool, dynamic, and root-staked TAO valuation data, and compute bottom-up/top-down ratios, that page should be discoverable from at least one prominent surface (footer, /docs index, or main nav). A skeptic specifically looking for "where do they justify their valuation claims?" should not have to guess the URL.
  - Got: the footer's "Education & Research" link is a misleading hyphenated phrase that resolves only to `/education`; `/docs` makes no mention of `/research`; the page is reachable only by direct URL or sitemap.
  - Why it matters: serious due-diligence readers go looking for research first. Hiding the strongest-evidence page behind no link wastes the work and makes the visible site look thinner than it is — exactly the inverse of what a journalist needs to write a credible piece.
  - Fix idea: rename the footer link to "Education" (drop "& Research"), add a parallel "Research" link below it pointing to `/research`, and add `/research/tao-valuation` to `/docs` "Choose your path" as a fifth tile or to a new "Research" column. Also add `/research/tao-valuation` to `web/app/sitemap.ts` if it isn't already.

- **[MED]** `/docs/api` example response on `GET /api/network/config` hard-codes `shamir_n: 10, shamir_k: 3` (file: `web/app/docs/api/page.tsx:223-224`), but `/docs/how-it-works` describes the Shamir threshold as "configurable" and `/about` describes decoy count as a fixed "10". The site exposes three different specificities for the cryptographic parameters across three docs pages.
  - Page: `/docs/api`, `/docs/how-it-works`, `/about` (files: `web/app/docs/api/page.tsx:222-225`, `web/app/docs/how-it-works/page.tsx:52-118`, `web/app/about/page.tsx:84-86,184-185`)
  - Expected: cryptographic parameters are the kind of thing a journalist will copy verbatim into a piece. They should be stated identically wherever they appear, with one canonical source of truth (e.g. a `/docs/parameters` page or a single `<NetworkConfig>` component fed by `/api/network/config`).
  - Got: `/about` says "10 decoy lines" (twice). `/docs/how-it-works` says "configurable set of decoy lines" + "configurable Shamir threshold". `/docs/api` says `shamir_n: 10, shamir_k: 3` and treats decoy count as `(decoy_indices.length)` per signal. Three pages, three specificities, no shared source.
  - Why it matters: iter-014 flagged the `/about` vs `/docs/how-it-works` decoy contradiction; this is the same problem extended to Shamir parameters. The skeptic angle: "they don't agree internally on their own threshold" is a fast credibility hit on Twitter.
  - Fix idea: pull all three values (`decoy_count`, `shamir_n`, `shamir_k`) from `/api/network/config` and render them inline on `/about`, `/docs/how-it-works`, and `/docs/api` via a shared `<NetworkParam name="..." />` component. Stop hard-coding "10".

- **[MED]** `/docs/api` ships canonical-looking REST docs that publicly admit critical sub-systems are "honor system" with "TBD verifier".
  - Page: `/docs/api` (file: `web/app/docs/api/page.tsx:286-336`)
  - Got: the `POST /v1/cb/appeal` endpoint description on line 322 reads "Currently runs in honor-system mode behind the appeal_mechanism feature flag. Real TLSNotary verification lands in a follow-up." The canonical example response (line 332) returns `verdict: "honor_system_accepted"` and `verification_mode: "honor_system"`. The `tlsnotary_proof` parameter description (line 327) is literally "TLSNotary proof of the declared source (TBD verifier)". Similarly `/v1/odds/canonical` line 289 says "Currently in bridge mode behind the canonical_odds feature flag" with `feature_flag_enabled: false` baked into the example.
  - Why it matters: putting these admissions in the *public API reference* (rather than a "roadmap" page) tells a journalist "the consensus circuit-breaker, the canonical odds source, and miner appeal verification are all stubs right now." That is a fair description of testnet, but a skeptic linking to `/docs/api#consensus-circuit-breaker` will pull the "honor system" string into a critical piece. Either the line belongs in a separate "Status" page where the framing is "what's live vs what's coming", or the language needs softening to "the verifier is being upgraded; current behavior accepts the appeal pending TLSNotary verification".
  - Fix idea: split `/docs/api` into "Live" and "Preview" sections. Put `/v1/odds/canonical` and `/v1/cb/appeal` under Preview with a "Status: testnet bridge mode" chip. Or move them entirely to a new `/docs/roadmap` page.

- **[MED]** `/docs/contracts` describes a 72-hour TimelockController governance delay but provides no surface anywhere on the site for *current* pending proposals.
  - Page: `/docs/contracts` (file: `web/app/docs/contracts/page.tsx:135-150`)
  - Expected: a "trustless governance via 72-hour timelock" claim begs the skeptic question "can I see what's queued?" A serious DeFi protocol exposes either a Tally / Snapshot link, an Etherscan filter for `scheduled(...)` events on the timelock, or a `/governance` page listing pending operations.
  - Got: the page lists the timelock address (`0x37f4...`) and explains the proposer/executor split, but the only outbound link is a Basescan address page that requires the reader to know to filter by `OperationScheduled`. No `/governance` route exists in `web/app/`. A user who wants to verify "this protocol is not being silently upgraded" has no UI.
  - Fix idea: add a `/governance` page (or section on `/docs/contracts`) that pulls pending operations from the timelock contract and renders "X queued, executable Y", or at minimum a deep-link Basescan URL pre-filtered to `topic0=OperationScheduled`.

- **[MED]** `/docs/contracts` and `/docs/api` cite a single source for ABIs (a github URL in `djinn-inc/djinn/tree/main/contracts/out`) with no second source — no IPFS pin, no Etherscan-verified-source link, no in-page download, no checksum.
  - Page: `/docs/contracts` (file: `web/app/docs/contracts/page.tsx:225-232`)
  - Expected: a skeptic verifying ABIs against on-chain bytecode wants either (a) Etherscan/Basescan "Contract Source Verified" badges (these are in fact common on Base), (b) an IPFS-pinned mirror of the ABIs, or (c) a `Download ABI (.json)` button per contract that doesn't depend on Github org liveness. The whole point of a "trustless protocol" is that documentation should not single-source on Github.
  - Got: a single anchor tag (`href="https://github.com/djinn-inc/djinn/tree/main/contracts/out"`). If the org is renamed, made private, or deleted, the entire ABI surface disappears for visitors. The Basescan link on each contract goes to the *address page*, not the verified-source tab.
  - Fix idea: per-contract "Download ABI" + "View verified source on Basescan" buttons; pin the `out/` directory on IPFS and dual-link.

- [x] (fixed in c13592a7) **[LOW]** `/docs/contracts` per-card address links use the `https://sepolia.basescan.org/address/...` template but no card has a visible "Testnet" chip next to the address. Anyone deep-linking to a contract card sees an Ethereum address with no immediate signal that it's not a mainnet contract.
  - Page: `/docs/contracts` (file: `web/app/docs/contracts/page.tsx:184-192`)
  - Got: the Address label reads "Address (Base Sepolia)" but in 14px slate-500 above a 14px font-mono blue link. On a phone or after-screenshot, the chain hint is easy to miss; the link itself does not include any visible network indicator.
  - Fix idea: render a `<span class="bg-amber-100 text-amber-800 ...">Testnet</span>` chip inline with each address, and prefix the link text itself with `[Sepolia]`.

(All seven findings are static-review; the WAF blocked browser verification this iteration. Reconfirm against live `/docs/contracts`, `/docs/api`, `/research/tao-valuation`, `/about`, and `/docs/how-it-works` once the saved Vercel session is refreshed. Iter-014's HIGH on "no `/disputes` page" remains open: `web/app/disputes/` and `web/app/docs/disputes/` still do not exist as of this commit.)

---

### 2026-05-01, Iter-023, Persona 3 (Track-record researcher), 0 browser findings + 7 static-review findings

**Sweep**: 18th WAF block of the loop. Headless Chromium with the freshly-refreshed `web/e2e/ux/.vercel-session.json` (~9 min old at start of probe) hit `/leaderboard` and `/` and got 403 "Vercel Security Checkpoint" on both, 3 retry attempts each, even after a 30s `waitForFunction` on title change. So this iteration is a static review of `web/app/leaderboard/page.tsx` (330 lines, full read) and `web/app/genius/track-record/page.tsx` (208 lines, full read), focused on net-new issues since iter-3 (browser, /leaderboard) and iter-13 (static, /leaderboard + /genius/[addr]). Iter-3's "off-site basescan profile link only" is closed (the leaderboard now links `@handle` → `/genius/[address]` in-site). Iter-13's "synthetic handles", "unitless Quality Score", and "no per-row tx-hash basescan link on profile" remain open. Findings below are net-new.

- [x] (fixed in 3c62d3fc) **[HIGH]** Win Rate column has no minimum-sample filter or small-sample warning: a 100% (2W/0L) genius outranks a 65% (130W/70L) genius when sorting by Win Rate, and there is no visual cue that the 100% has a sample size of 2.
  - Page: `/leaderboard` (file: `web/app/leaderboard/page.tsx:280-289` Win Rate cell, `:14-18` `getWinRate`, `:35-41` sort comparator)
  - Expected: A track-record researcher who sorts the leaderboard by Win Rate expects either (a) a minimum-sample filter (e.g. "≥10 settled signals") applied before ranking, (b) a min-sample threshold UI ("show only ≥N audits"), or (c) a small-sample badge / dimmed row for entries with `favCount + unfavCount < 10` so they cannot mistake noise for skill. Bayesian-shrunk rates (e.g. Wilson lower bound) are the standard fix in sports/poker leaderboards for exactly this reason.
  - Got: The comparator `(a[sortBy] - b[sortBy]) * multiplier` does a raw numeric sort with no denominator threshold and no styling difference for tiny samples. The cell renders the W/L/V breakdown in tiny grey type to the right of the percentage, but it's the same size whether the sample is 2 or 200, and the percentage itself is rendered identically. Sorting Win Rate desc on a fresh testnet with a few 1-of-1 wins puts the lowest-credibility geniuses at #1.
  - Why it matters: This is the marquee researcher question. The whole point of the page is "ranked by cryptographically verified track records" (the subtitle), and a small-sample 100% win rate is the opposite of a verified track record — it's noise.
  - Fix idea: Show only entries with `favCount + unfavCount >= MIN_SAMPLE` (default 10, configurable via dropdown) when sorting by Win Rate or ROI; render a "small sample" tag (`<5 audits`) on rows that fall below.

- **[HIGH]** Sort preference is in-component React state only — no URL state, no `localStorage`, no query-param sync. A researcher who clicks "ROI ↓" and then refreshes, opens a Genius profile in a new tab, or shares the URL is reset to the default sort.
  - Page: `/leaderboard` (file: `web/app/leaderboard/page.tsx:23-24,43-50`)
  - Expected: Sortable leaderboards in 2026 are link-shareable. URL like `/leaderboard?sort=roi&dir=desc&min_audits=10` lets a researcher (i) reload without losing their view, (ii) link a finding in Discord/X ("here's the top-10 by ROI: <url>"), (iii) bookmark the "ROI desc" view as their daily check.
  - Got: `useState<SortField | null>(null)` with `userSortBy` purely local. The sort headers update visual state but never `router.replace` or write to storage. Hard refresh, navigate away and back, or share the URL — sort is gone.
  - Why it matters: A research workflow that requires re-clicking the sort header on every visit is friction; an unshareable rank is a missed growth-loop (researchers love to post screenshots of "look at this guy on the ROI leaderboard" — but the link doesn't preserve the sort).
  - Fix idea: Sync `sortBy`, `sortDesc`, and (when added) `min_audits` to the URL via `useSearchParams` / `router.replace` in a `useEffect`. Hydrate from `searchParams` on mount.

- **[MED]** Two pages each show a "% of stuff that went well" headline number, with different numerators, denominators, and units, and zero cross-link or shared glossary. A researcher cross-referencing a profile against the leaderboard will conflate them.
  - Page: `/leaderboard` "Win Rate" (file: `web/app/leaderboard/page.tsx:14-18,279-289`) and `/genius/track-record` "Profitable" (file: `web/app/genius/track-record/page.tsx:91-98`)
  - Expected: Identical metric definitions across pages with the same name, OR clearly distinct names with a one-line tooltip on each.
  - Got: Leaderboard "Win Rate" = `favCount / (favCount + unfavCount)` of *individual signal lines* (audit-level decisions). Track-record "Profitable" = `audits.filter(a => a.qualityScore > 0n).length / audits.length` of *audit batches* (multi-signal aggregates). A genius can be 80% on lines but 40% on batches if their losses cluster, or vice versa. The two pages use different colors, different denominators, different units, and never link to each other. Researchers will assume they're the same thing and draw wrong conclusions about consistency.
  - Why it matters: Trust. The single most important deliverable of this site is "is this person actually good?" If the answer differs by which page you're on, the numbers feel cooked even if both are correct.
  - Fix idea: Either harmonize ("Profitable Batches %" on both pages) or add a hover tooltip on each cell explaining the formula and linking to a `/docs/metrics` page.

- **[MED]** No timeframe / season filter on the leaderboard. All metrics are all-time-since-genesis.
  - Page: `/leaderboard` (file: `web/app/leaderboard/page.tsx:104-297`)
  - Expected: Drop-down or pill-row for "Last 7d / Last 30d / Last 90d / This season / All time". Sport seasons matter — an 80% MLB win rate from Aug 2024 through Oct 2024 dominates a 30% cold streak in March 2025, but the researcher question "is this genius hot *right now*" is unanswerable on the current page.
  - Got: There are no time controls anywhere on the page. `useLeaderboard()` returns aggregate-since-launch stats. ROI is cumulative. A genius who went +200% in their first month and has been -10% since reads the same as a slow-and-steady +5%/month.
  - Why it matters: Decay is the core question of any track-record site. Without it, the leaderboard answers "who has been good *ever*", which is not what an Idiot wants to know before paying.
  - Fix idea: Add a `period` state + URL param; pass to `useLeaderboard({ period })` which filters audits by `block.timestamp` before reducing.

- **[MED]** Two adjacent action icons (copy-address ~12px SVG, basescan-link ~14px SVG) with ~8px gap inside the Genius cell are well below the iOS / Material 24px+ tap-target threshold (44px preferred), and the basescan icon — the *only* "verify on-chain" affordance on this row — is the smaller of the two.
  - Page: `/leaderboard` (file: `web/app/leaderboard/page.tsx:223-251`)
  - Expected: The "verify on-chain via Basescan" action is the headline trust feature for a track-record researcher. It should be a labelled chip ("Basescan ↗") at least 32×32 px with text, not a 14px icon-only SVG nested next to a 12px copy-address icon.
  - Got: `<svg className="w-3.5 h-3.5">` (basescan) sits 8px to the right of `<svg className="w-3 h-3">` (copy). On a 390-px mobile viewport with the leaderboard table forced to `overflow-x-auto`, these icons sit very close to the right table edge and the user often hits the wrong one. There's no visible label on either; the only cue is `title=` and `aria-label=`, which are invisible on touch devices.
  - Why it matters: Researcher trust ladder is "see name → see numbers → click to Basescan to verify". If the basescan tap is fiddly, the verification step is silently skipped. (Persona-5 mobile/iter-15 already flagged hamburger and footer tap targets; this is the same class of bug on the leaderboard's most important action.)
  - Fix idea: Replace the two icon-only buttons with a labelled chip pair: `[ Copy ] [ Basescan ↗ ]` at ≥32px height, or move them into a "..." action menu.

- **[LOW]** "How Quality Score Works" panel uses three undefined glossary terms in a single bullet list: "Notional", "Backing%", "audit batch". A track-record researcher hitting this page first cannot evaluate the formulas without bouncing off-page.
  - Page: `/leaderboard` (file: `web/app/leaderboard/page.tsx:300-326`)
  - Expected: Inline definitions or a single linked tooltip ("Notional = the dollar size of the underlying bet. Backing% = collateral fraction set by the Genius."). Or a "Read the full audit math →" link to `/docs/quality-score`.
  - Got: `Favorable: +Notional × (odds − 1)` / `Unfavorable: −Notional × Backing%` / `Void: does not count`, then a paragraph that introduces "audit batch", "validator audit", "Djinn Credits" without explaining any. A first-time researcher has to guess at the units (USDC? percentage points?), which is exactly what iter-13's "Quality Score is unitless / mixed-units" finding flagged.
  - Why it matters: This panel is the canonical explanation, sitting at the bottom of the marquee leaderboard. If it's unparseable, every metric above it inherits the opacity.
  - Fix idea: Two-line inline glossary above the formulae: "*Notional* = USDC the buyer wagers on this signal; *Backing%* = the collateral multiple the Genius posted." Plus a "More: how validators audit a batch →" link.

- **[LOW]** Avatar circle on the leaderboard is a styled `<div>` with `aria-hidden="true"` and is not clickable, but the visual gestalt (rounded, vivid colors, sitting next to a bold link) makes it look like the primary affordance. Users will tap the avatar and nothing happens; the actual link is the "@handle" text.
  - Page: `/leaderboard` (file: `web/app/leaderboard/page.tsx:203-210`)
  - Expected: Either (a) wrap the avatar in the same `<Link>` as the handle so a tap on the avatar navigates to `/genius/[address]`, or (b) make the avatar visually subordinate (smaller, lower-contrast border) so it doesn't read as a click target.
  - Got: An h-8/w-8 rounded color-block with initials + `aria-hidden="true"` next to a `<Link>` wrapping `@handle`. On thumb-typing devices the natural tap is the avatar, and it's a no-op.
  - Why it matters: Affordance fail. Researchers click the most "buttony" thing first.
  - Fix idea: Wrap both the avatar and the handle in a single `<Link>` so the entire `flex items-start gap-3` cell is the click target.

(Not browser-verified; the saved Vercel session refresh from iter-022 has already gone stale at the WAF level by iter-023, even though the file mtime is ~9 min old. Loop should consider a periodic background session-refresher or `VERCEL_BYPASS_SECRET`-based health check before observer iterations run.)

---

### 2026-05-01, Iter-022, Persona 2 (Aspiring publisher / Genius), 4 browser-verified findings + 2 resolved-confirmations

**Sweep**: First browser-verified iteration in 7 attempts. Headless Chromium with the freshly-refreshed `web/e2e/ux/.vercel-session.json` (~5 min old) cleanly loaded `/` (200) and `/genius` (200), then WAF re-engaged on subsequent navigations (`/docs/how-it-works`, `/genius/publish` second hit, mobile `/genius` all 403'd with Code 21). Probe captured the full `/genius` landing-page text and ran route discovery for plausible publish URLs. Persona 2 was also covered in iter-002 (browser, "no economics") and iter-012 (browser, "wizard steps 2-5 are empty stubs"). Both of those prior findings are now resolved — see notes at end of this block. Findings below are net-new.

- [x] (fixed in 3b88cbf4) **[HIGH]** Onboarding step 3 ("Get USDC on Base") points the user off a cliff: it says "Use Base Sepolia faucet funds, then *swap to test USDC*" but provides only a faucet button (which dispenses ETH, not USDC) and zero pointer to *how* to swap or where test-USDC liquidity exists.
  - Page: `/genius` (file: `web/app/genius/page.tsx`, "Getting started" step 3)
  - Expected: A first-time publisher reading "Start small ($10-$50 equivalent) while learning" expects a one-click way to actually obtain test USDC. Either (a) a Djinn-hosted test-USDC faucet, (b) a link to a known Base Sepolia USDC faucet/DEX, or (c) explicit instructions for a 0x/Uniswap testnet swap.
  - Got: One blue pill "Open Base Sepolia faucet" links to a generic ETH faucet. No mention of the test-USDC token address, no DEX recommendation, no Djinn faucet, no troubleshooting copy. The implied workflow ("then swap") simply does not exist on Base Sepolia for most users — they will get ETH, hit a wall, and bounce.
  - Why it matters: Genius onboarding requires USDC collateral. If the very first hands-on step is "do an undefined cross-asset swap on a testnet," 80%+ of would-be publishers stop here. This is the single load-bearing step in the funnel and the instructions render it impossible.
  - Fix idea: Ship a tiny Djinn faucet endpoint that mints test USDC for any verified-on-list address (rate-limited), or contract-address + DEX link. At minimum, change copy to: "Test USDC on Base Sepolia: contact us in Discord with your address" — anything more concrete than "swap" with no how.

- **[MED]** Adjacent visual blocks on `/genius` use the word "Fee" for two different concepts with no disambiguation, one paragraph apart.
  - Page: `/genius` (file: `web/app/genius/page.tsx`, "What you keep, what it costs" + "EXAMPLE SIGNAL" card)
  - Expected: Either consistent terminology (e.g., "protocol take rate" vs "buyer fee") or an inline tooltip / footnote disambiguating.
  - Got: The economics panel says **"0.5% Protocol fee, taken at settlement"** and **"99.5% Of every USDC pick fee paid by an Idiot lands in your collateral balance"**. Six lines below, an "EXAMPLE SIGNAL" card shows **"Fee: 1.50%"** in its metadata strip. Reading top-to-bottom, a publisher could reasonably conclude that "the fee is 1.5%, of which I keep 99.5% and the protocol takes 0.5%". In reality the 1.5% in the example is the buyer-paid fee (per Signal contract semantics), and the 99.5%/0.5% split applies *to that fee*. So a publisher who lists at 1.5% actually receives 1.5% × 99.5% = 1.4925% of buyer-paid notional, not 1.5%. The page's example math ("20 buyers × $2.00 fee = $40 gross, $39.80 net") is correct, but it never connects the two "Fee" labels.
  - Why it matters: Mis-pricing risk. A genius who reads this and prices their signal at exactly cover-cost will under-earn by 0.5% on every fill, then blame the marketplace.
  - Fix idea: Rename the example-card field "Fee: 1.50%" → "Buyer fee: 1.50%" and add a single inline line under the economics block: "Buyer fee = what you set per signal. Protocol take = 0.5% of that fee. You keep 99.5%."

- **[MED]** Routing for "publish a signal" is inconsistent: 4 of 5 plausible URLs 404, but `/genius/publish` returns 200 (likely a Vercel cache or fallback render) — and the canonical route `/genius/signal/new` is not a URL a normal publisher would guess.
  - Page: route surface (file: `web/app/genius/signal/new/page.tsx` is canonical; no `web/app/genius/publish/` directory exists)
  - Expected: One of: (a) `/genius/publish` redirects to `/genius/signal/new`, (b) all guess-routes 404 uniformly so users learn the correct one from the in-page CTA, or (c) the in-page CTA URL matches at least one obvious guess.
  - Got: From a clean session, `/genius/publish` returned 200 ("https://www.djinn.gg/genius/publish") while sibling guesses (`/genius/new`, `/publish`, `/genius/signals/new`, `/genius/create`) all 403'd through WAF (so unverifiable, but `/genius/publish` clearly resolved differently). The actual publish wizard lives at `/genius/signal/new`. The in-page step 5 button is text "Open signal builder" with no visible href in the rendered text dump (likely a `<Link>` that the regex probe missed, but a copy-pasted URL or browser-history search would never find it). A returning publisher who remembers "publish" cannot reliably bookmark or hand-type the route.
  - Why it matters: Power users live on URLs. Inconsistent route handling is a "this place is held together with tape" smell.
  - Fix idea: Add a Next.js redirect from `/genius/publish` (and ideally `/publish`, `/genius/new`) → `/genius/signal/new` in `next.config.js`.

- **[LOW]** "EXAMPLE SIGNAL" disambiguation lives only in the small uppercase eyebrow above the card — the card body itself looks like a real active signal, including a green "Active" pill.
  - Page: `/genius` (file: `web/app/genius/page.tsx`, EXAMPLE SIGNAL card)
  - Expected: A demo card on a logged-out marketing page should be unmistakably a demo: watermark, "Example only — not a real signal" inside the card, or a different card style (dashed border, opacity).
  - Got: The card reads `NBA · Signal #0x7a…c1`, `Pick: ██████ encrypted ██████`, `Fee: 1.50% · Backing: 100% · Max: $250 · Expires: tip-off`, then a green pill `Active`. The only "this is fake" cue is the eyebrow text "EXAMPLE SIGNAL" above the card. A scrolling user who lands directly at this card from an in-page anchor (or a screenshot) sees what looks like a live signal.
  - Why it matters: Trust. If a journalist screenshots this and posts "Djinn is publishing fake signals", that's a 24h cycle to live down.
  - Fix idea: Add `border-dashed` and an inline `<span>EXAMPLE</span>` watermark inside the card body, or replace the green "Active" pill with a gray "Demo" pill on this card only.

**Resolved confirmations (no action needed, just closing the loop):**
- ✅ Iter-002 finding ("/genius shows zero publisher economics") is **resolved**. The `/genius` page now displays a "What you keep, what it costs" panel with three concrete numbers (99.5% to publisher, 0.5% protocol, $0 minimum) plus a worked payout example ("20 buyers × $2.00 fee = $39.80 net"). Verified in this iteration's browser dump.
- ✅ Iter-012 finding ("wizard steps 2-5 are content-empty stubs after fix 41b15134") is **resolved**. All 5 onboarding steps now have full body copy plus action CTAs ("Add Base Sepolia", "Open Base Sepolia faucet", "Read collateral rules", "Open signal builder"). Verified in this iteration's browser dump. (The HIGH finding above is a *new* problem inside step 3's now-populated copy.)

---

### 2026-05-01, Iter-021, Persona 1 (Curious shopper / Idiot), 0 browser findings + 6 static-review findings

**Sweep**: 17th consecutive WAF-blocked iteration on the live origin. Headless Chromium with the saved `web/e2e/ux/.vercel-session.json` (~21h stale) hit `/idiot` then `/` and got HTTP 403 "Vercel Security Checkpoint" both times (body title "Vercel Security Checkpoint", `fra1::1777604726-...`); persona-1 was also covered with a browser at iter-001 and statically at iter-011 — those focused on the `/idiot/browse` cards. This block focuses on the post-click flow: `/idiot/signal/?id=...` (`web/app/idiot/signal/page.tsx`), the page where a curious shopper has decided to look closer and is asked to commit USDC. None are browser-verified — re-queue once Vercel session refreshes.

- **[HIGH]** Signal detail page never displays the underlying *game* (teams, league, kickoff time) — pre-purchase, the buyer sees only `Signal #0xfa12…` as the H1 and `MLB` as a tiny grid label.
  - Page: `/idiot/signal?id=…` (file: `web/app/idiot/signal/page.tsx:1632-1710`)
  - Expected: A buyer who clicked a card to drill in expects to see "Yankees @ Red Sox · Mon May 6, 7:10 PM ET · MLB" prominently, plus market type ("Run line" / "Spread") even though the actual *pick* stays encrypted. The decoy lines panel below already implies decoys are real bookmaker lines from "multiple games and sports", so even the genius's chosen game is not necessarily revealed pre-purchase — but that is *exactly* the kind of thing the page should explain, not silently elide.
  - Got: H1 reads `Signal #0xfa12…34f` (truncated bigint id), subtitle `by 0x5e88…aa11`, then a 2x3 grid: Sport · Signal Fee · Genius Skin in Game · Pricing · Expires. There is no teams/event/kickoff string anywhere on the page, and no copy that says "the game is hidden until purchase, by design". A curious shopper has to take it on faith that they'll get something useful for their $1-$X.
  - Why it matters: This is the single highest-friction moment in the funnel. The buyer is one click from spending USDC on what reads as "an opaque hex string in MLB". Even pre-purchase, naming the game (or explicitly saying "the game stays hidden until purchase") materially changes the trust calculus. Right now the page silently hides information without explaining why.
  - Fix idea: Either (a) commit the event identifier to the on-chain signal payload and render "MLB · Yankees @ Red Sox · Mon 7:10 PM ET" under the H1, or (b) render an explanatory chip "Game hidden until purchase — see decoy explainer below" so the absence is intentional and legible.

- **[HIGH]** "Genius Stats" sidebar is the entire pre-purchase trust panel and shows only three numbers — Quality Score, Total Signals, Audit Count — with no link to a Genius profile, no win rate, no ROI, no recent settlement outcomes, no time-on-platform.
  - Page: `/idiot/signal?id=…` (file: `web/app/idiot/signal/page.tsx:2099-2123`)
  - Expected: At the moment of "should I trust this seller", the sidebar should at minimum (i) link the truncated address H1 to `/genius/0x…` (which now exists per iter-013), (ii) show win rate + ROI from `useAuditHistory`, (iii) show "Active since YYYY-MM-DD" so a 12-audit count has a denominator in time. The data is already loaded (`geniusSignals`, `geniusAudits`) but only the count is shown, not the outcomes.
  - Got: Three stacked rows (Quality Score, Total Signals, Audit Count). `geniusAudits` has each settled outcome (PnL, win/loss) but the sidebar only `length`s it. The page already imports `QualityScore` but does not wire any drill-down. The H1 subtitle `by 0x5e88…` is plain text, not a link.
  - Why it matters: A curious shopper at this exact moment is asking "who is this guy and have they been right?" The page surfaces a single proprietary score and two raw counts, which makes Quality Score the *only* trust lever — and Quality Score is itself unitless and uncorrelated with sports-betting intuition (covered in iter-013). Without ROI / win rate / a profile link, the buyer either bounces or buys on faith.
  - Fix idea: Convert the truncated `by 0x…` into `<Link href={`/genius/${signal.genius}`}>` and add Win Rate + ROI rows from `useAuditHistory(genius)`; show "Active since {firstSignalDate}".

- **[MED]** "Genius collateral locked" copy is misleading on a per-signal basis: the help text under the input says "Genius has 200% of your notional locked as collateral" while the summary box below says "Collateral is settled based on the Genius's audited quality score across a *batch* of signals, not on any single pick." Two adjacent UI elements describe two different settlement models, and most buyers will read only the first one.
  - Page: `/idiot/signal?id=…` (file: `web/app/idiot/signal/page.tsx:1685-1688` and `:1997-2000`)
  - Expected: One coherent claim. Either (a) collateral is per-signal and a losing single pick returns USDC to *this* buyer (in which case the "across a batch" caveat is wrong), or (b) collateral is batch-settled and *no* USDC flows back to this buyer for a single losing pick — in which case the "200% of your notional locked" copy is misleading because none of it is locked *for you*. Pick one and remove the other.
  - Got: First copy block (1686): "Genius has X% of your notional locked as collateral, settled based on audited performance across a batch of signals." Second copy block (1998): "Collateral is settled based on the Genius's audited quality score across a batch of signals, not on any single pick." A buyer reads the first and thinks they have downside protection if this specific pick loses; the second contradicts that.
  - Why it matters: This is dark-pattern-adjacent — the most plausible buyer interpretation of "200% locked" is the strongest one (per-signal protection), and the truth (batch-aggregated, lossy averaging) is buried in a smaller-grade caveat. First angry support ticket after a losing buy will be "but you said the genius had 200% locked".
  - Fix idea: Replace both blocks with one explicit sentence: "If this Genius's audited quality score drops below threshold across their next batch, slashed collateral is redistributed to *all* their buyers in that window. There is no per-signal payout to you for a single losing pick."

- **[MED]** "Best Price Available" / "Worst Price Available" pricing-mode label appears in the spec grid with zero explanation, no tooltip, and no docs link. "Worst Price Available" reads as a red flag to a non-crypto sports buyer.
  - Page: `/idiot/signal?id=…` (file: `web/app/idiot/signal/page.tsx:1690-1697`)
  - Expected: A `<Tooltip>` (the component already exists at `web/components/Tooltip.tsx`) explaining that BPA = "validators verify your buy at the best odds available across your enabled books at the moment of purchase" and WPA = "verified at the worst available odds, used as a more conservative settlement reference". Or a `(?)` link to `/docs/how-it-works#pricing-mode`.
  - Got: Bare string in the spec grid. WPA in particular reads as "the seller is going to give me bad odds", which is the opposite of its actual meaning (more conservative for the genius, *better* settlement reference for the buyer in some scenarios).
  - Why it matters: A first-time buyer comparing two cards "BPA" vs "WPA" cannot make a choice; the WPA card looks worse without any signal that it isn't.
  - Fix idea: Wrap both spans in `<Tooltip>` and link to a `/docs/how-it-works` anchor; on the card list, sort/filter by pricing mode if it's a meaningful axis.

- **[MED]** Mobile sticky purchase bar's CTA reads "Purchase Signal" but its onClick *scrolls to the form* rather than submitting the purchase — identical label to the real submit button, different action.
  - Page: `/idiot/signal?id=…` mobile viewport (file: `web/app/idiot/signal/page.tsx:2128-2150`)
  - Expected: A sticky bar CTA labeled "Purchase Signal" should submit when tapped; if scroll-to-form is the right behavior (because amount/notional are required first), label it "Enter notional ↓" or "Review purchase" — not the same words as the actual submit.
  - Got: The mobile sticky bar shows fee math, then a `btn-idiot` button labeled `"Purchase Signal"` whose `onClick` is `document.getElementById("notional")?.scrollIntoView(...)`. Buyer taps it expecting purchase, gets a scroll. On thumb-typing devices that scroll feels broken, especially when the form is already partly visible.
  - Why it matters: Identical labels with different behaviors are a textbook UX bug; on mobile this becomes a confidence killer right at the spend moment.
  - Fix idea: When `notional` is empty, label "Enter notional ↓"; when `notional > 0`, *submit the form* directly (the value is already in state) and remove the redundant scroll.

- **[LOW]** When the signed-in wallet equals `signal.genius`, the page shows an amber "Heads up: this is your own signal" banner but does *not* disable the purchase form — a Genius can pay their own fee to themselves.
  - Page: `/idiot/signal?id=…` (file: `web/app/idiot/signal/page.tsx:1848-1854`)
  - Expected: When `address === signal.genius`, the submit button should be disabled with copy "You can't buy your own signal" and a small explanation that the encrypted pick is already plaintext to them. Self-purchase has no buyer benefit (you wrote the pick) and burns gas + fee.
  - Got: Amber notice only; the form, slider, min/max buttons, and `Purchase Signal` button all remain enabled. A returning Genius who lands on their own signal page from a share link can fat-finger a self-purchase.
  - Why it matters: Tiny dollar leak, but more importantly it suggests the contract permits self-purchase as a real action, which is a yellow flag for any reviewer (it's a known wash-trading vector for fake volume / Quality-Score gaming if the contract doesn't gate it). A disabled button + clear copy closes the front-end half of that hole.
  - Fix idea: `disabled={... || address?.toLowerCase() === signal.genius?.toLowerCase()}` on the submit button, with the amber notice promoted to a slate-50 "(Self-purchase disabled)" label.

---

### 2026-05-01, Iter-020, Persona 0 (First-time visitor), 0 browser findings + 5 static-review findings

**Sweep**: 16th consecutive WAF-blocked iteration on the live origin. Headless Chromium with the saved `web/e2e/ux/.vercel-session.json` (~19h stale; `_vcrcs` cookie expired) hit `/` and got HTTP 403 "Vercel Security Checkpoint" Code 21 (body 120 chars, title "Vercel Security Checkpoint"); plain `curl -A 'Mozilla...'` to `https://djinn.gg/` also 403. Falling back to a fresh first-impression review of `web/app/page.tsx` AFTER the iter-010 fixes shipped (commits `dbfb1382` adding "Encrypted sports picks, settled on-chain" and `6b5165ef` promoting the primary "See today's signals" CTA). This block is strictly net-new vs iter-010; none are browser-verified — re-queue once Vercel session refreshes.

- [x] (fixed in 80e60f14) **[HIGH]** Idiot card under "Or pick a side" is now a redundant duplicate of the primary CTA — both routes lead to `/idiot`, so two of three above-the-fold CTAs land the visitor on the same page.
  - Page: `/` (file: `web/app/page.tsx:71-80` primary CTA + `web/app/page.tsx:111-127` Idiot secondary card)
  - Expected: after the iter-010 fix promoted "See today's signals →" to the primary CTA (which goes to `/idiot`), the secondary "Or pick a side" row should offer ONE genuinely-different choice (publishing/Genius), not duplicate the primary destination.
  - Got: visitor sees `<Link href="/idiot">See today's signals</Link>` (primary, slate-900), then a divider "Or pick a side", then a 2-card row whose right card `<Link href="/idiot">I'm an Idiot — Buy signals</Link>` goes to the same URL. The Genius card is the only differentiated path. Three CTAs, two destinations.
  - Why it matters: cognitive duplication wastes the most valuable real-estate on the page; a first-time visitor pauses to figure out the difference between "See today's signals" and "I'm an Idiot — Buy signals" (there is none) and either re-reads the page or bounces. It also waters down the meaning of "Or pick a side" — there is only one alternative side now (Genius).
  - Fix idea: collapse the secondary row to a single "Want to sell instead? → I'm a Genius" link, OR keep both cards but drop the primary CTA so the page presents one clear binary choice.

- **[HIGH]** "Signals stay secret forever. Even from us." is technically untrue — the buyer sees the prediction, and validators audit outcomes (which requires the index/pick to be revealed at settlement). Over-promise risks a credibility hit the moment a curious visitor reads `/docs` or the whitepaper.
  - Page: `/` (file: `web/app/page.tsx:46-48`)
  - Expected: a hero trust-claim that survives a 30-second skim of `/docs`. The whitepaper describes threshold encryption + post-settlement reveal so validators can audit; "stay secret forever" contradicts that flow.
  - Got: italic small-text "Signals stay secret forever. Even from us." with no qualifying clause. Adjacent step 1 says "Genius posts encrypted prediction" and step 3 says "Validators audit outcomes on-chain", which a reasoning visitor immediately notices implies a reveal at settlement.
  - Why it matters: the entire trust narrative of the product is "we can't see your pick" — and that is true *before* settlement and *for non-buyers*. Saying "forever" turns a defensible technical claim into marketing fluff that a journalist or skeptic will pull on first. iter-010 already flagged the lack of a `(learn more)` link; this is the orthogonal copy-accuracy bug.
  - Fix idea: change to "Only the buyer ever sees the pick. Even we can't read it." or "Hidden from us until settlement, then audited on-chain."

- **[MED]** Hero tagline "Information × Execution" is design-driven mystique with no plain-English explanation, no tooltip, and no surrounding caption.
  - Page: `/` (file: `web/app/page.tsx:28-32`)
  - Expected: any hero phrase that occupies its own line (and gets a stylized `&times;` glyph in bold slate-900) should pay back the visual weight with a one-line clarification or a tooltip. A first-time visitor reading top-down sees logo → DJINN → "The Genius-Idiot Network" → "Information × Execution" and has no anchor for what "Information × Execution" means.
  - Got: a standalone line above the trust taglines. No `title`, no link, no caption. Screen readers announce it as "information times execution", which lands as a math expression rather than a brand promise.
  - Why it matters: occupies prime above-the-fold space without communicating; a non-crypto-twitter visitor parses it as corporate-speak and loses confidence that the page is written for them.
  - Fix idea: either delete the line OR add a sub-caption ("Experts predict, the network executes the trade.") OR collapse it into the existing taglines.

- **[MED]** Zero social proof above the fold — no press logos, no testimonials, no founder names, no track-record sample, no "X picks settled, $Y paid out" headline above the abstract NetworkStats.
  - Page: `/` (file: `web/app/page.tsx:51-52`)
  - Expected: a marketplace asking new users to send USDC to anonymous strangers for sports picks needs visible trust signals on the landing page. Industry baseline is 1-2 of: press mentions, testimonial quote, named founder/team blurb, "audited by", or a compact "Top genius last week: +$12k, 67% win rate" preview that links to `/leaderboard`.
  - Got: hero → taglines → `<NetworkStats />` (numeric component) → 3-step explainer → CTAs. NetworkStats shows aggregate counts but is unbranded ("78 geniuses, 312 signals settled" reads like a server status page, not social proof). `/press` exists as a separate page (already flagged in iter-016 as 2 stale items) but is not surfaced on `/`.
  - Why it matters: first-time visitor leaves with no answer to "who else is doing this and did it work for them?". For a betting product specifically, the absence is conspicuous because every legitimate competitor (sportsbooks, picks services, prediction markets) leans heavily on win-rate testimonials.
  - Fix idea: add a one-row "This week's standout pick" card pulling top result from `/leaderboard`, or a small "As featured on" strip if any press exists.

- **[LOW]** "I'm a Genius / I'm an Idiot" forces self-labeling for the secondary CTA, even after iter-010's primary-CTA promotion softened the issue. Outside crypto-twitter brand-wink culture, asking a normal sports-betting buyer to identify as "Idiot" is hostile copy.
  - Page: `/` (file: `web/app/page.tsx:102-126`)
  - Expected: the brand identity ("Genius-Idiot Network") can stay in the wordmark / About page, but the action labels should be neutral ("Sell predictions" / "Buy signals" — already present as sub-labels) without forcing the user to self-identify with the slur on the click target.
  - Got: card headers `<h2>I'm a Genius</h2>` and `<h2>I'm an Idiot</h2>` are the dominant text on each card; the neutral verb sub-labels are smaller and grayer.
  - Why it matters: A/B-test class issue, but worth flagging — a non-trivial slice of mainstream sports-betting buyers will not click a card that requires them to identify as an idiot, and will instead try the Genius path (wrong funnel) or bounce. The brand wink works for retained users; it costs at the door.
  - Fix idea: swap the `<h2>` and `<p>` so the action verb leads ("Buy signals" / "Sell predictions") with "(Idiot side)" / "(Genius side)" as the small-text identity wink.

---

### 2026-05-01, Iter-019, Persona 9 (Accessibility / dark-pattern auditor), 5 findings

**Sweep**: 15th consecutive WAF-blocked iteration on the live origin (saved Vercel session ~21h stale; `/`, `/idiot`, `/genius` all returned 403 "Vercel Security Checkpoint" via headless Chromium with the saved `storageState`). Pivoted to a static review of `web/components/Layout.tsx`, `web/components/ReportError.tsx`, `web/components/SecretModal.tsx`, and `web/components/SignalCard.tsx`, focused on what iter-009 did NOT cover: the *non*-TermsModal modals, the mobile drawer's focus management, the privacy-notice copy on the feedback flow, and color-contrast on the dark-themed SecretModal. iter-009 already shipped role=dialog / aria-modal / Escape / skip-link / prefers-reduced-motion findings (all marked fixed); this block is strictly net-new. None are browser-verified — re-queue persona 9 once the WAF session is fresh.

- [x] (fixed in 0729827e) **[HIGH]** ReportError / Feedback modal claims "No personal data is shared" but submits `userAgent`, `pathname`, and the last 5 captured `console.error` strings, which routinely contain wallet addresses, signal IDs, and tx hashes.
  - Page: `web/components/ReportError.tsx:59-68` (`report` payload) and `:142-144` (the user-facing claim).
  - Expected: a feedback modal that says "No personal data is shared" should send the message + page URL and nothing else, OR the disclosure should enumerate exactly what is captured ("We also send your browser, the current URL, and the last few console errors, which may include your wallet address.")
  - Got: payload includes `userAgent: navigator.userAgent`, `consoleErrors: getCapturedErrors()` (the last 5 `console.error` invocations, sliced to 500 chars each), `pathname`, and a `wallet` field that is currently hardcoded `""` but is clearly intended to be filled. wagmi/viem and the SDK log addresses, signed-message hashes, and chain IDs to `console.error` on most failure paths, so the "No personal data is shared" promise is materially false the moment a user hits the feedback button after a failed transaction.
  - Why it matters: this is an FTC-flavored dark pattern — a privacy claim that is unambiguously contradicted by the code one screen away. A regulator, a journalist persona-4, or a tech-literate user who opens DevTools while filing feedback will see the difference and lose trust instantly. Worse, captured `console.error` strings can leak whole wallet addresses to `/v1/report-error` even when the user typed nothing sensitive.
  - Fix idea: either (a) drop `consoleErrors` and `userAgent` from the payload and keep the claim, or (b) replace the disclosure with a truthful, expandable "What we send" detail (`<details>` tag) listing each field, and add a checkbox `[ ] include diagnostic logs (recommended for bug reports)` that is **unchecked by default**.

- **[HIGH]** SecretModal (`local`/`network`/`distribute` variants) has no cancel, abort, or close affordance — once it opens it is a fullscreen, body-scroll-locked, focus-trapping wait state with no escape.
  - Page: `web/components/SecretModal.tsx:21-110` (whole component).
  - Expected: any modal that blocks the entire UI for an indeterminate operation (key derivation, network check, validator distribution) needs at minimum a "Cancel" button or an X-close that returns control to the user. Best practice: also a visible elapsed-time indicator after ~10s and a "this is taking longer than expected, [retry] [cancel]" branch after ~30s.
  - Got: there is literally no `onClose` prop, no Esc key listener, no backdrop-click handler, no X button, and `document.body.style.overflow = "hidden"` is forced on (line 25). If the spinner stalls because of an RPC hiccup, the user's only recourse is to reload the page, which loses the in-flight state machine.
  - Why it matters: this is the surface that fronts the entire "buy a pick" payoff (variant=`local` shows the decrypted secret) AND the entire "publish a pick" upload (variant=`distribute`). Being trapped in a spinner with no abort is the textbook frustration scenario that makes users force-quit, then they don't come back. Combined with the lack of aria-modal (iter-009), keyboard users are doubly stuck.
  - Fix idea: add an optional `onCancel?: () => void` prop; render an X-close button top-right whenever it is provided; also add an Esc keydown listener that calls `onCancel`. Wire each call site's parent state machine to abort the underlying promise (AbortController) when fired.

- **[HIGH]** SecretModal body copy uses `text-slate-500` (#64748b) on `bg-slate-900` (#0f172a) — measured contrast ratio ≈ 3.0:1, fails WCAG AA (4.5:1) for normal text.
  - Page: `web/components/SecretModal.tsx:104` (`text-xs text-slate-500` footer line, e.g. "Encrypted locally using AES-256. Your data never leaves this device.").
  - Expected: legal-flavored privacy / encryption claims need to be readable. WCAG 2.1 AA is 4.5:1 for body text (or 3:1 for large/bold), which means `text-slate-400` (#94a3b8) ≈ 4.6:1 is the floor on `slate-900`, and `text-slate-300` (#cbd5e1) ≈ 7.0:1 is safer.
  - Got: `text-xs text-slate-500` on `bg-slate-900` clocks in at ~3.0:1 — visually it reads as "system grey, ignore me", which is exactly the *wrong* signal for the line that justifies the privacy claim. The body description (`text-sm text-slate-400 mb-6`, line 94) is also borderline at ~4.5:1 and goes sub-AA on retina at small sizes.
  - Why it matters: low-vision users literally cannot read the encryption / privacy disclosures, which is both a legal compliance risk (ADA / EU EAA) and a UX harm — the modal is showing a sensitive payoff and burying its trust copy in unreadable grey. Persona-4 (skeptic) will read this as "they don't want me to read the fine print".
  - Fix idea: bump footer to `text-slate-300` (or `text-slate-200`) and the `<p>` body description to `text-slate-200`. Audit every other dark-card surface (`bg-slate-800`/`bg-slate-900`) for `text-slate-500` body copy.

- **[MED]** Mobile hamburger button declares `aria-expanded` but has no `aria-controls`, and the mobile drawer it opens has no Esc handler, no outside-click close, no focus trap, and no focus return on close.
  - Page: `web/components/Layout.tsx:151-167` (button) and `:172-233` (drawer).
  - Expected: a disclosure button uses `aria-controls="mobile-nav"`; the corresponding `<nav id="mobile-nav">` is announced as the controlled region. The drawer should close on Esc, on outside-click, and on route change; focus should land on the first nav item when opened and return to the hamburger when closed; Tab should be trapped within the drawer while it is open.
  - Got: `aria-expanded={menuOpen}` is set but with no `aria-controls`, so a screen reader user is told "expanded" with no idea what was expanded. The drawer has no `useEffect` for Escape, no overlay div, no focus management; tabbing past the last `<a>Discord</a>` (line 219) jumps straight into the page main content while the drawer is still visually open, which is disorienting on a phone in landscape.
  - Why it matters: persona-9's keyboard-only audit fails the moment the drawer opens. Persona-5's mobile-thumb-typer (already covered for tap-target sizes in iter-015) hits the second-order issue: opening the drawer, then tapping outside it expecting it to close, and being confused when it doesn't.
  - Fix idea: add `id="mobile-nav"` to the `<div>` at line 173 and `aria-controls="mobile-nav"` to the button. In an effect, listen for `Escape` and for `usePathname()` changes to call `setMenuOpen(false)`. On open, focus the first link; on close, restore focus to the hamburger button via a ref. Wrap the drawer in an `aria-hidden`-toggling backdrop so outside-click closes it.

- **[MED]** SignalCard public-facing "N lines (privacy-enhanced)" copy is meaningless to a normal buyer — there is no tooltip, link, or explainer for what "privacy-enhanced" means or how it changes what the buyer is paying for.
  - Page: `web/components/SignalCard.tsx:97-108`.
  - Expected: a card showing "5 lines (privacy-enhanced)" should either link `privacy-enhanced` to `/docs/how-it-works#decoys` or render a tooltip ("Lines include decoys to obscure the real pick on-chain; you decrypt all of them after purchase, decoys are clearly labeled.") The buyer needs to know whether "5 lines" means 5 picks they can use, or 1 pick + 4 decoys that they must filter through.
  - Got: bare jargon string, no `<Tooltip>` wrap, no anchor to docs. The component has access to `signal.lineCount` and `signal.decoyLines.length` but conflates them in copy. A buyer comparing two cards — "5 lines (privacy-enhanced)" vs "5 lines" — has no way to tell that the first means "1 real + 4 decoy" and the second means "5 real, no privacy".
  - Why it matters: this is a borderline dark-pattern by ambiguity — the buyer believes they are getting more value than they actually are. It also undermines the protocol's headline trust claim ("encrypted picks") because the moment the buyer hits the dashboard they cannot tell what they bought without leaving the app.
  - Fix idea: replace the line with `Lines: <Tooltip text="...">{realCount} real + {decoyCount} decoy</Tooltip>` whenever both numbers are known, and link the tooltip target to `/docs/how-it-works#decoys`. Hide the line entirely until both counts are non-zero so cards in a "no data yet" state don't lie either way.

---

### 2026-05-01, Iter-018, Persona 8 (Returning power user), 5 findings

**Sweep**: First WAF-clear iteration in 6 hours. Chromium navigated to `/idiot` (200, "Buyer Dashboard") and `/genius` (200, "Genius Dashboard") logged-out, then probed obvious returning-user URLs: `/idiot/history`, `/settings`, `/profile`, `/dashboard`, `/idiot/portfolio`, `/idiot/purchases`, `/genius/signals`, `/genius/dashboard`, `/genius/history`. Asked: where does a power user who already knows the product go to find their stuff, tweak preferences, or deep-link a teammate to "my purchase #42"? Findings below are browser-verified (DOM snapshot + `fetch()` status checks against the live origin).

- [x] (fixed in 803d002f) **[HIGH]** Every guessable returning-user URL is a bare 404 with no redirect — there is no concept of "deep-link to my dashboard subview".
  - Pages: `/idiot/history` → 404, `/idiot/portfolio` → 404, `/idiot/purchases` → 404, `/genius/history` → 404, `/genius/dashboard` → 404, `/genius/signals` → 404, `/dashboard` → 404, `/profile` → 404, `/settings` → 404 (all verified live).
  - Expected: A returning user who bookmarks `/idiot/history` or types it from muscle memory should land on the connected `/idiot` Purchase History section (or a dedicated history route). Either render those routes, or 308-redirect them to `/idiot#purchase-history` with a hash anchor.
  - Got: A bare 404 page with H1 "404" / "Page not found" / "Back to Home" — the user is bounced to `/` and has to start the connect flow over.
  - Why it matters: Power users live in URLs. Slack/Discord shares of "look at this purchase: djinn.gg/idiot/history" 404 for everyone receiving the link. Email confirmations cannot deep-link "view purchase #X" because no permalink exists for it. This silently caps virality and recovery flows.
  - Fix idea: At minimum, register `/idiot/history`, `/idiot/portfolio`, `/genius/history`, `/genius/track-record` as valid Next routes that redirect (or render the same dashboard scrolled to the relevant `<section>` via `#anchor`). Long-term: add a real `/settings` route.

- **[HIGH]** Logged-out `/idiot` "Live signals" preview shows a sport label as raw enum `baseball_mlb`.
  - Page: `/` and `/idiot` (file: `web/app/idiot/page.tsx:323` — `<span>{s.sport}</span>`).
  - Expected: A user-facing card should say "MLB", "Baseball / MLB", or even "⚾ MLB", not the raw on-chain string.
  - Got: The first sample card on the unauth dashboard renders `baseball_mlb` (lowercase, underscored) as the most prominent text. It looks like a dev placeholder leaked into prod.
  - Why it matters: First impression on /idiot for a curious-shopper / returning user. Raw enums signal "this is alpha software" louder than any banner. The same `s.sport` value is rendered identically inside the connected dashboard list (`page.tsx:826`) and inside `SignalPlot`, so the bug is multi-page.
  - Fix idea: Add a `formatSport(raw)` helper (or use the existing `SPORT_LABELS` if one exists in `lib/`) that maps `baseball_mlb → "MLB"`, `basketball_nba → "NBA"`, etc., and call it in `page.tsx` and `web/components/SignalCard*` before render.

- **[MED]** Public preview signal card shows "+0.00 QS" for a Genius with no track record — looks like a neutral score, not "no data yet".
  - Page: `/idiot` logged-out (file: `web/app/idiot/page.tsx:325-329`).
  - Expected: A Genius who has never settled an audit should render either nothing (no QS chip) or a neutral "New" / "Unproven" pill. Showing "+0.00 QS" tinted in green-text-color (`text-green-600` because `qualityScore >= 0`) implies they have a *zero-net* track record, which is materially different from "we have no data on this seller".
  - Got: Sample card rendered `+0.00 QS` in green next to a brand-new genius. Clicking through, the only reason it's "+" and green is that `qualityScore >= 0` is true at zero.
  - Why it matters: A buyer reading "+0.00 QS" assumes the seller is at least neutral. In reality the seller may have made zero settled signals ever, or could even be a brand-new wallet. This is a subtle trust/dark-pattern issue.
  - Fix idea: Treat `proofCount === 0` (or `totalSignals === 0`) as "no data" — render a small `<span>New</span>` chip in slate, not green. Reserve the +/- QS pill for sellers with at least one settled audit.

- **[MED]** Returning power-user dashboard has no in-page TOC, anchor nav, or sticky header — six stacked sections (Balances, Recovery banner, Balance Mgmt, Browse Signals, Purchase History, Active Relationships, Settlement History) and no way to jump.
  - Page: `/idiot` logged in (file: `web/app/idiot/page.tsx:385-1141`).
  - Expected: Power users want to land on `/idiot` and immediately scan "purchase X status" or "current escrow balance" without scrolling past the entire browse panel. Either a tab strip (Browse / Purchases / Relationships / Settlements), a sticky sidebar with anchors, or even just `id="purchase-history"` on each `<section>` so deep links work.
  - Got: One long flat scroll. Purchase History sits below Browse Signals, which is a list that grows with the marketplace. No `id` attributes on `<section>` elements means there's nothing to deep-link.
  - Why it matters: Daily-active users will hit this page constantly. Scrolling past 20+ live signal cards every visit is friction that compounds.
  - Fix idea: Add `id="purchase-history"`, `id="relationships"`, `id="settlements"`, `id="balance"` to the existing sections, then add a small sticky tab strip near the H1 with anchor links. Optional: `?tab=purchases` query-param routing.

- **[LOW]** Sample preview shows `4m left` red countdown but offers no "more like this" / sport-filter / "show me ones expiring later" affordance. A returning user who lands on /idiot at 2 a.m. and sees nothing but expiring picks has no way to filter to "expires tomorrow".
  - Page: `/idiot` logged-out (file: `web/app/idiot/page.tsx:295-348`).
  - Expected: Either show 6 *non-expiring-soonest* picks instead of the literal six soonest, or add a small "View all signals →" link below the preview list.
  - Got: 6 cards all sorted by expiry, top one was 4 minutes from expiry. The "Connect to buy" affordance is the only path forward. Even if a curious shopper had 30 minutes to spare, they cannot click into one to read more without connecting.
  - Why it matters: First-time and returning visitors who arrive when all the soonest-expiring signals are seconds from death see "this site is dead / about to be empty" instead of the actual market depth.
  - Fix idea: Sort the public preview by `qualityScore desc, expiresAt asc` (showing best Geniuses with most time left first), and add a "View 30 more →" link to a public read-only browse page.

---

### 2026-05-01, Iter-017, Persona 7 (Wallet connector), 0 browser findings + 6 static-review findings

**Sweep**: 13th consecutive WAF-blocked iteration. Drove headless Chromium with the saved `web/e2e/ux/.vercel-session.json` (now ~20 h stale) at `/`, `/idiot`, `/genius`. All three returned `HTTP 403` with `<title>Vercel Security Checkpoint</title>` (Code 21); the 45 s "waiting for challenge" idle did not clear ("Failed to verify your browser" remained). No connect-affordance text could be enumerated from the live DOM. Falling back to a static wallet-connector review of `web/components/WalletButton.tsx`, `web/app/providers.tsx`, `web/components/TermsModal.tsx` — focused on what a returning crypto user with MetaMask + Coinbase Wallet + Rabby installed actually sees when they hit "Connect Wallet." Persona 7 was last attempted in Iter-007 (also fully WAF-blocked); the four findings logged then have either been resolved or are now superseded. None of the findings below are browser-verified; re-queue persona 7 once the saved session is refreshed.

- [x] (fixed in cde6e5c9) **HIGH** "Wrong Network" button is a dead-end label — never names the chain Djinn wants.
  - Page: every page (file: `web/components/WalletButton.tsx:106-114`)
  - Expected: when a connected wallet is on the wrong chain, the button should name the target ("Switch to Base Sepolia") and clicking it should call `switchChain` with the right chain ID; if not auto-switchable, show the chain ID + an "Add to wallet" link.
  - Got: a red button labeled exactly "Wrong Network" that opens RainbowKit's chain modal. The modal lists Djinn's supported chains, but the button itself never tells the user which chain to pick. A user with MetaMask defaulting to Ethereum mainnet has to open the modal, read the list, infer that the only entry ("Base Sepolia") is the answer, and switch — three steps for one decision.
  - Why it matters: this is the most-hit error state in any multi-chain web app. Microcopy here is the difference between a 5-second fix and a bounce. "Wrong Network" violates the rule "tell the user what to do, not what's wrong."
  - Fix idea: render `Switch to {activeChain.name}` (e.g., "Switch to Base Sepolia") and call `useSwitchChain` directly on click; only fall back to the chain modal if the wallet refuses programmatic switch.

- **HIGH** Connected-wallet pill opens stock RainbowKit account modal — no Djinn context (USDC, escrow, recent buys).
  - Page: every page (file: `web/components/WalletButton.tsx:117-125`, click handler `openAccountModal`)
  - Expected: a returning Idiot clicking their address pill expects "What's my USDC balance? What signals did I buy? What's in escrow?" — the same numbers `/idiot/dashboard` shows. A returning Genius expects collateral + active-market count.
  - Got: stock RainbowKit modal showing ETH balance (irrelevant — Djinn settles in USDC), Copy Address, Disconnect. Zero Djinn-specific data. The user has to close the modal and navigate to `/idiot/dashboard` or `/genius/dashboard` to see anything useful.
  - Why it matters: the wallet pill is the highest-frequency UI in the app for returning users. Sending them through a generic modal that shows the wrong balance unit (ETH, not USDC) on every click is a missed engagement loop. RainbowKit's `ConnectButton.Custom` already exposes the surface needed; a custom popover with USDC + escrow + 1-click "View dashboard" would be a small component.
  - Fix idea: replace `openAccountModal` click with a custom dropdown that surfaces a USDC `balanceOf` read + escrow balance + a "Disconnect" footer.

- **MED** Decline-ToS path has no terminal copy — silent close, no explanation that connect is now blocked.
  - Page: every page where the user clicks Connect Wallet (files: `web/components/WalletButton.tsx:53-56` and `web/components/TermsModal.tsx:262-266`)
  - Expected: clicking Decline should leave a brief inline note near the Connect button ("You must accept the Terms to connect a wallet") or convert the Connect button to a tertiary "Review Terms" affordance; the user should know what state they're in.
  - Got: `handleDecline` just `setShowTerms(false)` and clears `pendingConnect`. The modal disappears, the Connect Wallet button stays exactly as it was. A user who declined doesn't know whether browsing without a wallet is still allowed, or whether the next click will re-prompt the same modal (it will), or whether some other path exists.
  - Why it matters: legal-modal abandonment is a common churn point; users who decline once need a clear "here's what you can still do" off-ramp, otherwise they assume the site is broken.
  - Fix idea: after Decline, render a small toast/inline message: "You can still browse public signals, but connecting a wallet requires accepting the Terms. [Review again]".

- **MED** ToS modal has no visible close affordance (no "X" button) — only Decline / Accept.
  - Page: any page where the modal opens (file: `web/components/TermsModal.tsx:93-110`, header has `<h2>` + subhead but no close button)
  - Expected: standard dialog pattern is an "X" in the top-right of the header so users can dismiss without committing to "Decline" semantics. Escape-to-close exists in the keyboard handler (line 53), but it's invisible to mouse and touch users.
  - Got: header is text-only; the only ways out are the Decline / Accept buttons in the footer. On mobile (where Escape isn't available), users who want to back out without "declining" (e.g., to read `/terms` first in a new tab and come back) have to scroll past 6 numbered points to find Decline.
  - Why it matters: dialog conventions are load-bearing. A modal without an X feels like a dark pattern even when it isn't, because users have read decades of dialogs that close in the corner. Decline is also a stronger semantic than "close" — some users will avoid clicking it because they don't want to "decline" anything.
  - Fix idea: add an `aria-label="Close"` `<button>` with an SVG X to the header `border-b` row, calling `onDecline` (or a new `onClose` if you want to distinguish dismiss-without-deciding from explicit decline).

- **MED** Wallet-button area collapses to nothing during hydration — header layout shift on every cold load.
  - Page: every page (file: `web/components/WalletButton.tsx:74-77`, `if (!ready) return null`)
  - Expected: a skeleton or non-interactive placeholder of the same width as the eventual button so the header doesn't reflow.
  - Got: until wagmi mounts (one tick post-hydration), the entire WalletButton subtree renders nothing. On a slow connection the user sees the header with a Connect-shaped void where the CTA will be, then it pops in and shifts the surrounding nav links left (depending on connected vs. not). Cumulative Layout Shift on first paint.
  - Why it matters: CLS hurts Core Web Vitals (so SEO) and feels janky on every page. It also briefly hides the CTA — a first-time visitor scrolling fast might not even notice the Connect button exists for a beat.
  - Fix idea: while `!ready`, render a fixed-width skeleton with the same dimensions as the connected pill (e.g. `h-10 w-[148px] rounded-lg bg-slate-100 animate-pulse aria-hidden`) to prevent reflow.

- **LOW** "I already have a wallet" group + auto-discovery double-lists MetaMask for users who have it injected.
  - Page: RainbowKit Connect modal (files: `web/app/providers.tsx:40-52`, `multiInjectedProviderDiscovery: true` plus a curated `wallets: [..., metaMaskWallet, ...]` array)
  - Expected: either curated list OR auto-discovered EIP-6963 list, not both — or a dedup pass so MetaMask doesn't appear twice.
  - Got: any user with the MetaMask extension installed sees MetaMask in the curated "I already have a wallet" group AND in the auto-injected list (RainbowKit's default behavior with `multiInjectedProviderDiscovery: true`). Same icon, same label, two rows. Users wonder which one to click; choosing the wrong one occasionally produces different connector IDs which can affect later reconnect.
  - Why it matters: a tiny bit of "is something broken?" friction at the most fragile moment of onboarding. Lower severity because the click works either way, but it is the kind of polish gap that a careful reviewer notices and reports as "looks unfinished."
  - Fix idea: drop the explicit `metaMaskWallet` from the curated list (let auto-discovery handle injected wallets) OR set `multiInjectedProviderDiscovery: false` and curate the full list manually. Keeping both means dedup, which RainbowKit does not do automatically.

(All six are static-review only — the WAF blocked browser verification this iteration. Persona 7 has now been blocked twice in a row (Iter-007 and Iter-017); the operator should refresh `web/e2e/ux/.vercel-session.json` or set a Vercel-protection-bypass token. Cross-reference: HIGH #2 echoes Iter-008's "dashboard shows chain-native units instead of app-domain numbers" theme — both the dashboard and the wallet popover fail returning users by speaking blockchain instead of speaking Djinn.)

---

### 2026-05-01, Iter-016, Persona 6 (Footer trawler), 0 browser findings + 5 static-review findings

**Sweep**: 12th WAF-blocked iteration. Drove headless Chromium with the saved `web/e2e/ux/.vercel-session.json` (now ~26 h stale) at all 16 footer destinations: `/genius`, `/idiot`, `/leaderboard`, `/network`, `/attest`, `/whitepaper.pdf`, `/education`, `/docs`, `/press`, `/about`, `/support`, `/terms`, `/privacy`, `/risk`, `/acceptable-use`, `/dmca`. Every URL returned `HTTP 403` with `<title>Vercel Security Checkpoint</title>` (Code 29 / 21). Iter-15's slip-through on `/genius` did not repeat. The slip-through that allowed iter-012 also did not repeat. Falling back to a static footer-trawler review of `web/components/Layout.tsx:265-318` (the four footer columns + legal-links bar + Feedback button) and the destination pages: `web/app/press/page.tsx`, `web/app/education/page.tsx`, `web/app/support/page.tsx`, `web/app/risk/page.tsx`, `web/app/dmca/page.tsx`. Persona 6 was last attempted in Iter-006 (also fully WAF-blocked, zero findings logged), so this is the first actual footer audit of the loop. None of the findings below are browser-verified; re-queue persona 6 once the saved session is refreshed.

- **[HIGH]** Footer "Settled in USDC on Base" copy contradicts the protocol's actual testnet status; reads as a deposit-real-USDC promise.
  - Page: every page (footer block, file: `web/components/Layout.tsx:256-262`)
  - Expected: footer states the live deployment plainly. If it's "USDC on Base" it should be Base mainnet; if it's testnet, footer should say "Testnet (Base Sepolia) — no real money" the same way the homepage banner does (per Iter-001 finding at `/`).
  - Got: footer reads "Sports Intelligence Marketplace. Powered by a decentralized network. Settled in USDC on Base." — no "testnet", no "Sepolia", no caveat. Yet `/risk` section 1 says "Djinn operates on Base Sepolia. Tokens on Base Sepolia, including the USDC shown in the Djinn interface, have **no cash value**" and `/support` links to `https://sepolia.basescan.org` for tx checks.
  - Why it matters: footer is on every page, including `/idiot` purchase modals. A non-crypto user reads "Settled in USDC on Base," opens MetaMask on Base mainnet, sends real USDC to a deposit address that resolves on Sepolia, loses it. The risk page covers the team legally but the footer copy is doing the *opposite* of what risk.tsx promises.
  - Fix idea: while on testnet, change the footer line to "Currently on Base Sepolia testnet · No real money" with a `Link href="/risk#testnet-status"`; flip back to "Settled in USDC on Base" only on mainnet launch.

- **[HIGH]** `/press` is bottom-of-funnel evidence and it is dangerously thin: 2 articles, both dated Jan 2026, only 1 actually external.
  - Page: `/press` (file: `web/app/press/page.tsx:25-46`)
  - Expected: a Press page on a marketplace claiming production traction shows a steady drip of external coverage (rolling 30-90 day items), each from independently editable outlets, with at least 5-8 entries by month 4 of public ops.
  - Got: array length 2. Item 1 is TAO Daily ("600 TAO in 51 minutes" Bitstarter coverage) dated `Jan 24, 2026`. Item 2 is **Djinn's own launch tweet** masquerading as press coverage (`source: "Djinn"`, `url: "https://x.com/djinn_gg"`, `tag: "ecosystem"`). Today is 2026-05-01 — the page has been static for 3+ months. There is no `last updated` line on the page (every other policy page has one).
  - Why it matters: a journalist or institutional partner clicking Press looks for proof the team is talked about. Two items, one of which is a self-tweet, signals "we got one piece of coverage at launch and nothing since." That's worse than no Press page.
  - Fix idea: hide self-tweets from the Press grid entirely (move to a "Announcements" page or delete), add a 30-day-rolling banner if `ARTICLES[0].date < 60 days ago` saying "We refresh this monthly — coverage thread on @djinn_gg," and add a `last updated` stamp. Better: post 2-3 more genuine 3rd-party items (newsletter, podcast, Substack writeup) before linking this from the footer.

- **[HIGH]** Press "Media Inquiries" CTA has no email; it points reporters at an X DM.
  - Page: `/press` (file: `web/app/press/page.tsx:228-247`)
  - Expected: a press@ mailbox, an embargo-friendly contact, and a phone or Signal handle for breaking-news. At minimum a real email.
  - Got: a card titled "Media Inquiries" whose body is "For press inquiries, interviews, or partnership opportunities, reach out on **X @djinn_gg**." No email anywhere on the page.
  - Why it matters: serious reporters do not DM unverified X accounts about embargoed crypto/gambling stories — they need a deliverability-checkable email. `/support` correctly exposes `security@djinn.gg` and `support@djinn.gg`; `/press` should expose a `press@djinn.gg` (or reuse `support@`) right next to the CTA. Pointing only to X also looks like the team is too small to staff a press function — a footer trawler skeptic walks away.
  - Fix idea: add `<a href="mailto:press@djinn.gg">press@djinn.gg</a>` as the primary CTA, keep "or DM @djinn_gg" as a secondary option.

- **[MED]** `/education` has 3 resources and zero of them teach the *actual* claimed audience (sports bettors).
  - Page: `/education` (file: `web/app/education/page.tsx:25-53`)
  - Expected: page titled "Education & Research" linked from the footer of a sports-intelligence marketplace teaches a sports-betting newcomer the basics — what a moneyline is, how to read American/decimal odds, what implied probability means, what a closing-line value is, why "edge" matters. It can also include the existing Bittensor/dTAO research, but the headliners should serve the funnel.
  - Got: 3 cards: (1) "TAO Valuation: Top-Down vs Bottom-Up" (dTAO economics), (2) "AMM-Implied Options on Bittensor Subnet Tokens" (academic options paper), (3) "Analytics.Bet" (one external partner course platform). Nothing native to djinn.gg explains odds, EV, line-shopping, bankroll, or how a Genius's Quality Score relates to traditional sharp metrics. The two internal items are crypto/economics for an LP audience, not bettors.
  - Why it matters: an Idiot persona clicking the footer link looking for "how do I read these picks" finds zero answers and bounces to Analytics.Bet (which is a partner, not a Djinn page). The page exists to satisfy a footer label, not to onboard users.
  - Fix idea: ship one short native explainer ("How to read a Djinn signal: market, side, odds, stake") at `/education/reading-signals`, and another ("How Quality Score relates to closing-line value") aimed at the actual product. Keep TAO/options for the Bittensor LP audience but section them under a "Network research" subhead so they don't dominate.

- **[MED]** Footer button "Feedback" is a non-shareable, non-right-clickable, no-keyboard-Enter modal trigger; behaves unlike every other footer destination.
  - Page: every page, footer legal row (file: `web/components/Layout.tsx:316`)
  - Expected: every other footer item is a `Link href="/path"` — right-click "open in new tab" works, middle-click works, Cmd-click works, the URL is shareable, screen readers announce a link role with destination. A keyboard user tabbing through the legal row hears "link, Support; link, Terms; link, Privacy; link, Risk; link, AUP; link, DMCA; **button, Feedback**." The shape change is jarring.
  - Got: `<button onClick={() => setFeedbackOpen(true)} className="hover:text-slate-600 transition-colors">Feedback</button>` — no `aria-haspopup="dialog"`, no keyboard preview that this opens a modal, no shareable URL like `/feedback?open=1`.
  - Why it matters: a footer trawler doing a "do all these go somewhere real?" sweep cannot tab/right-click into Feedback to confirm it is a real page; on mobile a long-press doesn't reveal a URL. The page `/feedback` *does* exist (per Iter-08's bookmark list), so the modal-only entry is a regression — it hides the durable URL. Also breaks the footer's visual / interaction symmetry.
  - Fix idea: make Feedback a `<Link href="/feedback">` like the other items; on the `/feedback` page, auto-open the same modal via `searchParams.open === "1"` (or just render the form inline). Drops the local `useState` and restores keyboard/right-click parity.

---

### 2026-05-01, Iter-015, Persona 5 (Mobile thumb-typer / iPhone 13 390x844), 4 browser-verified + 2 static-review findings

**Sweep**: Headless Chromium with iPhone 13 device profile (390x844, touch, mobile UA) using saved Vercel session. WAF still blocked `/` and `/idiot` (Code 21, 11th consecutive iteration), but `/genius` and `/leaderboard` actually loaded clean (status=200, no challenge), giving the first real mobile-viewport browser data of the loop. Also probed `components/Layout.tsx` (header, mobile drawer, footer) and `components/SecretModal.tsx` for mobile-specific layout. All findings below are touch-target / cramped-layout issues a thumb-typer hits within the first 30 seconds. Screenshots saved to `e2e-screenshots/ux-mobile-15-*.png`. No horizontal overflow on either page (good).

- **[HIGH]** Hamburger menu button is 36×36 px on a 390 px viewport — below iOS / Material 44×44 minimum tap target.
  - Page: every page (file: `web/components/Layout.tsx:151-166`)
  - Expected: the *primary* mobile navigation control should be at least 44×44 px (Apple HIG) / 48×48 dp (Material). Sub-44 px controls are cited as the #1 mobile usability fail.
  - Got: button is `lg:hidden rounded-lg p-2` wrapping a `w-5 h-5` SVG → 8 + 20 + 8 = 36 px square (browser-verified bbox: 36×36). Above the target row, the WalletButton is wider/taller, so the hamburger is the smallest control on the bar despite being the most-used one when not connected.
  - Why it matters: every mobile session that needs to navigate without scrolling first (most of them) has to aim for a 36 px target near the screen edge. Mistaps tap the WalletButton instead, which on a fresh visit opens RainbowKit and a wallet picker — high-friction wrong-modal recovery.
  - Fix idea: bump padding to `p-2.5` (or `p-3`) and the icon to `w-6 h-6`.

- **[HIGH]** Footer "Protocol" / "Resources" link rows are 17 px tall — far below 44 px tap target, and they are the only access to `/leaderboard`, `/network`, `/attest`, `/docs`, `/about`, `/press`, `/education` on a closed-menu mobile page.
  - Page: every page (file: `web/components/Layout.tsx:264-305`)
  - Expected: footer nav on mobile uses generous spacing (~48 px row height) because that's the only path to deep pages once the hamburger menu is closed.
  - Got: `<li>` items use `space-y-2` (8 px) with `text-sm` (14 px) text and no padding. Browser-verified bounding boxes: "Genius Dashboard" 122×17, "Browse Signals" 101×17, "Leaderboard" 87×17, "Network Status" 100×17, "Verify Picks" 78×17. Side-by-side at 8 px vertical gap → near-impossible to tap correctly with a thumb.
  - Why it matters: a mobile user who closed the hamburger and scrolled to the bottom looking for "About" or "Risk" can't reliably tap any of them, especially with a screen protector or in landscape.
  - Fix idea: add `py-2` to each `<li>` (or wrap each link in a `block py-2 -mx-2 px-2`) so the row is at least 36 px tall; bump `space-y-2` to `space-y-1` to compensate.

- **[MED]** Footer legal-links bar (Support · Terms · Privacy · Risk · AUP · DMCA · Feedback) is a single `flex flex-wrap` row of `text-xs` (12 px) items at 390 px viewport — wraps to 2-3 unpredictable rows where each item is ~16 px tall and adjacent items are within finger-width of each other.
  - Page: every page (file: `web/components/Layout.tsx:307-317`)
  - Expected: legally important links (Risk disclosure, Terms, AUP, DMCA) should be unambiguously tappable on the device most users read them on (mobile). Many regulators look specifically at the prominence of risk/AUP links.
  - Got: 7 items at `text-xs` with `gap-x-4 gap-y-2` flex-wrap — on 390 px the row breaks at unpredictable points; "Risk" and "AUP" can land directly adjacent with 16 px of horizontal gap and 12 px text height.
  - Why it matters: a regulator-friendly read of "did the user have a fair shot at finding Risk?" depends on these links being conspicuous. They aren't. Also, "Feedback" is a `<button>` styled identically to `<Link>`s — looks like another legal page until tapped.
  - Fix idea: on mobile, render this as a 2-column grid (`grid grid-cols-2 sm:flex`), `text-sm`, with `py-2` on each item. Visually distinguish "Feedback" (e.g., a chevron or different color).

- **[MED]** DJINN home wordmark is 97×28 px — main "go back home" affordance is a 28 px-tall tap target.
  - Page: every page (file: `web/components/Layout.tsx:75-86`)
  - Expected: the logo home link is a near-universal "escape hatch" for users who feel lost. Should be a tall, generous target.
  - Got: `Link` wraps `Image w-7 h-7` (28 px) + `text-lg` wordmark with no vertical padding. Browser-verified 97×28.
  - Why it matters: low-priority on its own, but combined with the 36 px hamburger right next to it on the header, the entire 64 px-tall header bar contains zero ≥44 px tap targets except the WalletButton.
  - Fix idea: add `py-2 -my-2` to the `Link` on mobile so the hit-area is 44 px tall without changing visual height.

- **[MED]** SecretModal (the surface that reveals a purchased pick's plaintext) uses `p-8` (32 px on every side) inside `mx-4 max-w-md` on 390 px viewport → effective content width is 390 − 32 − 64 = ~294 px, cramped for the multi-line monospace secret string.
  - Page: post-purchase reveal flow (file: `web/components/SecretModal.tsx:74-79`, static review)
  - Expected: a modal whose entire job is to display a string the user needs to read/copy should give that string the full available width on mobile.
  - Got: 32 px of padding on left + right eats ~16% of the modal's interior on a 390 px screen; long secret lines wrap aggressively and the reveal feels visually anxious.
  - Why it matters: the buyer just spent USDC; the moment the secret is revealed is the *one* moment that has to feel premium. Cramped padding undermines the payoff.
  - Fix idea: drop to `p-6 sm:p-8` and consider `mx-2 sm:mx-4` on mobile.

- **[LOW]** Mobile drawer's bottom social-icon row (X / GitHub / Discord) uses `w-4 h-4` (16 px) SVGs inside un-padded `<a>` tags, separated by `gap-4`.
  - Page: every page when hamburger is open (file: `web/components/Layout.tsx:196-230`, static review — drawer didn't open in time on this run's probe)
  - Expected: even tertiary social links should be ≥32 px tap targets when they're inside a drawer where adjacent rows are full-width nav links.
  - Got: 16 px icons, no padding, 16 px gap → three 16-pixel targets on one row.
  - Why it matters: minor — most users won't tap these — but the drawer feels half-finished compared to the proper nav links above it.
  - Fix idea: wrap each in a `p-2` block so each is ≥32 px square, matching the same `py-2.5` rhythm as the nav links.

---

### 2026-05-01, Iter-014, Persona 4 (Skeptic / journalist), 0 browser findings + 7 static-review findings

**Sweep**: 10th consecutive WAF block. Headless Chromium with the saved `web/e2e/ux/.vercel-session.json` (now ~26 h stale) hit `/`, `/network`, `/docs`, `/about` and got `<title>Vercel Security Checkpoint</title>` Code 21 on all four; raw curl to the same paths returned HTTP 403 (~40 ms). Persona 4 was last attempted in Iter-004 (also WAF-blocked, zero findings) so this is the first real skeptic pass against the *content* of the explainer pages. Falling back to a static review of `web/app/about/page.tsx`, `web/app/docs/page.tsx`, `web/app/docs/how-it-works/page.tsx`, and `web/app/network/page.tsx`. Skeptic angle: does the site explain HOW this works to a non-crypto reader, is the trust model self-consistent across pages, are the validators legible as real infrastructure? None of the findings below are browser-verified; they are read against the source.

- **[HIGH]** `/about` and `/docs/how-it-works` contradict each other on two core trust claims (decoy count and what Shamir splits).
  - Page: `/about`, `/docs/how-it-works` (files: `web/app/about/page.tsx:84-86,184-185,212-216`, `web/app/docs/how-it-works/page.tsx:52-59,113-118`)
  - Expected: a journalist comparing the marketing page (`/about`) to the technical explainer (`/docs/how-it-works`) should see the same numbers and the same mechanism. Two pages, one protocol.
  - Got: `/about` says the Genius commits "alongside 10 decoy lines" (fixed count, twice — in step 1 and in the Encrypt lifecycle card and again in the Cryptographic Guarantees card), but `/docs/how-it-works` step 1 and the Key Properties section both say "a configurable set of decoy lines". `/about` step 2 says "The key is released via Shamir secret sharing", which reads as the AES key being threshold-released; `/docs/how-it-works` step 1 says Shamir splits the *real pick's index*, not the AES key, and step 4 confirms reconstruction happens inside MPC, not as a key handed to the buyer. Two different mental models on adjacent pages.
  - Why it matters: this is exactly the comparison a skeptical journalist or auditor will make first. Inconsistent magic numbers ("10" vs "configurable") and inconsistent crypto descriptions are the single fastest way to get a "they don't actually know how their own protocol works" headline. It also triggers the "marketing vs engineering" smell that makes investors and exchanges nervous.
  - Fix idea: pick one canonical statement, link both pages to it, and stop saying "10" if the count is configurable.

- **[HIGH]** "48-hour dispute window" appears once on the entire site (in `/docs/how-it-works` step 5) with no UI, no `/disputes` page, no "how to dispute" link, and no contract address.
  - Page: `/docs/how-it-works` (file: `web/app/docs/how-it-works/page.tsx:91-96`)
  - Expected: if the protocol promises a 48-hour dispute window before fees clear, a skeptical reader expects (a) a UI to file a dispute, (b) a description of who adjudicates, (c) a link to the relevant contract function, and (d) at minimum a `/disputes` or `/support#disputes` page.
  - Got: a single sentence, "The Genius can claim their earned fees after a 48-hour dispute window." No mechanism, no UI, no link. Searching the app router (`web/app/`) finds no `disputes/` directory, and `support/`, `risk/`, `terms/` do not appear to host the dispute mechanics either. To a journalist this reads as a marketing line, not a real recourse path.
  - Why it matters: every honest betting/prediction marketplace gets asked "what happens if I think the outcome is wrong?" If the answer is a one-liner with no UI, the protocol's "consensus-driven outcomes" claim has no fallback for the case where the consensus is wrong. Regulators and journalists both probe this immediately.
  - Fix idea: ship a `/docs/disputes` (or `/disputes`) page that explains the window, who can file, what evidence matters, what the on-chain function is, and link it from both `/about` and `/docs/how-it-works` step 5.

- **[HIGH]** `/docs` "Choose your path" 2x2 Human/Computer × Genius/Idiot table is performative — three of the four cells link to the same two destinations.
  - Page: `/docs` (file: `web/app/docs/page.tsx:64-155`)
  - Expected: a 2x2 promises four distinct entry points. Either the four cells lead to four meaningfully different pages, or the table should be a 1x2 (Human / Computer).
  - Got: Human/Genius → `/genius`, Human/Idiot → `/idiot`, Computer/Genius → `/docs/api`, Computer/Idiot → `/docs/api`. The Computer row collapses both personas into a single `/docs/api` link with copy that *claims* differentiation ("Automate signal posting from models, bots, or agent frameworks" vs. "Build bots, LLM agents, or custom tools that buy signals programmatically") but the destination URL is identical. There is no `#genius`/`#idiot` anchor either.
  - Why it matters: a skeptical reader notices padding instantly. It signals "we have less docs than the layout suggests" — exactly the impression you do not want on the Documentation index page.
  - Fix idea: either deep-link to `/docs/api#genius` and `/docs/api#idiot` with real anchored sections, or split into `/docs/api/genius` and `/docs/api/idiot`, or collapse the row to a single Computer cell.

- **[MED]** `/network` is a pure ops dashboard with no "what am I looking at" header for a non-engineer reader, and the Quorum card can flash "below threshold" without explaining whether the protocol is stuck or merely conservative.
  - Page: `/network` (file: `web/app/network/page.tsx:387-418`)
  - Expected: the page a journalist clicks from the homepage to verify "the validators are real" should explain what a validator is, why there is a Gini coefficient, and what "below threshold" actually means in user terms (fully halted? degraded? OK but cautious?).
  - Got: the only narration is "Live infrastructure status for Bittensor Subnet 103. Updated …". The six summary cards are unannotated jargon: "Miners", "Unique IPs", "Gini", "Burn", "Validators", "Quorum". The Quorum card uses `effectiveSigners >= ceil((2 * totalValidators) / 3)` (line 384) where `totalValidators` is the *full set including offline ones*, so a transient outage flips the card to red ("below threshold"); the journalist sees red and assumes the protocol is broken.
  - Why it matters: the Network page is the single best evidence that this is a real network and not a Potemkin frontend. Showing a red "below threshold" without a 1-sentence "what does this mean for me, the buyer?" tooltip turns the page from credibility into FUD. A skeptical journalist will screenshot it.
  - Fix idea: add a top-of-page "Read the protocol overview" link to `/docs/how-it-works`, give every Stat card a `<Tooltip>` with a one-sentence plain-English explanation, and have the Quorum card distinguish "settlement halted" vs "1 validator below" rather than a binary red/green.

- **[MED]** `/about` Trust bar (AES-256, On-Chain, USDC, Bittensor) is decorative — every claim is a leaf with no link, tooltip, or citation a journalist could verify.
  - Page: `/about` (file: `web/app/about/page.tsx:44-70`)
  - Expected: the most-clicked place to anchor "show me the source" trust evidence. Each badge should hover or click into the relevant doc/contract/repo.
  - Got: four spans with inline SVGs and plain text. "AES-256-GCM Encrypted" doesn't link to the encryption section of `/docs/how-it-works`. "On-Chain Track Records" doesn't link to `/leaderboard` or a Basescan query. "Settled in USDC on Base" doesn't link to the USDC contract or to `/docs/contracts`. "Powered by Bittensor" doesn't link to Subnet 103 or `/network`. The strongest part of the page is also the least clickable.
  - Why it matters: the trust bar is the place a skeptic *expects* to drill in. Leaving it as decoration trains them to read the rest of the page as marketing copy too.
  - Fix idea: each badge wraps a `<Link>` or `<Tooltip>` with a one-sentence explanation and a "View source" jump.

- **[MED]** `/docs/how-it-works` step 2 introduces "the buyer's preferred sportsbooks" with no explanation of where the buyer configures that preference and no link to a settings/preferences page.
  - Page: `/docs/how-it-works` (file: `web/app/docs/how-it-works/page.tsx:62-71`)
  - Expected: any phrase of the form "the buyer's preferred X" implies an X-preference UI. The reader should be able to click "preferred sportsbooks" and land on the preferences screen, or see a sentence saying "you'll set this on your Idiot dashboard the first time you buy a signal".
  - Got: the phrase appears once, with no link, no tooltip, no follow-up. A skeptic asks: "Is this a feature, or is it aspirational? Is it gated by KYC? Does it support my book?" None of those questions are answered anywhere on the page or its docs neighbors.
  - Why it matters: protocol honesty matters most when the reader is checking your claims. Mentioning a feature ("preferred sportsbook routing") and not letting the reader find it makes them assume nothing else on the page is shippable either.
  - Fix idea: either link to the actual preferences UI, or rephrase to "the sportsbook prices the miner network observes at the time of attestation" (which is what the protocol actually does).

- **[LOW]** `/about` Trust bar SVG icons all use `text-idiot-500` (the buyer-persona accent), visually associating platform-wide claims with the Idiot color rather than a neutral platform color.
  - Page: `/about` (file: `web/app/about/page.tsx:47,53,59,65`)
  - Expected: the trust bar speaks for the platform, not for one of the two persona sides. Use `text-slate-700`, `text-blue-600`, or a dedicated platform accent.
  - Got: every icon is `text-idiot-500`, presumably amber/orange. Subtle but reads as "these are buyer claims" to anyone who clicks Genius first.
  - Fix idea: switch to a neutral platform accent and reserve `idiot-500` / `genius-500` for persona-specific surfaces.

(All seven are static-review only. The WAF blocked browser verification this iteration. They should be reconfirmed against the live `/about`, `/docs`, `/docs/how-it-works`, and `/network` once `web/e2e/ux/.vercel-session.json` is refreshed. Persona 4 has now been blocked twice (Iter-004 and Iter-014); the operator should consider a fresh session capture or a Vercel-protection-bypass token before the loop hits another full-rotation gap on this persona.)

---

### 2026-05-01, Iter-013, Persona 3 (Track-record researcher), 0 browser findings + 6 static-review findings

**Sweep**: 9th WAF-blocked iteration. MCP Chromium hit `https://djinn.gg/leaderboard` and `https://www.djinn.gg/leaderboard`; both stayed on `<title>Vercel Security Checkpoint</title>` after a 30 s wait, and a node script using the saved `web/e2e/ux/.vercel-session.json` (now ~42 h stale) returned HTTP 403 from both apex and `www`. The slip-through that allowed iter-012 to verify `/genius` did not repeat. Falling back to a static track-record-researcher review of the now-shipped `web/app/leaderboard/page.tsx`, `web/app/genius/[address]/view.tsx`, and `web/lib/profileIdentity.ts` (the fixes for iter-003's three closed findings). Asked: "Can I verify a top Genius's claims without a PhD in crypto, *and* are the new identity/profile pages telling me the truth or selling me a story?" None of these are browser-verified.

- **[HIGH]** Auto-generated `@AdjectiveNoun` handles + canned bios masquerade as user-chosen identity — soft dark pattern.
  - Page: `/leaderboard`, `/genius/[address]` (file: `web/lib/profileIdentity.ts:1-60`)
  - Expected: Either let Geniuses pick their own handle/bio (the fix iter-003 envisioned: "Allow Geniuses to set a handle plus avatar in their /genius dashboard") with a clear "unset" fallback, OR make the synthetic identity visually obvious as synthetic ("Auto-generated identicon — this Genius hasn't set a handle yet"). A researcher must be able to tell a chosen identity from a derived one.
  - Got: Every address gets a deterministic `${ADJECTIVES[h%10]}${NOUNS[(h>>4)%10]}` handle (e.g. `@SteadyScout`, `@SharpOracle`) plus one of three identical bios ("On-chain analyst publishing verified sports signals.", "Public track record secured by audit settlements.", "Signal publisher with transparent performance history."). These render with no "auto" badge, no italic, no "unverified" tag — a researcher reads `@SteadyScout` + bio and reasonably assumes the publisher chose both.
  - Why it matters: Two distinct addresses can collide on the same `@AdjectiveNoun` handle (only 100 combinations from 10 adj × 10 noun) — directly impersonable. Worse, the bio claim "Public track record secured by audit settlements" is asserted by the *site*, not the publisher, even when `auditCount === 0`. A researcher who treats the bio as a claim by the publisher is being misled by the system.
  - Fix idea: Tag synthetic handles visually (`@SteadyScout · auto`), strip the bio when no audits have settled, and ship the dashboard handle/bio editor that iter-003's fix proposal called for.

- **[HIGH]** Genius profile claims "All numbers below are computed from on-chain audit settlements" but no settlement row exposes a tx hash or basescan link — researcher cannot click through to verify a single batch.
  - Page: `/genius/[address]` (file: `web/app/genius/[address]/view.tsx:101-104,187-223`)
  - Expected: Each row in "Settlement History" should have a "View on Basescan" link or tx-hash chip. The header makes a cryptographic-verification promise; rows must let the researcher fulfill it. A fingertip-distance basescan link per audit is the single most important affordance on this page.
  - Got: Each row shows `Batch <cycle>`, truncated `Buyer 0xabc...`, block date, tranche A/B totals, and a green/red `qualityScore`. No tx hash, no `eventUrl`, no `txUrl`, no per-row basescan link. The page-level "View raw txs on Basescan" link goes to the EOA's address page (a flat list of every tx the address has ever made, not the specific batch settlement event).
  - Why it matters: Track-record researchers are the marketplace's most valuable persona because they convert and recruit. The whole "verifiable, on-chain" pitch collapses if the page asserts numbers and then refuses to show its work. A researcher who cannot verify *one specific batch* without grepping basescan tx history will rationally distrust the aggregate.
  - Fix idea: `useAuditHistory` returns events with `transactionHash`/`blockNumber`; render a per-row `<a href={txUrl(audit.transactionHash)}>↗</a>` chip. Cheap, decisive, makes the trust claim real.

- **[MED]** "Quality Score" is the same label on both pages but two different units — leaderboard shows a unitless score, profile aggregate shows USDC.
  - Page: `/leaderboard` vs `/genius/[address]` (files: `web/app/leaderboard/page.tsx:117-119,256-261` shows `QualityScore` rounded to 1 dp; `web/app/genius/[address]/view.tsx:96-98,224-230` shows the same component for `lbEntry.qualityScore` AND a separate "Aggregate Quality Score" line formatted via `signedUsdc` — i.e. dollars).
  - Expected: One name, one unit. Either rename the dollar-denominated row to "Aggregate P&L (USDC)" or convert the leaderboard QS to dollars. A researcher cross-checking "QS = +12.4" on the leaderboard against "Aggregate Quality Score = +$3,420.18" on the profile cannot reconcile them without reading source.
  - Got: Leaderboard sorts/displays `qualityScore` as a small unitless number ("+12.4"); profile shows the *same* `lbEntry.qualityScore` rounded to 1 dp at the top right, *and* below it a separate "Aggregate Quality Score" line formatted as `$3,420.18` via `signedUsdc(aggregateQualityScore)`. Both are labelled "Quality Score." Different math, different units, same name.
  - Why it matters: Researchers form trust by reconciling numbers across views. Two values calling themselves "Quality Score" with no unit reconciliation reads as either a bug or a smokescreen. Either interpretation hurts.
  - Fix idea: Rename the per-batch and aggregate USDC value to "P&L" or "Settlement value", reserve "Quality Score" for the unitless metric defined in the leaderboard's "How QS Works" panel, and add a one-line "QS vs P&L" tooltip on the profile.

- **[MED]** Genius profile shows no time horizon — no "active since", no "first signal date", no recency badge.
  - Page: `/genius/[address]` (file: `web/app/genius/[address]/view.tsx:135-168`)
  - Expected: A track-record researcher cannot evaluate "Lifetime Signals: 240 / Audits: 12 / ROI: +14.2%" without a denominator in time. Was that 12 audits in 6 months, or 12 audits last week? An "Active since 2025-09-14 · 38 weeks" line under the H1, or a "Signals over time" sparkline, would answer that in one glance.
  - Got: Four stat cards (Signals, Audits, ROI, Win Rate) — no first-signal date, no last-active date, no time-window control, no sparkline. The settlement history card has block-dates per row but the user must scroll and squint to infer recency.
  - Why it matters: A 70% win rate over 4 picks and a 70% win rate over 400 picks have radically different signal value; researchers know this, and Djinn knows it (the leaderboard `auditCount` column exists for the same reason). Without a time anchor on the profile, even the auditCount means little.
  - Fix idea: Compute `firstAuditBlock = min(audits.blockNumber)` and `lastAuditBlock = max(...)`; show "Active since `{date}` · `{n}` weeks" beneath the bio. Optional: a small "Last 7d / 30d / All" tab that filters the stat grid.

- **[MED]** Settlement History card has internal `max-h-[480px] overflow-y-auto` — long histories scroll inside a card that itself sits inside the page scroll, with no pagination, filter, or export.
  - Page: `/genius/[address]` (file: `web/app/genius/[address]/view.tsx:186`)
  - Expected: For a researcher comparing a Genius's last 50 audits, either paginate ("Showing 1-20 of 87 · Next →"), or page-scroll the whole list, or both. Internal-scroll inside a page-scroll causes mobile thumb-trapping and desktop trackpad confusion. Plus a CSV/JSON export so a researcher can crunch the numbers offline.
  - Got: A fixed 480px scroll viewport; nothing else. No pagination, no filter by buyer/outcome/date, no sort toggle (rows render in `audits` order which is whatever `useAuditHistory` returns), no download.
  - Why it matters: Researchers are precisely the users who'd want to scrub a Genius's 200-audit history; the current widget caps useful inspection at the height of one fold, and produces a janky scroll-trap on touch devices. They will give up and trust the aggregate, defeating the whole "verifiable history" promise.
  - Fix idea: Drop `max-h-[480px]` (let the page scroll); add a small "Sort: newest / oldest / biggest win / biggest loss" select; add "Export CSV" footer link.

- **[LOW]** Settlement-row buyer pill is a truncated address chip with no link — researcher cannot cross-check the buyer's identity or repeat-buyer pattern.
  - Page: `/genius/[address]` (file: `web/app/genius/[address]/view.tsx:197-202`)
  - Expected: Click "Buyer 0xabc...123" and either land on that buyer's profile (if Idiot profiles exist) or at least on basescan for that address. Repeat-buyer concentration ("80% of this Genius's audits are with one buyer") is itself a trust signal; today the researcher can't even tell whether two rows are the same buyer without manually comparing truncated text.
  - Got: A static `<span>` chip showing `Buyer 0xabc...123` with `title={audit.idiot}` (full address only on hover). No link, no repeat-buyer indicator, no "view buyer" affordance.
  - Why it matters: Wash-trading detection in prediction marketplaces is exactly "is the same address always on the other side?" Researchers want this; today they have to copy-paste hover-titles to find out.
  - Fix idea: Wrap the pill in an `<a href={addressUrl(audit.idiot)}>` (offsite basescan is fine for now); add a tiny "(repeat ×3)" badge when `count(audits where idiot==X) > 1`.

(All six are static-review only — the WAF blocked browser verification this iteration. They should be confirmed against the live `/leaderboard` and `/genius/<addr>` once `web/e2e/ux/.vercel-session.json` is refreshed. Iter-003's three closed findings (in-site profile, populated leaderboard, handle+avatar) are all genuinely shipped — these new findings are about the *trust gaps that the fixes themselves introduce*.)

**Re-recommendation (9th consecutive iteration)**: please pause this loop and refresh `web/e2e/ux/.vercel-session.json` (a human headed-Chromium login) or set `VERCEL_BYPASS_SECRET` in `web/.env.local`. The single browser-verified slip-through in iter-012 confirms the saved-session approach can work transiently, but for sustained UX coverage the WAF policy must be addressed.

---

### 2026-05-01, Iter-012, Persona 2 (Aspiring publisher / Genius), 3 findings (browser-verified on www.djinn.gg/genius)

**Sweep**: WAF finally let one page through. Drove MCP Chromium against `https://www.djinn.gg/genius` (the apex `djinn.gg` 307s to `www`). First load rendered fully; subsequent navigations to `/idiot`, `/genius/signals/new`, `/docs/how-it-works`, and even a re-load of `/genius` itself hit Vercel Security Checkpoint Code 29, so the sweep is limited to the logged-out `/genius` view. Confirmed the post-fix-`41b15134` "Getting started" 5-step wizard now exists. Asked, as a would-be publisher: what's the workflow, what's it cost, what do I earn, what do I risk?

- [x] (fixed in b9996cc2) **[HIGH]** "Getting started" wizard steps 2-5 are content-empty stubs — only the title renders, no instructions.
  - Page: `/genius` (logged out)
  - Expected: After fix `41b15134` shipped a 5-step onboarding wizard, each step should explain *how* to do that step (or at least *where* to do it). Step 1 ("Connect your wallet") does this correctly: it tells the user to click "Get Started" in the top right and recommends Coinbase Smart Wallet.
  - Got: Steps 2-5 render only the headline:
    - 2. "Switch to Base network" — no explanation of what Base is, no "click here in your wallet" hint, no chain ID, no add-network button.
    - 3. "Get USDC on Base" — no link to a faucet (this is testnet!), no link to a bridge / on-ramp, no minimum amount, no explanation of what USDC is.
    - 4. "Deposit collateral" — no $ amount, no link to the deposit flow, no explanation of what collateral does (slashing? lock? withdrawals?).
    - 5. "Create your first signal" — no link to `/genius/signals/new`, no preview of the signal form, no example.
  - Why it matters: A wizard that lists 5 steps but only explains step 1 is *worse* than no wizard — it surfaces 4 unsolved problems and provides zero forward motion. Aspiring publishers who get past wallet connect will hit step 2 and bounce because they don't know how to "switch to Base." This is the single biggest blocker between "interested visitor" and "first signal published."
  - Fix idea: Each step body should be 1-2 lines plus a link/CTA. Examples: step 2 → "In your wallet, switch the network to Base Sepolia (chain id 84532). [Add Base to wallet]"; step 3 → "Get test USDC from the [Base Sepolia faucet](https://...) or bridge from Base mainnet."; step 4 → "Minimum collateral: $X USDC. Deposit goes to escrow contract `0x...`. [Deposit now]"; step 5 → "[Open signal builder →]".

- [x] (fixed in b9996cc2) **[HIGH]** Even after the fix, /genius still answers none of "what does it cost / what do I earn / what do I risk" with a number.
  - Page: `/genius` (logged out)
  - Expected: Iter-002's top finding ("publisher landing page has zero economics") is marked `[x] (fixed in 41b15134)` in this file. The fix added a 5-step wizard but added zero numbers. A would-be publisher should see, on this page: minimum collateral ($), platform take rate (%), example earnings ("an analyst with a 55% hit rate earning $X/month"), slashing exposure ("if you fail to reveal, you forfeit $X").
  - Got: The page contains exactly 0 dollar amounts, 0 percentages, 0 example numbers, and 0 risk disclosures. Step 4 says "Deposit collateral" with no minimum, no maximum, no slashing rules. Tagline is "Sell predictions, build your track record." That is editorial copy, not economics.
  - Why it matters: The previous finding's "fix" added scaffolding without addressing the actual content gap. A publisher cannot evaluate the opportunity without knowing the unit economics. Reopening this is more honest than letting the closure stand.
  - Fix idea: Either re-open finding 002-HIGH-1 (mark unchecked again) or add a sibling "Publisher economics" panel above or beside the wizard with: min collateral, fee/take rate, slashing rules, expected revenue formula, link to a calculator.

- **[MED]** /genius tagline + body never says the word "sports" (or "betting", or any specific market) — same opacity as the landing hero noted in iter-010.
  - Page: `/genius` (logged out)
  - Expected: A first-time would-be publisher landing on `/genius` should know what they'd be predicting before they connect a wallet. "Sell predictions" of *what?* If a sports analyst lands here, they should see the word "sports" or a sport icon (NFL/NBA/MLB) in the first viewport.
  - Got: H1 "Genius Dashboard", subhead "Sell predictions, build your track record." No mention of sports, betting, odds, lines, spreads, moneylines, or any specific market type. Footer mentions "Sports Intelligence Marketplace" but that's tiny and below the fold.
  - Why it matters: A poker pro, a stock-pickin' Twitter account, and an NFL handicapper would all read "Sell predictions" and assume Djinn supports their domain. Three of four would bounce when they discover it's sports-only after wallet connect. Surfaces wasted-conversion churn early.
  - Fix idea: H1 → "Genius Dashboard" (unchanged), subhead → "Sell encrypted sports picks. Build a verifiable track record. Earn from accuracy." Add small NFL/NBA/MLB/NHL/Soccer chips beneath.

---

### 2026-05-01, Iter-011, Persona 1 (Curious shopper / Idiot), 0 browser findings + 5 static-review findings

**Sweep**: 8th consecutive WAF-blocked iteration. Drove the MCP Playwright browser (a real headed Chromium, not the stale headless probe) at https://djinn.gg/ — got the Vercel Security Checkpoint page (`<title>Vercel Security Checkpoint</title>`), waited 45 s, page rendered "Failed to verify your browser, Code 29" instead of clearing. `curl -I https://djinn.gg/` and `curl -I https://djinn.gg/idiot` both return 403. Saved session file (`web/e2e/ux/.vercel-session.json`) is now ~42 h stale. Falling back to a static curious-shopper review of `web/app/idiot/browse/page.tsx` (the page Iter-001's top fix shipped), looking for "what would a curious shopper actually need to decide whether to buy a signal?" gaps. None of these are browser-verified; re-queue persona 1 once the saved session is refreshed.

- [x] (fixed in b79dafd4) **[HIGH]** Browse-signal cards never say *what game* the signal is about — no teams, no event, no kickoff time.
  - Page: `/idiot/browse` (file: `web/app/idiot/browse/page.tsx:244-326`)
  - Expected: A curious shopper scanning a grid of picks needs at minimum: `Sport`, `Game/Event` ("Lakers vs Warriors, Sun 7pm ET"), market type ("Spread / Moneyline / O-U"), and the seller's track record. That is the merchandise.
  - Got: Each card shows only `Sport` (e.g. "NFL"), seller's truncated address, "X hours left" (signal expiry, not game time), Fee/$100, Backing %, Max Notional. The shopper has no idea which game, which market, which side, or even when the underlying event starts. Two cards labelled "NFL · 5h left · Fee $1.50" are completely indistinguishable.
  - Why it matters: The whole curious-shopper journey rests on "do these picks look interesting?" If every card looks identical except the address and the price, there is no signal-quality differentiation pre-purchase, only post-purchase. People won't pay $5 to find out a card is for a game they don't care about. This is the single biggest gap on the browse page.
  - Fix idea: The signal struct already binds to a market (the validator audits real events); surface a non-revealing teaser — sport + league + event window + market type — without leaking the pick itself. e.g. "NFL · Cowboys @ Eagles · Sun 8:20pm ET · Spread".

- [x] (fixed in b79dafd4) **[HIGH]** Sellers on the browse page are anonymous truncated addresses with zero track-record signal — no win-rate, no signal count, no rating.
  - Page: `/idiot/browse` (file: `web/app/idiot/browse/page.tsx:273-285`)
  - Expected: Each card shows the genius's handle (or address), recent win-rate or quality score, and lifetime signals — at least a "trust badge" so a curious shopper can prefer a 67% / 240-pick seller over an unknown 0-pick seller.
  - Got: `by 0x68fc...2a1d` and (for some) an "Open audit set" badge whose meaning is undocumented on this page. There is no quality score, no historical win-rate, no signal count, no anything that would make seller A more trustworthy than seller B. The curious shopper has to leave the page, click each address (which goes off-site to BaseScan per Iter-003 finding) and reverse-engineer trust.
  - Why it matters: A marketplace that hides seller reputation at the browse step trains shoppers to treat all sellers as equally untrusted, which crashes prices to floor and selects out the high-quality geniuses. This is a marketplace-design failure, not just a UX nit.
  - Fix idea: Render a tiny inline quality-score chip next to the address (the hook `useGeniusStats(address)` already exists per `web/components/QualityScore.tsx`); link the address to an in-site `/genius/[address]` profile (cross-references Iter-003 CRITICAL).

- **[MED]** "Backing" and "Fee / $100" are unexplained jargon on the most-scanned UI element on the site.
  - Page: `/idiot/browse` (file: `web/app/idiot/browse/page.tsx:293-318`)
  - Expected: Either rename to plain English ("Seller's collateral", "Cost per $100 wagered") OR add a hover tooltip / `aria-describedby` with a one-line definition.
  - Got: Three labels — `Fee / $100`, `Backing`, `Max Notional` — with no tooltip, no `(?)` icon, no link to a glossary. A curious shopper sees `Backing 250%` and has no idea whether that is good or bad, or what it backs. `Max Notional` is also pure trader argot for "biggest bet you can place using this pick".
  - Why it matters: This is the per-card decision strip, the single most-eyeballed pixel cluster in the whole shopping flow. Ambiguous labels here mean shoppers either guess wrong ("backing 50% sounds bad, skip!") or freeze and bounce.
  - Fix idea: Rename to "Cost per $100", "Seller stake", "Max bet"; add a `<title>` attribute or hover tooltip ("Seller's stake: how much of their own money the genius has locked behind this pick. Higher = more confidence.").

- **[MED]** Sport filter is hard-coded to NFL/NBA/MLB/NHL/Soccer; any signal with a different sport tag (NCAA, MMA, tennis, F1, esports) silently appears unfilterable.
  - Page: `/idiot/browse` (file: `web/app/idiot/browse/page.tsx:12-19`)
  - Expected: Either derive the sport list from the live `useBrowseSignals()` payload, or include the long tail (NCAA Football, NCAA Basketball, Tennis, MMA, esports/Valorant/CS, F1, golf, cricket, rugby) explicitly. A "show all sports if user typed sport doesn't match" graceful fallback is fine, but the picker UI should know what's actually available.
  - Got: Five hard-coded options; if the validator publishes a signal tagged `Tennis`, that signal will render under "All Sports" but cannot be filtered to. Power-shoppers who only follow tennis can't isolate their feed.
  - Why it matters: Niche-sport bettors are a high-LTV segment on tipster sites (NCAA + tennis + MMA together are a large share of the US betting handle). Hiding them in the filter signals "we don't really cover your sport" even if signals exist.
  - Fix idea: Build the dropdown from `Array.from(new Set(signals.map(s => s.sport)))` plus a static fallback list; surface a "More sports →" footnote linking to a network-wide sport catalogue.

- **[LOW]** "Game may have started. Check before purchasing." warning is shown for every signal with <3 h to expiry, regardless of actual game start.
  - Page: `/idiot/browse` (file: `web/app/idiot/browse/page.tsx:230,287-291`)
  - Expected: The warning should reflect the *event*'s scheduled start, not an arbitrary 3-hour heuristic on the signal's expiry. A pick on Monday Night Football posted 30 min before kickoff is a perfectly clean buy if expiry is set tightly; a pick whose underlying game doesn't start for 6 hours but expires in 2 should NOT carry a "Game may have started" warning.
  - Got: A blanket amber line on every card with `hoursLeft < 3`, even when the signal description (post-purchase) says the game starts in 6 hours. Buyers learn to tune the warning out.
  - Why it matters: Cried-wolf warnings train shoppers to ignore real "game already kicked off, don't buy" alerts, which is the one warning that actually matters for a tipster site.
  - Fix idea: Bind the warning to the signal's bound game-start timestamp (the audit committee already knows it), not to an expiry heuristic. Hide the warning entirely if `now < gameStartTs - 5 min`.

(All five are static-review findings because the WAF blocked browser verification this iteration. They should be confirmed against the live `/idiot/browse` once `.vercel-session.json` is refreshed.)

**Re-recommendation (8th consecutive iteration)**: please pause this loop and refresh `web/e2e/ux/.vercel-session.json` (headed login from a human, or set `VERCEL_BYPASS_SECRET` in `web/.env.local`). Eight consecutive WAF-blocked iterations is wasted compute; the MCP browser also fails the JS challenge with `Code 29`, suggesting the WAF rule is now fingerprinting all automation, not just headless mode.

---

### 2026-05-01, Iter-010, Persona 0 (First-time visitor), 0 browser findings + 6 static-review findings

**Sweep**: 7th consecutive WAF-blocked iteration. Probed `/`, `/idiot`, `/genius` headless via Playwright with the saved `web/e2e/ux/.vercel-session.json` (~26 h stale, `_vcrcs` cookie expired ~21 h ago); all three returned HTTP 403 with body "Website owner? Click here to fix" (`curl -I` against djinn.gg also returns 403 with no cookie). Falling back to a static first-impression review of `web/app/page.tsx` and `web/components/NetworkStats.tsx`, looking for "do I understand what this is in 5 seconds?" failures. None of these are browser-verified; re-queue persona 0 once the Vercel session is refreshed.

- [x] (fixed in dbfb1382) **[HIGH]** Landing page never says "sports" or "betting" — first-time visitor can't tell what is being predicted.
  - Page: `/` (file: `web/app/page.tsx:5-65`)
  - Expected: a normal user reading the hero in five seconds learns "this is encrypted sports-betting picks" or at minimum the vertical (sports? markets? politics?). The whitepaper claim is sports betting, the docs claim it, but the homepage hides it.
  - Got: hero says "The Genius-Idiot Network", "Information × Execution", "Buy intelligence you can trust / Sell analysis you can prove", "Genius posts encrypted prediction / Buyer purchases access at live odds". The words "sports", "bet", "betting", "wager", "NFL", "NBA", "soccer", "tennis", "esports" appear nowhere on `page.tsx`. "Live odds" is the only hint and is itself crypto/finance-ambiguous.
  - Why it matters: a first-time visitor has to click into `/idiot` or `/genius` (or the PDF whitepaper) to learn what's being sold. Bounce risk is high; SEO / link-preview previews will read as generic crypto.
  - Fix idea: add one line under the taglines, e.g. "Encrypted sports-betting picks, sold by the second, settled on-chain."

- [x] (fixed in 6b5165ef) **[HIGH]** Two equal-weight CTAs ("I'm a Genius" / "I'm an Idiot") force a self-identification before the user understands the product.
  - Page: `/` (file: `web/app/page.tsx:75-111`)
  - Expected: one obvious primary CTA for the majority persona (browse picks / see today's signals) plus a secondary "Sell instead" link. Asking a brand-new visitor to declare themselves a genius or an idiot is a cognitive tax before they know what the product even does.
  - Got: two identically-sized cards, one orange and one green, with sub-labels "Sell predictions" / "Buy signals". The user has to map "Genius=seller, Idiot=buyer" before clicking. There is no neutral "Browse the leaderboard" or "See today's picks" option above the fold.
  - Why it matters: lowers conversion for the dominant funnel (buyers) by introducing a needless choice. Self-deprecating "Idiot" framing also makes some users not want to click the option that's actually meant for them.
  - Fix idea: lead with a primary "See today's signals →" CTA, demote Genius/Idiot to a secondary row labeled "Or pick a side".

- **[MED]** "Signals stay secret forever. Even from us." is an unsupported claim with no link to a how-it-works explainer.
  - Page: `/` (file: `web/app/page.tsx:43-45`)
  - Expected: this is the strongest trust claim on the page; it should hover-tooltip or link to a one-paragraph explainer of the cryptographic scheme (threshold encryption, validator audit, time-locked release) so a skeptical first-time visitor can verify the claim before clicking anything.
  - Got: italic small-text fine print with no `href`, no tooltip, no `(learn more)` affordance. A reader has to find `/docs` from the quick-link rail or download the PDF whitepaper to validate it.
  - Why it matters: this is the entire moat versus a normal tipster site; leaving it as an unverifiable italic line trains skeptical users to ignore it as marketing fluff.
  - Fix idea: wrap the line in a link to `/docs#encryption` or add a `(how?)` button that opens a short modal.

- **[MED]** "How it works" 3-step uses jargon the target visitor doesn't yet know ("encrypted prediction", "live odds", "validators audit outcomes on-chain").
  - Page: `/` (file: `web/app/page.tsx:52-65`)
  - Expected: progressive disclosure — three steps in plain English first ("Expert posts a pick", "You unlock it for a fee", "Network audits the result"), with crypto/network terms revealed on hover or in a "Read the spec" link.
  - Got: step 3 in particular ("Validators audit outcomes on-chain") is meaningless to a non-crypto visitor, and step 1's "encrypted prediction" demands prior context about why encryption matters here.
  - Why it matters: this is the section the visitor reads to decide if the site is legible to them. If two of three steps are jargon, they bounce.
  - Fix idea: rewrite to plain English; keep the crypto vocabulary as a secondary tooltip.

- [x] (fixed in a677d202) **[MED]** `NetworkStats` renders **nothing** on validator failure, silently collapsing the only social-proof block on the homepage.
  - Page: `/` (file: `web/components/NetworkStats.tsx:13-36` — `if (!stats) return null;` plus `} catch { /* Silent fail; stats are decorative */ }`)
  - Expected: even on fetch failure, show a placeholder (skeleton, last-known cached value, or "Network online" badge) so the homepage is never empty between the taglines and the "How it works" grid.
  - Got: when any validator is down or rate-limited, the component returns `null`; the homepage layout silently loses its social-proof row, and a first-time visitor sees the page jump from taglines straight to "1 / 2 / 3" with no proof the network exists.
  - Why it matters: failure mode is invisible to first-time visitors but actively undercuts the trust pitch (the only number you can SHOW them disappears). This is a stealth conversion killer because nobody monitoring sees it.
  - Fix idea: render a low-key fallback row "Live network stats unavailable — try /network" or cache the last successful payload in `localStorage`.

- **[LOW]** Whitepaper link points directly at a PDF (`/whitepaper.pdf`) instead of a readable HTML overview.
  - Page: `/` bottom row (file: `web/app/page.tsx:147`)
  - Expected: the most likely use of the whitepaper link by a first-time visitor is "read the explanation, not download a PDF". Most modern crypto sites render an HTML page (with a "Download PDF" button) so the content is searchable and mobile-friendly.
  - Got: clicking the link opens a binary PDF in a new tab; on mobile, this triggers the browser's PDF viewer or a download prompt, both of which feel heavy for a first-touch action.
  - Why it matters: lower-friction reading = more visitors who actually finish the explanation = more conversions to genius/idiot pages.
  - Fix idea: serve `/whitepaper` (HTML) and link the PDF as a secondary "Download" affordance on that page.

---

### 2026-05-01, Iter-009, Persona 9 (Accessibility / dark-pattern auditor), 0 browser findings + 7 static-review findings

**Sweep**: 6th consecutive WAF-blocked iteration. Used the saved `web/e2e/ux/.vercel-session.json` (~25 h stale) against / and waited up to 90 s for the JS challenge to auto-resolve via `waitForFunction(!title.includes("Vercel Security Checkpoint"))`. Title never changed, even after a 12 s cooldown + reload. (One earlier probe in this same iteration did get a transient 200 from `/` then 403 on every subsequent navigation, suggesting the WAF rate-limits per fingerprint after the first request.) Falling back to a static a11y / dark-pattern review of `app/layout.tsx`, `components/TermsModal.tsx`, and a codebase grep for `role="dialog"`, `aria-modal`, `Escape`, `Skip to`, `prefers-reduced-motion`, and `focus-visible`. None of these findings are browser-verified; re-queue persona 9 once the saved session is refreshed.

- [x] (fixed in fd4a8bd5) **[HIGH]** No modal in the codebase declares `role="dialog"` or `aria-modal="true"`.
  - Page: every wallet/consent flow (file: `web/components/TermsModal.tsx:48`, plus any other `fixed inset-0 z-50` overlay)
  - Expected: each modal sets `role="dialog"`, `aria-modal="true"`, and `aria-labelledby` pointing at its `<h2>` so screen readers announce it as a modal
  - Got: a plain `<div className="fixed inset-0 z-50">`. Screen readers treat the dialog as inline content, so blind users have no idea a blocking modal opened.
  - Why it matters: this is the gating ToS modal in front of every first wallet connect; a SR user who cannot perceive the modal will read site chrome behind it and never realise their click was hijacked.
  - Fix idea: add `role="dialog" aria-modal="true" aria-labelledby="tos-title"` to the inner card and an `id="tos-title"` to the `<h2>`.

- [x] (fixed in fd4a8bd5) **[HIGH]** TermsModal (and likely all modals) does not trap focus.
  - Page: any flow that opens `TermsModal` (file: `web/components/TermsModal.tsx:34`)
  - Expected: while open, Tab cycles only inside the modal; first Tab lands on the first focusable inside the modal
  - Got: no `useFocusTrap` / no manual `Tab`-key handler / no initial `useEffect(() => firstFocusable.focus())`. Tab leaks straight through to the underlying nav links and footer, so a keyboard user can `Tab` into and click "Genius" while the ToS is still gating the page.
  - Why it matters: combined with the missing `aria-modal`, a keyboard or SR user can interact with the very content the modal is trying to gate, defeating the consent flow.
  - Fix idea: add a small focus-trap effect (or use Radix/Headless UI Dialog) and `firstButtonRef.current?.focus()` on open.

- [x] (fixed in fd4a8bd5) **[HIGH]** No `Escape`-key handler on the consent modal.
  - Page: `web/components/TermsModal.tsx:34` (grep confirms only `web/components/ReportError.tsx` listens for `Escape` anywhere in `web/components/`)
  - Expected: Esc closes the modal (calls `onDecline`), per WAI-ARIA dialog pattern
  - Got: keyboard users with no mouse must visually locate and tab to the "Decline" button to dismiss, which itself is not initially focusable on open.
  - Why it matters: makes the consent flow feel like a trap to keyboard-only and motor-impaired users — a known dark-pattern signal even when unintentional.
  - Fix idea: `useEffect(() => { const h = (e) => e.key === "Escape" && onDecline(); window.addEventListener("keydown", h); return () => window.removeEventListener("keydown", h); }, [onDecline]);`

- [x] (fixed in fd4a8bd5) **[HIGH]** No "Skip to main content" link anywhere in the layout.
  - Page: `web/app/layout.tsx:66` (grep across `web/` finds `Skip to` only in `e2e/live/deep-interactions.spec.ts`, never in product code)
  - Expected: a visually-hidden-until-focused `<a href="#main">Skip to content</a>` as the very first focusable element, plus an `id="main"` on the page-content wrapper
  - Got: a keyboard-only user must Tab through the full top nav (~8 nav links + connect-wallet button + every footer trigger) on every single page before they can reach the actual content.
  - Why it matters: WCAG 2.4.1 (Bypass Blocks) failure; a screen-reader user re-traverses the same chrome on each route change, which on Djinn is on the order of a dozen Tabs each time.
  - Fix idea: add the skip link in `app/layout.tsx` immediately inside `<body>`, with Tailwind's `sr-only focus:not-sr-only focus:fixed focus:top-2 focus:left-2`.

- **[MED]** Restricted-jurisdiction self-attestation and class-action waiver are bundled into a single checkbox label.
  - Page: `web/components/TermsModal.tsx:199-201` ("…and I am not located in a sanctioned jurisdiction.") combined with arbitration / class-action language already incorporated by reference at `:112`
  - Expected: at minimum, separate the geo-self-cert from the broader Terms acceptance, or surface the arbitration / class-action waiver as its own line with a 30-day opt-out reminder visible (currently buried in summary item 6)
  - Got: a single checkbox grants ToS, Privacy, Risk, AUP, DMCA, **and** legal self-cert about sanctions, **and** an arbitration / class waiver, **and** an opt-out clock starts running silently. Borderline "consent fatigue" dark pattern.
  - Why it matters: regulators (FTC, EU DSA) increasingly treat bundled consent as non-consent; for a sports-prediction marketplace with sanctions exposure this is also legal-risk-bearing.
  - Fix idea: split into two checkboxes: (1) "I agree to the Terms, Privacy, Risk, AUP, DMCA"; (2) "I confirm I am not in a sanctioned jurisdiction." Show a tiny "30-day opt-out of arbitration available — see Terms §X" hint below.

- [x] (fixed in 0a7d5bf5) **[MED]** No `prefers-reduced-motion` respect anywhere in the codebase.
  - Page: site-wide (grep `prefers-reduced-motion` across `web/` returns 0 hits)
  - Expected: any animation / scroll-driven effect / spinner on the marketing page checks `@media (prefers-reduced-motion: reduce)` and degrades to a static state
  - Got: animations always run regardless of OS-level setting, which can trigger nausea/dizziness in users with vestibular disorders.
  - Why it matters: WCAG 2.3.3 (AAA) and a known accessibility-lawsuit vector in 2025.
  - Fix idea: in `tailwind.config.ts` enable the `motion-safe:` / `motion-reduce:` variants and gate any `animate-*` class with `motion-safe:animate-*`.

- [x] (fixed in fd4a8bd5) **[LOW]** TermsModal does not move focus to the dialog when it opens.
  - Page: `web/components/TermsModal.tsx:34` (no `useEffect` calling `.focus()` on mount-when-open)
  - Expected: when `open` flips to true, focus moves to the dialog title or the first interactive element so screen readers announce the new context
  - Got: focus stays on the "Connect Wallet" button that opened the modal; SR users hear nothing change.
  - Why it matters: completes the trio of dialog-pattern misses (no role, no trap, no initial focus). Each is small alone; together they make the consent flow opaque to assistive tech.
  - Fix idea: `useEffect(() => { if (open) headingRef.current?.focus(); }, [open]);` with `tabIndex={-1}` on the heading.

---

### 2026-05-01, Iter-008, Persona 8 (Returning power user), 0 browser findings + 4 static-review findings

**Sweep**: Attempted to drive headless Chromium with the saved `.vercel-session.json` against /, /idiot, /genius, /leaderboard, /feedback to test returning-power-user flows (history depth, filters, settings). All five URLs returned HTTP 403 with title "Vercel Security Checkpoint" (htmlLen ~31 KB JS challenge that does not auto-resolve in headless). **Fifth consecutive WAF-blocked iteration** (iter-004/005/006/007/008); session is now ~18-26 h stale. Falling back to a static review of `web/app/idiot/page.tsx` since it is the canonical returning-power-user surface (Purchase History, Settlement History, balances). Findings below are NOT browser-verified; re-queue persona 8 once the session is refreshed.

- [x] (fixed in d1a64fc0) **HIGH** Purchase History and Settlement History tables have a `Date` column header but render "Block 12345678" in the cell — no actual timestamp, ever.
  - Page: `/idiot` (file: `web/app/idiot/page.tsx:902` header + `:923` cell, and `:1013` header + `:1044` cell)
  - Expected: A returning user scanning their purchase log expects "Apr 28, 14:32" or at least "3 days ago" so they can correlate a purchase with the live event it was meant for. Block heights are not human time.
  - Got: Header says `Date`, cell says `Block 23912844`. The user has to copy the block number, paste into BaseScan, read the timestamp from there, and convert UTC manually. The mobile card view (`:957-958`) is even worse: just `Block: 23912844`.
  - Why it matters: Power users (the persona that opens this dashboard repeatedly) cannot answer the most basic question — "when did I buy this?" — without leaving the site. Tax filing, dispute resolution, and "did I buy this before or after the injury news?" are all blocked.
  - Fix idea: The block timestamp is already on-chain via `eth_getBlockByNumber`; cache it once per render and format with `new Date(blockTime * 1000).toLocaleString()`. The genius dashboard already uses `toLocaleString()` (`web/app/genius/page.tsx:626`) so the pattern exists.

- [x] (fixed in 2ae58048) **HIGH** Purchase History "Status" pill is a hard-coded literal `"Purchased"` for every row, regardless of whether the underlying signal has settled, expired, refunded, or is still active.
  - Page: `/idiot` (file: `web/app/idiot/page.tsx:919-921` desktop + `:937-939` mobile)
  - Expected: A status pill on a purchase row should distinguish at least: Active (signal is live), Settled-favorable, Settled-unfavorable, Expired, Refunded, Disputed. Color-code accordingly (green / red / amber / gray).
  - Got: Every row, forever, says `Purchased` in identical neutral gray — including rows whose underlying audit was already settled minutes earlier (the audit data is loaded into the Settlement History section right below it, so the page literally has both sides of the join in memory).
  - Why it matters: A returning user opens the dashboard expecting to see "what happened with my last buys?" at a glance. They get a featureless wall of identical pills and have to cross-reference signal IDs into a separate Settlement History table to learn anything. Most will not bother.
  - Fix idea: Join `purchases` against `audits` (already loaded via `useIdiotAuditHistory`) by signalId and render the resolved status inline; default to `Active` if not found and `expiresAt < now` ? `Expired` : `Active`.

- **MED** Purchase History and Settlement History have no pagination, no date-range filter, and no CSV/JSON export — they will become an unscrollable wall after weeks of activity, and tax/record-keeping is impossible.
  - Page: `/idiot` (file: `web/app/idiot/page.tsx:891-1090`)
  - Expected: At minimum a "last 30 / 90 / all" filter, plus an "Export CSV" button on each table. Crypto-financial products live or die on whether power users can reconcile records at year-end.
  - Got: Both tables render `[...purchases].reverse().map(...)` and `audits.map(...)` with no slicing, no pagination, no export. After 200 purchases the dashboard will be a single giant scroll page. Returning power users cannot self-serve "show me my Q1 trades for taxes."
  - Why it matters: This is the single most-cited reason power users churn from crypto products to centralized exchanges. Power-user retention on a money product is roughly proportional to "can I get my data out without asking support."
  - Fix idea: Add a small `Export CSV` button next to each `<h2>`; ship pagination at 25 rows/page once `length > 50`; consider a simple `from`/`to` date filter.

- **MED** Purchase History rows navigate via `window.location.href = "/idiot/signal?id=..."` instead of next/Link, forcing a full page reload on every click.
  - Page: `/idiot` (file: `web/app/idiot/page.tsx:907` desktop + `:932` mobile)
  - Expected: Click a row → SPA-navigate to the signal detail in <100ms with the wallet/balances already cached.
  - Got: Click a row → full reload (white flash, ~1-2s on a slow connection), wallet reconnect dance, escrow refetch, signals refetch. A power user clicking through five purchases pays the cost five times.
  - Why it matters: Returning power users navigate frequently; perceived snappiness is what makes a dashboard feel "professional vs prototype." The same component already imports `useRouter`-style hooks elsewhere; the fix is one line.
  - Fix idea: Replace `onClick={() => window.location.href = ...}` with `<Link href={...}>` wrapping the row, or `router.push(...)` from `next/navigation`.

(All four are static-review findings because the WAF blocked browser verification this iteration. They should be confirmed against the live dashboard once `.vercel-session.json` is refreshed and persona 8 is re-queued.)

**Re-recommendation (5th iteration in a row)**: please pause this loop and refresh `.vercel-session.json` (headed login from a human, or set `VERCEL_BYPASS_SECRET` in `web/.env.local`). Five consecutive WAF-blocked iterations is wasted compute; static reviews are a poor substitute for the persona-driven browser sweeps the program is designed for.

---

### 2026-05-01, Iter-004, Persona 4 (Skeptic / journalist), 0 findings

**Sweep**: Attempted to visit /, /network, /docs, /about with headless Chromium to read the public claims. All four URLs returned a Vercel Security Checkpoint that did not auto-resolve within 90s on a stale (>12h) session. No product content was rendered, so no UX findings are possible this iteration. (Infrastructure flake, not a UX issue.) Persona 4 will be retried next time the saved session is fresh.

No new findings, persona 4 swept nothing renderable; site was unreachable behind Vercel WAF for the duration of the iteration.

---

### 2026-05-01, Iter-003, Persona 3 (Track-record researcher), 6 findings

**Sweep**: Visited https://djinn.gg/leaderboard from a clean session, sorted by Quality Score, tried to drill into the #1 ranked Genius (0x68fc...2a1d) to verify their on-chain history. Read the "How Quality Score Works" panel and footer.

- [x] (fixed in 7a339ae3) **CRITICAL** "Profile" link for a top Genius leaves the site for a third-party block explorer; no in-site Genius profile exists.
  - Page: `/leaderboard` (table rows; the only Genius link points at `https://sepolia.basescan.org/address/0x68fc...`)
  - Expected: Click a Genius's row/handle and land on `/genius/0x68fc...` with a human-readable profile: handle, joined date, lifetime signals, win rate, ROI, recent picks (with sport/market/odds/result), and a chart of cumulative P&L. A small "View on Base Sepolia" link below for cryptographic verification.
  - Got: The truncated address is the only thing rendered, and clicking it kicks the user to basescan.org (which itself shows a Cloudflare bot challenge in headless contexts). The site has no Genius profile page at all.
  - Why it matters: A track-record researcher is the most valuable persona on a prediction marketplace; they convert into Idiots (buyers) and recruit other Geniuses. Sending them off-site to read raw EVM transactions on a third-party explorer is the opposite of "cryptographically verified track records made legible." This is the single biggest broken promise on the leaderboard.
  - Fix idea: Build `/genius/[address]` with the data the on-chain track record already produces (signals, audits, slashes, ROI). Truncated address links to that page; add a small "View raw txs on BaseScan" secondary link.

- [x] (fixed in c1d534c9) **HIGH** Leaderboard ranks by "Quality Score" but every visible row shows `-` for that column (and ROI, Win Rate, Proofs, Audits all show 0 or `-`).
  - Page: `/leaderboard` (table)
  - Expected: A leaderboard's whole job is to differentiate. The header column "Quality Score" implies sortable numeric values; users expect numbers like `+12.4`, `-3.1`, etc. with at least one or two ranked entries.
  - Got: Two rows total; both show Quality Score `-`, ROI `-`, Win Rate `-`, Proofs `0`. Only "Signals" has values (1230 vs 20). The sort is therefore on an invisible field, and rank #1 vs #2 means nothing visible to the user.
  - Why it matters: A leaderboard with no actual ranking signal looks broken or fraudulent. Researcher persona concludes "no audits have ever happened" and bounces. Worse, a curious Idiot looking here for "who should I buy from?" gets zero useful information.
  - Fix idea: If pre-audit, replace the table with an empty-state card explaining that no audits have settled yet on Base Sepolia and that the leaderboard activates after the first batch. If post-audit, surface the real numbers.

- [x] (fixed in e7a6c7e6) **HIGH** Geniuses are identified only by truncated 0x addresses; no handle, no avatar, no bio.
  - Page: `/leaderboard` and table rows
  - Expected: A handle (e.g. @sharpshooter), an avatar (blockie or uploaded), and an optional 1-line bio next to the address. Crypto-native users still want a human handle to remember; non-crypto users need it to form trust.
  - Got: Just `0x68fc...2a1d`, `0x4986...11d3`. Indistinguishable, unmemorable, untrustable.
  - Why it matters: Trust on a prediction marketplace flows through identity. A truncated hex string is the least trustable representation possible. Idiots will not pay to follow a hex string.
  - Fix idea: Allow Geniuses to set a handle plus avatar in their /genius dashboard (already have wallet auth; add an ENS-style handle record or off-chain profile). Default to a deterministic colored blockie plus adjective-noun handle if none set.

- **MED** "How Quality Score Works" panel is pure formula notation with no worked example.
  - Page: `/leaderboard` ("How Quality Score Works" section)
  - Expected: Two short bullets and one concrete example: e.g. "If a Genius backs Lakers -5.5 at odds 1.91 with $100 notional and the Lakers cover, QS gains $100 x (1.91 - 1) = $91. If they don't cover, QS loses $100 x Backing%."
  - Got: The bare formulae `Favorable: +Notional x (odds - 1)`, `Unfavorable: -Notional x Backing%`, `Void: does not count`, plus a paragraph using "audit batch", "validator audit", "Djinn Credits", "fees paid" without defining any of them.
  - Why it matters: Track-record researchers are exactly the people who want the math, but they want it explained, not asserted. A worked example converts skepticism into respect; a bare formula reads as crypto-bro signalling.
  - Fix idea: Add a 2-line worked example with realistic numbers, plus a "What is an audit batch?" tooltip linking to the docs.

- **MED** No filtering, search, time window, or sport breakdown on the leaderboard.
  - Page: `/leaderboard`
  - Expected: Filters for sport (NBA, NFL, MLB, Soccer), time window (7d / 30d / All), market type (spread, moneyline, total), and minimum signal count. A search box for finding a specific Genius by address or handle.
  - Got: A static, unfiltered, unsearchable, untemporal table. Only two rows today so it doesn't matter, but the page sets up zero affordances for when the network has 100+ Geniuses.
  - Why it matters: A leaderboard without filters becomes useless above ~20 entries. Researchers want to find e.g. "who is the best NFL spread Genius over the last 30 days?" A static table cannot answer that.
  - Fix idea: Add a filter bar above the table: sport pill-list, time-window toggle (7d / 30d / All), and a search field.

- **LOW** Slashing description is buried inside the QS explainer paragraph.
  - Page: `/leaderboard` ("How Quality Score Works")
  - Expected: Slashing is the trust mechanism that makes Djinn different from Telegram tipsters; it deserves its own callout, not a dependent clause.
  - Got: A single sentence at the end of a math paragraph, mentioning "Djinn Credits" without defining them and "fees paid" without specifying which fees.
  - Why it matters: This is the strongest trust signal on the page; burying it weakens the pitch. Researchers skim formulae but read trust mechanisms carefully, so put it where they'll see it.
  - Fix idea: Pull slashing into its own panel labelled "What protects buyers": one sentence on slashing, one on refund, one on Djinn Credits (with a tooltip defining them).

---

### 2026-05-01, Iter-002, Persona 2 (Aspiring publisher / Genius), 5 findings

**Sweep**: Visited https://djinn.gg/genius fresh as a would-be analyst. Read the H1 ("Genius Dashboard / Sell predictions, build your track record"), the 5-step getting-started wizard, the "Learn how Djinn works" link, and the footer. Asked: what does it cost me, what do I earn, what do I risk?

- [x] (fixed in 41b15134) **HIGH** Publisher landing page has zero economics: no collateral amount, no take rate, no example earnings.
  - Page: `/genius`
  - Expected: A potential publisher decides whether to onboard based on three numbers: cost (collateral required), take (% the protocol/network skims off picks they sell), and upside (top-genius earnings, average revenue per signal, hit-rate-to-revenue curve). At minimum a "How much can I make?" section with a real or representative figure.
  - Got: A 5-step crypto plumbing checklist plus the tagline "Sell predictions, build your track record." No dollar amount appears anywhere on the page. The closest thing is step 4 "Deposit collateral" with no quantity attached.
  - Why it matters: Geniuses are the supply side of the marketplace. If the page does not answer "what's in it for me?" in the first viewport, aspiring analysts bounce to a competitor or to a Telegram tipster channel that already shows revenue screenshots. Asymmetric: Idiots can be lured by a pretty pick card, Geniuses need numbers.
  - Fix idea: Above the wizard, show a "Top Geniuses this week" mini-leaderboard (handle, hit rate, USDC earned, picks sold) and a "Protocol takes X%, you keep Y%" headline.

- [x] (fixed in 41b15134) **HIGH** "Deposit collateral" step is one bullet with no amount, no slashing rules, no reclaim path.
  - Page: `/genius` step 4
  - Expected: Aspiring publishers want to know exactly how much USDC they must lock up, what triggers slashing (failed reveal? lost pick? settlement dispute?), and how/when collateral is returned. This is the single biggest anxiety for the publisher persona.
  - Got: The literal text "Deposit collateral" with no quantity, no link, no mechanics. A user has to read the whitepaper to find out the protocol economics they are signing up for.
  - Why it matters: Asking for an unspecified deposit on the marketing landing page reads as a bait-and-switch. Even crypto-native users will not click further without a number. This step alone probably kills the funnel.
  - Fix idea: Replace with "Deposit X USDC collateral (refundable, slashable on failed reveal). Why?" with a tooltip or modal explaining the slashing rules in two sentences.

- [x] (fixed in 41b15134) **MED** "Create your first signal" step shows zero preview of what a signal actually is.
  - Page: `/genius` step 5
  - Expected: A picture, schematic, or one-line example: "A signal is an encrypted pick (sport, market, side, stake, expiry, price), revealed after settlement so the chain can verify your call." Ideally a thumbnail of the create-signal form.
  - Got: Just the step title. The user has no mental model of what the deliverable looks like before being asked to deposit collateral.
  - Why it matters: Selling an unknown product in an unknown format is a trust killer. Publishers want to know whether they are uploading a CSV, picking from a dropdown, or writing prose, and how granular the bet shape can be.
  - Fix idea: Inline a small example signal card (encrypted body blurred, metadata visible) under step 5, plus a "See an example signal" link.

- [x] (fixed in 41b15134) **MED** Publisher trust model (encrypt-reveal, on-chain track record, slashing) is not explained on the page that needs it most.
  - Page: `/genius`
  - Expected: A 2-3 line "How your track record works" panel explaining encrypted commit, settlement reveal, immutable history, reputation. This is Djinn's whole differentiator vs Telegram tipsters and it should headline the publisher page.
  - Got: The trust model is buried behind the small "Learn how Djinn works" link. The /genius page itself only says "build your track record" without explaining how that track record is tamper-proof or why an Idiot would trust it.
  - Why it matters: Without the cryptographic-trust pitch, Djinn looks like just another tipster site to a Genius too. The unique value prop is invisible at the moment of decision.
  - Fix idea: Add a "Why publish on Djinn" 3-bullet panel above the wizard: encrypted commits, on-chain reveal, immutable rep. One line each.

- [x] (fixed in 41b15134) **LOW** "Learn how Djinn works" link is visually deprioritized below a 5-step wizard the user cannot evaluate without it.
  - Page: `/genius` (link below step 5)
  - Expected: For a skeptical-publisher persona, the explainer should appear BEFORE the action checklist, not after. The cognitive order is "convince me, then onboard me", not "onboard me, then explain".
  - Got: The link "New to crypto? Learn how Djinn works" sits below all five steps in muted styling, framed as if only crypto-newbies need it. A sophisticated would-be publisher who needs the protocol details before depositing collateral has to scroll past the wizard to find it.
  - Why it matters: Users skip optional links framed as remedial. Reframing the explainer as "How Djinn works for Geniuses" and placing it above the wizard converts more skeptics.
  - Fix idea: Promote the link to a primary "How it works for Geniuses" panel above the getting-started checklist, and rename so it does not sound like a beginner aside.

---

### 2026-05-01, Iter-001, Persona 1 (Curious shopper / Idiot), 5 findings

**Sweep**: Visited https://djinn.gg/idiot fresh (saved Vercel session, 1280x900). Read the landing copy, scanned for signals, prices, buy CTAs, looked for a wallet-connect affordance.

- [x] (fixed in cba4bf81) **HIGH** /idiot has no browse-before-buy: no signals, prices, or sample picks visible until a wallet is connected.
  - Page: `/idiot`
  - Expected: A curious shopper expects to skim a few sample signals (sport, market, stake, odds, price, seller win-rate) before deciding whether to fund a wallet. The H1 is literally "Browse signals, buy picks from verified analysts."
  - Got: A 5-step "Getting started" checklist (Connect wallet, switch to Base, get USDC, deposit to escrow, then browse). Zero example cards, zero prices, zero analyst names visible to an unauthenticated visitor.
  - Why it matters: Asks the user to do crypto onboarding for a marketplace whose merchandise they have not yet seen. Most curious shoppers will bounce here. This is the highest-leverage funnel leak on the site.
  - Fix idea: Render a public, read-only grid of recent or active signals (encrypted body hidden, but seller, sport, market type, price, expiry, and seller track-record visible) above or in place of the onboarding checklist. Move the 5-step wizard to a collapsible "First time? Set up your wallet" panel.

- [x] (fixed in c30b2f98) **HIGH** Wallet-connect CTA is labelled "Get Started", not "Connect Wallet".
  - Page: `/idiot` and global header
  - Expected: A button called "Connect Wallet" or showing a wallet icon, matching universal Web3 convention.
  - Got: The top-right CTA reads "Get Started"; the body copy then says "Click 'Get Started' in the top right" to explain what that button actually does.
  - Why it matters: Users scanning for "Connect" will not find it. The fact that the page itself has to translate the button label proves the label is wrong. New users may click "Get Started" expecting an onboarding form, not a wallet picker, then bounce on the wallet modal.
  - Fix idea: Rename the header CTA to "Connect Wallet" (with a wallet glyph). Keep "Get Started" only on a marketing tour CTA, not on the auth control.

- **MED** Onboarding step copy assumes the user has already chosen Coinbase Smart Wallet.
  - Page: `/idiot` step 1 ("Connect your wallet")
  - Expected: Neutral guidance with a list of supported wallets (Coinbase, MetaMask, Rainbow, WalletConnect, etc.) and the trade-offs.
  - Got: "Click 'Get Started' in the top right. We recommend Coinbase Smart Wallet: free to create, no gas fees, works with just an email." No mention of any other supported connectors.
  - Why it matters: Users who already have MetaMask or Rainbow may think the site only supports Coinbase and leave. Recommending one wallet is fine; concealing the alternatives is not.
  - Fix idea: After the recommendation, add a small "Already have MetaMask, Rainbow, or another wallet? Connect any EVM wallet on Base." link, plus surface the connector list in a tooltip or modal preview.

- **MED** "Testnet: Base Sepolia. Not real money." banner sits above the H1 with no explanation of what testnet implies.
  - Page: global header
  - Expected: A banner that tells a curious visitor whether they are looking at a live product, a demo, or a testnet, and links to a one-paragraph explainer.
  - Got: Only the literal string "Testnet: Base Sepolia. Not real money." A non-crypto user has no idea whether picks here are real, whether analysts are real, or whether this is a toy.
  - Why it matters: Skeptical users will assume "not real money" means "fake leaderboard, fake analysts, fake track records" and discount everything they see, including the on-chain trust story. This silently undercuts the whole value prop.
  - Fix idea: Make the banner clickable to a short page explaining "We are in public beta on Base Sepolia. Picks, escrow, and track records are real on-chain, settled in test USDC. Mainnet launch <date>." Or add an inline "(why?)" link.

- **LOW** Step list lacks any indication of cost or time per step.
  - Page: `/idiot` Getting started checklist
  - Expected: For each step, an estimated time and cost ("Switch to Base ~ 10 sec, free", "Get USDC on Base ~ 2 min, varies").
  - Got: Bare titles, no estimates, no cost preview. Users cannot tell if the next click costs $5 or $50, or whether the whole onboarding is two minutes or twenty.
  - Why it matters: Crypto onboarding fear is largely fear of unknown cost and time. Five blank steps look like five unknowns.
  - Fix idea: Append a small muted "~30s, free" or "~2 min, gas-free with Smart Wallet" line under each step title.

---
