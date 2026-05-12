"""Durable outbound peer-gossip retry queue (v1744).

Background
----------
v1721 added 3 in-memory retry rounds (30s, 90s, 240s) to
``_gossip_purchase_odds_to_peers``. That covers transient 504s and brief
peer restarts (the original P0-01 layer-3 fix). It does NOT cover the
case where a peer is offline for >6 minutes during the gossip window:
once the in-memory budget exhausts, the originating validator gives up,
and the offline peer permanently lacks BPA/WPA for that (signal, buyer)
tuple. At settlement time, that peer prefetches from peers, gets 404
from the offline-at-commit peer (which is no longer offline but never
received the data), abstains. After 10 abstain ticks the audit_set is
permanent_abstain-evicted and never settles.

This module persists every non-acked-non-permanent peer to SQLite at
the end of the in-memory retry budget. A background worker drains the
queue continuously, so a peer that recovers 1 hour later still
eventually receives the gossip and can participate in the audit.

Design mirrors v1743 ``error_reports.py``:

- One SQLite file (``gossip_outbox.db``)
- One row per (peer_uid, endpoint, payload_hash) tuple
- Status: ``pending`` -> ``acked`` | ``failed_terminal``
- Exponential backoff capped at MAX_RETRY_INTERVAL_SEC
- Hard horizon at MAX_LIFETIME_SEC after which a row goes failed_terminal
- Idempotent at the DB level via UNIQUE(peer_uid, endpoint, payload_hash)
  so a re-enqueue from a fresh in-memory round dedups against an existing
  pending row instead of multiplying entries

The queue is intentionally generic (path-agnostic) so a future
v1745 outcome-gossip retry can reuse the same machinery without
copy-paste. Today only the BPA/WPA path enqueues.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import sqlite3
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

log = logging.getLogger(__name__)

# Tunables. Defaults are conservative; operators can override via env.
RETRY_POLL_SEC = float(os.environ.get("DJINN_GOSSIP_OUTBOX_POLL_SEC", "60"))
RETRY_BATCH_SIZE = int(os.environ.get("DJINN_GOSSIP_OUTBOX_BATCH", "20"))
RETRY_HTTP_TIMEOUT_SEC = float(os.environ.get("DJINN_GOSSIP_OUTBOX_HTTP_TIMEOUT", "10"))
INITIAL_RETRY_INTERVAL_SEC = float(os.environ.get("DJINN_GOSSIP_OUTBOX_INITIAL_INTERVAL", "300"))  # 5 min
MAX_RETRY_INTERVAL_SEC = float(os.environ.get("DJINN_GOSSIP_OUTBOX_MAX_INTERVAL", "3600"))  # 1 h
MAX_LIFETIME_SEC = float(os.environ.get("DJINN_GOSSIP_OUTBOX_MAX_LIFETIME", "86400"))  # 24 h
BACKOFF_BASE = float(os.environ.get("DJINN_GOSSIP_OUTBOX_BACKOFF_BASE", "2.0"))


_DDL = """
CREATE TABLE IF NOT EXISTS gossip_outbox (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    enqueue_ts REAL NOT NULL,
    peer_uid INTEGER NOT NULL,
    peer_url TEXT NOT NULL,
    peer_hotkey TEXT NOT NULL,
    endpoint TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    payload_hash TEXT NOT NULL,
    path_label TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    attempts INTEGER NOT NULL DEFAULT 0,
    last_attempt_ts REAL,
    next_attempt_ts REAL NOT NULL,
    last_error TEXT NOT NULL DEFAULT '',
    acked_ts REAL,
    UNIQUE(peer_uid, endpoint, payload_hash)
);
CREATE INDEX IF NOT EXISTS idx_outbox_status_next ON gossip_outbox(status, next_attempt_ts);
"""


@dataclass
class _State:
    db: sqlite3.Connection | None = None
    db_lock: threading.Lock = field(default_factory=threading.Lock)
    worker_task: asyncio.Task | None = None
    worker_stop: asyncio.Event | None = None
    # Caller wires a signer at configure() time so the worker can sign retries
    # with the live wallet. We store a callable rather than the wallet itself
    # so tests can inject a stub without depending on bittensor types.
    signer: Callable[[str, bytes], dict[str, str]] | None = None


_state = _State()


def configure(
    db_path: str | None,
    signer: Callable[[str, bytes], dict[str, str]] | None = None,
) -> None:
    """Open the persistent store. Idempotent.

    Args:
        db_path: SQLite file path. Pass None to disable persistence
            (in-memory mode; enqueue becomes a no-op, primarily for tests).
        signer: A callable ``signer(endpoint, body) -> dict[str, str]`` that
            returns the X-Hotkey/X-Signature/etc. headers needed to
            authenticate retries to peer ``/v1/...`` endpoints. The retry
            worker calls this on every drain so the signature is fresh.
            Pass None to disable retries (the worker still drains
            terminally-failed rows but doesn't attempt new POSTs).
    """
    if db_path is None:
        # Even without persistence, configure still latches the signer so
        # callers using `enqueue` for in-process testing don't crash.
        _state.signer = signer
        return
    with _state.db_lock:
        _state.signer = signer
        if _state.db is not None:
            return
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(db_path, check_same_thread=False)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=5000")
        conn.executescript(_DDL)
        conn.commit()
        _state.db = conn
        log.info("gossip_outbox_store_opened path=%s", db_path)


def reset_for_tests() -> None:
    """Wipe state. Tests must call between cases; production never does."""
    with _state.db_lock:
        if _state.db is not None:
            try:
                _state.db.execute("DELETE FROM gossip_outbox")
                _state.db.commit()
            except sqlite3.Error:
                pass
        _state.signer = None


def _payload_hash(payload: dict[str, Any]) -> str:
    """Deterministic hash of payload for dedup."""
    body = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    return hashlib.sha256(body).hexdigest()


def enqueue(
    peer_uid: int,
    peer_url: str,
    peer_hotkey: str,
    endpoint: str,
    payload: dict[str, Any],
    path_label: str = "purchase_odds",
) -> bool:
    """Add a non-acked peer/payload to the durable retry queue.

    Returns True on enqueue, False if the row already exists (dedup) or
    persistence is disabled.

    The caller passes the already-prepared payload dict; the worker will
    re-serialize on drain so a stale signature from the original gossip
    attempt doesn't cause silent rejects.
    """
    if _state.db is None:
        return False
    h = _payload_hash(payload)
    body_json = json.dumps(payload, separators=(",", ":"))
    now = time.time()
    next_attempt = now + INITIAL_RETRY_INTERVAL_SEC
    with _state.db_lock:
        try:
            _state.db.execute(
                """
                INSERT INTO gossip_outbox
                  (enqueue_ts, peer_uid, peer_url, peer_hotkey, endpoint,
                   payload_json, payload_hash, path_label,
                   status, attempts, next_attempt_ts)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending', 0, ?)
                """,
                (
                    now,
                    int(peer_uid),
                    peer_url,
                    peer_hotkey,
                    endpoint,
                    body_json,
                    h,
                    path_label,
                    next_attempt,
                ),
            )
            _state.db.commit()
            return True
        except sqlite3.IntegrityError:
            # Dedup: row already pending or terminal for this triple.
            return False


def pending_count() -> int:
    """Number of rows in pending state. Used by /v1/audit/summary."""
    if _state.db is None:
        return 0
    with _state.db_lock:
        cur = _state.db.execute("SELECT COUNT(*) FROM gossip_outbox WHERE status='pending'")
        return int(cur.fetchone()[0])


def stats() -> dict[str, int]:
    """Per-status counts. Surfaced on /v1/audit/summary."""
    out = {"pending": 0, "acked": 0, "failed_terminal": 0}
    if _state.db is None:
        return out
    with _state.db_lock:
        cur = _state.db.execute("SELECT status, COUNT(*) FROM gossip_outbox GROUP BY status")
        for status, count in cur.fetchall():
            if status in out:
                out[status] = int(count)
    return out


def _backoff_seconds(attempts: int) -> float:
    """Exponential backoff with cap. attempts is the count BEFORE this round."""
    interval = INITIAL_RETRY_INTERVAL_SEC * (BACKOFF_BASE**attempts)
    return min(interval, MAX_RETRY_INTERVAL_SEC)


async def _attempt_one(row: tuple[Any, ...]) -> None:
    """POST one queued entry, update status. Caller holds no lock."""
    (
        row_id,
        enqueue_ts,
        peer_url,
        endpoint,
        payload_json,
        attempts,
    ) = row
    now = time.time()
    if now - enqueue_ts >= MAX_LIFETIME_SEC:
        # Past the lifetime horizon — give up.
        with _state.db_lock:
            _state.db.execute(
                """
                UPDATE gossip_outbox
                SET status='failed_terminal', last_attempt_ts=?, last_error=?
                WHERE id=?
                """,
                (now, "max_lifetime_exceeded", row_id),
            )
            _state.db.commit()
        log.info("gossip_outbox_lifetime_exceeded id=%s", row_id)
        return

    if _state.signer is None:
        # No signer configured (test mode or pre-startup); reschedule and bail.
        with _state.db_lock:
            _state.db.execute(
                "UPDATE gossip_outbox SET next_attempt_ts=? WHERE id=?",
                (now + RETRY_POLL_SEC, row_id),
            )
            _state.db.commit()
        return

    body = payload_json.encode()
    try:
        headers = _state.signer(endpoint, body)
    except Exception as e:
        log.warning("gossip_outbox_sign_failed id=%s err=%s", row_id, str(e)[:120])
        # Treat as transient; reschedule.
        new_attempts = attempts + 1
        with _state.db_lock:
            _state.db.execute(
                """
                UPDATE gossip_outbox
                SET attempts=?, last_attempt_ts=?, last_error=?, next_attempt_ts=?
                WHERE id=?
                """,
                (new_attempts, now, f"sign_failed:{e}"[:200], now + _backoff_seconds(new_attempts), row_id),
            )
            _state.db.commit()
        return

    try:
        async with httpx.AsyncClient(timeout=RETRY_HTTP_TIMEOUT_SEC) as client:
            resp = await client.post(
                f"{peer_url}{endpoint}",
                content=body,
                headers={"Content-Type": "application/json", **headers},
            )
        status_code = resp.status_code
    except httpx.HTTPError as e:
        status_code = -1
        last_err = f"httpx:{type(e).__name__}:{str(e)[:100]}"
    else:
        last_err = ""

    new_attempts = attempts + 1
    if status_code == 200:
        new_status = "acked"
        next_ts = now
        outcome = "acked"
    elif 400 <= status_code < 500:
        # 4xx is permanent — peer rejected the payload (auth, validation,
        # 404 on old peer). Stop retrying.
        new_status = "failed_terminal"
        next_ts = now
        last_err = f"http_{status_code}"
        outcome = "failed_terminal"
    else:
        # 5xx, network error, or unknown — transient, schedule next retry.
        new_status = "pending"
        next_ts = now + _backoff_seconds(new_attempts)
        if not last_err:
            last_err = f"http_{status_code}"
        outcome = "retry"

    with _state.db_lock:
        if new_status == "acked":
            _state.db.execute(
                """
                UPDATE gossip_outbox
                SET status='acked', attempts=?, last_attempt_ts=?, acked_ts=?, last_error=''
                WHERE id=?
                """,
                (new_attempts, now, now, row_id),
            )
        else:
            _state.db.execute(
                """
                UPDATE gossip_outbox
                SET status=?, attempts=?, last_attempt_ts=?, last_error=?, next_attempt_ts=?
                WHERE id=?
                """,
                (new_status, new_attempts, now, last_err[:200], next_ts, row_id),
            )
        _state.db.commit()

    if outcome == "acked":
        log.info(
            "gossip_outbox_acked id=%s peer=%s endpoint=%s attempts=%s",
            row_id,
            peer_url,
            endpoint,
            new_attempts,
        )
    elif outcome == "failed_terminal":
        log.warning(
            "gossip_outbox_terminal id=%s peer=%s endpoint=%s err=%s",
            row_id,
            peer_url,
            endpoint,
            last_err,
        )
    # transient is silent at info level — only failures are noisy


async def drain_once() -> int:
    """Drain up to RETRY_BATCH_SIZE pending rows. Returns count attempted."""
    if _state.db is None:
        return 0
    now = time.time()
    with _state.db_lock:
        cur = _state.db.execute(
            """
            SELECT id, enqueue_ts, peer_url, endpoint, payload_json, attempts
            FROM gossip_outbox
            WHERE status='pending' AND next_attempt_ts <= ?
            ORDER BY next_attempt_ts ASC
            LIMIT ?
            """,
            (now, RETRY_BATCH_SIZE),
        )
        rows = cur.fetchall()
    for row in rows:
        await _attempt_one(row)
    return len(rows)


async def _drain_loop() -> None:
    """Background worker. Polls every RETRY_POLL_SEC."""
    assert _state.worker_stop is not None
    log.info("gossip_outbox_drain_loop_started poll_sec=%s", RETRY_POLL_SEC)
    while not _state.worker_stop.is_set():
        try:
            await drain_once()
        except Exception as e:  # pragma: no cover — defensive
            log.warning("gossip_outbox_drain_iter_failed err=%s", str(e)[:200])
        try:
            await asyncio.wait_for(_state.worker_stop.wait(), timeout=RETRY_POLL_SEC)
        except TimeoutError:
            pass


def start_worker() -> None:
    """Start the background drain worker on the running event loop. Idempotent."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    if _state.worker_task is not None and not _state.worker_task.done():
        return
    _state.worker_stop = asyncio.Event()
    _state.worker_task = loop.create_task(_drain_loop())


def stop_worker() -> None:
    """Cancel the background worker. Used by tests."""
    if _state.worker_stop is not None:
        _state.worker_stop.set()
    _state.worker_task = None
    _state.worker_stop = None
