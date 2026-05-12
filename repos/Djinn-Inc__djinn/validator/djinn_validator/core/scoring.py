"""Miner scoring module — implements split sports/attestation scoring.

Sports challenge weights (executability checks via The Odds API):
  - Accuracy:   35%  (Phase 1 matches TLSNotary ground truth)
  - Speed:      25%  (Response latency, normalized across miners)
  - Coverage:   15%  (% of queries with valid TLSNotary proof)
  - Uptime:     15%  (% of epochs responding to health checks)
  - Capability: 10%  (System resource capability bonus)

Attestation challenge weights (web attestation via TLSNotary, mandatory):
  - Proof validity: 60%  (TLSNotary proof verifies correctly)
  - Speed:          40%  (Attestation latency, normalized independently)

Blending: final_score = (1 - W_ATTESTATION) * sports + W_ATTESTATION * attestation
Default W_ATTESTATION = 0.30 — raised from 0.20 for early subnet where sports
data is sparse and attestation is the primary differentiator.

Empty epoch weights (no active signals):
  Without attestation data:
  - Uptime:  50%
  - History: 50%  (Consecutive participation, log-scaled)
  With attestation data:
  - Uptime:      35%
  - History:     30%
  - Attestation: 35%  (Same attestation scoring as active epochs)
"""

from __future__ import annotations

import json
import math
import sqlite3
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from djinn_validator.core.circuit_breaker import ConsensusCircuitBreaker

log = structlog.get_logger()

# Hard ceiling on per-session bytes credited to the proof-complexity amplifier.
# Validator-side `proof_bytes` is derived from `len(proof_hex) // 2`, which the
# miner controls — without a cap, a miner could pad the wire proof to reach the
# amplifier ceiling (2.0x at ≥1 MiB average) permanently. 1 MiB already saturates
# the multiplier (log2(1MiB/1KiB)*0.1 = 1.0 → 2.0x), so legitimate heavy sessions
# lose nothing while padded proofs gain nothing beyond the cap.
MAX_PROOF_BYTES_PER_SESSION = 1_048_576


@dataclass
class MinerMetrics:
    """Accumulated metrics for a single miner within a scoring window."""

    uid: int
    hotkey: str

    # SS58 coldkey from the metagraph, populated via MinerScorer.update_coldkey
    # during the health-check loop. Used by the coldkey-density sybil defense
    # gate (DJINN_FF_COLDKEY_DENSITY_WEIGHT): miners sharing a coldkey with
    # many others get a score divisor so large clusters can't brute-force
    # emissions by registering N UIDs. Empty string = not yet populated (e.g.
    # a freshly-created MinerMetrics before the first health-check cycle runs).
    coldkey: str = ""

    # First time this validator observed this hotkey at this UID. Used by
    # the new-miner zero-weight bootstrap window: miners who haven't been
    # observed long enough AND haven't accumulated enough scored samples
    # are held at weight 0 to close the registration-window Sybil hole.
    # Defaults to 0.0 for legacy records; the loader treats 0.0 as "old
    # enough that bootstrap doesn't apply" so existing miners are never
    # retroactively penalized.
    first_seen_at: float = 0.0

    # ── Sports challenge metrics ──
    queries_total: int = 0
    queries_correct: int = 0  # Phase 1 matched TLSNotary truth
    latencies: list[float] = field(default_factory=list)
    proofs_submitted: int = 0  # queries where miner returned a proof
    proofs_verified: int = 0  # proofs that passed TLSNotary verification
    accuracy_outcomes: list[bool] = field(default_factory=list)  # sliding window (last 20)
    coverage_outcomes: list[bool] = field(default_factory=list)  # sliding window (last 20)

    # ── Canonical odds agreement (task #16, observe-only for now) ──
    # Sliding window of relative-distance scores from the canonical
    # odds median consensus, one entry per /v1/odds/canonical fan-out
    # where this miner contributed a price. Lower is better:
    #   0.00 = exact match on every group
    #   1.00 = ~100% relative distance (completely off)
    # The metric is currently OBSERVE-ONLY — it is NOT fed into the
    # weight formula until we've gathered enough live data to tune
    # the coefficient. Once that lands, miners that diverge from
    # consensus lose weight even if they pass the sports challenge.
    canonical_distances: list[float] = field(default_factory=list)  # sliding window (last 20)

    # ── Attestation challenge metrics (separate from sports) ──
    attestations_total: int = 0
    attestations_valid: int = 0  # TLSNotary proof verified
    attestation_latencies: list[float] = field(default_factory=list)
    attestation_outcomes: list[bool] = field(default_factory=list)  # sliding window (last 10)

    # ── Proof-request tracking ──
    proofs_requested: int = 0  # times miner was asked to submit proof

    # ── Proactive attestation (survives epoch resets) ──
    proactive_proof_verified: bool = False  # miner has a fresh, verified proactive proof
    tlsn_binary_hash: str = ""  # SHA256 prefix of miner's TLSNotary binary (for version matching)

    # ── Notary pair tracking (survives epoch resets) ──
    notary_pair_successes: dict[int, int] = field(default_factory=dict)  # notary_uid -> success count
    notary_pair_failures: dict[int, int] = field(default_factory=dict)  # notary_uid -> failure count

    # ── Notary service metrics (peer-to-peer notarization) ──
    # Per-epoch counters; reset_epoch() zeros these.
    notary_duties_assigned: int = 0  # times assigned as notary for another miner (THIS epoch)
    notary_duties_completed: int = 0  # times the proof using this notary verified (THIS epoch)
    # Lifetime counters; survive reset_epoch(). Used by total_scored_samples()
    # so notary-sidecar miners don't drop back into bootstrap every 12s when
    # the per-epoch counter zeroes. Same pattern as lifetime_queries /
    # lifetime_attestations.
    lifetime_notary_duties_assigned: int = 0
    lifetime_notary_duties_completed: int = 0
    # Per-session work accumulators (instrumentation for DJINN_FF_PROOF_COMPLEXITY_WEIGHT).
    # Incremented only on successful notary duties (proof_valid=True). Total / completed
    # gives average bytes-per-session and ms-per-session — the signal for whether a
    # notary is serving heavy sessions (large sites, long TLS transcripts) or light ones.
    lifetime_notary_proof_bytes: int = 0
    lifetime_notary_duration_ms: int = 0
    # Count of notary duties for which proof_bytes were actually recorded. This
    # is the correct divisor for avg_notary_bytes — using lifetime_notary_duties_completed
    # dilutes new data with pre-instrumentation history that had zero bytes. The
    # counter is monotonic and only ever incremented alongside proof_bytes.
    lifetime_notary_proof_sessions: int = 0
    notary_capable: bool = False  # running a notary sidecar (discovered this epoch)
    shield_installed: bool = False  # djinn-tunnel-shield DDoS protection installed

    # ── Capability advertisement (from health check) ──
    memory_total_mb: int = 0
    memory_available_mb: int = 0
    cpu_cores: int = 0
    cpu_load_1m: float = 0.0
    tlsn_max_concurrent: int = 0
    tlsn_active_sessions: int = 0
    notary_max_concurrent: int = 0
    notary_active_sessions: int = 0
    disk_free_gb: float = 0.0
    capabilities_reported: bool = False  # True if miner reports capabilities
    reported_version: str = ""  # Miner's self-reported version from health check

    # ── Shared metrics ──
    health_checks_total: int = 0  # lifetime counter (display only)
    health_checks_responded: int = 0  # lifetime counter (display only)
    consecutive_epochs: int = 0
    # EMA uptime: smoothed uptime score that persists across epoch resets.
    # Alpha = 0.00193 gives a half-life of exactly 1 Bittensor tempo (360 blocks).
    # A 4-minute DDoS costs 3.8%. A 30-second restart costs 0.6%.
    # A dead miner reaches 50% after 1 tempo, ~0% after 5 tempos (~6 hours).
    #
    # Defaults to 1.0 ("presumed healthy") so a fresh miner registration
    # is online immediately. Was 0.0, which forced new miners through a
    # ~72min "ramp-up" where they showed as offline AND received zero
    # uptime weight even when serving 200s — broke new-miner bootstrap.
    # A genuinely dead axon still falls below 0.5 in ~72min (one tempo);
    # the symmetric trade is tracking new-miner online instantly.
    ema_uptime: float = 1.0

    # ── Carry-forward metrics (preserved across epoch resets) ──
    # Challenges run every ~10 min but epochs reset every ~12s. Without
    # carry-forward, all challenge metrics show 0 for 98% of the time.
    prev_accuracy: float = 0.0
    prev_latencies: list[float] = field(default_factory=list)
    prev_coverage: float = 0.0

    # ── Lifetime counters (never reset, for dashboard display) ──
    lifetime_queries: int = 0
    lifetime_correct: int = 0
    lifetime_attestations: int = 0
    lifetime_attestations_valid: int = 0
    # Per-session work accumulators on the PROVER side (symmetric to
    # lifetime_notary_proof_bytes/duration_ms on the notary side). Only
    # incremented on proof_valid=True; total / valid = avg-per-session which
    # feeds DJINN_FF_PROOF_COMPLEXITY_WEIGHT. A miner serving heavy sites
    # (large transcripts, long handshakes) accrues faster than a sybil cluster
    # spraying trivial sessions across 30 UIDs.
    lifetime_attestation_proof_bytes: int = 0
    lifetime_attestation_duration_ms: int = 0
    # Count of attestations for which proof_bytes were actually recorded.
    # Symmetric to lifetime_notary_proof_sessions. Used as the divisor for
    # avg_prover_bytes so pre-instrumentation history doesn't dilute the signal.
    lifetime_attestation_proof_sessions: int = 0

    def accuracy_score(self) -> float:
        """Fraction of recent sports queries where result matched ground truth.

        Uses a sliding window of the last 20 outcomes so declining miners
        lose their advantage quickly. Falls back to lifetime ratio or
        previous epoch carry-forward for backwards compatibility.
        """
        if self.accuracy_outcomes:
            return sum(self.accuracy_outcomes) / len(self.accuracy_outcomes)
        if self.queries_total == 0:
            return self.prev_accuracy
        return self.queries_correct / self.queries_total

    def coverage_score(self) -> float:
        """Fraction of recent proof requests where miner's proof was verified.

        Uses a sliding window of the last 20 outcomes. Falls back to
        lifetime ratio or previous epoch carry-forward.
        """
        if self.coverage_outcomes:
            return sum(self.coverage_outcomes) / len(self.coverage_outcomes)
        if self.proofs_requested == 0:
            return self.prev_coverage
        return self.proofs_verified / self.proofs_requested

    def canonical_agreement_score(self) -> float:
        """Agreement with canonical odds median consensus.

        Returns 1.0 - mean(recent distances), clipped to [0.0, 1.0].
        A miner that matches consensus every time scores 1.0; a miner
        that's consistently ~10% off consensus scores ~0.90; a miner
        with no recorded canonical observations scores 1.0 (neutral)
        so we don't penalize miners before the canonical pipeline is
        enabled on their fleet.

        The metric is observe-only until the weight-formula integration
        lands; ``compute_weights_detailed`` surfaces it in the breakdown
        but does NOT multiply it into the final weight.
        """
        if not self.canonical_distances:
            return 1.0
        avg = sum(self.canonical_distances) / len(self.canonical_distances)
        return max(0.0, min(1.0, 1.0 - avg))

    # EMA uptime alpha: chosen so the half-life is exactly one Bittensor tempo
    # (360 blocks = 360 health checks at 12s each = ~72 minutes).
    # alpha = 1 - exp(ln(0.5) / 360) = 0.00193
    # This means a miner must be offline for a full tempo to lose half its
    # uptime score. Brief DDoS bursts (4 min) cost only ~4%. Restarts cost <1%.
    _EMA_ALPHA = 0.00193

    def record_health_check(self, responded: bool) -> None:
        """Update EMA uptime and lifetime counters."""
        self.health_checks_total += 1
        if responded:
            self.health_checks_responded += 1
        self.ema_uptime = self._EMA_ALPHA * (1.0 if responded else 0.0) + (1.0 - self._EMA_ALPHA) * self.ema_uptime

    def uptime_score(self) -> float:
        """EMA-smoothed uptime score. Survives epoch resets and restarts."""
        return self.ema_uptime

    def total_scored_samples(self) -> int:
        """Total scored interactions used for bootstrap + volume confidence.

        Counts three kinds of evidence:
          * LIFETIME sports queries (canonical odds, line checks, etc.)
          * LIFETIME attestation challenges (TLSNotary proofs we asked for)
          * LIFETIME peer notary duties assigned (this miner acted as notary
            for another miner's TLSN session; pass/fail feeds into
            notary_reliability)

        Any of the three is scoreable work we've observed the miner perform,
        so all three should contribute to volume confidence. Excluding
        notary duties underweights miners who specialize in running notary
        sidecars.

        Must use lifetime counters rather than the per-epoch queries_total
        (which reset_epoch() zeroes at the end of every weight window). Using
        the per-epoch count caused a miner with 200 lifetime queries but
        zero queries in the current 12-second window to drop BACK into the
        bootstrap window every time the epoch rolled over.
        """
        return self.lifetime_queries + self.lifetime_attestations + self.lifetime_notary_duties_assigned

    def is_in_bootstrap(
        self,
        *,
        min_samples: int,
        min_age_seconds: float,
        now: float | None = None,
    ) -> bool:
        """A miner is in bootstrap iff it has too few samples AND too little
        observed age. Both conditions must hold; satisfying either graduates
        the miner. Legacy records with first_seen_at == 0.0 are treated as
        old enough to skip bootstrap (never penalize existing miners on a
        rolling deploy).
        """
        import time as _time

        if self.first_seen_at <= 0.0:
            return False
        if self.total_scored_samples() >= min_samples:
            return False
        current = _time.time() if now is None else now
        age = current - self.first_seen_at
        return age < min_age_seconds

    def attestation_validity_score(self) -> float:
        """Fraction of recent attestation challenges with valid TLSNotary proof.

        Uses a sliding window of the last 10 outcomes so declining miners
        lose their advantage and new miners can catch up quickly.
        Falls back to lifetime ratio if no sliding window data exists
        (backwards compatibility with persisted state).
        """
        if self.attestation_outcomes:
            return sum(self.attestation_outcomes) / len(self.attestation_outcomes)
        if self.attestations_total == 0:
            return 0.0
        return self.attestations_valid / self.attestations_total

    # Optional consensus circuit breaker reference. Wired by MinerScorer
    # in get_or_create when the breaker is attached. Used to feed CUSUM
    # observations from record_query/record_attestation without forcing
    # every challenge call site to know about the breaker.
    _circuit_breaker_ref: object | None = None

    def _feed_breaker(self, deviation: float, query_id: str = "") -> None:
        """Push a CUSUM observation to the consensus circuit breaker if
        one is attached. Never raises — a tracker hiccup must not break
        the scoring loop.
        """
        cb = self._circuit_breaker_ref
        if cb is None or not self.hotkey:
            return
        try:
            cb.record_observation(  # type: ignore[attr-defined]
                hotkey=self.hotkey, deviation=deviation, query_id=query_id
            )
        except Exception as e:
            log.warning(
                "miner_metrics_cb_feed_failed",
                hotkey=self.hotkey[:10],
                error=str(e)[:100],
            )

    def record_query(
        self,
        correct: bool,
        latency: float,
        proof_submitted: bool,
        proof_status: str = "",
        *,
        query_id: str = "",
    ) -> None:
        """Record a single sports query result.

        If proof_status is "unverified", the query is never counted as
        correct regardless of the ``correct`` flag — unverified proofs
        cannot be trusted for accuracy scoring (R25-18).
        """
        self.queries_total += 1
        self.lifetime_queries += 1
        is_correct = False
        if proof_status == "unverified":
            log.warning(
                "unverified_proof_zero_accuracy",
                uid=self.uid,
                hotkey=self.hotkey,
            )
        elif correct:
            is_correct = True
            self.queries_correct += 1
            self.lifetime_correct += 1
        # Sliding window: track last 20 accuracy outcomes
        self.accuracy_outcomes.append(is_correct)
        if len(self.accuracy_outcomes) > 20:
            self.accuracy_outcomes = self.accuracy_outcomes[-20:]
        self.latencies.append(latency)
        if proof_submitted:
            self.proofs_submitted += 1
        # Feed the circuit breaker: 0 deviation when correct, a fixed
        # magnitude when wrong. Wrong-answer signal accumulates over
        # many queries until the CUSUM threshold trips.
        deviation = 0.0 if is_correct else 0.05
        self._feed_breaker(deviation=deviation, query_id=query_id or f"q{self.queries_total}")

    def record_attestation(
        self,
        latency: float,
        proof_valid: bool,
        *,
        validator_timeout: bool = False,
        proof_bytes: int = 0,
        duration_ms: int = 0,
    ) -> None:
        """Record a web attestation challenge result (separate from sports).

        Args:
            latency: Time taken for the attestation.
            proof_valid: Whether the proof was valid.
            validator_timeout: If True, the failure was a validator-side
                verification timeout (not the miner's fault). The attempt
                is still counted in lifetime stats but excluded from the
                sliding window so it doesn't penalize the miner's score.
            proof_bytes: Size of the TLSNotary proof this miner PROVED.
                Lifetime accumulator for DJINN_FF_PROOF_COMPLEXITY_WEIGHT.
            duration_ms: Wall-clock duration of the MPC-TLS session.

        proof_bytes and duration_ms accumulate only on proof_valid=True so
        failed sessions don't amplify. Symmetric to record_notary_duty.
        """
        self.attestations_total += 1
        self.lifetime_attestations += 1
        if proof_valid:
            self.attestations_valid += 1
            self.lifetime_attestations_valid += 1
            if proof_bytes > 0:
                capped_bytes = min(int(proof_bytes), MAX_PROOF_BYTES_PER_SESSION)
                self.lifetime_attestation_proof_bytes += capped_bytes
                self.lifetime_attestation_proof_sessions += 1
            if duration_ms > 0:
                self.lifetime_attestation_duration_ms += int(duration_ms)
        # Sliding window: track last 10 outcomes for recency-weighted scoring.
        # Validator-side timeouts are excluded since the miner can't control them.
        if not validator_timeout:
            self.attestation_outcomes.append(proof_valid)
            if len(self.attestation_outcomes) > 10:
                self.attestation_outcomes = self.attestation_outcomes[-10:]
        # Only record real latencies (skip latency=0 from known-broken miner
        # auto-scoring, which would pollute speed normalization)
        if latency > 0:
            self.attestation_latencies.append(latency)
        # Feed the consensus circuit breaker. Validator-side timeouts
        # are not the miner's fault, so they don't count as deviations.
        # Otherwise: 0.0 for valid proof, 0.05 for invalid (same scale
        # as record_query so the threshold tuning is consistent).
        if not validator_timeout:
            deviation = 0.0 if proof_valid else 0.05
            self._feed_breaker(
                deviation=deviation,
                query_id=f"a{self.attestations_total}",
            )

    def notary_reliability(self) -> float:
        """Fraction of notary assignments that produced a verified proof."""
        if self.notary_duties_assigned == 0:
            return 0.0
        return self.notary_duties_completed / self.notary_duties_assigned

    def avg_prover_bytes(self) -> float:
        """Average TLSN proof size across sessions where we recorded bytes.

        Divides by lifetime_attestation_proof_sessions (not lifetime_attestations_valid)
        so pre-v1173 attestations — which had no bytes counted — don't dilute the
        average. A brand-new miner and a miner with 500 pre-instrumentation valid
        attestations compute the same average from the same 3 new sessions.
        """
        if self.lifetime_attestation_proof_sessions <= 0:
            return 0.0
        return self.lifetime_attestation_proof_bytes / self.lifetime_attestation_proof_sessions

    def avg_notary_bytes(self) -> float:
        """Average TLSN proof size across notary sessions where bytes were recorded."""
        if self.lifetime_notary_proof_sessions <= 0:
            return 0.0
        return self.lifetime_notary_proof_bytes / self.lifetime_notary_proof_sessions

    def avg_prover_duration_ms(self) -> float:
        if self.lifetime_attestation_proof_sessions <= 0:
            return 0.0
        return self.lifetime_attestation_duration_ms / self.lifetime_attestation_proof_sessions

    def avg_notary_duration_ms(self) -> float:
        if self.lifetime_notary_proof_sessions <= 0:
            return 0.0
        return self.lifetime_notary_duration_ms / self.lifetime_notary_proof_sessions

    def record_notary_duty(
        self,
        proof_valid: bool,
        proof_bytes: int = 0,
        duration_ms: int = 0,
    ) -> None:
        """Record that this miner served as notary for another miner's proof.

        proof_bytes and duration_ms are accumulated only on proof_valid=True;
        failed sessions don't produce meaningful work-done signals. These feed
        future DJINN_FF_PROOF_COMPLEXITY_WEIGHT gating that rewards notaries
        serving heavier sessions sub-linearly (evidence that a shared sidecar
        can't hide behind 30× UIDs).
        """
        self.notary_duties_assigned += 1
        self.lifetime_notary_duties_assigned += 1
        if proof_valid:
            self.notary_duties_completed += 1
            self.lifetime_notary_duties_completed += 1
            if proof_bytes > 0:
                capped_bytes = min(int(proof_bytes), MAX_PROOF_BYTES_PER_SESSION)
                self.lifetime_notary_proof_bytes += capped_bytes
                self.lifetime_notary_proof_sessions += 1
            if duration_ms > 0:
                self.lifetime_notary_duration_ms += int(duration_ms)

    def update_capabilities(
        self,
        memory_total_mb: int,
        memory_available_mb: int,
        cpu_cores: int,
        cpu_load_1m: float,
        tlsn_max_concurrent: int,
        tlsn_active_sessions: int,
        notary_max_concurrent: int,
        notary_active_sessions: int,
        disk_free_gb: float,
    ) -> None:
        """Update capability metrics from health check response."""
        self.memory_total_mb = memory_total_mb
        self.memory_available_mb = memory_available_mb
        self.cpu_cores = cpu_cores
        self.cpu_load_1m = cpu_load_1m
        self.tlsn_max_concurrent = tlsn_max_concurrent
        self.tlsn_active_sessions = tlsn_active_sessions
        self.notary_max_concurrent = notary_max_concurrent
        self.notary_active_sessions = notary_active_sessions
        self.disk_free_gb = disk_free_gb
        self.capabilities_reported = True


class MinerScorer:
    """Computes normalized scores across all miners for weight setting.

    Sports and attestation challenges are scored independently then blended.
    This ensures attestation-focused miners are fairly rewarded (~$0.02/attestation
    burn cost recouped via emission share at equilibrium).
    """

    # ── Sports challenge weights ──
    W_ACCURACY = 0.35
    W_SPEED = 0.25
    W_COVERAGE = 0.15
    W_UPTIME = 0.15
    # Canonical agreement is observe-only until the data pipeline reliably
    # populates canonical_distances for every miner. Today /v1/odds/canonical
    # is only called when external clients request consensus odds, so coverage
    # is ~0% in production — integrating the metric with a nonzero weight
    # would just give miners a flat 15% bonus (default score = 1.0 when no
    # observations). Re-enable when an auto-fan-out is added and validated.
    W_CANONICAL = 0.0
    W_CAPABILITY = 0.10  # Resource capability bonus

    # ── Volume confidence curve ──
    # Miners need VOLUME_TARGET scored samples to reach full weight.
    # Below that, weight is scaled by sqrt(samples / target). This
    # prevents low-query miners from getting the same weight as
    # high-volume ones, and smooths the cliff edge after bootstrap.
    #
    # Calibrated against SN103's 10,000-block (~33h) immunity. At
    # observed query rates a legitimate new miner accumulates roughly
    # 150-200 samples during immunity; at target 500 they exited
    # immunity at volume_factor ~63%, which put perfectly-scoring new
    # miners below average-scoring veterans. Target 250 lets a busy
    # new miner hit ~89% by end of immunity while still giving a full
    # sqrt shrinkage on under-observed miners. The 50-sample bootstrap
    # floor remains the Sybil gate; volume_factor is the confidence
    # shrinkage — distinct knobs with distinct roles.
    VOLUME_TARGET = 250

    # ── Attestation challenge weights ──
    W_ATTEST_VALIDITY = 0.60  # TLSNotary proof correctness
    W_ATTEST_SPEED = 0.40  # Normalized attestation latency

    # ── Blend weight: how much attestation contributes to final score ──
    # 30% attestation / 70% sports. Raised from 0.20 for early subnet where
    # sports data is sparse and attestation is the primary differentiator.
    W_ATTESTATION_BLEND = 0.30

    # ── Bootstrap window for fresh miners ──
    # New hotkeys are held at weight 0 until they have BOTH at least
    # BOOTSTRAP_MIN_SAMPLES scored interactions AND have been visible
    # to this validator for at least BOOTSTRAP_MIN_AGE_SECONDS. Closes
    # the Sybil hole where a freshly-registered miner could extract
    # value before validators have built up enough samples to score
    # them honestly. Gated by DJINN_FF_NEW_MINER_ZERO_WEIGHT until
    # validated. See project_incentive_attack_surface threat #1.
    BOOTSTRAP_MIN_SAMPLES = 50
    BOOTSTRAP_MIN_AGE_SECONDS = 86400  # 24 hours

    # ── Reliability amplification (gated by DJINN_FF_RELIABILITY_WEIGHT) ──
    # Once a miner has accumulated enough notary assignments for the ratio
    # to be meaningful, multiply score by max(floor, notary_reliability).
    # Sybils that clone miner boxes without cloning notary infrastructure
    # earn linearly on cheap signals but sub-linearly on this one, because
    # each UID needs its own working TLSN sidecar.
    RELIAB_GATE_MIN_ASSIGNED = 5
    RELIAB_FLOOR = 0.20
    SHIELD_BONUS = 0.20

    # ── Proof-complexity amplifier (gated by DJINN_FF_PROOF_COMPLEXITY_WEIGHT) ──
    # Miners serving heavy sessions (large pages like debust/firmrecord, long
    # TLS transcripts) earn more per session than sybils spraying tiny sessions.
    # The multiplier is log-scaled from COMPLEXITY_REF_BYTES:
    #   avg_bytes <= ref  → 1.0x
    #   avg_bytes == ref*2^N → 1.0 + N*step (clamped)
    # For step=0.1, ref=1KB, cap=2.0: 1KB→1.0, 2KB→1.1, 16KB→1.4, 1MB→1.9,
    # 16MB+→2.0. Averaged across prover and notary sides, whichever is higher.
    # Gate: only applied once the miner has at least COMPLEXITY_GATE_MIN_SESSIONS
    # successful sessions on the chosen side — below that, neutral 1.0x.
    COMPLEXITY_REF_BYTES = 1024
    COMPLEXITY_STEP_PER_OCTAVE = 0.10
    COMPLEXITY_MAX_MULT = 2.0
    COMPLEXITY_GATE_MIN_SESSIONS = 3

    # ── Empty epoch weights (no attestation data) ──
    W_EMPTY_UPTIME = 0.50
    W_EMPTY_HISTORY = 0.50

    # ── Empty epoch weights (with attestation data) ──
    W_EMPTY_UPTIME_A = 0.35
    W_EMPTY_HISTORY_A = 0.30
    W_EMPTY_ATTESTATION = 0.35

    def __init__(
        self,
        attestation_blend: float | None = None,
        db_path: str | None = None,
        circuit_breaker: ConsensusCircuitBreaker | None = None,
    ) -> None:
        self._miners: dict[int, MinerMetrics] = {}
        if attestation_blend is not None:
            self.W_ATTESTATION_BLEND = attestation_blend
        # Optional consensus circuit breaker. When provided AND the
        # DJINN_FF_CIRCUIT_BREAKER feature flag is on, miners that have
        # been flagged for sustained deviation from consensus are forced
        # to weight 0 in compute_weights. The breaker is fed by call
        # sites that observe per-query miner deviations (sports challenge
        # accuracy, attestation validity, etc.) via record_observation.
        self._circuit_breaker = circuit_breaker

        # Optional SQLite persistence so scores survive restarts
        self._db: sqlite3.Connection | None = None
        self._db_lock = threading.Lock()
        if db_path:
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
            self._db = sqlite3.connect(db_path, check_same_thread=False)
            self._db.execute("PRAGMA journal_mode=WAL")
            self._db.execute("PRAGMA busy_timeout=5000")
            self._db.execute("""
                CREATE TABLE IF NOT EXISTS miner_scores (
                    uid INTEGER PRIMARY KEY,
                    hotkey TEXT NOT NULL,
                    data TEXT NOT NULL,
                    updated_at REAL NOT NULL
                )
            """)
            self._db.execute("""
                CREATE TABLE IF NOT EXISTS migrations (
                    id TEXT PRIMARY KEY,
                    applied_at REAL NOT NULL
                )
            """)
            self._db.commit()
            self._load_persisted()
            self._apply_migrations()

    def _load_persisted(self) -> None:
        """Load miner scores from SQLite on startup."""
        if not self._db:
            return
        try:
            cursor = self._db.execute("SELECT uid, hotkey, data FROM miner_scores")
            loaded = 0
            for uid, hotkey, data_json in cursor:
                try:
                    d = json.loads(data_json)
                    m = MinerMetrics(uid=uid, hotkey=hotkey)
                    m.queries_total = d.get("queries_total", 0)
                    m.queries_correct = d.get("queries_correct", 0)
                    m.proofs_submitted = d.get("proofs_submitted", 0)
                    m.proofs_verified = d.get("proofs_verified", 0)
                    m.proofs_requested = d.get("proofs_requested", 0)
                    m.accuracy_outcomes = d.get("accuracy_outcomes", [])[-20:]
                    m.coverage_outcomes = d.get("coverage_outcomes", [])[-20:]
                    m.attestations_total = d.get("attestations_total", 0)
                    m.attestations_valid = d.get("attestations_valid", 0)
                    m.health_checks_total = d.get("health_checks_total", 0)
                    m.health_checks_responded = d.get("health_checks_responded", 0)
                    # Persisted miners load their stored EMA. Records that
                    # pre-date the EMA field (very old persistence) are
                    # presumed healthy (1.0) for parity with the dataclass
                    # default; they'll decay normally if they're really dead.
                    _ema = d.get("ema_uptime", 1.0)
                    m.ema_uptime = (
                        max(0.0, min(1.0, _ema)) if isinstance(_ema, int | float) and math.isfinite(_ema) else 1.0
                    )
                    m.consecutive_epochs = d.get("consecutive_epochs", 0)
                    m.notary_duties_assigned = d.get("notary_duties_assigned", 0)
                    m.notary_duties_completed = d.get("notary_duties_completed", 0)
                    m.lifetime_notary_duties_assigned = d.get("lifetime_notary_duties_assigned", 0)
                    m.lifetime_notary_duties_completed = d.get("lifetime_notary_duties_completed", 0)
                    m.lifetime_notary_proof_bytes = d.get("lifetime_notary_proof_bytes", 0)
                    m.lifetime_notary_duration_ms = d.get("lifetime_notary_duration_ms", 0)
                    m.lifetime_notary_proof_sessions = d.get("lifetime_notary_proof_sessions", 0)
                    m.notary_capable = d.get("notary_capable", False)
                    m.proactive_proof_verified = d.get("proactive_proof_verified", False)
                    m.tlsn_binary_hash = d.get("tlsn_binary_hash", "")
                    m.capabilities_reported = d.get("capabilities_reported", False)
                    m.memory_total_mb = d.get("memory_total_mb", 0)
                    m.cpu_cores = d.get("cpu_cores", 0)
                    m.lifetime_queries = d.get("lifetime_queries", 0)
                    m.lifetime_correct = d.get("lifetime_correct", 0)
                    m.lifetime_attestations = d.get("lifetime_attestations", 0)
                    m.lifetime_attestations_valid = d.get("lifetime_attestations_valid", 0)
                    m.lifetime_attestation_proof_bytes = d.get("lifetime_attestation_proof_bytes", 0)
                    m.lifetime_attestation_duration_ms = d.get("lifetime_attestation_duration_ms", 0)
                    m.lifetime_attestation_proof_sessions = d.get("lifetime_attestation_proof_sessions", 0)
                    m.prev_accuracy = d.get("prev_accuracy", 0.0)
                    m.prev_latencies = d.get("prev_latencies", [])
                    m.prev_coverage = d.get("prev_coverage", 0.0)
                    # Legacy records persisted before the bootstrap window
                    # was added have first_seen_at == 0.0, which the
                    # is_in_bootstrap() check treats as "old enough to skip
                    # bootstrap." This is intentional: rolling out the
                    # bootstrap rule must not retroactively penalize miners
                    # already on the network.
                    m.first_seen_at = float(d.get("first_seen_at", 0.0) or 0.0)
                    m.attestation_latencies = d.get("attestation_latencies", [])[:50]
                    m.attestation_outcomes = d.get("attestation_outcomes", [])[-10:]
                    # Restore notary pair history (keys are JSON strings, convert to int)
                    raw_successes = d.get("notary_pair_successes", {})
                    m.notary_pair_successes = {int(k): v for k, v in raw_successes.items()}
                    raw_failures = d.get("notary_pair_failures", {})
                    m.notary_pair_failures = {int(k): v for k, v in raw_failures.items()}
                    self._miners[uid] = m
                    loaded += 1
                except Exception:
                    continue
            if loaded:
                log.info("scorer_loaded_from_db", count=loaded)
        except Exception as e:
            log.error("scorer_db_load_failed", err=str(e))

    def _apply_migrations(self) -> None:
        """Run any pending one-shot migrations against the in-memory miner set.

        Each migration has a stable id stored in the ``migrations`` table.
        On startup, we look up the id; if absent, we apply the change and
        insert the marker. Subsequent restarts find the marker and skip.

        Migrations are append-only: we never modify the historical effect
        of an old migration, only add new ones. To force a re-run for a
        specific incident, ``DELETE FROM migrations WHERE id = '...'``
        and restart — the migration body is also written to be safe under
        re-application (only acts on records that still need the bump).
        """
        if not self._db:
            return
        self._migration_v1739_uptime_bump()

    def _migration_v1739_uptime_bump(self) -> None:
        """Backfill ema_uptime=1.0 for miners with proof of life.

        Pre-v1738 the dataclass default was 0.0, so any miner ever
        observed by this validator carries a low EMA that needs a full
        tempo of successful checks to climb back above the 0.5 "ok"
        threshold — even if the miner is healthy right now. This
        migration bumps anyone with attestations_total > 0 (proof they
        responded to at least one challenge) up to 1.0 so they stop
        showing as "offline" the moment v1739 boots.

        Side effect window: a miner that died long ago but has an
        attestation in their history gets ~72min of wrong "online"
        before the EMA decays back below 0.5. Acceptable trade for
        instant recovery of currently-healthy miners.
        """
        if not self._db:
            return
        marker = "v1739_uptime_bump"
        try:
            row = self._db.execute(
                "SELECT applied_at FROM migrations WHERE id = ?",
                (marker,),
            ).fetchone()
            if row:
                return
            bumped = 0
            for m in self._miners.values():
                if m.attestations_total > 0 and m.ema_uptime < 1.0:
                    m.ema_uptime = 1.0
                    bumped += 1
            self._db.execute(
                "INSERT INTO migrations (id, applied_at) VALUES (?, ?)",
                (marker, time.time()),
            )
            self._db.commit()
            log.info("migration_applied", id=marker, bumped=bumped)
        except Exception as e:
            log.error("migration_failed", id=marker, err=str(e))

    def persist(self, uid: int) -> None:
        """Save a single miner's scores to SQLite."""
        if not self._db:
            return
        m = self._miners.get(uid)
        if not m:
            return
        import time as _time

        data = json.dumps(
            {
                "queries_total": m.queries_total,
                "queries_correct": m.queries_correct,
                "proofs_submitted": m.proofs_submitted,
                "proofs_verified": m.proofs_verified,
                "proofs_requested": m.proofs_requested,
                "accuracy_outcomes": m.accuracy_outcomes[-20:],
                "coverage_outcomes": m.coverage_outcomes[-20:],
                "attestations_total": m.attestations_total,
                "attestations_valid": m.attestations_valid,
                "health_checks_total": m.health_checks_total,
                "health_checks_responded": m.health_checks_responded,
                "ema_uptime": m.ema_uptime,
                "consecutive_epochs": m.consecutive_epochs,
                "notary_duties_assigned": m.notary_duties_assigned,
                "notary_duties_completed": m.notary_duties_completed,
                "lifetime_notary_duties_assigned": m.lifetime_notary_duties_assigned,
                "lifetime_notary_duties_completed": m.lifetime_notary_duties_completed,
                "lifetime_notary_proof_bytes": m.lifetime_notary_proof_bytes,
                "lifetime_notary_duration_ms": m.lifetime_notary_duration_ms,
                "lifetime_notary_proof_sessions": m.lifetime_notary_proof_sessions,
                "notary_capable": m.notary_capable,
                "proactive_proof_verified": m.proactive_proof_verified,
                "tlsn_binary_hash": m.tlsn_binary_hash,
                "capabilities_reported": m.capabilities_reported,
                "memory_total_mb": m.memory_total_mb,
                "cpu_cores": m.cpu_cores,
                "lifetime_queries": m.lifetime_queries,
                "lifetime_correct": m.lifetime_correct,
                "lifetime_attestations": m.lifetime_attestations,
                "lifetime_attestations_valid": m.lifetime_attestations_valid,
                "lifetime_attestation_proof_bytes": m.lifetime_attestation_proof_bytes,
                "lifetime_attestation_duration_ms": m.lifetime_attestation_duration_ms,
                "lifetime_attestation_proof_sessions": m.lifetime_attestation_proof_sessions,
                "prev_accuracy": m.prev_accuracy,
                "prev_latencies": m.prev_latencies[:10],
                "prev_coverage": m.prev_coverage,
                "first_seen_at": m.first_seen_at,
                "attestation_latencies": m.attestation_latencies[-50:],
                "attestation_outcomes": m.attestation_outcomes[-10:],
                "notary_pair_successes": m.notary_pair_successes,
                "notary_pair_failures": m.notary_pair_failures,
            }
        )
        try:
            with self._db_lock:
                self._db.execute(
                    "INSERT OR REPLACE INTO miner_scores (uid, hotkey, data, updated_at) " "VALUES (?, ?, ?, ?)",
                    (uid, m.hotkey, data, _time.time()),
                )
                self._db.commit()
        except Exception:
            pass  # non-critical

    def persist_all(self) -> None:
        """Batch save all miner scores. Called after each epoch."""
        if not self._db:
            return
        import time as _time

        try:
            with self._db_lock:
                for uid, m in self._miners.items():
                    data = json.dumps(
                        {
                            "queries_total": m.queries_total,
                            "queries_correct": m.queries_correct,
                            "proofs_submitted": m.proofs_submitted,
                            "proofs_verified": m.proofs_verified,
                            "proofs_requested": m.proofs_requested,
                            "accuracy_outcomes": m.accuracy_outcomes[-20:],
                            "coverage_outcomes": m.coverage_outcomes[-20:],
                            "attestations_total": m.attestations_total,
                            "attestations_valid": m.attestations_valid,
                            "health_checks_total": m.health_checks_total,
                            "health_checks_responded": m.health_checks_responded,
                            "ema_uptime": m.ema_uptime,
                            "consecutive_epochs": m.consecutive_epochs,
                            "notary_duties_assigned": m.notary_duties_assigned,
                            "notary_duties_completed": m.notary_duties_completed,
                            "lifetime_notary_duties_assigned": m.lifetime_notary_duties_assigned,
                            "lifetime_notary_duties_completed": m.lifetime_notary_duties_completed,
                            "lifetime_notary_proof_bytes": m.lifetime_notary_proof_bytes,
                            "lifetime_notary_duration_ms": m.lifetime_notary_duration_ms,
                            "lifetime_notary_proof_sessions": m.lifetime_notary_proof_sessions,
                            "notary_capable": m.notary_capable,
                            "proactive_proof_verified": m.proactive_proof_verified,
                            "tlsn_binary_hash": m.tlsn_binary_hash,
                            "capabilities_reported": m.capabilities_reported,
                            "memory_total_mb": m.memory_total_mb,
                            "cpu_cores": m.cpu_cores,
                            "lifetime_queries": m.lifetime_queries,
                            "lifetime_correct": m.lifetime_correct,
                            "lifetime_attestations": m.lifetime_attestations,
                            "lifetime_attestations_valid": m.lifetime_attestations_valid,
                            "lifetime_attestation_proof_bytes": m.lifetime_attestation_proof_bytes,
                            "lifetime_attestation_duration_ms": m.lifetime_attestation_duration_ms,
                            "lifetime_attestation_proof_sessions": m.lifetime_attestation_proof_sessions,
                            "prev_accuracy": m.prev_accuracy,
                            "prev_latencies": m.prev_latencies[:10],
                            "prev_coverage": m.prev_coverage,
                            "first_seen_at": m.first_seen_at,
                            "attestation_latencies": m.attestation_latencies[-50:],
                            "attestation_outcomes": m.attestation_outcomes[-10:],
                            "notary_pair_successes": m.notary_pair_successes,
                            "notary_pair_failures": m.notary_pair_failures,
                        }
                    )
                    self._db.execute(
                        "INSERT OR REPLACE INTO miner_scores (uid, hotkey, data, updated_at) " "VALUES (?, ?, ?, ?)",
                        (uid, m.hotkey, data, _time.time()),
                    )
                self._db.commit()
        except Exception as e:
            log.warning("scorer_persist_all_failed", err=str(e)[:100])

    def get(self, uid: int) -> MinerMetrics | None:
        """Get metrics for a miner without creating or resetting."""
        return self._miners.get(uid)

    def record_consensus_observation(
        self,
        *,
        hotkey: str,
        deviation: float,
        query_id: str = "",
    ) -> None:
        """Feed an observation into the consensus circuit breaker.

        Call sites pass the absolute distance between the miner's response
        and the validator's consensus on a single query, on whatever
        normalized scale the caller chose (typically 0.0 to 1.0). The
        breaker accumulates deviations beyond the tolerance noise floor
        and flags the miner if the cumulative score crosses the threshold.

        No-op when the breaker is not wired or the hotkey is empty. Never
        raises — a tracker hiccup must not break the scoring loop.
        """
        if self._circuit_breaker is None or not hotkey:
            return
        try:
            self._circuit_breaker.record_observation(hotkey=hotkey, deviation=deviation, query_id=query_id)
        except Exception as e:
            log.warning(
                "scorer_cb_record_failed",
                hotkey=hotkey[:10],
                error=str(e)[:100],
            )

    def record_canonical_distance(
        self,
        uid: int,
        distance: float,
    ) -> None:
        """Record one canonical odds distance observation for a miner.

        Called by the validator's /v1/odds/canonical fan-out after
        running the median consensus reducer. ``distance`` is the
        miner's average relative distance from consensus on the
        observations it returned — the same value
        ``miner_distance_scores`` computes.

        Appends to a 20-entry sliding window on the miner's metrics
        so the canonical_agreement_score can be read alongside the
        other scores in compute_weights_detailed. Does NOT currently
        change the final weight — the metric is observe-only until
        the weight-formula integration lands. See DEV-043.
        """
        m = self._miners.get(uid)
        if m is None:
            return
        try:
            d = float(distance)
        except (TypeError, ValueError):
            return
        if d < 0:
            d = 0.0
        m.canonical_distances.append(d)
        if len(m.canonical_distances) > 20:
            m.canonical_distances = m.canonical_distances[-20:]

    def get_or_create(self, uid: int, hotkey: str) -> MinerMetrics:
        """Get or create metrics for a miner.

        If the hotkey changed (miner deregistered and a new one took the UID),
        reset all metrics so the new miner starts fresh, including
        first_seen_at — the new hotkey enters the bootstrap window.

        Also wires the consensus circuit breaker (if attached) onto the
        new metrics so record_query / record_attestation can feed CUSUM
        observations without every call site knowing about the breaker.
        """
        import time as _time

        now = _time.time()
        existing = self._miners.get(uid)
        if existing is not None:
            if existing.hotkey != hotkey:
                log.info("miner_hotkey_changed", uid=uid, old=existing.hotkey, new=hotkey)
                m = MinerMetrics(uid=uid, hotkey=hotkey, first_seen_at=now)
                m._circuit_breaker_ref = self._circuit_breaker
                self._miners[uid] = m
            else:
                if existing._circuit_breaker_ref is None:
                    existing._circuit_breaker_ref = self._circuit_breaker
            return self._miners[uid]
        m = MinerMetrics(uid=uid, hotkey=hotkey, first_seen_at=now)
        m._circuit_breaker_ref = self._circuit_breaker
        self._miners[uid] = m
        return self._miners[uid]

    def update_coldkey(self, uid: int, coldkey: str) -> None:
        """Populate the SS58 coldkey on an already-tracked miner.

        Called from the main validator loop after get_or_create so the
        coldkey-density gate can aggregate UIDs per coldkey without
        reaching back into the metagraph at scoring time. No-op if the
        UID isn't tracked, or the coldkey is empty (we never overwrite
        a populated coldkey with blank).
        """
        m = self._miners.get(uid)
        if m is None or not coldkey:
            return
        m.coldkey = coldkey

    def remove(self, uid: int) -> None:
        """Remove a deregistered miner."""
        self._miners.pop(uid, None)

    def prune_absent(self, active_uids: set[int]) -> int:
        """Remove metrics for UIDs no longer on the metagraph. Returns count pruned."""
        stale = [uid for uid in self._miners if uid not in active_uids]
        for uid in stale:
            del self._miners[uid]
        if stale:
            log.info("scorer_pruned_absent", count=len(stale), uids=stale)
        return len(stale)

    def compute_weights(self, is_active_epoch: bool) -> dict[int, float]:
        """Compute normalized weights for all tracked miners.

        Returns:
            Mapping of miner UID -> weight (0.0 to 1.0), normalized to sum to 1.
        """
        weights, _ = self.compute_weights_detailed(is_active_epoch)
        return weights

    def compute_weights_detailed(self, is_active_epoch: bool) -> tuple[dict[int, float], dict[int, dict]]:
        """Compute normalized weights with per-miner component breakdowns.

        Returns:
            (weights, breakdowns) where weights maps uid -> normalized weight,
            and breakdowns maps uid -> component scores dict.
        """
        if not self._miners:
            return {}, {}

        if is_active_epoch:
            return self._compute_active_weights_detailed()
        return self._compute_empty_weights_detailed()

    def _compute_active_weights(self) -> dict[int, float]:
        weights, _ = self._compute_active_weights_detailed()
        return weights

    def _compute_active_weights_detailed(
        self,
    ) -> tuple[dict[int, float], dict[int, dict]]:
        miners = list(self._miners.values())

        sports_scores = self._compute_sports_scores(miners)
        attestation_scores = self._compute_attestation_scores(miners)
        sports_speed = self._normalize_speed(miners, use_attestation=False)
        attest_speed = self._normalize_speed(miners, use_attestation=True)
        capability_scores = self._compute_capability_scores([m.uid for m in miners])

        has_attestation_data = any(m.attestations_total > 0 for m in miners)

        raw: dict[int, float] = {}
        breakdowns: dict[int, dict] = {}
        for m in miners:
            sports = sports_scores.get(m.uid, 0.0)
            attest = attestation_scores.get(m.uid, 0.0) if has_attestation_data else 0.0
            if has_attestation_data:
                score = (1.0 - self.W_ATTESTATION_BLEND) * sports + self.W_ATTESTATION_BLEND * attest
            else:
                score = sports

            # Volume confidence curve: miners with fewer scored samples
            # get reduced weight. Prevents low-activity miners from earning
            # the same emissions as high-volume ones. Uses sqrt scaling for
            # a smooth ramp (50 samples = 45%, 125 = 71%, 250+ = 100%).
            samples = m.total_scored_samples()
            if samples < self.VOLUME_TARGET:
                import math

                volume_factor = math.sqrt(samples / self.VOLUME_TARGET)
                score *= volume_factor

            # Miners that were challenged for attestation but never produced
            # a valid proof are penalized heavily. Being online isn't enough;
            # you must be able to do the work when asked. Miners that haven't
            # been challenged yet (attestations_total == 0) are unaffected.
            if m.attestations_total > 0 and m.attestations_valid == 0 and not m.proactive_proof_verified:
                score *= 0.05  # 95% penalty

            # Bootstrap window for fresh hotkeys. Closes the registration-
            # window Sybil hole. Gated by feature flag so it can roll out
            # on UID 0 first. Legacy miners with first_seen_at == 0.0 are
            # not in bootstrap (loader convention).
            try:
                from djinn_validator.feature_flags import flags as _ff

                if _ff.new_miner_zero_weight and m.is_in_bootstrap(
                    min_samples=self.BOOTSTRAP_MIN_SAMPLES,
                    min_age_seconds=self.BOOTSTRAP_MIN_AGE_SECONDS,
                ):
                    log.info(
                        "miner_in_bootstrap",
                        uid=m.uid,
                        hotkey=m.hotkey[:10] if m.hotkey else "",
                        samples=m.total_scored_samples(),
                        min_samples=self.BOOTSTRAP_MIN_SAMPLES,
                    )
                    score = 0.0
            except Exception as _bootstrap_err:
                log.warning(
                    "bootstrap_check_failed",
                    uid=m.uid,
                    error=str(_bootstrap_err)[:100],
                )

            # Reliability amplification + shield bonus. Gated by the
            # DJINN_FF_RELIABILITY_WEIGHT flag. The gate only fires once a
            # miner has accumulated RELIAB_GATE_MIN_ASSIGNED lifetime notary
            # duties (evidence threshold). Below that the miner passes
            # through neutrally to avoid zeroing slow new miners. Shield
            # bonus is unconditional per-UID operational premium — sybil
            # farms that share one shield across many UIDs do not get it
            # per-UID and lose the full SHIELD_BONUS multiplier on the
            # UIDs without their own deployment.
            try:
                from djinn_validator.feature_flags import flags as _ff

                if _ff.reliability_weight and score > 0:
                    assigned = m.lifetime_notary_duties_assigned
                    if assigned >= self.RELIAB_GATE_MIN_ASSIGNED:
                        eff_reliab = max(self.RELIAB_FLOOR, m.notary_reliability())
                        score *= eff_reliab
                    if m.shield_installed:
                        score *= 1.0 + self.SHIELD_BONUS
            except Exception as _reliab_err:
                log.warning(
                    "reliability_amplification_failed",
                    uid=m.uid,
                    error=str(_reliab_err)[:100],
                )

            # Proof-complexity amplifier. Gated by DJINN_FF_PROOF_COMPLEXITY_WEIGHT.
            # Multiplier is [1.0, COMPLEXITY_MAX_MULT], log-scaled from the
            # reference byte size. Applies ON TOP of reliability, so a sybil
            # cluster serving tiny sessions gets multiplied by ~1.0x (no uplift)
            # while a miner serving heavy pages gets the full multiplier.
            try:
                from djinn_validator.feature_flags import flags as _ff

                if _ff.proof_complexity_weight and score > 0:
                    mult = self._proof_complexity_multiplier(m)
                    score *= mult
            except Exception as _cx_err:
                log.warning(
                    "proof_complexity_amplifier_failed",
                    uid=m.uid,
                    error=str(_cx_err)[:100],
                )

            # Consensus circuit breaker. When the breaker is wired AND
            # the DJINN_FF_CIRCUIT_BREAKER flag is on, force the score
            # to 0 for any miner currently flagged for sustained
            # deviation. The flag clears via the appeal flow (TBD) or
            # by the slash handler. See
            # project_consensus_circuit_breaker.md for the design.
            try:
                from djinn_validator.feature_flags import flags as _ff

                if (
                    _ff.circuit_breaker
                    and self._circuit_breaker is not None
                    and m.hotkey
                    and self._circuit_breaker.is_flagged(m.hotkey)
                ):
                    state = self._circuit_breaker.get_state(m.hotkey)
                    log.warning(
                        "miner_circuit_breaker_flagged",
                        uid=m.uid,
                        hotkey=m.hotkey[:10],
                        score=round(state.score, 4) if state else None,
                        sample_count=state.sample_count if state else 0,
                    )
                    score = 0.0
            except Exception as _cb_err:
                log.warning(
                    "circuit_breaker_check_failed",
                    uid=m.uid,
                    error=str(_cb_err)[:100],
                )

            raw[m.uid] = score
            breakdowns[m.uid] = {
                "accuracy": m.accuracy_score(),
                "speed": sports_speed.get(m.uid, 0.0),
                "coverage": m.coverage_score(),
                "uptime": m.uptime_score(),
                "capability_score": capability_scores.get(m.uid, 0.3),
                "memory_total_mb": m.memory_total_mb,
                "cpu_cores": m.cpu_cores,
                "capabilities_reported": m.capabilities_reported,
                "sports_score": sports,
                "attest_validity": m.attestation_validity_score(),
                "attest_speed": attest_speed.get(m.uid, 0.0),
                "attestation_score": attest,
                "canonical_agreement": m.canonical_agreement_score(),
                "canonical_samples": len(m.canonical_distances),
                "volume_factor": min(1.0, (m.total_scored_samples() / self.VOLUME_TARGET) ** 0.5),
                "total_samples": m.total_scored_samples(),
                "raw_score": score,
                "queries_total": m.queries_total,
                "queries_correct": m.queries_correct,
                "attestations_total": m.attestations_total,
                "attestations_valid": m.attestations_valid,
                "health_checks_total": m.health_checks_total,
                "health_checks_responded": m.health_checks_responded,
                "consecutive_epochs": m.consecutive_epochs,
                "notary_duties_assigned": m.notary_duties_assigned,
                "notary_duties_completed": m.notary_duties_completed,
                "notary_reliability": round(m.notary_reliability(), 4),
                "notary_capable": m.notary_capable,
                "shield_installed": m.shield_installed,
                "lifetime_notary_duties_assigned": m.lifetime_notary_duties_assigned,
                "avg_prover_bytes": round(m.avg_prover_bytes(), 1),
                "avg_notary_bytes": round(m.avg_notary_bytes(), 1),
                "avg_prover_duration_ms": round(m.avg_prover_duration_ms(), 1),
                "avg_notary_duration_ms": round(m.avg_notary_duration_ms(), 1),
                "proof_complexity_mult": round(self._proof_complexity_multiplier(m), 3),
            }

        return self._normalize(raw), breakdowns

    def _proof_complexity_multiplier(self, m: MinerMetrics) -> float:
        """Return the proof-complexity multiplier in [1.0, COMPLEXITY_MAX_MULT].

        Uses max(avg_prover_bytes, avg_notary_bytes) on whichever side has at
        least COMPLEXITY_GATE_MIN_SESSIONS successful sessions. Below the gate,
        returns 1.0 (neutral). Above the reference, each doubling of bytes
        adds COMPLEXITY_STEP_PER_OCTAVE up to COMPLEXITY_MAX_MULT.

        Rationale: the signal is average bytes per SUCCESSFUL session, not
        total bytes. A sybil cluster sharing one sidecar across 30 UIDs shows
        the SAME avg-bytes per UID as a single honest miner with one sidecar —
        so the 30-UID amplifier is capped at 1x per session. This breaks the
        linear-per-UID tiny-session spray attack.
        """
        # Gate on the sessions where we actually recorded bytes, not the full
        # lifetime valid count. Pre-instrumentation sessions don't tell us anything
        # about payload size.
        prover_ok = m.lifetime_attestation_proof_sessions >= self.COMPLEXITY_GATE_MIN_SESSIONS
        notary_ok = m.lifetime_notary_proof_sessions >= self.COMPLEXITY_GATE_MIN_SESSIONS
        if not (prover_ok or notary_ok):
            return 1.0
        avg_bytes = 0.0
        if prover_ok:
            avg_bytes = max(avg_bytes, m.avg_prover_bytes())
        if notary_ok:
            avg_bytes = max(avg_bytes, m.avg_notary_bytes())
        if avg_bytes <= self.COMPLEXITY_REF_BYTES:
            return 1.0
        # log2 ratio = how many octaves above the reference
        octaves = math.log2(avg_bytes / self.COMPLEXITY_REF_BYTES)
        mult = 1.0 + self.COMPLEXITY_STEP_PER_OCTAVE * octaves
        return max(1.0, min(self.COMPLEXITY_MAX_MULT, mult))

    def _compute_sports_scores(self, miners: list[MinerMetrics]) -> dict[int, float]:
        """Compute per-miner sports scores (unnormalized 0-1 range).

        Miners with no sports queries get 0 — no free speed credit for
        miners that haven't been challenged or haven't responded.

        Notary bonus: miners who reliably serve as peer notaries get up to
        a 10% bonus on their uptime component. This rewards network service
        without changing weight structure (backwards compatible).
        """
        speed_scores = self._normalize_speed(miners, use_attestation=False)
        capability_scores = self._compute_capability_scores([m.uid for m in miners])

        scores: dict[int, float] = {}
        for m in miners:
            # Notary bonus: up to 10% boost on the uptime component
            notary_bonus = 1.0 + 0.10 * m.notary_reliability()
            uptime = m.uptime_score() * notary_bonus
            cap_score = capability_scores.get(m.uid, 0.3)
            if m.queries_total == 0:
                scores[m.uid] = self.W_UPTIME * uptime + self.W_CAPABILITY * cap_score
            else:
                scores[m.uid] = (
                    self.W_ACCURACY * m.accuracy_score()
                    + self.W_SPEED * speed_scores.get(m.uid, 0.0)
                    + self.W_COVERAGE * m.coverage_score()
                    + self.W_UPTIME * uptime
                    + self.W_CANONICAL * m.canonical_agreement_score()
                    + self.W_CAPABILITY * cap_score
                )
        return scores

    # Miners without a notary sidecar get this multiplier on attestation score.
    # They benefit from the network's notary infrastructure without contributing.
    NOTARY_FREERIDER_PENALTY = 0.5

    def _compute_attestation_scores(self, miners: list[MinerMetrics]) -> dict[int, float]:
        """Compute per-miner attestation scores (unnormalized 0-1 range).

        Attestation scoring uses only two axes:
        - Proof validity (60%): did TLSNotary proof verify?
        - Speed (40%): how fast was the attestation?

        Miners not running a notary sidecar receive a 50% penalty on their
        attestation score. This incentivizes every operator to contribute
        notary capacity proportional to their miner count.
        """
        speed_scores = self._normalize_speed(miners, use_attestation=True)

        scores: dict[int, float] = {}
        for m in miners:
            if m.attestations_total == 0:
                scores[m.uid] = 0.0
            else:
                base = self.W_ATTEST_VALIDITY * m.attestation_validity_score() + self.W_ATTEST_SPEED * speed_scores.get(
                    m.uid, 0.0
                )
                if not m.notary_capable:
                    base *= self.NOTARY_FREERIDER_PENALTY
                scores[m.uid] = base
        return scores

    def _compute_capability_scores(self, uids: list[int]) -> dict[int, float]:
        """Score miners based on advertised system capabilities.

        Scoring formula (0-1 range):
        - Memory tier: 0-0.4 based on total RAM (8GB=0.1, 16GB=0.2, 32GB=0.3, 64GB+=0.4)
        - CPU tier: 0-0.2 based on core count (4=0.05, 8=0.1, 16=0.15, 32+=0.2)
        - Availability: 0-0.2 based on memory_available / memory_total ratio
        - Capacity headroom: 0-0.2 based on (max - active) / max for TLSNotary sessions

        Miners that don't report capabilities get 0.3 (neutral, not penalized heavily).
        """
        scores: dict[int, float] = {}
        for uid in uids:
            m = self._miners.get(uid)
            if m is None or not m.capabilities_reported:
                scores[uid] = 0.3  # Neutral score for non-reporting miners
                continue

            score = 0.0

            # Memory tier (0-0.4)
            mem_gb = m.memory_total_mb / 1024
            if mem_gb >= 64:
                score += 0.4
            elif mem_gb >= 32:
                score += 0.3
            elif mem_gb >= 16:
                score += 0.2
            elif mem_gb >= 8:
                score += 0.1

            # CPU tier (0-0.2)
            if m.cpu_cores >= 32:
                score += 0.2
            elif m.cpu_cores >= 16:
                score += 0.15
            elif m.cpu_cores >= 8:
                score += 0.1
            elif m.cpu_cores >= 4:
                score += 0.05

            # Memory availability (0-0.2)
            if m.memory_total_mb > 0:
                avail_ratio = m.memory_available_mb / m.memory_total_mb
                score += min(0.2, avail_ratio * 0.2)

            # Session headroom (0-0.2)
            if m.tlsn_max_concurrent > 0:
                headroom = (m.tlsn_max_concurrent - m.tlsn_active_sessions) / m.tlsn_max_concurrent
                score += min(0.2, max(0.0, headroom) * 0.2)
            elif m.capabilities_reported:
                score += 0.1  # No TLSNotary info but reports other caps

            scores[uid] = min(0.5, score)

        return scores

    def _compute_empty_weights(self) -> dict[int, float]:
        weights, _ = self._compute_empty_weights_detailed()
        return weights

    def _compute_empty_weights_detailed(
        self,
    ) -> tuple[dict[int, float], dict[int, dict]]:
        miners = list(self._miners.values())
        max_history = max((m.consecutive_epochs for m in miners), default=1)

        has_attestation_data = any(m.attestations_total > 0 for m in miners)
        attestation_scores = self._compute_attestation_scores(miners) if has_attestation_data else {}

        attest_speed = self._normalize_speed(miners, use_attestation=True)

        raw: dict[int, float] = {}
        breakdowns: dict[int, dict] = {}
        for m in miners:
            history = math.log1p(m.consecutive_epochs) / math.log1p(max_history) if max_history > 0 else 0.0
            # Floor: any miner that participated this epoch gets at least 30% history
            # credit. Without this, new miners get 0% on 50% of their weight, making
            # it nearly impossible to earn emissions in their first epochs.
            participated = (
                m.health_checks_total > 0
                or m.queries_total > 0
                or m.attestations_total > 0
                or m.notary_duties_assigned > 0
            )
            if participated and history < 0.3:
                history = 0.3
            attest = attestation_scores.get(m.uid, 0.0)
            if has_attestation_data:
                score = (
                    self.W_EMPTY_UPTIME_A * m.uptime_score()
                    + self.W_EMPTY_HISTORY_A * history
                    + self.W_EMPTY_ATTESTATION * attest
                )
            else:
                score = self.W_EMPTY_UPTIME * m.uptime_score() + self.W_EMPTY_HISTORY * history

            # Same penalty as active epochs: challenged but never verified = near zero
            if m.attestations_total > 0 and m.attestations_valid == 0 and not m.proactive_proof_verified:
                score *= 0.05

            raw[m.uid] = score
            breakdowns[m.uid] = {
                "accuracy": 0.0,
                "speed": 0.0,
                "coverage": 0.0,
                "uptime": m.uptime_score(),
                "sports_score": 0.0,
                "attest_validity": m.attestation_validity_score(),
                "attest_speed": attest_speed.get(m.uid, 0.0),
                "attestation_score": attest,
                "history": round(history, 4),
                "raw_score": score,
                "queries_total": m.queries_total,
                "queries_correct": m.queries_correct,
                "attestations_total": m.attestations_total,
                "attestations_valid": m.attestations_valid,
                "health_checks_total": m.health_checks_total,
                "health_checks_responded": m.health_checks_responded,
                "consecutive_epochs": m.consecutive_epochs,
                "notary_duties_assigned": m.notary_duties_assigned,
                "notary_duties_completed": m.notary_duties_completed,
                "notary_reliability": round(m.notary_reliability(), 4),
                "notary_capable": m.notary_capable,
                "shield_installed": m.shield_installed,
                "lifetime_notary_duties_assigned": m.lifetime_notary_duties_assigned,
                "avg_prover_bytes": round(m.avg_prover_bytes(), 1),
                "avg_notary_bytes": round(m.avg_notary_bytes(), 1),
                "avg_prover_duration_ms": round(m.avg_prover_duration_ms(), 1),
                "avg_notary_duration_ms": round(m.avg_notary_duration_ms(), 1),
                "proof_complexity_mult": round(self._proof_complexity_multiplier(m), 3),
            }

        return self._normalize(raw), breakdowns

    def _normalize_speed(self, miners: list[MinerMetrics], *, use_attestation: bool = False) -> dict[int, float]:
        """Normalize speed scores: fastest miner gets 1.0, slowest gets 0.0.

        Args:
            use_attestation: If True, uses attestation_latencies instead of
                sports latencies. This ensures the two challenge types are
                normalized independently (attestation takes 30-90s vs <10s
                for sports).
        """
        avg_latencies: dict[int, float] = {}
        for m in miners:
            lats = m.attestation_latencies if use_attestation else m.latencies
            # Fall back to previous epoch's latencies if none in current epoch
            if not lats and not use_attestation:
                lats = m.prev_latencies
            if lats:
                avg_latencies[m.uid] = sum(lats) / len(lats)

        if not avg_latencies:
            return {m.uid: 0.0 for m in miners}

        min_lat = min(avg_latencies.values())
        max_lat = max(avg_latencies.values())
        spread = max_lat - min_lat

        if spread == 0:
            return {uid: 1.0 for uid in avg_latencies} | {m.uid: 0.0 for m in miners if m.uid not in avg_latencies}

        scores = {uid: 1.0 - (lat - min_lat) / spread for uid, lat in avg_latencies.items()}
        for m in miners:
            if m.uid not in scores:
                scores[m.uid] = 0.0
        return scores

    @staticmethod
    def _normalize(raw: dict[int, float]) -> dict[int, float]:
        """Normalize weights to sum to 1.0.

        Uses epsilon comparison to avoid division by near-zero floating point sums
        that could produce Infinity or extremely large weights. Validates all
        outputs are finite to prevent inf/nan propagation to on-chain weight setting.
        """
        total = sum(raw.values())
        if total < 1e-12:
            return {uid: 0.0 for uid in raw}
        result = {uid: score / total for uid, score in raw.items()}
        if not all(math.isfinite(v) for v in result.values()):
            return {uid: 0.0 for uid in result}
        return result

    def select_attest_miners(self, candidate_uids: list[int], max_results: int = 8) -> list[tuple[int, str]]:
        """Select the best miners for attestation dispatch.

        Returns list of (uid, tier) tuples where tier is:
        - "proven": produced at least one valid attestation proof
        - "unproven": responds to health checks but hasn't been challenged yet
        - "redemption": previously failed but gets a short-timeout retry chance

        Miners cycle through tiers naturally: excluded miners get a redemption
        slot (1 per dispatch, short timeout) so they can recover after fixing
        issues like missing TLSNotary binaries.

        Unproven miners always get at least 2 reserved slots so new joiners
        can earn attestation scores without being crowded out by proven miners.

        Args:
            candidate_uids: UIDs with valid axon info (IP/port).
            max_results: Maximum number of candidates to return.
        """
        import random

        proven: list[tuple[int, float, float]] = []  # (uid, validity_score, median_latency)
        unproven: list[int] = []
        excluded: list[int] = []

        for uid in candidate_uids:
            m = self._miners.get(uid)
            if m is None:
                # Never seen — treat as unproven
                unproven.append(uid)
                continue

            if m.attestations_valid > 0 or m.proactive_proof_verified:
                # Tier 1: has produced valid proofs (challenge or proactive)
                med_lat = (
                    sorted(m.attestation_latencies)[len(m.attestation_latencies) // 2]
                    if m.attestation_latencies
                    else 999.0
                )
                proven.append((uid, m.attestation_validity_score(), med_lat))
            elif m.attestations_total > 0:
                # Tier 3: challenged but never succeeded — track for redemption
                excluded.append(uid)
            elif m.ema_uptime > 0.001:
                # Tier 2: responsive but never challenged for attestation
                unproven.append(uid)
            else:
                # After epoch reset: all counters zero but entry exists.
                # Treat same as unproven so miners aren't invisible.
                unproven.append(uid)

        # Sort proven: highest validity first, then fastest, prefer available capacity
        def _proven_sort_key(t: tuple[int, float, float]) -> tuple[float, float, float]:
            uid, validity, latency = t
            m = self._miners.get(uid)
            # Prefer miners with TLSNotary capacity headroom
            headroom = 0.0
            if m and m.capabilities_reported and m.tlsn_max_concurrent > 0:
                headroom = (m.tlsn_max_concurrent - m.tlsn_active_sessions) / m.tlsn_max_concurrent
            return (-validity, -headroom, latency)

        proven.sort(key=_proven_sort_key)

        # Reserve guaranteed slots for unproven miners so new joiners
        # aren't crowded out when the network has many proven miners.
        reserved_unproven = min(2, len(unproven))
        proven_limit = max_results - reserved_unproven - 1  # -1 for redemption slot

        result: list[tuple[int, str]] = []
        for uid, _, _ in proven:
            if len(result) >= proven_limit:
                break
            result.append((uid, "proven"))

        # Unproven miners: guaranteed 2 reserved slots, plus any remaining
        # space if fewer proven miners filled up.
        unproven_limit = max(reserved_unproven, min(len(unproven), max_results - len(result) - 1))
        random.shuffle(unproven)
        for uid in unproven[:unproven_limit]:
            result.append((uid, "unproven"))

        # Redemption: give 1 random excluded miner a retry chance.
        # Short timeout (handled by caller via "redemption" tier) so it
        # doesn't slow down dispatch if the miner is still broken.
        if excluded and len(result) < max_results:
            pick = random.choice(excluded)
            result.append((pick, "redemption"))
            log.info("attest_redemption_slot", uid=pick, excluded_count=len(excluded))

        return result

    def rank_notary_candidates(self, candidate_uids: list[int]) -> list[tuple[int, float]]:
        """Rank notary candidates by MPC reliability for external prover assignment.

        Combines attestation validity (can this miner complete a TLSNotary proof?)
        with notary duty reliability (does its sidecar stay up through MPC?) and
        uptime. Returns all candidates sorted best-first.

        Returns list of (uid, score) where score is 0.0-1.0.
        """
        scored: list[tuple[int, float]] = []

        for uid in candidate_uids:
            m = self._miners.get(uid)
            if m is None:
                # Never seen by scorer: put at the bottom with zero score
                scored.append((uid, 0.0))
                continue

            # Primary signal: has this miner's notary sidecar produced verified
            # proofs when assigned as notary for other miners?
            nr = m.notary_reliability()  # 0.0 if never assigned

            # Secondary: can this miner itself produce valid attestation proofs?
            # Miners that pass attestation challenges have working TLSNotary stacks.
            av = m.attestation_validity_score()

            # Tertiary: basic liveness
            up = m.uptime_score()

            # Combine. Notary reliability is the strongest signal because it
            # directly measures "did MPC complete when this miner was the notary?"
            # Attestation validity measures the full stack health. Uptime is a
            # tiebreaker for miners with no attestation/notary history.
            # Capacity factor: prefer notaries with available sessions
            cap_factor = 1.0
            if m.capabilities_reported and m.notary_max_concurrent > 0:
                active_ratio = m.notary_active_sessions / m.notary_max_concurrent
                cap_factor = 1.0 - (active_ratio * 0.3)  # Up to 30% penalty when fully loaded

            if m.notary_duties_assigned > 0:
                # Has served as notary before: weight heavily on that track record
                score = (0.50 * nr + 0.35 * av + 0.15 * up) * cap_factor
            elif m.attestations_total > 0:
                # Never assigned as notary but has attestation history
                score = (0.60 * av + 0.40 * up) * cap_factor
            else:
                # No history at all: score on uptime only
                score = 0.30 * up * cap_factor  # Cap at 0.30 so proven miners always rank above

            scored.append((uid, score))

        # Best first
        scored.sort(key=lambda t: -t[1])
        return scored

    def reset_epoch(self) -> None:
        """Reset per-epoch metrics while preserving history.

        Increments consecutive_epochs for miners that participated (responded
        to at least one health check, answered a query, or completed an attestation).
        """
        for m in self._miners.values():
            participated = (
                m.queries_total > 0
                or m.health_checks_total > 0
                or m.attestations_total > 0
                or m.notary_duties_assigned > 0
            )
            if participated:
                m.consecutive_epochs += 1
            else:
                m.consecutive_epochs = 0
            # Carry forward sports accuracy from the previous epoch so miners
            # aren't scored as 0% accuracy between challenge rounds. Challenges
            # run every ~10 minutes but epochs reset every ~12 seconds. Without
            # carry-forward, accuracy is zero for 98% of epochs.
            # Carry forward challenge metrics so they don't zero out between rounds
            if m.queries_total > 0:
                m.prev_accuracy = m.accuracy_score()
            if m.latencies:
                m.prev_latencies = list(m.latencies)
            if m.proofs_requested > 0:
                m.prev_coverage = m.coverage_score()
            m.queries_total = 0
            m.queries_correct = 0
            m.latencies.clear()
            m.proofs_submitted = 0
            m.proofs_verified = 0
            m.proofs_requested = 0
            # Attestation metrics are NOT reset per-epoch.  Attestation
            # challenges are rare events (minutes apart vs. 12-second epochs).
            # Resetting every epoch zeroed them before the next weight
            # computation could use the data.  Instead we let them accumulate
            # so attestation_validity_score() returns a running average.
            # Cap latencies to prevent unbounded growth.
            if len(m.attestation_latencies) > 100:
                m.attestation_latencies = m.attestation_latencies[-50:]
            # Reset notary metrics
            m.notary_duties_assigned = 0
            m.notary_duties_completed = 0
            m.notary_capable = False
            # ema_uptime is NOT reset: it decays naturally via EMA (half-life=1 tempo).
