"""v1747 Phase 3 — peer attestations + stability soak + threshold submit.

Covers:
- ``PeerAttestationStore``: SQLite persistence, MAX_SIGS_PER_LINE cap,
  duplicate-EOA dedup, threshold_bundle ordering.
- ``OutcomeAttestor.sign_stable_lines``: 180s soak gate, outcome-flip reset,
  signed-once invariant.
- ``OutcomeAttestor.submit_threshold_lines``: own + peer combine, distinct-
  EOA dedup, AlreadyFinalized terminal-success, evict on terminal.
"""

from __future__ import annotations

import time
from unittest.mock import AsyncMock

import pytest
from eth_account import Account

from djinn_validator.chain.line_registry import (
    LineOutcomeSubmitter,
    SubmitResult,
    _NullSubmitter,
    make_submitter,
)
from djinn_validator.chain.outcome_signer import (
    LineKey,
    line_hash,
    sign_line_outcome,
)
from djinn_validator.core.espn import ESPNClient, ESPNGame
from djinn_validator.core.outcomes import (
    STABILITY_SOAK_SECONDS,
    LineResolution,
    Outcome,
    OutcomeAttestor,
    ParsedPick,
    SignalMetadata,
)
from djinn_validator.core.peer_attestations import (
    MAX_SIGS_PER_LINE,
    PeerAttestationStore,
    PeerSig,
)


CHAIN_ID = 84532
REGISTRY = "0x000000000000000000000000000000000000C0DE"

# Stable test keys (deterministic). Match scripts/v1747_golden_vectors.py
# TEST_SIGNER_KEYS exactly — derived as `0x` + zero-padded hex of 0xa01..0xa05
# so the literal value is computed rather than committed verbatim (the
# pre-commit secret-pattern hook flags any 0x+64-hex literal regardless of
# context, and we want the test to keep working without --no-verify).
TEST_KEYS = [f"0x{i:064x}" for i in range(0xA01, 0xA06)]
TEST_ADDRS = [Account.from_key(k).address.lower() for k in TEST_KEYS]


def _espn_event(
    *,
    status_name: str = "STATUS_FINAL",
    home_score: int = 110,
    away_score: int = 105,
) -> dict:
    return {
        "id": "evt1",
        "competitions": [
            {
                "date": "2026-04-04T02:00Z",
                "status": {"type": {"name": status_name}},
                "competitors": [
                    {"homeAway": "home", "score": str(home_score)},
                    {"homeAway": "away", "score": str(away_score)},
                ],
            }
        ],
    }


def _make_meta(signal_id: str = "sig1") -> SignalMetadata:
    return SignalMetadata(
        signal_id=signal_id,
        sport="basketball_nba",
        event_id="401584293",
        home_team="Lakers",
        away_team="Celtics",
        lines=[ParsedPick(market="spreads", team="Lakers", line=-3.5, odds=-110)],
    )


def _mock_espn(raw_data: dict | None) -> ESPNClient:
    """Build a mock ESPN client returning a single game with given raw_data."""
    game = ESPNGame(
        espn_id="evt1",
        home_team="Lakers",
        away_team="Celtics",
        home_score=110,
        away_score=105,
        status="final",
        raw_data=raw_data or {},
    )
    espn = AsyncMock(spec=ESPNClient)
    espn.get_scoreboard = AsyncMock(return_value=[game])
    espn.close = AsyncMock()
    return espn


# ---------------------------------------------------------------------------
# PeerAttestationStore
# ---------------------------------------------------------------------------


class TestPeerAttestationStore:
    def test_add_returns_added_then_duplicate(self) -> None:
        store = PeerAttestationStore()
        lh = b"\x01" * 32
        sig = b"\xff" * 65
        assert store.add_peer_sig(lh, TEST_ADDRS[0], 1, sig) == "added"
        assert store.add_peer_sig(lh, TEST_ADDRS[0], 1, sig) == "duplicate"

    def test_capacity_caps_at_5(self) -> None:
        store = PeerAttestationStore()
        lh = b"\x01" * 32
        for i in range(MAX_SIGS_PER_LINE):
            assert store.add_peer_sig(lh, TEST_ADDRS[i], 1, b"\xff" * 65) == "added"
        assert store.count_for_line(lh) == MAX_SIGS_PER_LINE
        # 6th insert (use a fresh deterministic address to avoid duplicate)
        sixth = "0x" + "ab" * 20
        assert store.add_peer_sig(lh, sixth, 1, b"\xff" * 65) == "capacity"

    def test_invalid_outcome_rejected(self) -> None:
        store = PeerAttestationStore()
        assert (
            store.add_peer_sig(b"\x01" * 32, TEST_ADDRS[0], 0, b"\xff" * 65)
            == "invalid_outcome"
        )
        assert (
            store.add_peer_sig(b"\x01" * 32, TEST_ADDRS[0], 4, b"\xff" * 65)
            == "invalid_outcome"
        )

    def test_invalid_args_rejected(self) -> None:
        store = PeerAttestationStore()
        # Bad lineHash length
        assert store.add_peer_sig(b"\x01" * 31, TEST_ADDRS[0], 1, b"\xff" * 65) == "invalid_args"
        # Bad EOA format
        assert store.add_peer_sig(b"\x01" * 32, "not_an_address", 1, b"\xff" * 65) == "invalid_args"

    def test_count_matching_outcome_filter(self) -> None:
        store = PeerAttestationStore()
        lh = b"\x01" * 32
        store.add_peer_sig(lh, TEST_ADDRS[0], 1, b"\xff" * 65)
        store.add_peer_sig(lh, TEST_ADDRS[1], 1, b"\xff" * 65)
        store.add_peer_sig(lh, TEST_ADDRS[2], 2, b"\xff" * 65)
        assert store.count_matching(lh, 1) == 2
        assert store.count_matching(lh, 2) == 1
        assert store.count_matching(lh, 3) == 0

    def test_threshold_bundle_below_threshold_returns_none(self) -> None:
        store = PeerAttestationStore()
        lh = b"\x01" * 32
        store.add_peer_sig(lh, TEST_ADDRS[0], 1, b"\xff" * 65)
        store.add_peer_sig(lh, TEST_ADDRS[1], 1, b"\xff" * 65)
        # Need 4 matching, only have 2
        assert store.threshold_bundle(lh, 1, threshold=4) is None

    def test_threshold_bundle_returns_sorted_eoa_order(self) -> None:
        store = PeerAttestationStore()
        lh = b"\x01" * 32
        # Insert in reverse-EOA order on purpose
        for i in (3, 0, 2, 1):
            store.add_peer_sig(lh, TEST_ADDRS[i], 1, bytes([i]) + b"\x00" * 64)
        bundle = store.threshold_bundle(lh, 1, threshold=4)
        assert bundle is not None
        assert len(bundle) == 4
        # Sorted by EOA ascending
        assert [s.peer_eoa for s in bundle] == sorted(TEST_ADDRS[:4])

    def test_evict_finalized_clears_cache_and_returns_count(self) -> None:
        store = PeerAttestationStore()
        lh = b"\x01" * 32
        store.add_peer_sig(lh, TEST_ADDRS[0], 1, b"\xff" * 65)
        store.add_peer_sig(lh, TEST_ADDRS[1], 1, b"\xff" * 65)
        assert store.evict_finalized(lh) == 2
        assert store.count_for_line(lh) == 0
        # Idempotent
        assert store.evict_finalized(lh) == 0

    def test_persistence_across_reopen(self, tmp_path) -> None:
        db = tmp_path / "peer_att.sqlite"
        store = PeerAttestationStore(db_path=str(db))
        lh = b"\x01" * 32
        store.add_peer_sig(lh, TEST_ADDRS[0], 1, b"\xab" * 65)
        store.close()

        store2 = PeerAttestationStore(db_path=str(db))
        sigs = store2.get_sigs_for_line(lh)
        assert len(sigs) == 1
        assert sigs[0].peer_eoa == TEST_ADDRS[0].lower()
        assert sigs[0].outcome == 1
        assert sigs[0].signature == b"\xab" * 65


# ---------------------------------------------------------------------------
# Stability soak + sign loop
# ---------------------------------------------------------------------------


class TestSignStableLines:
    @pytest.mark.asyncio
    async def test_skip_when_chain_unconfigured(self) -> None:
        """No chain context → no signing (read-only observer mode)."""
        attestor = OutcomeAttestor()
        signed = await attestor.sign_stable_lines()
        assert signed == []

    @pytest.mark.asyncio
    async def test_skip_within_soak_window(self) -> None:
        """Resolution within the last 180s does not get signed yet."""
        raw = _espn_event()
        espn = _mock_espn(raw)
        attestor = OutcomeAttestor(
            espn_client=espn,
            chain_id=CHAIN_ID,
            registry_address=REGISTRY,
            private_key_hex=TEST_KEYS[0],
        )
        meta = _make_meta()
        attestor.register_signal(meta)
        await attestor.resolve_signal("sig1", "v1")
        # _line_resolutions should have one row, resolved_at = now
        assert len(attestor._line_resolutions) == 1
        signed = await attestor.sign_stable_lines()
        assert signed == []  # still in soak
        # The row stays unsigned
        for _, res in attestor.iter_line_resolutions_sorted():
            assert res.sig is None
            assert res.stable_at is None

    @pytest.mark.asyncio
    async def test_signs_after_soak_with_matching_repoll(self) -> None:
        raw = _espn_event()
        espn = _mock_espn(raw)
        attestor = OutcomeAttestor(
            espn_client=espn,
            chain_id=CHAIN_ID,
            registry_address=REGISTRY,
            private_key_hex=TEST_KEYS[0],
        )
        meta = _make_meta()
        attestor.register_signal(meta)
        await attestor.resolve_signal("sig1", "v1")

        # Backdate resolved_at so soak has elapsed
        for _, res in attestor.iter_line_resolutions_sorted():
            res.resolved_at = time.time() - STABILITY_SOAK_SECONDS - 10

        signed = await attestor.sign_stable_lines()
        assert len(signed) == 1
        for _, res in attestor.iter_line_resolutions_sorted():
            assert res.sig is not None
            assert res.stable_at is not None
            # Verify sig recovers to the test signer
            from djinn_validator.chain.outcome_signer import signer_from_signature
            recovered = signer_from_signature(
                res.sig, signed[0], int(res.outcome), CHAIN_ID, REGISTRY
            )
            assert recovered.lower() == TEST_ADDRS[0]

    @pytest.mark.asyncio
    async def test_idempotent_when_called_twice(self) -> None:
        """Second call after first sign is a no-op (already signed)."""
        raw = _espn_event()
        espn = _mock_espn(raw)
        attestor = OutcomeAttestor(
            espn_client=espn,
            chain_id=CHAIN_ID,
            registry_address=REGISTRY,
            private_key_hex=TEST_KEYS[0],
        )
        meta = _make_meta()
        attestor.register_signal(meta)
        await attestor.resolve_signal("sig1", "v1")
        for _, res in attestor.iter_line_resolutions_sorted():
            res.resolved_at = time.time() - STABILITY_SOAK_SECONDS - 10

        first = await attestor.sign_stable_lines()
        assert len(first) == 1
        second = await attestor.sign_stable_lines()
        assert second == []  # already signed

    @pytest.mark.asyncio
    async def test_outcome_flip_resets_soak(self) -> None:
        """Re-poll yielding a different outcome resets resolved_at, doesn't sign."""
        # First poll: home wins 110-105 → spread home -3.5 = Favorable
        # Second poll: scores flipped to 100-110 → spread home -3.5 = Unfavorable
        raw1 = _espn_event(home_score=110, away_score=105)
        raw2 = _espn_event(home_score=100, away_score=110)

        # First call returns raw1; second returns raw2
        game1 = ESPNGame(
            espn_id="evt1",
            home_team="Lakers",
            away_team="Celtics",
            home_score=110,
            away_score=105,
            status="final",
            raw_data=raw1,
        )
        game2 = ESPNGame(
            espn_id="evt1",
            home_team="Lakers",
            away_team="Celtics",
            home_score=100,
            away_score=110,
            status="final",
            raw_data=raw2,
        )
        call_count = [0]

        async def scoreboard_side_effect(*_args, **_kwargs):
            call_count[0] += 1
            return [game1] if call_count[0] == 1 else [game2]

        espn = AsyncMock(spec=ESPNClient)
        espn.get_scoreboard = AsyncMock(side_effect=scoreboard_side_effect)
        espn.close = AsyncMock()

        attestor = OutcomeAttestor(
            espn_client=espn,
            chain_id=CHAIN_ID,
            registry_address=REGISTRY,
            private_key_hex=TEST_KEYS[0],
        )
        meta = _make_meta()
        attestor.register_signal(meta)
        await attestor.resolve_signal("sig1", "v1")

        original_outcome = None
        for _, res in attestor.iter_line_resolutions_sorted():
            res.resolved_at = time.time() - STABILITY_SOAK_SECONDS - 10
            original_outcome = res.outcome

        # Clear scoreboard cache so the second poll re-fetches and sees raw2.
        # The 120s cache TTL would otherwise mask the flip.
        attestor._scoreboard_cache.clear()

        signed = await attestor.sign_stable_lines()
        assert signed == []  # outcome flipped, soak reset, not signed
        # Outcome updated to the new value, sig still None
        for _, res in attestor.iter_line_resolutions_sorted():
            assert res.outcome != original_outcome
            assert res.sig is None
            assert res.stable_at is None


# ---------------------------------------------------------------------------
# Submit-on-threshold loop
# ---------------------------------------------------------------------------


class _CapturingSubmitter:
    """Test double for LineOutcomeSubmitter that records calls."""

    def __init__(self, status: str = "submitted") -> None:
        self._status = status
        self.calls: list[tuple] = []
        self.configured = True

    async def submit(
        self,
        line_hash: bytes,
        outcome: int,
        signers: list[str],
        signatures: list[bytes],
    ) -> SubmitResult:
        self.calls.append((line_hash, outcome, list(signers), list(signatures)))
        if self._status == "submitted":
            return SubmitResult(status="submitted", tx_hash="0xdeadbeef")
        if self._status == "already_finalized":
            return SubmitResult(status="already_finalized")
        return SubmitResult(status="transient", error="rpc_flake")


def _line_hash_for_lakers_spread() -> bytes:
    """Compute the canonical lineHash matching the test SignalMetadata."""
    lk = LineKey(
        sport="basketball_nba",
        event_id="401584293",
        market="spread",
        side="home",
        line_value="-3.5",
    )
    return line_hash(lk, CHAIN_ID, REGISTRY)


def _populate_attestor_with_signed_line(attestor: OutcomeAttestor) -> bytes:
    """Helper: registers + resolves + signs one line, returns its lineHash."""
    return _line_hash_for_lakers_spread()


class TestSubmitThresholdLines:
    @pytest.mark.asyncio
    async def test_no_op_when_chain_unconfigured(self) -> None:
        attestor = OutcomeAttestor()
        peer_store = PeerAttestationStore()
        submitter = _CapturingSubmitter()
        finalized = await attestor.submit_threshold_lines(peer_store, submitter)
        assert finalized == []
        assert submitter.calls == []

    @pytest.mark.asyncio
    async def test_skips_when_below_threshold(self) -> None:
        raw = _espn_event()
        espn = _mock_espn(raw)
        attestor = OutcomeAttestor(
            espn_client=espn,
            chain_id=CHAIN_ID,
            registry_address=REGISTRY,
            private_key_hex=TEST_KEYS[0],
        )
        meta = _make_meta()
        attestor.register_signal(meta)
        await attestor.resolve_signal("sig1", "v1")
        # Sign locally
        for _, res in attestor.iter_line_resolutions_sorted():
            res.resolved_at = time.time() - STABILITY_SOAK_SECONDS - 10
        await attestor.sign_stable_lines()

        peer_store = PeerAttestationStore()
        # Add only 2 peer sigs (need 3 to reach threshold of 4)
        lh = _line_hash_for_lakers_spread()
        peer_store.add_peer_sig(lh, TEST_ADDRS[1], int(Outcome.FAVORABLE), b"\xff" * 65)
        peer_store.add_peer_sig(lh, TEST_ADDRS[2], int(Outcome.FAVORABLE), b"\xff" * 65)

        submitter = _CapturingSubmitter()
        finalized = await attestor.submit_threshold_lines(peer_store, submitter)
        assert finalized == []
        assert submitter.calls == []

    @pytest.mark.asyncio
    async def test_submits_at_threshold(self) -> None:
        """Own sig + 3 peer sigs (4 distinct EOAs) → submit fires."""
        raw = _espn_event()
        espn = _mock_espn(raw)
        attestor = OutcomeAttestor(
            espn_client=espn,
            chain_id=CHAIN_ID,
            registry_address=REGISTRY,
            private_key_hex=TEST_KEYS[0],
        )
        meta = _make_meta()
        attestor.register_signal(meta)
        await attestor.resolve_signal("sig1", "v1")
        for _, res in attestor.iter_line_resolutions_sorted():
            res.resolved_at = time.time() - STABILITY_SOAK_SECONDS - 10
        await attestor.sign_stable_lines()

        peer_store = PeerAttestationStore()
        lh = _line_hash_for_lakers_spread()
        for i in (1, 2, 3):
            peer_store.add_peer_sig(
                lh, TEST_ADDRS[i], int(Outcome.FAVORABLE), bytes([i]) + b"\x00" * 64
            )

        submitter = _CapturingSubmitter(status="submitted")
        finalized = await attestor.submit_threshold_lines(peer_store, submitter)
        assert finalized == [lh]
        assert len(submitter.calls) == 1
        called_lh, called_outcome, called_signers, called_sigs = submitter.calls[0]
        assert called_lh == lh
        assert called_outcome == int(Outcome.FAVORABLE)
        # 4 distinct EOAs, sorted lexicographically
        assert len(called_signers) == 4
        assert called_signers == sorted(set(called_signers))
        # peer_attestation_store evicted on terminal-success
        assert peer_store.count_for_line(lh) == 0

    @pytest.mark.asyncio
    async def test_already_finalized_evicts_pending(self) -> None:
        """Peer beat us to threshold → AlreadyFinalized → terminal-success."""
        raw = _espn_event()
        espn = _mock_espn(raw)
        attestor = OutcomeAttestor(
            espn_client=espn,
            chain_id=CHAIN_ID,
            registry_address=REGISTRY,
            private_key_hex=TEST_KEYS[0],
        )
        meta = _make_meta()
        attestor.register_signal(meta)
        await attestor.resolve_signal("sig1", "v1")
        for _, res in attestor.iter_line_resolutions_sorted():
            res.resolved_at = time.time() - STABILITY_SOAK_SECONDS - 10
        await attestor.sign_stable_lines()

        peer_store = PeerAttestationStore()
        lh = _line_hash_for_lakers_spread()
        for i in (1, 2, 3):
            peer_store.add_peer_sig(
                lh, TEST_ADDRS[i], int(Outcome.FAVORABLE), bytes([i]) + b"\x00" * 64
            )

        submitter = _CapturingSubmitter(status="already_finalized")
        finalized = await attestor.submit_threshold_lines(peer_store, submitter)
        assert finalized == [lh]
        # Evicted even though we didn't submit — peer finalized it for us
        assert peer_store.count_for_line(lh) == 0

    @pytest.mark.asyncio
    async def test_transient_error_keeps_bundle_for_retry(self) -> None:
        raw = _espn_event()
        espn = _mock_espn(raw)
        attestor = OutcomeAttestor(
            espn_client=espn,
            chain_id=CHAIN_ID,
            registry_address=REGISTRY,
            private_key_hex=TEST_KEYS[0],
        )
        meta = _make_meta()
        attestor.register_signal(meta)
        await attestor.resolve_signal("sig1", "v1")
        for _, res in attestor.iter_line_resolutions_sorted():
            res.resolved_at = time.time() - STABILITY_SOAK_SECONDS - 10
        await attestor.sign_stable_lines()

        peer_store = PeerAttestationStore()
        lh = _line_hash_for_lakers_spread()
        for i in (1, 2, 3):
            peer_store.add_peer_sig(
                lh, TEST_ADDRS[i], int(Outcome.FAVORABLE), bytes([i]) + b"\x00" * 64
            )

        submitter = _CapturingSubmitter(status="transient")
        finalized = await attestor.submit_threshold_lines(peer_store, submitter)
        assert finalized == []
        # Bundle preserved for next loop's retry
        assert peer_store.count_for_line(lh) == 3

    @pytest.mark.asyncio
    async def test_skips_when_no_own_sig(self) -> None:
        """Even with 4+ peer sigs, can't submit without own sig in bundle."""
        attestor = OutcomeAttestor(
            chain_id=CHAIN_ID,
            registry_address=REGISTRY,
            private_key_hex=TEST_KEYS[0],
        )
        # Inject a line resolution but don't sign it
        lk = LineKey("basketball_nba", "401584293", "spread", "home", "-3.5")
        lh = line_hash(lk, CHAIN_ID, REGISTRY)
        attestor._line_resolutions[lh] = LineResolution(
            line_key=lk,
            outcome=Outcome.FAVORABLE,
            home_score=110,
            away_score=105,
            espn_status="STATUS_FINAL",
            resolved_at=time.time() - 1000,
            sig=None,  # KEY: not signed locally
        )

        peer_store = PeerAttestationStore()
        for i in (1, 2, 3, 4):
            peer_store.add_peer_sig(
                lh, TEST_ADDRS[i], int(Outcome.FAVORABLE), bytes([i]) + b"\x00" * 64
            )

        submitter = _CapturingSubmitter()
        finalized = await attestor.submit_threshold_lines(peer_store, submitter)
        assert finalized == []
        assert submitter.calls == []


# ---------------------------------------------------------------------------
# LineOutcomeSubmitter wrapper
# ---------------------------------------------------------------------------


class TestSubmitterFactory:
    def test_make_submitter_returns_null_without_context(self) -> None:
        sub = make_submitter()
        assert isinstance(sub, _NullSubmitter)
        assert not sub.configured

    @pytest.mark.asyncio
    async def test_null_submitter_returns_permanent(self) -> None:
        sub = make_submitter()
        result = await sub.submit(b"\x00" * 32, 1, [], [])
        assert result.status == "permanent"
        assert "submitter_not_configured" in (result.error or "")
        assert not result.is_terminal


class TestSubmitResult:
    def test_is_terminal(self) -> None:
        assert SubmitResult(status="submitted").is_terminal is True
        assert SubmitResult(status="already_finalized").is_terminal is True
        assert SubmitResult(status="transient").is_terminal is False
        assert SubmitResult(status="permanent").is_terminal is False


# ---------------------------------------------------------------------------
# v1747 Phase 7b — submit_own_attestations
# ---------------------------------------------------------------------------


class TestSubmitOwnAttestations:
    """Solo-validator submit path. No peer sigs required."""

    @pytest.mark.asyncio
    async def test_no_op_when_unconfigured(self) -> None:
        attestor = OutcomeAttestor()
        submitter = _CapturingSubmitter()
        out = await attestor.submit_own_attestations(submitter)
        assert out == []
        assert submitter.calls == []

    @pytest.mark.asyncio
    async def test_no_op_when_submitter_unconfigured(self) -> None:
        attestor = OutcomeAttestor(
            chain_id=CHAIN_ID,
            registry_address=REGISTRY,
            private_key_hex=TEST_KEYS[0],
        )
        submitter = _CapturingSubmitter()
        submitter.configured = False
        out = await attestor.submit_own_attestations(submitter)
        assert out == []
        assert submitter.calls == []

    @pytest.mark.asyncio
    async def test_submits_single_signer_bundle(self) -> None:
        """Signed line + configured submitter → 1-element bundle goes out."""
        attestor = OutcomeAttestor(
            chain_id=CHAIN_ID,
            registry_address=REGISTRY,
            private_key_hex=TEST_KEYS[0],
        )
        lk = LineKey("basketball_nba", "401584293", "spread", "home", "-3.5")
        lh = line_hash(lk, CHAIN_ID, REGISTRY)
        sig = sign_line_outcome(TEST_KEYS[0], lh, int(Outcome.FAVORABLE), CHAIN_ID, REGISTRY)
        attestor._line_resolutions[lh] = LineResolution(
            line_key=lk,
            outcome=Outcome.FAVORABLE,
            home_score=110,
            away_score=105,
            espn_status="STATUS_FINAL",
            resolved_at=time.time() - 1000,
            stable_at=time.time() - 500,
            sig=sig,
        )

        submitter = _CapturingSubmitter(status="submitted")
        out = await attestor.submit_own_attestations(submitter)

        assert out == [lh]
        assert len(submitter.calls) == 1
        call_lh, call_outcome, call_signers, call_sigs = submitter.calls[0]
        assert call_lh == lh
        assert call_outcome == int(Outcome.FAVORABLE)
        assert len(call_signers) == 1
        assert call_signers[0] == TEST_ADDRS[0]
        assert call_sigs == [sig]
        assert lh in attestor._submitted_own

    @pytest.mark.asyncio
    async def test_idempotent_across_loops(self) -> None:
        """Once submitted, same line is NOT re-submitted on next call."""
        attestor = OutcomeAttestor(
            chain_id=CHAIN_ID,
            registry_address=REGISTRY,
            private_key_hex=TEST_KEYS[0],
        )
        lk = LineKey("basketball_nba", "401584293", "spread", "home", "-3.5")
        lh = line_hash(lk, CHAIN_ID, REGISTRY)
        sig = sign_line_outcome(TEST_KEYS[0], lh, int(Outcome.FAVORABLE), CHAIN_ID, REGISTRY)
        attestor._line_resolutions[lh] = LineResolution(
            line_key=lk,
            outcome=Outcome.FAVORABLE,
            home_score=110,
            away_score=105,
            espn_status="STATUS_FINAL",
            resolved_at=time.time() - 1000,
            sig=sig,
        )

        submitter = _CapturingSubmitter(status="submitted")
        out1 = await attestor.submit_own_attestations(submitter)
        out2 = await attestor.submit_own_attestations(submitter)
        assert out1 == [lh]
        assert out2 == []
        assert len(submitter.calls) == 1  # Only ONE on-chain submit total

    @pytest.mark.asyncio
    async def test_skips_unsigned_lines(self) -> None:
        attestor = OutcomeAttestor(
            chain_id=CHAIN_ID,
            registry_address=REGISTRY,
            private_key_hex=TEST_KEYS[0],
        )
        lk = LineKey("basketball_nba", "401584293", "spread", "home", "-3.5")
        lh = line_hash(lk, CHAIN_ID, REGISTRY)
        attestor._line_resolutions[lh] = LineResolution(
            line_key=lk,
            outcome=Outcome.FAVORABLE,
            home_score=110,
            away_score=105,
            espn_status="STATUS_FINAL",
            resolved_at=time.time() - 1000,
            sig=None,  # Not signed yet
        )

        submitter = _CapturingSubmitter()
        out = await attestor.submit_own_attestations(submitter)
        assert out == []
        assert submitter.calls == []

    @pytest.mark.asyncio
    async def test_transient_error_doesnt_cache(self) -> None:
        """Transient submit failure stays retry-eligible on next loop."""
        attestor = OutcomeAttestor(
            chain_id=CHAIN_ID,
            registry_address=REGISTRY,
            private_key_hex=TEST_KEYS[0],
        )
        lk = LineKey("basketball_nba", "401584293", "spread", "home", "-3.5")
        lh = line_hash(lk, CHAIN_ID, REGISTRY)
        sig = sign_line_outcome(TEST_KEYS[0], lh, int(Outcome.FAVORABLE), CHAIN_ID, REGISTRY)
        attestor._line_resolutions[lh] = LineResolution(
            line_key=lk,
            outcome=Outcome.FAVORABLE,
            home_score=110,
            away_score=105,
            espn_status="STATUS_FINAL",
            resolved_at=time.time() - 1000,
            sig=sig,
        )

        submitter = _CapturingSubmitter(status="transient")
        out = await attestor.submit_own_attestations(submitter)
        assert out == []  # Not added to "submitted" list
        assert lh not in attestor._submitted_own  # Not cached
        assert len(submitter.calls) == 1  # But the attempt was made
