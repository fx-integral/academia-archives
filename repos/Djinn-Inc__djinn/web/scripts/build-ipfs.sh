#!/usr/bin/env bash
# build-ipfs.sh — produce a static export of the Djinn web client.
#
# Next.js 14's `output: "export"` mode cannot generate api/* routes
# because they're server-only. The simplest reliable workaround is to
# temporarily move api/ out of the way during the build, then restore
# it. The static export then runs purely client-side and ships from
# any static host (IPFS, ENS, S3, anywhere).
#
# Usage:  bash scripts/build-ipfs.sh
#
# Output: out/ (the static bundle ready to pin)
#
# Anything in api/ is unavailable in the static build. The migration
# story is to replace api/ routes one by one with direct client calls
# to validators (over HTTPS, see runbook-validator-https.md). Until
# that migration is complete, the static build is partial — pages
# that depend on api/ routes will fail at runtime in the browser.
#
# Set DJINN_IPFS_DRY_RUN=1 to print the moves without running the build.

set -euo pipefail

cd "$(dirname "$0")/.."

if [ ! -d app/api ]; then
  echo "ERROR: app/api directory not found. Are you in web/?" >&2
  exit 1
fi

# Directories to stash during the static build. api/ is server-only.
#
# Sprint-B Stage 1 (v1343): /network/miner/[uid] and /network/validator/[uid]
# now export `generateStaticParams` covering UIDs 0..255 and are prerendered.
#
# Sprint-B Stage 1b (v1344): /idiot/signal and /genius/signal now read the
# signal id via useSearchParams from a ?id= query string, so the routes are
# statically exportable without generateStaticParams and no longer need to
# be stashed. Old /idiot/signal/[id] deep links 404 in the static bundle.
TIMESTAMP=$(date +%s)
declare -a STASH_DIRS=(
  "app/api:app/_api_disabled_for_ipfs_${TIMESTAMP}"
)

cleanup() {
  for entry in "${STASH_DIRS[@]}"; do
    src="${entry%:*}"
    dst="${entry#*:}"
    if [ -d "$dst" ]; then
      echo "[ipfs-build] restoring $dst -> $src"
      mv "$dst" "$src"
    fi
  done
}
trap cleanup EXIT

for entry in "${STASH_DIRS[@]}"; do
  src="${entry%:*}"
  dst="${entry#*:}"
  if [ -d "$src" ]; then
    echo "[ipfs-build] stashing $src -> $dst"
    mv "$src" "$dst"
  fi
done

if [ "${DJINN_IPFS_DRY_RUN:-0}" = "1" ]; then
  echo "[ipfs-build] dry-run: skipping next build"
  exit 0
fi

NEXT_BUILD_TARGET=ipfs npx next build --no-lint

# next.config.ipfs.js sets distDir=".next-ipfs". With output:"export"
# Next.js writes the static bundle to the distDir (not to a separate
# out/ directory). Check the configured distDir for the result.
EXPORT_DIR=".next-ipfs"
if [ ! -d "$EXPORT_DIR" ] || [ -z "$(ls -A $EXPORT_DIR 2>/dev/null)" ]; then
  echo "[ipfs-build] ERROR: $EXPORT_DIR/ is missing or empty after build" >&2
  exit 2
fi

if [ ! -f "$EXPORT_DIR/index.html" ]; then
  echo "[ipfs-build] ERROR: $EXPORT_DIR/index.html missing — static export incomplete" >&2
  exit 3
fi

bytes=$(du -sb "$EXPORT_DIR" 2>/dev/null | cut -f1)
files=$(find "$EXPORT_DIR" -type f | wc -l)
echo "[ipfs-build] OK: $EXPORT_DIR/ ready, ${files} files, $((bytes / 1024)) KB"
echo ""
echo "Next steps:"
echo "  1. Pin to IPFS:    ipfs add -r $EXPORT_DIR"
echo "  2. Or rsync to host: rsync -avz $EXPORT_DIR/ user@host:/var/www/djinn/"
echo ""
echo "Note: any feature that depends on a removed api/ route will not work"
echo "in this build. See docs/runbook-ipfs-deploy.md for the migration plan."
echo ""
echo "Known remaining gaps:"
echo "  - api/* routes are stashed during build. Pages that fetch from"
echo "    /api/* will fail at runtime in the browser. Replace with direct"
echo "    validator calls via web/lib/validatorHostnames.ts."
echo "  - Deep links to /idiot/signal/<id> and /genius/signal/<id> 404 in"
echo "    the static bundle. Use /idiot/signal?id=<id> (query-string) — that"
echo "    route is prerendered and reads the id client-side."
