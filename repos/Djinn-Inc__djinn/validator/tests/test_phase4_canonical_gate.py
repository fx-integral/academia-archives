"""v1747 Phase 4 — MPC orchestrator canonical-outcomes gate.

Verifies:
- ``build_purchase_inputs_from_audit_set`` accepts ``line_outcomes_override``
  and threads canonical outcomes into PurchaseInputs.
- ``MPCOrchestrator._read_canonical_line_outcomes`` reads from chain,
  honors honesty gate, abstains on RPC error / canonical pending /
  divergence.
- The gate is dormant when ``DJINN_FF_OUTCOME_REGISTRY_READ`` is unset
  (default off).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from unittest.mock import AsyncMock

import pytest

from djinn_validator.api.metrics import SHADOW_SETTLE_OUTCOME
from djinn_validator.chain.outcome_signer import LineKey, line_hash
from djinn_validator.core.audit_set import AuditSet, AuditSignal
from djinn_validator.core.mpc_batch_settlement import (
    PurchaseInputs,
    build_purchase_inputs_from_audit_set,
)
from djinn_validator.core.outcomes import (
    Outcome,
    OutcomeAttestor,
    ParsedPick,
    SignalMetadata,
)


def _outcome_metric(label: str) -> float:
    """Read a SHADOW_SETTLE_OUTCOME label's current count.

    Counters are process-global — capture before/after to assert deltas
    rather than absolute values, since other tests in the same run may
    have ticked the same labels.
    """
    return SHADOW_SETTLE_OUTCOME.labels(outcome=label)._value.get()


CHAIN_ID = 84532
REGISTRY = "0x000000000000000000000000000000000000C0DE"


# ---------------------------------------------------------------------------
# Fakes for share_store + purchase_odds_ledger
# ---------------------------------------------------------------------------


@dataclass
class _FakeShare:
    x: int = 1


@dataclass
class _FakeShareRecord:
    encrypted_index_share: bytes
    share: _FakeShare


class _FakeShareStore:
    def __init__(self, sigs: dict[str, _FakeShareRecord]) -> None:
        self._sigs = sigs

    def get(self, signal_id: str) -> _FakeShareRecord | None:
        return self._sigs.get(signal_id)


@dataclass
class _FakePurchaseOddsRecord:
    bpas: list[int]
    wpas: list[int]
    bpa_mode: str = "weighted"


class _FakePurchaseOddsLedger:
    def __init__(self, recs: dict[tuple[str, str], _FakePurchaseOddsRecord]) -> None:
        self._recs = recs

    def get(
        self, *, signal_id: str, buyer_address: str
    ) -> _FakePurchaseOddsRecord | None:
        return self._recs.get((signal_id, buyer_address))


def _make_audit_set_with_one_signal() -> AuditSet:
    aset = AuditSet(
        genius_address="0x" + "1" * 40,
        idiot_address="0x" + "2" * 40,
        cycle=0,
        version=2,
    )
    aset.signals["sig1"] = AuditSignal(
        signal_id="sig1",
        purchase_id=42,
        outcomes=[Outcome.FAVORABLE],  # single line
        notional=1_000_000,
        odds=2_000_000,
        sla_bps=10_000,
    )
    return aset


def _share_store_for(signal_id: str = "sig1") -> _FakeShareStore:
    return _FakeShareStore(
        {
            signal_id: _FakeShareRecord(
                encrypted_index_share=(1).to_bytes(32, "big"),
                share=_FakeShare(x=1),
            )
        }
    )


def _odds_ledger_for(
    signal_id: str = "sig1", idiot_address: str = "0x" + "2" * 40
) -> _FakePurchaseOddsLedger:
    return _FakePurchaseOddsLedger(
        {(signal_id, idiot_address): _FakePurchaseOddsRecord(bpas=[100], wpas=[100])}
    )


# ---------------------------------------------------------------------------
# build_purchase_inputs_from_audit_set with line_outcomes_override
# ---------------------------------------------------------------------------


class TestLineOutcomesOverride:
    def test_no_override_uses_local(self) -> None:
        aset = _make_audit_set_with_one_signal()
        batch = build_purchase_inputs_from_audit_set(
            aset,
            share_store=_share_store_for(),
            purchase_odds_ledger=_odds_ledger_for(),
        )
        assert batch is not None
        assert len(batch) == 1
        assert batch[0].outcomes == [int(Outcome.FAVORABLE)]

    def test_override_replaces_local(self) -> None:
        aset = _make_audit_set_with_one_signal()
        batch = build_purchase_inputs_from_audit_set(
            aset,
            share_store=_share_store_for(),
            purchase_odds_ledger=_odds_ledger_for(),
            line_outcomes_override={"sig1": [Outcome.UNFAVORABLE]},
        )
        assert batch is not None
        # Override wins
        assert batch[0].outcomes == [int(Outcome.UNFAVORABLE)]

    def test_override_length_mismatch_aborts_batch(self) -> None:
        aset = _make_audit_set_with_one_signal()
        batch = build_purchase_inputs_from_audit_set(
            aset,
            share_store=_share_store_for(),
            purchase_odds_ledger=_odds_ledger_for(),
            # Override has 2 entries; local has 1
            line_outcomes_override={"sig1": [Outcome.FAVORABLE, Outcome.VOID]},
        )
        assert batch is None

    def test_override_only_affects_signals_in_dict(self) -> None:
        """Signals NOT in override use their local outcomes."""
        aset = AuditSet(
            genius_address="0x" + "1" * 40,
            idiot_address="0x" + "2" * 40,
            cycle=0,
            version=2,
        )
        aset.signals["sig1"] = AuditSignal(
            signal_id="sig1",
            purchase_id=10,
            outcomes=[Outcome.FAVORABLE],
            notional=1_000_000,
            odds=2_000_000,
            sla_bps=10_000,
        )
        aset.signals["sig2"] = AuditSignal(
            signal_id="sig2",
            purchase_id=11,
            outcomes=[Outcome.UNFAVORABLE],
            notional=1_000_000,
            odds=2_000_000,
            sla_bps=10_000,
        )
        share_store = _FakeShareStore(
            {
                "sig1": _FakeShareRecord(
                    encrypted_index_share=(1).to_bytes(32, "big"),
                    share=_FakeShare(x=1),
                ),
                "sig2": _FakeShareRecord(
                    encrypted_index_share=(2).to_bytes(32, "big"),
                    share=_FakeShare(x=1),
                ),
            }
        )
        ledger = _FakePurchaseOddsLedger(
            {
                ("sig1", aset.idiot_address): _FakePurchaseOddsRecord(bpas=[100], wpas=[100]),
                ("sig2", aset.idiot_address): _FakePurchaseOddsRecord(bpas=[100], wpas=[100]),
            }
        )
        batch = build_purchase_inputs_from_audit_set(
            aset,
            share_store=share_store,
            purchase_odds_ledger=ledger,
            line_outcomes_override={"sig1": [Outcome.VOID]},
        )
        assert batch is not None
        # Sorted by purchase_id ascending
        outcomes_by_sid = {p.signal_id: p.outcomes for p in batch}
        assert outcomes_by_sid["sig1"] == [int(Outcome.VOID)]  # overridden
        assert outcomes_by_sid["sig2"] == [int(Outcome.UNFAVORABLE)]  # local


# ---------------------------------------------------------------------------
# MPCOrchestrator._read_canonical_line_outcomes
# ---------------------------------------------------------------------------


class _FakeChainClient:
    """Minimal chain client double for the canonical gate tests."""

    def __init__(
        self,
        canonical_outcomes: list[int] | None = None,
        chain_id: int = CHAIN_ID,
        registry_address: str = REGISTRY,
    ) -> None:
        self._canonical = canonical_outcomes
        self._chain_id = chain_id
        self._line_outcome_registry_address = registry_address
        self.batch_line_outcomes_calls: list[list[bytes]] = []

    async def batch_line_outcomes(
        self, line_hashes: list[bytes], confirmations: int = 2
    ) -> list[int] | None:
        self.batch_line_outcomes_calls.append(list(line_hashes))
        return self._canonical


def _make_orchestrator(
    *,
    chain_client: _FakeChainClient | None,
    outcome_attestor: OutcomeAttestor | None,
):
    """Build a minimally-instantiated orchestrator for the gate tests.

    We bypass __init__ to avoid wiring the full peer network. The gate
    method only depends on _chain_client + _outcome_attestor.
    """
    from djinn_validator.core.mpc_orchestrator import MPCOrchestrator

    orch = MPCOrchestrator.__new__(MPCOrchestrator)
    orch._chain_client = chain_client
    orch._outcome_attestor = outcome_attestor
    return orch


def _seed_attestor_with_signal(
    attestor: OutcomeAttestor,
    signal_id: str,
    sport: str = "basketball_nba",
    event_id: str = "401584293",
    home_team: str = "Lakers",
    away_team: str = "Celtics",
) -> SignalMetadata:
    meta = SignalMetadata(
        signal_id=signal_id,
        sport=sport,
        event_id=event_id,
        home_team=home_team,
        away_team=away_team,
        lines=[ParsedPick(market="spreads", team="Lakers", line=-3.5, odds=-110)],
    )
    attestor.register_signal(meta)
    return meta


def _aset_with_signal(signal_id: str, outcome: Outcome) -> AuditSet:
    aset = AuditSet(
        genius_address="0x" + "1" * 40,
        idiot_address="0x" + "2" * 40,
        cycle=0,
        version=2,
    )
    aset.signals[signal_id] = AuditSignal(
        signal_id=signal_id,
        purchase_id=42,
        outcomes=[outcome],
        notional=1_000_000,
        odds=2_000_000,
        sla_bps=10_000,
    )
    return aset


class TestReadCanonicalLineOutcomes:
    @pytest.mark.asyncio
    async def test_unconfigured_returns_none(self) -> None:
        """No chain_client + no attestor → abstain (unconfigured)."""
        orch = _make_orchestrator(chain_client=None, outcome_attestor=None)
        aset = _aset_with_signal("sig1", Outcome.FAVORABLE)
        result = await orch._read_canonical_line_outcomes(aset)
        assert result is None

    @pytest.mark.asyncio
    async def test_canonical_match_returns_override(self) -> None:
        attestor = OutcomeAttestor()
        _seed_attestor_with_signal(attestor, "sig1")
        chain_client = _FakeChainClient(canonical_outcomes=[int(Outcome.FAVORABLE)])
        orch = _make_orchestrator(chain_client=chain_client, outcome_attestor=attestor)

        aset = _aset_with_signal("sig1", Outcome.FAVORABLE)
        result = await orch._read_canonical_line_outcomes(aset)
        assert result is not None
        assert "sig1" in result
        assert result["sig1"] == [Outcome.FAVORABLE]
        # batch_line_outcomes was called with the lineHash for Lakers -3.5 spread
        assert len(chain_client.batch_line_outcomes_calls) == 1
        assert len(chain_client.batch_line_outcomes_calls[0]) == 1
        expected_lh = line_hash(
            LineKey(
                sport="basketball_nba",
                event_id="401584293",
                market="spread",
                side="home",
                line_value="-3.5",
            ),
            CHAIN_ID,
            REGISTRY,
        )
        assert chain_client.batch_line_outcomes_calls[0][0] == expected_lh

    @pytest.mark.asyncio
    async def test_rpc_error_returns_none(self) -> None:
        attestor = OutcomeAttestor()
        _seed_attestor_with_signal(attestor, "sig1")
        # canonical=None signals an RPC error per chain_client.batch_line_outcomes
        chain_client = _FakeChainClient(canonical_outcomes=None)
        orch = _make_orchestrator(chain_client=chain_client, outcome_attestor=attestor)
        aset = _aset_with_signal("sig1", Outcome.FAVORABLE)
        result = await orch._read_canonical_line_outcomes(aset)
        assert result is None

    @pytest.mark.asyncio
    async def test_canonical_pending_returns_none(self) -> None:
        """Any PENDING outcome on chain → abstain."""
        attestor = OutcomeAttestor()
        _seed_attestor_with_signal(attestor, "sig1")
        chain_client = _FakeChainClient(canonical_outcomes=[int(Outcome.PENDING)])
        orch = _make_orchestrator(chain_client=chain_client, outcome_attestor=attestor)
        aset = _aset_with_signal("sig1", Outcome.FAVORABLE)
        result = await orch._read_canonical_line_outcomes(aset)
        assert result is None

    @pytest.mark.asyncio
    async def test_local_diverges_from_canonical_returns_none(self) -> None:
        """HONESTY GATE: local FAVORABLE vs canonical UNFAVORABLE → abstain."""
        attestor = OutcomeAttestor()
        _seed_attestor_with_signal(attestor, "sig1")
        chain_client = _FakeChainClient(canonical_outcomes=[int(Outcome.UNFAVORABLE)])
        orch = _make_orchestrator(chain_client=chain_client, outcome_attestor=attestor)
        aset = _aset_with_signal("sig1", Outcome.FAVORABLE)  # local says FAVORABLE
        result = await orch._read_canonical_line_outcomes(aset)
        assert result is None

    @pytest.mark.asyncio
    async def test_unknown_signal_returns_none(self) -> None:
        """Outcome attestor missing meta for a signal → abstain."""
        attestor = OutcomeAttestor()  # no signals registered
        chain_client = _FakeChainClient(canonical_outcomes=[int(Outcome.FAVORABLE)])
        orch = _make_orchestrator(chain_client=chain_client, outcome_attestor=attestor)
        aset = _aset_with_signal("sig1", Outcome.FAVORABLE)
        result = await orch._read_canonical_line_outcomes(aset)
        assert result is None

    @pytest.mark.asyncio
    async def test_unparseable_line_skips_signal_only(self) -> None:
        """v1763: ParsedPick that can't build LineKey → skip signal, not whole audit.

        parsed_pick_to_line_key's docstring says callers should fall back
        to legacy ``determine_outcome`` for unparseable picks. The flag-gated
        canonical-read implements that by omitting the signal from the
        override dict — build_purchase_inputs_from_audit_set then uses the
        signal's local outcomes naturally.
        """
        attestor = OutcomeAttestor()
        meta = SignalMetadata(
            signal_id="sig1",
            sport="basketball_nba",
            event_id="401584293",
            home_team="Lakers",
            away_team="Celtics",
            # 76ers matches neither team
            lines=[ParsedPick(market="spreads", team="76ers", line=-3.5, odds=-110)],
        )
        attestor.register_signal(meta)
        chain_client = _FakeChainClient(canonical_outcomes=[])
        orch = _make_orchestrator(chain_client=chain_client, outcome_attestor=attestor)
        aset = _aset_with_signal("sig1", Outcome.FAVORABLE)
        result = await orch._read_canonical_line_outcomes(aset)
        # Empty dict (not None) — caller falls through to local outcomes.
        assert result == {}
        # No chain reads happened — there were no parseable lines to query.
        assert chain_client.batch_line_outcomes_calls == []

    @pytest.mark.asyncio
    async def test_partial_unparseable_keeps_other_signals(self) -> None:
        """v1763: one unparseable signal in a 2-signal audit → only the
        parseable signal goes through canonical read; the unparseable falls
        through to local."""
        attestor = OutcomeAttestor()
        # sig1: parseable Lakers pick
        attestor.register_signal(
            SignalMetadata(
                signal_id="sig1",
                sport="basketball_nba",
                event_id="401584293",
                home_team="Lakers",
                away_team="Celtics",
                lines=[ParsedPick(market="spreads", team="Lakers", line=-3.5, odds=-110)],
            )
        )
        # sig2: unparseable team mismatch
        attestor.register_signal(
            SignalMetadata(
                signal_id="sig2",
                sport="basketball_nba",
                event_id="401584294",
                home_team="Lakers",
                away_team="Celtics",
                lines=[ParsedPick(market="spreads", team="76ers", line=-3.5, odds=-110)],
            )
        )
        # Only one chain query expected: the parseable sig1's line.
        chain_client = _FakeChainClient(canonical_outcomes=[int(Outcome.FAVORABLE)])
        orch = _make_orchestrator(chain_client=chain_client, outcome_attestor=attestor)

        aset = AuditSet(
            genius_address="0x" + "1" * 40,
            idiot_address="0x" + "2" * 40,
            cycle=0,
            version=2,
        )
        aset.signals["sig1"] = AuditSignal(
            signal_id="sig1",
            purchase_id=1,
            outcomes=[Outcome.FAVORABLE],
            notional=1_000_000,
            odds=2_000_000,
            sla_bps=10_000,
        )
        aset.signals["sig2"] = AuditSignal(
            signal_id="sig2",
            purchase_id=2,
            outcomes=[Outcome.UNFAVORABLE],
            notional=1_000_000,
            odds=2_000_000,
            sla_bps=10_000,
        )
        result = await orch._read_canonical_line_outcomes(aset)
        assert result is not None
        assert "sig1" in result
        assert result["sig1"] == [Outcome.FAVORABLE]
        assert "sig2" not in result  # falls through to local
        # Only sig1's hash was queried.
        assert len(chain_client.batch_line_outcomes_calls) == 1
        assert len(chain_client.batch_line_outcomes_calls[0]) == 1

    @pytest.mark.asyncio
    async def test_partial_unparseable_still_honors_divergence_gate(self) -> None:
        """v1763: per-signal skip must NOT bypass the honesty gate for
        signals we DO read canonically.

        Pins on the SPECIFIC abstain reason, not just `result is None`.
        Without the metric assertion, this test would still pass under a
        regression that re-aborts the whole audit on unparseable (returns
        None for the wrong reason).
        """
        attestor = OutcomeAttestor()
        attestor.register_signal(
            SignalMetadata(
                signal_id="sig_parse",
                sport="basketball_nba",
                event_id="401584293",
                home_team="Lakers",
                away_team="Celtics",
                lines=[ParsedPick(market="spreads", team="Lakers", line=-3.5, odds=-110)],
            )
        )
        attestor.register_signal(
            SignalMetadata(
                signal_id="sig_unparse",
                sport="basketball_nba",
                event_id="401584294",
                home_team="Lakers",
                away_team="Celtics",
                lines=[ParsedPick(market="spreads", team="76ers", line=-3.5, odds=-110)],
            )
        )
        # Canonical UNFAVORABLE, local FAVORABLE on sig_parse → divergence.
        chain_client = _FakeChainClient(canonical_outcomes=[int(Outcome.UNFAVORABLE)])
        orch = _make_orchestrator(chain_client=chain_client, outcome_attestor=attestor)

        aset = AuditSet(
            genius_address="0x" + "1" * 40,
            idiot_address="0x" + "2" * 40,
            cycle=0,
            version=2,
        )
        aset.signals["sig_parse"] = AuditSignal(
            signal_id="sig_parse",
            purchase_id=1,
            outcomes=[Outcome.FAVORABLE],
            notional=1_000_000,
            odds=2_000_000,
            sla_bps=10_000,
        )
        aset.signals["sig_unparse"] = AuditSignal(
            signal_id="sig_unparse",
            purchase_id=2,
            outcomes=[Outcome.UNFAVORABLE],
            notional=1_000_000,
            odds=2_000_000,
            sla_bps=10_000,
        )

        before_div = _outcome_metric("abstain_local_divergence")
        before_unp = _outcome_metric("abstain_canonical_unparseable_line")
        result = await orch._read_canonical_line_outcomes(aset)
        after_div = _outcome_metric("abstain_local_divergence")
        after_unp = _outcome_metric("abstain_canonical_unparseable_line")

        # Whole audit aborts — even though sig_unparse would skip, sig_parse
        # diverges from canonical and the honesty gate must fire.
        assert result is None
        # The honesty gate is the ACTUAL reason for the abort. If a future
        # regression made unparseable abort the whole audit again, this
        # delta would be 0 (we'd never reach the divergence check).
        assert after_div - before_div == 1, (
            "honesty gate must fire on local-vs-canonical divergence; "
            "got the right None for the wrong reason"
        )
        # And sig_unparse contributed its tick (proving skip-vs-abort still
        # took the skip path, which is the precondition for reaching the
        # honesty gate at all).
        assert after_unp - before_unp == 1

    @pytest.mark.asyncio
    async def test_empty_audit_set_returns_empty_dict(self) -> None:
        attestor = OutcomeAttestor()
        chain_client = _FakeChainClient(canonical_outcomes=[])
        orch = _make_orchestrator(chain_client=chain_client, outcome_attestor=attestor)
        aset = AuditSet(
            genius_address="0x" + "1" * 40,
            idiot_address="0x" + "2" * 40,
            cycle=0,
            version=2,
        )
        # No resolved signals
        result = await orch._read_canonical_line_outcomes(aset)
        assert result == {}


class TestFeatureFlagDormantByDefault:
    """When DJINN_FF_OUTCOME_REGISTRY_READ is unset, the gate is dormant."""

    def test_flag_default_off(self, monkeypatch) -> None:
        monkeypatch.delenv("DJINN_FF_OUTCOME_REGISTRY_READ", raising=False)
        # Flag check: only when "1" does the read fire
        assert os.environ.get("DJINN_FF_OUTCOME_REGISTRY_READ", "0") != "1"

    def test_flag_explicit_on(self, monkeypatch) -> None:
        monkeypatch.setenv("DJINN_FF_OUTCOME_REGISTRY_READ", "1")
        assert os.environ.get("DJINN_FF_OUTCOME_REGISTRY_READ", "0") == "1"


class TestChainIdAndRegistryHelpers:
    def test_chain_id_from_chain_client(self) -> None:
        chain_client = _FakeChainClient(chain_id=8453)
        orch = _make_orchestrator(chain_client=chain_client, outcome_attestor=None)
        assert orch._chain_id_for_line_registry() == 8453

    def test_chain_id_falls_back_to_env(self, monkeypatch) -> None:
        monkeypatch.setenv("BASE_CHAIN_ID", "84532")
        orch = _make_orchestrator(chain_client=None, outcome_attestor=None)
        assert orch._chain_id_for_line_registry() == 84532

    def test_registry_address_from_chain_client(self) -> None:
        chain_client = _FakeChainClient(registry_address=REGISTRY)
        orch = _make_orchestrator(chain_client=chain_client, outcome_attestor=None)
        assert orch._line_registry_address() == REGISTRY

    def test_registry_address_falls_back_to_env(self, monkeypatch) -> None:
        monkeypatch.setenv("LINE_OUTCOME_REGISTRY_ADDRESS", REGISTRY)
        orch = _make_orchestrator(chain_client=None, outcome_attestor=None)
        assert orch._line_registry_address() == REGISTRY
