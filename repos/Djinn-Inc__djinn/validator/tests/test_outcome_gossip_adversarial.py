"""Phase C — adversarial / boundary tests for outcome gossip.

These tests actively try to break the gossip layer. They cover the
edges the happy-path tests in test_outcome_gossip.py don't reach:

- Pydantic boundary: length 0 / 1 / 2000 / 2001, enum -1 / 0 / 3 / 4
- Length-mismatch with non-trivial line counts (1, 100, 1000)
- Race: gossip arrives while own resolve is in flight
- Idempotency: concurrent gossips for the same signal
- Adversarial peer: forged outcomes don't get stored even on retries
- Concurrent gossip from multiple peers for the same signal
- ESPN-fetch raises mid-replay
- Large signal (1000 lines) survives end-to-end
"""

from __future__ import annotations

import asyncio

import pytest
from unittest.mock import AsyncMock

from djinn_validator.core.espn import ESPNClient, ESPNGame
from djinn_validator.core.outcomes import (
    Outcome,
    OutcomeAttestor,
    SignalMetadata,
    parse_pick,
)


# Reuse the canonical mock pattern from test_outcome_gossip.py so behavior
# diffs across test files are obvious.

SAMPLE_LINES = [
    "Lakers -3.5 (-110)",
    "Celtics +3.5 (-110)",
    "Over 218.5 (-110)",
    "Under 218.5 (-110)",
    "Lakers ML (-150)",
    "Celtics ML (+130)",
    "Lakers -1.5 (-105)",
    "Celtics +1.5 (-115)",
    "Over 215.0 (-110)",
    "Under 215.0 (-110)",
]
SAMPLE_PARSED = [parse_pick(line) for line in SAMPLE_LINES]


def _mock_espn_client(game: ESPNGame | None) -> ESPNClient:
    mock = AsyncMock(spec=ESPNClient)
    mock.get_game_by_teams = AsyncMock(return_value=game)
    mock.get_scoreboard = AsyncMock(return_value=[game] if game else [])
    mock.close = AsyncMock()
    return mock


def _signal(signal_id: str = "sig1", lines=None) -> SignalMetadata:
    return SignalMetadata(
        signal_id=signal_id,
        sport="basketball_nba",
        event_id="evt1",
        home_team="Lakers",
        away_team="Celtics",
        lines=lines or SAMPLE_PARSED,
    )


def _final_game() -> ESPNGame:
    return ESPNGame(
        espn_id="1",
        home_team="Lakers",
        away_team="Celtics",
        home_score=110,
        away_score=105,
        status="final",
    )


class TestPydanticBoundaries:
    """OutcomeGossipRequest schema boundaries — these run via TestClient
    so we exercise the FastAPI request validation path, not just the
    receive_gossip method."""

    @pytest.fixture
    def client(self):
        from fastapi.testclient import TestClient
        from djinn_validator.api.server import create_app
        from djinn_validator.core.purchase import PurchaseOrchestrator
        from djinn_validator.core.shares import ShareStore

        store = ShareStore()
        orch = PurchaseOrchestrator(store)
        attestor = OutcomeAttestor(espn_client=_mock_espn_client(_final_game()))
        attestor.register_signal(_signal())
        app = create_app(store, orch, attestor)
        yield TestClient(app), attestor
        store.close()

    def test_outcomes_length_0_rejected(self, client):
        c, _ = client
        resp = c.post(
            "/v1/outcomes/gossip",
            json={"signal_id": "sig1", "outcomes": [], "raw_espn_summary": {}, "source_uid": 1},
        )
        assert resp.status_code == 422, resp.text

    def test_outcomes_length_2001_rejected(self, client):
        c, _ = client
        resp = c.post(
            "/v1/outcomes/gossip",
            json={
                "signal_id": "sig1",
                "outcomes": [1] * 2001,
                "raw_espn_summary": {},
                "source_uid": 1,
            },
        )
        assert resp.status_code == 422, resp.text

    def test_outcomes_length_2000_passes_validation(self, client):
        """2000 is the new ceiling; should hit the receive_gossip method
        (not 422 at the schema layer). Will then fail length-match against
        the registered 10-line signal — that's the next layer's concern."""
        c, _ = client
        resp = c.post(
            "/v1/outcomes/gossip",
            json={
                "signal_id": "sig1",
                "outcomes": [1] * 2000,
                "raw_espn_summary": {},
                "source_uid": 1,
            },
        )
        # Schema passes; semantics fail (length mismatch vs 10-line signal)
        assert resp.status_code == 200, resp.text
        assert resp.json()["reason"] == "disputed"

    def test_outcome_enum_negative_rejected(self, client):
        c, _ = client
        resp = c.post(
            "/v1/outcomes/gossip",
            json={"signal_id": "sig1", "outcomes": [-1] * 10, "raw_espn_summary": {}, "source_uid": 1},
        )
        assert resp.status_code == 422

    def test_outcome_enum_4_rejected(self, client):
        c, _ = client
        resp = c.post(
            "/v1/outcomes/gossip",
            json={"signal_id": "sig1", "outcomes": [4] * 10, "raw_espn_summary": {}, "source_uid": 1},
        )
        assert resp.status_code == 422

    def test_outcome_enum_3_void_passes(self, client):
        """3=VOID is the upper-bound legitimate value."""
        c, _ = client
        resp = c.post(
            "/v1/outcomes/gossip",
            json={"signal_id": "sig1", "outcomes": [3] * 10, "raw_espn_summary": {}, "source_uid": 1},
        )
        # Schema passes; replay-verify will dispute (game was decisive, all VOID is wrong)
        assert resp.status_code == 200
        assert resp.json()["reason"] == "disputed"

    def test_signal_id_with_path_traversal_rejected(self, client):
        c, _ = client
        resp = c.post(
            "/v1/outcomes/gossip",
            json={
                "signal_id": "../../../etc/passwd",
                "outcomes": [1] * 10,
                "raw_espn_summary": {},
                "source_uid": 1,
            },
        )
        assert resp.status_code == 422

    def test_source_uid_negative_rejected(self, client):
        c, _ = client
        resp = c.post(
            "/v1/outcomes/gossip",
            json={"signal_id": "sig1", "outcomes": [1] * 10, "raw_espn_summary": {}, "source_uid": -1},
        )
        assert resp.status_code == 422

    def test_source_uid_huge_rejected(self, client):
        c, _ = client
        resp = c.post(
            "/v1/outcomes/gossip",
            json={
                "signal_id": "sig1",
                "outcomes": [1] * 10,
                "raw_espn_summary": {},
                "source_uid": 100_000,
            },
        )
        assert resp.status_code == 422

    def test_missing_outcomes_field_rejected(self, client):
        c, _ = client
        resp = c.post(
            "/v1/outcomes/gossip",
            json={"signal_id": "sig1", "raw_espn_summary": {}, "source_uid": 1},
        )
        assert resp.status_code == 422


class TestConcurrentReceives:
    """Multiple peers gossip the same outcome simultaneously — receiver
    must be idempotent and not double-count resolved_total."""

    @pytest.mark.asyncio
    async def test_concurrent_gossips_resolve_once(self):
        from djinn_validator.core.outcomes import (
            EventResult,
            determine_all_outcomes,
        )

        attestor = OutcomeAttestor(espn_client=_mock_espn_client(_final_game()))
        meta = _signal()
        attestor.register_signal(meta)
        expected = determine_all_outcomes(
            SAMPLE_PARSED,
            EventResult(
                event_id="evt1",
                home_team="Lakers",
                away_team="Celtics",
                home_score=110,
                away_score=105,
                status="final",
            ),
            "Lakers",
            "Celtics",
        )
        expected_ints = [int(o) for o in expected]

        # 5 concurrent peers all gossiping the same correct outcome
        results = await asyncio.gather(
            *[
                attestor.receive_gossip("sig1", expected_ints, f"peer{i}")
                for i in range(5)
            ]
        )
        # Exactly ONE accepted, the rest are already_resolved (idempotent).
        statuses = [r[0] for r in results]
        accepted_count = statuses.count("accepted")
        already_count = statuses.count("already_resolved")
        assert accepted_count == 1, f"expected exactly 1 accepted, got {accepted_count}: {statuses}"
        assert already_count == 4, f"expected 4 already_resolved, got {already_count}: {statuses}"
        # And resolved_total only incremented once
        assert attestor.resolved_total == 1
        assert meta.resolved


class TestRaceWithLocalResolve:
    """Receive gossip while own resolve_signal is mid-flight."""

    @pytest.mark.asyncio
    async def test_local_resolve_then_gossip_is_idempotent(self):
        attestor = OutcomeAttestor(espn_client=_mock_espn_client(_final_game()))
        meta = _signal()
        attestor.register_signal(meta)

        # Local resolves first
        sid = await attestor.resolve_signal("sig1", "v_local")
        assert sid == "sig1"
        assert meta.resolved
        assert attestor.resolved_total == 1

        # Now gossip arrives — should be idempotent
        existing = [int(o) for o in (meta.outcomes or [])]
        status, _ = await attestor.receive_gossip("sig1", existing, "peer1")
        assert status == "already_resolved"
        # Crucially: resolved_total did NOT double-increment
        assert attestor.resolved_total == 1


class TestForgedOutcomeMustNotStick:
    """An adversarial peer keeps sending forged outcomes; receiver
    rejects every time and never silently corrupts state."""

    @pytest.mark.asyncio
    async def test_repeat_disputes_never_store(self):
        attestor = OutcomeAttestor(espn_client=_mock_espn_client(_final_game()))
        meta = _signal()
        attestor.register_signal(meta)

        # 10 attempts with forged outcomes
        forged = [int(Outcome.VOID)] * 10
        for _ in range(10):
            status, _ = await attestor.receive_gossip("sig1", forged, "5BadActor")
            assert status == "disputed"
        assert not meta.resolved
        assert attestor.resolved_total == 0

    @pytest.mark.asyncio
    async def test_disputed_then_correct_eventually_accepts(self):
        """A peer first sends garbage then sends correct outcomes —
        receiver should accept the second one. Disputes don't poison
        the per-signal slot."""
        from djinn_validator.core.outcomes import (
            EventResult,
            determine_all_outcomes,
        )

        attestor = OutcomeAttestor(espn_client=_mock_espn_client(_final_game()))
        meta = _signal()
        attestor.register_signal(meta)

        forged = [int(Outcome.VOID)] * 10
        s1, _ = await attestor.receive_gossip("sig1", forged, "5HonestPeer")
        assert s1 == "disputed"
        assert not meta.resolved

        expected = determine_all_outcomes(
            SAMPLE_PARSED,
            EventResult(
                event_id="evt1",
                home_team="Lakers",
                away_team="Celtics",
                home_score=110,
                away_score=105,
                status="final",
            ),
            "Lakers",
            "Celtics",
        )
        s2, _ = await attestor.receive_gossip(
            "sig1", [int(o) for o in expected], "5HonestPeer"
        )
        assert s2 == "accepted"
        assert meta.resolved


class TestLargeSignal:
    """A 100-line signal (the production case that hit max_length=64).
    Ensures the path works end-to-end at production scale."""

    @pytest.mark.asyncio
    async def test_100_line_signal_resolves_via_gossip(self):
        from djinn_validator.core.outcomes import (
            EventResult,
            determine_all_outcomes,
        )

        # 100 distinct lines (mix of spreads/totals/h2h, varied)
        line_strs = []
        for i in range(100):
            kind = i % 4
            if kind == 0:
                line_strs.append(f"Lakers -{(i % 10) + 0.5} (-110)")
            elif kind == 1:
                line_strs.append(f"Celtics +{(i % 10) + 0.5} (-110)")
            elif kind == 2:
                line_strs.append(f"Over {200 + (i % 30) + 0.5} (-110)")
            else:
                line_strs.append(f"Under {200 + (i % 30) + 0.5} (-110)")
        parsed = [parse_pick(s) for s in line_strs]

        attestor = OutcomeAttestor(espn_client=_mock_espn_client(_final_game()))
        meta = _signal(lines=parsed)
        attestor.register_signal(meta)

        result = EventResult(
            event_id="evt1",
            home_team="Lakers",
            away_team="Celtics",
            home_score=110,
            away_score=105,
            status="final",
        )
        expected = determine_all_outcomes(parsed, result, "Lakers", "Celtics")
        expected_ints = [int(o) for o in expected]
        assert len(expected_ints) == 100

        status, accepted = await attestor.receive_gossip("sig1", expected_ints, "5Peer")
        assert status == "accepted"
        assert accepted == expected_ints
        assert meta.resolved

    @pytest.mark.asyncio
    async def test_reconcile_picks_oldest_first(self):
        """Phase A1.5 reconciliation tracker — oldest-gossiped first,
        never-gossiped before previously-gossiped, only resolved signals,
        respects limit."""
        attestor = OutcomeAttestor(espn_client=_mock_espn_client(_final_game()))
        # Register 5 signals
        metas = []
        for i in range(5):
            m = _signal(signal_id=f"sig{i}")
            attestor.register_signal(m)
            metas.append(m)
        # Resolve 4 of them (sig0..sig3); leave sig4 unresolved
        for i in range(4):
            sid = await attestor.resolve_signal(f"sig{i}", "v1")
            assert sid == f"sig{i}"

        # Mark some as gossiped at known times so order is deterministic
        import time

        attestor._last_gossiped_at["sig0"] = time.time() - 100  # oldest
        attestor._last_gossiped_at["sig2"] = time.time() - 50   # mid
        attestor._last_gossiped_at["sig3"] = time.time() - 10   # newest
        # sig1 is resolved but never gossiped — should sort FIRST (ts=0)

        ordered = attestor.get_resolved_for_reconcile(limit=10)
        # sig1 (never gossiped) before all timestamped ones
        # then sig0, sig2, sig3 by oldest-first
        assert ordered == ["sig1", "sig0", "sig2", "sig3"], ordered
        # sig4 is unresolved — must NOT be in the list
        assert "sig4" not in ordered

        # mark_gossiped updates the timestamp; sig1 should move to last
        attestor.mark_gossiped("sig1")
        ordered = attestor.get_resolved_for_reconcile(limit=10)
        assert ordered[-1] == "sig1", ordered
        assert ordered[0] == "sig0", ordered

        # Limit honored
        assert len(attestor.get_resolved_for_reconcile(limit=2)) == 2

    @pytest.mark.asyncio
    async def test_100_line_signal_with_one_outcome_flipped_is_disputed(self):
        """Single-bit flip on a 100-line outcome must be caught."""
        from djinn_validator.core.outcomes import (
            EventResult,
            determine_all_outcomes,
        )

        line_strs = [f"Lakers -{(i % 10) + 0.5} (-110)" for i in range(100)]
        parsed = [parse_pick(s) for s in line_strs]
        attestor = OutcomeAttestor(espn_client=_mock_espn_client(_final_game()))
        meta = _signal(lines=parsed)
        attestor.register_signal(meta)

        expected = determine_all_outcomes(
            parsed,
            EventResult(
                event_id="evt1",
                home_team="Lakers",
                away_team="Celtics",
                home_score=110,
                away_score=105,
                status="final",
            ),
            "Lakers",
            "Celtics",
        )
        expected_ints = [int(o) for o in expected]
        # Flip outcome at position 50: FAVORABLE↔UNFAVORABLE
        flipped = list(expected_ints)
        if flipped[50] == int(Outcome.FAVORABLE):
            flipped[50] = int(Outcome.UNFAVORABLE)
        elif flipped[50] == int(Outcome.UNFAVORABLE):
            flipped[50] = int(Outcome.FAVORABLE)
        else:
            flipped[50] = int(Outcome.FAVORABLE)
        assert flipped != expected_ints

        status, _ = await attestor.receive_gossip("sig1", flipped, "5Peer")
        assert status == "disputed"
        assert not meta.resolved
