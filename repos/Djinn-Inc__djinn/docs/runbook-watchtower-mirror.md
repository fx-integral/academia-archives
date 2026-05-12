# Watchtower Multi-Remote Mirror Setup

This runbook configures a Djinn validator to auto-update from multiple git remotes in priority order, so a single GitHub outage (or upstream rate limit, or DNS failure) doesn't pin the validator at an old commit.

## Why mirror

Today every validator pulls from `origin` (GitHub) on its watchtower cycle. If GitHub is down, validators stop receiving updates. If GitHub silently lies (cache issue, BGP, MITM), validators still trust it. Mirroring spreads the trust across N independent remotes — the watchtower picks the first one that responds and falls through on failure.

## Configuration

Two new env vars on the validator. Add to your validator's `.env` file:

```bash
# Comma-separated list of remote names to try in order. Default: "origin"
AUTO_UPDATE_REMOTES=origin,codeberg,gitlab

# Optional: declare the URLs the watchtower should attach to those names
# if they don't already exist as git remotes. Format:
#   "name1=url1;name2=url2;name3=url3"
AUTO_UPDATE_REMOTE_URLS=codeberg=https://codeberg.org/djinn-inc/djinn.git;gitlab=https://gitlab.com/djinn-inc/djinn.git
```

The watchtower will:

1. On startup, ensure each declared remote exists at the right URL (creating or updating as needed via `git remote add` / `git remote set-url`).
2. On each polling cycle, try `git ls-remote <name> main` against each remote in order. The first one that responds wins.
3. Pull from the same remote that returned the fresh sha. If the pull fails (network blip), the watchtower falls through to the next remote in the list and tries again.
4. Log every fallthrough event so operators can spot a remote that's persistently failing.

## Recommended setup

For Djinn-operated boxes (UID 0):

```bash
AUTO_UPDATE_REMOTES=origin,codeberg
AUTO_UPDATE_REMOTE_URLS=codeberg=https://codeberg.org/djinn-inc/djinn.git
```

For independent validators that want their own backup:

```bash
# Set up your own private mirror (e.g. on a small VPS or your own gitlab)
AUTO_UPDATE_REMOTES=origin,my-mirror
AUTO_UPDATE_REMOTE_URLS=my-mirror=git@your-mirror.example:djinn-inc/djinn.git
```

## Setting up the mirror itself

The watchtower only consumes mirrors; you have to populate them. The cleanest options:

### Option A: GitHub-side mirror via Actions

In `djinn-inc/djinn`, add a workflow that pushes to the mirror on every push to main. One-time setup, fully automated.

### Option B: Cron-based push from any box

Run a cron on any box with push access:

```bash
*/15 * * * * cd /opt/djinn-mirror && git fetch origin && git push codeberg main 2>&1 | logger -t djinn-mirror
```

### Option C: IPFS-pinned snapshot

For real decentralization, periodically pin the build artifact to IPFS and have the watchtower fetch from `ipfs://<hash>/main.tar`. This is more involved (requires the watchtower to speak ipfs), so it's the longer-term endgame, not the next step.

## Verification

After updating `.env`, restart the validator with `pm2 restart djinn-validator --update-env`. Check the logs for:

```
watchtower_started branch=main remotes=['origin', 'codeberg']
watchtower_remote_added name=codeberg url=https://codeberg.org/djinn-inc/djinn.git
```

To test the fallthrough, you can temporarily break the first remote:

```bash
# Point origin at a bad URL temporarily
git remote set-url origin https://github.invalid/djinn-inc/djinn.git
# Wait for the next watchtower cycle (default 15 min)
# Logs should show:
#   watchtower_remote_skip remote=origin
#   watchtower_pulled remote=codeberg ...
# Restore the real URL
git remote set-url origin https://github.com/djinn-inc/djinn.git
```

## Backwards compatibility

The default is `AUTO_UPDATE_REMOTES=origin`, which is byte-equivalent to the previous single-remote behavior. Validators that don't set the env var see no change.
