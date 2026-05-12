"""v1747 Phase 3: peer-attestation SQLite store.

Each validator gossips its locally-signed ``LineResolution.sig`` to peers.
Receivers verify the EIP-712 signature, confirm the signer is in the
``OutcomeVoting.isValidator`` set, and persist the (line_hash, peer_eoa,
outcome, sig) tuple here. Once a validator has 4 distinct-EOA matching
sigs for a single line + outcome AND its own ESPN view agrees, it submits
to ``LineOutcomeRegistry.submitLineOutcome``.

Bounded at 5 sigs per line (= the OV signer count). A 6th sig for the
same line is rejected as duplicate or adversarial spam.

Persistence model: SQLite. Survives validator restart so a peer's
attestation gossip received hours before the threshold quorum lands isn't
lost. Cleared after on-chain finalization (``evict_finalized``).
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path

import structlog

log = structlog.get_logger()


# Maximum sigs stored per line. Equals the OV signer set size; any 6th sig
# is duplicate or adversarial. Hard cap protects the SQLite from gossip
# flood attacks.
MAX_SIGS_PER_LINE = 5


@dataclass(frozen=True)
class PeerSig:
    """A single peer-validator's attestation for a canonical line."""

    line_hash: bytes        # 32-byte canonical lineHash
    peer_eoa: str           # 0x-prefixed lowercase, 42 chars
    outcome: int            # 1=Favorable, 2=Unfavorable, 3=Void; never 0=Pending
    signature: bytes        # 65-byte EIP-712 ECDSA sig
    received_at: float      # epoch seconds


class PeerAttestationStore:
    """SQLite-backed store for peer attestation signatures.

    Threading: SQLite connection uses ``check_same_thread=False`` for the
    same reason as ``OutcomeAttestor`` — the validator's epoch loop and
    HTTP API both write here. WAL mode + busy_timeout keep contention
    bounded.
    """

    def __init__(self, db_path: str | None = None) -> None:
        self._db: sqlite3.Connection | None = None
        # In-memory mirror for read-heavy threshold checks. Refreshed on
        # write; reset on restart from the SQLite snapshot.
        self._cache: dict[bytes, list[PeerSig]] = {}

        if db_path is None:
            return

        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(db_path, check_same_thread=False)
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.execute("PRAGMA busy_timeout=5000")
        self._db.execute(
            """
            CREATE TABLE IF NOT EXISTS peer_attestations (
                line_hash   BLOB    NOT NULL,
                peer_eoa    TEXT    NOT NULL,
                outcome     INTEGER NOT NULL,
                signature   BLOB    NOT NULL,
                received_at REAL    NOT NULL,
                PRIMARY KEY (line_hash, peer_eoa)
            )
            """
        )
        self._db.execute(
            "CREATE INDEX IF NOT EXISTS idx_peer_att_line ON peer_attestations (line_hash)"
        )
        self._db.commit()
        self._load_cache()

    def _load_cache(self) -> None:
        if not self._db:
            return
        cur = self._db.execute(
            "SELECT line_hash, peer_eoa, outcome, signature, received_at FROM peer_attestations"
        )
        for line_hash, peer_eoa, outcome, signature, received_at in cur:
            sig = PeerSig(
                line_hash=bytes(line_hash),
                peer_eoa=peer_eoa,
                outcome=int(outcome),
                signature=bytes(signature),
                received_at=float(received_at),
            )
            self._cache.setdefault(sig.line_hash, []).append(sig)

    def add_peer_sig(
        self,
        line_hash: bytes,
        peer_eoa: str,
        outcome: int,
        signature: bytes,
        *,
        received_at: float | None = None,
    ) -> str:
        """Persist a peer sig. Returns a status string.

        Status values:
        - "added": new sig stored.
        - "duplicate": (line_hash, peer_eoa) already present (idempotent).
        - "capacity": MAX_SIGS_PER_LINE already reached for this line.
        - "invalid_outcome": ``outcome`` is not 1/2/3.
        - "invalid_args": malformed line_hash or peer_eoa.
        """
        if outcome not in (1, 2, 3):
            return "invalid_outcome"
        if len(line_hash) != 32:
            return "invalid_args"
        if not peer_eoa.startswith("0x") or len(peer_eoa) != 42:
            return "invalid_args"
        peer_eoa = peer_eoa.lower()

        import time

        now = time.time() if received_at is None else received_at
        existing = self._cache.get(line_hash, [])
        for s in existing:
            if s.peer_eoa == peer_eoa:
                return "duplicate"
        if len(existing) >= MAX_SIGS_PER_LINE:
            return "capacity"

        sig = PeerSig(
            line_hash=line_hash,
            peer_eoa=peer_eoa,
            outcome=outcome,
            signature=signature,
            received_at=now,
        )
        self._cache.setdefault(line_hash, []).append(sig)
        if self._db is not None:
            try:
                self._db.execute(
                    "INSERT OR IGNORE INTO peer_attestations "
                    "(line_hash, peer_eoa, outcome, signature, received_at) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (line_hash, peer_eoa, outcome, signature, now),
                )
                self._db.commit()
            except sqlite3.Error as e:
                log.warning("peer_att_persist_failed", err=str(e)[:120])
        return "added"

    def get_sigs_for_line(self, line_hash: bytes) -> list[PeerSig]:
        """All peer sigs cached for ``line_hash`` (any outcome)."""
        return list(self._cache.get(line_hash, []))

    def count_for_line(self, line_hash: bytes) -> int:
        return len(self._cache.get(line_hash, []))

    def count_matching(self, line_hash: bytes, outcome: int) -> int:
        """How many cached sigs vote for this exact outcome on this line."""
        return sum(1 for s in self._cache.get(line_hash, []) if s.outcome == outcome)

    def threshold_bundle(
        self, line_hash: bytes, outcome: int, threshold: int = 4
    ) -> list[PeerSig] | None:
        """Return up to ``threshold`` distinct-EOA sigs matching ``outcome``.

        Returns None if fewer than ``threshold`` matching sigs are cached.
        Sigs are returned in deterministic peer_eoa order so submitters
        produce identical bundles across the fleet (helps multi-submit
        idempotency).
        """
        matches = [s for s in self._cache.get(line_hash, []) if s.outcome == outcome]
        if len(matches) < threshold:
            return None
        matches.sort(key=lambda s: s.peer_eoa)
        return matches[:threshold]

    def evict_finalized(self, line_hash: bytes) -> int:
        """Drop all cached sigs for a finalized line. Returns count removed.

        Called after the contract emits ``LineFinalized`` (via the validator's
        own submit success or a peer's submit observed via subgraph). Storage
        is bounded by the unfinalized-line working set, not lifetime traffic.
        """
        removed = len(self._cache.pop(line_hash, []))
        if self._db is not None and removed:
            try:
                self._db.execute(
                    "DELETE FROM peer_attestations WHERE line_hash = ?", (line_hash,)
                )
                self._db.commit()
            except sqlite3.Error as e:
                log.warning("peer_att_evict_failed", err=str(e)[:120])
        return removed

    def close(self) -> None:
        if self._db is not None:
            try:
                self._db.close()
            except sqlite3.Error:
                pass
            self._db = None
