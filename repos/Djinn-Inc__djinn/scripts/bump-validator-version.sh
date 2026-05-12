#!/usr/bin/env bash
# Bumps validator/djinn_validator/VERSION to match the next vNNNN tag.
# Intended use: run before `git tag vNNNN && git push origin main vNNNN` so
# operators on non-git installs (tarball, container without .git) report the
# correct version via /v1/identity even when their `git describe` fails.
#
# Why this is a script and not a commit-time hook: a hook would fight with
# any local edits and require sign-offs from every contributor. A pre-tag
# script is a one-liner the release-runner remembers (and the next /djinn
# iteration enforces if drift appears).
#
# Usage:
#   scripts/bump-validator-version.sh 1626        # writes "1626" to VERSION
#   scripts/bump-validator-version.sh             # auto-derive next from latest tag

set -euo pipefail

cd "$(dirname "$0")/.."

if [ $# -ge 1 ]; then
  TAG_NUM="$1"
else
  LAST=$(git tag --list 'v[0-9]*' --sort=-v:refname | head -1 | sed 's/^v//')
  TAG_NUM=$((LAST + 1))
fi

VERSION_FILE="validator/djinn_validator/VERSION"
echo "$TAG_NUM" > "$VERSION_FILE"
echo "wrote $VERSION_FILE: $TAG_NUM"
