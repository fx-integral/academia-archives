# The MIT License (MIT)
# Copyright © 2026 TAO Colosseum

# Constants for TAO Colosseum validator

import os

# Load .env from current directory (or parent) so env vars override defaults below
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# Subnet version — change this single value to update version everywhere
# (setup.py, __init__.py, API, etc.)
VERSION = "2.0.0"

# RPC and contract: use env vars from .env if set, else these defaults
# (see .env.example for TAO_COLOSSEUM_CONTRACT_ADDRESS, BITTENSOR_EVM_RPC, BITTENSOR_EVM_CHAIN_ID)
_DEFAULT_CONTRACT = "0x2866c1f38629E3391614E54d1b63A7D0d3Ec2cDB"
_DEFAULT_RPC = "https://archive.chain.opentensor.ai"
_DEFAULT_CHAIN_ID = 964

def _env(key: str, default: str) -> str:
    v = os.environ.get(key, default)
    return (v or default).strip().strip('"\'') or default


def _env_int(key: str, default: int) -> int:
    v = (os.environ.get(key) or "").strip()
    if not v:
        return default
    try:
        return int(v)
    except ValueError:
        return default


TAO_COLOSSEUM_CONTRACT_ADDRESS = _env("TAO_COLOSSEUM_CONTRACT_ADDRESS", _DEFAULT_CONTRACT)
BITTENSOR_EVM_RPC = _env("BITTENSOR_EVM_RPC", _DEFAULT_RPC)
BITTENSOR_EVM_CHAIN_ID = _env_int("BITTENSOR_EVM_CHAIN_ID", _DEFAULT_CHAIN_ID)

# Time decay weights for 7 days (index 0 = today, index 6 = 6 days ago)
# Most recent activity gets highest weight
TIME_DECAY_WEIGHTS = [1.0, 0.85, 0.70, 0.55, 0.40, 0.25, 0.10]

# Volume check interval in seconds (5 minutes)
VOLUME_CHECK_INTERVAL = 300

# Weight commit interval in blocks (360 blocks = ~72 minutes)
WEIGHT_COMMIT_INTERVAL = 360

# Blocks per day (assuming 12 second blocks)
BLOCKS_PER_DAY = 7200

# Database path
DB_PATH = "validator_data.db"

# API settings
API_HOST = "0.0.0.0"
API_PORT = 8000
