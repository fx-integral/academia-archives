"""Tests for the validator egress-IP publisher."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from djinn_validator.utils.egress_publisher import (
    DEFAULT_MAX_IPS,
    ENV_MAX_VAR,
    ENV_VAR,
    HARD_MAX_IPS,
    _normalize,
    _reset_detection,
    get_max_ips,
    parse_payload,
    publish_egress_ips,
)


@pytest.fixture(autouse=True)
def _clear_detection_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    _reset_detection()
    # Tests assume the wide cap unless they override; the production
    # default is 1, but legacy tests were written when MAX was 5.
    monkeypatch.setenv(ENV_MAX_VAR, str(HARD_MAX_IPS))


class TestGetMaxIps:
    def test_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv(ENV_MAX_VAR, raising=False)
        assert get_max_ips() == DEFAULT_MAX_IPS == 1

    def test_clamps_low(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(ENV_MAX_VAR, "-3")
        assert get_max_ips() == 0

    def test_clamps_high(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(ENV_MAX_VAR, "999")
        assert get_max_ips() == HARD_MAX_IPS

    def test_garbage_uses_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(ENV_MAX_VAR, "abc")
        assert get_max_ips() == DEFAULT_MAX_IPS

    def test_zero_disables(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(ENV_MAX_VAR, "0")
        assert get_max_ips() == 0


class TestAxonMatchSkip:
    """If detected egress equals own axon IP, the commitment is redundant."""

    def test_skips_when_detected_equals_axon(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv(ENV_VAR, raising=False)
        monkeypatch.setattr(
            "djinn_validator.utils.egress_publisher.detect_egress_ip",
            lambda force=False: "203.0.113.42",
        )
        n = MagicMock()
        n.netuid = 103
        n.uid = 7
        n.metagraph.axons[7].ip = "203.0.113.42"  # axon == detected
        assert publish_egress_ips(n) is False
        n.subtensor.set_commitment.assert_not_called()

    def test_publishes_when_detected_differs_from_axon(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv(ENV_VAR, raising=False)
        monkeypatch.setattr(
            "djinn_validator.utils.egress_publisher.detect_egress_ip",
            lambda force=False: "8.8.8.8",
        )
        n = MagicMock()
        n.netuid = 103
        n.uid = 7
        n.metagraph.axons[7].ip = "203.0.113.42"  # axon != detected
        n.subtensor.get_commitment.return_value = ""
        assert publish_egress_ips(n) is True
        assert n.subtensor.set_commitment.call_args.kwargs["data"] == "8.8.8.8"

    def test_env_overrides_axon_match(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Env-set IPs are not filtered against axon — operator chose them."""
        monkeypatch.setenv(ENV_VAR, "203.0.113.42")  # same as axon
        n = MagicMock()
        n.netuid = 103
        n.uid = 7
        n.metagraph.axons[7].ip = "203.0.113.42"
        n.subtensor.get_commitment.return_value = ""
        assert publish_egress_ips(n) is True


class TestZeroDisables:
    def test_no_op_when_cap_zero(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv(ENV_MAX_VAR, "0")
        monkeypatch.setenv(ENV_VAR, "8.8.8.8")
        n = MagicMock()
        n.netuid = 103
        n.uid = 7
        assert publish_egress_ips(n) is False
        n.subtensor.set_commitment.assert_not_called()

    def test_default_cap_is_one(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Out-of-the-box: only the most-recent detected IP is published."""
        monkeypatch.delenv(ENV_MAX_VAR, raising=False)
        monkeypatch.delenv(ENV_VAR, raising=False)
        monkeypatch.setattr(
            "djinn_validator.utils.egress_publisher.detect_egress_ip",
            lambda force=False: "203.0.113.42",
        )
        n = MagicMock()
        n.netuid = 103
        n.uid = 7
        n.subtensor.get_commitment.return_value = "1.1.1.1,2.2.2.2,3.3.3.3"
        assert publish_egress_ips(n) is True
        # Cap=1 truncates to just the new detected entry.
        assert n.subtensor.set_commitment.call_args.kwargs["data"] == "203.0.113.42"


class TestNormalize:
    def test_empty(self) -> None:
        assert _normalize(None) == []
        assert _normalize("") == []

    def test_preserves_input_order(self) -> None:
        """Insertion order is the wire format so FIFO eviction is meaningful."""
        assert _normalize("8.8.8.8,1.1.1.1") == ["8.8.8.8", "1.1.1.1"]

    def test_dedupes(self) -> None:
        assert _normalize("8.8.8.8,8.8.8.8,1.1.1.1") == ["8.8.8.8", "1.1.1.1"]

    def test_strips_whitespace(self) -> None:
        assert _normalize("  8.8.8.8 , 1.1.1.1 ") == ["8.8.8.8", "1.1.1.1"]

    def test_rejects_private_loopback_unspecified(self) -> None:
        assert _normalize("10.0.0.1,127.0.0.1,0.0.0.0") == []

    def test_rejects_garbage(self) -> None:
        assert _normalize("not-an-ip") == []

    def test_caps_at_max(self) -> None:
        many = ",".join(f"8.8.8.{i}" for i in range(1, 20))
        assert len(_normalize(many)) == HARD_MAX_IPS


@pytest.fixture
def neuron() -> MagicMock:
    n = MagicMock()
    n.netuid = 103
    n.uid = 7
    n.subtensor.get_commitment.return_value = ""
    return n


class TestParsePayload:
    def test_round_trip(self) -> None:
        # Insertion order preserved (matches what's written to chain)
        assert parse_payload("8.8.8.8,1.1.1.1") == ["8.8.8.8", "1.1.1.1"]

    def test_ignores_json(self) -> None:
        assert parse_payload('{"v":2,"url":"x"}') == []

    def test_handles_bytes(self) -> None:
        assert parse_payload(b"8.8.8.8") == ["8.8.8.8"]


class TestPublishEgressIps:
    def test_no_env_falls_back_to_detect(
        self, monkeypatch: pytest.MonkeyPatch, neuron: MagicMock
    ) -> None:
        """When the env is empty, publisher should auto-detect via reflector."""
        monkeypatch.delenv(ENV_VAR, raising=False)
        monkeypatch.setattr(
            "djinn_validator.utils.egress_publisher.detect_egress_ip",
            lambda force=False: "203.0.113.42",
        )
        assert publish_egress_ips(neuron) is True
        kwargs = neuron.subtensor.set_commitment.call_args.kwargs
        assert kwargs["data"] == "203.0.113.42"

    def test_no_env_no_detection_no_op(
        self, monkeypatch: pytest.MonkeyPatch, neuron: MagicMock
    ) -> None:
        monkeypatch.delenv(ENV_VAR, raising=False)
        monkeypatch.setattr(
            "djinn_validator.utils.egress_publisher.detect_egress_ip",
            lambda force=False: None,
        )
        assert publish_egress_ips(neuron) is False
        neuron.subtensor.set_commitment.assert_not_called()

    def test_env_overrides_detect(self, monkeypatch: pytest.MonkeyPatch, neuron: MagicMock) -> None:
        """Env var is the operator override; auto-detect should not be called."""
        monkeypatch.setenv(ENV_VAR, "8.8.8.8")
        monkeypatch.setattr(
            "djinn_validator.utils.egress_publisher.detect_egress_ip",
            lambda force=False: pytest.fail("should not auto-detect when env is set"),
        )
        assert publish_egress_ips(neuron) is True


class TestFifoAccumulation:
    """Auto-detect mode appends new IPs to the chain commitment up to MAX_IPS."""

    def _neuron(self, current: str) -> MagicMock:
        n = MagicMock()
        n.netuid = 103
        n.uid = 7
        n.subtensor.get_commitment.return_value = current
        return n

    def test_appends_new_ip(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv(ENV_VAR, raising=False)
        monkeypatch.setattr(
            "djinn_validator.utils.egress_publisher.detect_egress_ip",
            lambda force=False: "1.1.1.1",
        )
        n = self._neuron("8.8.8.8")
        assert publish_egress_ips(n) is True
        assert n.subtensor.set_commitment.call_args.kwargs["data"] == "8.8.8.8,1.1.1.1"

    def test_no_op_when_already_present(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv(ENV_VAR, raising=False)
        monkeypatch.setattr(
            "djinn_validator.utils.egress_publisher.detect_egress_ip",
            lambda force=False: "8.8.8.8",
        )
        n = self._neuron("8.8.8.8,1.1.1.1")
        assert publish_egress_ips(n) is False
        n.subtensor.set_commitment.assert_not_called()

    def test_drops_oldest_at_cap(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv(ENV_VAR, raising=False)
        monkeypatch.setattr(
            "djinn_validator.utils.egress_publisher.detect_egress_ip",
            lambda force=False: "9.9.9.9",
        )
        n = self._neuron("1.1.1.1,2.2.2.2,3.3.3.3,4.4.4.4,5.5.5.5")
        assert publish_egress_ips(n) is True
        # 1.1.1.1 was oldest; dropped. 9.9.9.9 appended at end.
        assert (
            n.subtensor.set_commitment.call_args.kwargs["data"]
            == "2.2.2.2,3.3.3.3,4.4.4.4,5.5.5.5,9.9.9.9"
        )

    def test_writes_when_chain_empty(
        self, monkeypatch: pytest.MonkeyPatch, neuron: MagicMock
    ) -> None:
        monkeypatch.setenv(ENV_VAR, "8.8.8.8,1.1.1.1")
        assert publish_egress_ips(neuron) is True
        neuron.subtensor.set_commitment.assert_called_once()
        kwargs = neuron.subtensor.set_commitment.call_args.kwargs
        assert kwargs["netuid"] == 103
        assert kwargs["data"] == "8.8.8.8,1.1.1.1"  # input order preserved

    def test_no_write_when_chain_matches(
        self, monkeypatch: pytest.MonkeyPatch, neuron: MagicMock
    ) -> None:
        monkeypatch.setenv(ENV_VAR, "8.8.8.8,1.1.1.1")
        neuron.subtensor.get_commitment.return_value = "8.8.8.8,1.1.1.1"
        assert publish_egress_ips(neuron) is False
        neuron.subtensor.set_commitment.assert_not_called()

    def test_rewrites_on_diff(self, monkeypatch: pytest.MonkeyPatch, neuron: MagicMock) -> None:
        monkeypatch.setenv(ENV_VAR, "8.8.8.8")
        neuron.subtensor.get_commitment.return_value = "9.9.9.9"
        assert publish_egress_ips(neuron) is True
        neuron.subtensor.set_commitment.assert_called_once()

    def test_swallows_get_failure_and_writes(
        self, monkeypatch: pytest.MonkeyPatch, neuron: MagicMock
    ) -> None:
        monkeypatch.setenv(ENV_VAR, "8.8.8.8")
        neuron.subtensor.get_commitment.side_effect = RuntimeError("rpc down")
        assert publish_egress_ips(neuron) is True

    def test_swallows_set_failure(
        self, monkeypatch: pytest.MonkeyPatch, neuron: MagicMock
    ) -> None:
        monkeypatch.setenv(ENV_VAR, "8.8.8.8")
        neuron.subtensor.set_commitment.side_effect = RuntimeError("rate limited")
        assert publish_egress_ips(neuron) is False

    def test_skips_when_no_neuron(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(ENV_VAR, "8.8.8.8")
        assert publish_egress_ips(None) is False

    def test_skips_when_sdk_lacks_set_commitment(
        self, monkeypatch: pytest.MonkeyPatch, neuron: MagicMock
    ) -> None:
        monkeypatch.setenv(ENV_VAR, "8.8.8.8")
        neuron.subtensor = MagicMock(spec=[])
        assert publish_egress_ips(neuron) is False

    def test_skips_when_uid_unset(self, monkeypatch: pytest.MonkeyPatch, neuron: MagicMock) -> None:
        monkeypatch.setenv(ENV_VAR, "8.8.8.8")
        neuron.uid = None
        assert publish_egress_ips(neuron) is False
