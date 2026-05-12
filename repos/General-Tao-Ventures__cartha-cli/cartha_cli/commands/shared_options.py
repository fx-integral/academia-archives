"""Shared option definitions for consistent CLI interface.

This module provides reusable typer.Option definitions with comprehensive aliases
to ensure consistency across all CLI commands.
"""

import typer
from ..config import settings


def wallet_name_option(required: bool = True):
    """Coldkey wallet name option with consistent aliases.
    
    Aliases: --wallet-name, --wallet.name, --coldkey, -w
    """
    if required:
        return typer.Option(
            ...,
            "--wallet-name",
            "--wallet.name",
            "--coldkey",
            "-w",
            prompt="Coldkey wallet name",
            help="Coldkey wallet name (aliases: --wallet-name, --wallet.name, --coldkey, -w)",
            show_default=False,
        )
    else:
        return typer.Option(
            None,
            "--wallet-name",
            "--wallet.name",
            "--coldkey",
            "-w",
            help="Coldkey wallet name (aliases: --wallet-name, --wallet.name, --coldkey, -w)",
            show_default=False,
        )


def wallet_hotkey_option(required: bool = True):
    """Hotkey name option with consistent aliases.
    
    Aliases: --wallet-hotkey, --wallet.hotkey, --hotkey, -wh
    """
    if required:
        return typer.Option(
            ...,
            "--wallet-hotkey",
            "--wallet.hotkey",
            "--hotkey",
            "-wh",
            prompt="Hotkey name",
            help="Hotkey name (aliases: --wallet-hotkey, --wallet.hotkey, --hotkey, -wh)",
            show_default=False,
        )
    else:
        return typer.Option(
            None,
            "--wallet-hotkey",
            "--wallet.hotkey",
            "--hotkey",
            "-wh",
            help="Hotkey name (aliases: --wallet-hotkey, --wallet.hotkey, --hotkey, -wh)",
            show_default=False,
        )


def pool_id_option():
    """Pool ID option with aliases.
    
    Aliases: --pool-id, --pool, --poolid, -p
    """
    return typer.Option(
        None,
        "--pool-id",
        "--pool",
        "--poolid",
        "-p",
        help="Pool name (e.g., BTCUSD, ETHUSD) or hex ID (0x...) (aliases: --pool-id, --pool, --poolid, -p)",
        show_default=False,
    )


def chain_id_option():
    """Chain ID option with aliases.
    
    Aliases: --chain-id, --chain, --chainid
    """
    return typer.Option(
        None,
        "--chain-id",
        "--chain",
        "--chainid",
        help="EVM chain ID (auto-detected from pool if not provided) (aliases: --chain-id, --chain, --chainid)",
        show_default=False,
    )


def vault_address_option():
    """Vault contract address option with aliases.
    
    Aliases: --vault-address, --vault
    """
    return typer.Option(
        None,
        "--vault-address",
        "--vault",
        help="Vault contract address (auto-detected from pool if not provided) (aliases: --vault-address, --vault)",
        show_default=False,
    )


def owner_evm_option():
    """Owner EVM address option with aliases.
    
    Aliases: --owner-evm, --owner, --evm-address, --evm, -e
    """
    return typer.Option(
        None,
        "--owner-evm",
        "--owner",
        "--evm-address",
        "--evm",
        "-e",
        help="EVM address that will own the lock position (aliases: --owner-evm, --owner, --evm-address, --evm, -e)",
        show_default=False,
    )


def amount_option():
    """Amount option.
    
    Aliases: --amount, -a
    """
    return typer.Option(
        None,
        "--amount",
        "-a",
        help="Lock amount in USDC (e.g., 250.5). Auto-detects if normalized USDC or base units (>1e9) (alias: -a)",
        show_default=False,
    )


def lock_days_option():
    """Lock days option with aliases.
    
    Aliases: --lock-days, --days, -d
    """
    return typer.Option(
        None,
        "--lock-days",
        "--days",
        "-d",
        help="Lock duration in days (e.g., 365) (aliases: --lock-days, --days, -d)",
        show_default=False,
    )


def network_option():
    """Network option with netuid auto-mapping.
    
    Aliases: --network, -n
    Maps: test → netuid 78, finney → netuid 35
    """
    return typer.Option(
        settings.network,
        "--network",
        "-n",
        help="Bittensor network (test or finney). Auto-maps to correct netuid (test=78, finney=35)"
    )


def netuid_option():
    """Netuid option."""
    return typer.Option(
        settings.netuid,
        "--netuid",
        help="Subnet netuid"
    )


def slot_option():
    """Slot UID option with aliases.
    
    Aliases: --slot, --uid, -u
    """
    return typer.Option(
        None,
        "--slot",
        "--uid",
        "-u",
        help="Subnet UID assigned to the miner (aliases: --slot, --uid, -u). If not provided, will auto-fetch or prompt.",
        show_default=False,
    )


def auto_fetch_uid_option():
    """Auto-fetch UID option."""
    return typer.Option(
        True,
        "--auto-fetch-uid/--no-auto-fetch-uid",
        help="Automatically fetch UID from Bittensor network (default: enabled).",
        show_default=False,
    )


def tx_hash_option():
    """Transaction hash option with aliases.
    
    Aliases: --tx-hash, --tx, --transaction
    """
    return typer.Option(
        None,
        "--tx-hash",
        "--tx",
        "--transaction",
        help="Transaction hash (aliases: --tx-hash, --tx, --transaction)",
    )


def json_output_option():
    """JSON output option."""
    return typer.Option(
        False,
        "--json",
        help="Emit responses as JSON."
    )


def refresh_option():
    """Refresh option for triggering manual processing."""
    return typer.Option(
        False,
        "--refresh",
        help="If position not found, manually trigger verifier to process a lock transaction.",
    )
