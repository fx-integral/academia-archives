#!/usr/bin/env bash
# Cross-validator outcome divergence diagnostic (v1680+).
#
# For a given (genius, idiot) pair, queries each OV signer's
# /v1/audit/{g}/{i}/detail and prints the outcomes_hash for each
# resolved signal. If hashes differ across validators for the same
# signal, P1-36 outcome divergence is the active blocker — validators
# back-walked ESPN and matched different historical games.
#
# Output format (one row per signal):
#   pid=NNNN  UID0:hash  UID1:hash  UID2:hash  UID86:hash  UID213:hash  -> CONVERGED|DIVERGENT|UNRESOLVED
#
# Usage:
#   bash scripts/check-outcome-divergence.sh <genius> <idiot>
#
# Requires v1680+ on validators (older respond with hash=null).
set -euo pipefail

declare -A VALIDATORS=(
  [0]="v0.djinn.gg"
  [1]="v1.djinn.gg"
  [2]="v2.djinn.gg"
  [86]="v86.djinn.gg"
  [213]="v213.djinn.gg"
)

if [ $# -ne 2 ]; then
  echo "Usage: $0 <genius> <idiot>" >&2
  exit 1
fi

GENIUS=$1
IDIOT=$2

# Fetch all 5 validator details in parallel into temp files.
TMPDIR=$(mktemp -d)
trap "rm -rf $TMPDIR" EXIT

for uid in 0 1 2 86 213; do
  ip=${VALIDATORS[$uid]}
  curl -s -m 8 "${_PROTO}://${ip}/v1/audit/${GENIUS}/${IDIOT}/detail" \
    > "$TMPDIR/uid${uid}.json" 2>/dev/null &
done
wait

# Pivot: for each (purchase_id), collect per-validator outcome hash.
python3 <<PYEOF
import json
from pathlib import Path
TMPDIR = "$TMPDIR"
data = {}
uids = [0, 1, 2, 86, 213]
all_pids = set()
for uid in uids:
    p = Path(f"{TMPDIR}/uid{uid}.json")
    if not p.exists() or p.stat().st_size == 0:
        data[uid] = None
        continue
    try:
        d = json.loads(p.read_text())
        sigs = d.get("signals", [])
        per = {int(s["purchase_id"]): s.get("outcomes_hash") for s in sigs}
        data[uid] = per
        all_pids.update(per.keys())
    except Exception:
        data[uid] = None

if not all_pids:
    print("No signals found across any validator. Pair may not be indexed yet.")
else:
    print("Per-purchase outcome hash by validator (v1680+ field; null=unresolved):")
    converged = divergent = unresolved = 0
    for pid in sorted(all_pids):
        hashes = []
        cells = []
        for uid in uids:
            per = data.get(uid)
            h = per.get(pid) if per else None
            cells.append(f"UID{uid}:{h or '-'}")
            if h:
                hashes.append(h)
        unique = set(hashes)
        if not hashes:
            status = "UNRESOLVED"
            unresolved += 1
        elif len(unique) == 1:
            status = f"CONVERGED ({len(hashes)} validators agree)"
            converged += 1
        else:
            status = f"DIVERGENT ({len(unique)} distinct hashes from {len(hashes)} validators)"
            divergent += 1
        print(f"  pid={pid}  {' '.join(cells)}  -> {status}")
    print()
    print(f"Summary: converged={converged} divergent={divergent} unresolved={unresolved}")
    if divergent > 0:
        print("DIAGNOSIS: P1-36 outcome divergence active. Validators back-walked to different games.")
        print("  Fix: v1679 game_date gossip propagation should converge over time as outcomes re-resolve.")
        print("  Manual: restart any validator to re-trigger resolution with v1679+ gossip path.")
PYEOF
