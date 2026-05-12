"""Audit set tracking for batch settlement.

Supports two contract models:
- v1 (cycle-based): A fixed cycle of 10 signals between one genius-idiot
  pair.  Settlement triggers when the cycle is full and all resolved.
- v2 (queue-based): An append-only purchase queue.  Settlement triggers
  when 10+ resolved, unaudited purchases exist for a pair.

The internal data model uses the queue model (it is a superset of cycles).
The difference is only in readiness logic and on-chain call signatures.

Persistence (Phase A1.9, 2026-05-02): when constructed with db_path, every
add_signal / record_outcomes / mark_settled mutation is durably persisted
to a SQLite file. On startup _load_persisted reconstructs the in-memory
state. This eliminates the 30-min post-restart degraded window where
audit_set_store was empty (in-memory only) and gossip arriving for known-
resolved signals couldn't be bridged via record_outcomes because the
signal index hadn't bootstrapped from chain yet. Outcomes are now
durable across restarts; bootstrap remains as the chain → audit_set
catch-up path for signals this validator never saw locally.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from dataclasses import dataclass, field
from pathlib import Path

import structlog

from djinn_validator.core.outcomes import Outcome

log = structlog.get_logger()

SIGNALS_PER_CYCLE = 10  # v1 cycle size / v2 minimum batch size
# v2 minimum batch size: how many resolved-unaudited purchases per (genius, idiot)
# pair before settlement can fire. Default on Base mainnet is 10 (amortizes gas);
# on Base testnet it drops to 2 so settlements fire at realistic per-pair volumes
# instead of stalling until a single idiot makes 10+ back-to-back purchases.
# Override via AUDIT_MIN_BATCH_SIZE env.
#
# v1455: detect testnet from BASE_CHAIN_ID (EVM chain), not BT_NETWORK (Bittensor
# network). Rationale: every validator runs BT_NETWORK=finney (Bittensor mainnet)
# while EVM contracts are on Base Sepolia (84532), so the old BT_NETWORK=="test"
# check was always false and the default silently fell to 10 — blocking every
# testnet cohort from ever promoting to ready_for_settlement. Detected via v1454
# /health probe on 2026-04-21: UIDs 189 and 213 reported audit_min_batch_size=10
# despite operating on Sepolia. See MAINNET_BLOCKERS P0-01.
import os  # noqa: E402

# v1559: load .env before resolving module-level env reads. Without this, the
# module-level MIN_BATCH_SIZE below resolves at import time using only the
# process-level shell environment, which does NOT include .env values. On UID 0
# this silently pinned audit_min_batch_size=2 even though .env had
# AUDIT_MIN_BATCH_SIZE=1, blocking single-purchase audits from ever promoting
# to ready_for_settlement and thus blocking the first submit-from-shadow vote
# needed to close P0-01. Same defensive pattern as feature_flags.py.
try:
    from dotenv import load_dotenv as _load_dotenv  # noqa: E402

    _load_dotenv()
except ImportError:
    pass

try:
    _chain_id_raw = int(os.environ.get("BASE_CHAIN_ID", "84532"))
except ValueError:
    _chain_id_raw = 84532
_DEFAULT_MIN_BATCH_SIZE = "10" if _chain_id_raw == 8453 else "2"
MIN_BATCH_SIZE = max(1, int(os.environ.get("AUDIT_MIN_BATCH_SIZE", _DEFAULT_MIN_BATCH_SIZE)))


def _normalize_signal_id(signal_id: str) -> str:
    """Canonicalize a signal_id string to decimal uint256.

    Signal IDs reach this module via three paths:
    - ``/v1/signal`` (client-sent): usually decimal, sometimes 0x-hex or bare hex.
    - ``_bootstrap_pair_v{1,2}``: ``str(purchase["signalId"])`` (always decimal).
    - ``_register_signals_from_chain``: the ShareStore key (client-sent encoding).

    Without normalization, the same on-chain uint256 can be stored under two
    different strings ("0xabc" vs "2748") and ``record_outcomes`` lookups miss.
    This was the root cause of ``outcomes_resolved_total`` incrementing while
    ``audit.resolved_signals`` stayed at 0 (diagnosed via v1419 WARNING logs,
    fixed in v1420).
    """
    if not signal_id:
        return signal_id
    s = signal_id.strip()
    try:
        if s.startswith(("0x", "0X")):
            return str(int(s, 16))
        return str(int(s, 10))
    except ValueError:
        try:
            return str(int(s, 16))
        except ValueError:
            return s


@dataclass
class AuditSignal:
    """One signal within an audit set."""

    signal_id: str
    purchase_id: int = 0  # On-chain Escrow purchase ID (needed for v2 vote)
    outcomes: list[Outcome] | None = None  # 10 line outcomes once game resolves
    notional: int = 0  # Purchase notional (wei)
    odds: int = 1_000_000  # 6-decimal odds (1.0 = 1_000_000)
    sla_bps: int = 10_000  # SLA multiplier in basis points


@dataclass
class AuditSet:
    """A settlement batch: signals between one genius-idiot pair.

    In v1, this represents a fixed 10-signal cycle.
    In v2, this is a batch of 10+ resolved, unaudited purchases.
    """

    genius_address: str
    idiot_address: str
    cycle: int = 0  # v1: cycle number; v2: batch number (monotonically increasing)
    signals: dict[str, AuditSignal] = field(default_factory=dict)
    settled: bool = False
    version: int = 1  # 1 = cycle-based, 2 = queue-based

    @property
    def is_full(self) -> bool:
        """v1: cycle has 10 signals. v2: always False (queue grows unbounded)."""
        if self.version == 2:
            return False  # v2 queues are never "full"
        return len(self.signals) >= SIGNALS_PER_CYCLE

    @property
    def resolved_signals(self) -> list[AuditSignal]:
        """All signals whose outcomes have been resolved."""
        return [s for s in self.signals.values() if s.outcomes is not None]

    @property
    def all_resolved(self) -> bool:
        return bool(self.signals) and all(s.outcomes is not None for s in self.signals.values())

    @property
    def ready_for_settlement(self) -> bool:
        """Check if this set is ready for batch MPC settlement.

        v1: exactly 10 signals, all resolved, not yet settled.
        v2: 10+ resolved signals, not yet settled.
        """
        if self.settled:
            return False
        if self.version == 2:
            return len(self.resolved_signals) >= MIN_BATCH_SIZE
        return self.is_full and self.all_resolved

    @property
    def purchase_ids(self) -> list[int]:
        """All on-chain purchase IDs in this set (for v2 vote submission)."""
        return [s.purchase_id for s in self.signals.values() if s.purchase_id > 0]

    @property
    def resolved_purchase_ids(self) -> list[int]:
        """Purchase IDs for resolved signals only (for v2 batch voting)."""
        return [s.purchase_id for s in self.signals.values() if s.outcomes is not None and s.purchase_id > 0]


class AuditSetStore:
    """In-memory store for audit sets, keyed by (genius, idiot, cycle).

    Thread-safe via a lock since the epoch loop and API may access
    concurrently. Works with both v1 and v2 contract models.
    """

    def __init__(
        self,
        contract_version: int = 1,
        db_path: str | None = None,
    ) -> None:
        self._sets: dict[tuple[str, str, int], AuditSet] = {}
        self._signal_index: dict[str, tuple[str, str, int]] = {}
        # v1716: per-set abstain counter. When build_purchase_inputs_from_audit_set
        # returns None for a set N times in a row, it gets excluded from
        # get_ready_sets() so the head-of-queue can advance to pairs that
        # actually have recoverable data. Per-validator local state — does
        # not require consensus. Other validators with the missing data
        # continue voting on the same pair; 4-of-5 quorum is unaffected.
        # v1718: default threshold lowered 5 → 2. v1717's reset_abstain on
        # push-gossip arrival auto-re-admits a false-evicted pair when the
        # missing BPA/WPA or outcomes finally land. The lower default makes
        # legacy-backlog eviction sweep ~3x faster (critical for the
        # pre-gossip-era queue clearance blocking P0-01 convergence).
        self._abstain_counts: dict[tuple[str, str, int], int] = {}
        self._abstain_threshold = int(os.environ.get("DJINN_AUDIT_ABSTAIN_THRESHOLD", "2"))
        # v1734: lifetime abstain counter that NEVER resets on push gossip.
        # The recoverable counter above resets whenever any gossip arrives for
        # any signal in (g, i, c), which lets legacy pre-SealedBox-fanout pairs
        # ping-pong back into the queue forever — a peer 404 on share recovery
        # is permanent (no other validator has the forwarding blob either) so
        # the data will never arrive even though gossip keeps re-admitting the
        # pair. Once the lifetime count exceeds this threshold the pair is
        # filtered from get_ready_sets indefinitely, draining the legacy
        # backlog so new commits get a turn at head-of-queue.
        #
        # v1746: threshold raised from 10 to 600. Rationale: v1744 ships the
        # durable outbound gossip queue with a 5-min initial retry interval
        # (so the first outbox retry happens ~11 min after a peer-offline
        # gossip; second retry at ~16 min). The legacy threshold of 10 with a
        # 12-second epoch evicted in 2 min — well before v1744's first
        # retry could deliver. 600 attempts × 12s = ~2 hours, which gives
        # v1744 ample room (initial retry + 2-3 backed-off retries) before
        # eviction. Legacy pairs whose data is genuinely lost still evict,
        # just on a 2-hour cadence instead of 2 minutes — no observable
        # downside since those audits never settle anyway.
        self._permanent_abstain_counts: dict[tuple[str, str, int], int] = {}
        self._permanent_abstain_threshold = int(os.environ.get("DJINN_AUDIT_PERMANENT_ABSTAIN_THRESHOLD", "600"))
        self._lock = threading.Lock()
        self._contract_version = contract_version
        self._db: sqlite3.Connection | None = None
        if db_path:
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
            self._db = sqlite3.connect(db_path, check_same_thread=False)
            self._db.execute("PRAGMA journal_mode=WAL")
            self._db.execute("PRAGMA busy_timeout=5000")
            self._db.execute("""
                CREATE TABLE IF NOT EXISTS audit_sets (
                    genius_address TEXT NOT NULL,
                    idiot_address TEXT NOT NULL,
                    cycle INTEGER NOT NULL,
                    settled INTEGER NOT NULL DEFAULT 0,
                    version INTEGER NOT NULL DEFAULT 1,
                    PRIMARY KEY (genius_address, idiot_address, cycle)
                )
            """)
            cols = [r[1] for r in self._db.execute("PRAGMA table_info(audit_sets)")]
            if "permanent_abstain_count" not in cols:
                self._db.execute("ALTER TABLE audit_sets ADD COLUMN permanent_abstain_count INTEGER NOT NULL DEFAULT 0")
            self._db.execute("""
                CREATE TABLE IF NOT EXISTS audit_signals (
                    signal_id TEXT PRIMARY KEY,
                    genius_address TEXT NOT NULL,
                    idiot_address TEXT NOT NULL,
                    cycle INTEGER NOT NULL,
                    purchase_id INTEGER NOT NULL DEFAULT 0,
                    notional INTEGER NOT NULL DEFAULT 0,
                    odds INTEGER NOT NULL DEFAULT 1000000,
                    sla_bps INTEGER NOT NULL DEFAULT 10000,
                    outcomes_json TEXT
                )
            """)
            self._db.execute(
                "CREATE INDEX IF NOT EXISTS idx_audit_signals_set "
                "ON audit_signals(genius_address, idiot_address, cycle)"
            )
            self._db.commit()
            self._load_persisted()

    def _load_persisted(self) -> None:
        """Reconstruct in-memory state from SQLite at startup."""
        if not self._db:
            return
        try:
            sets_loaded = 0
            signals_loaded = 0
            outcomes_loaded = 0
            cur = self._db.execute(
                "SELECT genius_address, idiot_address, cycle, settled, version, "
                "permanent_abstain_count FROM audit_sets"
            )
            for row in cur:
                genius, idiot, cycle, settled, version, perm_abstain = row
                key = (genius.lower(), idiot.lower(), int(cycle))
                self._sets[key] = AuditSet(
                    genius_address=genius,
                    idiot_address=idiot,
                    cycle=int(cycle),
                    settled=bool(settled),
                    version=int(version),
                )
                if perm_abstain:
                    self._permanent_abstain_counts[key] = int(perm_abstain)
                sets_loaded += 1
            cur = self._db.execute(
                "SELECT signal_id, genius_address, idiot_address, cycle, "
                "purchase_id, notional, odds, sla_bps, outcomes_json "
                "FROM audit_signals"
            )
            for row in cur:
                (
                    signal_id,
                    genius,
                    idiot,
                    cycle,
                    purchase_id,
                    notional,
                    odds,
                    sla_bps,
                    outcomes_json,
                ) = row
                key = (genius.lower(), idiot.lower(), int(cycle))
                audit_set = self._sets.get(key)
                if audit_set is None:
                    # Orphaned signal — set row missing. Skip rather than
                    # silently fabricate a set; will be re-created on next
                    # add_signal call from chain bootstrap.
                    continue
                outcomes = None
                if outcomes_json:
                    try:
                        outcomes = [Outcome(int(x)) for x in json.loads(outcomes_json)]
                        outcomes_loaded += 1
                    except Exception:
                        outcomes = None
                audit_set.signals[signal_id] = AuditSignal(
                    signal_id=signal_id,
                    purchase_id=int(purchase_id),
                    outcomes=outcomes,
                    notional=int(notional),
                    odds=int(odds),
                    sla_bps=int(sla_bps),
                )
                self._signal_index[signal_id] = key
                signals_loaded += 1
            log.info(
                "audit_set_store_loaded_persisted",
                sets=sets_loaded,
                signals=signals_loaded,
                outcomes=outcomes_loaded,
            )
        except Exception as e:
            log.error("audit_set_store_load_failed", error=str(e)[:120])

    def _persist_set(self, audit_set: AuditSet) -> None:
        """Write or update a set row. Idempotent."""
        if not self._db:
            return
        try:
            key = (
                audit_set.genius_address.lower(),
                audit_set.idiot_address.lower(),
                audit_set.cycle,
            )
            perm = self._permanent_abstain_counts.get(key, 0)
            self._db.execute(
                "INSERT OR REPLACE INTO audit_sets "
                "(genius_address, idiot_address, cycle, settled, version, "
                "permanent_abstain_count) VALUES (?, ?, ?, ?, ?, ?)",
                (
                    audit_set.genius_address.lower(),
                    audit_set.idiot_address.lower(),
                    audit_set.cycle,
                    1 if audit_set.settled else 0,
                    audit_set.version,
                    perm,
                ),
            )
            self._db.commit()
        except Exception as e:
            log.debug("audit_set_persist_failed", err=str(e)[:80])

    def _persist_signal(
        self,
        signal: AuditSignal,
        genius: str,
        idiot: str,
        cycle: int,
    ) -> None:
        """Write or update a signal row. Idempotent."""
        if not self._db:
            return
        try:
            outcomes_json = json.dumps([int(o) for o in signal.outcomes]) if signal.outcomes is not None else None
            self._db.execute(
                "INSERT OR REPLACE INTO audit_signals "
                "(signal_id, genius_address, idiot_address, cycle, "
                "purchase_id, notional, odds, sla_bps, outcomes_json) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    signal.signal_id,
                    genius.lower(),
                    idiot.lower(),
                    cycle,
                    signal.purchase_id,
                    signal.notional,
                    signal.odds,
                    signal.sla_bps,
                    outcomes_json,
                ),
            )
            self._db.commit()
        except Exception as e:
            log.debug("audit_signal_persist_failed", err=str(e)[:80])

    @property
    def contract_version(self) -> int:
        return self._contract_version

    @contract_version.setter
    def contract_version(self, value: int) -> None:
        if value != self._contract_version:
            log.info("audit_set_store_version_changed", old=self._contract_version, new=value)
            # Migrate every existing set to the new version. Without this,
            # sets added before bootstrap detected v2 stay stamped as v1
            # forever and their ready_for_settlement uses v1 rules — they
            # never trigger v2 queue-based settlement. Codex-audit HIGH-1
            # (2026-04-14).
            with self._lock:
                migrated = 0
                for s in self._sets.values():
                    if s.version != value:
                        s.version = value
                        migrated += 1
                if migrated:
                    log.info("audit_set_store_version_migrated", count=migrated, to=value)
            self._contract_version = value

    def add_signal(
        self,
        genius: str,
        idiot: str,
        cycle: int,
        signal_id: str,
        notional: int = 0,
        odds: int = 1_000_000,
        sla_bps: int = 10_000,
        purchase_id: int = 0,
    ) -> AuditSet:
        """Add a signal to the audit set for (genius, idiot, cycle).

        In v2, cycle is the batch number (or 0 for the active queue).
        """
        signal_id = _normalize_signal_id(signal_id)
        key = (genius.lower(), idiot.lower(), cycle)
        with self._lock:
            # Global dedup by signal_id — a signal can only belong to one
            # (genius, idiot, cycle) bucket at a time. Codex-audit HIGH-2
            # (2026-04-14): without this, a repeated /register with the
            # same signal_id but a different cycle would appear in both
            # sets and the summary would double-count. _signal_index is
            # the source of truth for "where does this signal live".
            existing_key = self._signal_index.get(signal_id)
            if existing_key is not None and existing_key != key:
                log.warning(
                    "audit_set_rejected_signal_in_other_set",
                    signal_id=signal_id,
                    existing=existing_key,
                    attempted=key,
                )
                return self._sets[existing_key]

            audit_set = self._sets.get(key)
            if audit_set is None:
                audit_set = AuditSet(
                    genius_address=genius,
                    idiot_address=idiot,
                    cycle=cycle,
                    version=self._contract_version,
                )
                self._sets[key] = audit_set

            if signal_id in audit_set.signals:
                # v1732: backfill purchase_id when a later add (typically
                # audit_bootstrap with chain-derived purchase_id) supersedes
                # an earlier add (typically v1720's purchase-handler path,
                # which doesn't yet know the on-chain purchase_id and uses
                # the default 0). Without this backfill, the signal stays
                # at purchase_id=0 forever; build_purchase_inputs then
                # builds a batch with all-zero purchase_ids and
                # OutcomeVoting.submitVote reverts on the
                # PurchaseIdsNotSorted check (0 <= 0).
                existing_signal = audit_set.signals[signal_id]
                if purchase_id and not existing_signal.purchase_id:
                    existing_signal.purchase_id = int(purchase_id)
                    if self._db is not None:
                        try:
                            self._db.execute(
                                "UPDATE audit_signals SET purchase_id = ? WHERE signal_id = ?",
                                (int(purchase_id), signal_id),
                            )
                            self._db.commit()
                        except Exception as e:
                            log.debug(
                                "audit_set_backfill_purchase_id_persist_failed",
                                signal_id=signal_id,
                                err=str(e)[:120],
                            )
                    log.info(
                        "audit_set_backfill_purchase_id",
                        signal_id=signal_id[:20],
                        purchase_id=int(purchase_id),
                    )
                else:
                    log.debug("signal_already_in_audit_set", signal_id=signal_id)
                return audit_set

            if audit_set.is_full:
                log.warning(
                    "audit_set_full",
                    genius=genius,
                    idiot=idiot,
                    cycle=cycle,
                    signal_id=signal_id,
                )
                return audit_set

            new_signal = AuditSignal(
                signal_id=signal_id,
                purchase_id=purchase_id,
                notional=notional,
                odds=odds,
                sla_bps=sla_bps,
            )
            audit_set.signals[signal_id] = new_signal
            self._signal_index[signal_id] = key
            # Persist (Phase A1.9). Atomic per-signal writes; the set
            # row was already persisted above on first creation.
            self._persist_set(audit_set)
            self._persist_signal(new_signal, genius, idiot, cycle)
            log.debug(
                "signal_added_to_audit_set",
                signal_id=signal_id,
                genius=genius,
                idiot=idiot,
                cycle=cycle,
                count=len(audit_set.signals),
                purchase_id=purchase_id,
                version=self._contract_version,
            )
            return audit_set

    def get_pair_for_signal(self, signal_id: str) -> tuple[str, str, int] | None:
        """Return (genius, idiot, cycle) for a registered signal, or None.

        Used by outcome gossip senders so the gossip payload can carry
        the pair info — enables peer receivers to add_signal+record_outcomes
        in one shot during the post-restart window when the receiver's
        audit_set_store hasn't bootstrapped from chain yet.
        """
        signal_id = _normalize_signal_id(signal_id)
        with self._lock:
            return self._signal_index.get(signal_id)

    def get_purchase_id_for_signal(self, signal_id: str) -> int | None:
        """Return purchase_id for a registered signal, or None."""
        signal_id = _normalize_signal_id(signal_id)
        with self._lock:
            key = self._signal_index.get(signal_id)
            if key is None:
                return None
            audit_set = self._sets.get(key)
            if audit_set is None:
                return None
            sig = audit_set.signals.get(signal_id)
            return sig.purchase_id if sig else None

    def record_outcomes(self, signal_id: str, outcomes: list[Outcome]) -> bool:
        """Record the 10 line outcomes for a signal."""
        signal_id = _normalize_signal_id(signal_id)
        with self._lock:
            key = self._signal_index.get(signal_id)
            if key is None:
                # v1419 diagnostics: resolved_signals=0 on UID 0 despite
                # health.outcomes_resolved_total growing. Silent failures
                # here were the untraceable root cause. Sample the first
                # few missing lookups with known-indexed prefixes so we
                # can see whether /register and bootstrap are using
                # different signal_id encodings.
                sample_keys = list(self._signal_index.keys())[:3]
                log.warning(
                    "audit_record_outcomes_unknown_signal",
                    signal_id_preview=signal_id[:20],
                    signal_id_len=len(signal_id),
                    indexed_count=len(self._signal_index),
                    indexed_sample=[k[:20] for k in sample_keys],
                )
                return False
            audit_set = self._sets.get(key)
            if audit_set is None:
                return False
            signal = audit_set.signals.get(signal_id)
            if signal is None:
                return False
            signal.outcomes = outcomes
            self._persist_signal(
                signal,
                audit_set.genius_address,
                audit_set.idiot_address,
                audit_set.cycle,
            )
            log.info(
                "audit_record_outcomes_ok",
                signal_id_preview=signal_id[:20],
                genius=audit_set.genius_address[:10],
                idiot=audit_set.idiot_address[:10],
            )
            return True

    def get_ready_sets(self) -> list[AuditSet]:
        """Return all audit sets ready for batch settlement, in a
        DETERMINISTIC order shared across the fleet.

        v1714: prior implementation returned dict-insertion order, which
        diverged across validators because each validator inserted pairs
        in a different order (subgraph response order, audit-gossip
        arrival order, RPC scan timing). Result was 7 votes spread across
        7 different pairs with zero convergence — no two validators
        attempted the same pair first under fleet load.

        Sorting by (genius, idiot, cycle) string concatenation gives
        every validator the same iteration order. When 4+ validators
        each pick their first ready pair to MPC-vote on, they
        statistically attempt the SAME pair, raising the probability
        of 4-of-5 quorum convergence on any one batchKey.

        v1716: pairs that this validator has abstained on
        ``DJINN_AUDIT_ABSTAIN_THRESHOLD`` times in a row are filtered
        out so head-of-queue can advance past locally-unsettleable
        pairs (missing share, missing BPA/WPA from pre-gossip era).
        Per-validator local state; other validators with the recoverable
        data continue voting on the same pair, so 4-of-5 quorum is
        unaffected.
        """
        with self._lock:
            ready = []
            for s in self._sets.values():
                if not s.ready_for_settlement:
                    continue
                key = (s.genius_address.lower(), s.idiot_address.lower(), s.cycle)
                if self._abstain_counts.get(key, 0) >= self._abstain_threshold:
                    continue
                if self._permanent_abstain_counts.get(key, 0) >= self._permanent_abstain_threshold:
                    continue
                ready.append(s)
        ready.sort(key=lambda s: (s.genius_address.lower(), s.idiot_address.lower(), s.cycle))
        return ready

    def mark_abstain(self, genius: str, idiot: str, cycle: int) -> int:
        """Increment both the recoverable and permanent abstain counters.

        Called when build_purchase_inputs_from_audit_set returns None for
        this set. The recoverable counter resets on push-gossip arrival
        (v1717); the permanent counter does not, so legacy pairs whose
        data will never arrive eventually evict for good. Returns the
        recoverable count so the caller can log threshold crossings.
        """
        key = (genius.lower(), idiot.lower(), cycle)
        with self._lock:
            count = self._abstain_counts.get(key, 0) + 1
            self._abstain_counts[key] = count
            perm = self._permanent_abstain_counts.get(key, 0) + 1
            self._permanent_abstain_counts[key] = perm
            audit_set = self._sets.get(key)
        if audit_set is not None:
            self._persist_set(audit_set)
        return count

    def reset_abstain(self, genius: str, idiot: str, cycle: int) -> None:
        """Reset the abstain counter (e.g., when share/BPA finally arrives)."""
        key = (genius.lower(), idiot.lower(), cycle)
        with self._lock:
            self._abstain_counts.pop(key, None)

    def mark_settled(self, genius: str, idiot: str, cycle: int) -> None:
        """Mark an audit set as settled to prevent re-processing."""
        key = (genius.lower(), idiot.lower(), cycle)
        with self._lock:
            audit_set = self._sets.get(key)
            if audit_set is not None:
                audit_set.settled = True
                self._persist_set(audit_set)

    def get_set(self, genius: str, idiot: str, cycle: int) -> AuditSet | None:
        """Look up an audit set by key."""
        key = (genius.lower(), idiot.lower(), cycle)
        with self._lock:
            return self._sets.get(key)

    def get_set_for_signal(self, signal_id: str) -> AuditSet | None:
        """Look up the audit set containing a signal."""
        signal_id = _normalize_signal_id(signal_id)
        with self._lock:
            key = self._signal_index.get(signal_id)
            if key is None:
                return None
            return self._sets.get(key)

    def protected_signal_ids(self) -> set[str]:
        """Signal IDs whose outcome data must NOT be cleaned by the validator's
        outcome attestor.

        A signal is protected iff it belongs to an audit_set that has not yet
        been mark_settled-ed. The outcome attestor's cleanup_resolved respects
        this set so that resolved-but-still-pending-settlement signals retain
        their outcomes for as long as MPC may still need them, regardless of
        wall-clock age. Without this gate, any settlement that lags more than
        the cleanup-age cutoff loses its outcome data and silently abstains
        forever — a P0 mainnet hazard given Audit V2 supports a 45-day SLA
        timeout (`autoEarlyExitDelay = 3,888,000s`). v1620 closes that gap by
        making cleanup correctness-driven instead of age-driven.

        Returns normalized (string) signal IDs so the set is directly
        intersectable with OutcomeAttestor._pending_signals keys.
        """
        with self._lock:
            protected: set[str] = set()
            for audit_set in self._sets.values():
                if audit_set.settled:
                    continue
                protected.update(audit_set.signals.keys())
            return protected

    @property
    def count(self) -> int:
        """Total number of tracked audit sets."""
        with self._lock:
            return len(self._sets)

    def summary(self) -> dict[str, int]:
        """Bucketed counts for /v1/audit/summary.

        Buckets:
          - total: all tracked sets
          - waiting_for_outcomes: at least one signal not yet resolved
          - ready_for_settlement: fully resolved, not yet settled
          - permanently_abstained: ready_for_settlement sets evicted by
            the v1716 permanent-abstain counter (data unrecoverable);
            counted inside ready_for_settlement, surfaced separately so
            operators can see how many sets are actually eligible for
            the settle path (= ready_for_settlement - permanently_abstained)
          - settled: marked settled (post-onchain)
          - total_signals: signals across all sets
          - resolved_signals: signals with outcomes populated
        """
        with self._lock:
            total = len(self._sets)
            waiting = 0
            ready = 0
            permanently_abstained = 0
            settled = 0
            total_signals = 0
            resolved_signals = 0
            for s in self._sets.values():
                total_signals += len(s.signals)
                resolved_signals += sum(1 for sig in s.signals.values() if sig.outcomes is not None)
                if s.settled:
                    settled += 1
                elif s.ready_for_settlement:
                    ready += 1
                    key = (s.genius_address.lower(), s.idiot_address.lower(), s.cycle)
                    if self._permanent_abstain_counts.get(key, 0) >= self._permanent_abstain_threshold:
                        permanently_abstained += 1
                else:
                    waiting += 1
            return {
                "total": total,
                "waiting_for_outcomes": waiting,
                "ready_for_settlement": ready,
                "permanently_abstained": permanently_abstained,
                "settled": settled,
                "total_signals": total_signals,
                "resolved_signals": resolved_signals,
            }
