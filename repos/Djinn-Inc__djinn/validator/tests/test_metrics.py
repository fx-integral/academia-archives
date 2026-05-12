"""Tests for Prometheus metrics endpoint and counters."""

from __future__ import annotations

import pytest
from prometheus_client import CollectorRegistry

from djinn_validator.api.metrics import (
    ACTIVE_SHARES,
    CIRCUIT_BREAKER_STATE,
    MPC_DURATION,
    MPC_ERRORS,
    OUTCOMES_ATTESTED,
    PURCHASES_PROCESSED,
    RPC_FAILOVERS,
    SHARES_STORED,
    metrics_response,
)


class TestMetricsResponse:
    def test_returns_bytes(self) -> None:
        result = metrics_response()
        assert isinstance(result, bytes)

    def test_contains_metric_names(self) -> None:
        text = metrics_response().decode()
        assert "djinn_validator_requests_total" in text or "djinn_validator" in text

    def test_prometheus_format(self) -> None:
        text = metrics_response().decode()
        # Should contain TYPE declarations
        assert "# TYPE" in text or "# HELP" in text


class TestCounterIncrements:
    def test_shares_stored_increments(self) -> None:
        before = SHARES_STORED._value.get()
        SHARES_STORED.inc()
        assert SHARES_STORED._value.get() == before + 1

    def test_active_shares_gauge(self) -> None:
        ACTIVE_SHARES.set(42)
        assert ACTIVE_SHARES._value.get() == 42
        ACTIVE_SHARES.set(0)

    def test_purchases_labeled(self) -> None:
        PURCHASES_PROCESSED.labels(result="available").inc()
        PURCHASES_PROCESSED.labels(result="unavailable").inc()
        # Verify both labels exist in metrics output
        text = metrics_response().decode()
        assert "available" in text

    def test_outcomes_labeled(self) -> None:
        OUTCOMES_ATTESTED.labels(outcome="favorable").inc()
        text = metrics_response().decode()
        assert "favorable" in text

    def test_mpc_duration_histogram(self) -> None:
        MPC_DURATION.labels(mode="single_validator").observe(0.5)
        text = metrics_response().decode()
        assert "djinn_validator_mpc_duration_seconds" in text

    def test_mpc_errors_labeled(self) -> None:
        MPC_ERRORS.labels(reason="timeout").inc()
        MPC_ERRORS.labels(reason="mac_failure").inc()
        text = metrics_response().decode()
        assert "djinn_validator_mpc_errors_total" in text

    def test_rpc_failovers_counter(self) -> None:
        before = RPC_FAILOVERS._value.get()
        RPC_FAILOVERS.inc()
        assert RPC_FAILOVERS._value.get() == before + 1

    def test_circuit_breaker_state_gauge(self) -> None:
        CIRCUIT_BREAKER_STATE.labels(target="rpc").set(1)
        text = metrics_response().decode()
        assert "djinn_validator_circuit_breaker_open" in text
        CIRCUIT_BREAKER_STATE.labels(target="rpc").set(0)


class TestSafeLabelInc:
    """v1700+ shared best-effort counter helper. Used across the validator
    on every diagnostic abstain branch — must be cheap, never raise, and
    correctly forward arbitrary keyword labels to the underlying counter."""

    def test_increments_single_label_counter(self) -> None:
        from djinn_validator.api.metrics import (
            BUILD_PI_ABSTAIN_REASON,
            safe_label_inc,
        )

        before = float(
            BUILD_PI_ABSTAIN_REASON.labels(reason="missing_share")._value.get()
        )
        safe_label_inc(BUILD_PI_ABSTAIN_REASON, reason="missing_share")
        after = float(
            BUILD_PI_ABSTAIN_REASON.labels(reason="missing_share")._value.get()
        )
        assert after == before + 1.0

    def test_increments_multi_label_counter(self) -> None:
        """GOSSIP_PUSH_RESULT has both path + outcome labels."""
        from djinn_validator.api.metrics import GOSSIP_PUSH_RESULT, safe_label_inc

        before = float(
            GOSSIP_PUSH_RESULT.labels(path="purchase_odds", outcome="sent")._value.get()
        )
        safe_label_inc(GOSSIP_PUSH_RESULT, path="purchase_odds", outcome="sent")
        after = float(
            GOSSIP_PUSH_RESULT.labels(path="purchase_odds", outcome="sent")._value.get()
        )
        assert after == before + 1.0

    def test_swallows_invalid_label_arg(self) -> None:
        """Passing a label name the counter doesn't define must NOT raise.
        That's the point of the wrapper: a typo at a call site can't
        crash the surrounding hot path."""
        from djinn_validator.api.metrics import (
            BUILD_PI_ABSTAIN_REASON,
            safe_label_inc,
        )

        # Valid call to set a baseline so the test does something.
        safe_label_inc(BUILD_PI_ABSTAIN_REASON, reason="missing_share")
        # Invalid: BUILD_PI_ABSTAIN_REASON has only the "reason" label.
        # Underlying Counter.labels(unknown=...) raises ValueError.
        try:
            safe_label_inc(BUILD_PI_ABSTAIN_REASON, not_a_real_label="oops")
        except Exception as e:
            raise AssertionError(
                f"safe_label_inc must swallow exceptions; raised {type(e).__name__}: {e}"
            )

    def test_swallows_none_counter(self) -> None:
        """If the counter argument itself is somehow None (e.g. test patched
        the module attr to None), we still don't blow up the caller."""
        from djinn_validator.api.metrics import safe_label_inc

        try:
            safe_label_inc(None, reason="x")  # type: ignore[arg-type]
        except Exception as e:
            raise AssertionError(
                f"safe_label_inc must swallow exceptions; raised {type(e).__name__}: {e}"
            )
