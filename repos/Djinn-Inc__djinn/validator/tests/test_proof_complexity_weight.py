"""Tests for the proof-complexity amplifier (DJINN_FF_PROOF_COMPLEXITY_WEIGHT).

The amplifier multiplies a miner's score by a [1.0, MAX] factor derived from
max(avg_prover_bytes, avg_notary_bytes). It's gated behind a feature flag and
requires a minimum number of successful sessions before firing, so cold-start
miners aren't punished.
"""

from __future__ import annotations

import importlib
import math

import pytest

from djinn_validator.core.scoring import (
    MAX_PROOF_BYTES_PER_SESSION,
    MinerMetrics,
    MinerScorer,
)


@pytest.fixture
def scorer() -> MinerScorer:
    """Fresh scorer, no DB, flags unset."""
    return MinerScorer()


@pytest.fixture
def flag_on(monkeypatch):
    """Turn proof_complexity_weight ON for this test."""
    monkeypatch.setenv("DJINN_FF_PROOF_COMPLEXITY_WEIGHT", "true")
    from djinn_validator import feature_flags

    importlib.reload(feature_flags)
    # Also reload scoring.py's view of flags — it imports lazily inside the
    # amplifier block, so reloading feature_flags alone is enough.
    yield
    # Teardown: leave the env untouched (monkeypatch handles it) and reload
    # feature_flags once more so the default OFF state returns for the next
    # test module.
    importlib.reload(feature_flags)


class TestProofComplexityMultiplier:
    """Direct unit tests on _proof_complexity_multiplier."""

    def test_neutral_below_session_gate(self, scorer: MinerScorer) -> None:
        """Fewer than COMPLEXITY_GATE_MIN_SESSIONS recorded sessions -> 1.0x."""
        m = MinerMetrics(uid=1, hotkey="hk")
        m.lifetime_attestation_proof_sessions = scorer.COMPLEXITY_GATE_MIN_SESSIONS - 1
        m.lifetime_attestation_proof_bytes = 10_000_000  # huge bytes, but gated out
        m.lifetime_notary_proof_sessions = 0
        assert scorer._proof_complexity_multiplier(m) == 1.0

    def test_neutral_at_reference_bytes(self, scorer: MinerScorer) -> None:
        """avg_bytes == COMPLEXITY_REF_BYTES -> exactly 1.0x."""
        m = MinerMetrics(uid=1, hotkey="hk")
        m.lifetime_attestation_proof_sessions = 10
        m.lifetime_attestation_proof_bytes = 10 * scorer.COMPLEXITY_REF_BYTES
        assert scorer._proof_complexity_multiplier(m) == 1.0

    def test_one_octave_above_ref(self, scorer: MinerScorer) -> None:
        """avg_bytes == 2*ref -> 1.0 + step (one octave)."""
        m = MinerMetrics(uid=1, hotkey="hk")
        m.lifetime_attestation_proof_sessions = 10
        m.lifetime_attestation_proof_bytes = 10 * scorer.COMPLEXITY_REF_BYTES * 2
        mult = scorer._proof_complexity_multiplier(m)
        assert mult == pytest.approx(1.0 + scorer.COMPLEXITY_STEP_PER_OCTAVE)

    def test_capped_at_max_multiplier(self, scorer: MinerScorer) -> None:
        """Arbitrarily-large bytes -> capped at COMPLEXITY_MAX_MULT."""
        m = MinerMetrics(uid=1, hotkey="hk")
        m.lifetime_attestation_proof_sessions = 10
        m.lifetime_attestation_proof_bytes = 10 * scorer.COMPLEXITY_REF_BYTES * (1 << 30)
        assert scorer._proof_complexity_multiplier(m) == scorer.COMPLEXITY_MAX_MULT

    def test_uses_max_of_prover_and_notary(self, scorer: MinerScorer) -> None:
        """Takes the MAX of prover and notary averages, not the average."""
        m = MinerMetrics(uid=1, hotkey="hk")
        # Prover: tiny sessions. Notary: big sessions.
        m.lifetime_attestation_proof_sessions = 10
        m.lifetime_attestation_proof_bytes = 10 * scorer.COMPLEXITY_REF_BYTES  # avg=1KB
        m.lifetime_notary_proof_sessions = 10
        m.lifetime_notary_proof_bytes = 10 * scorer.COMPLEXITY_REF_BYTES * 4  # avg=4KB (2 octaves)
        mult = scorer._proof_complexity_multiplier(m)
        assert mult == pytest.approx(1.0 + 2 * scorer.COMPLEXITY_STEP_PER_OCTAVE)

    def test_gate_satisfied_by_notary_only(self, scorer: MinerScorer) -> None:
        """If only the notary side passes the gate, we still get the amplifier."""
        m = MinerMetrics(uid=1, hotkey="hk")
        m.lifetime_attestation_proof_sessions = 0
        m.lifetime_notary_proof_sessions = scorer.COMPLEXITY_GATE_MIN_SESSIONS
        m.lifetime_notary_proof_bytes = scorer.COMPLEXITY_GATE_MIN_SESSIONS * scorer.COMPLEXITY_REF_BYTES * 4
        mult = scorer._proof_complexity_multiplier(m)
        assert mult > 1.0

    def test_pre_instrumentation_history_does_not_dilute(self, scorer: MinerScorer) -> None:
        """A miner with a long pre-v1173 history still sees accurate avg bytes.

        Regression test for the divisor-dilution bug found 2026-04-17 on UID 0:
        500 pre-v1173 valid attestations (0 bytes each) + 3 new 4KB attestations
        should compute avg = 4KB, not 4KB/503 ≈ 8 bytes.
        """
        m = MinerMetrics(uid=1, hotkey="hk")
        m.lifetime_attestations_valid = 503  # inflated from pre-v1173 history
        m.lifetime_attestation_proof_sessions = 3  # only these 3 recorded bytes
        m.lifetime_attestation_proof_bytes = 3 * 4096  # 12 KB total
        # avg_prover_bytes should be 4096, not 12288/503 ≈ 24
        assert m.avg_prover_bytes() == pytest.approx(4096.0)
        # And the amplifier should fire (4KB is 2 octaves above 1KB ref)
        mult = scorer._proof_complexity_multiplier(m)
        assert mult == pytest.approx(1.0 + 2 * scorer.COMPLEXITY_STEP_PER_OCTAVE)


class TestProofComplexityAmplifierIntegration:
    """The amplifier should multiply a miner's final weight when the flag is ON."""

    def _build_miner_with_work(self, scorer: MinerScorer, uid: int, bytes_per_session: int) -> MinerMetrics:
        m = scorer.get_or_create(uid, f"hk-{uid}")
        # Give each miner enough sports + attestation credit to have score > 0.
        for _ in range(20):
            m.record_query(correct=True, latency=1.0, proof_submitted=True)
            m.proofs_verified += 1
        # Successful attestations with the target byte size.
        for _ in range(10):
            m.record_attestation(
                latency=1.0,
                proof_valid=True,
                proof_bytes=bytes_per_session,
                duration_ms=1000,
            )
        m.record_health_check(responded=True)
        m.ema_uptime = 1.0
        return m

    def test_flag_off_neutral(self, scorer: MinerScorer) -> None:
        """With the flag OFF, avg bytes are ignored (no uplift)."""
        big = self._build_miner_with_work(scorer, uid=1, bytes_per_session=64 * 1024)
        small = self._build_miner_with_work(scorer, uid=2, bytes_per_session=100)
        weights, breakdowns = scorer.compute_weights_detailed(is_active_epoch=True)
        # Multipliers are still surfaced in the breakdown (observe-only), but
        # the final weight shouldn't differ by the amplifier path.
        # With flag OFF both get 1.0x; since other inputs are identical the
        # weights end up equal (modulo float rounding).
        assert weights[1] == pytest.approx(weights[2], rel=1e-6)
        # Surfacing sanity:
        assert "proof_complexity_mult" in breakdowns[1]
        assert breakdowns[1]["proof_complexity_mult"] > 1.0  # 64KB avg
        assert breakdowns[2]["proof_complexity_mult"] == 1.0  # 100 bytes avg, below ref

    def test_flag_on_heavy_miner_outweighs_light_miner(self, scorer: MinerScorer, flag_on) -> None:
        """With the flag ON, the heavy-byte miner wins."""
        big = self._build_miner_with_work(scorer, uid=1, bytes_per_session=64 * 1024)
        small = self._build_miner_with_work(scorer, uid=2, bytes_per_session=100)
        weights, breakdowns = scorer.compute_weights_detailed(is_active_epoch=True)
        # Normalized weights sum to 1.0; the heavy miner should take more.
        assert weights[1] > weights[2], (
            f"heavy miner (64KB/session) should beat tiny miner (100B/session) when "
            f"DJINN_FF_PROOF_COMPLEXITY_WEIGHT=ON, got weights {weights}"
        )

    def test_flag_on_identical_bytes_weights_equal(self, scorer: MinerScorer, flag_on) -> None:
        """Two miners with identical byte profiles should weight identically."""
        m1 = self._build_miner_with_work(scorer, uid=1, bytes_per_session=16 * 1024)
        m2 = self._build_miner_with_work(scorer, uid=2, bytes_per_session=16 * 1024)
        weights, _ = scorer.compute_weights_detailed(is_active_epoch=True)
        assert weights[1] == pytest.approx(weights[2], rel=1e-6)


class TestAttestationWorkAccumulators:
    """record_attestation must populate proof_bytes/duration_ms only on success."""

    def test_accumulates_on_success(self) -> None:
        m = MinerMetrics(uid=1, hotkey="hk")
        m.record_attestation(
            latency=1.0,
            proof_valid=True,
            proof_bytes=4096,
            duration_ms=2500,
        )
        m.record_attestation(
            latency=1.0,
            proof_valid=True,
            proof_bytes=8192,
            duration_ms=3500,
        )
        assert m.lifetime_attestation_proof_bytes == 12288
        assert m.lifetime_attestation_duration_ms == 6000
        assert m.lifetime_attestation_proof_sessions == 2
        assert m.avg_prover_bytes() == pytest.approx(6144.0)
        assert m.avg_prover_duration_ms() == pytest.approx(3000.0)

    def test_failures_do_not_accumulate(self) -> None:
        m = MinerMetrics(uid=1, hotkey="hk")
        m.record_attestation(
            latency=1.0,
            proof_valid=False,
            proof_bytes=4096,
            duration_ms=2500,
        )
        assert m.lifetime_attestation_proof_bytes == 0
        assert m.lifetime_attestation_duration_ms == 0
        assert m.lifetime_attestation_proof_sessions == 0

    def test_defaults_zero_work(self) -> None:
        """Calls without the new kwargs must not crash existing code paths."""
        m = MinerMetrics(uid=1, hotkey="hk")
        m.record_attestation(latency=1.0, proof_valid=True)
        assert m.lifetime_attestations_valid == 1
        assert m.lifetime_attestation_proof_bytes == 0
        assert m.lifetime_attestation_duration_ms == 0
        assert m.lifetime_attestation_proof_sessions == 0


class TestProofBytesCap:
    """Miner-controlled proof_hex length must not inflate the amplifier.

    The validator computes proof_bytes = len(proof_hex) // 2 from the miner's
    wire response. Without a cap, a miner serving padded responses could lock
    the 2.0x multiplier ceiling permanently. We cap per-session contribution at
    MAX_PROOF_BYTES_PER_SESSION so padding past the saturation point gains
    nothing.
    """

    def test_attestation_bytes_capped(self) -> None:
        m = MinerMetrics(uid=1, hotkey="hk")
        # Miner claims a 10 MiB proof — should be credited at most 1 MiB.
        m.record_attestation(
            latency=1.0,
            proof_valid=True,
            proof_bytes=10 * MAX_PROOF_BYTES_PER_SESSION,
            duration_ms=1000,
        )
        assert m.lifetime_attestation_proof_bytes == MAX_PROOF_BYTES_PER_SESSION
        assert m.lifetime_attestation_proof_sessions == 1

    def test_notary_bytes_capped(self) -> None:
        m = MinerMetrics(uid=1, hotkey="hk")
        m.record_notary_duty(
            proof_valid=True,
            proof_bytes=10 * MAX_PROOF_BYTES_PER_SESSION,
            duration_ms=1000,
        )
        assert m.lifetime_notary_proof_bytes == MAX_PROOF_BYTES_PER_SESSION
        assert m.lifetime_notary_proof_sessions == 1

    def test_under_cap_not_affected(self) -> None:
        """Legitimate heavy sessions (still < cap) are credited in full."""
        m = MinerMetrics(uid=1, hotkey="hk")
        half_meg = MAX_PROOF_BYTES_PER_SESSION // 2
        m.record_attestation(
            latency=1.0,
            proof_valid=True,
            proof_bytes=half_meg,
            duration_ms=1000,
        )
        assert m.lifetime_attestation_proof_bytes == half_meg

    def test_padded_miner_capped_at_max_mult(self, monkeypatch) -> None:
        """A miner padding to 10 MiB/session gets the same multiplier as one at 1 MiB."""
        monkeypatch.setenv("DJINN_FF_PROOF_COMPLEXITY_WEIGHT", "true")
        import importlib

        from djinn_validator import feature_flags

        importlib.reload(feature_flags)
        try:
            scorer = MinerScorer()
            padder = MinerMetrics(uid=1, hotkey="padder")
            honest_max = MinerMetrics(uid=2, hotkey="honest")
            for _ in range(scorer.COMPLEXITY_GATE_MIN_SESSIONS):
                padder.record_attestation(
                    latency=1.0,
                    proof_valid=True,
                    proof_bytes=10 * MAX_PROOF_BYTES_PER_SESSION,
                    duration_ms=1000,
                )
                honest_max.record_attestation(
                    latency=1.0,
                    proof_valid=True,
                    proof_bytes=MAX_PROOF_BYTES_PER_SESSION,
                    duration_ms=1000,
                )
            assert scorer._proof_complexity_multiplier(padder) == scorer._proof_complexity_multiplier(honest_max)
        finally:
            importlib.reload(feature_flags)
