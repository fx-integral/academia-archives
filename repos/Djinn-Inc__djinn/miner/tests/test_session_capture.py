"""Tests for SessionCapture (proof session management)."""

from __future__ import annotations

import time

from djinn_miner.core.proof import CapturedSession, SessionCapture


def _make_session(query_id: str, captured_at: float | None = None) -> CapturedSession:
    return CapturedSession(
        query_id=query_id,
        request_url="https://api.example.com/v4/sports/nba/odds",
        captured_at=captured_at or time.time(),
    )


class TestSessionCapture:
    def test_record_and_get(self) -> None:
        cap = SessionCapture()
        session = _make_session("q-1")
        cap.record(session)
        assert cap.get("q-1") is session

    def test_get_nonexistent(self) -> None:
        cap = SessionCapture()
        assert cap.get("does-not-exist") is None

    def test_remove(self) -> None:
        cap = SessionCapture()
        cap.record(_make_session("q-1"))
        cap.remove("q-1")
        assert cap.get("q-1") is None
        assert cap.count == 0

    def test_remove_nonexistent_is_safe(self) -> None:
        cap = SessionCapture()
        cap.remove("q-nonexistent")  # Should not raise

    def test_count(self) -> None:
        cap = SessionCapture()
        assert cap.count == 0
        cap.record(_make_session("q-1"))
        assert cap.count == 1
        cap.record(_make_session("q-2"))
        assert cap.count == 2

    def test_eviction_on_max_sessions(self) -> None:
        cap = SessionCapture()
        cap._MAX_SESSIONS = 3
        cap.record(_make_session("q-1"))
        cap.record(_make_session("q-2"))
        cap.record(_make_session("q-3"))
        assert cap.count == 3
        # Adding a 4th should evict the oldest
        cap.record(_make_session("q-4"))
        assert cap.count == 3
        assert cap.get("q-4") is not None

    def test_ttl_expiration(self) -> None:
        cap = SessionCapture()
        cap.record(_make_session("q-1"))
        cap.record(_make_session("q-2"))
        # Backdate only q-1 past TTL
        cap._timestamps["q-1"] = time.monotonic() - cap._SESSION_TTL - 1
        # get() now triggers eviction of expired sessions
        assert cap.get("q-1") is None
        assert cap.get("q-2") is not None

    def test_overwrite_existing_session(self) -> None:
        cap = SessionCapture()
        s1 = _make_session("q-1")
        s2 = _make_session("q-1")
        cap.record(s1)
        cap.record(s2)
        assert cap.count == 1
        assert cap.get("q-1") is s2

    def test_eviction_with_empty_timestamps_is_safe(self) -> None:
        """Edge case: MAX_SESSIONS reached but timestamps dict is empty."""
        cap = SessionCapture()
        cap._MAX_SESSIONS = 0  # Always at capacity
        # This should not crash even with empty timestamps
        cap.record(_make_session("q-1"))
        assert cap.count == 1

    def test_get_evicts_expired(self) -> None:
        """get() should evict expired sessions, not just record()."""
        cap = SessionCapture()
        cap.record(_make_session("q-1"))
        cap.record(_make_session("q-2"))
        assert cap.count == 2
        # Backdate q-1 past TTL
        cap._timestamps["q-1"] = time.monotonic() - cap._SESSION_TTL - 1
        # get() triggers eviction
        result = cap.get("q-1")
        assert result is None
        assert cap.count == 1  # Only q-2 remains
