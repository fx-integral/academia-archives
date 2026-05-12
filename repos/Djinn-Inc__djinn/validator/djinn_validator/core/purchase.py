"""Purchase flow orchestration.

Implements the purchase lifecycle from Appendix A:
1. Buyer -> Validator: POST /v1/signal/{id}/purchase
2. Validator -> Miners: Query line availability
3. Validators -> MPC: Is real index ∈ available set?
4. If available: call Escrow.purchase() on-chain
5. Payment verified: release key shares to buyer
"""

from __future__ import annotations

import re
import sqlite3
import threading
import time
from dataclasses import dataclass, field
from enum import Enum, auto
from pathlib import Path

import structlog

from djinn_validator.core.mpc import MPCResult
from djinn_validator.core.shares import ShareStore

log = structlog.get_logger()


class PurchaseStatus(Enum):
    PENDING = auto()
    CHECKING_AVAILABILITY = auto()
    MPC_IN_PROGRESS = auto()
    UNAVAILABLE = auto()
    AWAITING_PAYMENT = auto()
    PAYMENT_CONFIRMED = auto()
    SHARES_RELEASED = auto()
    FAILED = auto()
    VOIDED = auto()


@dataclass
class PurchaseRequest:
    """Tracks the state of a purchase attempt."""

    signal_id: str
    buyer_address: str
    sportsbook: str
    status: PurchaseStatus = PurchaseStatus.PENDING
    mpc_result: MPCResult | None = None
    tx_hash: str | None = None
    created_at: float = field(default_factory=time.monotonic)
    completed_at: float | None = None


class PurchaseOrchestrator:
    """Manages the purchase flow for this validator.

    Uses SQLite to persist verified payments and prevent TOCTOU replay attacks.
    In-memory dict tracks active (in-flight) purchases for concurrency control.
    """

    def __init__(self, share_store: ShareStore, db_path: str | Path | None = None) -> None:
        self._store = share_store
        self._active: dict[str, PurchaseRequest] = {}  # keyed by signal_id:buyer
        self._db_lock = threading.Lock()
        if db_path is not None:
            path = Path(db_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            self._conn = sqlite3.connect(str(path), check_same_thread=False)
        else:
            self._conn = sqlite3.connect(":memory:", check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA busy_timeout=5000")
        self._create_tables()

    def _create_tables(self) -> None:
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS verified_payments (
                signal_id      TEXT NOT NULL,
                buyer_address  TEXT NOT NULL,
                tx_hash        TEXT NOT NULL,
                status         TEXT NOT NULL,
                created_at     REAL NOT NULL,
                completed_at   REAL,
                PRIMARY KEY (signal_id, buyer_address)
            );
            CREATE INDEX IF NOT EXISTS idx_vp_tx_hash ON verified_payments(tx_hash);
        """)
        self._conn.commit()

    def is_payment_consumed(self, signal_id: str, buyer_address: str) -> bool:
        """Check if payment was already verified and share released for this signal+buyer."""
        with self._db_lock:
            row = self._conn.execute(
                "SELECT status FROM verified_payments WHERE signal_id = ? AND buyer_address = ?",
                (signal_id, buyer_address),
            ).fetchone()
            return row is not None and row[0] in ("SHARES_RELEASED", "PAYMENT_CONFIRMED")

    def record_payment(self, signal_id: str, buyer_address: str, tx_hash: str, status: str) -> bool:
        """Record a verified payment. Returns False if already recorded (replay)."""
        with self._db_lock:
            try:
                self._conn.execute(
                    "INSERT INTO verified_payments (signal_id, buyer_address, tx_hash, status, created_at) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (signal_id, buyer_address, tx_hash, status, time.time()),
                )
                self._conn.commit()
                return True
            except sqlite3.IntegrityError:
                return False

    def update_payment_status(self, signal_id: str, buyer_address: str, status: str) -> None:
        """Update the status of a recorded payment."""
        with self._db_lock:
            self._conn.execute(
                "UPDATE verified_payments SET status = ?, completed_at = ? "
                "WHERE signal_id = ? AND buyer_address = ?",
                (status, time.time(), signal_id, buyer_address),
            )
            self._conn.commit()

    def close(self) -> None:
        """Close the database connection."""
        try:
            self._conn.close()
        except Exception as e:
            log.warning("purchase_db_close_error", error=str(e))

    _SAFE_ID_RE = re.compile(r"^[a-zA-Z0-9_\-]{1,256}$")

    def _key(self, signal_id: str, buyer: str) -> str:
        return f"{signal_id}:{buyer}"

    def initiate(
        self,
        signal_id: str,
        buyer_address: str,
        sportsbook: str,
    ) -> PurchaseRequest:
        """Start a new purchase flow."""
        if not self._SAFE_ID_RE.match(signal_id):
            raise ValueError("Invalid signal_id: must match [a-zA-Z0-9_-]{1,256}")
        key = self._key(signal_id, buyer_address)

        if key in self._active:
            existing = self._active[key]
            if existing.status not in (PurchaseStatus.FAILED, PurchaseStatus.VOIDED):
                log.warning("purchase_already_active", signal_id=signal_id, buyer=buyer_address)
                return existing

        if not self._store.has(signal_id):
            req = PurchaseRequest(
                signal_id=signal_id,
                buyer_address=buyer_address,
                sportsbook=sportsbook,
                status=PurchaseStatus.FAILED,
            )
            self._active[key] = req
            log.error("no_share_for_signal", signal_id=signal_id)
            return req

        req = PurchaseRequest(
            signal_id=signal_id,
            buyer_address=buyer_address,
            sportsbook=sportsbook,
            status=PurchaseStatus.CHECKING_AVAILABILITY,
        )
        self._active[key] = req
        log.info("purchase_initiated", signal_id=signal_id, buyer=buyer_address, sportsbook=sportsbook)
        return req

    def set_mpc_result(
        self,
        signal_id: str,
        buyer_address: str,
        result: MPCResult,
    ) -> PurchaseRequest | None:
        """Record MPC result for a purchase."""
        key = self._key(signal_id, buyer_address)
        req = self._active.get(key)
        if req is None:
            return None

        req.mpc_result = result
        if result.available:
            req.status = PurchaseStatus.AWAITING_PAYMENT
            log.info("signal_available", signal_id=signal_id)
        else:
            req.status = PurchaseStatus.UNAVAILABLE
            log.info("signal_unavailable", signal_id=signal_id)

        return req

    def confirm_payment(
        self,
        signal_id: str,
        buyer_address: str,
        tx_hash: str,
    ) -> PurchaseRequest | None:
        """Record on-chain payment confirmation and release shares."""
        key = self._key(signal_id, buyer_address)
        req = self._active.get(key)
        if req is None:
            return None

        # Guard: reject if already confirmed or released
        if req.status in (PurchaseStatus.PAYMENT_CONFIRMED, PurchaseStatus.SHARES_RELEASED):
            log.warning("purchase_already_confirmed", signal_id=signal_id, buyer=buyer_address)
            return req

        req.tx_hash = tx_hash
        req.status = PurchaseStatus.PAYMENT_CONFIRMED

        # Release the key share
        share_data = self._store.release(signal_id, buyer_address)
        if share_data is not None:
            req.status = PurchaseStatus.SHARES_RELEASED
            req.completed_at = time.monotonic()
            log.info("purchase_complete", signal_id=signal_id, buyer=buyer_address)
        else:
            req.status = PurchaseStatus.FAILED
            log.error("share_release_failed", signal_id=signal_id)

        return req

    def get(self, signal_id: str, buyer_address: str) -> PurchaseRequest | None:
        """Get status of a purchase."""
        return self._active.get(self._key(signal_id, buyer_address))

    def cleanup_stale(self, stale_timeout: float = 300) -> int:
        """Fail purchases stuck in transient states for longer than stale_timeout seconds.

        Purchases in CHECKING_AVAILABILITY or MPC_IN_PROGRESS that exceed
        the timeout are moved to FAILED so they don't block the key indefinitely.
        """
        now = time.monotonic()
        transient = (PurchaseStatus.CHECKING_AVAILABILITY, PurchaseStatus.MPC_IN_PROGRESS, PurchaseStatus.PENDING)
        failed = 0
        for req in list(self._active.values()):
            if req.status in transient and now - req.created_at > stale_timeout:
                log.warning(
                    "purchase_stale_timeout",
                    signal_id=req.signal_id,
                    buyer=req.buyer_address,
                    status=req.status.name,
                    age_s=round(now - req.created_at, 1),
                )
                req.status = PurchaseStatus.FAILED
                req.completed_at = time.monotonic()
                failed += 1
        return failed

    def cleanup_completed(self, max_age_seconds: float = 86400) -> int:
        """Remove completed/failed/voided purchases older than max_age_seconds.

        Prevents unbounded growth of the in-memory _active dict.
        Returns count of removed entries.
        """
        now = time.monotonic()
        terminal = (
            PurchaseStatus.SHARES_RELEASED,
            PurchaseStatus.FAILED,
            PurchaseStatus.VOIDED,
            PurchaseStatus.UNAVAILABLE,
        )
        stale = [k for k, p in self._active.items() if p.status in terminal and now - p.created_at > max_age_seconds]
        for k in stale:
            del self._active[k]
        if stale:
            log.info("purchases_cleaned", removed=len(stale))
        return len(stale)
