# Migration Rollback Plan — VPS #1 → VPS #2

**Started:** 2026-05-04
**Source:** VPS #1 (37.60.251.252, expires May 13 2026)
**Target:** VPS #2 (161.97.138.250, prepaid through Mar 14 2027)

## What I'm migrating

pm2 services on VPS #1:
- `djinn-validator` (UID 0, v1697)
- `debust`
- `firmrecord-api`
- `proveaudit`
- `proveaudit-notary`

Plus:
- nginx (wildcard `*.djinn.gg` + `v0.djinn.gg` + Let's Encrypt certs)
- `/root/djinn-backups` cron (15-min snapshots)
- `.env` files in /root/djinn/{web,validator,contracts,subgraph}

## Rollback triggers

If ANY of these happens after cutover, ROLL BACK:
1. UID 0 health-check failing on its own /health for >10 min
2. Validator vote rate drops to 0 (chain check) for >30 min
3. v0.djinn.gg returns 502/504 for >10 min after DNS propagation
4. Wildcard *.djinn.gg routing broken (UID 1/2/86/213 frontends unreachable)
5. Any data DB corruption or version mismatch on startup

## Rollback procedure (if needed)

### Step 1: Restart services on VPS #1
VPS #1 was NOT deleted — services were just `pm2 stop`ed. Restart:
```bash
ssh -J root@161.97.138.250 root@37.60.251.252 'pm2 start djinn-validator debust firmrecord-api proveaudit proveaudit-notary'
ssh -J root@161.97.138.250 root@37.60.251.252 'systemctl reload nginx'
```

### Step 2: Restore DNS via Namecheap API
DNS records to revert (currently both `*` and `v0` point at 173.249... target):
```bash
# Set in script (running locally in /home/user/djinn/scripts/migrate-dns.sh):
NEW_IP=37.60.251.252  # ← rollback target = VPS #1's IP
bash /home/user/djinn/scripts/migrate-dns.sh
```

### Step 3: Update Bittensor axon back
User runs btcli command to point UID 0 axon back at 37.60.251.252:
```bash
btcli s post_ip --netuid 103 --ip 37.60.251.252 --port 8421
# Or via SDK call to subtensor.serve_axon(...)
```

### Step 4: STOP the migrated services on VPS #2
Don't leave a duplicate validator running:
```bash
ssh root@161.97.138.250 'pm2 stop djinn-validator debust firmrecord-api proveaudit proveaudit-notary'
ssh root@161.97.138.250 'systemctl stop nginx'  # only if it was started for djinn routing
```

### Step 5: Verify rollback success
```bash
curl -sS http://37.60.251.252:8421/health  # UID 0 back online
dig v0.djinn.gg                              # resolves to 37.60.251.252
curl -sS https://v0.djinn.gg/health          # 200
# Wait for next epoch tick on chain, confirm UID 0 vote attempts resume
```

## Backups before any destructive operation

- VPS #1 has `/root/djinn-backups` with 7-day retention of validator state (96 snapshots/day × 7 days × ~25MB)
- I will rsync the LATEST snapshot to a SEPARATE directory before doing the final state DB sync
- Store at: `/root/djinn-backups-pre-migration-2026-05-04/` on BOTH boxes
- Keep this directory for 30 days minimum (manual cleanup)

## Cutover sequence (forward direction, for reference)

1. Pre-flight VPS #2: install deps (foundry, uv, node 20, pm2, nginx, certbot)
2. Clone /root/djinn from git on VPS #2
3. Rsync .env files (NOT in git) from VPS #1 → VPS #2
4. Rsync nginx config + LE certs
5. Rsync /root/djinn-backups (latest snapshot only, for warm start)
6. Start non-validator services on VPS #2 (debust, firmrecord-api, proveaudit, proveaudit-notary, nginx)
7. Verify they respond on http://161.97.138.250
8. **PAUSE for go-ahead** before next destructive step
9. `pm2 stop djinn-validator` on VPS #1 (state freeze)
10. Final state DB rsync VPS #1 → VPS #2
11. `pm2 start djinn-validator` on VPS #2
12. Verify UID 0 health on http://161.97.138.250:8421/health
13. Update Namecheap DNS (`*` and `v0` → 161.97.138.250)
14. **PAUSE — user runs btcli axon update**
15. Wait for DNS propagation (~5 min)
16. Verify v0.djinn.gg + v1.djinn.gg + v213.djinn.gg etc. via HTTPS
17. Watch chain for UID 0's first vote from new IP
18. Soak 24-48h before cancelling VPS #1

## Key facts to remember

- UID 0 hotkey/coldkey/signer key are UNCHANGED — only the axon IP moves
- DNS TTL on djinn.gg is short; propagation ~5-10 min
- Let's Encrypt certs are domain-based; will renew on the new IP automatically
- The old VPS #1 STAYS RUNNING during the soak; do not delete data

## File locations on each box (post-migration)

VPS #2 (target):
- `/root/djinn/` — repo
- `/root/djinn-backups/` — ongoing 15-min snapshots (cron resumes here)
- `/root/djinn-backups-pre-migration-2026-05-04/` — pre-cutover safety net
- `/etc/nginx/conf.d/djinn.conf` — wildcard router
- `/etc/letsencrypt/live/djinn.gg/` — TLS certs
- `/root/.env-validator-prod` — validator env
- `/root/.env-debust-prod` — debust env
- ... etc per service

VPS #1 (frozen, kept for rollback):
- All same paths, untouched
- pm2 services stopped (not deleted)
- 13-day grace period before Contabo cancellation
