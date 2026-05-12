"""Docker integration tests for the Djinn protocol stack.

Runs against live validator + miner + anvil services started via:
  docker compose -f docker-compose.yml -f docker-compose.test.yml up -d

Tests the full signal lifecycle over HTTP:
1. Health checks for all services
2. Signal share storage (validator)
3. Line availability check (miner)
4. Purchase flow (validator MPC)
5. Signal registration and outcome attestation

Usage:
  python tests/integration/test_docker_e2e.py

  Or via the wrapper script:
  ./scripts/run_docker_tests.sh
"""

from __future__ import annotations

import json
import os
import secrets
import sys
import time
from typing import Any

import httpx

VALIDATOR_URL = os.getenv("VALIDATOR_URL", "http://localhost:8421")
MINER_URL = os.getenv("MINER_URL", "http://localhost:8422")
ANVIL_URL = os.getenv("ANVIL_URL", "http://localhost:8545")

TIMEOUT = 10.0
STARTUP_TIMEOUT = 120  # max seconds to wait for services


class IntegrationTestRunner:
    """Simple test runner for Docker integration tests."""

    def __init__(self) -> None:
        self._client = httpx.Client(timeout=TIMEOUT)
        self._passed = 0
        self._failed = 0
        self._errors: list[str] = []

    def run(self, name: str, fn: Any) -> None:
        try:
            fn()
            self._passed += 1
            print(f"  PASS  {name}")
        except AssertionError as e:
            self._failed += 1
            self._errors.append(f"{name}: {e}")
            print(f"  FAIL  {name}: {e}")
        except Exception as e:
            self._failed += 1
            self._errors.append(f"{name}: {type(e).__name__}: {e}")
            print(f"  ERROR {name}: {type(e).__name__}: {e}")

    def summary(self) -> int:
        total = self._passed + self._failed
        print(f"\n{'=' * 60}")
        print(f"Results: {self._passed}/{total} passed, {self._failed} failed")
        if self._errors:
            print("\nFailures:")
            for err in self._errors:
                print(f"  - {err}")
        print(f"{'=' * 60}")
        return 0 if self._failed == 0 else 1

    # -------------------------------------------------------------------
    # Helpers
    # -------------------------------------------------------------------

    def get(self, url: str) -> httpx.Response:
        return self._client.get(url)

    def post(self, url: str, json_data: dict) -> httpx.Response:
        return self._client.post(url, json=json_data)

    def assert_ok(self, resp: httpx.Response, msg: str = "") -> dict:
        assert resp.status_code == 200, (
            f"Expected 200, got {resp.status_code} for {resp.url}"
            + (f": {msg}" if msg else "")
            + f" — body: {resp.text[:200]}"
        )
        return resp.json()

    def close(self) -> None:
        self._client.close()


def wait_for_services(runner: IntegrationTestRunner) -> None:
    """Wait for all services to be healthy before running tests."""
    services = [
        ("Anvil", ANVIL_URL, lambda: runner.post(
            ANVIL_URL, {"jsonrpc": "2.0", "method": "eth_blockNumber", "params": [], "id": 1}
        )),
        ("Validator", VALIDATOR_URL, lambda: runner.get(f"{VALIDATOR_URL}/health")),
        ("Miner", MINER_URL, lambda: runner.get(f"{MINER_URL}/health")),
    ]

    deadline = time.monotonic() + STARTUP_TIMEOUT
    for name, url, check in services:
        print(f"Waiting for {name} ({url})...", end="", flush=True)
        while time.monotonic() < deadline:
            try:
                resp = check()
                if resp.status_code == 200:
                    print(" OK")
                    break
            except (httpx.ConnectError, httpx.ReadError, httpx.ConnectTimeout):
                pass
            time.sleep(2)
            print(".", end="", flush=True)
        else:
            print(f"\nFATAL: {name} did not become healthy within {STARTUP_TIMEOUT}s")
            sys.exit(1)


def main() -> int:
    runner = IntegrationTestRunner()

    print("=" * 60)
    print("Djinn Docker Integration Tests")
    print("=" * 60)

    # Wait for services
    wait_for_services(runner)
    print()

    # ------------------------------------------------------------------
    # Health checks
    # ------------------------------------------------------------------
    print("--- Health Checks ---")

    def test_anvil_health() -> None:
        resp = runner.post(
            ANVIL_URL,
            {"jsonrpc": "2.0", "method": "eth_chainId", "params": [], "id": 1},
        )
        data = runner.assert_ok(resp)
        chain_id = int(data["result"], 16)
        assert chain_id == 31337, f"Expected chain 31337, got {chain_id}"

    def test_validator_health() -> None:
        data = runner.assert_ok(runner.get(f"{VALIDATOR_URL}/health"))
        assert data["status"] == "ok", f"Validator not ok: {data}"
        assert "version" in data

    def test_miner_health() -> None:
        data = runner.assert_ok(runner.get(f"{MINER_URL}/health"))
        assert data["status"] == "ok", f"Miner not ok: {data}"
        assert "version" in data

    runner.run("Anvil chain ID is 31337", test_anvil_health)
    runner.run("Validator /health returns ok", test_validator_health)
    runner.run("Miner /health returns ok", test_miner_health)

    # ------------------------------------------------------------------
    # Signal share storage
    # ------------------------------------------------------------------
    print("\n--- Signal Share Storage ---")
    signal_id = f"inttest_{secrets.token_hex(8)}"

    def test_store_share() -> None:
        resp = runner.post(
            f"{VALIDATOR_URL}/v1/signal",
            {
                "signal_id": signal_id,
                "genius_address": "0x" + "a1" * 20,
                "share_x": 1,
                "share_y": "0a1b2c3d4e5f",
                "encrypted_key_share": "deadbeefcafe",
            },
        )
        data = runner.assert_ok(resp)
        assert data["stored"] is True, f"Share not stored: {data}"
        assert data["signal_id"] == signal_id

    def test_store_multiple_shares() -> None:
        for x in range(2, 11):
            resp = runner.post(
                f"{VALIDATOR_URL}/v1/signal",
                {
                    "signal_id": signal_id,
                    "genius_address": "0x" + "a1" * 20,
                    "share_x": x,
                    "share_y": f"{x:012x}",
                    "encrypted_key_share": "deadbeefcafe",
                },
            )
            data = runner.assert_ok(resp)
            assert data["stored"] is True

    def test_store_share_validation() -> None:
        resp = runner.post(
            f"{VALIDATOR_URL}/v1/signal",
            {
                "signal_id": "",  # Invalid: empty
                "genius_address": "0x" + "a1" * 20,
                "share_x": 1,
                "share_y": "ff",
                "encrypted_key_share": "00",
            },
        )
        assert resp.status_code == 422, f"Expected 422, got {resp.status_code}"

    runner.run("Store first share", test_store_share)
    runner.run("Store remaining 9 shares", test_store_multiple_shares)
    runner.run("Reject invalid signal_id", test_store_share_validation)

    # ------------------------------------------------------------------
    # Miner line check
    # ------------------------------------------------------------------
    print("\n--- Miner Line Check ---")

    def test_check_lines_basic() -> None:
        lines = [
            {
                "index": i + 1,
                "sport": "basketball_nba",
                "event_id": f"test_event_{i}",
                "home_team": "Lakers",
                "away_team": "Celtics",
                "market": "spreads",
                "line": -3.5 + i,
                "side": "Lakers",
            }
            for i in range(3)
        ]
        resp = runner.post(f"{MINER_URL}/v1/check", {"lines": lines})
        data = runner.assert_ok(resp)
        assert "results" in data, "Missing results"
        assert "available_indices" in data, "Missing available_indices"
        assert "response_time_ms" in data, "Missing response_time_ms"
        assert isinstance(data["results"], list)
        assert len(data["results"]) == 3

    def test_check_lines_empty() -> None:
        resp = runner.post(f"{MINER_URL}/v1/check", {"lines": []})
        # Empty lines should either return 200 with empty results or 422
        assert resp.status_code in (200, 422)

    runner.run("Check lines returns structured response", test_check_lines_basic)
    runner.run("Check empty lines list", test_check_lines_empty)

    # ------------------------------------------------------------------
    # Purchase flow (single-validator mode)
    # ------------------------------------------------------------------
    print("\n--- Purchase Flow ---")

    def test_purchase_signal() -> None:
        resp = runner.post(
            f"{VALIDATOR_URL}/v1/signal/{signal_id}/purchase",
            {
                "buyer_address": "0x" + "b2" * 20,
                "sportsbook": "DraftKings",
                "available_indices": [1, 2, 3, 4, 5],
            },
        )
        data = runner.assert_ok(resp)
        assert "status" in data
        assert "available" in data
        assert data["signal_id"] == signal_id

    runner.run("Purchase signal returns response", test_purchase_signal)

    # ------------------------------------------------------------------
    # MPC session status
    # ------------------------------------------------------------------
    print("\n--- MPC Session ---")

    def test_mpc_init_rejects_bad_session() -> None:
        resp = runner.post(
            f"{VALIDATOR_URL}/v1/mpc/init",
            {
                "session_id": "nonexistent_session",
                "signal_id": "test",
                "available_indices": [1, 2, 3],
                "coordinator_x": 1,
                "participant_xs": [1, 2, 3],
                "threshold": 2,
                "triple_shares": [],
            },
        )
        # Should accept (participant creates local state)
        # or reject if validation fails
        assert resp.status_code in (200, 400, 422)

    def test_mpc_status_unknown_session() -> None:
        resp = runner.get(f"{VALIDATOR_URL}/v1/mpc/nonexistent123/status")
        assert resp.status_code == 404

    runner.run("MPC init handles unknown session", test_mpc_init_rejects_bad_session)
    runner.run("MPC status returns 404 for unknown session", test_mpc_status_unknown_session)

    # ------------------------------------------------------------------
    # Signal registration
    # ------------------------------------------------------------------
    print("\n--- Signal Registration ---")

    def test_register_signal() -> None:
        resp = runner.post(
            f"{VALIDATOR_URL}/v1/signal/{signal_id}/register",
            {
                "sport": "basketball_nba",
                "event_id": "test_event_001",
                "home_team": "Lakers",
                "away_team": "Celtics",
                "pick": "Lakers -3.5 (-110)",
            },
        )
        data = runner.assert_ok(resp)
        assert data["registered"] is True
        assert data["signal_id"] == signal_id

    runner.run("Register signal for outcome tracking", test_register_signal)

    # ------------------------------------------------------------------
    # Cross-service: Miner checks → Validator purchase
    # ------------------------------------------------------------------
    print("\n--- Cross-Service Flow ---")

    def test_full_flow() -> None:
        # Create a new signal
        sid = f"flow_{secrets.token_hex(8)}"

        # Store 10 shares
        for x in range(1, 11):
            resp = runner.post(
                f"{VALIDATOR_URL}/v1/signal",
                {
                    "signal_id": sid,
                    "genius_address": "0x" + "c3" * 20,
                    "share_x": x,
                    "share_y": f"{(x * 12345):012x}",
                    "encrypted_key_share": "ff" * 32,
                },
            )
            runner.assert_ok(resp)

        # Check lines with miner
        lines = [
            {
                "index": i + 1,
                "sport": "basketball_nba",
                "event_id": f"flow_event_{i}",
                "home_team": "Warriors",
                "away_team": "Heat",
                "market": "spreads",
                "line": -2.5,
                "side": "Warriors",
            }
            for i in range(5)
        ]
        check_resp = runner.post(f"{MINER_URL}/v1/check", {"lines": lines})
        check_data = runner.assert_ok(check_resp)
        assert "available_indices" in check_data

        # Purchase from validator
        purchase_resp = runner.post(
            f"{VALIDATOR_URL}/v1/signal/{sid}/purchase",
            {
                "buyer_address": "0x" + "d4" * 20,
                "sportsbook": "FanDuel",
                "available_indices": check_data.get("available_indices", [1, 2, 3]),
            },
        )
        purchase_data = runner.assert_ok(purchase_resp)
        assert purchase_data["signal_id"] == sid
        assert "available" in purchase_data

    runner.run("Full signal lifecycle (store → check → purchase)", test_full_flow)

    # ------------------------------------------------------------------
    # OT endpoints
    # ------------------------------------------------------------------
    print("\n--- OT Endpoints ---")

    def test_ot_setup() -> None:
        resp = runner.post(
            f"{VALIDATOR_URL}/v1/ot/setup",
            {"session_id": "inttest_ot", "n_triples": 3, "n_bits": 64},
        )
        # Accept 200 (success) or 400/422 (validation) — just ensure endpoint exists
        assert resp.status_code in (200, 400, 422), f"Unexpected {resp.status_code}"

    def test_ot_status() -> None:
        resp = runner.get(f"{VALIDATOR_URL}/v1/ot/inttest_ot/status")
        assert resp.status_code in (200, 404)

    runner.run("OT setup endpoint reachable", test_ot_setup)
    runner.run("OT status endpoint reachable", test_ot_status)

    # ------------------------------------------------------------------
    # Concurrent requests
    # ------------------------------------------------------------------
    print("\n--- Concurrent Requests ---")

    def test_concurrent_health_checks() -> None:
        import concurrent.futures

        def check_health(url: str) -> int:
            with httpx.Client(timeout=TIMEOUT) as c:
                return c.get(f"{url}/health").status_code

        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as pool:
            futures = [pool.submit(check_health, VALIDATOR_URL) for _ in range(10)]
            futures += [pool.submit(check_health, MINER_URL) for _ in range(10)]
            results = [f.result() for f in futures]
        assert all(r == 200 for r in results), f"Some health checks failed: {results}"

    runner.run("20 concurrent health checks succeed", test_concurrent_health_checks)

    # ------------------------------------------------------------------
    # Error handling
    # ------------------------------------------------------------------
    print("\n--- Error Handling ---")

    def test_validator_404() -> None:
        resp = runner.get(f"{VALIDATOR_URL}/v1/nonexistent")
        assert resp.status_code in (404, 405)

    def test_miner_404() -> None:
        resp = runner.get(f"{MINER_URL}/v1/nonexistent")
        assert resp.status_code in (404, 405)

    def test_validator_bad_json() -> None:
        resp = runner._client.post(
            f"{VALIDATOR_URL}/v1/signal",
            content="not json",
            headers={"Content-Type": "application/json"},
        )
        assert resp.status_code in (400, 422)

    runner.run("Validator returns 404 for unknown path", test_validator_404)
    runner.run("Miner returns 404 for unknown path", test_miner_404)
    runner.run("Validator rejects malformed JSON", test_validator_bad_json)

    # ------------------------------------------------------------------
    # Done
    # ------------------------------------------------------------------
    runner.close()
    return runner.summary()


if __name__ == "__main__":
    sys.exit(main())
