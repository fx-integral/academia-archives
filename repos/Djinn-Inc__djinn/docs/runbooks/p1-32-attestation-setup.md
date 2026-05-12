# P1-32 — DNSSEC + ENS contenthash parallel attestation

Two independent attestation paths bind `djinn.gg` to the IPFS bundle. If
either path is compromised (DNS hijack at the registrar, or ENS resolver
takeover), the other still tells users which CID is canonical.

## Status

| Path | Status | Owner |
|---|---|---|
| DNSSEC on `djinn.gg` | **enabled** | human (Namecheap) — already done |
| DNSLink TXT auto-update on push to main | **enabled** | code (`ipfs-mirror.yml`) |
| ENS `djinn.eth` registration | **registered** | already done (expires 2026-12-02) |
| ENS contenthash on `djinn.eth` | **empty** | human (set once via ENS app) |
| ENS contenthash auto-update on push to main | **code-complete, dormant** | code (`ipfs-mirror.yml`) |
| User verification script | **shipped** | code (`scripts/verify-attestation.mjs`) |

The ENS workflow step skips silently until `ENS_PRIVATE_KEY` is set in
GitHub Secrets. Once `djinn.eth` is registered and the secret is
provisioned, the next push to `main` updates both DNSLink and ENS in
the same run.

## Operator setup (one-time)

### 1. DNSSEC on `djinn.gg` — already enabled

Verify with:

```bash
dig DS djinn.gg @8.8.8.8 +short
# Expected: 57976 13 1 456076B2D700DB5416A44A3446E745D0D2475918
dig DNSKEY djinn.gg @8.8.8.8 +short | head -2
# Expected: two DNSKEY lines (KSK 257 + ZSK 256)
```

If those return empty, DNSSEC is broken — re-enable in Namecheap:
Domain List → djinn.gg → Advanced DNS → DNSSEC: ENABLE.

### 2. `djinn.eth` ENS state

**Already registered** as of 2025-02-01. Verified via the ENS subgraph
(namehash of `djinn.eth` computed via `ethers.namehash()`):

```bash
NAMEHASH=$(node -e "import('ethers').then(e=>console.log(e.namehash('djinn.eth')))")
curl -s -X POST https://api.thegraph.com/subgraphs/name/ensdomains/ens \
  -H 'Content-Type: application/json' \
  -d "{\"query\":\"{ domain(id: \\\"$NAMEHASH\\\") { name owner { id } resolver { address contentHash } registration { expiryDate } } }\"}"
```

- Owner: `0xd4416b13d2b3a9abae7acd5d6c2bbdbe25686401`
- Resolver: `0x231b0ee14048e9dccd1d247744d114a4eb5e8e63` (legacy Public Resolver — supports contenthash)
- contentHash: `0x` (empty — never set)
- Expiry: 2026-12-02 (~7 months from 2026-05-05; renew before)

**Pending human action — pick one:**

(a) **Set contenthash on existing legacy resolver via the ENS app UI.**
   Visit https://app.ens.domains/djinn.eth → Records → Add/Edit → Content
   Hash → paste `ipfs://QmUqfYBWmgddjR53pVfuu3FXpd7dokivKqWQRJtaJ7BAp6`
   (or the latest CID from `dig _dnslink.djinn.gg TXT +short`). One-time
   setup; the workflow keeps it in sync after.

(b) **Migrate to a modern resolver first.** Optional. The legacy
   resolver (0x231b...) supports contenthash but lacks newer features
   (CCIP-Read, multichain). The current Public Resolver is at
   `0xC1735677a60884ABbCF72295E88d47764BeDa282`. Switch in the ENS app
   under Resolver → Edit, then set contenthash. Slight gas cost but
   gives the resolver a longer support runway.

The controller wallet `0xd4416b13...` will sign `setContenthash` txs.
For automated updates from CI: export the private key for that EOA
into `ENS_PRIVATE_KEY` (step 3). If that wallet should not be used
for automation, transfer ownership of `djinn.eth` first to a dedicated
ENS-update-only EOA (Domain → Send → Manager only, keeps the registrant
unchanged so renewal still works).

Fund the controller with ~0.01 ETH for ~50 contenthash updates.

### 3. Add GitHub secrets

Repository → Settings → Secrets and variables → Actions → New
repository secret:

- `ENS_PRIVATE_KEY` — hex 0x-prefixed key controlling `djinn.eth`
- `L1_RPC_URL` (optional) — Ethereum mainnet RPC; default
  `https://cloudflare-eth.com` works for setContenthash but is
  rate-limited; for production use Alchemy or Infura.

### 4. First update

Trigger the workflow manually to force a contenthash write:

```
gh workflow run ipfs-mirror.yml
```

Watch the run. The "Update ENS contenthash for djinn.eth" step
should print a tx hash and confirm in a block.

After confirmation:

```bash
node scripts/verify-attestation.mjs
# Expected:
#   dnslink: OK cid=Qm...
#   ens:     OK cid=Qm...   (same CID)
#   dnssec:  OK (AD bit set)
#   match:   OK both paths agree
```

## User verification

A user can verify the bundle they're loading was attested through both
paths from any machine:

```bash
git clone https://github.com/djinn-inc/djinn
cd djinn
npm install --no-save @ensdomains/content-hash@2.5.7 ethers@6
node scripts/verify-attestation.mjs
```

Output is JSON to stdout (machine-parseable) and a human summary to
stderr. Exit code 0 means both paths agree on the same CID; non-zero
means a mismatch or path failure.

For browser-only verification (no Node), users with Brave or
MetaMask + IPFS Companion can navigate to:

- `https://djinn.gg/` — served via Vercel + DNSLink
- `ipns://djinn.eth/` — resolved via ENS contenthash
- `ipfs://Qm.../` — direct CID

All three should serve byte-identical bundles. The third tab can be
diffed against the first via DevTools → Network → Response (or
`curl -s | sha256sum`).

## What this defends against

- **DNS hijack at Namecheap**: ENS contenthash diverges from DNSLink;
  `verify-attestation.mjs` flags MISMATCH; users with ENS-aware
  browsers automatically resolve to the canonical CID via
  `ipns://djinn.eth/`.
- **ENS resolver compromise**: DNSLink still points at the canonical
  CID; users without ENS support continue to receive the correct
  bundle; mismatch surfaces in monitoring.
- **CDN injection (Vercel-side)**: out of scope for this layer —
  defended by Subresource Integrity + the IPFS path as the canonical
  source. See `docs/runbooks/vercel-break-glass.md`.

## What this does **not** defend against

- **Both paths compromised simultaneously** (key reuse on Namecheap
  + ENS controller). Mitigation: separate keys, hardware wallets for
  the ENS controller, 2FA on Namecheap.
- **Bundle-level supply chain attack** (malicious dep merged into
  `main`). Mitigation: `pnpm audit`, dependency review, branch
  protection on `main`. Out of scope for P1-32.
- **Stale ENS lookup at the user's resolver**. ENS values cache; a
  legitimate update may take a few minutes to propagate to all
  resolvers. Users hitting a stale resolver during an emergency
  rotation see the previous CID until TTL expires.

## References

- EIP-1577: contenthash field for ENS
  <https://eips.ethereum.org/EIPS/eip-1577>
- DNSLink spec
  <https://dnslink.dev/>
- DNSSEC RFC 4035
  <https://www.rfc-editor.org/rfc/rfc4035>
- `scripts/update-ens-contenthash.mjs` — workflow entry point
- `scripts/verify-attestation.mjs` — cross-path check
- `.github/workflows/ipfs-mirror.yml` — the deploy hook that updates
  both paths atomically per push
