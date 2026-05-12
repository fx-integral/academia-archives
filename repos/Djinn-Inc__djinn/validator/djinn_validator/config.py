"""Validator configuration loaded from environment variables."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()

_log = logging.getLogger(__name__)


def _int_env(key: str, default: str) -> int:
    val = os.getenv(key, default)
    try:
        return int(val)
    except (ValueError, TypeError, OverflowError):
        raise ValueError(f"Invalid integer for {key}: {val!r}")


def _float_env(key: str, default: str) -> float:
    val = os.getenv(key, default)
    try:
        return float(val)
    except (ValueError, TypeError, OverflowError):
        raise ValueError(f"Invalid float for {key}: {val!r}")


# Canonical OutcomeVoting proxy addresses keyed by Base chain_id. The proxy
# address is the permanent on-chain identity; upgrades change the impl slot,
# never the proxy. Each chain needs its own entry. MAINNET_BLOCKERS P0-07.
#
# When mainnet (8453) deploys its proxy, add the entry here and delete the
# mainnet-missing branch in _resolve_outcome_voting_address.
CANONICAL_OUTCOME_VOTING_ADDRESSES: dict[int, str] = {
    84532: "0xAD534f4CAB13707BD4d65e4EF086A455e6A643e5",  # Base Sepolia (current testnet)
}

# Backward-compatible alias pointing at the Sepolia canonical address.
# Tests and older imports rely on this name; keep it until the mainnet
# entry is populated, then it becomes ambiguous and should be removed.
CANONICAL_OUTCOME_VOTING_ADDRESS = CANONICAL_OUTCOME_VOTING_ADDRESSES[84532]


def _canonical_outcome_voting_address(chain_id: int) -> str:
    addr = CANONICAL_OUTCOME_VOTING_ADDRESSES.get(chain_id)
    if addr is None:
        raise ValueError(
            f"No canonical OUTCOME_VOTING_ADDRESS registered for "
            f"BASE_CHAIN_ID={chain_id}. Registered chains: "
            f"{sorted(CANONICAL_OUTCOME_VOTING_ADDRESSES)}. If this is a new "
            f"chain (e.g. mainnet 8453 post-deploy), add the proxy address to "
            f"config.CANONICAL_OUTCOME_VOTING_ADDRESSES."
        )
    return addr


# P0-07 follow-up / audit finding: extend the same chain-aware guard to the
# other proxy addresses. Stale .env values (left over from pre-UUPS deploys)
# silently broke settlement via OUTCOME_VOTING_ADDRESS before P1-01 fixed it.
# The SAME failure mode exists for ESCROW_ADDRESS / SIGNAL_COMMITMENT_ADDRESS /
# ACCOUNT_ADDRESS / COLLATERAL_ADDRESS: an operator with a stale .env would
# have their validator read/write to a dead contract and fail silently.
#
# Layout: outer key = env var name; inner key = chain_id -> canonical proxy.
CANONICAL_CONTRACT_ADDRESSES: dict[str, dict[int, str]] = {
    "ESCROW_ADDRESS": {
        84532: "0xb43BA175a6784973eB3825acF801Cd7920ac692a",  # Base Sepolia
    },
    "SIGNAL_COMMITMENT_ADDRESS": {
        84532: "0x4712479Ba57c9ED40405607b2B18967B359209C0",  # Base Sepolia
    },
    "ACCOUNT_ADDRESS": {
        84532: "0x4546354Dd32a613B76Abf530F81c8359e7cE440B",  # Base Sepolia
    },
    "COLLATERAL_ADDRESS": {
        84532: "0x71F0a8c6BBFc4C83c5203807fAdd305B0C0F4C88",  # Base Sepolia
    },
    # Sprint B Stage 4 additions — needed so /v1/network/config can emit the
    # full contracts blob for static SDK consumers without a Vercel proxy.
    # These four are not currently read/written by the validator directly;
    # they're published-only. The canonical guard is still applied so a
    # stale operator .env can't lie to clients about the protocol topology.
    "AUDIT_ADDRESS": {
        84532: "0xCa7e642FE31BA83a7a857644E8894c1B93a2a44E",  # Base Sepolia
    },
    "CREDIT_LEDGER_ADDRESS": {
        84532: "0xA65296cd11B65629641499024AD905FAcAB64C3E",  # Base Sepolia
    },
    "KEY_RECOVERY_ADDRESS": {
        84532: "0x496919DB9BC4590323cd019fE874311AC6116525",  # Base Sepolia
    },
    "USDC_ADDRESS": {
        84532: "0x00e8293b05dbD3732EF3396ad1483E87e7265054",  # Base Sepolia MockUSDC
    },
    "LINE_OUTCOME_REGISTRY_ADDRESS": {
        84532: "0x2AB6ef76464D25713dfc3b9613f6AD2d07218352",  # v1747, deployed 2026-05-09
    },
}


def _resolve_contract_address(env_key: str) -> str:
    """Resolve a proxy contract address with the P0-07 / P1-01 guard applied.

    Mirrors _resolve_outcome_voting_address exactly, just parameterized over
    env_key. Canonical per chain_id is hardcoded; env overrides are warned-and-
    ignored unless DJINN_ALLOW_NONCANONICAL_CONTRACTS=1. Single flag covers the
    four addresses managed here (escrow, signal_commitment, account, collateral)
    — OutcomeVoting keeps its own historical flag DJINN_ALLOW_NONCANONICAL_OV.

    Raises ValueError if the chain has no canonical AND no env override — same
    fail-loud behavior as _resolve_outcome_voting_address.
    """
    canonical_map = CANONICAL_CONTRACT_ADDRESSES.get(env_key)
    if canonical_map is None:
        raise ValueError(
            f"_resolve_contract_address called with unknown env_key={env_key!r}. "
            f"Registered keys: {sorted(CANONICAL_CONTRACT_ADDRESSES)}."
        )

    chain_id = _int_env("BASE_CHAIN_ID", "84532")
    canonical = canonical_map.get(chain_id)
    env_override = os.getenv(env_key)
    allow_flag = os.getenv("DJINN_ALLOW_NONCANONICAL_CONTRACTS") == "1"

    if canonical is None:
        # Chain has no registered canonical. Bridge via env override during
        # pre-launch windows; fail loud once deployed if still missing.
        if env_override:
            _log.warning(
                "No canonical %s registered for BASE_CHAIN_ID=%s; using env "
                "value %s. Update config.CANONICAL_CONTRACT_ADDRESSES[%r] once "
                "the chain has a deployed proxy so operators don't need the "
                "env override.",
                env_key,
                chain_id,
                env_override,
                env_key,
            )
            return env_override
        raise ValueError(
            f"No canonical {env_key} registered for BASE_CHAIN_ID={chain_id}. "
            f"Registered chains for this key: "
            f"{sorted(canonical_map)}. If this is a new chain (e.g. mainnet "
            f"8453 post-deploy), add the proxy address to "
            f"config.CANONICAL_CONTRACT_ADDRESSES[{env_key!r}]."
        )

    if env_override and allow_flag:
        if env_override.lower() != canonical.lower():
            _log.warning(
                "Using non-canonical %s=%s (canonical for chain_id=%s is %s, "
                "DJINN_ALLOW_NONCANONICAL_CONTRACTS=1). Validator will read "
                "from and write to this address.",
                env_key,
                env_override,
                chain_id,
                canonical,
            )
        return env_override
    if env_override and env_override.lower() != canonical.lower():
        _log.warning(
            "Ignoring stale %s=%s in environment; using canonical %s for "
            "chain_id=%s. To override, set DJINN_ALLOW_NONCANONICAL_CONTRACTS=1.",
            env_key,
            env_override,
            canonical,
            chain_id,
        )
    return canonical


def _resolve_outcome_voting_address() -> str:
    """Resolve the OutcomeVoting contract address.

    Operators shouldn't need to touch this. Stale OUTCOME_VOTING_ADDRESS values
    in .env files (left over from pre-UUPS deploys) silently broke settlement
    quorum — validators voted into dead contracts. This function hardcodes the
    canonical address per-chain and ignores env overrides by default. To override
    (local forks / tests / emergency hotfix), set DJINN_ALLOW_NONCANONICAL_OV=1.

    Chain-awareness (P0-07): the canonical proxy address is DIFFERENT on
    testnet vs mainnet. Before this fix, a single Sepolia address was compiled
    in — a mainnet validator would have voted into a Sepolia contract (silent
    no-op). Now the lookup is keyed by BASE_CHAIN_ID.
    """
    # Default to Base Sepolia (84532) matches what today's validators actually
    # run. A mainnet validator MUST set BASE_CHAIN_ID=8453 explicitly; if they
    # forget, they get the (safe) testnet canonical rather than trying to vote
    # into mainnet with no canonical registered. When mainnet proxies deploy,
    # either add 8453 to CANONICAL_OUTCOME_VOTING_ADDRESSES or flip the default.
    chain_id = _int_env("BASE_CHAIN_ID", "84532")
    try:
        canonical = _canonical_outcome_voting_address(chain_id)
    except ValueError:
        # Chain is registered nowhere. Before mainnet proxy deploys, allow an
        # explicit env override so operators aren't blocked; warn loudly since
        # there is no canonical to check against.
        env_override = os.getenv("OUTCOME_VOTING_ADDRESS")
        if env_override:
            _log.warning(
                "No canonical OUTCOME_VOTING_ADDRESS registered for "
                "BASE_CHAIN_ID=%s; using OUTCOME_VOTING_ADDRESS=%s from env. "
                "Update config.CANONICAL_OUTCOME_VOTING_ADDRESSES once the "
                "chain has a deployed proxy so operators don't need the env "
                "override.",
                chain_id,
                env_override,
            )
            return env_override
        raise

    env_override = os.getenv("OUTCOME_VOTING_ADDRESS")
    allow_flag = os.getenv("DJINN_ALLOW_NONCANONICAL_OV") == "1"
    if env_override and allow_flag:
        if env_override.lower() != canonical.lower():
            _log.warning(
                "Using non-canonical OUTCOME_VOTING_ADDRESS=%s "
                "(canonical for chain_id=%s is %s, "
                "DJINN_ALLOW_NONCANONICAL_OV=1). "
                "Settlement votes will be cast to this address.",
                env_override,
                chain_id,
                canonical,
            )
        return env_override
    if env_override and env_override.lower() != canonical.lower():
        _log.warning(
            "Ignoring stale OUTCOME_VOTING_ADDRESS=%s in environment; "
            "using canonical %s for chain_id=%s. To override, set "
            "DJINN_ALLOW_NONCANONICAL_OV=1.",
            env_override,
            canonical,
            chain_id,
        )
    return canonical


@dataclass(frozen=True)
class Config:
    _REDACTED_FIELDS = frozenset(
        {
            "base_validator_private_key",
            "sports_api_key",
            "admin_api_key",
            "odds_api_keys",
        }
    )

    def __repr__(self) -> str:
        fields = []
        for f in self.__dataclass_fields__:
            val = getattr(self, f)
            if f in self._REDACTED_FIELDS and val:
                fields.append(f"{f}='***REDACTED***'")
            else:
                fields.append(f"{f}={val!r}")
        return f"Config({', '.join(fields)})"

    # Bittensor
    bt_netuid: int = _int_env("BT_NETUID", "103")
    bt_network: str = os.getenv("BT_NETWORK", "finney")
    bt_wallet_name: str = os.getenv("BT_WALLET_NAME", "default")
    bt_wallet_hotkey: str = os.getenv("BT_WALLET_HOTKEY", "default")
    # Burn fraction is a protocol parameter, not operator-configurable.
    # Hardcoded so .env overrides can't cause validators to diverge.
    # If you previously had BT_BURN_FRACTION in your .env, it is now ignored.
    bt_burn_fraction: float = 0.80

    # Base chain (comma-separated URLs for failover)
    # Defaults target Base Sepolia (84532) to match the rest of Config (contract
    # addresses below are Sepolia proxies). A mainnet validator MUST set
    # BASE_CHAIN_ID=8453, BASE_RPC_URL, and the contract-address envs together.
    # See _resolve_outcome_voting_address — it uses the same 84532 default so
    # the two stay consistent; an inconsistent default silently votes a
    # mainnet-configured validator into the Sepolia OV contract.
    base_rpc_url: str = os.getenv("BASE_RPC_URL", "https://sepolia.base.org")
    base_chain_id: int = _int_env("BASE_CHAIN_ID", "84532")

    @property
    def base_rpc_urls(self) -> list[str]:
        """Parse comma-separated RPC URLs for failover support."""
        return [u.strip() for u in self.base_rpc_url.split(",") if u.strip()]

    # Validator Base chain private key (for signing outcome settlement txs)
    base_validator_private_key: str = os.getenv("BASE_VALIDATOR_PRIVATE_KEY", "")

    # Contract addresses. All use the chain-aware canonical guard — env
    # overrides are ignored unless DJINN_ALLOW_NONCANONICAL_CONTRACTS=1 for the
    # first four, or DJINN_ALLOW_NONCANONICAL_OV=1 for outcome voting (kept
    # separate for backward compat). Operators never need to touch these on
    # Base Sepolia (84532). Mainnet requires BASE_CHAIN_ID=8453 AND the
    # addresses populated in config.CANONICAL_CONTRACT_ADDRESSES once the
    # mainnet proxies deploy.
    escrow_address: str = _resolve_contract_address("ESCROW_ADDRESS")
    signal_commitment_address: str = _resolve_contract_address("SIGNAL_COMMITMENT_ADDRESS")
    account_address: str = _resolve_contract_address("ACCOUNT_ADDRESS")
    collateral_address: str = _resolve_contract_address("COLLATERAL_ADDRESS")
    outcome_voting_address: str = _resolve_outcome_voting_address()
    audit_address: str = _resolve_contract_address("AUDIT_ADDRESS")
    credit_ledger_address: str = _resolve_contract_address("CREDIT_LEDGER_ADDRESS")
    key_recovery_address: str = _resolve_contract_address("KEY_RECOVERY_ADDRESS")
    usdc_address: str = _resolve_contract_address("USDC_ADDRESS")
    line_outcome_registry_address: str = _resolve_contract_address("LINE_OUTCOME_REGISTRY_ADDRESS")

    # Validator API
    api_host: str = os.getenv("API_HOST", "0.0.0.0")
    api_port: int = _int_env("API_PORT", "8421")

    # External address for metagraph discovery (set when behind NAT/proxy)
    external_ip: str = os.getenv("EXTERNAL_IP", "")
    external_port: int = _int_env("EXTERNAL_PORT", "0")

    # Sports data
    sports_api_key: str = os.getenv("SPORTS_API_KEY", "")

    # Odds API multi-key rotation (comma-separated).
    # Sprint A Stage A-1: validator serves /v1/odds directly instead of
    # proxying through Vercel. Each operator sets its own ODDS_API_KEYS.
    # Legacy ODDS_API_KEY (single) is still honored by odds_feed.py.
    odds_api_keys: tuple[str, ...] = tuple(
        k.strip() for k in os.getenv("ODDS_API_KEYS", os.getenv("ODDS_API_KEY", "")).split(",") if k.strip()
    )

    # Timeouts (seconds)
    http_timeout: int = _int_env("HTTP_TIMEOUT", "30")
    rpc_timeout: int = _int_env("RPC_TIMEOUT", "30")

    # Rate limits (configurable without redeploy).
    # Defaults: 30 burst, 4 req/sec ≈ 240/min per IP per path. Tighter
    # than the prior 60/10 = 600/min because browsers now hit validators
    # directly (post-DEV-045 IPFS serving path); the 200-300/min band
    # matches the Vercel edge middleware that used to gate traffic.
    # MAINNET P1-31.
    rate_limit_capacity: int = _int_env("RATE_LIMIT_CAPACITY", "30")
    rate_limit_rate: int = _int_env("RATE_LIMIT_RATE", "4")

    # MPC
    mpc_peer_timeout: float = _float_env("MPC_PEER_TIMEOUT", "10.0")
    mpc_availability_timeout: float = _float_env("MPC_AVAILABILITY_TIMEOUT", "90.0")

    # Fallback miner URL for attestation when no miners on metagraph
    fallback_miner_url: str = os.getenv("FALLBACK_MINER_URL", "")

    # Admin API key (optional — if set, admin/telemetry endpoints require Bearer token)
    admin_api_key: str = os.getenv("ADMIN_API_KEY", "")

    # Data directory for SQLite databases (shares, attestations, purchases)
    data_dir: str = os.getenv("DATA_DIR", "data")

    # Protocol constants
    signals_per_cycle: int = 10
    shares_total: int = 10
    # Shamir reconstruction threshold. MUST match the client-side commit
    # threshold (web/app/genius/signal/new/page.tsx: SHAMIR_MIN=SHAMIR_MAX=2
    # as of 2026-04-21, so every signal is 2-of-2 Shamir). v1556 lowers the
    # default from 7 to 2 to match reality — the stale 7-default was silent-
    # skipping every reconstruction and blocking P0-01 settlement on every
    # validator without an explicit override (batch_settle_audit_set loops
    # through outcome_selection_failed_skipped -> audit_set_no_settable_signals
    # -> settlement_skipped_no_batch_result every ~20s). See MAINNET_BLOCKERS
    # P0-01 note at 2026-04-21 01:45Z and feedback_bt_network_vs_chain_id.md
    # for the matching pattern (config default decoupled from deployment
    # reality). Raise SHAMIR_THRESHOLD in .env if commit-time threshold ever
    # goes above 2, but for the current Sepolia fleet 2 is correct.
    shares_threshold: int = _int_env("SHAMIR_THRESHOLD", "2")
    mpc_quorum: float = 2 / 3
    protocol_fee_bps: int = 50
    odds_precision: int = 1_000_000
    bps_denom: int = 10_000

    def validate(self) -> list[str]:
        """Validate config at startup. Returns list of warnings (empty = all good).

        Hard errors (missing keys, invalid addresses) raise ValueError.
        Soft warnings (deprecated env vars, non-standard values) are returned
        as strings for logging but never prevent startup.
        """
        import re

        warnings = []
        if not (0.0 <= self.bt_burn_fraction <= 1.0):
            raise ValueError(f"BT_BURN_FRACTION must be 0.0-1.0, got {self.bt_burn_fraction}")
        env_burn = os.getenv("BT_BURN_FRACTION")
        if env_burn is not None:
            warnings.append(
                f"BT_BURN_FRACTION={env_burn} found in your .env but is ignored. "
                f"Burn fraction is now a hardcoded protocol parameter ({self.bt_burn_fraction}). "
                f"Remove BT_BURN_FRACTION from your .env to silence this warning."
            )
        if not (1 <= self.bt_netuid <= 65535):
            raise ValueError(f"BT_NETUID must be 1-65535, got {self.bt_netuid}")
        if self.api_port < 1 or self.api_port > 65535:
            raise ValueError(f"API_PORT must be 1-65535, got {self.api_port}")
        is_production = self.bt_network in ("finney", "mainnet")
        if self.sports_api_key:
            warnings.append(
                "SPORTS_API_KEY is set but no longer used — " "validator now uses ESPN's free public API for scores"
            )
        contract_names = (
            "escrow_address",
            "signal_commitment_address",
            "account_address",
            "collateral_address",
            "outcome_voting_address",
        )
        if is_production:
            for name in contract_names:
                addr = getattr(self, name)
                if not addr:
                    raise ValueError(f"{name.upper()} must be set in production")
                elif not re.match(r"^0x[0-9a-fA-F]{40}$", addr):
                    raise ValueError(f"{name.upper()} is not a valid Ethereum address: {addr!r}")
        elif self.bt_network not in ("finney", "mainnet"):
            for name in contract_names:
                addr = getattr(self, name)
                if addr and not re.match(r"^0x[0-9a-fA-F]{40}$", addr):
                    raise ValueError(f"{name.upper()} is not a valid Ethereum address: {addr!r}")
        if not self.base_validator_private_key:
            if is_production:
                raise ValueError(
                    "BASE_VALIDATOR_PRIVATE_KEY must be set in production — outcome settlement requires it"
                )
            warnings.append("BASE_VALIDATOR_PRIVATE_KEY not set — on-chain outcome settlement disabled")
        elif not re.match(r"^(0x)?[0-9a-fA-F]{64}$", self.base_validator_private_key):
            raise ValueError("BASE_VALIDATOR_PRIVATE_KEY must be a 32-byte hex string (with optional 0x prefix)")
        known_networks = ("finney", "mainnet", "test", "local", "mock")
        if self.bt_network not in known_networks:
            warnings.append(f"BT_NETWORK={self.bt_network!r} is not a recognized network ({', '.join(known_networks)})")
        if self.http_timeout < 1:
            raise ValueError(f"HTTP_TIMEOUT must be >= 1, got {self.http_timeout}")
        if self.rpc_timeout < 1:
            raise ValueError(f"RPC_TIMEOUT must be >= 1, got {self.rpc_timeout}")
        if self.base_chain_id not in (8453, 84532, 31337):
            warnings.append(
                f"BASE_CHAIN_ID={self.base_chain_id} is non-standard "
                "(expected 8453=mainnet, 84532=sepolia, 31337=localhost)"
            )
        if self.rate_limit_capacity < 1:
            raise ValueError(f"RATE_LIMIT_CAPACITY must be >= 1, got {self.rate_limit_capacity}")
        if self.rate_limit_rate < 1:
            raise ValueError(f"RATE_LIMIT_RATE must be >= 1, got {self.rate_limit_rate}")
        if self.mpc_peer_timeout < 1.0 or self.mpc_peer_timeout > 60.0:
            raise ValueError(f"MPC_PEER_TIMEOUT must be 1.0-60.0, got {self.mpc_peer_timeout}")
        if self.mpc_availability_timeout < 5.0 or self.mpc_availability_timeout > 120.0:
            raise ValueError(f"MPC_AVAILABILITY_TIMEOUT must be 5.0-120.0, got {self.mpc_availability_timeout}")
        if self.shares_threshold > self.shares_total:
            raise ValueError(
                f"SHAMIR_THRESHOLD ({self.shares_threshold}) must be <= shares_total ({self.shares_total})"
            )
        if self.shares_threshold < 1:
            raise ValueError(f"SHAMIR_THRESHOLD must be >= 1, got {self.shares_threshold}")
        # Production Shamir-threshold floor. "Production" for this check means
        # Base MAINNET (real USDC, real money) — not just BT_NETWORK=finney
        # (every SN103 validator runs finney even on Sepolia). Without this
        # split the check would hard-fail the whole Sepolia fleet on startup
        # for shares_threshold < 3, which is wrong: client commits at
        # SHAMIR_MIN=SHAMIR_MAX=2 today, so threshold=2 is the correct
        # validator-side value for Sepolia. See v1455 precedent
        # (feedback_bt_network_vs_chain_id.md) for the same lesson.
        if is_production and self.base_chain_id == 8453 and self.shares_threshold < 3:
            raise ValueError(
                f"SHAMIR_THRESHOLD must be >= 3 on Base mainnet for meaningful secret sharing, "
                f"got {self.shares_threshold}"
            )
        if self.rate_limit_capacity < self.rate_limit_rate:
            warnings.append(
                f"RATE_LIMIT_CAPACITY ({self.rate_limit_capacity}) < RATE_LIMIT_RATE ({self.rate_limit_rate}) "
                "-- bucket will never fill above rate"
            )
        if is_production and not self.admin_api_key:
            import structlog as _sl

            _sl.get_logger().warning("ADMIN_API_KEY not set - admin endpoints are unprotected")
            warnings.append("ADMIN_API_KEY not set - admin endpoints are unprotected on a production network")
        # Warnings are logged but never fatal. Real config errors use
        # raise ValueError() above. The old strict-mode crash prevented
        # validators from starting when they had deprecated env vars
        # (SPORTS_API_KEY, BT_BURN_FRACTION) in their .env files.
        return warnings
