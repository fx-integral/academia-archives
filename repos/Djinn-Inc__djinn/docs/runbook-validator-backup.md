# Validator Backup and Restore Runbook

This runbook covers backing up and restoring a Djinn validator's persistent state. Run it on every validator that holds Shamir key shares; losing those shares is the only kind of validator failure that cannot be recovered from elsewhere on the network.

## What needs to be backed up

The validator owns nine SQLite databases under its data directory (default `/root/djinn/validator/data`):

| File | Contains | Loss impact |
|------|----------|-------------|
| `shares.db` | Encrypted Shamir key shares for every signal this validator helped store | **CRITICAL.** Losing this means buyers cannot decrypt signals that depended on this validator's threshold contribution. |
| `signal_registrations.db` | On-chain signal metadata (sport, lines, geniuses, idiots) | High. Recoverable from chain + The Graph but rebuilding is slow. |
| `purchases.db` | Buyer purchase records and payment confirmations | High. Used for replay protection. |
| `purchase_odds.db` | Per-line BPA/WPA vectors captured at purchase time | Medium. Used by batch settlement. Loss means falling back to cross-line max for affected buyers. |
| `attestations.db` | TLSNotary attestation cache | Low. Cache, can be regenerated. |
| `miner_scores.db` | Accumulated miner scores for Yuma weight setting | Medium. Loss resets the bootstrap window for every miner from this validator's view. |
| `validator_telemetry.db` | Event log | Low. Audit trail, not load-bearing. |
| `audit_sets.db` | Audit set state | Medium. Used by settlement. |
| `circuit_breaker.db` | CUSUM scores per miner hotkey (only present once `DJINN_FF_CIRCUIT_BREAKER` has been on) | Medium. Loss resets all flag state — flagged miners get a clean slate. |

The order of importance is `shares.db` first, everything else second.

## Backup

The script `scripts/validator-backup.sh` snapshots all nine databases into a single timestamped tarball under `${BACKUP_DIR}` (default `/root/djinn-backups`). It uses SQLite's `VACUUM INTO` to take a consistent snapshot of WAL-mode databases without locking the originals, so it is **safe to run while the validator is live**.

### Manual backup

```bash
bash /root/djinn/scripts/validator-backup.sh
# OR with custom paths:
DATA_DIR=/var/djinn/data BACKUP_DIR=/var/backups bash /root/djinn/scripts/validator-backup.sh
```

Output:

```
OK /root/djinn-backups/djinn-validator-20260411T204500Z.tar.gz (12M, 9 dbs)
```

### Scheduled backup (recommended: every 15 minutes)

Add to root's crontab on every validator box:

```
*/15 * * * * /usr/bin/bash /root/djinn/scripts/validator-backup.sh >> /var/log/djinn-backup.log 2>&1
```

The script auto-prunes backups older than `RETENTION_DAYS` (default 7).

### Off-box copy

Local snapshots protect against process crashes and corruption, but not against losing the box. Sync `${BACKUP_DIR}` to an off-box location every hour (rsync, S3, B2, IPFS, your choice). Example with rsync:

```bash
0 * * * * /usr/bin/rsync -az /root/djinn-backups/ user@offbox:/srv/djinn-backups/$(hostname)/
```

## Restore

The restore script `scripts/validator-restore.sh` is the inverse of backup. It:

1. Verifies the archive's integrity by checking sha256 hashes against the manifest.
2. Stops the validator's pm2 process.
3. Moves the existing data directory aside as `${DATA_DIR}.preYYYYMMDDTHHMMSSZ` so nothing is lost.
4. Copies the verified databases into the data directory.
5. Restarts the validator.

### Procedure

```bash
# Pick the backup you want to restore from. Most recent is usually right:
ls -la /root/djinn-backups/

# Run the restore:
bash /root/djinn/scripts/validator-restore.sh /root/djinn-backups/djinn-validator-20260411T204500Z.tar.gz

# Verify the validator came back up healthy:
curl -s localhost:8421/health | jq
```

Expected output: `status: "ok"`, `bt_connected: true`, `shares_held: <nonzero>`.

### After a successful restore

The script preserves your old data directory at `${DATA_DIR}.preYYYYMMDDTHHMMSSZ`. Once you've confirmed the validator is healthy and serving requests, delete it manually:

```bash
rm -rf /root/djinn/validator/data.pre20260411T210015Z
```

If something looks wrong after the restore, you can roll back by stopping the validator, moving the preserved directory back into place, and restarting:

```bash
pm2 stop djinn-validator
rm -rf /root/djinn/validator/data
mv /root/djinn/validator/data.pre20260411T210015Z /root/djinn/validator/data
pm2 start djinn-validator
```

## Disaster scenarios

### Scenario 1: Process crash, disk intact

No restore needed. The pm2 supervisor restarts the validator, which reopens the existing databases and continues. WAL mode protects against partial-write corruption.

### Scenario 2: Database file corruption

Stop the validator, restore from the most recent backup that pre-dates the corruption. Inspect the corrupt file with `sqlite3 corrupt.db 'PRAGMA integrity_check;'` to confirm before throwing it away.

### Scenario 3: Whole disk lost

Provision a new box, install the validator, restore from off-box backup. Re-issue the same `BT_WALLET_*` credentials so the validator rejoins SN103 with its existing UID. The newly-restored `shares.db` lets it serve key shares for any signal it previously held.

### Scenario 4: Whole VPS provider goes down

If you also lost the off-box backup, the only recovery is to mark the validator as dead on SN103 (let it deregister) and stand up a fresh one from scratch. Buyers who depended exclusively on this validator's share will lose decryption ability for affected signals; the Shamir threshold should always be set such that no single validator is load-bearing.

## Verification: regularly test restores

Backups that have never been restored are not real backups. Once a month, on a non-production box, untar a recent backup, run the validator pointed at it in dev mode, and confirm `/health` returns `shares_held > 0`. This catches silent corruption before you need the backup for real.
