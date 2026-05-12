"""Tests for MPC batch settlement primitive.

Verifies:
1. compute_gain_vector matches the closed-form Audit.sol formula
2. Single-purchase MPC selection recovers the real-line gain
3. Batch sum across purchases matches the sum of individual gains
4. Negative gains (unfavorable outcomes) flow through the field
   arithmetic and decode back to correct signed values
5. Void and mixed-outcome batches settle correctly
6. Legacy edge cases: 2-line signals, very large/very small notionals,
   boundary outcome enums
"""

from __future__ import annotations

import pytest

from djinn_validator.core.mpc_batch_settlement import (
    BPS_DENOMINATOR,
    ODDS_PRECISION,
    OUTCOME_FAVORABLE,
    OUTCOME_UNFAVORABLE,
    OUTCOME_VOID,
    BatchSession,
    BatchSessionError,
    PurchaseInputs,
    compute_gain_vector,
    decode_field_to_signed,
    local_batch_settle,
    local_batch_settle_revealing_individual_gains,
    simulate_distributed_batch_settle,
)
from djinn_validator.utils.crypto import BN254_PRIME, split_secret


def _shares_for_index(real_index: int, n: int = 3, k: int = 2) -> list:
    """Build Shamir shares of a secret real index."""
    return split_secret(real_index, n=n, k=k, prime=BN254_PRIME)


def _scale_decimal(decimal: float) -> int:
    """Convert a decimal odds value to its ODDS_PRECISION-scaled form."""
    return round(decimal * ODDS_PRECISION)


class TestComputeGainVector:
    """The per-line gain vector must match Audit.sol's settlement formula."""

    def test_favorable_bpa_mode(self) -> None:
        # 3 lines, all favorable, BPA mode.
        # Line odds 1.91 / 1.75 / 2.10, notional $100 (100 * 1e6 units).
        # Expected per-line gain = 100 * (odds - 1) in USDC micro-units.
        inputs = PurchaseInputs(
            purchase_id=1,
            shares=_shares_for_index(2),
            notional=100_000_000,
            sla_bps=500,
            bpa_mode=True,
            bpas=[_scale_decimal(1.91), _scale_decimal(1.75), _scale_decimal(2.10)],
            wpas=[_scale_decimal(1.80), _scale_decimal(1.70), _scale_decimal(2.00)],
            outcomes=[OUTCOME_FAVORABLE, OUTCOME_FAVORABLE, OUTCOME_FAVORABLE],
        )
        v = compute_gain_vector(inputs)
        assert len(v) == 3
        # Each entry is notional * (bpa_scaled - 1e6) / 1e6
        assert v[0] == (100_000_000 * (_scale_decimal(1.91) - ODDS_PRECISION)) // ODDS_PRECISION
        assert v[1] == (100_000_000 * (_scale_decimal(1.75) - ODDS_PRECISION)) // ODDS_PRECISION
        assert v[2] == (100_000_000 * (_scale_decimal(2.10) - ODDS_PRECISION)) // ODDS_PRECISION

    def test_favorable_wpa_mode(self) -> None:
        inputs = PurchaseInputs(
            purchase_id=1,
            shares=_shares_for_index(1),
            notional=100_000_000,
            sla_bps=500,
            bpa_mode=False,  # WPA
            bpas=[_scale_decimal(1.91), _scale_decimal(1.75)],
            wpas=[_scale_decimal(1.80), _scale_decimal(1.70)],
            outcomes=[OUTCOME_FAVORABLE, OUTCOME_FAVORABLE],
        )
        v = compute_gain_vector(inputs)
        # WPA mode should use wpas
        assert v[0] == (100_000_000 * (_scale_decimal(1.80) - ODDS_PRECISION)) // ODDS_PRECISION
        assert v[1] == (100_000_000 * (_scale_decimal(1.70) - ODDS_PRECISION)) // ODDS_PRECISION

    def test_unfavorable_loss(self) -> None:
        # 2 lines, both unfavorable. Loss = notional * sla_bps / 10_000.
        # sla_bps = 1000 = 10%, notional $100 → loss = $10 = 10_000_000 units.
        # Negated to -10_000_000 and wrapped into the field.
        inputs = PurchaseInputs(
            purchase_id=1,
            shares=_shares_for_index(1),
            notional=100_000_000,
            sla_bps=1000,
            bpa_mode=True,
            bpas=[_scale_decimal(1.91), _scale_decimal(2.00)],
            wpas=[_scale_decimal(1.80), _scale_decimal(1.90)],
            outcomes=[OUTCOME_UNFAVORABLE, OUTCOME_UNFAVORABLE],
        )
        v = compute_gain_vector(inputs)
        expected_loss = 10_000_000
        assert decode_field_to_signed(v[0]) == -expected_loss
        assert decode_field_to_signed(v[1]) == -expected_loss

    def test_void_is_zero(self) -> None:
        inputs = PurchaseInputs(
            purchase_id=1,
            shares=_shares_for_index(1),
            notional=100_000_000,
            sla_bps=500,
            bpa_mode=True,
            bpas=[_scale_decimal(1.91), _scale_decimal(2.00)],
            wpas=[_scale_decimal(1.80), _scale_decimal(1.90)],
            outcomes=[OUTCOME_VOID, OUTCOME_VOID],
        )
        v = compute_gain_vector(inputs)
        assert v[0] == 0
        assert v[1] == 0

    def test_mixed_outcomes(self) -> None:
        # One favorable, one unfavorable, one void.
        inputs = PurchaseInputs(
            purchase_id=1,
            shares=_shares_for_index(1),
            notional=100_000_000,
            sla_bps=500,
            bpa_mode=True,
            bpas=[_scale_decimal(1.91), _scale_decimal(2.00), _scale_decimal(1.80)],
            wpas=[_scale_decimal(1.80), _scale_decimal(1.90), _scale_decimal(1.70)],
            outcomes=[OUTCOME_FAVORABLE, OUTCOME_UNFAVORABLE, OUTCOME_VOID],
        )
        v = compute_gain_vector(inputs)
        assert v[0] == (100_000_000 * (_scale_decimal(1.91) - ODDS_PRECISION)) // ODDS_PRECISION
        assert decode_field_to_signed(v[1]) == -((100_000_000 * 500) // BPS_DENOMINATOR)
        assert v[2] == 0

    def test_vector_length_mismatch_rejected(self) -> None:
        inputs = PurchaseInputs(
            purchase_id=1,
            shares=_shares_for_index(1),
            notional=100_000_000,
            sla_bps=500,
            bpa_mode=True,
            bpas=[_scale_decimal(1.91), _scale_decimal(1.75)],
            wpas=[_scale_decimal(1.80)],  # wrong length
            outcomes=[OUTCOME_FAVORABLE, OUTCOME_FAVORABLE],
        )
        with pytest.raises(ValueError, match="same length"):
            compute_gain_vector(inputs)


class TestSinglePurchaseSelection:
    """Single-purchase settle reveals the real-line gain via MPC."""

    def test_favorable_real_pick_recovered(self) -> None:
        # 3 lines, only line 2 is favorable.
        # Notional 100 USDC, BPA line 2 = 1.91 -> expected gain $91.
        real_index = 2
        inputs = PurchaseInputs(
            purchase_id=1,
            shares=_shares_for_index(real_index),
            notional=100_000_000,
            sla_bps=500,
            bpa_mode=True,
            bpas=[_scale_decimal(1.75), _scale_decimal(1.91), _scale_decimal(2.00)],
            wpas=[_scale_decimal(1.70), _scale_decimal(1.80), _scale_decimal(1.90)],
            outcomes=[OUTCOME_VOID, OUTCOME_FAVORABLE, OUTCOME_VOID],
        )
        result = local_batch_settle([inputs], threshold=2)
        assert result.purchase_count == 1
        expected = (100_000_000 * (_scale_decimal(1.91) - ODDS_PRECISION)) // ODDS_PRECISION
        assert result.total_score_change == expected

    def test_unfavorable_real_pick_recovered(self) -> None:
        # Line 1 is unfavorable, others void.
        real_index = 1
        inputs = PurchaseInputs(
            purchase_id=1,
            shares=_shares_for_index(real_index),
            notional=100_000_000,
            sla_bps=500,
            bpa_mode=True,
            bpas=[_scale_decimal(1.91), _scale_decimal(1.75)],
            wpas=[_scale_decimal(1.80), _scale_decimal(1.70)],
            outcomes=[OUTCOME_UNFAVORABLE, OUTCOME_VOID],
        )
        result = local_batch_settle([inputs], threshold=2)
        expected = -((100_000_000 * 500) // BPS_DENOMINATOR)
        assert result.total_score_change == expected

    def test_void_real_pick_returns_zero(self) -> None:
        real_index = 2
        inputs = PurchaseInputs(
            purchase_id=1,
            shares=_shares_for_index(real_index),
            notional=100_000_000,
            sla_bps=500,
            bpa_mode=True,
            bpas=[_scale_decimal(1.91), _scale_decimal(1.75)],
            wpas=[_scale_decimal(1.80), _scale_decimal(1.70)],
            outcomes=[OUTCOME_FAVORABLE, OUTCOME_VOID],
        )
        result = local_batch_settle([inputs], threshold=2)
        assert result.total_score_change == 0

    def test_real_index_outside_first_line(self) -> None:
        # Real index = 3 in a 3-line signal. Sanity check the
        # Lagrange eval picks the correct entry.
        real_index = 3
        inputs = PurchaseInputs(
            purchase_id=1,
            shares=_shares_for_index(real_index),
            notional=50_000_000,
            sla_bps=500,
            bpa_mode=True,
            bpas=[_scale_decimal(1.91), _scale_decimal(1.75), _scale_decimal(2.50)],
            wpas=[_scale_decimal(1.80), _scale_decimal(1.70), _scale_decimal(2.40)],
            outcomes=[OUTCOME_UNFAVORABLE, OUTCOME_VOID, OUTCOME_FAVORABLE],
        )
        result = local_batch_settle([inputs], threshold=2)
        # Line 3 is the real pick. Gain = 50 * (2.5 - 1) = $75
        expected = (50_000_000 * (_scale_decimal(2.50) - ODDS_PRECISION)) // ODDS_PRECISION
        assert result.total_score_change == expected


class TestBatchSumAcrossPurchases:
    """Batch sum should equal the sum of individual per-purchase gains."""

    def _make_purchase(
        self,
        purchase_id: int,
        real_index: int,
        notional: int,
        outcomes: list[int],
        bpa_odds: list[float],
    ) -> PurchaseInputs:
        return PurchaseInputs(
            purchase_id=purchase_id,
            shares=_shares_for_index(real_index),
            notional=notional,
            sla_bps=500,
            bpa_mode=True,
            bpas=[_scale_decimal(o) for o in bpa_odds],
            wpas=[_scale_decimal(o - 0.05) for o in bpa_odds],
            outcomes=outcomes,
        )

    def test_two_favorable_purchases(self) -> None:
        p1 = self._make_purchase(
            purchase_id=1,
            real_index=1,
            notional=100_000_000,
            outcomes=[OUTCOME_FAVORABLE, OUTCOME_VOID],
            bpa_odds=[1.91, 1.75],
        )
        p2 = self._make_purchase(
            purchase_id=2,
            real_index=2,
            notional=50_000_000,
            outcomes=[OUTCOME_VOID, OUTCOME_FAVORABLE],
            bpa_odds=[2.00, 1.80],
        )
        # Expected:
        #   p1 gain = 100 * (1.91 - 1) = $91
        #   p2 gain = 50  * (1.80 - 1) = $40
        #   total   = $131
        expected_p1 = (100_000_000 * (_scale_decimal(1.91) - ODDS_PRECISION)) // ODDS_PRECISION
        expected_p2 = (50_000_000 * (_scale_decimal(1.80) - ODDS_PRECISION)) // ODDS_PRECISION

        result = local_batch_settle([p1, p2], threshold=2)
        assert result.purchase_count == 2
        assert result.total_score_change == expected_p1 + expected_p2

    def test_mixed_outcomes_in_batch(self) -> None:
        # 3 purchases with different outcome types.
        p1 = self._make_purchase(1, 1, 100_000_000, [OUTCOME_FAVORABLE, OUTCOME_VOID], [1.91, 1.75])
        p2 = self._make_purchase(2, 1, 100_000_000, [OUTCOME_UNFAVORABLE, OUTCOME_VOID], [2.00, 1.80])
        p3 = self._make_purchase(3, 2, 100_000_000, [OUTCOME_VOID, OUTCOME_FAVORABLE], [1.50, 2.50])
        result = local_batch_settle([p1, p2, p3], threshold=2)

        expected_p1 = (100_000_000 * (_scale_decimal(1.91) - ODDS_PRECISION)) // ODDS_PRECISION
        expected_p2 = -((100_000_000 * 500) // BPS_DENOMINATOR)  # unfavorable loss
        expected_p3 = (100_000_000 * (_scale_decimal(2.50) - ODDS_PRECISION)) // ODDS_PRECISION
        assert result.total_score_change == expected_p1 + expected_p2 + expected_p3

    def test_per_purchase_debug_helper_matches_sum(self) -> None:
        p1 = self._make_purchase(1, 1, 100_000_000, [OUTCOME_FAVORABLE, OUTCOME_UNFAVORABLE], [1.91, 1.75])
        p2 = self._make_purchase(2, 2, 50_000_000, [OUTCOME_VOID, OUTCOME_FAVORABLE], [1.60, 2.20])
        result, per_purchase = local_batch_settle_revealing_individual_gains(
            [p1, p2],
            threshold=2,
        )
        assert len(per_purchase) == 2
        assert sum(per_purchase) == result.total_score_change

    def test_empty_batch_is_no_op(self) -> None:
        result = local_batch_settle([], threshold=2)
        assert result.total_score_change == 0
        assert result.purchase_count == 0


class TestDecodeFieldToSigned:
    """decode_field_to_signed must round-trip signed integers through
    the field correctly."""

    def test_positive_values_unchanged(self) -> None:
        assert decode_field_to_signed(42) == 42
        assert decode_field_to_signed(1_000_000_000) == 1_000_000_000

    def test_negative_values_wrap_and_decode(self) -> None:
        for original in [-1, -42, -1_000_000_000, -100_000_000_000]:
            wrapped = original % BN254_PRIME
            assert decode_field_to_signed(wrapped) == original

    def test_zero(self) -> None:
        assert decode_field_to_signed(0) == 0


class TestRealisticAuditBatch:
    """End-to-end realistic scenario: 10 purchases in an audit cycle."""

    def test_ten_purchase_audit_batch(self) -> None:
        """10 purchases from the same genius/idiot pair, mixed outcomes."""
        batch: list[PurchaseInputs] = []
        expected_total = 0

        # Purchase 1-4: favorable, real index 1, BPA 1.91
        for pid in range(1, 5):
            batch.append(
                PurchaseInputs(
                    purchase_id=pid,
                    shares=_shares_for_index(1),
                    notional=100_000_000,
                    sla_bps=500,
                    bpa_mode=True,
                    bpas=[_scale_decimal(1.91), _scale_decimal(2.00)],
                    wpas=[_scale_decimal(1.80), _scale_decimal(1.90)],
                    outcomes=[OUTCOME_FAVORABLE, OUTCOME_VOID],
                )
            )
            expected_total += (100_000_000 * (_scale_decimal(1.91) - ODDS_PRECISION)) // ODDS_PRECISION

        # Purchase 5-7: unfavorable, real index 2
        for pid in range(5, 8):
            batch.append(
                PurchaseInputs(
                    purchase_id=pid,
                    shares=_shares_for_index(2),
                    notional=100_000_000,
                    sla_bps=500,
                    bpa_mode=True,
                    bpas=[_scale_decimal(1.91), _scale_decimal(2.00)],
                    wpas=[_scale_decimal(1.80), _scale_decimal(1.90)],
                    outcomes=[OUTCOME_VOID, OUTCOME_UNFAVORABLE],
                )
            )
            expected_total += -((100_000_000 * 500) // BPS_DENOMINATOR)

        # Purchase 8-10: void, real index 1
        for pid in range(8, 11):
            batch.append(
                PurchaseInputs(
                    purchase_id=pid,
                    shares=_shares_for_index(1),
                    notional=100_000_000,
                    sla_bps=500,
                    bpa_mode=True,
                    bpas=[_scale_decimal(1.91), _scale_decimal(2.00)],
                    wpas=[_scale_decimal(1.80), _scale_decimal(1.90)],
                    outcomes=[OUTCOME_VOID, OUTCOME_VOID],
                )
            )
            # gain = 0 for each

        result = local_batch_settle(batch, threshold=2)
        assert result.purchase_count == 10
        assert result.total_score_change == expected_total
        # Ensure signed result came out as a reasonable magnitude
        # (not the gigantic field-wrapped number)
        assert abs(result.total_score_change) < 10**12

    def test_net_negative_batch_decodes_correctly(self) -> None:
        """A batch with more losses than wins produces a negative total."""
        batch = []
        expected_total = 0
        for pid in range(1, 6):
            batch.append(
                PurchaseInputs(
                    purchase_id=pid,
                    shares=_shares_for_index(1),
                    notional=100_000_000,
                    sla_bps=1000,  # 10% SLA
                    bpa_mode=True,
                    bpas=[_scale_decimal(1.91), _scale_decimal(2.00)],
                    wpas=[_scale_decimal(1.80), _scale_decimal(1.90)],
                    outcomes=[OUTCOME_UNFAVORABLE, OUTCOME_VOID],
                )
            )
            expected_total += -((100_000_000 * 1000) // BPS_DENOMINATOR)

        result = local_batch_settle(batch, threshold=2)
        assert result.total_score_change == expected_total
        assert result.total_score_change < 0


# ---------------------------------------------------------------------------
# Distributed (HTTP-shape) simulation must match the local trusted-dealer
# reference across the same inputs. Any divergence is a correctness or
# privacy bug.
# ---------------------------------------------------------------------------


class TestSimulatedDistributedBatchSettle:
    """The simulator is the test oracle for the HTTP runtime. It must
    produce the same totals as ``local_batch_settle`` while keeping all
    per-purchase shares unopened until the final sum is reconstructed.
    """

    def test_matches_local_on_single_favorable_purchase(self) -> None:
        inputs = PurchaseInputs(
            purchase_id=1,
            shares=_shares_for_index(2, n=3, k=3),
            notional=100_000_000,
            sla_bps=500,
            bpa_mode=True,
            bpas=[_scale_decimal(1.91), _scale_decimal(1.75), _scale_decimal(2.10)],
            wpas=[_scale_decimal(1.80), _scale_decimal(1.70), _scale_decimal(2.00)],
            outcomes=[OUTCOME_FAVORABLE, OUTCOME_FAVORABLE, OUTCOME_FAVORABLE],
        )
        ref = local_batch_settle([inputs], threshold=3)
        got = simulate_distributed_batch_settle([inputs], threshold=3)
        assert got.total_score_change == ref.total_score_change
        assert got.purchase_count == 1

    def test_matches_local_on_mixed_outcomes_batch(self) -> None:
        batch = [
            PurchaseInputs(
                purchase_id=1,
                shares=_shares_for_index(1, n=3, k=3),
                notional=100_000_000,
                sla_bps=500,
                bpa_mode=True,
                bpas=[_scale_decimal(1.91), _scale_decimal(2.00), _scale_decimal(1.85)],
                wpas=[_scale_decimal(1.80), _scale_decimal(1.90), _scale_decimal(1.75)],
                outcomes=[OUTCOME_FAVORABLE, OUTCOME_FAVORABLE, OUTCOME_FAVORABLE],
            ),
            PurchaseInputs(
                purchase_id=2,
                shares=_shares_for_index(2, n=3, k=3),
                notional=200_000_000,
                sla_bps=1000,
                bpa_mode=False,
                bpas=[_scale_decimal(1.91), _scale_decimal(2.00), _scale_decimal(1.85)],
                wpas=[_scale_decimal(1.80), _scale_decimal(1.90), _scale_decimal(1.75)],
                outcomes=[OUTCOME_UNFAVORABLE, OUTCOME_UNFAVORABLE, OUTCOME_UNFAVORABLE],
            ),
            PurchaseInputs(
                purchase_id=3,
                shares=_shares_for_index(3, n=3, k=3),
                notional=50_000_000,
                sla_bps=500,
                bpa_mode=True,
                bpas=[_scale_decimal(1.91), _scale_decimal(2.00), _scale_decimal(1.85)],
                wpas=[_scale_decimal(1.80), _scale_decimal(1.90), _scale_decimal(1.75)],
                outcomes=[OUTCOME_VOID, OUTCOME_FAVORABLE, OUTCOME_FAVORABLE],
            ),
        ]
        ref = local_batch_settle(batch, threshold=3)
        got = simulate_distributed_batch_settle(batch, threshold=3)
        assert got.total_score_change == ref.total_score_change
        assert got.purchase_count == 3

    def test_all_unfavorable_produces_negative_total(self) -> None:
        batch = [
            PurchaseInputs(
                purchase_id=i + 1,
                shares=_shares_for_index(1, n=3, k=3),
                notional=100_000_000,
                sla_bps=1000,
                bpa_mode=True,
                bpas=[_scale_decimal(1.91), _scale_decimal(2.00)],
                wpas=[_scale_decimal(1.80), _scale_decimal(1.90)],
                outcomes=[OUTCOME_UNFAVORABLE, OUTCOME_VOID],
            )
            for i in range(4)
        ]
        ref = local_batch_settle(batch, threshold=3)
        got = simulate_distributed_batch_settle(batch, threshold=3)
        assert got.total_score_change == ref.total_score_change
        assert got.total_score_change < 0

    def test_empty_batch_returns_zero(self) -> None:
        got = simulate_distributed_batch_settle([], threshold=3)
        assert got.total_score_change == 0
        assert got.purchase_count == 0

    def test_mismatched_participant_set_rejected(self) -> None:
        """All purchases in a batch must share the same participant
        set — otherwise the running sum share accumulates values at
        different Shamir x-coordinates and cannot be reconstructed."""
        batch = [
            PurchaseInputs(
                purchase_id=1,
                shares=_shares_for_index(1, n=3, k=3),
                notional=100_000_000,
                sla_bps=500,
                bpa_mode=True,
                bpas=[_scale_decimal(1.91), _scale_decimal(2.00)],
                wpas=[_scale_decimal(1.80), _scale_decimal(1.90)],
                outcomes=[OUTCOME_FAVORABLE, OUTCOME_VOID],
            ),
            PurchaseInputs(
                purchase_id=2,
                shares=_shares_for_index(1, n=4, k=3),  # different set
                notional=100_000_000,
                sla_bps=500,
                bpa_mode=True,
                bpas=[_scale_decimal(1.91), _scale_decimal(2.00)],
                wpas=[_scale_decimal(1.80), _scale_decimal(1.90)],
                outcomes=[OUTCOME_FAVORABLE, OUTCOME_VOID],
            ),
        ]
        with pytest.raises(ValueError, match="participant set"):
            simulate_distributed_batch_settle(batch, threshold=3)

    def test_simulation_does_not_reconstruct_index(self) -> None:
        """Sanity check that the simulator never calls reconstruct_at_zero
        on the full Shamir shares (which would leak the realIndex). Does
        the check by wrapping reconstruct_at_zero and verifying it is only
        called on (d, e) reconstructions plus the final sum open — NEVER
        on the raw secret share map.
        """
        import djinn_validator.core.mpc_batch_settlement as mbs
        from djinn_validator.utils.crypto import BN254_PRIME as P

        inputs = PurchaseInputs(
            purchase_id=1,
            shares=_shares_for_index(2, n=3, k=3),
            notional=100_000_000,
            sla_bps=500,
            bpa_mode=True,
            bpas=[_scale_decimal(1.91), _scale_decimal(2.00), _scale_decimal(1.85)],
            wpas=[_scale_decimal(1.80), _scale_decimal(1.90), _scale_decimal(1.75)],
            outcomes=[OUTCOME_FAVORABLE, OUTCOME_FAVORABLE, OUTCOME_FAVORABLE],
        )
        secret_share_map = {s.x: s.y for s in inputs.shares}

        calls: list[dict[int, int]] = []
        real_reconstruct = mbs.reconstruct_at_zero

        def watching_reconstruct(shares_map, prime):
            calls.append(dict(shares_map))
            return real_reconstruct(shares_map, prime)

        mbs.reconstruct_at_zero = watching_reconstruct
        try:
            simulate_distributed_batch_settle([inputs], threshold=3)
        finally:
            mbs.reconstruct_at_zero = real_reconstruct

        # No call's map should equal the raw secret share map — that
        # would mean the simulator reconstructed the realIndex.
        for call_map in calls:
            assert call_map != secret_share_map, "simulator leaked the realIndex via reconstruct_at_zero"


# ---------------------------------------------------------------------------
# Peer-side state machine (BatchSession). Drive it through the full
# lifecycle with N peers in-process and verify the reconstructed total
# matches the simulator.
# ---------------------------------------------------------------------------


def _drive_batch_session_across_peers(
    batch: list[PurchaseInputs],
    threshold: int,
    prime: int = BN254_PRIME,
) -> tuple[list[BatchSession], dict[int, int], int]:
    """Helper: spin up one BatchSession per participant and drive the
    full protocol across all of them in-process.

    Returns (sessions, sum_share_by_x, public_c_0_sum) after every
    session has been ``open()``'d. The caller can then reconstruct
    the batch total from ``sum_share_by_x`` and add the public
    register to get the final score change.
    """
    from djinn_validator.core.mpc import generate_beaver_triples
    from djinn_validator.core.mpc_batch_settlement import (
        compute_gain_vector as _compute_gain_vector,
    )

    ref_shares = batch[0].shares
    participant_xs = sorted(s.x for s in ref_shares)
    share_maps: dict[int, dict[str, int]] = {vx: {} for vx in participant_xs}
    # Each signal has one logical share secret. The Shamir shares at
    # different x coords live on different peers.
    # Build per-peer share lookup: maps signal_id to this peer's y.
    for purchase in batch:
        for s in purchase.shares:
            share_maps[s.x][f"sig-{purchase.purchase_id}"] = s.y

    sessions: dict[int, BatchSession] = {}
    for vx in participant_xs:
        sessions[vx] = BatchSession(
            session_id=f"session-{vx}",
            validator_x=vx,
            participant_xs=participant_xs,
            threshold=threshold,
            prime=prime,
        )

    # Build per-purchase gain vectors + Beaver triples (one set per
    # purchase, split across peers). Each peer gets its own
    # triple-shares slice, mimicking what the coordinator would
    # transmit over HTTP.
    per_peer_purchases: dict[int, list] = {vx: [] for vx in participant_xs}

    for purchase in batch:
        gain_vector = _compute_gain_vector(purchase, prime=prime)
        n_lines = len(gain_vector)
        n_gates = max(0, n_lines - 2)
        if n_gates > 0:
            triples = generate_beaver_triples(
                n_gates,
                n=len(participant_xs),
                k=threshold,
                prime=prime,
                x_coords=participant_xs,
            )
        else:
            triples = []

        for vx in participant_xs:
            peer_triples: list[tuple[int, int, int]] = []
            for g in range(n_gates):
                # Find this peer's slot in the triple's share list.
                ts = triples[g]
                idx = participant_xs.index(vx)
                peer_triples.append(
                    (
                        ts.a_shares[idx].y,
                        ts.b_shares[idx].y,
                        ts.c_shares[idx].y,
                    )
                )
            per_peer_purchases[vx].append(
                (f"sig-{purchase.purchase_id}", gain_vector, purchase.purchase_id, peer_triples)
            )

    # accept_init on each session
    for vx in participant_xs:
        sessions[vx].accept_init(
            per_peer_purchases[vx],
            lambda sig_id, m=share_maps[vx]: m.get(sig_id),
        )

    # Drive gate chain: for each purchase, for each gate, collect
    # (d_i, e_i) from every peer, reconstruct, pass to next gate.
    from djinn_validator.core.mpc import reconstruct_at_zero

    for p_idx, purchase in enumerate(batch):
        gain_vector = _compute_gain_vector(purchase, prime=prime)
        n_gates = max(0, len(gain_vector) - 2)

        if n_gates == 0:
            # 2-line purchase: no gates, accumulate directly
            for vx in participant_xs:
                sessions[vx].accumulate(p_idx, None, None)
            continue

        prev_d = None
        prev_e = None
        for g_idx in range(n_gates):
            d_by_v: dict[int, int] = {}
            e_by_v: dict[int, int] = {}
            for vx in participant_xs:
                d_i, e_i = sessions[vx].compute_gate(p_idx, g_idx, prev_d, prev_e)
                d_by_v[vx] = d_i
                e_by_v[vx] = e_i
            prev_d = reconstruct_at_zero(d_by_v, prime)
            prev_e = reconstruct_at_zero(e_by_v, prime)

        assert prev_d is not None and prev_e is not None
        for vx in participant_xs:
            sessions[vx].accumulate(p_idx, prev_d, prev_e)

    # Open every session and collect the sum shares.
    sum_share_by_x: dict[int, int] = {}
    public_c_0_sum: int | None = None
    for vx in participant_xs:
        share_val, pub = sessions[vx].open()
        sum_share_by_x[vx] = share_val
        if public_c_0_sum is None:
            public_c_0_sum = pub
        else:
            # Every peer must compute the same public c_0 — that's a
            # correctness check for free.
            assert pub == public_c_0_sum, f"peer {vx} public c_0 {pub} != {public_c_0_sum}"

    assert public_c_0_sum is not None
    return list(sessions.values()), sum_share_by_x, public_c_0_sum


class TestBatchSessionStateMachine:
    """Drive BatchSession across N peers in-process and verify the
    total matches simulate_distributed_batch_settle.
    """

    def test_single_favorable_purchase(self) -> None:
        inputs = PurchaseInputs(
            purchase_id=1,
            shares=_shares_for_index(2, n=3, k=3),
            notional=100_000_000,
            sla_bps=500,
            bpa_mode=True,
            bpas=[_scale_decimal(1.91), _scale_decimal(2.00), _scale_decimal(1.85)],
            wpas=[_scale_decimal(1.80), _scale_decimal(1.90), _scale_decimal(1.75)],
            outcomes=[OUTCOME_FAVORABLE, OUTCOME_FAVORABLE, OUTCOME_FAVORABLE],
        )
        from djinn_validator.core.mpc import reconstruct_at_zero
        from djinn_validator.core.mpc_batch_settlement import decode_field_to_signed

        expected = simulate_distributed_batch_settle([inputs], threshold=3)

        _, sum_shares, public_c0 = _drive_batch_session_across_peers([inputs], threshold=3)
        q_minus_c0 = reconstruct_at_zero(sum_shares, BN254_PRIME)
        total = decode_field_to_signed((q_minus_c0 + public_c0) % BN254_PRIME, BN254_PRIME)
        assert total == expected.total_score_change

    def test_mixed_outcomes_batch(self) -> None:
        batch = [
            PurchaseInputs(
                purchase_id=1,
                shares=_shares_for_index(1, n=3, k=3),
                notional=100_000_000,
                sla_bps=500,
                bpa_mode=True,
                bpas=[_scale_decimal(1.91), _scale_decimal(2.00), _scale_decimal(1.85)],
                wpas=[_scale_decimal(1.80), _scale_decimal(1.90), _scale_decimal(1.75)],
                outcomes=[OUTCOME_FAVORABLE, OUTCOME_FAVORABLE, OUTCOME_FAVORABLE],
            ),
            PurchaseInputs(
                purchase_id=2,
                shares=_shares_for_index(3, n=3, k=3),
                notional=200_000_000,
                sla_bps=1000,
                bpa_mode=False,
                bpas=[_scale_decimal(1.91), _scale_decimal(2.00), _scale_decimal(1.85)],
                wpas=[_scale_decimal(1.80), _scale_decimal(1.90), _scale_decimal(1.75)],
                outcomes=[OUTCOME_UNFAVORABLE, OUTCOME_VOID, OUTCOME_FAVORABLE],
            ),
        ]
        from djinn_validator.core.mpc import reconstruct_at_zero
        from djinn_validator.core.mpc_batch_settlement import decode_field_to_signed

        expected = simulate_distributed_batch_settle(batch, threshold=3)
        _, sum_shares, public_c0 = _drive_batch_session_across_peers(batch, threshold=3)
        q_minus_c0 = reconstruct_at_zero(sum_shares, BN254_PRIME)
        total = decode_field_to_signed((q_minus_c0 + public_c0) % BN254_PRIME, BN254_PRIME)
        assert total == expected.total_score_change

    def test_open_before_accumulating_all_purchases_raises(self) -> None:
        inputs = PurchaseInputs(
            purchase_id=1,
            shares=_shares_for_index(2, n=3, k=3),
            notional=100_000_000,
            sla_bps=500,
            bpa_mode=True,
            bpas=[_scale_decimal(1.91), _scale_decimal(2.00), _scale_decimal(1.85)],
            wpas=[_scale_decimal(1.80), _scale_decimal(1.90), _scale_decimal(1.75)],
            outcomes=[OUTCOME_FAVORABLE, OUTCOME_FAVORABLE, OUTCOME_FAVORABLE],
        )
        from djinn_validator.core.mpc_batch_settlement import (
            compute_gain_vector as _cgv,
        )

        gain_vector = _cgv(inputs, prime=BN254_PRIME)
        session = BatchSession(
            session_id="s1",
            validator_x=1,
            participant_xs=[1, 2, 3],
            threshold=3,
        )
        # Seed with a trivial 2-line purchase so n_gates=0 and no triples needed.
        session.accept_init(
            [("sig-1", [1_000_000, 2_000_000], 1, [])],
            lambda sig_id: {"sig-1": 7}.get(sig_id),
        )
        # Don't accumulate; open() should reject.
        with pytest.raises(BatchSessionError, match="0/1 purchases accumulated"):
            session.open()

    def test_double_accumulate_idempotent(self) -> None:
        """v1693: a second accumulate on the same purchase is a silent no-op.

        Pre-v1693 it raised BatchSessionError. Idempotency was added because
        ``_peer_request._PEER_RETRIES=2`` causes the server to process duplicate
        accumulate requests on transient client retries; a raise would treat the
        second one as protocol_failed and abort the whole shadow_settle.
        Mirrors v1692 init / v1693 compute_gate / open idempotency.
        """
        session = BatchSession(
            session_id="s1",
            validator_x=1,
            participant_xs=[1, 2, 3],
            threshold=3,
        )
        session.accept_init(
            [("sig-1", [1_000_000, 2_000_000], 1, [])],
            lambda sig_id: {"sig-1": 7}.get(sig_id),
        )
        session.accumulate(0, None, None)
        # Second call must NOT raise (was BatchSessionError pre-v1693). The
        # sum_share is already folded; a no-op preserves it without double-
        # counting.
        session.accumulate(0, None, None)
        # State unchanged after the no-op: still exactly 1 of 1 accumulated.
        assert session._purchases[0].accumulated is True

    def test_accept_init_twice_rejected(self) -> None:
        session = BatchSession(
            session_id="s1",
            validator_x=1,
            participant_xs=[1, 2, 3],
            threshold=3,
        )
        purchases = [("sig-1", [1_000_000, 2_000_000], 1, [])]
        lookup = lambda sig_id: {"sig-1": 7}.get(sig_id)
        session.accept_init(purchases, lookup)
        with pytest.raises(BatchSessionError, match="accept_init called twice"):
            session.accept_init(purchases, lookup)

    def test_missing_share_rejected(self) -> None:
        session = BatchSession(
            session_id="s1",
            validator_x=1,
            participant_xs=[1, 2, 3],
            threshold=3,
        )
        with pytest.raises(BatchSessionError, match="no local Shamir share"):
            session.accept_init(
                [("sig-unknown", [1_000_000, 2_000_000], 1, [])],
                lambda sig_id: None,
            )

    def test_reused_beaver_triple_rejected(self) -> None:
        """Codex audit H#4: each Beaver triple (a,b,c) must be one-time-use
        per session. Reusing a triple across two purchases (or two gates
        in the same purchase) breaks the multiplication protocol's
        privacy by leaking linear relations.
        """
        session = BatchSession(
            session_id="s-reuse",
            validator_x=1,
            participant_xs=[1, 2, 3],
            threshold=3,
        )
        # Same triple reused for two 3-line purchases (each needs 1 gate).
        same_triple = [(11111, 22222, 33333)]
        with pytest.raises(BatchSessionError, match="beaver triple reused"):
            session.accept_init(
                [
                    ("sig-1", [1_000_000, 2_000_000, 3_000_000], 1, same_triple),
                    ("sig-2", [1_500_000, 2_500_000, 3_500_000], 2, same_triple),
                ],
                lambda sig_id: {"sig-1": 7, "sig-2": 9}.get(sig_id),
            )

    def test_malformed_triple_rejected(self) -> None:
        session = BatchSession(
            session_id="s-bad",
            validator_x=1,
            participant_xs=[1, 2, 3],
            threshold=3,
        )
        with pytest.raises(BatchSessionError, match="malformed triple"):
            session.accept_init(
                [("sig-x", [1_000_000, 2_000_000, 3_000_000], 1, [(1, 2)])],
                lambda sig_id: {"sig-x": 7}.get(sig_id),
            )

    def test_out_of_order_gate_rejected(self) -> None:
        # 3-line purchase has 1 gate. Skipping straight to gate 1 is a
        # protocol violation.
        from djinn_validator.core.mpc import generate_beaver_triples

        session = BatchSession(
            session_id="s1",
            validator_x=1,
            participant_xs=[1, 2, 3],
            threshold=3,
        )
        triples = generate_beaver_triples(
            1,
            n=3,
            k=3,
            prime=BN254_PRIME,
            x_coords=[1, 2, 3],
        )
        peer_triples = [
            (
                triples[0].a_shares[0].y,
                triples[0].b_shares[0].y,
                triples[0].c_shares[0].y,
            )
        ]
        session.accept_init(
            [("sig-1", [1_000_000, 2_000_000, 3_000_000], 1, peer_triples)],
            lambda sig_id: {"sig-1": 7}.get(sig_id),
        )
        with pytest.raises(BatchSessionError, match="expected gate 0"):
            session.compute_gate(0, 1, None, None)

    def test_validator_x_must_be_in_participant_set(self) -> None:
        with pytest.raises(BatchSessionError, match="validator_x 99 not in"):
            BatchSession(
                session_id="s1",
                validator_x=99,
                participant_xs=[1, 2, 3],
                threshold=3,
            )

    def test_purchase_count_respects_threshold(self) -> None:
        with pytest.raises(BatchSessionError, match="participant count"):
            BatchSession(
                session_id="s1",
                validator_x=1,
                participant_xs=[1, 2],
                threshold=3,
            )

    def test_build_purchase_inputs_from_audit_set_happy_path(self) -> None:
        from dataclasses import dataclass, field
        from djinn_validator.core.audit_set import AuditSet, AuditSignal
        from djinn_validator.core.outcomes import Outcome
        from djinn_validator.core.mpc_batch_settlement import (
            build_purchase_inputs_from_audit_set,
        )

        # Fake share_store: returns a pretend record with a Shamir share.
        @dataclass
        class _FakeRec:
            share: "Any"
            encrypted_index_share: bytes

        class _FakeShareStore:
            def __init__(self, x: int, y: int):
                from djinn_validator.utils.crypto import Share as _Share

                self._rec = _FakeRec(
                    share=_Share(x=x, y=y),
                    encrypted_index_share=(5).to_bytes(32, "big"),
                )

            def get(self, signal_id: str):
                return self._rec

        # Fake ledger: returns BPA/WPA per-signal.
        @dataclass
        class _FakeLedgerRec:
            bpa_mode: bool
            bpas: list
            wpas: list

        class _FakeLedger:
            def __init__(self, n_lines: int):
                self._rec = _FakeLedgerRec(
                    bpa_mode=True,
                    bpas=[1_900_000 + i for i in range(n_lines)],
                    wpas=[1_800_000 + i for i in range(n_lines)],
                )

            def get(self, *, signal_id: str, buyer_address: str):
                return self._rec

        audit_set = AuditSet(
            genius_address="0xG",
            idiot_address="0xI",
            cycle=0,
            version=2,
        )
        audit_set.signals["sig-1"] = AuditSignal(
            signal_id="sig-1",
            purchase_id=42,
            outcomes=[Outcome.FAVORABLE, Outcome.FAVORABLE, Outcome.UNFAVORABLE],
            notional=100_000_000,
            odds=1_950_000,
            sla_bps=500,
        )

        batch = build_purchase_inputs_from_audit_set(
            audit_set,
            share_store=_FakeShareStore(x=1, y=12345),
            purchase_odds_ledger=_FakeLedger(n_lines=3),
        )
        assert batch is not None
        assert len(batch) == 1
        pi = batch[0]
        assert pi.purchase_id == 42
        assert pi.signal_id == "sig-1"
        assert pi.notional == 100_000_000
        assert pi.sla_bps == 500
        assert pi.bpa_mode is True
        assert len(pi.bpas) == 3
        assert len(pi.outcomes) == 3
        assert pi.outcomes[0] == Outcome.FAVORABLE.value

    def test_build_purchase_inputs_v2_abstains_when_any_signal_unbuildable(self) -> None:
        """Regression for P0-01 Stage B (v1576).

        Silently skipping unbuildable signals in v2 produced
        per-validator batch divergence: validator A with all data
        built a 3-signal batch, validator B with partial data built
        a 2-signal batch, their batchKey = keccak256(genius, idiot,
        keccak256(purchase_ids)) differed, votes never coalesced,
        and OutcomeVoting quorum could not form. Observed on-chain
        as 8 VoteSubmitted events with 0 QuorumReached.

        The canonical fix: abstain from the whole batch whenever any
        signal in audit_set.signals is missing outcomes, shares, or
        BPA/WPA. Validators that vote are guaranteed to agree on the
        pid set.
        """
        from dataclasses import dataclass
        from djinn_validator.core.audit_set import AuditSet, AuditSignal
        from djinn_validator.core.outcomes import Outcome
        from djinn_validator.core.mpc_batch_settlement import (
            build_purchase_inputs_from_audit_set,
        )
        from djinn_validator.utils.crypto import Share as _Share

        @dataclass
        class _Rec:
            share: object
            encrypted_index_share: bytes

        class _ShareStore:
            """Returns a share only for sig-good; sig-no-share returns None."""

            def get(self, signal_id: str):
                if signal_id == "sig-good":
                    return _Rec(
                        share=_Share(x=1, y=12345),
                        encrypted_index_share=(5).to_bytes(32, "big"),
                    )
                return None

        @dataclass
        class _LedgerRec:
            bpa_mode: bool
            bpas: list
            wpas: list

        class _Ledger:
            """Returns BPA/WPA only for sig-good and sig-no-share."""

            def get(self, *, signal_id, buyer_address):
                if signal_id in ("sig-good", "sig-no-share"):
                    return _LedgerRec(
                        bpa_mode=True,
                        bpas=[1_900_000, 1_800_000, 1_700_000],
                        wpas=[1_800_000, 1_700_000, 1_600_000],
                    )
                return None

        audit_set = AuditSet(
            genius_address="0xG",
            idiot_address="0xI",
            cycle=0,
            version=2,
        )
        # resolved + share + ledger row -> builds
        audit_set.signals["sig-good"] = AuditSignal(
            signal_id="sig-good",
            purchase_id=1,
            outcomes=[Outcome.FAVORABLE, Outcome.UNFAVORABLE, Outcome.VOID],
            notional=100_000_000,
            odds=1_950_000,
            sla_bps=500,
        )
        # resolved + NO share -> skipped
        audit_set.signals["sig-no-share"] = AuditSignal(
            signal_id="sig-no-share",
            purchase_id=2,
            outcomes=[Outcome.FAVORABLE, Outcome.UNFAVORABLE, Outcome.VOID],
            notional=100_000_000,
            odds=1_950_000,
            sla_bps=500,
        )
        # unresolved -> skipped (not in resolved_signals)
        audit_set.signals["sig-unresolved"] = AuditSignal(
            signal_id="sig-unresolved",
            purchase_id=3,
            outcomes=None,
            notional=100_000_000,
            odds=1_950_000,
            sla_bps=500,
        )

        batch = build_purchase_inputs_from_audit_set(
            audit_set,
            share_store=_ShareStore(),
            purchase_odds_ledger=_Ledger(),
        )
        # Canonical abstention: sig-unresolved lacks outcomes and
        # sig-no-share lacks its Shamir share, so the validator must
        # abstain from the entire batch rather than submit a partial
        # vote that diverges from peers.
        assert batch is None, (
            f"validator must abstain when any signal in audit_set is "
            f"unbuildable; got batch={batch!r}"
        )

    def test_build_purchase_inputs_returns_none_when_outcomes_missing(self) -> None:
        from djinn_validator.core.audit_set import AuditSet, AuditSignal
        from djinn_validator.core.mpc_batch_settlement import (
            build_purchase_inputs_from_audit_set,
        )

        audit_set = AuditSet(
            genius_address="0xG",
            idiot_address="0xI",
            cycle=0,
            version=2,
        )
        audit_set.signals["sig-1"] = AuditSignal(
            signal_id="sig-1",
            purchase_id=42,
            outcomes=None,  # <-- not resolved
            notional=100_000_000,
            odds=1_950_000,
            sla_bps=500,
        )

        class _StubStore:
            def get(self, sig):
                return None

        class _StubLedger:
            def get(self, *, signal_id, buyer_address):
                return None

        result = build_purchase_inputs_from_audit_set(
            audit_set,
            share_store=_StubStore(),
            purchase_odds_ledger=_StubLedger(),
        )
        assert result is None

    def test_build_purchase_inputs_returns_none_when_ledger_missing(self) -> None:
        from dataclasses import dataclass
        from djinn_validator.core.audit_set import AuditSet, AuditSignal
        from djinn_validator.core.outcomes import Outcome
        from djinn_validator.core.mpc_batch_settlement import (
            build_purchase_inputs_from_audit_set,
        )
        from djinn_validator.utils.crypto import Share as _Share

        @dataclass
        class _Rec:
            share: "Any"
            encrypted_index_share: bytes

        class _Store:
            def get(self, sig):
                return _Rec(
                    share=_Share(x=1, y=9),
                    encrypted_index_share=(5).to_bytes(32, "big"),
                )

        class _EmptyLedger:
            def get(self, *, signal_id, buyer_address):
                return None  # <-- no BPA/WPA record

        audit_set = AuditSet(
            genius_address="0xG",
            idiot_address="0xI",
            cycle=0,
            version=1,
        )
        audit_set.signals["sig-1"] = AuditSignal(
            signal_id="sig-1",
            purchase_id=42,
            outcomes=[Outcome.FAVORABLE, Outcome.VOID, Outcome.UNFAVORABLE],
            notional=100_000_000,
            odds=1_950_000,
            sla_bps=500,
        )

        result = build_purchase_inputs_from_audit_set(
            audit_set,
            share_store=_Store(),
            purchase_odds_ledger=_EmptyLedger(),
        )
        assert result is None

    def test_build_purchase_inputs_returns_none_when_vector_length_mismatch(self) -> None:
        from dataclasses import dataclass
        from djinn_validator.core.audit_set import AuditSet, AuditSignal
        from djinn_validator.core.outcomes import Outcome
        from djinn_validator.core.mpc_batch_settlement import (
            build_purchase_inputs_from_audit_set,
        )
        from djinn_validator.utils.crypto import Share as _Share

        @dataclass
        class _Rec:
            share: "Any"
            encrypted_index_share: bytes

        class _Store:
            def get(self, sig):
                return _Rec(
                    share=_Share(x=1, y=9),
                    encrypted_index_share=(5).to_bytes(32, "big"),
                )

        @dataclass
        class _LedgerRec:
            bpa_mode: bool
            bpas: list
            wpas: list

        class _Ledger:
            def __init__(self):
                # 5 BPA, 3 WPA — mismatch
                self._rec = _LedgerRec(
                    bpa_mode=True,
                    bpas=[1, 2, 3, 4, 5],
                    wpas=[1, 2, 3],
                )

            def get(self, *, signal_id, buyer_address):
                return self._rec

        audit_set = AuditSet(
            genius_address="0xG",
            idiot_address="0xI",
            cycle=0,
            version=1,
        )
        audit_set.signals["sig-1"] = AuditSignal(
            signal_id="sig-1",
            purchase_id=42,
            outcomes=[Outcome.FAVORABLE, Outcome.VOID, Outcome.UNFAVORABLE],
            notional=100_000_000,
            odds=1_950_000,
            sla_bps=500,
        )

        result = build_purchase_inputs_from_audit_set(
            audit_set,
            share_store=_Store(),
            purchase_odds_ledger=_Ledger(),
        )
        assert result is None

    def test_build_purchase_inputs_canonical_order_across_validators(self) -> None:
        """P0-01 Stage B (v1576): determinism regression.

        Two validators that insert the same signals into audit_set in
        DIFFERENT insertion orders (Python dict preserves insertion
        order) must still produce the same
        [p.purchase_id for p in batch] array. If the sort breaks, the
        resulting on-chain batchKey diverges across voters and
        OutcomeVoting quorum can never form.
        """
        from dataclasses import dataclass
        from djinn_validator.core.audit_set import AuditSet, AuditSignal
        from djinn_validator.core.outcomes import Outcome
        from djinn_validator.core.mpc_batch_settlement import (
            build_purchase_inputs_from_audit_set,
        )
        from djinn_validator.utils.crypto import Share as _Share

        @dataclass
        class _Rec:
            share: "Any"
            encrypted_index_share: bytes

        class _Store:
            def get(self, sig):
                return _Rec(
                    share=_Share(x=1, y=12345),
                    encrypted_index_share=(5).to_bytes(32, "big"),
                )

        @dataclass
        class _LedgerRec:
            bpa_mode: bool
            bpas: list
            wpas: list

        class _Ledger:
            def get(self, *, signal_id, buyer_address):
                return _LedgerRec(
                    bpa_mode=True,
                    bpas=[1_900_000, 1_800_000, 1_700_000],
                    wpas=[1_800_000, 1_700_000, 1_600_000],
                )

        def _mk_signal(sid: str, pid: int) -> AuditSignal:
            return AuditSignal(
                signal_id=sid,
                purchase_id=pid,
                outcomes=[Outcome.FAVORABLE, Outcome.UNFAVORABLE, Outcome.VOID],
                notional=100_000_000,
                odds=1_950_000,
                sla_bps=500,
            )

        # Validator A inserts in order pid=3, pid=1, pid=2
        set_a = AuditSet(genius_address="0xG", idiot_address="0xI", cycle=0, version=2)
        set_a.signals["sig-3"] = _mk_signal("sig-3", 3)
        set_a.signals["sig-1"] = _mk_signal("sig-1", 1)
        set_a.signals["sig-2"] = _mk_signal("sig-2", 2)

        # Validator B inserts in order pid=1, pid=2, pid=3
        set_b = AuditSet(genius_address="0xG", idiot_address="0xI", cycle=0, version=2)
        set_b.signals["sig-1"] = _mk_signal("sig-1", 1)
        set_b.signals["sig-2"] = _mk_signal("sig-2", 2)
        set_b.signals["sig-3"] = _mk_signal("sig-3", 3)

        batch_a = build_purchase_inputs_from_audit_set(
            set_a, share_store=_Store(), purchase_odds_ledger=_Ledger()
        )
        batch_b = build_purchase_inputs_from_audit_set(
            set_b, share_store=_Store(), purchase_odds_ledger=_Ledger()
        )
        assert batch_a is not None and batch_b is not None
        pids_a = [p.purchase_id for p in batch_a]
        pids_b = [p.purchase_id for p in batch_b]
        assert pids_a == [1, 2, 3], f"validator A must sort canonically, got {pids_a}"
        assert pids_b == [1, 2, 3], f"validator B must sort canonically, got {pids_b}"
        assert pids_a == pids_b, (
            "batch pid order must be insertion-order-independent so "
            "on-chain batchKey = keccak256(g, i, keccak256(pids)) matches "
            f"across voters; got A={pids_a} B={pids_b}"
        )

    def test_generate_batch_beaver_triples_returns_one_list_per_purchase(self) -> None:
        from djinn_validator.core.mpc_batch_settlement import (
            generate_batch_beaver_triples,
        )

        batch = [
            PurchaseInputs(
                purchase_id=1,
                shares=_shares_for_index(2, n=3, k=3),
                notional=100_000_000,
                sla_bps=500,
                bpa_mode=True,
                bpas=[_scale_decimal(1.91), _scale_decimal(2.00), _scale_decimal(1.85)],
                wpas=[_scale_decimal(1.80), _scale_decimal(1.90), _scale_decimal(1.75)],
                outcomes=[OUTCOME_FAVORABLE, OUTCOME_FAVORABLE, OUTCOME_FAVORABLE],
            ),
            PurchaseInputs(
                purchase_id=2,
                shares=_shares_for_index(1, n=3, k=3),
                notional=50_000_000,
                sla_bps=500,
                bpa_mode=True,
                bpas=[_scale_decimal(1.91), _scale_decimal(2.00)],
                wpas=[_scale_decimal(1.80), _scale_decimal(1.90)],
                outcomes=[OUTCOME_FAVORABLE, OUTCOME_FAVORABLE],
            ),
        ]
        triples = generate_batch_beaver_triples(
            batch,
            participant_xs=[1, 2, 3],
            threshold=3,
        )
        assert len(triples) == 2
        # First purchase has 3 lines -> 1 power gate -> 1 triple
        assert len(triples[0]) == 1
        # Second purchase has 2 lines -> 0 power gates -> empty list
        assert triples[1] == []

    def test_generate_batch_beaver_triples_empty_batch(self) -> None:
        from djinn_validator.core.mpc_batch_settlement import (
            generate_batch_beaver_triples,
        )

        assert generate_batch_beaver_triples([], participant_xs=[1, 2, 3], threshold=3) == []

    def test_generate_batch_beaver_triples_feeds_drive_http(self) -> None:
        """End-to-end: generate triples then drive the simulated
        batch protocol using them. Verifies the helper produces
        triples in the shape the driver expects."""
        import asyncio as _asyncio
        from djinn_validator.core.mpc_batch_settlement import (
            generate_batch_beaver_triples,
            drive_http_batch_settlement,
            simulate_distributed_batch_settle,
        )

        batch = [
            PurchaseInputs(
                purchase_id=100,
                shares=_shares_for_index(2, n=3, k=3),
                notional=100_000_000,
                sla_bps=500,
                bpa_mode=True,
                bpas=[_scale_decimal(1.91), _scale_decimal(2.00), _scale_decimal(1.85)],
                wpas=[_scale_decimal(1.80), _scale_decimal(1.90), _scale_decimal(1.75)],
                outcomes=[OUTCOME_FAVORABLE, OUTCOME_FAVORABLE, OUTCOME_FAVORABLE],
            ),
        ]
        triples = generate_batch_beaver_triples(
            batch,
            participant_xs=[1, 2, 3],
            threshold=3,
        )

        # Build a minimal in-memory peer_rpc that drives three
        # BatchSession instances (mimicking the three-peer network
        # without FastAPI / HTTP).
        from djinn_validator.core.mpc_batch_settlement import (
            BatchSession,
        )

        sessions: dict[int, BatchSession] = {}
        share_maps: dict[int, dict[str, int]] = {}
        for purchase in batch:
            for s in purchase.shares:
                share_maps.setdefault(s.x, {})[f"sig-{purchase.purchase_id}"] = int(s.y)
        for vx in [1, 2, 3]:
            sessions[vx] = BatchSession(
                session_id="test-session",
                validator_x=vx,
                participant_xs=[1, 2, 3],
                threshold=3,
            )

        accepted: set[int] = set()

        async def peer_rpc(vx: int, endpoint: str, payload: dict) -> dict:
            sess = sessions[vx]
            if endpoint == "init":
                purchase_specs = []
                x_idx = [1, 2, 3].index(vx)
                for p_idx, purchase_spec in enumerate(payload["purchases"]):
                    gv = [int(g, 16) for g in purchase_spec["gain_vector"]]
                    peer_triples_for_this_purchase = []
                    for t in triples[p_idx]:
                        peer_triples_for_this_purchase.append(
                            (
                                t.a_shares[x_idx].y,
                                t.b_shares[x_idx].y,
                                t.c_shares[x_idx].y,
                            )
                        )
                    purchase_specs.append(
                        (
                            purchase_spec["signal_id"],
                            gv,
                            purchase_spec["purchase_id"],
                            peer_triples_for_this_purchase,
                        )
                    )
                sess.accept_init(
                    purchase_specs,
                    lambda sig_id, _v=vx: share_maps[_v].get(sig_id),
                )
                accepted.add(vx)
                return {"session_id": "test", "accepted": True, "purchase_count": len(batch)}
            if endpoint == "compute_gate":
                prev_d = int(payload["prev_opened_d"], 16) if payload.get("prev_opened_d") else None
                prev_e = int(payload["prev_opened_e"], 16) if payload.get("prev_opened_e") else None
                d_i, e_i = sess.compute_gate(
                    payload["purchase_idx"],
                    payload["gate_idx"],
                    prev_d,
                    prev_e,
                )
                return {
                    "session_id": "test",
                    "purchase_idx": payload["purchase_idx"],
                    "gate_idx": payload["gate_idx"],
                    "d_value": hex(d_i),
                    "e_value": hex(e_i),
                }
            if endpoint == "accumulate":
                last_d = int(payload["last_opened_d"], 16)
                last_e = int(payload["last_opened_e"], 16)
                sess.accumulate(payload["purchase_idx"], last_d, last_e)
                return {
                    "session_id": "test",
                    "purchase_idx": payload["purchase_idx"],
                    "accumulated": True,
                    "purchases_accumulated_so_far": sess.purchases_accumulated,
                }
            if endpoint == "open":
                s, c0 = sess.open()
                return {
                    "session_id": "test",
                    "sum_share": hex(s),
                    "purchases_accumulated": sess.purchase_count,
                    "validator_x": vx,
                    "public_c_0_sum": hex(c0),
                }
            raise RuntimeError(f"unexpected endpoint {endpoint}")

        result = _asyncio.run(
            drive_http_batch_settlement(
                session_id="test-session",
                participant_xs=[1, 2, 3],
                threshold=3,
                batch=batch,
                beaver_triples_per_purchase=triples,
                peer_rpc=peer_rpc,
            )
        )
        expected = simulate_distributed_batch_settle(batch, threshold=3)
        assert result.total_score_change == expected.total_score_change

    def test_running_share_never_exposed_via_getattr(self) -> None:
        """The private running sum must only come out of open()."""
        session = BatchSession(
            session_id="s1",
            validator_x=1,
            participant_xs=[1, 2, 3],
            threshold=3,
        )
        session.accept_init(
            [("sig-1", [1_000_000, 2_000_000], 1, [])],
            lambda sig_id: {"sig-1": 7}.get(sig_id),
        )
        session.accumulate(0, None, None)
        # Public API must not expose any method named like
        # "get_running_share" or similar. If the state machine
        # grows such a method later it will be caught here so we
        # rethink the privacy invariant.
        public_names = [n for n in dir(session) if not n.startswith("_")]
        for name in public_names:
            assert "running" not in name.lower(), f"public attribute {name} leaks running sum state"
            assert name not in (
                "get_outcome_share",
                "get_per_purchase_share",
            ), f"public attribute {name} leaks per-purchase state"


class TestBuildPiAbstainReasonMetric:
    """v1698 regression: build_pi must tick BUILD_PI_ABSTAIN_REASON{reason=...}
    on each early return so operators can see WHY abstain_no_batch fired.

    SHADOW_SETTLE_OUTCOME{outcome=abstain_no_batch} on UID 1 was 314 of 444
    attempts (70%) and the high-level counter doesn't tell us whether to
    prioritize share recovery, BPA/WPA gossip (P1-33), or upstream signal
    resolution. These tests pin one tick per cause.
    """

    def _read_reason(self, reason: str) -> float:
        """Read current value of BUILD_PI_ABSTAIN_REASON for a given reason."""
        from djinn_validator.api.metrics import BUILD_PI_ABSTAIN_REASON

        # prometheus_client exposes ._value.get() on each child Counter.
        return float(BUILD_PI_ABSTAIN_REASON.labels(reason=reason)._value.get())

    def test_no_audit_set_label_increments(self) -> None:
        from djinn_validator.core.mpc_batch_settlement import (
            build_purchase_inputs_from_audit_set,
        )

        before = self._read_reason("no_audit_set")
        result = build_purchase_inputs_from_audit_set(
            None, share_store=None, purchase_odds_ledger=None
        )
        assert result is None
        assert self._read_reason("no_audit_set") == before + 1.0

    def test_no_resolved_label_increments(self) -> None:
        from djinn_validator.core.audit_set import AuditSet, AuditSignal
        from djinn_validator.core.mpc_batch_settlement import (
            build_purchase_inputs_from_audit_set,
        )

        audit_set = AuditSet(
            genius_address="0xG", idiot_address="0xI", cycle=0, version=2
        )
        # signal exists but outcomes=None so resolved set is empty
        audit_set.signals["sig-pending"] = AuditSignal(
            signal_id="sig-pending",
            purchase_id=1,
            outcomes=None,
            notional=100_000_000,
            odds=1_950_000,
            sla_bps=500,
        )
        before = self._read_reason("no_resolved")
        result = build_purchase_inputs_from_audit_set(
            audit_set, share_store=None, purchase_odds_ledger=None
        )
        assert result is None
        assert self._read_reason("no_resolved") == before + 1.0

    def test_missing_share_label_increments(self) -> None:
        from djinn_validator.core.audit_set import AuditSet, AuditSignal
        from djinn_validator.core.outcomes import Outcome
        from djinn_validator.core.mpc_batch_settlement import (
            build_purchase_inputs_from_audit_set,
        )

        class _NoShareStore:
            def get(self, sig):
                return None

        class _AnyLedger:
            def get(self, *, signal_id, buyer_address):
                return None

        audit_set = AuditSet(
            genius_address="0xG", idiot_address="0xI", cycle=0, version=2
        )
        audit_set.signals["sig-1"] = AuditSignal(
            signal_id="sig-1",
            purchase_id=1,
            outcomes=[Outcome.FAVORABLE, Outcome.UNFAVORABLE, Outcome.VOID],
            notional=100_000_000,
            odds=1_950_000,
            sla_bps=500,
        )
        before = self._read_reason("missing_share")
        result = build_purchase_inputs_from_audit_set(
            audit_set,
            share_store=_NoShareStore(),
            purchase_odds_ledger=_AnyLedger(),
        )
        assert result is None
        assert self._read_reason("missing_share") == before + 1.0

    def test_empty_index_share_label_increments(self) -> None:
        """v1700: distinguish 'no record at all' from 'record present but
        index share is empty bytes'. Pre-v1700 both rolled into missing_share
        and operators couldn't tell whether to chase gossip-propagation
        (no record) or commit-side validation (empty bytes)."""
        from dataclasses import dataclass
        from djinn_validator.core.audit_set import AuditSet, AuditSignal
        from djinn_validator.core.outcomes import Outcome
        from djinn_validator.core.mpc_batch_settlement import (
            build_purchase_inputs_from_audit_set,
        )
        from djinn_validator.utils.crypto import Share as _Share

        @dataclass
        class _Rec:
            share: object
            encrypted_index_share: bytes

        class _EmptyIndexStore:
            def get(self, sig):
                # Record exists, but index share is empty bytes — the
                # commit-path bug class v1700 splits out.
                return _Rec(
                    share=_Share(x=1, y=12345),
                    encrypted_index_share=b"",
                )

        class _AnyLedger:
            def get(self, *, signal_id, buyer_address):
                return None

        audit_set = AuditSet(
            genius_address="0xG", idiot_address="0xI", cycle=0, version=2
        )
        audit_set.signals["sig-1"] = AuditSignal(
            signal_id="sig-1",
            purchase_id=1,
            outcomes=[Outcome.FAVORABLE, Outcome.UNFAVORABLE, Outcome.VOID],
            notional=100_000_000,
            odds=1_950_000,
            sla_bps=500,
        )
        before_missing = self._read_reason("missing_share")
        before_empty = self._read_reason("empty_index_share")
        result = build_purchase_inputs_from_audit_set(
            audit_set,
            share_store=_EmptyIndexStore(),
            purchase_odds_ledger=_AnyLedger(),
        )
        assert result is None
        # The new label fires; the old one does not.
        assert self._read_reason("empty_index_share") == before_empty + 1.0
        assert self._read_reason("missing_share") == before_missing

    def test_no_ledger_label_increments(self) -> None:
        from dataclasses import dataclass
        from djinn_validator.core.audit_set import AuditSet, AuditSignal
        from djinn_validator.core.outcomes import Outcome
        from djinn_validator.core.mpc_batch_settlement import (
            build_purchase_inputs_from_audit_set,
        )
        from djinn_validator.utils.crypto import Share as _Share

        @dataclass
        class _Rec:
            share: object
            encrypted_index_share: bytes

        class _Store:
            def get(self, sig):
                return _Rec(
                    share=_Share(x=1, y=12345),
                    encrypted_index_share=(5).to_bytes(32, "big"),
                )

        audit_set = AuditSet(
            genius_address="0xG", idiot_address="0xI", cycle=0, version=2
        )
        audit_set.signals["sig-1"] = AuditSignal(
            signal_id="sig-1",
            purchase_id=1,
            outcomes=[Outcome.FAVORABLE, Outcome.UNFAVORABLE, Outcome.VOID],
            notional=100_000_000,
            odds=1_950_000,
            sla_bps=500,
        )
        before = self._read_reason("no_ledger")
        result = build_purchase_inputs_from_audit_set(
            audit_set, share_store=_Store(), purchase_odds_ledger=None
        )
        assert result is None
        assert self._read_reason("no_ledger") == before + 1.0

    def test_missing_bpa_wpa_label_increments(self) -> None:
        from dataclasses import dataclass
        from djinn_validator.core.audit_set import AuditSet, AuditSignal
        from djinn_validator.core.outcomes import Outcome
        from djinn_validator.core.mpc_batch_settlement import (
            build_purchase_inputs_from_audit_set,
        )
        from djinn_validator.utils.crypto import Share as _Share

        @dataclass
        class _Rec:
            share: object
            encrypted_index_share: bytes

        class _Store:
            def get(self, sig):
                return _Rec(
                    share=_Share(x=1, y=12345),
                    encrypted_index_share=(5).to_bytes(32, "big"),
                )

        class _MissingLedger:
            def get(self, *, signal_id, buyer_address):
                return None  # ledger present but no row for this signal

        audit_set = AuditSet(
            genius_address="0xG", idiot_address="0xI", cycle=0, version=2
        )
        audit_set.signals["sig-1"] = AuditSignal(
            signal_id="sig-1",
            purchase_id=1,
            outcomes=[Outcome.FAVORABLE, Outcome.UNFAVORABLE, Outcome.VOID],
            notional=100_000_000,
            odds=1_950_000,
            sla_bps=500,
        )
        before = self._read_reason("missing_bpa_wpa")
        result = build_purchase_inputs_from_audit_set(
            audit_set,
            share_store=_Store(),
            purchase_odds_ledger=_MissingLedger(),
        )
        assert result is None
        assert self._read_reason("missing_bpa_wpa") == before + 1.0

    def test_vector_mismatch_label_increments(self) -> None:
        from dataclasses import dataclass
        from djinn_validator.core.audit_set import AuditSet, AuditSignal
        from djinn_validator.core.outcomes import Outcome
        from djinn_validator.core.mpc_batch_settlement import (
            build_purchase_inputs_from_audit_set,
        )
        from djinn_validator.utils.crypto import Share as _Share

        @dataclass
        class _Rec:
            share: object
            encrypted_index_share: bytes

        class _Store:
            def get(self, sig):
                return _Rec(
                    share=_Share(x=1, y=12345),
                    encrypted_index_share=(5).to_bytes(32, "big"),
                )

        @dataclass
        class _LedgerRec:
            bpa_mode: bool
            bpas: list
            wpas: list

        class _BadLedger:
            def get(self, *, signal_id, buyer_address):
                return _LedgerRec(
                    bpa_mode=True,
                    bpas=[1, 2, 3, 4, 5],  # len 5
                    wpas=[1, 2, 3],         # len 3 -> mismatch
                )

        audit_set = AuditSet(
            genius_address="0xG", idiot_address="0xI", cycle=0, version=2
        )
        audit_set.signals["sig-1"] = AuditSignal(
            signal_id="sig-1",
            purchase_id=1,
            outcomes=[Outcome.FAVORABLE, Outcome.UNFAVORABLE, Outcome.VOID],
            notional=100_000_000,
            odds=1_950_000,
            sla_bps=500,
        )
        before = self._read_reason("vector_mismatch")
        result = build_purchase_inputs_from_audit_set(
            audit_set, share_store=_Store(), purchase_odds_ledger=_BadLedger()
        )
        assert result is None
        assert self._read_reason("vector_mismatch") == before + 1.0

    def test_happy_path_does_not_tick_any_abstain_label(self) -> None:
        """Successful build must NOT increment any abstain reason."""
        from dataclasses import dataclass
        from djinn_validator.core.audit_set import AuditSet, AuditSignal
        from djinn_validator.core.outcomes import Outcome
        from djinn_validator.core.mpc_batch_settlement import (
            build_purchase_inputs_from_audit_set,
        )
        from djinn_validator.utils.crypto import Share as _Share

        @dataclass
        class _Rec:
            share: object
            encrypted_index_share: bytes

        class _Store:
            def get(self, sig):
                return _Rec(
                    share=_Share(x=1, y=12345),
                    encrypted_index_share=(5).to_bytes(32, "big"),
                )

        @dataclass
        class _LedgerRec:
            bpa_mode: bool
            bpas: list
            wpas: list

        class _GoodLedger:
            def get(self, *, signal_id, buyer_address):
                return _LedgerRec(
                    bpa_mode=True,
                    bpas=[1_900_000, 1_800_000, 1_700_000],
                    wpas=[1_800_000, 1_700_000, 1_600_000],
                )

        audit_set = AuditSet(
            genius_address="0xG", idiot_address="0xI", cycle=0, version=2
        )
        audit_set.signals["sig-1"] = AuditSignal(
            signal_id="sig-1",
            purchase_id=1,
            outcomes=[Outcome.FAVORABLE, Outcome.UNFAVORABLE, Outcome.VOID],
            notional=100_000_000,
            odds=1_950_000,
            sla_bps=500,
        )
        baseline = {
            r: self._read_reason(r)
            for r in (
                "no_audit_set",
                "no_resolved",
                "missing_share",
                "no_ledger",
                "missing_bpa_wpa",
                "vector_mismatch",
                "empty_batch",
            )
        }
        result = build_purchase_inputs_from_audit_set(
            audit_set, share_store=_Store(), purchase_odds_ledger=_GoodLedger()
        )
        assert result is not None
        assert len(result) == 1
        for r, v in baseline.items():
            assert self._read_reason(r) == v, (
                f"happy path must not tick BUILD_PI_ABSTAIN_REASON{{reason={r}}}; "
                f"baseline={v}, now={self._read_reason(r)}"
            )
