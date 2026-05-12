# Miner Offline Runbook

Handles: one of our miners (UID 0 on production VPS, UID 240 deregistered) is unreachable.
Detected by `/opt/monitoring/miner-watchdog.sh` (pm2 state + port probe).

Miner offline on SN103 is usually SEV-2, not SEV-1. Other miners on the subnet
serve attestation requests; our specific miner going down reduces our
emissions but does not outage the network. Treat as SEV-1 only if it's
**all** miners (our 2 + the field is flat), which indicates a TLSNotary
library regression or systemic issue.

## Decision tree (first 10 minutes)

1. **Which of our miners is down?**
   - UID 0 (miner1): `ssh root@161.97.138.250 "pm2 list | grep djinn-miner"`
   - UID 240 (miner2): `ssh root@161.97.138.250 "pm2 list | grep djinn-miner"`
     - As of 2026-04-18, UID 240 is DEREGISTERED and earning nothing; a miner-down
       alert there is not urgent. Confirm with `btcli subnet metagraph --netuid 103`.

2. **Is it a registration issue or a process issue?**
   - Registered but process dead → `pm2 restart` (most common).
   - Deregistered → re-register (costs TAO) or shut down.
   - Registered, process alive, but port unreachable → firewall / axon not published.

## Process dead (most common)

```bash
pm2 list | grep djinn-miner
# Common: status=errored, unstable_restarts > 0
pm2 logs djinn-miner --lines 100 --nostream
```

Typical causes:

| Last log line | Cause | Fix |
|---|---|---|
| `ModuleNotFoundError` after recent pull | Dependency drift from watchtower | `cd /root/djinn && uv sync && pm2 restart djinn-miner --update-env` |
| `TLSNotary: failed to connect to notary` | Notary sidecar crashed | `pm2 restart proveaudit-notary` (shared sidecar) then `pm2 restart djinn-miner` |
| `Cannot allocate memory` | OOM (unlikely — miner footprint is small) | `free -m`; if genuinely low, audit other processes before restarting |
| `axon: failed to post_axon ... connection refused` | Subtensor endpoint flaky | Retry; if persistent, switch endpoint via `SUBTENSOR_NETWORK` env |
| `coldkey not found` | Key file missing/permissions bad | `ls -la /root/.bittensor/wallets/miner*/`; restore from backup if gone |

After the restart, verify:

```bash
curl -sS http://127.0.0.1:8422/health    # miner1 or 8423 for miner2
# Expect { "ok": true, "version": "...", "tlsn_ready": true }
```

## Port unreachable but process alive

This means our axon published IP is wrong, or a firewall rule changed.

```bash
# What IP did we publish?
btcli subnet metagraph --netuid 103 | grep <our-hotkey>
# Compare against the actual public IP:
curl -s ifconfig.me
```

If they differ, `post_axon` with the correct IP:

```bash
cd /root/djinn && uv run python scripts/post_axon.py --uid <UID>
```

(Script exists if it was needed historically; if not, fall back to `btcli`
directly.)

If they match but the port still isn't reachable from outside:

```bash
ufw status verbose
# Expect: 8422/tcp ALLOW (or whatever port you publish)
# If missing: ufw allow 8422/tcp && ufw reload
```

## Deregistered

`btcli subnet metagraph --netuid 103` shows our hotkey missing. As of 2026-04-18:

- UID 240 (miner2 hotkey `5DvYPznueK2jkD92gHMDpxVSG91aTUPJfbsXFKSXCdz3tDTy`) is
  deregistered. The process keeps running on port 8422 but earns nothing.
- UID 0 miner historically deregistered too, then re-registered.

**Decision point:** re-register (costs TAO at current burn cost — check
`btcli subnet list --netuid 103` for `Burn`) or shut down.

- Re-register only if expected emissions > TAO burn cost.
- Shut down: `pm2 delete djinn-miner`, keep the coldkey file for future use.

Either action is a non-incident operational decision. Tell the user in Telegram,
don't tweet it.

## Systemic miner outage (SEV-1 escalation)

If 60%+ of the 256 SN103 miners are offline simultaneously:

- Do NOT restart ours first — establish what's wrong upstream before adding
  noise to already-broken logs.
- Check `https://taostats.io/subnets/103` for network-wide status.
- Check Bittensor Discord / forum for Subtensor outage.
- If it's a TLSNotary library regression (our miners all dead with the same
  stack trace), pin the last-known-good TLSN version in `scripts/install-tlsn.sh`
  and redeploy.
- Ping validator operators (runbook is validator-side): without miners, their
  attestation requests fail, and they'll start recording that against miner
  scores — meaning even healthy-coming-back miners will need many cycles to
  recover weights. Coordinate the recovery window in Telegram.

## Postmortem

Only required if the outage affected SN103 emissions (our miner was down >
12 h during a busy attestation window).

- `docs/postmortems/YYYY-MM-DD-miner-offline.md`.
- If the cause was a bad commit, add a regression test to the miner test suite.
- If re-registration was required, log the TAO cost for future capacity planning.
