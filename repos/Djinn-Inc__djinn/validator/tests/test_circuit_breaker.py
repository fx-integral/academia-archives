"""Tests for the circuit breaker utility."""

from __future__ import annotations

import time
from unittest.mock import patch

from djinn_validator.utils.circuit_breaker import CircuitBreaker, CircuitState


class TestCircuitBreaker:
    def test_initial_state_closed(self):
        cb = CircuitBreaker("test")
        assert cb.state == CircuitState.CLOSED
        assert not cb.is_open
        assert cb.allow_request()

    def test_stays_closed_below_threshold(self):
        cb = CircuitBreaker("test", failure_threshold=3)
        cb.record_failure()
        cb.record_failure()
        assert cb.state == CircuitState.CLOSED
        assert cb.allow_request()

    def test_opens_at_threshold(self):
        cb = CircuitBreaker("test", failure_threshold=3)
        cb.record_failure()
        cb.record_failure()
        cb.record_failure()
        assert cb.state == CircuitState.OPEN
        assert cb.is_open
        assert not cb.allow_request()

    def test_rejects_when_open(self):
        cb = CircuitBreaker("test", failure_threshold=1)
        cb.record_failure()
        assert not cb.allow_request()
        assert not cb.allow_request()

    def test_success_resets_failure_count(self):
        cb = CircuitBreaker("test", failure_threshold=3)
        cb.record_failure()
        cb.record_failure()
        cb.record_success()
        assert cb.state == CircuitState.CLOSED
        # Need full threshold again to open
        cb.record_failure()
        cb.record_failure()
        assert cb.state == CircuitState.CLOSED

    def test_transitions_to_half_open_after_timeout(self):
        cb = CircuitBreaker("test", failure_threshold=1, recovery_timeout=0.1)
        cb.record_failure()
        assert cb.state == CircuitState.OPEN

        time.sleep(0.15)
        assert cb.state == CircuitState.HALF_OPEN
        assert cb.allow_request()

    def test_half_open_allows_limited_requests(self):
        cb = CircuitBreaker("test", failure_threshold=1, recovery_timeout=0.1, half_open_max=1)
        cb.record_failure()
        time.sleep(0.15)

        assert cb.allow_request()  # First request allowed
        assert not cb.allow_request()  # Second rejected

    def test_half_open_success_closes(self):
        cb = CircuitBreaker("test", failure_threshold=1, recovery_timeout=0.1)
        cb.record_failure()
        time.sleep(0.15)

        cb.record_success()
        assert cb.state == CircuitState.CLOSED
        assert cb.allow_request()

    def test_half_open_failure_reopens(self):
        cb = CircuitBreaker("test", failure_threshold=1, recovery_timeout=0.1)
        cb.record_failure()
        time.sleep(0.15)

        assert cb.state == CircuitState.HALF_OPEN
        cb.record_failure()
        assert cb.state == CircuitState.OPEN
        assert not cb.allow_request()

    def test_reset(self):
        cb = CircuitBreaker("test", failure_threshold=1)
        cb.record_failure()
        assert cb.state == CircuitState.OPEN
        cb.reset()
        assert cb.state == CircuitState.CLOSED
        assert cb.allow_request()

    def test_name_preserved(self):
        cb = CircuitBreaker("rpc_client")
        assert cb.name == "rpc_client"

    def test_multiple_cycles(self):
        """Circuit breaker can go through multiple open/close cycles."""
        cb = CircuitBreaker("test", failure_threshold=2, recovery_timeout=0.05)

        # Cycle 1: open
        cb.record_failure()
        cb.record_failure()
        assert cb.state == CircuitState.OPEN

        # Recover
        time.sleep(0.1)
        cb.record_success()
        assert cb.state == CircuitState.CLOSED

        # Cycle 2: open again
        cb.record_failure()
        cb.record_failure()
        assert cb.state == CircuitState.OPEN

        # Recover again
        time.sleep(0.1)
        cb.record_success()
        assert cb.state == CircuitState.CLOSED


class TestChainClientCircuitBreaker:
    """Test that ChainClient uses circuit breaker."""

    def test_chain_client_has_circuit_breaker(self):
        from djinn_validator.chain.contracts import ChainClient

        client = ChainClient("https://example.com")
        assert hasattr(client, "_circuit_breaker")
        assert isinstance(client._circuit_breaker, CircuitBreaker)

    def test_chain_client_breaker_named_rpc(self):
        from djinn_validator.chain.contracts import ChainClient

        client = ChainClient("https://example.com")
        assert client._circuit_breaker.name == "rpc"


class TestMPCOrchestratorPeerBreakers:
    """Test that MPCOrchestrator creates per-peer circuit breakers."""

    def test_peer_breaker_creation(self):
        from djinn_validator.core.mpc_coordinator import MPCCoordinator
        from djinn_validator.core.mpc_orchestrator import MPCOrchestrator

        coord = MPCCoordinator()
        orch = MPCOrchestrator(coordinator=coord)
        breaker = orch._get_peer_breaker(42)
        assert isinstance(breaker, CircuitBreaker)
        assert breaker.name == "peer_42"

    def test_peer_breaker_reuse(self):
        from djinn_validator.core.mpc_coordinator import MPCCoordinator
        from djinn_validator.core.mpc_orchestrator import MPCOrchestrator

        coord = MPCCoordinator()
        orch = MPCOrchestrator(coordinator=coord)
        b1 = orch._get_peer_breaker(7)
        b2 = orch._get_peer_breaker(7)
        assert b1 is b2

    def test_different_peers_different_breakers(self):
        from djinn_validator.core.mpc_coordinator import MPCCoordinator
        from djinn_validator.core.mpc_orchestrator import MPCOrchestrator

        coord = MPCCoordinator()
        orch = MPCOrchestrator(coordinator=coord)
        b1 = orch._get_peer_breaker(1)
        b2 = orch._get_peer_breaker(2)
        assert b1 is not b2


class TestCircuitBreakerGauge:
    def test_gauge_updated_on_open(self):
        from djinn_validator.api.metrics import CIRCUIT_BREAKER_STATE

        cb = CircuitBreaker(name="test_gauge_open", failure_threshold=2)
        cb.record_failure()
        cb.record_failure()
        assert cb.state == CircuitState.OPEN
        val = CIRCUIT_BREAKER_STATE.labels(target="test_gauge_open")._value.get()
        assert val == 1

    def test_gauge_updated_on_close(self):
        from djinn_validator.api.metrics import CIRCUIT_BREAKER_STATE

        cb = CircuitBreaker(name="test_gauge_close", failure_threshold=2)
        cb.record_failure()
        cb.record_failure()
        cb.record_success()
        assert cb.state == CircuitState.CLOSED
        val = CIRCUIT_BREAKER_STATE.labels(target="test_gauge_close")._value.get()
        assert val == 0
