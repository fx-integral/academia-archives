# Wildcard `*.djinn.gg` Router

This is the operator-zero approach to validator HTTPS. Instead of asking each validator operator to set up nginx and Let's Encrypt on their own box, we run a single wildcard HTTPS router that maps `v<uid>.djinn.gg` to whichever IP that UID currently reports to the metagraph. New validators auto-appear; deregistered ones auto-disappear.

## Why this exists

Browsers block mixed-content, so the Djinn web client (HTTPS) cannot call validators directly over plain HTTP `IP:port`. Three places HTTPS can live:

1. **On each validator** — every operator runs nginx + cert. Per-validator coordination.
2. **On a router we control** (this doc) — one wildcard cert + one nginx vhost handles everything.
3. **On a third-party gateway** — Cloudflare Workers etc.

The router lets the Djinn protocol layer treat HTTPS as a *protocol property*, not an *operator property*. Validators stay simple. Operators do nothing. The cost is one centralized hop, mitigated by running multiple routers (anyone can spin one up using this runbook).

## Architecture

```
client (browser)
   |
   |  https://v213.djinn.gg/health
   v
  Wildcard A record:  *.djinn.gg → router IP (161.97.138.250 currently)
   |
   v
nginx (the router)
   |
   |  Loads /etc/nginx/conf.d/uid-routing-map.conf which maps:
   |    v0.djinn.gg   → 161.97.138.250:8421
   |    v1.djinn.gg   → 167.150.153.103:8421
   |    v213.djinn.gg → 3.150.72.96:8421
   |    ...
   |
   |  Falls back to 502 for any UID not currently in the metagraph.
   v
upstream validator at $validator_upstream:port  (plain HTTP)
```

The map is regenerated every minute by `scripts/refresh-uid-routing.sh`, which calls the local validator's `/v1/network/validators` endpoint to read the live metagraph and writes a new nginx `map` directive. nginx is reloaded only when the map actually changes.

## What's deployed where

- **DNS**: `*.djinn.gg → 161.97.138.250` (one wildcard A record at Namecheap)
- **Cert**: `*.djinn.gg` + `djinn.gg` wildcard, issued via acme.sh + Namecheap DNS-01 challenge. Files at `/etc/letsencrypt/wildcard-djinn-gg/{fullchain.pem,privkey.pem}`. Auto-renewing via acme.sh's cron.
- **nginx vhost**: `scripts/nginx-wildcard-djinn-gg.conf` → installed at `/etc/nginx/sites-enabled/wildcard-djinn-gg.conf`
- **Refresh script**: `scripts/refresh-uid-routing.sh` → installed at `/usr/local/bin/refresh-uid-routing.sh`
- **Cron**: `* * * * * /usr/local/bin/refresh-uid-routing.sh >> /var/log/uid-routing.log 2>&1`

## Operator-zero validator onboarding

When a new validator joins SN103:

1. Operator does normal Bittensor validator setup (axon on port 8421, registers with subnet)
2. The metagraph picks them up (within minutes)
3. The next refresh-uid-routing.sh tick generates a map entry for them
4. nginx reloads with the new entry
5. `https://v<their-uid>.djinn.gg/health` works

The operator never touches DNS, certs, nginx, or anything else. Validators stay HTTP-only on port 8421.

When a validator deregisters:

1. The metagraph stops listing them
2. The next refresh tick removes the entry from the map
3. `https://v<their-uid>.djinn.gg/...` returns 502

## Failure modes

- **Router box dies.** Fix: run multiple routers in different regions. The wildcard A record can have multiple IPs (DNS round-robin) or use a health-checked DNS provider.
- **acme.sh cert renewal fails.** Cron alerts on failure (acme.sh emails the configured address). Manual renewal is `acme.sh --renew -d '*.djinn.gg' --force`.
- **refresh-uid-routing.sh fails to call the local validator.** The script exits 0 silently if curl fails, leaving the previous map intact. nginx stays up; the map just stops updating until the validator recovers.
- **A new validator's IP is unreachable from the router.** nginx returns 502 on the proxy attempt. The client treats this as a normal validator failure.

## Adding more routers

Anyone can run a Djinn wildcard router. The setup:

1. Have a public IP and the ability to receive 80/443 traffic
2. Run a Djinn validator on the same box (so the router has a local metagraph view to query) — OR point `refresh-uid-routing.sh` at a remote validator's `/v1/network/validators` endpoint
3. Get a wildcard cert for whatever subdomain you want (`*.example.com` works the same way)
4. Install the nginx vhost with that cert
5. Install the refresh cron
6. Tell the Djinn web client about your router via the `validatorHostnames.ts` registry (or operate it as a private fallback)

The router is a standalone service. Multiple routers can serve the same network.

## Verification

```bash
# Check the live map:
ssh root@router cat /etc/nginx/conf.d/uid-routing-map.conf

# Smoke test a few hostnames:
curl -s https://v0.djinn.gg/health | head -c 200
curl -s https://v213.djinn.gg/health | head -c 200

# Confirm a nonexistent UID gets 502:
curl -s -o /dev/null -w "%{http_code}\n" https://v9999.djinn.gg/health
```

Expected outputs: real validator JSON for live UIDs, `502` for nonexistent ones.

## What this doesn't replace

- The Djinn web client still has to know that it should hit `v<uid>.djinn.gg` (not the validator's raw IP). The pattern is hardcoded in `web/lib/validatorHostnames.ts:patternHostname()`.
- The router does NOT verify that the upstream is actually a Djinn validator — it proxies whatever the metagraph says is at that IP. If a malicious operator publishes a fake IP to the metagraph, the router proxies to the fake. Defense: the validator's own /health response is signed (or will be) and the client verifies the signature against the metagraph hotkey.
- The router does not implement quorum, scoring, or any protocol logic. It is a thin TLS-terminating proxy.
