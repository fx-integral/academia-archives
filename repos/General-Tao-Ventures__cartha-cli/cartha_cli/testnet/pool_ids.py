"""Helper functions for generating and displaying human-readable pool IDs.

Pool IDs are bytes32 (32 bytes = 64 hex chars), so we can encode readable text
in hex format. This module provides helpers to convert between readable names
and hex pool IDs.
"""

from __future__ import annotations

# Predefined pool mappings (readable name -> hex pool ID)
# Base Sepolia testnet pool IDs from vault contracts (keccak256 hashes)
# Pool IDs are bytes32 (keccak256 hashes: 32 bytes = 64 hex chars + 0x prefix = 66 chars)
POOL_MAPPINGS: dict[str, str] = {
    "BTCUSD": "0xee62665949c883f9e0f6f002eac32e00bd59dfe6c34e92a91c37d6a8322d6489",  # BTC/USD (keccak256("BTC/USD"))
    "ETHUSD": "0x0b43555ace6b39aae1b894097d0a9fc17f504c62fea598fa206cc6f5088e6e45",  # ETH/USD (keccak256("ETH/USD"))
    "EURUSD": "0xa9226449042e36bf6865099eec57482aa55e3ad026c315a0e4a692b776c318ca",  # EUR/USD (keccak256("EUR/USD"))
}

# Reverse mapping (hex -> readable name)
POOL_NAMES: dict[str, str] = {v.lower(): k for k, v in POOL_MAPPINGS.items()}

# Pool ID to Vault Address mapping (Base Sepolia testnet)
# Each pool ID has its own dedicated vault address
VAULT_ADDRESSES: dict[str, str] = {
    "BTCUSD": "0x471D86764B7F99b894ee38FcD3cEFF6EAB321b69",  # BTC/USD Vault
    "ETHUSD": "0xdB74B44957A71c95406C316f8d3c5571FA588248",  # ETH/USD Vault
    "EURUSD": "0x3C4dAfAC827140B8a031d994b7e06A25B9f27BAD",  # EUR/USD Vault
}

# Pool ID (hex) to Vault Address mapping
POOL_ID_TO_VAULT: dict[str, str] = {
    POOL_MAPPINGS["BTCUSD"].lower(): VAULT_ADDRESSES["BTCUSD"],
    POOL_MAPPINGS["ETHUSD"].lower(): VAULT_ADDRESSES["ETHUSD"],
    POOL_MAPPINGS["EURUSD"].lower(): VAULT_ADDRESSES["EURUSD"],
}

# Vault Address to Chain ID mapping (Base Sepolia testnet)
# All testnet vaults are on Base Sepolia (chain ID 84532)
VAULT_TO_CHAIN_ID: dict[str, int] = {
    VAULT_ADDRESSES["BTCUSD"].lower(): 84532,  # Base Sepolia
    VAULT_ADDRESSES["ETHUSD"].lower(): 84532,  # Base Sepolia
    VAULT_ADDRESSES["EURUSD"].lower(): 84532,  # Base Sepolia
}

# Pool ID (hex) to Chain ID mapping
POOL_ID_TO_CHAIN_ID: dict[str, int] = {
    POOL_MAPPINGS["BTCUSD"].lower(): 84532,  # Base Sepolia
    POOL_MAPPINGS["ETHUSD"].lower(): 84532,  # Base Sepolia
    POOL_MAPPINGS["EURUSD"].lower(): 84532,  # Base Sepolia
}


def pool_id_to_vault_address(pool_id: str) -> str | None:
    """Get vault address for a given pool ID.
    
    Args:
        pool_id: Pool ID in hex format (bytes32)
        
    Returns:
        Vault address if found, None otherwise
    """
    pool_id_lower = pool_id.lower().strip()
    if not pool_id_lower.startswith("0x"):
        pool_id_lower = "0x" + pool_id_lower
    
    return POOL_ID_TO_VAULT.get(pool_id_lower)


def vault_address_to_pool_id(vault_address: str) -> str | None:
    """Get pool ID for a given vault address.
    
    Args:
        vault_address: Vault contract address
        
    Returns:
        Pool ID if found, None otherwise
    """
    vault_lower = vault_address.lower().strip()
    if not vault_lower.startswith("0x"):
        vault_lower = "0x" + vault_lower
    
    # Reverse lookup
    for pool_id, vault in POOL_ID_TO_VAULT.items():
        if vault.lower() == vault_lower:
            return pool_id
    return None


def pool_id_to_chain_id(pool_id: str) -> int | None:
    """Get chain ID for a given pool ID.
    
    Args:
        pool_id: Pool ID in hex format (bytes32)
        
    Returns:
        Chain ID if found, None otherwise
    """
    pool_id_lower = pool_id.lower().strip()
    if not pool_id_lower.startswith("0x"):
        pool_id_lower = "0x" + pool_id_lower
    
    return POOL_ID_TO_CHAIN_ID.get(pool_id_lower)


def vault_address_to_chain_id(vault_address: str) -> int | None:
    """Get chain ID for a given vault address.
    
    Args:
        vault_address: Vault contract address
        
    Returns:
        Chain ID if found, None otherwise
    """
    vault_lower = vault_address.lower().strip()
    if not vault_lower.startswith("0x"):
        vault_lower = "0x" + vault_lower
    
    return VAULT_TO_CHAIN_ID.get(vault_lower)


def pool_name_to_id(pool_name: str) -> str:
    """Convert a readable pool name to hex pool ID.
    
    Args:
        pool_name: Readable name (e.g., "USDEUR", "XAUUSD")
        
    Returns:
        Hex pool ID (bytes32 format)
        
    Examples:
        >>> pool_name_to_id("USDEUR")
        '0x0000000000000000000000000000000000000000000000000000000000555344455552'
    """
    pool_name_upper = pool_name.upper()
    if pool_name_upper in POOL_MAPPINGS:
        return POOL_MAPPINGS[pool_name_upper]
    
    # If not in predefined mappings, encode the name as hex
    # Pad to 32 bytes (64 hex chars), right-padded (data at end, zeros at beginning)
    name_bytes = pool_name.encode("utf-8")
    if len(name_bytes) > 32:
        raise ValueError(f"Pool name too long: {pool_name} (max 32 bytes)")
    
    # Right-pad with zeros to 32 bytes (data at end, zeros at beginning)
    padded = name_bytes.rjust(32, b"\x00")
    hex_id = "0x" + padded.hex()
    # Validate length
    if len(hex_id) != 66:  # 0x + 64 hex chars
        raise ValueError(f"Generated pool_id has incorrect length: {len(hex_id)} (expected 66)")
    return hex_id


def pool_id_to_name(pool_id: str) -> str | None:
    """Convert a hex pool ID to readable name if available.
    
    Args:
        pool_id: Hex pool ID (bytes32 format)
        
    Returns:
        Readable name if found, None otherwise
        
    Examples:
        >>> pool_id_to_name("0x0000000000000000000000000000000000000000000000000000000000555344455552")
        'USDEUR'
    """
    pool_id_lower = pool_id.lower()
    if pool_id_lower in POOL_NAMES:
        return POOL_NAMES[pool_id_lower]
    
    # Try to decode from hex
    try:
        # Remove 0x prefix
        hex_str = pool_id_lower.removeprefix("0x")
        # Convert to bytes
        pool_bytes = bytes.fromhex(hex_str)
        # Try to decode as UTF-8 (remove trailing zeros)
        name = pool_bytes.rstrip(b"\x00").decode("utf-8", errors="ignore")
        if name and name.isprintable():
            return name
    except Exception:
        pass
    
    return None


def format_pool_id(pool_id: str) -> str:
    """Format a pool ID for display (shows readable name if available).
    
    Args:
        pool_id: Hex pool ID
        
    Returns:
        Formatted string: "USDEUR (0x...)" or just "0x..." if no name found
    """
    name = pool_id_to_name(pool_id)
    if name:
        return f"{name} ({pool_id})"
    return pool_id


def list_pools() -> dict[str, str]:
    """List all predefined pools.
    
    Returns:
        Dictionary mapping readable names to hex pool IDs
    """
    return POOL_MAPPINGS.copy()

