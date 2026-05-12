"""Tests for the MPC coordinator module."""

from __future__ import annotations

import time

import pytest

from djinn_validator.core.mpc import MPCResult, Round1Message, generate_beaver_triples
from djinn_validator.core.mpc_coordinator import (
    MPCCoordinator,
    MPCSessionState,
    SessionStatus,
)
from djinn_validator.utils.crypto import Share, generate_signal_index_shares


class TestCreateSession:
    def test_creates_session(self) -> None:
        coord = MPCCoordinator()
        session = coord.create_session(
            signal_id="sig-1",
            available_indices=[1, 3, 5],
            coordinator_x=1,
            participant_xs=[1, 2, 3, 4, 5, 6, 7],
            threshold=7,
        )
        assert session.signal_id == "sig-1"
        assert session.available_indices == [1, 3, 5]
        assert session.status == SessionStatus.ROUND1_COLLECTING
        assert len(session.triples) == 3  # One per available index

    def test_session_id_unique(self) -> None:
        coord = MPCCoordinator()
        s1 = coord.create_session("sig-1", [1], 1, [1, 2, 3], 3)
        s2 = coord.create_session("sig-1", [1], 1, [1, 2, 3], 3)
        assert s1.session_id != s2.session_id

    def test_active_session_count(self) -> None:
        coord = MPCCoordinator()
        coord.create_session("sig-1", [1, 2], 1, [1, 2, 3], 3)
        coord.create_session("sig-2", [3, 4], 1, [1, 2, 3], 3)
        assert coord.active_session_count == 2


class TestGetSession:
    def test_get_existing(self) -> None:
        coord = MPCCoordinator()
        session = coord.create_session("sig-1", [1], 1, [1, 2, 3], 3)
        retrieved = coord.get_session(session.session_id)
        assert retrieved is session

    def test_get_nonexistent(self) -> None:
        coord = MPCCoordinator()
        assert coord.get_session("nope") is None

    def test_expired_session(self) -> None:
        coord = MPCCoordinator()
        session = coord.create_session("sig-1", [1], 1, [1, 2, 3], 3)
        session.created_at = time.monotonic() - 200  # Force expiry
        # Expired sessions return None (removed from internal dict)
        retrieved = coord.get_session(session.session_id)
        assert retrieved is None
        # Second lookup also returns None
        assert coord.get_session(session.session_id) is None


class TestTripleShares:
    def test_get_triple_shares(self) -> None:
        coord = MPCCoordinator()
        session = coord.create_session("sig-1", [1, 2], 1, [1, 2, 3], 3)
        shares = coord.get_triple_shares_for_participant(session.session_id, 2)
        assert shares is not None
        assert len(shares) == 2  # 2 available indices = 2 triples
        for s in shares:
            assert "a" in s
            assert "b" in s
            assert "c" in s

    def test_nonexistent_session(self) -> None:
        coord = MPCCoordinator()
        assert coord.get_triple_shares_for_participant("nope", 1) is None

    def test_nonexistent_participant(self) -> None:
        coord = MPCCoordinator()
        session = coord.create_session("sig-1", [1], 1, [1, 2, 3], 3)
        result = coord.get_triple_shares_for_participant(session.session_id, 99)
        assert result is None


class TestRound1Submission:
    def test_submit_round1(self) -> None:
        coord = MPCCoordinator()
        session = coord.create_session("sig-1", [1], 1, [1, 2, 3], 3)
        msg = Round1Message(validator_x=1, d_value=42, e_value=99)
        assert coord.submit_round1(session.session_id, 0, msg) is True
        assert len(session.round1_messages[0]) == 1

    def test_submit_duplicate_ignored(self) -> None:
        coord = MPCCoordinator()
        session = coord.create_session("sig-1", [1], 1, [1, 2, 3], 3)
        msg = Round1Message(validator_x=1, d_value=42, e_value=99)
        coord.submit_round1(session.session_id, 0, msg)
        coord.submit_round1(session.session_id, 0, msg)
        assert len(session.round1_messages[0]) == 1

    def test_submit_nonexistent_session(self) -> None:
        coord = MPCCoordinator()
        msg = Round1Message(validator_x=1, d_value=42, e_value=99)
        assert coord.submit_round1("nope", 0, msg) is False


class TestRoundComplete:
    def test_round_complete(self) -> None:
        coord = MPCCoordinator()
        session = coord.create_session("sig-1", [1], 1, [1, 2, 3], 3)
        for vx in [1, 2, 3]:
            msg = Round1Message(validator_x=vx, d_value=vx * 10, e_value=vx * 20)
            coord.submit_round1(session.session_id, 0, msg)
        assert coord.is_round_complete(session.session_id) is True

    def test_round_incomplete(self) -> None:
        coord = MPCCoordinator()
        session = coord.create_session("sig-1", [1], 1, [1, 2, 3], 3)
        msg = Round1Message(validator_x=1, d_value=10, e_value=20)
        coord.submit_round1(session.session_id, 0, msg)
        assert coord.is_round_complete(session.session_id) is False


class TestComputeResult:
    def test_compute_available(self) -> None:
        coord = MPCCoordinator()
        # Real index = 5, available set includes 5
        shares = generate_signal_index_shares(5)
        session = coord.create_session(
            "sig-1",
            [1, 3, 5, 7],
            1,
            list(range(1, 11)),
            7,
        )
        result = coord.compute_result_with_shares(session.session_id, shares)
        assert result is not None
        assert result.available is True
        assert session.status == SessionStatus.COMPLETE

    def test_compute_unavailable(self) -> None:
        coord = MPCCoordinator()
        # Real index = 5, available set does NOT include 5
        shares = generate_signal_index_shares(5)
        session = coord.create_session(
            "sig-1",
            [1, 3, 7, 9],
            1,
            list(range(1, 11)),
            7,
        )
        result = coord.compute_result_with_shares(session.session_id, shares)
        assert result is not None
        assert result.available is False

    def test_compute_nonexistent(self) -> None:
        coord = MPCCoordinator()
        assert coord.compute_result_with_shares("nope", []) is None


class TestSubmitRound1EdgeCases:
    def test_submit_to_expired_session_rejected(self) -> None:
        """Round 1 submission to an expired session should be rejected."""
        coord = MPCCoordinator()
        session = coord.create_session("sig-1", [1], 1, [1, 2, 3], 3)
        session.created_at = time.monotonic() - 200  # Force expiry
        # get_session marks it EXPIRED and removes it from dict
        coord.get_session(session.session_id)
        msg = Round1Message(validator_x=1, d_value=42, e_value=99)
        # Session is gone, so submit returns False
        assert coord.submit_round1(session.session_id, 0, msg) is False

    def test_submit_to_completed_session_rejected(self) -> None:
        coord = MPCCoordinator()
        session = coord.create_session("sig-1", [1], 1, [1, 2, 3], 3)
        session.status = SessionStatus.COMPLETE
        msg = Round1Message(validator_x=1, d_value=42, e_value=99)
        assert coord.submit_round1(session.session_id, 0, msg) is False

    def test_multiple_gate_round_completion(self) -> None:
        """Round completion requires all gates to have all participants."""
        coord = MPCCoordinator()
        session = coord.create_session("sig-1", [1, 2], 1, [1, 2], 2)
        # Submit for gate 0 from both participants
        coord.submit_round1(session.session_id, 0, Round1Message(1, 10, 20))
        coord.submit_round1(session.session_id, 0, Round1Message(2, 30, 40))
        # Gate 1 still missing
        assert coord.is_round_complete(session.session_id) is False
        # Submit for gate 1
        coord.submit_round1(session.session_id, 1, Round1Message(1, 50, 60))
        coord.submit_round1(session.session_id, 1, Round1Message(2, 70, 80))
        assert coord.is_round_complete(session.session_id) is True


class TestComputeResultIdempotency:
    def test_compute_result_twice(self) -> None:
        """Computing result multiple times should be safe."""
        from djinn_validator.utils.crypto import generate_signal_index_shares

        coord = MPCCoordinator()
        shares = generate_signal_index_shares(5)
        session = coord.create_session("sig-1", [1, 3, 5], 1, list(range(1, 11)), 7)
        r1 = coord.compute_result_with_shares(session.session_id, shares)
        r2 = coord.compute_result_with_shares(session.session_id, shares)
        assert r1 is not None
        assert r2 is not None
        assert r1.available == r2.available


class TestConcurrentAccess:
    def test_concurrent_session_creation(self) -> None:
        """Create sessions from multiple threads concurrently."""
        import threading

        coord = MPCCoordinator()
        errors = []
        sessions = []

        def create(i: int) -> None:
            try:
                s = coord.create_session(f"sig-{i}", [1], 1, [1, 2, 3], 3)
                sessions.append(s.session_id)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=create, args=(i,)) for i in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == []
        assert len(set(sessions)) == 20  # All unique

    def test_concurrent_cleanup(self) -> None:
        """Cleanup from multiple threads shouldn't crash."""
        import threading

        coord = MPCCoordinator()
        for i in range(10):
            s = coord.create_session(f"sig-{i}", [1], 1, [1, 2, 3], 3)
            s.created_at = time.monotonic() - 200  # All expired
        errors = []

        def cleanup() -> None:
            try:
                coord.cleanup_expired()
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=cleanup) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert errors == []


class TestCleanup:
    def test_cleanup_expired(self) -> None:
        coord = MPCCoordinator()
        s1 = coord.create_session("sig-1", [1], 1, [1, 2, 3], 3)
        s2 = coord.create_session("sig-2", [2], 1, [1, 2, 3], 3)  # Fresh
        # Backdate s1 AFTER both sessions are created. Doing it before
        # the second create_session would trip the sweep that runs
        # inside create_session and silently remove s1, leaving
        # cleanup_expired() with nothing to remove (which is what the
        # original test asserted, and what later broke when sweep was
        # added to create_session).
        s1.created_at = time.monotonic() - 200

        removed = coord.cleanup_expired()
        assert removed == 1
        assert coord.get_session(s1.session_id) is None
        assert coord.get_session(s2.session_id) is not None

    def test_cleanup_none_expired(self) -> None:
        coord = MPCCoordinator()
        coord.create_session("sig-1", [1], 1, [1, 2, 3], 3)
        assert coord.cleanup_expired() == 0


class TestExpiryRemovesFromDict:
    """Verify expired sessions are removed from memory by get_session()."""

    def test_expired_session_removed_from_active_count(self) -> None:
        coord = MPCCoordinator()
        session = coord.create_session("sig-1", [1], 1, [1, 2, 3], 3)
        assert coord.active_session_count == 1
        session.created_at = time.monotonic() - 200
        coord.get_session(session.session_id)
        assert coord.active_session_count == 0

    def test_expired_session_not_in_cleanup(self) -> None:
        """Already removed by get_session, so cleanup finds nothing."""
        coord = MPCCoordinator()
        session = coord.create_session("sig-1", [1], 1, [1, 2, 3], 3)
        session.created_at = time.monotonic() - 200
        coord.get_session(session.session_id)  # Removes it
        assert coord.cleanup_expired() == 0

    def test_triple_shares_for_expired_session(self) -> None:
        coord = MPCCoordinator()
        session = coord.create_session("sig-1", [1], 1, [1, 2, 3], 3)
        session.created_at = time.monotonic() - 200
        coord.get_session(session.session_id)  # Removes it
        assert coord.get_triple_shares_for_participant(session.session_id, 1) is None


class TestMaxSessionsEviction:
    """Verify that MAX_SESSIONS limit is enforced."""

    def test_evicts_expired_when_at_capacity(self) -> None:
        coord = MPCCoordinator()
        coord.MAX_SESSIONS = 3
        s1 = coord.create_session("sig-1", [1], 1, [1, 2, 3], 3)
        coord.create_session("sig-2", [1], 1, [1, 2, 3], 3)
        coord.create_session("sig-3", [1], 1, [1, 2, 3], 3)
        s1.created_at = time.monotonic() - 200  # Expire s1
        # Creating a 4th should evict the expired s1
        coord.create_session("sig-4", [1], 1, [1, 2, 3], 3)
        assert coord.get_session(s1.session_id) is None
        assert len(coord._sessions) == 3

    def test_evicts_oldest_when_all_fresh(self) -> None:
        coord = MPCCoordinator()
        coord.MAX_SESSIONS = 2
        s1 = coord.create_session("sig-1", [1], 1, [1, 2, 3], 3)
        coord.create_session("sig-2", [1], 1, [1, 2, 3], 3)
        # s1 is oldest but not expired
        coord.create_session("sig-3", [1], 1, [1, 2, 3], 3)
        assert coord.get_session(s1.session_id) is None
        assert len(coord._sessions) == 2


class TestReplaceSessionId:
    """Tests for the replace_session_id method."""

    def test_replace_succeeds(self) -> None:
        coord = MPCCoordinator()
        session = coord.create_session("sig-1", [1], 1, [1, 2, 3], 3)
        old_id = session.session_id
        assert coord.replace_session_id(old_id, "new-id")
        assert coord.get_session(old_id) is None
        assert coord.get_session("new-id") is not None
        assert coord.get_session("new-id").signal_id == "sig-1"

    def test_replace_old_id_not_found(self) -> None:
        coord = MPCCoordinator()
        assert not coord.replace_session_id("nonexistent", "new-id")

    def test_replace_new_id_already_exists(self) -> None:
        coord = MPCCoordinator()
        s1 = coord.create_session("sig-1", [1], 1, [1, 2, 3], 3)
        s2 = coord.create_session("sig-2", [2], 1, [1, 2, 3], 3)
        # Can't rename s1 to s2's ID
        assert not coord.replace_session_id(s1.session_id, s2.session_id)
        # s1 should still exist with its original ID
        assert coord.get_session(s1.session_id) is not None

    def test_replace_is_threadsafe(self) -> None:
        import threading

        coord = MPCCoordinator()
        session = coord.create_session("sig-1", [1], 1, [1, 2, 3], 3)
        old_id = session.session_id
        results = []

        def rename(new_id: str) -> None:
            results.append(coord.replace_session_id(old_id, new_id))

        t1 = threading.Thread(target=rename, args=("new-a",))
        t2 = threading.Thread(target=rename, args=("new-b",))
        t1.start()
        t2.start()
        t1.join()
        t2.join()
        # Exactly one should succeed
        assert sum(results) == 1


class TestSetResult:
    """Tests for the set_result method."""

    def test_set_result_succeeds(self) -> None:
        coord = MPCCoordinator()
        session = coord.create_session("sig-1", [1], 1, [1, 2, 3], 3)
        result = MPCResult(available=True, participating_validators=3)
        assert coord.set_result(session.session_id, result)
        updated = coord.get_session(session.session_id)
        assert updated.result is not None
        assert updated.result.available is True
        assert updated.status == SessionStatus.COMPLETE

    def test_set_result_nonexistent_session(self) -> None:
        coord = MPCCoordinator()
        result = MPCResult(available=False, participating_validators=0)
        assert not coord.set_result("nonexistent", result)

    def test_set_result_is_threadsafe(self) -> None:
        import threading

        coord = MPCCoordinator()
        session = coord.create_session("sig-1", [1], 1, [1, 2, 3], 3)
        errors = []

        def set_res(available: bool) -> None:
            try:
                coord.set_result(session.session_id, MPCResult(available=available, participating_validators=3))
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=set_res, args=(i % 2 == 0,)) for i in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert errors == []
        updated = coord.get_session(session.session_id)
        assert updated.status == SessionStatus.COMPLETE
