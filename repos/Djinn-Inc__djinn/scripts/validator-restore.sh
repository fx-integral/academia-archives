#!/usr/bin/env bash
# validator-restore.sh — restore a validator's persistent state from a
# backup archive produced by validator-backup.sh.
#
# Usage:
#   bash scripts/validator-restore.sh /path/to/djinn-validator-YYYYMMDDTHHMMSSZ.tar.gz
#
# Behavior:
#   1. Stops the validator pm2 process.
#   2. Moves the existing data directory aside as ${DATA_DIR}.preXXX.
#   3. Untars the archive into a temp directory and verifies sha256
#      hashes against the manifest.
#   4. Copies the verified .db files into ${DATA_DIR}.
#   5. Restarts the validator.
#
# Safety:
#   - Refuses to run if the archive doesn't exist or has no MANIFEST.
#   - Refuses to run if any sha256 mismatch is detected.
#   - The pre-restore data directory is preserved for manual inspection
#     until the operator deletes it.

set -euo pipefail

ARCHIVE="${1:-}"
DATA_DIR="${DATA_DIR:-/root/djinn/validator/data}"
PM2_NAME="${PM2_NAME:-djinn-validator}"

if [ -z "${ARCHIVE}" ] || [ ! -f "${ARCHIVE}" ]; then
  echo "Usage: $0 /path/to/djinn-validator-*.tar.gz" >&2
  exit 1
fi

work=$(mktemp -d)
trap 'rm -rf "${work}"' EXIT

tar -xzf "${ARCHIVE}" -C "${work}"

if [ ! -f "${work}/MANIFEST.txt" ]; then
  echo "ERROR: archive ${ARCHIVE} has no MANIFEST.txt — refusing to restore." >&2
  exit 2
fi

# Verify sha256 hashes from the manifest against the unpacked files.
# Format in MANIFEST.txt:  "  filename.db: size=N sha256=HEX"
fail=0
while IFS= read -r line; do
  case "${line}" in
    "  "*.db:*)
      file=$(echo "${line}" | sed 's/^  //; s/:.*//')
      expected=$(echo "${line}" | sed 's/.*sha256=//')
      actual=$(sha256sum "${work}/${file}" 2>/dev/null | cut -d' ' -f1)
      if [ "${actual}" != "${expected}" ]; then
        echo "ERROR: sha256 mismatch for ${file}" >&2
        echo "  expected: ${expected}" >&2
        echo "  actual:   ${actual}" >&2
        fail=$((fail + 1))
      fi
      ;;
  esac
done < "${work}/MANIFEST.txt"

if [ "${fail}" -gt 0 ]; then
  echo "ERROR: ${fail} hash mismatches — refusing to restore." >&2
  exit 3
fi

# Stop the validator before swapping files.
echo "Stopping ${PM2_NAME}..."
pm2 stop "${PM2_NAME}" 2>/dev/null || true

# Preserve the existing data directory.
backup_old=""
if [ -d "${DATA_DIR}" ]; then
  backup_old="${DATA_DIR}.pre$(date -u +%Y%m%dT%H%M%SZ)"
  mv "${DATA_DIR}" "${backup_old}"
  echo "Preserved existing data dir: ${backup_old}"
fi
mkdir -p "${DATA_DIR}"

# Copy verified .db files into the data directory.
restored=0
for f in "${work}"/*.db; do
  if [ -f "${f}" ]; then
    cp "${f}" "${DATA_DIR}/$(basename "${f}")"
    restored=$((restored + 1))
  fi
done

echo "Restored ${restored} databases into ${DATA_DIR}"

# Start the validator.
echo "Starting ${PM2_NAME}..."
pm2 start "${PM2_NAME}" 2>/dev/null || true

echo ""
echo "Restore complete. Verify health with:"
echo "  curl -s localhost:8421/health | jq"
echo ""
if [ -n "${backup_old}" ]; then
  echo "Pre-restore data dir preserved at: ${backup_old}"
  echo "Delete it once you have confirmed the restore is healthy:"
  echo "  rm -rf '${backup_old}'"
fi
