"""Persistent ledger of per-line BPA/WPA vectors committed at purchase time.

## Why this exists

MPC batch settlement needs to know, at audit time, what each buyer's
per-line BPA and WPA were at the moment they purchased a signal. Those
vectors depend on the buyer's configured sportsbook set and on the
live bookmaker odds at the instant of purchase, so they cannot be
re-derived later: books may be down, markets may have moved, or the
specific books the buyer used may no longer offer the line.

This ledger captures the vectors synchronously at the purchase API
boundary, keyed by `(signal_id, buyer_address)`, so the future batch
settlement job can look up exactly what the buyer saw.

## What this is NOT

Not a commitment scheme — the on-chain `vectorHash` that prevents
tampering comes in Phase 2 via a contract upgrade. In this Phase 1
ledger, the validator is storing vectors for its own records, and
the trust model is "validator is honest about what it saw." Phase 2
adds on-chain verifiability that the vectors haven't been changed
between purchase and settlement.

## Schema

  TABLE purchase_odds(
    signal_id TEXT NOT NULL,
    buyer_address TEXT NOT NULL,
    bpa_mode INTEGER NOT NULL,        -- 0 = WPA mode, 1 = BPA mode
    bpas_json TEXT NOT NULL,          -- JSON array of ODDS_PRECISION-scaled ints
    wpas_json TEXT NOT NULL,          -- JSON array of ODDS_PRECISION-scaled ints
    recorded_at REAL NOT NULL,        -- unix timestamp of purchase
    PRIMARY KEY (signal_id, buyer_address)
  )

The primary key ensures one row per (signal, buyer) — a second
purchase of the same signal by the same buyer is a no-op on this
table, since the underlying purchase would fail anyway (see
`hasPurchased[signalId][msg.sender]` in Escrow.sol).
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from dataclasses import dataclass
from pathlib import Path

import structlog

log = structlog.get_logger()


@dataclass(frozen=True)
class PurchaseOddsRecord:
    """One buyer's committed view of a signal's per-line BPA/WPA vectors."""

    signal_id: str
    buyer_address: str
    bpa_mode: bool
    bpas: list[int]
    wpas: list[int]
    recorded_at: float


class PurchaseOddsLedger:
    """SQLite-backed store for committed per-line BPA/WPA vectors.

    Thread-safe: a single RLock guards all writes. Reads don't need the
    lock because SQLite's default isolation gives us consistent snapshots.
    """

    def __init__(self, db_path: str | Path = ":memory:") -> None:
        self._db_path = Path(db_path) if db_path != ":memory:" else None
        self._conn = sqlite3.connect(
            db_path,
            check_same_thread=False,
            isolation_level=None,  # autocommit — each execute is its own tx
        )
        self._lock = threading.RLock()
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._create_schema()

    def _create_schema(self) -> None:
        with self._lock:
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS purchase_odds (
                    signal_id TEXT NOT NULL,
                    buyer_address TEXT NOT NULL,
                    bpa_mode INTEGER NOT NULL,
                    bpas_json TEXT NOT NULL,
                    wpas_json TEXT NOT NULL,
                    recorded_at REAL NOT NULL,
                    PRIMARY KEY (signal_id, buyer_address)
                )
                """
            )

    def record(
        self,
        signal_id: str,
        buyer_address: str,
        bpas: list[int],
        wpas: list[int],
        bpa_mode: bool,
    ) -> None:
        """Record a buyer's per-line BPA/WPA at purchase time.

        Idempotent on (signal_id, buyer_address): a second call for the
        same pair is silently ignored so retries don't overwrite the
        original values. If the buyer re-queries purchase with different
        vectors (e.g. because the market moved), the first set of
        vectors is the authoritative record.
        """
        if not signal_id or not buyer_address:
            raise ValueError("signal_id and buyer_address are required")
        if len(bpas) != len(wpas):
            raise ValueError(f"bpas and wpas must have equal length; got " f"bpas={len(bpas)}, wpas={len(wpas)}")

        bpas_json = json.dumps(bpas)
        wpas_json = json.dumps(wpas)
        recorded_at = time.time()

        with self._lock:
            try:
                self._conn.execute(
                    """
                    INSERT INTO purchase_odds
                        (signal_id, buyer_address, bpa_mode,
                         bpas_json, wpas_json, recorded_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        signal_id,
                        buyer_address.lower(),
                        1 if bpa_mode else 0,
                        bpas_json,
                        wpas_json,
                        recorded_at,
                    ),
                )
                log.info(
                    "purchase_odds_recorded",
                    signal_id=signal_id,
                    buyer=buyer_address.lower()[:10],
                    n_lines=len(bpas),
                    bpa_mode=bpa_mode,
                )
            except sqlite3.IntegrityError:
                # Row already exists for (signal, buyer). Keep the earlier
                # recording as the authoritative one — retries must not
                # overwrite.
                log.debug(
                    "purchase_odds_duplicate_ignored",
                    signal_id=signal_id,
                    buyer=buyer_address.lower()[:10],
                )

    def get(
        self,
        signal_id: str,
        buyer_address: str,
    ) -> PurchaseOddsRecord | None:
        """Fetch the stored record for a given (signal, buyer), or None."""
        row = self._conn.execute(
            """
            SELECT signal_id, buyer_address, bpa_mode, bpas_json, wpas_json,
                   recorded_at
            FROM purchase_odds
            WHERE signal_id = ? AND buyer_address = ?
            """,
            (signal_id, buyer_address.lower()),
        ).fetchone()
        if row is None:
            return None
        return PurchaseOddsRecord(
            signal_id=row[0],
            buyer_address=row[1],
            bpa_mode=bool(row[2]),
            bpas=json.loads(row[3]),
            wpas=json.loads(row[4]),
            recorded_at=row[5],
        )

    def count(self) -> int:
        """Total number of recorded (signal, buyer) pairs. Used in tests
        and metrics."""
        row = self._conn.execute("SELECT COUNT(*) FROM purchase_odds").fetchone()
        return int(row[0]) if row else 0

    def get_all_for_signal(self, signal_id: str) -> list[PurchaseOddsRecord]:
        """All records for a given signal, one per buyer. Used at audit
        time to pull every buyer's committed vectors for batch
        settlement."""
        rows = self._conn.execute(
            """
            SELECT signal_id, buyer_address, bpa_mode, bpas_json, wpas_json,
                   recorded_at
            FROM purchase_odds
            WHERE signal_id = ?
            ORDER BY recorded_at ASC
            """,
            (signal_id,),
        ).fetchall()
        return [
            PurchaseOddsRecord(
                signal_id=row[0],
                buyer_address=row[1],
                bpa_mode=bool(row[2]),
                bpas=json.loads(row[3]),
                wpas=json.loads(row[4]),
                recorded_at=row[5],
            )
            for row in rows
        ]

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
