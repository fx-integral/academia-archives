"""Pool client - fetches pool data from verifier API with caching."""

from __future__ import annotations

from functools import lru_cache
from typing import Any

from .verifier import VerifierError, fetch_pools


# Cache pool data for 5 minutes (300 seconds)
# Using a module-level cache that can be cleared if needed
_pools_cache: dict[str, Any] | None = None
_cache_timestamp: float = 0
_CACHE_TTL_SECONDS = 300


def _get_cached_pools() -> list[dict[str, Any]]:
    """Get pools with caching (5 minute TTL)."""
    global _pools_cache, _cache_timestamp
    import time
    
    now = time.time()
    if _pools_cache is None or (now - _cache_timestamp) > _CACHE_TTL_SECONDS:
        try:
            _pools_cache = fetch_pools()
            _cache_timestamp = now
        except VerifierError:
            # If fetch fails and we have cached data, use it
            if _pools_cache is not None:
                return _pools_cache
            # Otherwise return empty list
            return []
    
    return _pools_cache or []


def clear_cache() -> None:
    """Clear the pools cache."""
    global _pools_cache, _cache_timestamp
    _pools_cache = None
    _cache_timestamp = 0


def list_pools() -> dict[str, str]:
    """List all available pools from verifier.
    
    Returns:
        Dictionary mapping pool names (e.g., "BTCUSD") to hex pool IDs
    """
    pools = _get_cached_pools()
    result = {}
    for pool in pools:
        name = pool.get("name", "")
        # Verifier returns camelCase keys
        pool_id = pool.get("poolId", "")
        if name and pool_id:
            # Normalize name: "BTC/USD" -> "BTCUSD"
            normalized_name = name.replace("/", "").upper()
            result[normalized_name] = pool_id.lower()
    return result


def pool_name_to_id(pool_name: str) -> str:
    """Convert a readable pool name to hex pool ID.
    
    Args:
        pool_name: Readable name (e.g., "BTCUSD", "BTC/USD")
        
    Returns:
        Hex pool ID (bytes32 format)
    """
    normalized = pool_name.replace("/", "").upper()
    pools = list_pools()
    
    if normalized in pools:
        return pools[normalized]
    
    # Fallback: encode the name as hex (for unknown pools)
    name_bytes = pool_name.encode("utf-8")
    if len(name_bytes) > 32:
        raise ValueError(f"Pool name too long: {pool_name} (max 32 bytes)")
    padded = name_bytes.rjust(32, b"\x00")
    return "0x" + padded.hex()


def pool_id_to_name(pool_id: str) -> str | None:
    """Convert a hex pool ID to readable name if available.
    
    Args:
        pool_id: Hex pool ID (bytes32 format)
        
    Returns:
        Readable name if found, None otherwise
    """
    pools = _get_cached_pools()
    pool_id_lower = pool_id.lower()
    
    for pool in pools:
        # Verifier returns camelCase keys
        if pool.get("poolId", "").lower() == pool_id_lower:
            name = pool.get("name", "")
            # Return normalized name without slash
            return name.replace("/", "").upper() if name else None
    
    return None


def format_pool_id(pool_id: str) -> str:
    """Format a pool ID for display (shows readable name if available).
    
    Args:
        pool_id: Hex pool ID
        
    Returns:
        Formatted string: "BTCUSD (0x...)" or just "0x..." if no name found
    """
    name = pool_id_to_name(pool_id)
    if name:
        return f"{name} ({pool_id})"
    return pool_id


def pool_id_to_vault_address(pool_id: str) -> str | None:
    """Get vault address for a given pool ID.
    
    Args:
        pool_id: Pool ID in hex format (bytes32)
        
    Returns:
        Vault address if found, None otherwise
    """
    pools = _get_cached_pools()
    pool_id_lower = pool_id.lower()
    
    for pool in pools:
        # Verifier returns camelCase keys
        if pool.get("poolId", "").lower() == pool_id_lower:
            return pool.get("vaultAddress")
    
    return None


def vault_address_to_pool_id(vault_address: str) -> str | None:
    """Get pool ID for a given vault address.
    
    Args:
        vault_address: Vault contract address
        
    Returns:
        Pool ID if found, None otherwise
    """
    pools = _get_cached_pools()
    vault_lower = vault_address.lower()
    
    for pool in pools:
        # Verifier returns camelCase keys
        if pool.get("vaultAddress", "").lower() == vault_lower:
            return pool.get("poolId", "").lower()
    
    return None


def pool_id_to_chain_id(pool_id: str) -> int | None:
    """Get chain ID for a given pool ID.
    
    Args:
        pool_id: Pool ID in hex format (bytes32)
        
    Returns:
        Chain ID if found, None otherwise
    """
    pools = _get_cached_pools()
    pool_id_lower = pool_id.lower()
    
    for pool in pools:
        # Verifier returns camelCase keys
        if pool.get("poolId", "").lower() == pool_id_lower:
            return pool.get("chainId")
    
    return None


def vault_address_to_chain_id(vault_address: str) -> int | None:
    """Get chain ID for a given vault address.
    
    Args:
        vault_address: Vault contract address
        
    Returns:
        Chain ID if found, None otherwise
    """
    pools = _get_cached_pools()
    vault_lower = vault_address.lower()
    
    for pool in pools:
        # Verifier returns camelCase keys
        if pool.get("vaultAddress", "").lower() == vault_lower:
            return pool.get("chainId")
    
    return None


__all__ = [
    "clear_cache",
    "list_pools",
    "pool_name_to_id",
    "pool_id_to_name",
    "format_pool_id",
    "pool_id_to_vault_address",
    "vault_address_to_pool_id",
    "pool_id_to_chain_id",
    "vault_address_to_chain_id",
]
