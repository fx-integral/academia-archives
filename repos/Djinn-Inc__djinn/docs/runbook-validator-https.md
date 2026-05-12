# Validator HTTPS Setup

This runbook walks an SN103 validator operator through putting their axon behind HTTPS so the Djinn web client can hit it directly from a browser. Without this, every browser-to-validator call has to bounce through the centralized djinn.gg proxy, which is the last centralization point in the data plane and the only thing blocking the static IPFS-deployable client.

The Djinn-operated UID 0 validator is already set up at `https://v0.djinn.gg`. This document is the same procedure for everyone else.

## What you'll provision

- A subdomain pointing to your validator's public IP (one DNS A record)
- An nginx reverse proxy that terminates TLS and forwards to your validator on port 8421
- A Let's Encrypt certificate that auto-renews
- CORS headers that let browsers on `djinn.gg` make cross-origin calls

This is purely operator-side. **Zero changes to validator code or its configuration.** Your existing pm2 process keeps running on port 8421 unchanged; nginx just adds a TLS front door on top.

## Requirements

- A subdomain you control. We use `v0.djinn.gg`, `v1.djinn.gg`, etc. for Djinn-operated boxes; you can use anything that resolves to your IP. Alternatively, ask Philip to issue you a subdomain under `djinn.gg`.
- Ports 80 and 443 open in your firewall (`ufw allow 80/tcp; ufw allow 443/tcp`)
- nginx and certbot installed (`apt install nginx certbot python3-certbot-nginx`)
- Your validator running on `127.0.0.1:8421`

## Steps

### 1. DNS

Add an A record:

```
Name:   v<your-uid>           # or any unique label
Type:   A
Value:  <your-validator-public-ip>
TTL:    300
```

Wait until `dig v<your-uid>.djinn.gg` returns your IP. Usually under a minute.

### 2. nginx vhost

Save this as `/etc/nginx/sites-available/v<your-uid>.djinn.gg.conf`, replacing `v<your-uid>.djinn.gg` with your hostname:

```nginx
server {
    server_name v<your-uid>.djinn.gg;
    listen 80;

    location / {
        if ($request_method = OPTIONS) {
            add_header Access-Control-Allow-Origin $http_origin always;
            add_header Access-Control-Allow-Methods "GET, POST, OPTIONS" always;
            add_header Access-Control-Allow-Headers "Content-Type, Authorization, X-Validator-Hotkey, X-Validator-Signature, X-Validator-Timestamp" always;
            add_header Access-Control-Max-Age 86400 always;
            add_header Content-Length 0;
            return 204;
        }
        add_header Access-Control-Allow-Origin $http_origin always;
        add_header Access-Control-Allow-Methods "GET, POST, OPTIONS" always;
        add_header Access-Control-Allow-Headers "Content-Type, Authorization, X-Validator-Hotkey, X-Validator-Signature, X-Validator-Timestamp" always;

        proxy_pass http://127.0.0.1:8421;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 120s;
        proxy_send_timeout 120s;
        client_max_body_size 10m;
    }
}
```

Enable and test:

```bash
ln -sf /etc/nginx/sites-available/v<your-uid>.djinn.gg.conf /etc/nginx/sites-enabled/
nginx -t && systemctl reload nginx
```

### 3. Get the TLS cert

```bash
certbot --nginx -d v<your-uid>.djinn.gg --non-interactive --agree-tos -m you@example.com --redirect
```

Certbot adds the `listen 443 ssl` block, the cert paths, and an HTTP→HTTPS redirect. The cert auto-renews via the certbot.timer systemd unit (already installed by `python3-certbot-nginx`).

### 4. Verify

```bash
# Health endpoint should return JSON over HTTPS:
curl -s https://v<your-uid>.djinn.gg/health

# CORS preflight should return 204 with the right headers:
curl -i -X OPTIONS https://v<your-uid>.djinn.gg/health \
  -H "Origin: https://www.djinn.gg" \
  -H "Access-Control-Request-Method: GET"
```

You should see `Access-Control-Allow-Origin: https://www.djinn.gg` in the response headers.

### 5. Tell Philip

Send your hostname so it can be added to the validator discovery list. The web client will start direct-calling your axon over HTTPS instead of bouncing through the proxy.

## Troubleshooting

- **`certbot` fails with `unauthorized`**: DNS hasn't propagated yet, or your firewall is blocking port 80. `dig` your hostname and `curl http://your-host/` from a remote machine.
- **Browser shows "blocked by CORS"**: the `Access-Control-Allow-Origin` header isn't reaching the browser. Check that the `add_header` lines have `always` (otherwise they're stripped on error responses).
- **`502 Bad Gateway`**: your validator on `127.0.0.1:8421` isn't running or isn't bound to localhost. `ss -tlnp | grep 8421` should show your validator.
- **Cert renewal fails**: `certbot renew --dry-run` to debug. Usually a misconfigured nginx vhost.

## Why this is safe

- nginx never sees plaintext validator state, only proxies HTTP requests
- the validator process is unchanged
- the cert and key live under `/etc/letsencrypt/`, owned by root, no validator code touches them
- you can roll back at any time by removing the symlink in `sites-enabled/` and reloading nginx
- nothing in this setup changes how the validator participates in SN103 consensus
