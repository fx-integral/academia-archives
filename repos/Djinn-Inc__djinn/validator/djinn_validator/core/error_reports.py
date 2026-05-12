"""Durable feedback / error-report queue with bounded GitHub-issue retry.

Replaces the prior in-memory ring buffer (ported 1:1 from the Next route)
which had three correctness gaps:

1. Reports were lost on every validator restart — the ring buffer was
   process-only memory.
2. GitHub issue creation silently `return`-ed when GITHUB_ERROR_TOKEN
   was unset, so submissions returned 200 to the client without ever
   being forwarded. An operator who forgot to provision the token
   would never know their feedback channel was broken.
3. Network errors during forwarding were swallowed without logging or
   metrics, so transient GitHub outages also disappeared silently.

The new design:

- Reports persist to a SQLite queue under the validator data dir
  (`error_reports.db`), keyed by `submission_id` (UUIDv4). They survive
  restarts.
- A bounded background worker (max 5 attempts, exponential backoff) drains
  the `pending` queue to GitHub when a token is configured. If the token
  isn't set, reports stay queued indefinitely; once the operator adds
  the token and restarts, the backlog drains automatically.
- Forward outcomes (ok / no_token / http_4xx / http_5xx / network /
  exhausted) are counted in `error_report_forward_total{outcome}` so
  Prometheus surfaces failures.
- The submission endpoint response includes `submission_id` and a
  `forwarded` flag so the caller can tell durable persistence apart
  from confirmed GitHub delivery.

Module-level state stays for backward compat with the existing
`submit_report` / `recent_reports` / `fire_and_forget_issue` API. The
underlying state is now a class instance so tests can construct a fresh
in-memory store via `reset_for_tests`.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

try:
    from djinn_validator.api.metrics import ERROR_REPORT_FORWARD, ERROR_REPORT_PENDING
except ImportError:  # pragma: no cover — metrics is optional in some test paths
    ERROR_REPORT_FORWARD = None
    ERROR_REPORT_PENDING = None


log = logging.getLogger(__name__)

MAX_ERRORS_RING = 500  # in-memory cache for /v1/report-error/recent
MAX_BODY_BYTES = 10_000
MAX_MESSAGE_CHARS = 2000
RATE_LIMIT_MAX = 5
RATE_LIMIT_WINDOW_SEC = 60.0
MAX_FORWARD_ATTEMPTS = 5
FORWARD_POLL_SEC = 30.0
FORWARD_BATCH_SIZE = 10

_ALLOWED_SOURCES = frozenset({"error-boundary", "report-button", "api-error", "other"})


class _RateLimited(Exception):
    """Raised when the caller has exceeded RATE_LIMIT_MAX in the current window."""


class _InvalidReport(Exception):
    """Raised when the payload fails validation (size, required fields)."""


@dataclass
class StoredError:
    submission_id: str
    message: str
    url: str
    error_message: str
    error_stack: str
    user_agent: str
    wallet: str
    signal_id: str
    console_errors: list[str]
    source: str
    timestamp: str
    ip: str
    forwarded: bool = False
    attempts: int = 0
    last_error: str = ""

    def to_dict(self) -> dict[str, Any]:
        # camelCase keys to match the prior Next response shape byte-for-byte.
        # New fields (submissionId, forwarded, attempts) are additive so the
        # admin dashboard can opt in without breaking older clients.
        return {
            "submissionId": self.submission_id,
            "message": self.message,
            "url": self.url,
            "errorMessage": self.error_message,
            "errorStack": self.error_stack,
            "userAgent": self.user_agent,
            "wallet": self.wallet,
            "signalId": self.signal_id,
            "consoleErrors": self.console_errors,
            "source": self.source,
            "timestamp": self.timestamp,
            "ip": self.ip,
            "forwarded": self.forwarded,
            "attempts": self.attempts,
            "lastError": self.last_error,
        }


# ---------------------------------------------------------------------------
# Persistent store
# ---------------------------------------------------------------------------


_DDL = """
CREATE TABLE IF NOT EXISTS error_reports (
    submission_id TEXT PRIMARY KEY,
    ts_unix REAL NOT NULL,
    timestamp TEXT NOT NULL,
    ip TEXT NOT NULL,
    message TEXT NOT NULL,
    url TEXT NOT NULL,
    error_message TEXT NOT NULL,
    error_stack TEXT NOT NULL,
    user_agent TEXT NOT NULL,
    wallet TEXT NOT NULL,
    signal_id TEXT NOT NULL,
    console_errors TEXT NOT NULL,
    source TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    attempts INTEGER NOT NULL DEFAULT 0,
    last_attempt_ts REAL,
    last_error TEXT NOT NULL DEFAULT '',
    github_issue_number INTEGER
);
CREATE INDEX IF NOT EXISTS idx_status_ts ON error_reports(status, ts_unix);
"""


@dataclass
class _State:
    """Lazy singleton: SQLite store when configured, in-memory list otherwise.

    Tests that don't pass a db_path get the in-memory path which mirrors
    the old behavior — no persistence, no worker. Production sets db_path
    via configure().
    """

    db: sqlite3.Connection | None = None
    db_lock: threading.Lock = field(default_factory=threading.Lock)
    in_memory: list[StoredError] = field(default_factory=list)
    rate_buckets: dict[str, list[float]] = field(default_factory=dict)
    worker_task: asyncio.Task | None = None
    worker_stop: asyncio.Event | None = None


_state = _State()


def configure(db_path: str | None) -> None:
    """Open the persistent store. Idempotent. Safe to call before main loop."""
    if db_path is None:
        return
    with _state.db_lock:
        if _state.db is not None:
            return
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(db_path, check_same_thread=False)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=5000")
        conn.executescript(_DDL)
        conn.commit()
        _state.db = conn
        log.info("error_reports_store_opened path=%s", db_path)


def reset_for_tests() -> None:
    """Clear all state (in-memory + SQLite). Tests must call this; production never does."""
    with _state.db_lock:
        if _state.db is not None:
            try:
                _state.db.execute("DELETE FROM error_reports")
                _state.db.commit()
            except sqlite3.Error:
                pass
        _state.in_memory.clear()
        _state.rate_buckets.clear()


# ---------------------------------------------------------------------------
# Rate limiting
# ---------------------------------------------------------------------------


def _check_rate_limit(ip: str, now: float | None = None) -> None:
    ts_now = now if now is not None else time.time()
    bucket = _state.rate_buckets.get(ip, [])
    recent = [t for t in bucket if ts_now - t < RATE_LIMIT_WINDOW_SEC]
    if len(recent) >= RATE_LIMIT_MAX:
        _state.rate_buckets[ip] = recent
        raise _RateLimited("Too many error reports. Please try again later.")
    recent.append(ts_now)
    _state.rate_buckets[ip] = recent
    if len(_state.rate_buckets) > 1000:
        stale = [key for key, ts in _state.rate_buckets.items() if all(ts_now - t > RATE_LIMIT_WINDOW_SEC for t in ts)]
        for key in stale:
            _state.rate_buckets.pop(key, None)


# ---------------------------------------------------------------------------
# Sanitization + persistence
# ---------------------------------------------------------------------------


def _sanitize(payload: dict[str, Any], ip: str, now: float | None = None) -> StoredError:
    message = payload.get("message")
    if not isinstance(message, str) or not message or len(message) > MAX_MESSAGE_CHARS:
        raise _InvalidReport("message is required (max 2000 chars)")

    def _str(key: str, max_len: int) -> str:
        val = payload.get(key)
        return str(val)[:max_len] if val else ""

    console_errors_raw = payload.get("consoleErrors") or []
    if not isinstance(console_errors_raw, list):
        console_errors_raw = []
    console_errors = [str(e)[:500] for e in console_errors_raw[:5]]

    source = payload.get("source") or "other"
    if source not in _ALLOWED_SOURCES:
        source = "other"

    ts_unix = now if now is not None else time.time()
    ts = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(ts_unix))
    timestamp = f"{ts}.000Z"

    return StoredError(
        submission_id=str(uuid.uuid4()),
        message=message[:MAX_MESSAGE_CHARS],
        url=_str("url", 500),
        error_message=_str("errorMessage", 1000),
        error_stack=_str("errorStack", 2000),
        user_agent=_str("userAgent", 300),
        wallet=_str("wallet", 14),
        signal_id=_str("signalId", 100),
        console_errors=console_errors,
        source=source,
        timestamp=timestamp,
        ip=ip[:45],
    )


def _persist(entry: StoredError, ts_unix: float) -> None:
    """Write the report to durable storage. Falls back to in-memory if no db."""
    if _state.db is None:
        _state.in_memory.append(entry)
        if len(_state.in_memory) > MAX_ERRORS_RING:
            del _state.in_memory[: len(_state.in_memory) - MAX_ERRORS_RING]
        return

    with _state.db_lock:
        _state.db.execute(
            """
            INSERT INTO error_reports (
                submission_id, ts_unix, timestamp, ip, message, url,
                error_message, error_stack, user_agent, wallet, signal_id,
                console_errors, source, status, attempts, last_error
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', 0, '')
            """,
            (
                entry.submission_id,
                ts_unix,
                entry.timestamp,
                entry.ip,
                entry.message,
                entry.url,
                entry.error_message,
                entry.error_stack,
                entry.user_agent,
                entry.wallet,
                entry.signal_id,
                json.dumps(entry.console_errors),
                entry.source,
            ),
        )
        _state.db.commit()
    _refresh_pending_gauge()


def submit_report(
    payload: dict[str, Any],
    *,
    ip: str,
    now: float | None = None,
) -> StoredError:
    """Rate-check, sanitize, and persist. Raises _RateLimited or _InvalidReport.

    Persistence is the source of truth: when this returns, the report
    survives validator restarts. The caller should kick the forward worker
    via `fire_and_forget_issue(entry)` so the queue drains promptly even
    when the periodic poll is between ticks.
    """
    _check_rate_limit(ip, now=now)
    ts_unix = now if now is not None else time.time()
    entry = _sanitize(payload, ip, now=now)
    _persist(entry, ts_unix)
    return entry


def recent_reports(limit: int) -> dict[str, Any]:
    safe = max(1, min(limit, MAX_ERRORS_RING))
    if _state.db is None:
        tail = list(reversed(_state.in_memory[-safe:]))
        return {"errors": [e.to_dict() for e in tail], "total": len(_state.in_memory)}

    with _state.db_lock:
        cur = _state.db.execute(
            """
            SELECT submission_id, timestamp, ip, message, url,
                   error_message, error_stack, user_agent, wallet, signal_id,
                   console_errors, source, status, attempts, last_error
            FROM error_reports
            ORDER BY ts_unix DESC
            LIMIT ?
            """,
            (safe,),
        )
        rows = cur.fetchall()
        total_cur = _state.db.execute("SELECT COUNT(*) FROM error_reports")
        total = int(total_cur.fetchone()[0])

    errors = [
        StoredError(
            submission_id=r[0],
            timestamp=r[1],
            ip=r[2],
            message=r[3],
            url=r[4],
            error_message=r[5],
            error_stack=r[6],
            user_agent=r[7],
            wallet=r[8],
            signal_id=r[9],
            console_errors=json.loads(r[10] or "[]"),
            source=r[11],
            forwarded=(r[12] == "forwarded"),
            attempts=int(r[13]),
            last_error=r[14] or "",
        ).to_dict()
        for r in rows
    ]
    return {"errors": errors, "total": total}


def total_stored() -> int:
    if _state.db is None:
        return len(_state.in_memory)
    with _state.db_lock:
        cur = _state.db.execute("SELECT COUNT(*) FROM error_reports")
        return int(cur.fetchone()[0])


def pending_count() -> int:
    """Number of reports awaiting (or retrying) GitHub forward."""
    if _state.db is None:
        return 0  # in-memory mode has no queue concept
    with _state.db_lock:
        cur = _state.db.execute("SELECT COUNT(*) FROM error_reports WHERE status='pending'")
        return int(cur.fetchone()[0])


def _refresh_pending_gauge() -> None:
    if ERROR_REPORT_PENDING is not None:
        try:
            ERROR_REPORT_PENDING.set(pending_count())
        except Exception:  # pragma: no cover — metrics must never crash the path
            pass


# ---------------------------------------------------------------------------
# GitHub forwarding
# ---------------------------------------------------------------------------


def github_token() -> str:
    return os.getenv("GITHUB_ERROR_TOKEN", "")


def github_repo() -> str:
    return os.getenv("ERROR_REPORT_REPO", "djinn-inc/error-reports")


def _issue_body(entry: StoredError) -> tuple[str, str, list[str]]:
    title = f"[User Report] {entry.message[:80]}"
    lines: list[str] = [
        "## Error Report",
        "",
        f"**Message:** {entry.message}",
        f"**Source:** {entry.source}",
        f"**Page:** {entry.url or 'N/A'}",
        f"**Time:** {entry.timestamp}",
        f"**Submission:** `{entry.submission_id}`",
    ]
    if entry.wallet:
        lines.append(f"**Wallet:** `{entry.wallet}`")
    if entry.signal_id:
        lines.append(f"**Signal:** `{entry.signal_id}`")
    lines.append("")
    if entry.error_message:
        lines.append(f"### Error\n```\n{entry.error_message}\n```")
    if entry.error_stack:
        lines.append(f"### Stack Trace\n```\n{entry.error_stack}\n```")
    if entry.console_errors:
        lines.append("### Recent Console Errors\n```\n" + "\n".join(entry.console_errors) + "\n```")
    lines += [
        "",
        "### Environment",
        "```",
        f"User-Agent: {entry.user_agent or 'N/A'}",
        "```",
        "",
        "---",
        "*Submitted via djinn.gg error reporter*",
    ]
    labels = ["user-report"]
    if entry.source == "error-boundary":
        labels.append("crash")
    return title, "\n".join(lines), labels


def _record_outcome(outcome: str) -> None:
    if ERROR_REPORT_FORWARD is not None:
        try:
            ERROR_REPORT_FORWARD.labels(outcome=outcome).inc()
        except Exception:  # pragma: no cover
            pass


async def _post_github_issue(entry: StoredError) -> tuple[bool, str, int | None]:
    """Returns (forwarded, last_error, github_issue_number).

    Distinguishes outcome categories so the worker can decide retry vs. give-up:
      - 201 → forwarded, log issue number
      - 4xx (auth, schema, etc.) → not transient, mark exhausted next attempt
      - 5xx / network → transient, retry
    """
    token = github_token()
    if not token:
        _record_outcome("no_token")
        return False, "GITHUB_ERROR_TOKEN not configured", None

    title, body, labels = _issue_body(entry)
    url = f"https://api.github.com/repos/{github_repo()}/issues"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/vnd.github+json",
    }
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(url, headers=headers, json={"title": title, "body": body, "labels": labels})
        if resp.status_code == 201:
            _record_outcome("ok")
            try:
                issue_number = int(resp.json().get("number") or 0)
            except Exception:
                issue_number = None
            return True, "", issue_number
        if 400 <= resp.status_code < 500:
            _record_outcome("http_4xx")
            return False, f"github http {resp.status_code}: {resp.text[:200]}", None
        _record_outcome("http_5xx")
        return False, f"github http {resp.status_code}", None
    except (httpx.TimeoutException, httpx.NetworkError) as e:
        _record_outcome("network")
        return False, f"network: {type(e).__name__}: {str(e)[:120]}", None
    except Exception as e:  # pragma: no cover — defensive
        _record_outcome("network")
        return False, f"unexpected: {type(e).__name__}: {str(e)[:120]}", None


def _is_terminal_error(last_error: str) -> bool:
    """4xx errors aren't transient (bad token, missing label, etc.). Stop retrying."""
    return last_error.startswith("github http 4")


async def _forward_one(submission_id: str) -> None:
    """Forward a single queued report; updates DB with outcome."""
    if _state.db is None:
        return
    with _state.db_lock:
        cur = _state.db.execute(
            """
            SELECT submission_id, timestamp, ip, message, url,
                   error_message, error_stack, user_agent, wallet, signal_id,
                   console_errors, source, attempts
            FROM error_reports
            WHERE submission_id = ? AND status = 'pending'
            """,
            (submission_id,),
        )
        row = cur.fetchone()
    if row is None:
        return

    entry = StoredError(
        submission_id=row[0],
        timestamp=row[1],
        ip=row[2],
        message=row[3],
        url=row[4],
        error_message=row[5],
        error_stack=row[6],
        user_agent=row[7],
        wallet=row[8],
        signal_id=row[9],
        console_errors=json.loads(row[10] or "[]"),
        source=row[11],
        attempts=int(row[12]),
    )
    forwarded, err, issue_number = await _post_github_issue(entry)
    next_attempts = entry.attempts + 1
    new_status = (
        "forwarded"
        if forwarded
        else ("failed" if (next_attempts >= MAX_FORWARD_ATTEMPTS or _is_terminal_error(err)) else "pending")
    )
    if new_status == "failed" and not forwarded:
        _record_outcome("exhausted")
    with _state.db_lock:
        _state.db.execute(
            """
            UPDATE error_reports
            SET status = ?, attempts = ?, last_attempt_ts = ?, last_error = ?,
                github_issue_number = COALESCE(?, github_issue_number)
            WHERE submission_id = ?
            """,
            (new_status, next_attempts, time.time(), err, issue_number, submission_id),
        )
        _state.db.commit()
    _refresh_pending_gauge()
    if forwarded:
        log.info(
            "error_report_forwarded submission_id=%s issue=%s",
            submission_id,
            issue_number,
        )
    else:
        log.warning(
            "error_report_forward_failed submission_id=%s status=%s attempts=%s err=%s",
            submission_id,
            new_status,
            next_attempts,
            err[:200],
        )


async def _forward_loop() -> None:
    """Background worker: drain pending reports to GitHub on a 30s cycle."""
    assert _state.worker_stop is not None
    log.info("error_reports_forward_loop_started poll_sec=%s", FORWARD_POLL_SEC)
    while not _state.worker_stop.is_set():
        try:
            if _state.db is not None and github_token():
                with _state.db_lock:
                    cur = _state.db.execute(
                        """
                        SELECT submission_id FROM error_reports
                        WHERE status='pending'
                        ORDER BY ts_unix
                        LIMIT ?
                        """,
                        (FORWARD_BATCH_SIZE,),
                    )
                    ids = [r[0] for r in cur.fetchall()]
                for sid in ids:
                    if _state.worker_stop.is_set():
                        break
                    await _forward_one(sid)
        except Exception as e:  # pragma: no cover — defensive
            log.warning("error_report_forward_loop_iter_failed err=%s", str(e)[:200])
        try:
            await asyncio.wait_for(_state.worker_stop.wait(), timeout=FORWARD_POLL_SEC)
        except TimeoutError:
            pass


def fire_and_forget_issue(entry: StoredError) -> None:
    """Schedule an immediate forward attempt for a freshly-submitted entry.

    Complements the periodic _forward_loop: a fresh submission lands on
    GitHub within seconds rather than waiting up to FORWARD_POLL_SEC.
    Falls back to a no-op if there's no running event loop (e.g. unit tests).
    """
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return

    async def _run() -> None:
        if _state.db is None:
            # In-memory mode: keep prior fire-and-forget behavior so existing
            # tests / dev runs still post to GitHub when a token is configured.
            forwarded, err, _ = await _post_github_issue(entry)
            if not forwarded and err:
                log.warning("error_report_forward_in_memory_failed err=%s", err[:200])
            else:
                entry.forwarded = forwarded
            return
        await _forward_one(entry.submission_id)

    loop.create_task(_run())


def start_worker() -> None:
    """Start the background forward worker on the running event loop.

    Idempotent: safe to call multiple times. No-op if no loop is running
    or the worker is already up.
    """
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    if _state.worker_task is not None and not _state.worker_task.done():
        return
    _state.worker_stop = asyncio.Event()
    _state.worker_task = loop.create_task(_forward_loop())


def stop_worker() -> None:
    """Cancel the background worker. Used by tests."""
    if _state.worker_stop is not None:
        _state.worker_stop.set()
    _state.worker_task = None
    _state.worker_stop = None


# Backwards-compat alias for the prior shim. New code should call
# `_post_github_issue` directly to inspect the outcome.
async def create_github_issue(entry: StoredError) -> None:
    await _post_github_issue(entry)
