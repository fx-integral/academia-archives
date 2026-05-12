"""CUSUM-based consensus circuit breaker for miner honesty tracking.

Detects sustained deviation from consensus rather than reacting to single-
query disagreement, then escalates to a TLSNotary appeal flow when a miner
crosses the flag threshold. The full design (including the appeal flow,
slash economics, and rollout plan) is in
~/.claude/projects/-home-user-djinn/memory/project_consensus_circuit_breaker.md.

This module implements the tracker primitive only. The appeal endpoint,
slash mechanics, and integration into the validator scoring loop land in
follow-up commits behind the same feature flag (DJINN_FF_CIRCUIT_BREAKER).
The tracker is safe to instantiate and call without those — it observes
and reports, never slashes by itself.

Why CUSUM:

A simple "did this query disagree?" detector burns TLSNotary cost on
single-query noise (stale cache, upstream hiccup, line legitimately
moved). CUSUM (cumulative sum control chart) tracks accumulated deviation
above a tolerance noise floor, so honest miners with normal jitter never
cross the flag line, while a miner lying systematically — even at small
magnitudes — eventually accumulates enough deviation to trip the flag.
Detection time scales roughly inversely with bias size: a 5% liar gets
caught in O(1) time, a 0.5% liar in O(100). The economics balance
themselves: bigger lies get caught faster, smaller lies generate
proportionally smaller damage before being caught.

Hotkey, not UID:

Score is keyed by the miner's Bittensor hotkey, not its UID slot. UID
slots get recycled when miners deregister; the hotkey is the persistent
cryptographic identity. This is the same convention as MinerMetrics.
Hotkey-keyed scoring means UID re-registration starts the new owner at
zero, never inheriting suspicion (or trust) from the previous tenant.
"""

from __future__ import annotations

import json
import math
import sqlite3
import threading
import time as _time
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path

import structlog

log = structlog.get_logger()


@dataclass
class CusumState:
    """Per-miner cumulative deviation state.

    score: the running CUSUM value. Increments by max(0, |delta| - tolerance)
        on each observation. Decays by `decay_per_observation` to prevent
        extremely old deviations from sticking around forever.
    sample_count: total observations recorded for this miner.
    last_updated_at: epoch seconds of the most recent observation.
    flagged_at: epoch seconds when the miner first crossed the flag
        threshold this round, or 0.0 if not currently flagged.
    last_disputes: a recent ring buffer of (signal_id_or_query_id, delta)
        tuples to give the miner enough context to construct an appeal.
        Bounded to MAX_RECENT_DISPUTES.
    """

    hotkey: str
    score: float = 0.0
    sample_count: int = 0
    last_updated_at: float = 0.0
    flagged_at: float = 0.0
    last_disputes: list[tuple[str, float]] = field(default_factory=list)

    MAX_RECENT_DISPUTES = 20

    def is_flagged(self) -> bool:
        return self.flagged_at > 0.0

    def to_dict(self) -> dict:
        return {
            "hotkey": self.hotkey,
            "score": self.score,
            "sample_count": self.sample_count,
            "last_updated_at": self.last_updated_at,
            "flagged_at": self.flagged_at,
            "last_disputes": [list(d) for d in self.last_disputes[-self.MAX_RECENT_DISPUTES :]],
        }

    @classmethod
    def from_dict(cls, d: dict) -> CusumState:
        return cls(
            hotkey=d.get("hotkey", ""),
            score=float(d.get("score", 0.0)),
            sample_count=int(d.get("sample_count", 0)),
            last_updated_at=float(d.get("last_updated_at", 0.0)),
            flagged_at=float(d.get("flagged_at", 0.0)),
            last_disputes=[tuple(x) for x in d.get("last_disputes", [])][-cls.MAX_RECENT_DISPUTES :],
        )


class ConsensusCircuitBreaker:
    """Tracks CUSUM scores per miner hotkey and reports flag transitions.

    Use:
        cb = ConsensusCircuitBreaker(db_path="data/cusum.db")
        cb.record_observation(hotkey="5Aa", deviation=0.02, query_id="q123")
        if cb.is_flagged("5Aa"):
            # trigger appeal flow
            ...

    Parameters:
        tolerance: per-query noise floor. A deviation at-or-below this
            value contributes 0 to the score. Pick this larger than the
            typical honest jitter (cache staleness, upstream timing).
            Default 0.005 (0.5% of normalized price scale).
        flag_threshold: the cumulative score that triggers a flag. Pick
            so a miner with sustained 1% bias (delta - tolerance = 0.005)
            gets flagged in ~1000 observations. Default 5.0.
        decay_per_observation: multiplicative decay applied to the
            running score on each new observation. A small value
            (e.g. 0.999) makes ancient deviations slowly fade so a
            miner that went quiet for a while doesn't carry forever.
            Default 0.999.
    """

    DEFAULT_TOLERANCE = 0.005
    DEFAULT_FLAG_THRESHOLD = 5.0
    DEFAULT_DECAY = 0.999

    def __init__(
        self,
        *,
        tolerance: float = DEFAULT_TOLERANCE,
        flag_threshold: float = DEFAULT_FLAG_THRESHOLD,
        decay_per_observation: float = DEFAULT_DECAY,
        db_path: str | None = None,
    ) -> None:
        if tolerance < 0:
            raise ValueError("tolerance must be >= 0")
        if flag_threshold <= 0:
            raise ValueError("flag_threshold must be > 0")
        if not 0 < decay_per_observation <= 1.0:
            raise ValueError("decay_per_observation must be in (0, 1]")
        self.tolerance = tolerance
        self.flag_threshold = flag_threshold
        self.decay_per_observation = decay_per_observation

        self._states: dict[str, CusumState] = {}
        self._lock = threading.Lock()
        # Separate lock for SQLite writes. Without this, concurrent
        # record_observation() calls under high load can race the
        # _persist() write and trip "database is locked" even with
        # busy_timeout. WAL helps for reads but not for writers.
        self._db_lock = threading.Lock()

        self._db: sqlite3.Connection | None = None
        if db_path:
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
            self._db = sqlite3.connect(db_path, check_same_thread=False)
            self._db.execute("PRAGMA journal_mode=WAL")
            self._db.execute("PRAGMA busy_timeout=5000")
            self._db.execute(
                """
                CREATE TABLE IF NOT EXISTS cusum_scores (
                    hotkey TEXT PRIMARY KEY,
                    data TEXT NOT NULL,
                    updated_at REAL NOT NULL
                )
                """
            )
            self._db.commit()
            self._load_persisted()

    def _load_persisted(self) -> None:
        if not self._db:
            return
        try:
            cursor = self._db.execute("SELECT hotkey, data FROM cusum_scores")
            loaded = 0
            for hotkey, data_json in cursor:
                try:
                    state = CusumState.from_dict(json.loads(data_json))
                    self._states[hotkey] = state
                    loaded += 1
                except Exception:
                    continue
            if loaded:
                log.info("circuit_breaker_loaded", count=loaded)
        except Exception as e:
            log.error("circuit_breaker_load_failed", err=str(e)[:200])

    def _persist(self, hotkey: str) -> None:
        if not self._db:
            return
        state = self._states.get(hotkey)
        if not state:
            return
        try:
            with self._db_lock:
                self._db.execute(
                    "INSERT OR REPLACE INTO cusum_scores (hotkey, data, updated_at) VALUES (?, ?, ?)",
                    (hotkey, json.dumps(state.to_dict()), _time.time()),
                )
                self._db.commit()
        except Exception as e:
            log.warning("circuit_breaker_persist_failed", hotkey=hotkey[:10], err=str(e)[:100])

    def get_state(self, hotkey: str) -> CusumState | None:
        return self._states.get(hotkey)

    def get_or_create(self, hotkey: str) -> CusumState:
        with self._lock:
            existing = self._states.get(hotkey)
            if existing is not None:
                return existing
            state = CusumState(hotkey=hotkey)
            self._states[hotkey] = state
            return state

    def record_observation(
        self,
        *,
        hotkey: str,
        deviation: float,
        query_id: str = "",
        now: float | None = None,
    ) -> CusumState:
        """Update a miner's CUSUM score with a new observation.

        `deviation` is the absolute distance between this miner's response
        and the consensus on a single query, on whatever normalized scale
        the caller chose (typically 0.0 to 1.0). The score grows by
        max(0, |deviation| - tolerance), then is decayed.

        Returns the updated state (so callers can immediately check
        is_flagged() without a second lookup).
        """
        if not hotkey:
            raise ValueError("hotkey is required")
        if not math.isfinite(deviation):
            raise ValueError(f"deviation must be finite, got {deviation}")
        current = _time.time() if now is None else now
        with self._lock:
            state = self._states.get(hotkey)
            if state is None:
                state = CusumState(hotkey=hotkey)
                self._states[hotkey] = state

            abs_dev = abs(deviation)
            increment = max(0.0, abs_dev - self.tolerance)
            decayed = state.score * self.decay_per_observation
            new_score = decayed + increment
            state.score = new_score
            state.sample_count += 1
            state.last_updated_at = current

            if query_id:
                state.last_disputes.append((query_id, abs_dev))
                if len(state.last_disputes) > CusumState.MAX_RECENT_DISPUTES:
                    state.last_disputes = state.last_disputes[-CusumState.MAX_RECENT_DISPUTES :]

            was_flagged = state.flagged_at > 0.0
            if not was_flagged and new_score >= self.flag_threshold:
                state.flagged_at = current
                log.warning(
                    "circuit_breaker_flagged",
                    hotkey=hotkey[:10],
                    score=round(new_score, 4),
                    threshold=self.flag_threshold,
                    sample_count=state.sample_count,
                )

        self._persist(hotkey)
        return state

    def is_flagged(self, hotkey: str) -> bool:
        state = self._states.get(hotkey)
        return state is not None and state.is_flagged()

    def get_score(self, hotkey: str) -> float:
        state = self._states.get(hotkey)
        return state.score if state else 0.0

    def get_sample_count(self, hotkey: str) -> int:
        state = self._states.get(hotkey)
        return state.sample_count if state else 0

    def clear_flag(
        self,
        hotkey: str,
        *,
        reason: str = "",
        reset_score: bool = True,
    ) -> bool:
        """Clear a miner's flag. Called by the appeal handler when an
        appeal succeeds (reset_score=True; the miner is restored) or by
        the slash handler when an appeal fails (reset_score=False; the
        flag clears but score stays high so the miner has to actively
        rebuild reputation through agreement).

        Returns True if a flag was actually cleared.
        """
        with self._lock:
            state = self._states.get(hotkey)
            if state is None or not state.is_flagged():
                return False
            state.flagged_at = 0.0
            if reset_score:
                state.score = 0.0
            log.info(
                "circuit_breaker_flag_cleared",
                hotkey=hotkey[:10],
                reset_score=reset_score,
                reason=reason,
            )
        self._persist(hotkey)
        return True

    def remove(self, hotkey: str) -> bool:
        """Remove a miner's tracking entirely (e.g., on deregistration)."""
        with self._lock:
            if hotkey not in self._states:
                return False
            del self._states[hotkey]
        if self._db:
            try:
                with self._db_lock:
                    self._db.execute("DELETE FROM cusum_scores WHERE hotkey = ?", (hotkey,))
                    self._db.commit()
            except Exception:
                pass
        return True

    def all_flagged(self) -> Iterator[CusumState]:
        for state in list(self._states.values()):
            if state.is_flagged():
                yield state

    def all_states(self) -> Iterator[CusumState]:
        return iter(list(self._states.values()))

    def reset(self) -> None:
        """Wipe all in-memory state. Used by tests; not for production."""
        with self._lock:
            self._states.clear()
        if self._db:
            try:
                with self._db_lock:
                    self._db.execute("DELETE FROM cusum_scores")
                    self._db.commit()
            except Exception:
                pass
