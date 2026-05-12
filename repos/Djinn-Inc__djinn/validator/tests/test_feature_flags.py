"""Tests for the feature flag registry."""

from __future__ import annotations

import importlib
import os

import pytest


@pytest.fixture
def fresh_flags(monkeypatch):
    """Clear all DJINN_FF_* env vars and return a freshly-imported flags module.

    Sets BASE_CHAIN_ID=8453 (mainnet) so _on_sepolia=False and all flags
    default to False. Tests that specifically exercise Sepolia defaults should
    set BASE_CHAIN_ID=84532 before calling _reload().
    """
    for key in list(os.environ.keys()):
        if key.startswith("DJINN_FF_"):
            monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("BASE_CHAIN_ID", "8453")

    def _reload():
        from djinn_validator import feature_flags

        importlib.reload(feature_flags)
        return feature_flags

    return _reload


def test_all_flags_default_off(fresh_flags):
    ff = fresh_flags()
    assert ff.flags.circuit_breaker is False
    assert ff.flags.canonical_odds is False
    assert ff.flags.appeal_mechanism is False
    assert ff.flags.purchase_v2 is False
    assert ff.flags.new_miner_zero_weight is False
    assert ff.flags.quorum_strict is False


def test_flag_can_be_enabled(fresh_flags, monkeypatch):
    monkeypatch.setenv("DJINN_FF_CIRCUIT_BREAKER", "true")
    ff = fresh_flags()
    assert ff.flags.circuit_breaker is True


@pytest.mark.parametrize("value", ["1", "true", "yes", "on", "TRUE", "YES", "On"])
def test_truthy_values(fresh_flags, monkeypatch, value):
    monkeypatch.setenv("DJINN_FF_CIRCUIT_BREAKER", value)
    ff = fresh_flags()
    assert ff.flags.circuit_breaker is True


@pytest.mark.parametrize("value", ["0", "false", "no", "off", "", "garbage"])
def test_falsy_values(fresh_flags, monkeypatch, value):
    monkeypatch.setenv("DJINN_FF_CIRCUIT_BREAKER", value)
    ff = fresh_flags()
    assert ff.flags.circuit_breaker is False


def test_enabled_iterator(fresh_flags, monkeypatch):
    monkeypatch.setenv("DJINN_FF_CIRCUIT_BREAKER", "true")
    monkeypatch.setenv("DJINN_FF_PURCHASE_V2", "true")
    ff = fresh_flags()
    enabled = sorted(ff.flags.enabled())
    assert enabled == ["circuit_breaker", "purchase_v2"]


def test_summary_when_all_off(fresh_flags):
    ff = fresh_flags()
    assert ff.flags.summary() == "feature flags: all OFF"


def test_summary_when_some_on(fresh_flags, monkeypatch):
    monkeypatch.setenv("DJINN_FF_CANONICAL_ODDS", "true")
    ff = fresh_flags()
    summary = ff.flags.summary()
    assert "ON" in summary
    assert "canonical_odds" in summary


def test_as_dict_includes_all_flags(fresh_flags):
    ff = fresh_flags()
    d = ff.flags.as_dict()
    assert set(d.keys()) == {
        "circuit_breaker",
        "canonical_odds",
        "appeal_mechanism",
        "purchase_v2",
        "new_miner_zero_weight",
        "quorum_strict",
        "batch_settlement_http",
        "batch_settlement_http_submit",
        "reliability_weight",
        "proof_complexity_weight",
        "strict_peer_hotkey",
    }
    assert all(v is False for v in d.values())


def test_settlement_flags_default_on_on_sepolia(fresh_flags, monkeypatch):
    # v1567: batch_settlement_http and batch_settlement_http_submit default to True
    # on Base Sepolia (BASE_CHAIN_ID=84532). Validators already perform on-chain
    # duties (metagraph weights, registration) — submitVote is the same category.
    monkeypatch.setenv("BASE_CHAIN_ID", "84532")
    ff = fresh_flags()
    assert ff.flags.batch_settlement_http is True
    assert ff.flags.batch_settlement_http_submit is True


def test_settlement_flags_default_off_on_mainnet(fresh_flags, monkeypatch):
    # On Base mainnet (BASE_CHAIN_ID=8453) the flags remain OFF until a deliberate
    # mainnet crank-up. Operators opt in explicitly via env var.
    monkeypatch.setenv("BASE_CHAIN_ID", "8453")
    ff = fresh_flags()
    assert ff.flags.batch_settlement_http is False
    assert ff.flags.batch_settlement_http_submit is False


def test_settlement_flags_can_be_overridden_on_sepolia(fresh_flags, monkeypatch):
    # Explicit env var always wins over the chain-id default (kill switch).
    monkeypatch.setenv("BASE_CHAIN_ID", "84532")
    monkeypatch.setenv("DJINN_FF_BATCH_SETTLEMENT_HTTP_SUBMIT", "false")
    ff = fresh_flags()
    assert ff.flags.batch_settlement_http_submit is False


def test_independent_flag_toggles(fresh_flags, monkeypatch):
    monkeypatch.setenv("DJINN_FF_CIRCUIT_BREAKER", "true")
    monkeypatch.setenv("DJINN_FF_QUORUM_STRICT", "false")
    ff = fresh_flags()
    assert ff.flags.circuit_breaker is True
    assert ff.flags.quorum_strict is False
