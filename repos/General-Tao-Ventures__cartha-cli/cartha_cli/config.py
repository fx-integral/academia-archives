"""Runtime configuration for the Cartha CLI."""

from __future__ import annotations

import os
from functools import lru_cache
from typing import Any

from pydantic import Field
from pydantic_settings import BaseSettings


# Network to verifier URL mapping
NETWORK_VERIFIER_MAP = {
    "test": "https://cartha-verifier-826542474079.us-central1.run.app",
    "finney": "https://api.cartha.finance",
}


def get_verifier_url_for_network(network: str) -> str:
    """Get the appropriate verifier URL for a given network.
    
    Args:
        network: Network name ("test" or "finney")
        
    Returns:
        Verifier URL for the network
    """
    # Check if user set CARTHA_VERIFIER_URL explicitly
    env_url = os.getenv("CARTHA_VERIFIER_URL")
    if env_url:
        return env_url
    
    # Auto-map based on network
    mapped_url = NETWORK_VERIFIER_MAP.get(network)
    if mapped_url:
        return mapped_url
    
    # Default fallback to mainnet
    return "https://api.cartha.finance"


class Settings(BaseSettings):
    verifier_url: str = Field(
        "https://api.cartha.finance", alias="CARTHA_VERIFIER_URL"
    )
    network: str = Field("finney", alias="CARTHA_NETWORK")
    netuid: int = Field(35, alias="CARTHA_NETUID")
    evm_private_key: str | None = Field(None, alias="CARTHA_EVM_PK")
    # Retry configuration
    retry_max_attempts: int = Field(3, alias="CARTHA_RETRY_MAX_ATTEMPTS")
    retry_backoff_factor: float = Field(1.5, alias="CARTHA_RETRY_BACKOFF_FACTOR")
    # Note: retry_on_status cannot be set via env var easily (would need JSON parsing)
    # For now, it's hardcoded but can be overridden programmatically
    retry_on_status: list[int] = Field(default_factory=lambda: [500, 502, 503, 504])
    # Frontend lock UI URL
    lock_ui_url: str = Field(
        "https://liquidity.0xmarkets.io", alias="CARTHA_LOCK_UI_URL"
    )

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "env_nested_delimiter": "__",
    }


@lru_cache(maxsize=1)
def get_settings(**overrides: Any) -> Settings:
    return Settings(**overrides)


settings = get_settings()

__all__ = ["settings", "Settings", "get_settings"]
