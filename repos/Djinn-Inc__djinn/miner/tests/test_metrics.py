"""Tests for Prometheus metrics endpoint and counters."""

from __future__ import annotations

from djinn_miner.api.metrics import (
    BT_CONNECTED,
    CHECKS_PROCESSED,
    LINES_CHECKED,
    ODDS_API_QUERIES,
    PROOFS_GENERATED,
    UPTIME_SECONDS,
    metrics_response,
)


class TestMetricsResponse:
    def test_returns_bytes(self) -> None:
        result = metrics_response()
        assert isinstance(result, bytes)

    def test_contains_metric_names(self) -> None:
        text = metrics_response().decode()
        assert "djinn_miner" in text

    def test_prometheus_format(self) -> None:
        text = metrics_response().decode()
        assert "# TYPE" in text or "# HELP" in text


class TestCounterIncrements:
    def test_checks_processed(self) -> None:
        before = CHECKS_PROCESSED._value.get()
        CHECKS_PROCESSED.inc()
        assert CHECKS_PROCESSED._value.get() == before + 1

    def test_lines_checked_labeled(self) -> None:
        LINES_CHECKED.labels(result="available").inc()
        LINES_CHECKED.labels(result="unavailable").inc()
        text = metrics_response().decode()
        assert "available" in text

    def test_proofs_generated_labeled(self) -> None:
        PROOFS_GENERATED.labels(type="http_attestation").inc()
        text = metrics_response().decode()
        assert "http_attestation" in text

    def test_odds_api_queries_labeled(self) -> None:
        ODDS_API_QUERIES.labels(status="success").inc()
        text = metrics_response().decode()
        assert "success" in text


class TestGauges:
    def test_uptime_gauge(self) -> None:
        UPTIME_SECONDS.set(3600)
        assert UPTIME_SECONDS._value.get() == 3600
        UPTIME_SECONDS.set(0)

    def test_bt_connected_gauge(self) -> None:
        BT_CONNECTED.set(1)
        assert BT_CONNECTED._value.get() == 1
        BT_CONNECTED.set(0)
