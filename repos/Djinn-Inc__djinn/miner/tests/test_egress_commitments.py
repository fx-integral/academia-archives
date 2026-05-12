"""Tests for validator egress-IP commitment ingestion."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from djinn_miner.utils.egress_commitments import (
    MAX_IPS_PER_VALIDATOR,
    get_validator_egress_ips,
    parse_egress_ips,
    reset_cache,
)


@pytest.fixture(autouse=True)
def _clear_cache() -> None:
    reset_cache()


class TestParseEgressIps:
    def test_empty(self) -> None:
        assert parse_egress_ips("") == set()
        assert parse_egress_ips(None) == set()

    def test_single_ip(self) -> None:
        assert parse_egress_ips("8.8.8.8") == {"8.8.8.8"}

    def test_multiple_ips(self) -> None:
        assert parse_egress_ips("8.8.8.8,1.1.1.1") == {"8.8.8.8", "1.1.1.1"}

    def test_strips_whitespace(self) -> None:
        assert parse_egress_ips(" 8.8.8.8 , 1.1.1.1 ") == {"8.8.8.8", "1.1.1.1"}

    def test_rejects_loopback(self) -> None:
        assert parse_egress_ips("127.0.0.1") == set()

    def test_rejects_private(self) -> None:
        assert parse_egress_ips("10.0.0.1,192.168.1.1,172.16.0.1") == set()

    def test_rejects_unspecified(self) -> None:
        assert parse_egress_ips("0.0.0.0") == set()

    def test_rejects_garbage(self) -> None:
        assert parse_egress_ips("not-an-ip,also-junk") == set()

    def test_mixes_valid_and_invalid(self) -> None:
        assert parse_egress_ips("8.8.8.8,127.0.0.1,not-ip") == {"8.8.8.8"}

    def test_caps_at_max(self) -> None:
        many = ",".join(f"8.8.8.{i}" for i in range(1, 20))
        out = parse_egress_ips(many)
        assert len(out) == MAX_IPS_PER_VALIDATOR

    def test_ignores_json_payload(self) -> None:
        """Tunnel-shield commitments are JSON; we must not eat them."""
        assert parse_egress_ips('{"v":2,"url":"https://x.example"}') == set()
        assert parse_egress_ips("[1,2,3]") == set()

    def test_accepts_bytes(self) -> None:
        assert parse_egress_ips(b"8.8.8.8") == {"8.8.8.8"}

    def test_accepts_ipv6(self) -> None:
        assert parse_egress_ips("2001:db8::1,2606:4700:4700::1111") == {
            "2606:4700:4700::1111"
        }  # 2001:db8::1 is documentation-reserved -> rejected

    def test_dedupes(self) -> None:
        assert parse_egress_ips("8.8.8.8,8.8.8.8") == {"8.8.8.8"}


class TestGetValidatorEgressIps:
    def _mock_neuron(
        self,
        n: int,
        permits: list[bool],
        commitments: dict[int, str],
    ) -> MagicMock:
        neuron = MagicMock()
        neuron.netuid = 103
        neuron.metagraph.n = n
        neuron.metagraph.validator_permit = permits
        neuron.subtensor.get_commitment.side_effect = lambda netuid, uid: commitments.get(uid, "")
        return neuron

    def test_returns_empty_when_no_neuron(self) -> None:
        assert get_validator_egress_ips(None) == set()

    def test_returns_empty_when_no_subtensor(self) -> None:
        neuron = MagicMock()
        neuron.subtensor = None
        assert get_validator_egress_ips(neuron) == set()

    def test_only_validator_permit_uids(self) -> None:
        neuron = self._mock_neuron(
            n=3,
            permits=[True, False, True],
            commitments={0: "8.8.8.8", 1: "9.9.9.9", 2: "1.1.1.1"},
        )
        ips = get_validator_egress_ips(neuron)
        assert ips == {"8.8.8.8", "1.1.1.1"}

    def test_unions_across_validators(self) -> None:
        neuron = self._mock_neuron(
            n=2,
            permits=[True, True],
            commitments={0: "8.8.8.8,1.1.1.1", 1: "4.4.4.4"},
        )
        assert get_validator_egress_ips(neuron) == {"8.8.8.8", "1.1.1.1", "4.4.4.4"}

    def test_swallows_per_uid_exceptions(self) -> None:
        neuron = MagicMock()
        neuron.netuid = 103
        neuron.metagraph.n = 2
        neuron.metagraph.validator_permit = [True, True]

        def _flaky(netuid: int, uid: int) -> str:
            if uid == 0:
                raise RuntimeError("rpc down for uid 0")
            return "8.8.8.8"

        neuron.subtensor.get_commitment.side_effect = _flaky
        assert get_validator_egress_ips(neuron) == {"8.8.8.8"}

    def test_skips_when_sdk_lacks_get_commitment(self) -> None:
        neuron = MagicMock()
        # spec= forces hasattr to be honest about the attribute set
        neuron.subtensor = MagicMock(spec=[])
        assert get_validator_egress_ips(neuron) == set()

    def test_caches_repeated_calls(self) -> None:
        neuron = self._mock_neuron(
            n=1, permits=[True], commitments={0: "8.8.8.8"}
        )
        assert get_validator_egress_ips(neuron) == {"8.8.8.8"}
        assert get_validator_egress_ips(neuron) == {"8.8.8.8"}
        # Second call should hit the cache, not the chain
        assert neuron.subtensor.get_commitment.call_count == 1
