# Vercel break-glass → IPFS cutover runbook

Trigger: Vercel account is suspended, terminated, or institutes policy that conflicts with the protocol. This runbook moves `djinn.gg` off Vercel and onto the IPFS mirror in under 10 minutes.

Context: Per [DEV-045](../../DEVIATIONS.md#dev-045), Vercel is the day-to-day serve layer and IPFS is the sovereign canonical source. Every push to `main` pins a fresh CID to Lighthouse + Crust via [`.github/workflows/ipfs-mirror.yml`](../../.github/workflows/ipfs-mirror.yml) and updates `_dnslink.djinn.gg`. The bundle you cut over to already exists.

## Pre-flight (do once, before you need this)

- [ ] CI has run successfully on the latest `main`; the `ipfs-mirror` workflow summary shows a fresh CID.
- [ ] `dig _dnslink.djinn.gg TXT +short` returns `dnslink=/ipfs/<CID>`.
- [ ] `curl -sI https://gateway.lighthouse.storage/ipfs/<CID>/ | head -3` returns `200`. (Lighthouse is our primary pinner; this is the gateway most likely to serve a fresh CID before DHT propagation. Do NOT substitute `cloudflare-ipfs.com` — Cloudflare sunsetted its public IPFS gateway in 2024 and the host no longer resolves.)
- [ ] Namecheap API is whitelisted for at least one operator IP (so you can script the cutover). Check by running `node scripts/update-dnslink.mjs _dnslink <CURRENT_CID>` from that IP — should be a no-op confirmation.
- [ ] Backup copy of every `NEXT_PUBLIC_*` value is in `~/djinn/web/.env.production` (these are public but they're load-bearing for a clean build).

## Cutover decision tree

```
Vercel is dead
├── Do we need to rebuild the bundle?
│   ├── NO (latest pinned CID is good) → skip to step 3
│   └── YES (uncommitted changes or CI broken) → steps 1–2
└── Can we reach Namecheap API?
    ├── YES → script steps 3–5
    └── NO  → manual Namecheap UI fallback (bottom of this doc)
```

## Procedure (~10 min total)

### Step 0 — Verify Vercel really is gone

30 seconds. Don't cutover on a false positive.

```bash
curl -sI https://djinn.gg | head -3
curl -sI https://djinn.gg/about | head -3
```

If both return `5xx` or `404` and the Vercel dashboard shows suspension, proceed. A brief `503` is usually a deploy, not a suspension — wait 2 minutes.

### Step 1 — (only if rebuilding) Build + pin from dev box

Skip if the last CI-pinned CID is acceptable. Usually it is.

```bash
cd ~/djinn/web
pnpm install --frozen-lockfile
pnpm build:ipfs
cd ..

# Pin to Lighthouse + Crust from the dev box
export LIGHTHOUSE_API_KEY=$(grep LIGHTHOUSE_API_KEY ~/.lighthouse.env | cut -d= -f2)
out=$(node scripts/pin-lighthouse.mjs web/.next-ipfs "djinn-gg-breakglass-$(date +%s)")
CID=$(echo "$out" | node -e 'let s="";process.stdin.on("data",d=>s+=d).on("end",()=>{console.log(JSON.parse(s).cid)})')
echo "CID: $CID"

export CRUST_PRIVATE_KEY=$(grep CRUST_PRIVATE_KEY ~/.crust.env | cut -d= -f2)
node scripts/pin-crust.mjs "$CID" "djinn-gg-breakglass-$(date +%s)"
```

Record the CID. If this step fails, skip to Step 2 with the last known-good CID from the most recent `ipfs-mirror` workflow run.

### Step 2 — Smoke test the bundle via a public gateway

```bash
curl -sI "https://gateway.lighthouse.storage/ipfs/$CID/" | head -3   # our pinner's gateway; always works when pin succeeded
curl -sI "https://ipfs.io/ipfs/$CID/" | head -3                       # DNSLink-aware; often lags on fresh CIDs
curl -sLI "https://dweb.link/ipfs/$CID/" | head -5                    # Storacha; DNSLink-aware
```

Lighthouse's own gateway must return `200` (that's our pin, full stop). The other two are DHT-dependent and may `504` on a fresh CID — fine for the break-glass path since Lighthouse covers us. If Lighthouse is also 5xx, the pin itself failed or de-pinned; fall back to Option C (VPS Nginx stopgap) below.

### Step 3 — Point apex `djinn.gg` at an IPFS gateway

This is the load-bearing step. The apex `A` record currently points at Vercel's IP. Change it to point at a live IPFS gateway, or (for fastest recovery) at our own VPS.

> **The Cloudflare IPFS gateway was sunsetted in 2024 and `cloudflare-ipfs.com` does not resolve.** Earlier revisions of this runbook treated it as the recommended target; they were wrong. Do not CNAME anywhere to `cloudflare-ipfs.com`.

**Option A (recommended for speed) — VPS Nginx stopgap.** Point apex `A` at `161.97.138.250` (production VPS). Nginx already serves `*.djinn.gg` there. Serve the static export from `/var/www/djinn/` via a new `server_name djinn.gg www.djinn.gg` block. This is fastest because DNS is the only change and the VPS is our own infrastructure (no third-party flakiness).

```bash
# From production VPS (ssh root@161.97.138.250):
mkdir -p /var/www/djinn
rsync -avz --delete ~/djinn/web/.next-ipfs/ /var/www/djinn/
# If nginx config not already present, add a server block with
# root /var/www/djinn; and try_files $uri $uri/index.html /index.html;
nginx -t && systemctl reload nginx
```

Namecheap UI → Domain List → `djinn.gg` → Advanced DNS → edit apex `A` to `161.97.138.250`, TTL 60.

Trade-off: this violates the "no VPS fallback" principle from [project memory](../../.claude/projects/-home-user-djinn/memory/feedback_decentralization_means_decentralized.md). That principle is about the default state; during a break-glass event, getting back online beats ideological purity. Post-incident, migrate off the VPS back to IPFS once the ecosystem situation is clarified.

**Option B — DNSLink-aware public gateway.** Point apex at a third-party gateway that resolves `_dnslink.djinn.gg`. Viable gateways (circa 2026):

| Gateway | DNSLink? | Verified path |
|---|---|---|
| `gateway.lighthouse.storage` | No (path-based only) | Use for direct CID checks; cannot be DNS target |
| `dweb.link` | Yes | CNAME `djinn.gg` → `dweb.link` (requires apex-CNAME support) |
| `ipfs.io` | Yes | CNAME `djinn.gg` → `ipfs.io` (congested; expect 50%+ latency) |

Namecheap does not support apex `CNAME`. To use Option B, either migrate DNS to Cloudflare (which supports CNAME flattening) — or stay on Option A.

**Option C — Cloudflare as DNS host + self-hosted IPFS gateway.** The sovereign long-term answer: run `kubo` or `ipfs-cluster` on the production VPS, point DNS at it, and use Cloudflare only as the DNS registrar/nameserver. This is not a break-glass step; it is a pre-Cup hardening item — see [MAINNET_BLOCKERS P1-30](../../MAINNET_BLOCKERS.md) for status.

### Step 4 — Confirm DNSLink TXT points at the current CID

The DNSLink TXT should already be correct (CI updates it on every push). Verify:

```bash
dig _dnslink.djinn.gg TXT +short
# expect: "dnslink=/ipfs/<the CID from Step 1/2>"
```

If it's stale, update it:

```bash
source ~/.namecheap-api.env
export NAMECHEAP_CLIENT_IP=$(curl -s ifconfig.me)
node scripts/update-dnslink.mjs _dnslink "$CID"
```

### Step 5 — Wait for propagation + verify

TTL is 60s; propagation takes 1–5 minutes for most resolvers. While waiting:

```bash
# From a few exit points
for resolver in 1.1.1.1 8.8.8.8 9.9.9.9; do
  echo "=== $resolver ==="
  dig @$resolver djinn.gg +short
  dig @$resolver _dnslink.djinn.gg TXT +short
done
```

Once `djinn.gg` resolves to a Cloudflare IP (or your chosen gateway), hit it:

```bash
curl -sI https://djinn.gg | head -5
curl -s https://djinn.gg | grep -q '<title>Djinn' && echo "bundle loaded" || echo "FAIL"
```

### Step 6 — Announce

Post once:
- `#djinn-ops` Slack / Telegram: "Vercel → IPFS cutover complete. CID `<CID>`. Gateway: Cloudflare. Site: https://djinn.gg."
- Status page / Twitter: "djinn.gg is now being served from IPFS. No user action required."

Do NOT announce during the cutover — the `503 → 200` transition is the announcement.

## Manual Namecheap UI fallback

If the Namecheap API is unreachable (rate-limited, whitelist lost, API outage):

1. Log in to namecheap.com
2. Domain List → djinn.gg → Manage → Advanced DNS
3. Find the apex `A` record → set to `161.97.138.250` (production VPS, Option A) — NOT `cloudflare-ipfs.com` (sunsetted)
4. Find `_dnslink` TXT record → verify value is `dnslink=/ipfs/<CID>` — if stale, edit it
5. Save (Namecheap applies changes within 30s)
6. Skip to Step 5 above

## Rollback (Vercel comes back)

If Vercel restores the account and you want to go back:

1. Namecheap: apex `A 161.97.138.250` → back to apex `A 76.76.21.21` (or whatever Vercel shows for `djinn.gg` in the project DNS panel)
2. Keep the `_dnslink` TXT record — it's still the canonical source.
3. Force a fresh Vercel deploy to confirm the domain is attached.

The IPFS mirror keeps running via CI regardless. The hybrid state is the default, not the emergency.

## Known failure modes

- **All three public gateways are 5xx** — means Lighthouse and Crust both de-pinned simultaneously. Rare but possible (billing, policy). Detection: CI pin step fails for multiple consecutive runs. Mitigation: add a third pinner (Pinata, web3.storage / Storacha, 4EVERLAND) to the workflow, or self-host a gateway on the production VPS as the fourth option.

- **Public DNSLink gateway ecosystem has been decaying since 2024.** Cloudflare sunsetted `cloudflare-ipfs.com` in 2024. `ipfs.io` is saturated and 504s on sub-hour-old pins routinely. `dweb.link` redirects through the same upstream and shares the saturation. Lighthouse's own gateway (`gateway.lighthouse.storage`) is reliable but path-based only, not DNSLink-aware, so it cannot be an apex-CNAME target. Net effect: in a real break-glass, **Option A (VPS Nginx)** is the only option that's verifiably up inside minutes. The IPFS path is durable as the sovereign canonical *source* (content-addressed, pinned across Lighthouse + Crust) but is no longer a reliable *serve layer* without our own gateway on the production VPS. Self-hosted kubo gateway on the production VPS is the path out, tracked under MAINNET_BLOCKERS P1-30.

- **DNS TTL not respected** — some residential resolvers ignore TTL and cache for hours. No mitigation; tell affected users to flush DNS cache. `ipconfig /flushdns` on Windows, `sudo dscacheutil -flushcache` on macOS, `systemd-resolve --flush-caches` on Linux.

- **Wallet state migrates, wallet TX doesn't** — the static bundle connects to the same Base contracts. No contract state is lost. If a user's browser cached the Vercel bundle, they may see stale UI for up to 24h (CDN TTL); a hard reload (Cmd-Shift-R / Ctrl-F5) fixes it.

- **CSP violations after cutover** — IPFS gateways can't set edge CSP headers; the Vercel `middleware.ts` path was stripped on IPFS. This is tracked under [MAINNET_BLOCKERS P1-31](../../MAINNET_BLOCKERS.md). Check Sentry / GH error reports for `blocked-uri` CSP entries; tighten the `<meta http-equiv="Content-Security-Policy">` in `web/app/layout.tsx` if needed.

## Post-incident checklist

- [ ] Incident report committed to `docs/incidents/` with timeline + CID used.
- [ ] MEMORY: update `project_hybrid_vercel_ipfs_decision.md` to record the trigger case.
- [ ] If Vercel permanently gone, close MAINNET_BLOCKERS items related to Vercel middleware (they're moot) and reopen the IPFS-only variants.
- [ ] Run `/codex-audit docs/runbooks/vercel-break-glass.md` to find gaps that the real incident exposed.
