#!/usr/bin/env bash
# Collect signer EOAs from every registered validator's /health endpoint
# and print an env block ready to paste before running
# ScheduleRegisterValidators.s.sol.
#
# Strategy: query /api/validators/discover (which enumerates registered,
# axon-published validators from the metagraph), fetch /health on each,
# read validator_signer. Falls back to direct IP:port when HTTPS is absent.
#
# Usage: bash scripts/collect-validator-signers.sh
#        # Copy the printed exports, then:
#        # forge script contracts/script/ScheduleRegisterValidators.s.sol \
#        #   --rpc-url $BASE_SEPOLIA_RPC_URL --broadcast

set -euo pipefail

DISCOVER_URL="${DISCOVER_URL:-https://www.djinn.gg/api/validators/discover}"
TIMEOUT="${TIMEOUT:-10}"

echo "# Collecting signer EOAs from registered validators..."
echo "# Source: $DISCOVER_URL"
echo

# Fetch validator list. Each entry has uid + hostname (HTTPS if advertised)
# or ip:port (plain HTTP). Resolve to a URL we can query.
mapfile -t entries < <(
    curl -s --max-time "$TIMEOUT" "$DISCOVER_URL" \
    | python3 -c "
import sys, json
d = json.load(sys.stdin)
for v in d.get('validators', []):
    uid = v.get('uid')
    host = v.get('public_hostname') or ''
    ip = v.get('ip') or ''
    port = v.get('port') or 8421
    if host:
        url = f'https://{host}'
    elif ip:
        url = f'http://{ip}:{port}'
    else:
        continue
    print(f'{uid}\t{url}')
"
)

if [ "${#entries[@]}" -eq 0 ]; then
    echo "# ERROR: no validators discovered" >&2
    exit 1
fi

i=1
signers=()
for entry in "${entries[@]}"; do
    uid="${entry%%	*}"
    url="${entry#*	}"
    signer=$(curl -s --max-time "$TIMEOUT" "${url}/health" 2>/dev/null \
        | python3 -c "import sys, json; d=json.load(sys.stdin); print(d.get('validator_signer') or '')" 2>/dev/null || true)
    if [ -z "$signer" ] || [ "$signer" = "None" ]; then
        echo "# uid=$uid $url → no signer advertised (validator_signer null or /health unreachable)"
        continue
    fi
    # Dedupe: two validators sharing a signer EOA would only count once for MIN_VALIDATORS.
    dup=0
    for existing in "${signers[@]:-}"; do
        if [ "$existing" = "$signer" ]; then
            dup=1
            break
        fi
    done
    if [ "$dup" -eq 1 ]; then
        echo "# uid=$uid $url → $signer (DUPLICATE, skipped)"
        continue
    fi
    signers+=("$signer")
    printf "export VALIDATOR_%d=%s  # uid=%s (%s)\n" "$i" "$signer" "$uid" "$url"
    i=$((i+1))
done

echo
echo "# Unique signer EOAs collected: ${#signers[@]}"
if [ "${#signers[@]}" -lt 3 ]; then
    echo "# WARNING: fewer than MIN_VALIDATORS=3. Add remaining EOAs manually or"
    echo "# wait for more operators to publish /health.validator_signer."
else
    echo "# Ready to run: forge script contracts/script/ScheduleRegisterValidators.s.sol \\"
    echo "#   --rpc-url \$BASE_SEPOLIA_RPC_URL --broadcast"
fi
