"""Tests for djinn_validator.core.outcome_recovery."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from djinn_validator.api.server import create_app
from djinn_validator.core.outcome_recovery import recover_missing_outcomes
from djinn_validator.core.outcomes import Outcome, OutcomeAttestor, ParsedPick, SignalMetadata
from djinn_validator.core.purchase import PurchaseOrchestrator
from djinn_validator.core.shares import ShareStore


SIG = "test-recovery-1"


def _meta(signal_id: str = SIG, resolved: bool = False, outcomes: list[int] | None = None) -> SignalMetadata:
    return SignalMetadata(
        signal_id=signal_id,
        sport="baseball_mlb",
        event_id="401570001",
        home_team="Yankees",
        away_team="Red Sox",
        lines=[
            ParsedPick(market="h2h", team="Yankees"),
            ParsedPick(market="h2h", team="Red Sox"),
        ],
        resolved=resolved,
        outcomes=[Outcome(o) for o in outcomes] if outcomes else None,
    )


@pytest.fixture
def attestor():
    return OutcomeAttestor()


def _seal_response(meta: SignalMetadata) -> dict:
    line_strs = [
        json.dumps({"market": p.market, "team": p.team, "side": p.side, "line": p.line, "odds": p.odds})
        for p in meta.lines
    ]
    return {
        "signal_id": meta.signal_id,
        "sport": meta.sport,
        "event_id": meta.event_id,
        "home_team": meta.home_team,
        "away_team": meta.away_team,
        "lines": line_strs,
        "resolved": meta.resolved,
        "outcomes": [int(o) for o in (meta.outcomes or [])] if meta.resolved else None,
    }


@pytest.mark.asyncio
async def test_skip_already_resolved(attestor):
    attestor.register_signal(_meta(resolved=True, outcomes=[1, 0]))
    tally = await recover_missing_outcomes(
        signal_ids=[SIG],
        peer_validators=[{"url": "http://peer.example", "uid": 1}],
        outcome_attestor=attestor,
    )
    assert tally.get("skip_already_resolved") == 1
    assert tally.get("recovered", 0) == 0


@pytest.mark.asyncio
async def test_no_peer_returns_data(attestor, httpx_mock):
    attestor.register_signal(_meta(resolved=False))
    httpx_mock.add_response(
        url=f"http://peer-a.example/v1/outcomes/{SIG}",
        status_code=404,
    )
    httpx_mock.add_response(
        url=f"http://peer-b.example/v1/outcomes/{SIG}",
        status_code=404,
    )
    tally = await recover_missing_outcomes(
        signal_ids=[SIG],
        peer_validators=[
            {"url": "http://peer-a.example", "uid": 1},
            {"url": "http://peer-b.example", "uid": 2},
        ],
        outcome_attestor=attestor,
    )
    assert tally.get("no_peer_had_it") == 1
    assert tally.get("recovered", 0) == 0


@pytest.mark.asyncio
async def test_peer_returns_unresolved(attestor, httpx_mock):
    attestor.register_signal(_meta(resolved=False))
    body = _seal_response(_meta(resolved=False))
    httpx_mock.add_response(
        url=f"http://peer.example/v1/outcomes/{SIG}",
        json=body,
    )
    tally = await recover_missing_outcomes(
        signal_ids=[SIG],
        peer_validators=[{"url": "http://peer.example", "uid": 1}],
        outcome_attestor=attestor,
    )
    # Peer's response has resolved=False so the recovery loop continues
    # past it without marking recovered.
    assert tally.get("recovered", 0) == 0
    assert tally.get("no_peer_had_it") == 1


@pytest.mark.asyncio
async def test_replay_verify_calls_receive_gossip(attestor, httpx_mock):
    attestor.register_signal(_meta(resolved=False))
    body = _seal_response(_meta(resolved=True, outcomes=[1, 0]))

    # Stub receive_gossip to "accept" without hitting ESPN.
    received_calls: list[tuple] = []

    async def fake_receive(signal_id, gossiped_outcomes, signer_hotkey):
        received_calls.append((signal_id, list(gossiped_outcomes), signer_hotkey))
        return ("accepted", list(gossiped_outcomes))

    attestor.receive_gossip = fake_receive  # type: ignore[assignment]

    httpx_mock.add_response(
        url=f"http://peer.example/v1/outcomes/{SIG}",
        json=body,
    )
    tally = await recover_missing_outcomes(
        signal_ids=[SIG],
        peer_validators=[{"url": "http://peer.example", "uid": 7, "hotkey": "5xxx"}],
        outcome_attestor=attestor,
    )
    assert tally.get("recovered") == 1
    assert len(received_calls) == 1
    assert received_calls[0][0] == SIG
    assert received_calls[0][1] == [1, 0]
    # Peer hotkey is forwarded to receive_gossip for telemetry.
    assert received_calls[0][2] == "5xxx"


@pytest.mark.asyncio
async def test_replay_disputed_keeps_polling(attestor, httpx_mock):
    attestor.register_signal(_meta(resolved=False))

    states = iter([("disputed", None), ("accepted", [1, 0])])

    async def fake_receive(signal_id, gossiped_outcomes, signer_hotkey):
        return next(states)

    attestor.receive_gossip = fake_receive  # type: ignore[assignment]

    body_a = _seal_response(_meta(resolved=True, outcomes=[2, 2]))  # peer A claims
    body_b = _seal_response(_meta(resolved=True, outcomes=[1, 0]))
    httpx_mock.add_response(url=f"http://peer-a.example/v1/outcomes/{SIG}", json=body_a)
    httpx_mock.add_response(url=f"http://peer-b.example/v1/outcomes/{SIG}", json=body_b)

    tally = await recover_missing_outcomes(
        signal_ids=[SIG],
        peer_validators=[
            {"url": "http://peer-a.example", "uid": 1},
            {"url": "http://peer-b.example", "uid": 2},
        ],
        outcome_attestor=attestor,
    )
    assert tally.get("recovered") == 1
    assert tally.get("replay_disputed") == 1


@pytest.mark.asyncio
async def test_register_signal_when_unknown_locally(attestor, httpx_mock):
    # Don't register locally; recovery loop must register from peer's metadata.
    body = _seal_response(_meta(resolved=True, outcomes=[1, 0]))

    async def fake_receive(signal_id, gossiped_outcomes, signer_hotkey):
        return ("accepted", list(gossiped_outcomes))

    attestor.receive_gossip = fake_receive  # type: ignore[assignment]

    httpx_mock.add_response(url=f"http://peer.example/v1/outcomes/{SIG}", json=body)
    tally = await recover_missing_outcomes(
        signal_ids=[SIG],
        peer_validators=[{"url": "http://peer.example", "uid": 1}],
        outcome_attestor=attestor,
    )
    assert tally.get("recovered") == 1
    # Local registration happened.
    assert attestor.get_signal(SIG) is not None
    assert attestor.get_signal(SIG).event_id == "401570001"


@pytest.mark.asyncio
async def test_empty_inputs(attestor):
    assert await recover_missing_outcomes(
        signal_ids=[], peer_validators=[{"url": "http://peer.example", "uid": 1}], outcome_attestor=attestor
    ) == {}
    assert await recover_missing_outcomes(
        signal_ids=[SIG], peer_validators=[], outcome_attestor=attestor
    ) == {}


@pytest.mark.asyncio
async def test_v1703_peer_404_ticks_metric(attestor, httpx_mock):
    """v1703: 404 from peer ticks OUTCOME_RECOVERY_RESULT.peer_404."""
    from djinn_validator.api.metrics import OUTCOME_RECOVERY_RESULT

    attestor.register_signal(_meta(resolved=False))
    httpx_mock.add_response(
        url=f"http://peer-a.example/v1/outcomes/{SIG}",
        status_code=404,
    )
    before = OUTCOME_RECOVERY_RESULT.labels(outcome="peer_404")._value.get()
    await recover_missing_outcomes(
        signal_ids=[SIG],
        peer_validators=[{"url": "http://peer-a.example", "uid": 1}],
        outcome_attestor=attestor,
    )
    after = OUTCOME_RECOVERY_RESULT.labels(outcome="peer_404")._value.get()
    assert after == before + 1


@pytest.mark.asyncio
async def test_v1703_peer_unreachable_ticks_metric(attestor, httpx_mock):
    """v1703: httpx error ticks OUTCOME_RECOVERY_RESULT.peer_unreachable."""
    import httpx as _httpx
    from djinn_validator.api.metrics import OUTCOME_RECOVERY_RESULT

    attestor.register_signal(_meta(resolved=False))
    httpx_mock.add_exception(
        _httpx.ConnectTimeout("simulated peer down"),
        url=f"http://peer-a.example/v1/outcomes/{SIG}",
    )
    before = OUTCOME_RECOVERY_RESULT.labels(outcome="peer_unreachable")._value.get()
    await recover_missing_outcomes(
        signal_ids=[SIG],
        peer_validators=[{"url": "http://peer-a.example", "uid": 1}],
        outcome_attestor=attestor,
    )
    after = OUTCOME_RECOVERY_RESULT.labels(outcome="peer_unreachable")._value.get()
    assert after == before + 1


@pytest.mark.asyncio
async def test_v1703_recovered_ticks_metric(attestor, httpx_mock):
    """v1703: successful recovery ticks OUTCOME_RECOVERY_RESULT.recovered."""
    from djinn_validator.api.metrics import OUTCOME_RECOVERY_RESULT

    attestor.register_signal(_meta(resolved=False))

    async def fake_receive(signal_id, gossiped_outcomes, signer_hotkey):
        return ("accepted", list(gossiped_outcomes))

    attestor.receive_gossip = fake_receive  # type: ignore[assignment]

    body = _seal_response(_meta(resolved=True, outcomes=[1, 0]))
    httpx_mock.add_response(url=f"http://peer.example/v1/outcomes/{SIG}", json=body)
    before = OUTCOME_RECOVERY_RESULT.labels(outcome="recovered")._value.get()
    await recover_missing_outcomes(
        signal_ids=[SIG],
        peer_validators=[{"url": "http://peer.example", "uid": 1}],
        outcome_attestor=attestor,
    )
    after = OUTCOME_RECOVERY_RESULT.labels(outcome="recovered")._value.get()
    assert after == before + 1


# === Endpoint integration: GET /v1/outcomes/{signal_id} ===


@pytest.fixture
def server():
    store = ShareStore()
    purchase_orch = PurchaseOrchestrator(store)
    attestor = OutcomeAttestor()
    mock_chain = AsyncMock()
    mock_chain.is_connected = AsyncMock(return_value=True)
    mock_chain.is_paused = AsyncMock(return_value=False)
    app = create_app(store, purchase_orch, attestor, chain_client=mock_chain)
    yield TestClient(app), attestor
    store.close()


def test_get_outcome_404_when_unknown(server):
    client, _ = server
    resp = client.get(f"/v1/outcomes/{SIG}")
    assert resp.status_code == 404


def test_get_outcome_returns_unresolved_metadata(server):
    client, attestor = server
    attestor.register_signal(_meta(resolved=False))
    resp = client.get(f"/v1/outcomes/{SIG}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["signal_id"] == SIG
    assert body["resolved"] is False
    assert body["outcomes"] is None
    assert body["event_id"] == "401570001"
    assert isinstance(body["lines"], list)
    assert len(body["lines"]) == 2


def test_get_outcome_returns_resolved(server):
    client, attestor = server
    attestor.register_signal(_meta(resolved=True, outcomes=[1, 0]))
    resp = client.get(f"/v1/outcomes/{SIG}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["resolved"] is True
    assert body["outcomes"] == [1, 0]


class TestUnresolvedSignalIdComputation:
    """Regression for v1672 fix of v1671's unresolved-signal-ID bug.

    Pre-fix (v1671 19e4e610) at mpc_orchestrator.py:1614-1618:

        resolved_signals_set = set(getattr(audit_set, "resolved_signals", []) or [])
        all_signals = list(getattr(audit_set, "signals", {}) or {})
        unresolved = [sid for sid in all_signals if sid not in resolved_signals_set]

    Two compounding bugs:
    1. `set(list[AuditSignal])` raises TypeError because AuditSignal is a
       non-frozen @dataclass and unhashable.
    2. Even if hashable, `sid in <set of AuditSignal>` would always be False
       because we'd be comparing strings against AuditSignal objects.

    The bug was hidden by the v1671 NameError that crashed shadow_settle
    earlier in the same try-block. Once that NameError was fixed in v1672,
    THIS bug surfaced as the actual Layer 3 blocker.

    Fix uses an AuditSignal.signal_id set comprehension instead.
    """

    def test_unresolved_signal_ids_extracted_from_audit_set(self) -> None:
        from djinn_validator.core.audit_set import AuditSet, AuditSignal

        s = AuditSet(genius_address="0xg", idiot_address="0xi")
        s.signals["sig-A"] = AuditSignal(signal_id="sig-A")
        s.signals["sig-B"] = AuditSignal(
            signal_id="sig-B", outcomes=[1, 0, 1, 0, 1, 0, 1, 0, 1, 0]
        )
        s.signals["sig-C"] = AuditSignal(signal_id="sig-C")

        # Replicate the orchestrator's logic exactly (post-fix form).
        resolved_ids_set = {
            sig.signal_id for sig in (getattr(s, "resolved_signals", []) or [])
        }
        all_signals = list(getattr(s, "signals", {}) or {})
        unresolved = [sid for sid in all_signals if sid not in resolved_ids_set]

        # sig-B is the only one with outcomes (10 of them).
        assert resolved_ids_set == {"sig-B"}
        assert sorted(unresolved) == ["sig-A", "sig-C"]

    def test_set_of_audit_signals_raises_type_error(self) -> None:
        """Locks the underlying invariant: AuditSignal is unhashable.

        Any future refactor that makes AuditSignal hashable (e.g. by adding
        frozen=True to the @dataclass) needs to delete this test AND
        re-evaluate every set/dict-key call site that touches AuditSignal.
        """
        from djinn_validator.core.audit_set import AuditSignal

        a = AuditSignal(signal_id="x")
        with pytest.raises(TypeError, match="unhashable type"):
            set([a])
