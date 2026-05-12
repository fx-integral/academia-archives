# The MIT License (MIT)
# Copyright © 2023 Yuma Rao
# Copyright © 2023 Opentensor Foundation
# Copyright © 2026 UnitOne Labs

# Permission is hereby granted, free of charge, to any person obtaining a copy of this software and associated
# documentation files (the "Software"), to deal in the Software without restriction, including without limitation
# the rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the Software,
# and to permit persons to whom the Software is furnished to do so, subject to the following conditions:

# The above copyright notice and this permission notice shall be included in all copies or substantial portions of
# the Software.

# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO
# THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL
# THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION
# OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER
# DEALINGS IN THE SOFTWARE.

import os
import argparse
from pathlib import Path
import bittensor as bt
from .logging import setup_events_logger

DEFAULT_GATEWAY_URL = "https://gateway-dev.flamewire.io"
DEFAULT_VALIDATOR_MAX_WORKERS = 32
DEFAULT_VALIDATOR_EMA_ALPHA = 0.1
DEFAULT_VALIDATOR_VERIFICATION_INTERVAL = 480


def load_env(env_path: str = ".env"):
    """
    Load environment variables from a .env file.

    Lookup order:
    1) Provided absolute path.
    2) Current working directory.
    3) Repository root (resolved from this file location).
    """

    def _load_file(path: Path):
        with path.open() as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, val = line.split("=", 1)
                os.environ.setdefault(key.strip(), val.strip())

    try:
        candidate_paths = []
        env_candidate = Path(env_path)

        if env_candidate.is_absolute():
            candidate_paths.append(env_candidate)
        else:
            candidate_paths.append(Path.cwd() / env_candidate)
            repo_root = Path(__file__).resolve().parents[2]
            candidate_paths.append(repo_root / env_candidate)

        seen = set()
        for path in candidate_paths:
            resolved = str(path.resolve())
            if resolved in seen:
                continue
            seen.add(resolved)
            if path.exists():
                _load_file(path)
                return
    except Exception as e:
        bt.logging.warning(f"Failed to load {env_path}: {e}")


def _get_env_int(name: str, default: int) -> int:
    """Read int env var safely with fallback."""
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return int(default)
    try:
        return int(raw)
    except ValueError:
        bt.logging.warning(f"Invalid {name}='{raw}', using default {default}")
        return int(default)


def _get_env_float(name: str, default: float) -> float:
    """Read float env var safely with fallback."""
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return float(default)
    try:
        return float(raw)
    except ValueError:
        bt.logging.warning(f"Invalid {name}='{raw}', using default {default}")
        return float(default)


def _get_env_str(name: str, default: str) -> str:
    """Read string env var safely with fallback."""
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip() or default


def _get_env_bool(name: str, default: bool) -> bool:
    """Read bool env var safely with fallback."""
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return bool(default)

    normalized = raw.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False

    bt.logging.warning(f"Invalid {name}='{raw}', using default {default}")
    return bool(default)


def check_config(cls, config: "bt.Config"):
    r"""Checks/validates the config namespace object."""
    bt.logging.check_config(config)

    full_path = os.path.expanduser(
        "{}/{}/{}/netuid{}/{}".format(
            config.logging.logging_dir,
            config.wallet.name,
            config.wallet.hotkey,
            config.netuid,
            config.neuron.name,
        )
    )
    print("full path:", full_path)
    config.neuron.full_path = os.path.expanduser(full_path)
    if not os.path.exists(config.neuron.full_path):
        os.makedirs(config.neuron.full_path, exist_ok=True)

    if not config.neuron.dont_save_events:
        # Add custom event logger for the events.
        events_logger = setup_events_logger(
            config.neuron.full_path, config.neuron.events_retention_size
        )
        bt.logging.register_primary_logger(events_logger.name)


def add_args(cls, parser):
    """
    Adds relevant arguments to the parser for operation.
    """

    parser.add_argument("--netuid", type=int, help="Subnet netuid", default=97)

    parser.add_argument(
        "--neuron.epoch_length",
        type=int,
        help="The default epoch length (how often we set weights, measured in 12 second blocks).",
        default=360,
    )

    parser.add_argument(
        "--neuron.events_retention_size",
        type=str,
        help="Events retention size.",
        default=2 * 1024 * 1024 * 1024,  # 2 GB
    )

    parser.add_argument(
        "--neuron.dont_save_events",
        action="store_true",
        help="If set, we dont save events to a log file.",
        default=False,
    )

    parser.add_argument(
        "--neuron.disable_set_weights",
        action="store_true",
        help="Disables setting weights.",
        default=False,
    )

    parser.add_argument(
        "--wandb.offline",
        action="store_true",
        help="Runs wandb in offline mode.",
        default=False,
    )

    parser.add_argument(
        "--wandb.notes",
        type=str,
        help="Notes to add to the wandb run.",
        default="",
    )


def add_validator_args(cls, parser):
    """Add validator specific arguments to the parser."""

    parser.add_argument(
        "--neuron.name",
        type=str,
        help="Trials for this neuron go in neuron.root / (wallet_cold - wallet_hot) / neuron.name.",
        default="validator",
    )

    parser.add_argument(
        "--neuron.timeout",
        type=float,
        help="The timeout for each forward call in seconds.",
        default=10,
    )

    parser.add_argument(
        "--gateway.url",
        type=str,
        help="The gateway API URL.",
        default=DEFAULT_GATEWAY_URL,
    )

    parser.add_argument(
        "--validator.api_key",
        type=str,
        help="The validator API key for gateway authentication.",
        default="",
    )

    parser.add_argument(
        "--validator.max_workers",
        type=int,
        help="Maximum number of concurrent workers for node verification.",
        default=DEFAULT_VALIDATOR_MAX_WORKERS,
    )

    parser.add_argument(
        "--validator.ema_alpha",
        type=float,
        help="EMA smoothing factor (0-1). Higher = faster adaptation, lower = more stable.",
        default=DEFAULT_VALIDATOR_EMA_ALPHA,
    )

    parser.add_argument(
        "--validator.verification_interval",
        type=int,
        help="Interval between verification cycles in seconds.",
        default=DEFAULT_VALIDATOR_VERIFICATION_INTERVAL,
    )

    parser.add_argument(
        "--validator.reference_rpc_url",
        type=str,
        help="Validator-controlled archive RPC endpoint for reference block truth data.",
        default="",
    )


def config(cls):
    """
    Returns the configuration object specific to this validator after adding relevant arguments.
    """
    load_env()
    parser = argparse.ArgumentParser()
    bt.Wallet.add_args(parser)
    bt.Subtensor.add_args(parser)
    bt.logging.add_args(parser)
    bt.Axon.add_args(parser)
    cls.add_args(parser)

    cfg = bt.Config(parser)

    # Enable visible runtime logs by default. CLI flags are preserved unless env overrides are set.
    cfg.logging.info = _get_env_bool("LOGGING_INFO", True)
    cfg.logging.debug = _get_env_bool("LOGGING_DEBUG", bool(getattr(cfg.logging, "debug", False)))
    cfg.logging.trace = _get_env_bool("LOGGING_TRACE", bool(getattr(cfg.logging, "trace", False)))

    # Override settings from environment variables if present
    cfg.wallet.name = os.getenv("WALLET_NAME", cfg.wallet.name)
    cfg.wallet.hotkey = os.getenv("WALLET_HOTKEY", cfg.wallet.hotkey)
    cfg.subtensor.network = os.getenv("SUBTENSOR_NETWORK", cfg.subtensor.network)

    # Gateway and validator settings
    if cfg.gateway is None:
        cfg.gateway = bt.Config()
    cfg.gateway.url = _get_env_str("GATEWAY_URL", DEFAULT_GATEWAY_URL)

    if cfg.validator is None:
        cfg.validator = bt.Config()
    cfg.validator.api_key = _get_env_str("VALIDATOR_API_KEY", "")
    cfg.validator.max_workers = _get_env_int("VALIDATOR_MAX_WORKERS", DEFAULT_VALIDATOR_MAX_WORKERS)
    cfg.validator.ema_alpha = _get_env_float("VALIDATOR_EMA_ALPHA", DEFAULT_VALIDATOR_EMA_ALPHA)
    cfg.validator.verification_interval = _get_env_int(
        "VALIDATOR_VERIFICATION_INTERVAL",
        DEFAULT_VALIDATOR_VERIFICATION_INTERVAL,
    )
    reference_rpc_url = (
        os.getenv("REFERENCE_RPC_URL")
        or os.getenv("VALIDATOR_REFERENCE_RPC_URL")
        or ""
    )
    cfg.validator.reference_rpc_url = reference_rpc_url.strip()

    return cfg
