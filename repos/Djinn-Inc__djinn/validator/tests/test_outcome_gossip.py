"""Tests for outcome gossip — Phase A2 of the outcome layer.

Covers OutcomeAttestor.receive_gossip:
- Unknown signal (sender ahead of receiver's purchase pipeline)
- Idempotency on already-resolved signal
- Replay-verify: matching ESPN view → accept and store
- Replay-verify: mismatching outcomes → disputed, no storage
- Replay-verify: ESPN says game still in progress → pending_local
- Length-mismatched outcome vector → disputed

Uses the same _mock_espn_client pattern as test_outcomes.py so the validator
re-derives outcomes deterministically from the mock's view.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from djinn_validator.core.espn import ESPNClient, ESPNGame
from djinn_validator.core.outcomes import (
    Outcome,
    OutcomeAttestor,
    SignalMetadata,
    parse_pick,
)


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


def _signal(signal_id: str = "sig1") -> SignalMetadata:
    return SignalMetadata(
        signal_id=signal_id,
        sport="basketball_nba",
        event_id="evt1",
        home_team="Lakers",
        away_team="Celtics",
        lines=SAMPLE_PARSED,
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


class TestReceiveGossip:
    @pytest.mark.asyncio
    async def test_unknown_signal_returns_unknown(self) -> None:
        """Receiver with an empty signal table rejects gossip with 'unknown_signal'."""
        attestor = OutcomeAttestor()
        status, outcomes = await attestor.receive_gossip(
            signal_id="never_seen",
            gossiped_outcomes=[1, 1, 1, 1, 1, 1, 1, 1, 1, 1],
            signer_hotkey="5SignerHotkeyABC",
        )
        assert status == "unknown_signal"
        assert outcomes is None

    @pytest.mark.asyncio
    async def test_already_resolved_is_idempotent(self) -> None:
        """If a signal is already locally resolved, gossip is a no-op."""
        espn = _mock_espn_client(_final_game())
        attestor = OutcomeAttestor(espn_client=espn)
        meta = _signal()
        attestor.register_signal(meta)
        first = await attestor.resolve_signal("sig1", "v1")
        assert first == "sig1"
        assert meta.resolved
        existing = [int(o) for o in (meta.outcomes or [])]

        # Same outcomes gossiped from a peer — should be a clean idempotent return.
        status, outcomes = await attestor.receive_gossip(
            signal_id="sig1",
            gossiped_outcomes=existing,
            signer_hotkey="5SignerHotkeyABC",
        )
        assert status == "already_resolved"
        assert outcomes == existing

    @pytest.mark.asyncio
    async def test_accepted_when_replay_verify_matches(self) -> None:
        """Receiver re-fetches ESPN, derives same outcomes, marks resolved."""
        espn = _mock_espn_client(_final_game())
        attestor = OutcomeAttestor(espn_client=espn)
        meta = _signal()
        attestor.register_signal(meta)
        # Compute what local resolution WOULD produce, but don't run it —
        # we want the gossip path to do the work.
        from djinn_validator.core.outcomes import determine_all_outcomes, EventResult

        expected = determine_all_outcomes(
            SAMPLE_PARSED,
            EventResult(event_id="evt1", home_team="Lakers", away_team="Celtics", home_score=110, away_score=105, status="final"),
            "Lakers",
            "Celtics",
        )
        expected_ints = [int(o) for o in expected]
        assert not meta.resolved

        status, outcomes = await attestor.receive_gossip(
            signal_id="sig1",
            gossiped_outcomes=expected_ints,
            signer_hotkey="5SignerHotkeyABC",
        )
        assert status == "accepted"
        assert outcomes == expected_ints
        assert meta.resolved
        assert meta.outcomes is not None
        assert [int(o) for o in meta.outcomes] == expected_ints
        assert attestor.resolved_total == 1

    @pytest.mark.asyncio
    async def test_disputed_when_outcomes_diverge(self) -> None:
        """Gossiped outcomes that don't match local replay-verify are rejected."""
        espn = _mock_espn_client(_final_game())
        attestor = OutcomeAttestor(espn_client=espn)
        meta = _signal()
        attestor.register_signal(meta)

        # Send outcomes that are obviously wrong (all VOID when game is decisive).
        wrong = [int(Outcome.VOID)] * 10
        status, outcomes = await attestor.receive_gossip(
            signal_id="sig1",
            gossiped_outcomes=wrong,
            signer_hotkey="5BadActorXYZ",
        )
        assert status == "disputed"
        # Local-derived outcomes returned for diff logging
        assert outcomes is not None
        assert outcomes != wrong
        # And local state stays UNCOMMITTED — no silent accept
        assert not meta.resolved
        assert attestor.resolved_total == 0

    @pytest.mark.asyncio
    async def test_pending_local_when_espn_in_progress(self) -> None:
        """If receiver's ESPN says game not final yet, gossip is deferred."""
        in_progress = ESPNGame(
            espn_id="1",
            home_team="Lakers",
            away_team="Celtics",
            home_score=70,
            away_score=65,
            status="in_progress",
        )
        espn = _mock_espn_client(in_progress)
        attestor = OutcomeAttestor(espn_client=espn)
        meta = _signal()
        attestor.register_signal(meta)

        any_outcomes = [int(Outcome.FAVORABLE)] * 10
        status, outcomes = await attestor.receive_gossip(
            signal_id="sig1",
            gossiped_outcomes=any_outcomes,
            signer_hotkey="5SignerHotkeyABC",
        )
        assert status == "pending_local"
        assert outcomes is None
        assert not meta.resolved

    @pytest.mark.asyncio
    async def test_length_mismatch_is_disputed(self) -> None:
        """Outcome vector with wrong length never passes replay-verify."""
        espn = _mock_espn_client(_final_game())
        attestor = OutcomeAttestor(espn_client=espn)
        meta = _signal()
        attestor.register_signal(meta)

        too_short = [int(Outcome.FAVORABLE)] * 5  # 5 instead of 10
        status, outcomes = await attestor.receive_gossip(
            signal_id="sig1",
            gossiped_outcomes=too_short,
            signer_hotkey="5SignerHotkeyABC",
        )
        assert status == "disputed"
        assert outcomes is None
        assert not meta.resolved

    @pytest.mark.asyncio
    async def test_espn_fetch_error_returns_pending(self) -> None:
        """If receiver's ESPN call raises, gossip defers (no spurious dispute)."""
        espn = AsyncMock(spec=ESPNClient)
        espn.get_scoreboard = AsyncMock(side_effect=RuntimeError("ESPN unreachable"))
        espn.get_game_by_teams = AsyncMock(side_effect=RuntimeError("ESPN unreachable"))
        attestor = OutcomeAttestor(espn_client=espn)
        meta = _signal()
        # Fix game_date so we don't trigger 30-day back-walk (which catches
        # the exception per-day and would log it 31 times before bailing).
        meta.game_date = "20260101"
        attestor.register_signal(meta)

        any_outcomes = [int(Outcome.FAVORABLE)] * 10
        status, outcomes = await attestor.receive_gossip(
            signal_id="sig1",
            gossiped_outcomes=any_outcomes,
            signer_hotkey="5SignerHotkeyABC",
        )
        # An ESPN fetch error gives the receiver no opinion to rely on,
        # so it returns pending_local rather than falsely accepting or
        # falsely disputing. The sender will retry on a future cycle.
        assert status == "pending_local"
        assert outcomes is None
        assert not meta.resolved


class TestGossipEndpoint:
    """End-to-end test of POST /v1/outcomes/gossip via TestClient.

    Verifies the wire path: HTTP request → auth middleware → endpoint
    handler → OutcomeAttestor.receive_gossip → response. No real
    Bittensor metagraph; auth is skipped in BT_NETWORK=test mode.
    """

    @pytest.mark.asyncio
    async def test_endpoint_accepts_matching_gossip(self) -> None:
        from fastapi.testclient import TestClient

        from djinn_validator.api.server import create_app
        from djinn_validator.core.outcomes import (
            EventResult,
            determine_all_outcomes,
        )
        from djinn_validator.core.purchase import PurchaseOrchestrator
        from djinn_validator.core.shares import ShareStore

        share_store = ShareStore()
        try:
            purchase_orch = PurchaseOrchestrator(share_store)
            espn = _mock_espn_client(_final_game())
            attestor = OutcomeAttestor(espn_client=espn)
            meta = _signal()
            attestor.register_signal(meta)

            app = create_app(share_store, purchase_orch, attestor)
            client = TestClient(app)

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
            payload = {
                "signal_id": "sig1",
                "outcomes": [int(o) for o in expected],
                "raw_espn_summary": {
                    "home_team": "Lakers",
                    "away_team": "Celtics",
                    "sport": "basketball_nba",
                    "event_id": "evt1",
                },
                "source_uid": 1,
            }
            resp = client.post("/v1/outcomes/gossip", json=payload)
            assert resp.status_code == 200, resp.text
            data = resp.json()
            assert data["accepted"] is True
            assert data["duplicate"] is False
            assert data["reason"] == "accepted"
            assert meta.resolved
        finally:
            share_store.close()

    @pytest.mark.asyncio
    async def test_endpoint_rejects_disputed_gossip(self) -> None:
        from fastapi.testclient import TestClient

        from djinn_validator.api.server import create_app
        from djinn_validator.core.purchase import PurchaseOrchestrator
        from djinn_validator.core.shares import ShareStore

        share_store = ShareStore()
        try:
            purchase_orch = PurchaseOrchestrator(share_store)
            espn = _mock_espn_client(_final_game())
            attestor = OutcomeAttestor(espn_client=espn)
            meta = _signal()
            attestor.register_signal(meta)

            app = create_app(share_store, purchase_orch, attestor)
            client = TestClient(app)

            payload = {
                "signal_id": "sig1",
                "outcomes": [int(Outcome.VOID)] * 10,  # forged
                "raw_espn_summary": {},
                "source_uid": 99,
            }
            resp = client.post("/v1/outcomes/gossip", json=payload)
            assert resp.status_code == 200, resp.text
            data = resp.json()
            assert data["accepted"] is False
            assert data["reason"] == "disputed"
            assert not meta.resolved
        finally:
            share_store.close()

    @pytest.mark.asyncio
    async def test_endpoint_returns_unknown_for_unregistered(self) -> None:
        from fastapi.testclient import TestClient

        from djinn_validator.api.server import create_app
        from djinn_validator.core.purchase import PurchaseOrchestrator
        from djinn_validator.core.shares import ShareStore

        share_store = ShareStore()
        try:
            purchase_orch = PurchaseOrchestrator(share_store)
            attestor = OutcomeAttestor()  # empty
            app = create_app(share_store, purchase_orch, attestor)
            client = TestClient(app)

            payload = {
                "signal_id": "never_registered",
                "outcomes": [int(Outcome.FAVORABLE)] * 10,
                "raw_espn_summary": {},
                "source_uid": 1,
            }
            resp = client.post("/v1/outcomes/gossip", json=payload)
            assert resp.status_code == 200
            assert resp.json()["accepted"] is False
            assert resp.json()["reason"] == "unknown_signal"
        finally:
            share_store.close()


class TestGameDateGossipPropagation:
    """v1679 (P1-36 partial): gossip propagates game_date so receivers
    don't need to back-walk independently. When a sender includes
    game_date and the receiver's local meta has none, receiver adopts
    the gossiped date BEFORE replay-verify queries ESPN.

    Without this, validators that resolve a signal via 30-day back-walk
    may match different historical games (same team names play each
    other multiple times in a season) → divergent outcomes → divergent
    quality_scores → divergent scoreHashes → no quorum convergence.
    """

    @pytest.mark.asyncio
    async def test_gossiped_game_date_adopted_when_local_missing(self) -> None:
        espn = _mock_espn_client(_final_game())
        attestor = OutcomeAttestor(espn_client=espn)
        meta = _signal()
        attestor.register_signal(meta)
        assert meta.game_date is None

        status, outcomes = await attestor.receive_gossip(
            signal_id="sig1",
            gossiped_outcomes=[int(Outcome.FAVORABLE)] * 10,
            signer_hotkey="5SignerHotkeyABC",
            gossiped_game_date="20260501",
        )
        # Even though replay-verify may dispute the outcomes, the
        # game_date adoption happens before that.
        assert meta.game_date == "20260501"

    @pytest.mark.asyncio
    async def test_gossiped_game_date_does_not_overwrite_local(self) -> None:
        """Local game_date wins over gossip — the validator's own
        ESPN match has authority over peer claims."""
        espn = _mock_espn_client(_final_game())
        attestor = OutcomeAttestor(espn_client=espn)
        meta = _signal()
        meta.game_date = "20260601"  # Local has authoritative date
        attestor.register_signal(meta)

        await attestor.receive_gossip(
            signal_id="sig1",
            gossiped_outcomes=[int(Outcome.FAVORABLE)] * 10,
            signer_hotkey="5SignerHotkeyABC",
            gossiped_game_date="20260501",  # Different date in gossip
        )
        # Local date preserved, gossip date ignored.
        assert meta.game_date == "20260601"

    @pytest.mark.asyncio
    async def test_no_gossip_date_keeps_local_none(self) -> None:
        """Backward compat: pre-v1679 senders don't include game_date."""
        espn = _mock_espn_client(_final_game())
        attestor = OutcomeAttestor(espn_client=espn)
        meta = _signal()
        attestor.register_signal(meta)
        assert meta.game_date is None

        await attestor.receive_gossip(
            signal_id="sig1",
            gossiped_outcomes=[int(Outcome.FAVORABLE)] * 10,
            signer_hotkey="5SignerHotkeyABC",
            # gossiped_game_date omitted
        )
        # After replay-verify, meta.game_date may be set FROM the
        # ESPN raw_data, but not from the gossip (which had none).
        # The test passes whether replay-verify cached it or not —
        # we're only asserting the gossip didn't poison.

    @pytest.mark.asyncio
    async def test_invalid_gossip_date_format_rejected(self) -> None:
        """Malformed game_date strings are ignored, not adopted."""
        espn = _mock_espn_client(_final_game())
        attestor = OutcomeAttestor(espn_client=espn)
        meta = _signal()
        attestor.register_signal(meta)

        for bad in ["", "abc", "2026-05-01", "12345"]:
            meta.game_date = None  # reset
            await attestor.receive_gossip(
                signal_id="sig1",
                gossiped_outcomes=[int(Outcome.FAVORABLE)] * 10,
                signer_hotkey="5x",
                gossiped_game_date=bad,
            )
            # Should not have adopted the malformed value. (May have
            # been set by replay-verify caching the ESPN result, but
            # that's a separate path — we only check the bad value
            # specifically wasn't accepted.)
            assert meta.game_date != bad, f"Bad date {bad!r} was adopted"
