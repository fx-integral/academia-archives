#!/usr/bin/env bash
# validator-backup.sh — snapshot the validator's persistent state.
#
# Backs up every SQLite database the validator owns into a single
# tarball under DJINN_BACKUP_DIR. Safe to run while the validator is
# live: each .db is copied via the SQLite VACUUM INTO mechanism, which
# produces a consistent snapshot under WAL mode without locking the
# original.
#
# Usage:
#   bash scripts/validator-backup.sh                    # default paths
#   DATA_DIR=/var/djinn/data BACKUP_DIR=/var/backups bash scripts/validator-backup.sh
#
# What gets backed up:
#   - shares.db              encrypted Shamir key shares (CRITICAL)
#   - signal_registrations.db on-chain signal metadata + lines
#   - purchases.db           buyer purchase records
#   - purchase_odds.db       per-line BPA/WPA at purchase time
#   - attestations.db        TLSNotary attestation cache
#   - miner_scores.db        accumulated miner scores
#   - validator_telemetry.db event log
#   - audit_sets.db          audit set state
#   - circuit_breaker.db     CUSUM scores per hotkey (when present)
#
# Restore: see scripts/validator-restore.sh.
#
# Schedule: cron, every 15 minutes is a reasonable default. Old backups
# are pruned by retention policy below.

set -euo pipefail

DATA_DIR="${DATA_DIR:-/root/djinn/validator/data}"
BACKUP_DIR="${BACKUP_DIR:-/root/djinn-backups}"
RETENTION_DAYS="${RETENTION_DAYS:-7}"

if [ ! -d "${DATA_DIR}" ]; then
  echo "ERROR: DATA_DIR does not exist: ${DATA_DIR}" >&2
  exit 1
fi

mkdir -p "${BACKUP_DIR}"

ts=$(date -u +%Y%m%dT%H%M%SZ)
work=$(mktemp -d)
trap 'rm -rf "${work}"' EXIT

# List of expected DB filenames. Missing ones are skipped (not all
# validators have every db; for example circuit_breaker.db only exists
# after the v17xx upgrade).
dbs=(
  shares.db
  signal_registrations.db
  purchases.db
  purchase_odds.db
  attestations.db
  miner_scores.db
  validator_telemetry.db
  audit_sets.db
  circuit_breaker.db
)

snapshotted=0
skipped=0
failed=0

# Detect snapshot tool. The sqlite3 CLI is preferred (it has the
# documented VACUUM INTO syntax). If not present, fall back to a
# python3 + sqlite3 module shim, which every modern Linux box has.
have_sqlite3_cli=0
have_python3=0
if command -v sqlite3 >/dev/null 2>&1; then
  have_sqlite3_cli=1
fi
if command -v python3 >/dev/null 2>&1; then
  have_python3=1
fi
if [ "${have_sqlite3_cli}" -eq 0 ] && [ "${have_python3}" -eq 0 ]; then
  echo "ERROR: neither sqlite3 nor python3 is available — cannot snapshot." >&2
  exit 4
fi

snapshot_db() {
  local src="$1"
  local dst="$2"
  if [ "${have_sqlite3_cli}" -eq 1 ]; then
    if sqlite3 "${src}" "VACUUM INTO '${dst}';" 2>/dev/null; then
      return 0
    fi
    if sqlite3 "${src}" ".backup '${dst}'" 2>/dev/null; then
      return 0
    fi
  fi
  if [ "${have_python3}" -eq 1 ]; then
    python3 - "${src}" "${dst}" <<'PY' 2>/dev/null
import sqlite3, sys
src, dst = sys.argv[1], sys.argv[2]
conn = sqlite3.connect(src)
target = sqlite3.connect(dst)
with target:
    conn.backup(target)
target.close()
conn.close()
PY
    return $?
  fi
  return 1
}

for db in "${dbs[@]}"; do
  src="${DATA_DIR}/${db}"
  if [ ! -f "${src}" ]; then
    skipped=$((skipped + 1))
    continue
  fi
  dst="${work}/${db}"
  if snapshot_db "${src}" "${dst}"; then
    snapshotted=$((snapshotted + 1))
  else
    echo "WARN: failed to snapshot ${db}" >&2
    failed=$((failed + 1))
  fi
done

if [ "${snapshotted}" -eq 0 ]; then
  echo "ERROR: no databases could be snapshotted from ${DATA_DIR}" >&2
  exit 2
fi

# Manifest helps the restore script and human auditors understand what's
# in this archive without untarring it.
{
  echo "Djinn validator backup"
  echo "timestamp_utc: ${ts}"
  echo "data_dir: ${DATA_DIR}"
  echo "snapshotted: ${snapshotted}"
  echo "skipped: ${skipped}"
  echo "failed: ${failed}"
  echo ""
  echo "files:"
  for f in "${work}"/*.db; do
    if [ -f "${f}" ]; then
      size=$(stat -c '%s' "${f}")
      sha=$(sha256sum "${f}" | cut -d' ' -f1)
      echo "  $(basename "${f}"): size=${size} sha256=${sha}"
    fi
  done
} > "${work}/MANIFEST.txt"

archive="${BACKUP_DIR}/djinn-validator-${ts}.tar.gz"
tar -czf "${archive}" -C "${work}" .

# Retention pruning: delete backups older than RETENTION_DAYS.
find "${BACKUP_DIR}" -name 'djinn-validator-*.tar.gz' -mtime +"${RETENTION_DAYS}" -delete 2>/dev/null || true

size=$(du -h "${archive}" | cut -f1)
echo "OK ${archive} (${size}, ${snapshotted} dbs)"
