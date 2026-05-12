"""Tests for validator configuration loading and validation."""

from __future__ import annotations

import dataclasses
import logging
import os

import pytest

from djinn_validator.config import (
    CANONICAL_CONTRACT_ADDRESSES,
    CANONICAL_OUTCOME_VOTING_ADDRESS,
    Config,
    _float_env,
    _resolve_contract_address,
    _resolve_outcome_voting_address,
)


def _config(**overrides: object) -> Config:
    """Create a Config with overridden fields (bypasses frozen restriction)."""
    config = Config()
    for k, v in overrides.items():
        object.__setattr__(config, k, v)
    return config


class TestConfigDefaults:
    def test_default_port(self) -> None:
        config = Config()
        assert config.api_port == 8421

    def test_default_bt_network(self) -> None:
        config = Config()
        # conftest sets BT_NETWORK=test; verify Config reads from env
        expected = os.environ.get("BT_NETWORK", "finney")
        assert config.bt_network == expected

    def test_default_protocol_constants(self) -> None:
        config = Config()
        assert config.shares_total == 10
        # v1556: default matches web SHAMIR_MIN=SHAMIR_MAX=2 so validators
        # without explicit SHAMIR_THRESHOLD override can reconstruct signals
        # committed under current client settings. See MAINNET_BLOCKERS P0-01.
        assert config.shares_threshold == 2
        assert config.protocol_fee_bps == 50
        assert config.bps_denom == 10_000


class TestConfigValidation:
    def test_valid_config_no_warnings(self) -> None:
        config = _config(
            bt_network="local",
            sports_api_key="",
            base_validator_private_key="0x" + "ab" * 32,
        )
        warnings = config.validate()
        assert len(warnings) == 0

    def test_sports_api_key_set_warns_deprecated(self) -> None:
        config = _config(bt_network="local", sports_api_key="old-key")
        warnings = config.validate()
        assert any("no longer used" in w for w in warnings)

    def test_no_sports_api_key_no_warning(self) -> None:
        config = _config(bt_network="local", sports_api_key="")
        warnings = config.validate()
        assert not any("SPORTS_API_KEY" in w for w in warnings)

    def test_production_no_sports_api_key_ok(self) -> None:
        """Production no longer requires SPORTS_API_KEY."""
        config = _config(
            bt_network="finney",
            sports_api_key="",
            escrow_address="0x1234567890abcdef1234567890abcdef12345678",
            signal_commitment_address="0x1234567890abcdef1234567890abcdef12345678",
            account_address="0x1234567890abcdef1234567890abcdef12345678",
            collateral_address="0x1234567890abcdef1234567890abcdef12345678",
            outcome_voting_address="0x1234567890abcdef1234567890abcdef12345678",
            base_validator_private_key="0x" + "ab" * 32,
        )
        warnings = config.validate()
        assert not any("SPORTS_API_KEY" in w for w in warnings)

    def test_mainnet_missing_addresses_raises(self) -> None:
        config = _config(
            bt_network="finney",
            sports_api_key="",
            escrow_address="",
            signal_commitment_address="",
            account_address="",
            collateral_address="",
        )
        with pytest.raises(ValueError, match="must be set in production"):
            config.validate()

    def test_local_network_no_address_warnings(self) -> None:
        config = _config(
            bt_network="local",
            sports_api_key="",
            escrow_address="",
            base_validator_private_key="0x" + "ab" * 32,
        )
        warnings = config.validate()
        assert len(warnings) == 0

    def test_invalid_port_zero_raises(self) -> None:
        config = _config(api_port=0)
        with pytest.raises(ValueError, match="API_PORT"):
            config.validate()

    def test_invalid_port_too_high_raises(self) -> None:
        config = _config(api_port=70000)
        with pytest.raises(ValueError, match="API_PORT"):
            config.validate()


class TestConfigNetworkWarning:
    def test_known_network_no_warning(self) -> None:
        config = _config(
            bt_network="finney",
            sports_api_key="",
            escrow_address="0x1234567890abcdef1234567890abcdef12345678",
            signal_commitment_address="0x1234567890abcdef1234567890abcdef12345678",
            account_address="0x1234567890abcdef1234567890abcdef12345678",
            collateral_address="0x1234567890abcdef1234567890abcdef12345678",
            outcome_voting_address="0x1234567890abcdef1234567890abcdef12345678",
            base_validator_private_key="0x" + "ab" * 32,
        )
        warnings = config.validate()
        assert not any("BT_NETWORK" in w for w in warnings)

    def test_unknown_network_warns(self) -> None:
        config = _config(bt_network="devnet-42", sports_api_key="")
        warnings = config.validate()
        assert any("BT_NETWORK" in w for w in warnings)


class TestConfigStrictAutoDetect:
    """Strict mode auto-detects production network."""

    def test_strict_auto_enabled_on_finney(self) -> None:
        """Warnings are returned (not raised) even on finney."""
        config = _config(
            bt_network="finney",
            sports_api_key="",
            escrow_address="0x1234567890abcdef1234567890abcdef12345678",
            signal_commitment_address="0x1234567890abcdef1234567890abcdef12345678",
            account_address="0x1234567890abcdef1234567890abcdef12345678",
            collateral_address="0x1234567890abcdef1234567890abcdef12345678",
            outcome_voting_address="0x1234567890abcdef1234567890abcdef12345678",
            base_validator_private_key="0x" + "ab" * 32,
            base_chain_id=99999,  # Non-standard, generates a warning
        )
        warnings = config.validate()
        assert any("BASE_CHAIN_ID" in w for w in warnings)

    def test_warnings_returned_on_local(self) -> None:
        """Warnings are returned on local network too."""
        config = _config(
            bt_network="local",
            sports_api_key="",
            base_chain_id=99999,
        )
        warnings = config.validate()
        assert any("BASE_CHAIN_ID" in w for w in warnings)


class TestConfigTimeouts:
    def test_default_http_timeout(self) -> None:
        config = Config()
        assert config.http_timeout == 30

    def test_default_rpc_timeout(self) -> None:
        config = Config()
        assert config.rpc_timeout == 30

    def test_http_timeout_zero_raises(self) -> None:
        config = _config(bt_network="local", sports_api_key="", http_timeout=0)
        with pytest.raises(ValueError, match="HTTP_TIMEOUT"):
            config.validate()

    def test_rpc_timeout_zero_raises(self) -> None:
        config = _config(bt_network="local", sports_api_key="", rpc_timeout=0)
        with pytest.raises(ValueError, match="RPC_TIMEOUT"):
            config.validate()


class TestConfigNetuidValidation:
    def test_netuid_zero_raises(self) -> None:
        config = _config(bt_netuid=0, bt_network="local", sports_api_key="")
        with pytest.raises(ValueError, match="BT_NETUID"):
            config.validate()

    def test_netuid_too_high_raises(self) -> None:
        config = _config(bt_netuid=70000, bt_network="local", sports_api_key="")
        with pytest.raises(ValueError, match="BT_NETUID"):
            config.validate()

    def test_netuid_valid(self) -> None:
        config = _config(bt_netuid=103, bt_network="local", sports_api_key="")
        warnings = config.validate()
        assert not any("BT_NETUID" in w for w in warnings)


class TestConfigChainId:
    def test_standard_chain_id_no_warning(self) -> None:
        config = _config(bt_network="local", sports_api_key="", base_chain_id=8453)
        warnings = config.validate()
        assert not any("BASE_CHAIN_ID" in w for w in warnings)

    def test_localhost_chain_id_no_warning(self) -> None:
        config = _config(bt_network="local", sports_api_key="", base_chain_id=31337)
        warnings = config.validate()
        assert not any("BASE_CHAIN_ID" in w for w in warnings)

    def test_nonstandard_chain_id_warns(self) -> None:
        config = _config(bt_network="local", sports_api_key="", base_chain_id=999)
        warnings = config.validate()
        assert any("BASE_CHAIN_ID" in w for w in warnings)


class TestConfigRateLimits:
    def test_default_rate_limits(self) -> None:
        config = Config()
        # v1377 (P1-31): tightened from 60/10 to 30/4 ≈ 240/min per IP.
        assert config.rate_limit_capacity == 30
        assert config.rate_limit_rate == 4

    def test_rate_limit_capacity_zero_raises(self) -> None:
        config = _config(bt_network="local", sports_api_key="", rate_limit_capacity=0)
        with pytest.raises(ValueError, match="RATE_LIMIT_CAPACITY"):
            config.validate()

    def test_rate_limit_rate_zero_raises(self) -> None:
        config = _config(bt_network="local", sports_api_key="", rate_limit_rate=0)
        with pytest.raises(ValueError, match="RATE_LIMIT_RATE"):
            config.validate()


class TestConfigMPCPeerTimeout:
    def test_default_mpc_peer_timeout(self) -> None:
        config = Config()
        assert config.mpc_peer_timeout == 10.0

    def test_mpc_peer_timeout_too_low_raises(self) -> None:
        config = _config(bt_network="local", sports_api_key="", mpc_peer_timeout=0.5)
        with pytest.raises(ValueError, match="MPC_PEER_TIMEOUT"):
            config.validate()

    def test_mpc_peer_timeout_too_high_raises(self) -> None:
        config = _config(bt_network="local", sports_api_key="", mpc_peer_timeout=120.0)
        with pytest.raises(ValueError, match="MPC_PEER_TIMEOUT"):
            config.validate()

    def test_rate_limit_capacity_below_rate_warns(self) -> None:
        config = _config(
            bt_network="local",
            sports_api_key="",
            rate_limit_capacity=5,
            rate_limit_rate=10,
        )
        warnings = config.validate()
        assert any("RATE_LIMIT_CAPACITY" in w for w in warnings)


class TestConfigAddressValidation:
    def test_valid_address_accepted(self) -> None:
        config = _config(
            bt_network="finney",
            sports_api_key="",
            escrow_address="0x1234567890abcdef1234567890abcdef12345678",
            signal_commitment_address="0x1234567890abcdef1234567890abcdef12345678",
            account_address="0x1234567890abcdef1234567890abcdef12345678",
            collateral_address="0x1234567890abcdef1234567890abcdef12345678",
            outcome_voting_address="0x1234567890abcdef1234567890abcdef12345678",
            base_validator_private_key="0x" + "ab" * 32,
        )
        warnings = config.validate()
        assert not any("not a valid" in w for w in warnings)

    def test_invalid_address_format_raises(self) -> None:
        config = _config(
            bt_network="finney",
            sports_api_key="",
            escrow_address="not-an-address",
            signal_commitment_address="0x1234567890abcdef1234567890abcdef12345678",
            account_address="0x1234567890abcdef1234567890abcdef12345678",
            collateral_address="0x1234567890abcdef1234567890abcdef12345678",
        )
        with pytest.raises(ValueError, match="not a valid Ethereum address"):
            config.validate()

    def test_short_address_raises(self) -> None:
        config = _config(
            bt_network="finney",
            sports_api_key="",
            escrow_address="0x1234",
            signal_commitment_address="0x1234567890abcdef1234567890abcdef12345678",
            account_address="0x1234567890abcdef1234567890abcdef12345678",
            collateral_address="0x1234567890abcdef1234567890abcdef12345678",
        )
        with pytest.raises(ValueError, match="not a valid Ethereum address"):
            config.validate()

    def test_invalid_address_in_dev_mode_raises(self) -> None:
        config = _config(
            bt_network="local",
            sports_api_key="",
            escrow_address="not-an-address",
        )
        with pytest.raises(ValueError, match="not a valid Ethereum address"):
            config.validate()


class TestFloatEnv:
    def test_float_env_valid(self) -> None:
        import os

        os.environ["_TEST_FLOAT"] = "3.14"
        assert _float_env("_TEST_FLOAT", "1.0") == 3.14
        del os.environ["_TEST_FLOAT"]

    def test_float_env_default(self) -> None:
        assert _float_env("_TEST_FLOAT_MISSING", "2.5") == 2.5

    def test_float_env_malformed_raises(self) -> None:
        import os

        os.environ["_TEST_FLOAT_BAD"] = "not-a-number"
        with pytest.raises(ValueError, match="Invalid float"):
            _float_env("_TEST_FLOAT_BAD", "1.0")
        del os.environ["_TEST_FLOAT_BAD"]


class TestMpcAvailabilityTimeout:
    def test_default_value(self) -> None:
        config = Config()
        assert config.mpc_availability_timeout == 90.0

    def test_too_low_raises(self) -> None:
        config = _config(sports_api_key="", bt_network="local", mpc_availability_timeout=2.0)
        with pytest.raises(ValueError, match="MPC_AVAILABILITY_TIMEOUT"):
            config.validate()

    def test_too_high_raises(self) -> None:
        config = _config(sports_api_key="", bt_network="local", mpc_availability_timeout=200.0)
        with pytest.raises(ValueError, match="MPC_AVAILABILITY_TIMEOUT"):
            config.validate()

    def test_valid_range_accepted(self) -> None:
        config = _config(sports_api_key="", bt_network="local", mpc_availability_timeout=30.0)
        config.validate()


class TestShamirThresholdProduction:
    """Base MAINNET requires SHAMIR_THRESHOLD >= 3 for meaningful security.

    v1556: gate switched from BT_NETWORK-only to BT_NETWORK=finney AND
    BASE_CHAIN_ID=8453, because every SN103 validator runs BT_NETWORK=finney
    even on Sepolia testnet — the BT_NETWORK-only gate was silently blocking
    every Sepolia validator from booting at threshold<3 and made it impossible
    to ship the correct SHAMIR_THRESHOLD=2 that matches web SHAMIR_MIN=2.
    See MAINNET_BLOCKERS P0-01 and feedback_bt_network_vs_chain_id.md.
    """

    def _prod_config(self, **overrides: object) -> Config:
        defaults = dict(
            bt_network="finney",
            base_chain_id=8453,  # Base mainnet, where the >=3 floor applies
            sports_api_key="",
            escrow_address="0x1234567890abcdef1234567890abcdef12345678",
            signal_commitment_address="0x1234567890abcdef1234567890abcdef12345678",
            account_address="0x1234567890abcdef1234567890abcdef12345678",
            collateral_address="0x1234567890abcdef1234567890abcdef12345678",
            outcome_voting_address="0x1234567890abcdef1234567890abcdef12345678",
            base_validator_private_key="0x" + "ab" * 32,
        )
        defaults.update(overrides)
        return _config(**defaults)

    def test_threshold_1_raises_on_base_mainnet(self) -> None:
        config = self._prod_config(shares_threshold=1)
        with pytest.raises(ValueError, match="SHAMIR_THRESHOLD must be >= 3 on Base mainnet"):
            config.validate()

    def test_threshold_2_raises_on_base_mainnet(self) -> None:
        config = self._prod_config(shares_threshold=2)
        with pytest.raises(ValueError, match="SHAMIR_THRESHOLD must be >= 3 on Base mainnet"):
            config.validate()

    def test_threshold_3_passes_on_base_mainnet(self) -> None:
        config = self._prod_config(shares_threshold=3)
        warnings = config.validate()
        assert not any("SHAMIR_THRESHOLD" in w for w in warnings)

    def test_threshold_7_passes_on_base_mainnet(self) -> None:
        config = self._prod_config(shares_threshold=7)
        warnings = config.validate()
        assert not any("SHAMIR_THRESHOLD" in w for w in warnings)

    def test_threshold_2_allowed_on_base_sepolia(self) -> None:
        # bt_network=finney + base_chain_id=84532 (Sepolia) — current SN103 fleet
        config = self._prod_config(shares_threshold=2, base_chain_id=84532)
        warnings = config.validate()
        assert not any("SHAMIR_THRESHOLD" in w for w in warnings)

    def test_threshold_1_allowed_in_dev(self) -> None:
        config = _config(bt_network="local", sports_api_key="", shares_threshold=1)
        warnings = config.validate()
        assert not any("SHAMIR_THRESHOLD" in w for w in warnings)


class TestOutcomeVotingAddressResolution:
    """P1-01: OUTCOME_VOTING_ADDRESS env override is ignored by default.

    Operators who left stale pre-UUPS addresses in .env files silently broke
    settlement quorum. Code now hardcodes canonical; override requires
    DJINN_ALLOW_NONCANONICAL_OV=1.
    """

    def _clean_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("OUTCOME_VOTING_ADDRESS", raising=False)
        monkeypatch.delenv("DJINN_ALLOW_NONCANONICAL_OV", raising=False)
        # P0-07: canonical is per-chain. All legacy tests were written assuming
        # Base Sepolia (84532) — pin BASE_CHAIN_ID so the canonical lookup hits
        # the registered entry.
        monkeypatch.setenv("BASE_CHAIN_ID", "84532")

    def test_no_env_returns_canonical(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self._clean_env(monkeypatch)
        assert _resolve_outcome_voting_address() == CANONICAL_OUTCOME_VOTING_ADDRESS

    def test_stale_env_without_flag_is_ignored(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        self._clean_env(monkeypatch)
        stale = "0x28b5738ff35E207E90b2974cbfae2BdC556acAf6"
        monkeypatch.setenv("OUTCOME_VOTING_ADDRESS", stale)
        with caplog.at_level(logging.WARNING, logger="djinn_validator.config"):
            result = _resolve_outcome_voting_address()
        assert result == CANONICAL_OUTCOME_VOTING_ADDRESS
        assert any("Ignoring stale OUTCOME_VOTING_ADDRESS" in r.message for r in caplog.records)

    def test_canonical_env_without_flag_is_quiet(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        self._clean_env(monkeypatch)
        monkeypatch.setenv("OUTCOME_VOTING_ADDRESS", CANONICAL_OUTCOME_VOTING_ADDRESS)
        with caplog.at_level(logging.WARNING, logger="djinn_validator.config"):
            result = _resolve_outcome_voting_address()
        assert result == CANONICAL_OUTCOME_VOTING_ADDRESS
        assert not any("Ignoring stale" in r.message for r in caplog.records)

    def test_override_flag_honors_env(self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
        self._clean_env(monkeypatch)
        custom = "0x1234567890abcdef1234567890abcdef12345678"
        monkeypatch.setenv("OUTCOME_VOTING_ADDRESS", custom)
        monkeypatch.setenv("DJINN_ALLOW_NONCANONICAL_OV", "1")
        with caplog.at_level(logging.WARNING, logger="djinn_validator.config"):
            result = _resolve_outcome_voting_address()
        assert result == custom
        assert any("Using non-canonical OUTCOME_VOTING_ADDRESS" in r.message for r in caplog.records)

    def test_override_flag_with_canonical_env_is_quiet(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        self._clean_env(monkeypatch)
        monkeypatch.setenv("OUTCOME_VOTING_ADDRESS", CANONICAL_OUTCOME_VOTING_ADDRESS)
        monkeypatch.setenv("DJINN_ALLOW_NONCANONICAL_OV", "1")
        with caplog.at_level(logging.WARNING, logger="djinn_validator.config"):
            result = _resolve_outcome_voting_address()
        assert result == CANONICAL_OUTCOME_VOTING_ADDRESS
        assert not any("Using non-canonical" in r.message for r in caplog.records)

    def test_case_insensitive_match(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self._clean_env(monkeypatch)
        lower = CANONICAL_OUTCOME_VOTING_ADDRESS.lower()
        monkeypatch.setenv("OUTCOME_VOTING_ADDRESS", lower)
        assert _resolve_outcome_voting_address() == CANONICAL_OUTCOME_VOTING_ADDRESS

    def test_flag_other_than_1_does_not_enable(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Only DJINN_ALLOW_NONCANONICAL_OV=1 enables override; 'true'/'yes'/etc do not."""
        self._clean_env(monkeypatch)
        stale = "0x28b5738ff35E207E90b2974cbfae2BdC556acAf6"
        monkeypatch.setenv("OUTCOME_VOTING_ADDRESS", stale)
        for val in ("true", "yes", "TRUE", "0", ""):
            monkeypatch.setenv("DJINN_ALLOW_NONCANONICAL_OV", val)
            assert _resolve_outcome_voting_address() == CANONICAL_OUTCOME_VOTING_ADDRESS


class TestOutcomeVotingChainAwareness:
    """P0-07: canonical address is keyed by BASE_CHAIN_ID.

    Before this fix, a single testnet address was compiled in — a mainnet
    validator would have voted into a Sepolia contract (silent no-op;
    settlement stuck forever). Lookup is now chain-keyed; unregistered chain
    + no env override = loud error.
    """

    def test_sepolia_chain_id_returns_canonical_sepolia(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("OUTCOME_VOTING_ADDRESS", raising=False)
        monkeypatch.delenv("DJINN_ALLOW_NONCANONICAL_OV", raising=False)
        monkeypatch.setenv("BASE_CHAIN_ID", "84532")
        assert _resolve_outcome_voting_address() == CANONICAL_OUTCOME_VOTING_ADDRESS

    def test_mainnet_chain_id_no_env_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("OUTCOME_VOTING_ADDRESS", raising=False)
        monkeypatch.delenv("DJINN_ALLOW_NONCANONICAL_OV", raising=False)
        monkeypatch.setenv("BASE_CHAIN_ID", "8453")
        with pytest.raises(ValueError, match="No canonical OUTCOME_VOTING_ADDRESS"):
            _resolve_outcome_voting_address()

    def test_mainnet_chain_id_with_env_honors_env_and_warns(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Before mainnet proxy deploys, env override bridges the gap."""
        monkeypatch.delenv("DJINN_ALLOW_NONCANONICAL_OV", raising=False)
        monkeypatch.setenv("BASE_CHAIN_ID", "8453")
        custom = "0x1111111111111111111111111111111111111111"
        monkeypatch.setenv("OUTCOME_VOTING_ADDRESS", custom)
        with caplog.at_level(logging.WARNING, logger="djinn_validator.config"):
            result = _resolve_outcome_voting_address()
        assert result == custom
        assert any("No canonical OUTCOME_VOTING_ADDRESS" in r.message and "8453" in r.message for r in caplog.records)

    def test_unregistered_chain_id_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("OUTCOME_VOTING_ADDRESS", raising=False)
        monkeypatch.delenv("DJINN_ALLOW_NONCANONICAL_OV", raising=False)
        monkeypatch.setenv("BASE_CHAIN_ID", "999999")
        with pytest.raises(ValueError, match="BASE_CHAIN_ID=999999"):
            _resolve_outcome_voting_address()


class TestContractAddressResolution:
    """Follow-up to P0-07 + P1-01: extend the chain-aware canonical guard to
    the 4 non-OV proxy contracts (escrow, signal_commitment, account,
    collateral). Stale .env values silently broke settlement (P1-01) and
    cross-chain deploys (P0-07); same guard, same error cases, one unified
    flag DJINN_ALLOW_NONCANONICAL_CONTRACTS for emergency override.
    """

    @pytest.fixture(params=sorted(CANONICAL_CONTRACT_ADDRESSES))
    def env_key(self, request: pytest.FixtureRequest) -> str:
        return request.param

    def _clean_env(self, monkeypatch: pytest.MonkeyPatch, env_key: str) -> None:
        monkeypatch.delenv(env_key, raising=False)
        monkeypatch.delenv("DJINN_ALLOW_NONCANONICAL_CONTRACTS", raising=False)
        monkeypatch.setenv("BASE_CHAIN_ID", "84532")

    def test_no_env_returns_canonical(self, monkeypatch: pytest.MonkeyPatch, env_key: str) -> None:
        self._clean_env(monkeypatch, env_key)
        expected = CANONICAL_CONTRACT_ADDRESSES[env_key][84532]
        assert _resolve_contract_address(env_key) == expected

    def test_stale_env_without_flag_is_ignored(
        self,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
        env_key: str,
    ) -> None:
        self._clean_env(monkeypatch, env_key)
        stale = "0x1111111111111111111111111111111111111111"
        monkeypatch.setenv(env_key, stale)
        expected = CANONICAL_CONTRACT_ADDRESSES[env_key][84532]
        with caplog.at_level(logging.WARNING, logger="djinn_validator.config"):
            assert _resolve_contract_address(env_key) == expected
        assert any(f"Ignoring stale {env_key}" in r.message for r in caplog.records)

    def test_override_flag_honors_env(
        self,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
        env_key: str,
    ) -> None:
        self._clean_env(monkeypatch, env_key)
        custom = "0x2222222222222222222222222222222222222222"
        monkeypatch.setenv(env_key, custom)
        monkeypatch.setenv("DJINN_ALLOW_NONCANONICAL_CONTRACTS", "1")
        with caplog.at_level(logging.WARNING, logger="djinn_validator.config"):
            assert _resolve_contract_address(env_key) == custom
        assert any(f"Using non-canonical {env_key}" in r.message for r in caplog.records)

    def test_mainnet_no_canonical_no_env_raises(self, monkeypatch: pytest.MonkeyPatch, env_key: str) -> None:
        monkeypatch.delenv(env_key, raising=False)
        monkeypatch.delenv("DJINN_ALLOW_NONCANONICAL_CONTRACTS", raising=False)
        monkeypatch.setenv("BASE_CHAIN_ID", "8453")
        with pytest.raises(ValueError, match=f"No canonical {env_key}"):
            _resolve_contract_address(env_key)

    def test_mainnet_no_canonical_with_env_honors_env(self, monkeypatch: pytest.MonkeyPatch, env_key: str) -> None:
        monkeypatch.delenv("DJINN_ALLOW_NONCANONICAL_CONTRACTS", raising=False)
        monkeypatch.setenv("BASE_CHAIN_ID", "8453")
        custom = "0x3333333333333333333333333333333333333333"
        monkeypatch.setenv(env_key, custom)
        assert _resolve_contract_address(env_key) == custom

    def test_unknown_env_key_raises(self) -> None:
        with pytest.raises(ValueError, match="unknown env_key"):
            _resolve_contract_address("GHOST_ADDRESS")


class TestDefaultChainConsistency:
    """P0-07 follow-up: Config defaults for chain_id and outcome_voting_address
    must agree. A mismatch silently votes a mainnet-configured validator into
    the Sepolia OV contract.
    """

    def test_default_chain_id_matches_default_outcome_voting_address(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # Clear any ambient env the test runner set.
        monkeypatch.delenv("BASE_CHAIN_ID", raising=False)
        monkeypatch.delenv("OUTCOME_VOTING_ADDRESS", raising=False)
        monkeypatch.delenv("DJINN_ALLOW_NONCANONICAL_OV", raising=False)
        from djinn_validator.config import (
            CANONICAL_OUTCOME_VOTING_ADDRESSES,
            Config,
        )

        config = Config()
        canonical_for_default_chain = CANONICAL_OUTCOME_VOTING_ADDRESSES[config.base_chain_id]
        assert config.outcome_voting_address == canonical_for_default_chain, (
            f"Config default chain_id={config.base_chain_id} but "
            f"outcome_voting_address={config.outcome_voting_address} is not the "
            f"canonical for that chain. Defaults must stay in sync."
        )


class TestBaseRpcUrls:
    def test_single_url(self) -> None:
        config = _config(base_rpc_url="https://mainnet.base.org")
        assert config.base_rpc_urls == ["https://mainnet.base.org"]

    def test_multiple_urls(self) -> None:
        config = _config(base_rpc_url="https://rpc1.base.org, https://rpc2.base.org")
        assert config.base_rpc_urls == ["https://rpc1.base.org", "https://rpc2.base.org"]

    def test_empty_segments_stripped(self) -> None:
        config = _config(base_rpc_url="https://rpc1.base.org,,, https://rpc2.base.org,")
        assert config.base_rpc_urls == ["https://rpc1.base.org", "https://rpc2.base.org"]
