"""Djinn Protocol Bittensor Validator."""

import subprocess as _sp
import warnings as _warnings
from pathlib import Path as _Path

__version__ = "0"
__git_sha__ = ""

_VERSION_FILE = _Path(__file__).parent / "VERSION"

try:
    _desc = (
        _sp.check_output(
            ["git", "describe", "--tags", "--match", "v[0-9]*", "--long"],
            stderr=_sp.DEVNULL,
            cwd=_Path(__file__).parent,
        )
        .decode()
        .strip()
    )
    _parts = _desc.rsplit("-", 2)
    _tag = _parts[0].lstrip("v")
    _extra = int(_parts[1])
    __version__ = _tag if _extra == 0 else f"{_tag}+{_extra}"
    # The short SHA is always the last segment regardless of tag availability.
    __git_sha__ = _parts[2].lstrip("g") if len(_parts) >= 3 else ""
except Exception as _e:
    # Non-git installs (tarball, copy, container without .git) fall through
    # here. The VERSION file is committed in the repo and gets bumped on
    # every release via scripts/bump-validator-version.sh, so a fresh `git
    # pull` on the operator's box gets the right value without any runtime
    # write-back to a tracked file (which would just dirty the working tree
    # of any dev/CI machine that imports the package).
    _warnings.warn(f"djinn_validator: git describe failed ({_e}), falling back to VERSION file")
    try:
        __version__ = _VERSION_FILE.read_text().strip()
    except Exception as _e2:
        _warnings.warn(f"djinn_validator: VERSION file also unavailable ({_e2}), using __version__='0'")

if not __git_sha__:
    try:
        __git_sha__ = (
            _sp.check_output(
                ["git", "rev-parse", "--short", "HEAD"],
                stderr=_sp.DEVNULL,
                cwd=_Path(__file__).parent,
            )
            .decode()
            .strip()
        )
    except Exception:
        pass

# Commit timestamp of the running code. Lets dashboards answer "is this
# validator running current code?" with an absolute time, independent of
# tag drift and operator clock skew. None on non-git installs (UID 213
# class) — UI should render those as "unknown" rather than guess.
__git_commit_ts__: int | None = None
try:
    _ts = (
        _sp.check_output(
            ["git", "log", "-1", "--format=%ct"],
            stderr=_sp.DEVNULL,
            cwd=_Path(__file__).parent,
        )
        .decode()
        .strip()
    )
    __git_commit_ts__ = int(_ts) if _ts else None
except Exception:
    pass

# Non-git fallback: when `git log` is unavailable (UID 213-style tarball
# install), use the VERSION file's mtime. That's exactly when the
# operator extracted/refreshed their copy, which is the operationally
# meaningful "deploy time" for them. Better than publishing None and
# leaving the network dashboard with "unknown" forever.
if __git_commit_ts__ is None:
    try:
        if _VERSION_FILE.exists():
            __git_commit_ts__ = int(_VERSION_FILE.stat().st_mtime)
    except Exception:
        pass

# Tree state at process start. /health used to recompute these on every
# request via 2-3 inline subprocesses, which under parallel fan-out
# (overview self-probe + peer probes from every other validator) drove
# /health tail latency to 1-4s and made UID 0 appear "Offline" on its
# own /network. They genuinely cannot change while the process is
# running — watchtower restarts pm2 on every pull — so once-at-import
# is correct, not a cache. Operators who want to see live drift can
# hit `git status` on the box; the network dashboard reflects the
# code that's actually running.
__git_dirty__: bool | None = None
__git_dirty_files__: list[str] = []
__git_branch__: str | None = None
try:
    _porcelain = (
        _sp.check_output(
            ["git", "status", "--porcelain"],
            stderr=_sp.DEVNULL,
            cwd=_Path(__file__).parent,
            timeout=3,
        )
        .decode()
        .strip()
    )
    # Only TRACKED-MODIFIED lines block `git pull --rebase`. "?? " is
    # untracked workspace cruft and watchtower doesn't care about it.
    _tracked_dirty = [_line for _line in _porcelain.splitlines() if not _line.startswith("?? ")]
    __git_dirty__ = bool(_tracked_dirty)
    if _tracked_dirty:
        __git_dirty_files__ = [_line.strip().split(maxsplit=1)[-1] for _line in _tracked_dirty[:5]]
    __git_branch__ = (
        _sp.check_output(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            stderr=_sp.DEVNULL,
            cwd=_Path(__file__).parent,
            timeout=3,
        )
        .decode()
        .strip()
    )
except Exception:
    pass
# v1153 watchtower trigger
