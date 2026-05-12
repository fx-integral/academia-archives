"""Tests for the validator-side egress commitment reader."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from djinn_validator.utils.egress_reader import (
    get_all_egress_commitments,
    reset_cache,
)


@pytest.fixture(autouse=True)
def _clear_cache() -> None:
    reset_cache()


def _mock_neuron(
    n: int, permits: list[bool], commitments: dict[int, str]
) -> MagicMock:
    neuron = MagicMock()
    neuron.netuid = 103
    neuron.metagraph.n = n
    neuron.metagraph.validator_permit = permits
    neuron.subtensor.get_commitment.side_effect = lambda netuid, uid: commitments.get(uid, "")
    return neuron


def test_returns_empty_when_no_neuron() -> None:
    assert get_all_egress_commitments(None) == {}


def test_only_validator_permit_uids() -> None:
    neuron = _mock_neuron(
        n=3,
        permits=[True, False, True],
        commitments={0: "8.8.8.8", 1: "9.9.9.9", 2: "1.1.1.1"},
    )
    out = get_all_egress_commitments(neuron)
    assert out == {0: ["8.8.8.8"], 2: ["1.1.1.1"]}


def test_omits_uids_with_no_commitment() -> None:
    neuron = _mock_neuron(
        n=2, permits=[True, True], commitments={0: "8.8.8.8"}
    )
    out = get_all_egress_commitments(neuron)
    assert out == {0: ["8.8.8.8"]}


def test_swallows_per_uid_exceptions() -> None:
    neuron = MagicMock()
    neuron.netuid = 103
    neuron.metagraph.n = 2
    neuron.metagraph.validator_permit = [True, True]

    def _flaky(netuid: int, uid: int) -> str:
        if uid == 0:
            raise RuntimeError("rpc down")
        return "8.8.8.8"

    neuron.subtensor.get_commitment.side_effect = _flaky
    out = get_all_egress_commitments(neuron)
    assert out == {1: ["8.8.8.8"]}


def test_caches_repeated_calls() -> None:
    neuron = _mock_neuron(n=1, permits=[True], commitments={0: "8.8.8.8"})
    get_all_egress_commitments(neuron)
    get_all_egress_commitments(neuron)
    assert neuron.subtensor.get_commitment.call_count == 1


def test_skips_when_sdk_lacks_get_commitment() -> None:
    neuron = MagicMock()
    neuron.subtensor = MagicMock(spec=[])
    assert get_all_egress_commitments(neuron) == {}


def test_drops_unparseable_payloads() -> None:
    neuron = _mock_neuron(
        n=2,
        permits=[True, True],
        commitments={0: "8.8.8.8", 1: '{"v":2,"url":"x"}'},
    )
    out = get_all_egress_commitments(neuron)
    assert out == {0: ["8.8.8.8"]}
