#!/usr/bin/env bash
# Reads a stress-scale TSV, picks the most recent N (signal_id, idiot)
# purchases, and probes each validator's purchase_odds.db for the row.
# Output: a TSV showing per-(signal,idiot,validator) HIT/MISS so you
# can see if v1630's "fan out to ALL validators" change actually worked.
#
# Usage:
#   verify-purchase-odds-fanout.sh /tmp/uid0-soak.tsv [N]
#
# Default N=5 (last 5 purchases).

set -euo pipefail

TSV="${1:?Usage: $0 <stress-tsv> [N]}"
N="${2:-5}"
JUMP="${JUMP_HOST:-161.97.138.250}"

# Parse the TSV. Format: ts\tphase\tidx\tsignal_id\tpurchase_id\tidiot\toutcome\tdur_ms\terror
PAIRS=$(grep '	purchase	' "$TSV" 2>/dev/null | awk -F'\t' '$7=="ok" {print $4 "\t" tolower($6)}' | tail -n "$N")
if [ -z "$PAIRS" ]; then
  echo "no successful purchases found in $TSV"
  exit 1
fi

declare -A VIPS=(
  [UID0]=v0.djinn.gg
  [UID1]=v1.djinn.gg
  [UID2]=v2.djinn.gg
  [UID86]=v86.djinn.gg
  [UID213]=v213.djinn.gg
)

echo "uid	signal_short	idiot_short	hit"
while IFS=$'\t' read -r SIG IDIOT; do
  SIG_SHORT="${SIG:0:14}…"
  IDIOT_SHORT="${IDIOT:0:10}…"
  for UID in UID0 UID1 UID2 UID86 UID213; do
    IP="${VIPS[$UID]}"
    # Direct curl to the validator's purchase_odds endpoint requires auth,
    # so go via jump host + sqlite probe directly. UID 0 is the only one
    # we can SSH into; for the others we'd need their SSH access. So do
    # UID 0 directly + skip the others (they'd need an HTTP probe with
    # auth which we don't have set up here).
    if [ "$UID" = "UID0" ]; then
      HIT=$(ssh -J "root@${JUMP}" -o StrictHostKeyChecking=no -o ConnectTimeout=8 \
        root@${IP} \
        "sqlite3 /root/djinn/validator/data/purchase_odds.db \"SELECT 1 FROM purchase_odds WHERE signal_id='${SIG}' AND lower(buyer_address)='${IDIOT}' LIMIT 1\"" \
        2>/dev/null || true)
      [ -n "$HIT" ] && echo "$UID	$SIG_SHORT	$IDIOT_SHORT	YES" || echo "$UID	$SIG_SHORT	$IDIOT_SHORT	NO"
    else
      # For other UIDs we don't have direct SSH from this script; mark as
      # "not-probed" so a future operator can wire up a per-UID SSH map.
      echo "$UID	$SIG_SHORT	$IDIOT_SHORT	?"
    fi
  done
done <<< "$PAIRS"

echo
echo "Note: only UID0 is SSH-probed here; other UIDs require a per-UID SSH access map"
echo "to read their purchase_odds.db. UID0 is the canonical 'did our gossip land' check"
echo "since the script's recordPurchaseOdds fans out to all validators including UID0."
