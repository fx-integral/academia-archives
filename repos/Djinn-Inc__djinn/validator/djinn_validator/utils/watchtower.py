"""Auto-update watchtower for Djinn Protocol nodes.

Polls the remote git repository for new commits on the configured branch.
When an update is detected, pulls the latest code, reinstalls dependencies
with ``uv sync``, and restarts the process via ``os.execv``.

Enable by setting ``AUTO_UPDATE=true`` in the environment. Configuration:

    AUTO_UPDATE            – "true" to enable (default: "false")
    AUTO_UPDATE_BRANCH     – branch to track (default: "main")
    AUTO_UPDATE_INTERVAL   – seconds between checks (default: 900)
    AUTO_UPDATE_REPO_ROOT  – path to the git repo root; auto-detected if unset
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
from pathlib import Path

import structlog

log = structlog.get_logger()

_ENABLED = os.getenv("AUTO_UPDATE", "false").lower() in ("true", "1", "yes")
_BRANCH = os.getenv("AUTO_UPDATE_BRANCH", "main")
_INTERVAL = int(os.getenv("AUTO_UPDATE_INTERVAL", "900"))  # 15 minutes default

# Decentralized watchtower: list of git remotes to try in order. The
# first one that responds wins. Default is just "origin", but operators
# can set AUTO_UPDATE_REMOTES="origin,github,codeberg" so a single
# remote outage doesn't pin them at an old commit.
#
# Pair with AUTO_UPDATE_REMOTE_URLS to declare additional remote URLs
# the watchtower auto-creates if they don't exist:
#   AUTO_UPDATE_REMOTE_URLS="codeberg=https://codeberg.org/djinn-inc/djinn.git;mirror=git@gitlab.com:djinn-inc/djinn.git"
_REMOTES = [r.strip() for r in os.getenv("AUTO_UPDATE_REMOTES", "origin").split(",") if r.strip()]
_REMOTE_URLS: dict[str, str] = {}
for _entry in os.getenv("AUTO_UPDATE_REMOTE_URLS", "").split(";"):
    _entry = _entry.strip()
    if "=" in _entry:
        _name, _url = _entry.split("=", 1)
        _REMOTE_URLS[_name.strip()] = _url.strip()


def _find_repo_root() -> Path | None:
    """Walk up from this file to find the git repo root."""
    override = os.getenv("AUTO_UPDATE_REPO_ROOT")
    if override:
        p = Path(override)
        if (p / ".git").exists():
            return p
        return None
    d = Path(__file__).resolve().parent
    for _ in range(10):
        if (d / ".git").exists():
            return d
        d = d.parent
    return None


def _run(cmd: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=120)


def _local_sha(repo: Path) -> str | None:
    """Return the current HEAD sha."""
    try:
        r = _run(["git", "rev-parse", "HEAD"], repo)
        return r.stdout.strip() if r.returncode == 0 else None
    except Exception:
        return None


def _ensure_remote(repo: Path, name: str, url: str) -> bool:
    """Ensure a named git remote exists at the given URL.

    If the remote is missing, create it. If it exists with a different
    URL, update it. Returns True on success.
    """
    try:
        existing = _run(["git", "remote", "get-url", name], repo)
        if existing.returncode != 0:
            r = _run(["git", "remote", "add", name, url], repo)
            if r.returncode == 0:
                log.info("watchtower_remote_added", name=name, url=url)
                return True
            log.warning("watchtower_remote_add_failed", name=name, stderr=r.stderr[:200])
            return False
        if existing.stdout.strip() != url:
            r = _run(["git", "remote", "set-url", name, url], repo)
            if r.returncode == 0:
                log.info("watchtower_remote_updated", name=name, url=url)
                return True
            return False
        return True
    except Exception as e:
        log.warning("watchtower_remote_setup_error", name=name, error=str(e))
        return False


def _ensure_configured_remotes(repo: Path) -> None:
    """Make sure every remote declared in AUTO_UPDATE_REMOTE_URLS exists."""
    for name, url in _REMOTE_URLS.items():
        _ensure_remote(repo, name, url)


def _remote_sha(repo: Path, branch: str) -> tuple[str | None, str | None]:
    """Return (sha, remote_name) from the first remote that responds.

    Tries every entry in _REMOTES in order. Returns (None, None) if all
    remotes fail.
    """
    for remote in _REMOTES:
        try:
            r = _run(["git", "ls-remote", remote, branch], repo)
            if r.returncode == 0 and r.stdout.strip():
                return r.stdout.split()[0], remote
            log.debug("watchtower_remote_skip", remote=remote, reason=r.stderr[:100])
        except Exception as e:
            log.debug("watchtower_remote_error", remote=remote, error=str(e))
            continue
    return None, None


def _pull(repo: Path, branch: str, preferred_remote: str | None = None) -> bool:
    """Pull the latest code from the first available remote.

    `preferred_remote` is tried first (typically the remote that just
    returned a fresh sha in _remote_sha). On failure, falls through to
    the rest of the configured remotes.
    """
    order: list[str] = []
    if preferred_remote and preferred_remote in _REMOTES:
        order.append(preferred_remote)
    for r in _REMOTES:
        if r not in order:
            order.append(r)

    for remote in order:
        try:
            _run(["git", "fetch", "--tags", remote], repo)
            # Discard any tracked-file pollution before pulling. The
            # canonical case is the v1625 self-heal regression: that
            # release wrote `git describe` output back to VERSION on
            # every import, leaving every operator's working tree dirty.
            # `git pull --rebase` then refused to run ("you have unstaged
            # changes"), wedging watchtower indefinitely. See v1626 fix
            # and project_p001_sync_jam_2026_05_01.md. `git checkout .`
            # only resets TRACKED files (VERSION, ...), never untracked
            # ones (.env, local data dirs), so this is safe under our
            # `.env`-is-gitignored convention.
            _run(["git", "checkout", "."], repo)
            r = _run(["git", "pull", "--rebase", remote, branch], repo)
            if r.returncode == 0:
                log.info(
                    "watchtower_pulled",
                    remote=remote,
                    stdout=r.stdout.strip()[:200],
                )
                return True
            log.warning(
                "watchtower_pull_remote_failed",
                remote=remote,
                stderr=r.stderr[:300],
            )
            # Abort any in-progress rebase before trying the next remote
            _run(["git", "rebase", "--abort"], repo)
        except Exception as e:
            log.warning("watchtower_pull_remote_error", remote=remote, error=str(e))
            _run(["git", "rebase", "--abort"], repo)

    log.error("watchtower_pull_failed_all_remotes", remotes=order)
    return False


def _install_deps(package_dir: Path) -> bool:
    """Install dependencies. Tries uv sync first, falls back to pip."""
    # Install djinn-tunnel-shield from local path if available
    shield_dir = package_dir.parent / "shield"
    if shield_dir.is_dir():
        try:
            r = _run([sys.executable, "-m", "pip", "install", "-q", str(shield_dir)], package_dir)
            if r.returncode == 0:
                log.info("watchtower_shield_installed")
            else:
                log.warning("watchtower_shield_install_failed", stderr=r.stderr[:300])
        except Exception as e:
            log.warning("watchtower_shield_install_error", error=str(e))

    try:
        r = _run(["uv", "sync"], package_dir)
        if r.returncode != 0:
            log.error("watchtower_uv_sync_failed", stderr=r.stderr[:500])
            return False
        log.info("watchtower_deps_installed")
        return True
    except FileNotFoundError:
        # uv not available; fall back to pip install
        log.warning("watchtower_uv_not_found", msg="uv not installed, trying pip install")
        try:
            r = _run(
                [sys.executable, "-m", "pip", "install", "-q", str(package_dir)],
                package_dir,
            )
            if r.returncode != 0:
                log.error("watchtower_pip_install_failed", stderr=r.stderr[:500])
                return False
            log.info("watchtower_deps_installed_via_pip")
            return True
        except Exception as e:
            log.error("watchtower_pip_fallback_error", error=str(e))
            return False
    except Exception as e:
        log.error("watchtower_install_error", error=str(e))
        return False


def _close_server_sockets() -> None:
    """Close any listening sockets before execv to avoid FD inheritance.

    os.execv replaces the process but inherited FDs (without CLOEXEC) survive.
    A stale listening socket on port 8421 would steal connections from the new
    uvicorn server, causing intermittent hangs. Closing them here ensures the
    new process starts with a clean slate.
    """
    import socket

    port = int(os.environ.get("DJINN_PORT", "8421"))
    closed = 0

    # Use /proc/self/fd to find all open FDs (not just 3-1023)
    proc_fd = Path("/proc/self/fd")
    if proc_fd.is_dir():
        fds = []
        for entry in proc_fd.iterdir():
            try:
                fd = int(entry.name)
                if fd >= 3:
                    fds.append(fd)
            except ValueError:
                continue
    else:
        # Fallback for non-Linux: scan a reasonable range
        fds = list(range(3, 65536))

    for fd in fds:
        try:
            s = socket.fromfd(fd, socket.AF_INET, socket.SOCK_STREAM)
            try:
                addr = s.getsockname()
                if isinstance(addr, tuple) and len(addr) >= 2 and addr[1] == port:
                    os.close(fd)
                    closed += 1
            finally:
                # fromfd dups the fd; close the dup without closing the original
                # (we already closed the original above if it matched)
                s.detach()
        except (OSError, ValueError):
            pass
    if closed:
        log.info("watchtower_closed_sockets", count=closed, port=port)


def _restart() -> None:
    """Restart the current process in-place."""
    log.info("watchtower_restarting", argv=sys.argv)
    _close_server_sockets()
    os.execv(sys.executable, [sys.executable] + sys.argv)


def _verify_commit_signature(repo: Path) -> None:
    """Check GPG signature status of HEAD and log accordingly.

    This is a soft check: warnings are emitted for unsigned or bad signatures,
    but the update is never blocked. Operators can monitor logs for
    ``watchtower_unsigned_commit`` events and act on them.
    """
    try:
        r = _run(["git", "log", "-1", "--format=%G?|%H|%an", "HEAD"], repo)
        if r.returncode != 0:
            log.warning(
                "watchtower_sig_check_failed",
                msg="Could not check commit signature",
                stderr=r.stderr[:200],
            )
            return
        parts = r.stdout.strip().split("|", 2)
        if len(parts) < 3:
            log.warning("watchtower_sig_parse_error", raw=r.stdout.strip()[:100])
            return
        status, commit_hash, author = parts
        if status in ("G", "U"):
            log.info(
                "watchtower_signature_verified",
                status=status,
                commit=commit_hash[:8],
                author=author,
            )
        else:
            log.warning(
                "watchtower_unsigned_commit",
                status=status,
                commit=commit_hash[:8],
                author=author,
                msg="Commit is not GPG-signed; proceeding anyway",
            )
    except Exception as e:
        log.warning("watchtower_sig_check_error", error=str(e))


def _validator_code_changed(repo: Path, old_sha: str) -> bool:
    """Check if any validator or miner code changed between old_sha and HEAD."""
    try:
        r = _run(["git", "diff", "--name-only", old_sha, "HEAD"], repo)
        if r.returncode != 0:
            return True  # assume changed if diff fails
        changed = r.stdout.strip().splitlines()
        # Only restart for validator/ or shared config changes.
        # Miner changes don't require a validator restart.
        relevant_prefixes = ("validator/", "shield/", "pyproject.toml", "uv.lock")
        return any(f.startswith(relevant_prefixes) for f in changed)
    except Exception:
        return True  # restart on error to be safe


async def watch_loop(package_dir: Path | None = None) -> None:
    """Main watchtower loop. Runs forever, checking for updates.

    Args:
        package_dir: Directory containing pyproject.toml for ``uv sync``.
                     If None, uses the repo root.
    """
    if not _ENABLED:
        log.info("watchtower_disabled", msg="Set AUTO_UPDATE=true to enable")
        return

    repo = _find_repo_root()
    if repo is None:
        log.error("watchtower_no_repo", msg="Could not find git repository root")
        return

    if package_dir is None:
        package_dir = repo

    _ensure_configured_remotes(repo)

    log.info(
        "watchtower_started",
        branch=_BRANCH,
        interval_s=_INTERVAL,
        repo=str(repo),
        package_dir=str(package_dir),
        remotes=_REMOTES,
    )

    import random

    # Stagger initial check so validators don't all hit GitHub simultaneously
    await asyncio.sleep(random.uniform(30, 120))

    while True:
        await asyncio.sleep(_INTERVAL + random.uniform(-60, 60))
        try:
            local = _local_sha(repo)
            remote, remote_name = _remote_sha(repo, _BRANCH)

            if local is None or remote is None:
                log.debug("watchtower_skip", local=local, remote=remote)
                continue

            if local == remote:
                log.debug("watchtower_up_to_date", sha=local[:8])
                continue

            log.info(
                "watchtower_update_detected",
                local=local[:8],
                remote=remote[:8],
                remote_name=remote_name,
                branch=_BRANCH,
            )

            # Check which files changed before pulling
            old_sha = local

            if not _pull(repo, _BRANCH, preferred_remote=remote_name):
                continue

            _verify_commit_signature(repo)

            # Only restart if validator code changed. Web-only commits
            # (web/, docs/, scripts/) don't need a validator restart.
            if not _validator_code_changed(repo, old_sha):
                log.info(
                    "watchtower_skip_restart",
                    msg="No validator code changes, skipping restart",
                    old=old_sha[:8],
                    new=remote[:8],
                )
                continue

            if not _install_deps(package_dir):
                # Deps failed: revert to old commit so on-disk code matches
                # what's running. Prevents crash loops if process restarts.
                log.warning(
                    "watchtower_reverting",
                    msg="Dep install failed, reverting to previous commit",
                    old=old_sha[:8],
                )
                _run(["git", "reset", "--hard", old_sha], repo)
                continue

            _restart()

        except Exception as e:
            log.error("watchtower_error", error=str(e))
