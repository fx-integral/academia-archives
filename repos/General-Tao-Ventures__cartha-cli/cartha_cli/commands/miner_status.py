"""Miner status command - shows miner info without password."""

from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta
from typing import Any

import bittensor as bt
import typer
from rich.json import JSON
from rich.panel import Panel
from rich.status import Status
from rich.table import Table

from ..config import settings
from ..display import display_clock_and_countdown
from ..pair import get_uid_from_hotkey
from ..utils import format_timestamp, format_timestamp_multiline, format_evm_address, normalize_hex
from ..verifier import VerifierError, fetch_miner_status, get_lock_status, process_lock_transaction
from ..wallet import load_wallet
from .common import (
    console,
    handle_unexpected_exception,
    handle_wallet_exception,
)
from .shared_options import (
    wallet_name_option,
    wallet_hotkey_option,
    slot_option,
    auto_fetch_uid_option,
    network_option,
    netuid_option,
    json_output_option,
    tx_hash_option,
    refresh_option,
)

# Minimum total portfolio required to receive score/rewards (100k USDC)
# Miners below this threshold will receive score=0 and no rewards
# Reference: cartha-validator config.py min_total_assets_usdc
MIN_PORTFOLIO_THRESHOLD_USDC = 100_000.0

# Note: CLI does NOT convert pool_id to pool_name - verifier handles that
# CLI just displays the pool_name from verifier response (capitalized)


def miner_status(
    wallet_name: str = wallet_name_option(required=True),
    wallet_hotkey: str = wallet_hotkey_option(required=True),
    slot: int | None = slot_option(),
    auto_fetch_uid: bool = auto_fetch_uid_option(),
    network: str = network_option(),
    netuid: int = netuid_option(),
    json_output: bool = json_output_option(),
    refresh: bool = refresh_option(),
    tx_hash: str | None = tx_hash_option(),
) -> None:
    """Show miner status and pool information (no authentication required).

    USAGE:
    ------
    Interactive mode: 'cartha miner status' (will prompt for wallet)
    With arguments: 'cartha miner status -w cold -wh hot'
    
    ALIASES:
    --------
    Wallet: --wallet-name, --coldkey, -w  |  --wallet-hotkey, --hotkey, -wh
    Slot: --slot, --uid, -u  |  Network: --network, -n
    TX: --tx-hash, --tx, --transaction (for --refresh)
    
    FEATURES:
    ---------
    - Shows all your lock positions across pools and EVM addresses
    - No password required (public endpoint)
    - Auto-fetches your UID from Bittensor network
    - Use --refresh to manually trigger lock processing (if verifier hasn't detected it yet)
    - Displays expiration warnings for positions expiring soon
    
    Use 'cartha miner password' to view your password (requires authentication).
    """
    try:
        # Auto-map netuid and verifier URL based on network
        if network == "test":
            netuid = 78
        elif network == "finney":
            netuid = 35
        # Note: netuid parameter is kept for backwards compatibility / explicit override
        
        from ..config import get_verifier_url_for_network
        expected_verifier_url = get_verifier_url_for_network(network)
        if settings.verifier_url != expected_verifier_url:
            settings.verifier_url = expected_verifier_url
        
        wallet = load_wallet(wallet_name, wallet_hotkey, None)
        hotkey = wallet.hotkey.ss58_address

        # Fetch UID automatically by default, prompt if disabled
        if slot is None:
            if auto_fetch_uid:
                try:
                    with console.status(
                        "[bold cyan]Checking miner registration status...[/]",
                        spinner="dots",
                    ):
                        slot = get_uid_from_hotkey(
                            network=network, netuid=netuid, hotkey=hotkey
                        )
                except Exception as exc:
                    # Exit spinner context before prompting
                    console.print(
                        "[bold red]Failed to fetch UID automatically[/]: This may be due to Bittensor network issues."
                    )
                    console.print("[yellow]Falling back to manual input...[/]")
                    try:
                        slot_input = typer.prompt("Enter your slot UID", type=int)
                        slot = slot_input
                    except (ValueError, KeyboardInterrupt):
                        console.print("[bold red]Invalid UID or cancelled.[/]")
                        raise typer.Exit(code=1) from exc
                
                # Check if slot is None after fetching (outside spinner context)
                if slot is None:
                    console.print(
                        "[bold yellow]Hotkey is not registered or has been deregistered[/] "
                        f"on netuid {netuid} ({network} network)."
                    )
                    console.print(
                        "[yellow]You do not belong to any UID at the moment.[/] "
                        "Please register your hotkey first using 'cartha miner register'."
                    )
                    raise typer.Exit(code=0)
            else:
                console.print(
                    "[bold cyan]UID not provided.[/] "
                    "[yellow]Auto-fetch disabled. Enter UID manually.[/]"
                )
                try:
                    slot_input = typer.prompt(
                        "Enter your slot UID (from 'cartha miner register' output)",
                        type=int,
                    )
                    slot = slot_input
                except (ValueError, KeyboardInterrupt):
                    console.print("[bold red]Invalid UID or cancelled.[/]")
                    raise typer.Exit(code=1)

        slot_id = str(slot)

        # Fetch status without authentication (public endpoint)
        with console.status(
            "[bold cyan]Fetching miner status from Cartha verifier...[/]",
            spinner="dots",
        ):
            status = fetch_miner_status(
                hotkey=hotkey,
                slot=slot_id,
            )
    except bt.KeyFileError as exc:
        handle_wallet_exception(
            wallet_name=wallet_name, wallet_hotkey=wallet_hotkey, exc=exc
        )
    except typer.Exit:
        raise
    except VerifierError as exc:
        error_msg = str(exc)
        status_code = getattr(exc, "status_code", None)
        
        # Handle 404 Not Found - endpoint not deployed yet
        if status_code == 404 or "not found" in error_msg.lower():
            console.print(
                "[bold yellow]⚠ Endpoint not found[/]\n"
                "[yellow]The verifier service needs to be redeployed with the new endpoint.[/]\n"
                "[dim]This endpoint requires verifier version with /v1/miner/status support.[/]\n"
                "[dim]Please contact the verifier administrator or wait for deployment.[/]"
            )
            raise typer.Exit(code=1) from exc
        
        if "timed out" in error_msg.lower() or "timeout" in error_msg.lower():
            console.print(f"[bold red]Request timed out[/]")
            console.print(f"[yellow]{error_msg}[/]")
        else:
            console.print(f"[bold red]Verifier request failed[/]: {exc}")
        raise typer.Exit(code=1) from exc
    except Exception as exc:
        error_msg = str(exc)
        error_type = type(exc).__name__

        is_timeout = (
            "timed out" in error_msg.lower()
            or "timeout" in error_msg.lower()
            or error_type == "Timeout"
            or (
                hasattr(exc, "__cause__")
                and exc.__cause__ is not None
                and (
                    "timeout" in str(exc.__cause__).lower()
                    or "Timeout" in type(exc.__cause__).__name__
                )
            )
        )

        if is_timeout:
            console.print(f"[bold red]Request timed out[/]")
            console.print(
                f"[yellow]CLI failed to reach Cartha verifier\n"
                f"Possible causes: Network latency or the verifier is receiving too many requests\n"
                f"Tip: Try again in a moment\n"
                f"Error details: {error_msg}[/]"
            )
            raise typer.Exit(code=1) from exc

        handle_unexpected_exception("Unable to fetch miner status", exc)

    # Handle --refresh flag: manually trigger verifier if position not found
    state = status.get("state", "").lower()
    if refresh and state not in ("verified", "active"):
        console.print()
        console.print("[yellow]Position not found or not verified yet.[/]")
        console.print("[dim]Using --refresh to manually trigger verifier processing...[/]\n")
        
        # Prompt for tx_hash if not provided
        tx_hash_normalized = None
        if tx_hash:
            tx_hash_normalized = normalize_hex(tx_hash)
            if len(tx_hash_normalized) != 66:
                console.print(
                    "[bold red]Error:[/] Transaction hash must be 66 characters (0x + 64 hex chars)"
                )
                raise typer.Exit(code=1)
        else:
            while True:
                tx_input = typer.prompt(
                    "Transaction hash of your lock transaction (0x...)",
                    show_default=False,
                )
                tx_hash_normalized = normalize_hex(tx_input)
                if len(tx_hash_normalized) == 66:
                    break
                console.print(
                    "[bold red]Error:[/] Transaction hash must be 66 characters (0x + 64 hex chars)"
                )
        
        try:
            # Step 1: Check if already verified (to avoid unnecessary on-chain polling)
            console.print(f"[dim]Checking transaction status: {tx_hash_normalized}[/]\n")
            with Status(
                "[bold cyan]Checking lock status...[/]",
                console=console,
                spinner="dots",
            ) as status_spinner:
                lock_status_result = get_lock_status(tx_hash=tx_hash_normalized)
            
            is_verified = lock_status_result.get("verified", False)
            
            if is_verified:
                console.print("[bold green]✓ Transaction is already verified![/]")
                console.print("[dim]No need to trigger manual processing.[/]\n")
            else:
                # Step 2: Only trigger manual processing if not verified
                message = lock_status_result.get("message", "")
                console.print(f"[yellow]Status:[/] {message}\n")
                console.print("[bold cyan]Triggering manual processing...[/]")
                
                with Status(
                    "[bold cyan]Processing transaction...[/]",
                    console=console,
                    spinner="dots",
                ) as process_spinner:
                    process_result = process_lock_transaction(tx_hash=tx_hash_normalized)
                
                if process_result.get("success"):
                    console.print("[bold green]✓ Processing triggered successfully![/]\n")
                else:
                    console.print("[yellow]Processing triggered but result unclear.[/]\n")
            
            # Step 3: Wait a moment for database to update
            console.print("[dim]Waiting for verifier to update...[/]")
            time.sleep(2)
            
            # Step 4: Re-fetch miner status
            console.print("[dim]Re-fetching miner status...[/]\n")
            with Status(
                "[bold cyan]Fetching updated status...[/]",
                console=console,
                spinner="dots",
            ):
                status = fetch_miner_status(
                    hotkey=hotkey,
                    slot=slot_id,
                )
            
            # Check if status improved
            new_state = status.get("state", "").lower()
            if new_state in ("verified", "active"):
                console.print("[bold green]✓ Position verified successfully![/]\n")
            else:
                console.print(
                    "[yellow]Position not yet verified.[/] "
                    "[dim]The verifier will continue processing automatically.[/]\n"
                )
        
        except VerifierError as refresh_exc:
            console.print(f"[bold red]Refresh failed:[/] {refresh_exc}")
            console.print(
                "[dim]Continuing to display current status...[/]\n"
            )
        except Exception as refresh_exc:
            console.print(f"[bold red]Error during refresh:[/] {refresh_exc}")
            console.print(
                "[dim]Continuing to display current status...[/]\n"
            )

    sanitized = dict(status)
    sanitized.setdefault("state", "unknown")
    sanitized["hotkey"] = hotkey
    sanitized["slot"] = slot_id
    # Explicitly remove password from display
    sanitized.pop("pwd", None)

    if json_output:
        # Add total portfolio and warning to JSON output
        # Handle None values by defaulting to 0.0
        total_verified_usdc = sanitized.get("verified_lock_amount_usdc") or 0.0
        total_active_usdc = sanitized.get("active_lock_amount_usdc") or 0.0
        total_portfolio_usdc = total_active_usdc if total_active_usdc > 0 else total_verified_usdc
        
        # Calculate from pools if API didn't provide totals
        if total_portfolio_usdc == 0:
            pools = sanitized.get("pools", [])
            if pools:
                total_portfolio_usdc = sum(pool.get("amount_usdc", 0) for pool in pools)
        
        sanitized["total_portfolio_usdc"] = total_portfolio_usdc
        sanitized["min_portfolio_threshold_usdc"] = MIN_PORTFOLIO_THRESHOLD_USDC
        sanitized["below_min_threshold"] = total_portfolio_usdc < MIN_PORTFOLIO_THRESHOLD_USDC
        
        console.print(JSON.from_data(sanitized))
        return

    # Display clock and countdown
    display_clock_and_countdown()

    # Display info about Cartha being the Liquidity Provider for 0xMarkets DEX
    console.print("[dim]Cartha is the Liquidity Provider for 0xMarkets DEX[/]")
    console.print()

    table = Table(title="Miner Status", show_header=False)
    table.add_row("Hotkey", hotkey)
    table.add_row("Slot UID", slot_id)
    table.add_row("State", sanitized["state"])

    # Show lock amounts for verified/active states
    state = sanitized.get("state", "").lower()
    if state in ("verified", "active"):
        # Show EVM addresses used - display all addresses
        evm_addresses = sanitized.get("miner_evm_addresses")
        if evm_addresses:
            if len(evm_addresses) == 1:
                table.add_row("EVM Address", evm_addresses[0])
            elif len(evm_addresses) <= 3:
                # Show up to 3 addresses with line breaks
                evm_display = "\n".join(evm_addresses)
                table.add_row("EVM Addresses", evm_display)
            else:
                # Show count for many addresses
                table.add_row("EVM Addresses", f"{len(evm_addresses)} addresses (see pool details below)")


    console.print(table)

    # Show detailed status information for verified/active pairs
    if state in ("verified", "active"):
        pools = sanitized.get("pools", [])

        # Display per-pool table (primary display for lock information)
        if pools:
            console.print()
            console.print("[bold cyan]━━━ Active Pools ━━━[/]")

            pool_table = Table(show_header=True, header_style="bold cyan", padding=(0, 1), row_styles=["", "dim"])
            pool_table.add_column("Pool Name", style="cyan", no_wrap=True)
            pool_table.add_column("Amount Locked", style="green", justify="right")
            pool_table.add_column("Pending Amount", style="yellow", justify="right")
            pool_table.add_column("Lock Days", justify="center")
            pool_table.add_column("Expires At", style="yellow")
            pool_table.add_column("Status", justify="center")
            pool_table.add_column("EVM Address", style="dim")

            for idx, pool in enumerate(pools):
                # Get pool name from verifier response (already converted by verifier)
                # Display capitalized version
                pool_name = pool.get("pool_name")
                if pool_name:
                    # Capitalize pool name for display
                    pool_display = pool_name.upper()
                else:
                    # Fallback: if verifier didn't provide name, show last 8 chars of pool_id
                    pool_id = pool.get("pool_id", "")
                    if pool_id:
                        pool_id_normalized = str(pool_id).lower().strip()
                        pool_display = f"Pool ({pool_id_normalized[-8:]})"
                    else:
                        pool_display = "Unknown"

                # Format amount locked
                amount_usdc = pool.get("amount_usdc", 0)
                amount_str = f"{amount_usdc:.2f}"

                # Format pending amount (top-up that will be active in next epoch)
                pending_amount_usdc = pool.get("pending_lock_amount_usdc")
                if pending_amount_usdc is not None and pending_amount_usdc > 0:
                    pending_str = f"{pending_amount_usdc:.2f} USDC"
                else:
                    pending_str = "[dim]-[/]"

                # Format lock days
                lock_days = pool.get("lock_days", 0)
                lock_days_str = str(lock_days)

                # Format expiration with days countdown
                pool_expires_at = pool.get("expires_at")
                expires_str = "N/A"
                days_left_str = ""
                if pool_expires_at:
                    try:
                        if isinstance(pool_expires_at, str):
                            exp_dt = datetime.fromisoformat(
                                pool_expires_at.replace("Z", "+00:00")
                            )
                        elif isinstance(pool_expires_at, datetime):
                            exp_dt = pool_expires_at
                        else:
                            exp_dt = None
                        if exp_dt:
                            # Ensure timezone-aware
                            if exp_dt.tzinfo is None:
                                exp_dt = exp_dt.replace(tzinfo=UTC)

                            # Format timestamp on multiple lines
                            expires_str = format_timestamp_multiline(exp_dt.timestamp())

                            # Calculate days left
                            now = datetime.now(UTC)
                            time_until_expiry = (exp_dt - now).total_seconds()
                            days_until_expiry = time_until_expiry / 86400

                            # Format days left with color coding (on separate line)
                            if days_until_expiry < 0:
                                days_left_str = "\n[bold red]⚠ EXPIRED[/]"
                            elif days_until_expiry <= 7:
                                days_left_str = (
                                    f"\n[bold red]⚠ {int(days_until_expiry)}d left[/]"
                                )
                            elif days_until_expiry <= 15:
                                days_left_str = (
                                    f"\n[bold yellow]⚠ {int(days_until_expiry)}d left[/]"
                                )
                            else:
                                days_left_str = f"\n({int(days_until_expiry)}d left)"
                    except Exception:
                        expires_str = str(pool_expires_at)

                # Format status - only Active and In Next Epoch (remove Verified)
                is_active = pool.get("is_active", False)
                pool_in_upcoming = pool.get("in_upcoming_epoch", False)

                status_parts = []
                if is_active:
                    status_parts.append("[green]Active[/]")
                if pool_in_upcoming:
                    status_parts.append("[bold green]In Next Epoch[/]")
                if not status_parts:
                    status_parts.append("[dim]None[/]")

                status_str = " / ".join(status_parts)

                # EVM address - format in standard crypto wallet display
                evm_addr = pool.get("evm_address", "")
                evm_display = format_evm_address(evm_addr)

                pool_table.add_row(
                    pool_display,
                    f"{amount_str} USDC",
                    pending_str,
                    lock_days_str,
                    expires_str + days_left_str,
                    status_str,
                    evm_display,
                )
                
                # Add spacing row between pools (except after the last one)
                if idx < len(pools) - 1:
                    pool_table.add_row(
                        "",  # Empty row for visual spacing
                        "",
                        "",
                        "",
                        "",
                        "",
                        "",
                    )

            console.print(pool_table)

        # Calculate and display total portfolio
        console.print()
        console.print("[bold cyan]━━━ Total Portfolio ━━━[/]")
        
        # Get total amounts from API response (sum of all pools)
        # Use verified_lock_amount_usdc for upcoming epoch, or active_lock_amount_usdc for current
        # Handle None values by defaulting to 0.0
        total_verified_usdc = sanitized.get("verified_lock_amount_usdc") or 0.0
        total_active_usdc = sanitized.get("active_lock_amount_usdc") or 0.0
        
        # Use the larger of verified or active as the "scoring" total
        # If active exists, that's what's currently being scored
        # If only verified, that's what will be scored in next epoch
        total_portfolio_usdc = total_active_usdc if total_active_usdc > 0 else total_verified_usdc
        
        # Also calculate from pools if API didn't provide totals
        if total_portfolio_usdc == 0 and pools:
            total_portfolio_usdc = sum(pool.get("amount_usdc", 0) for pool in pools)
        
        # Display total portfolio
        portfolio_table = Table(show_header=False, box=None, padding=(0, 2))
        portfolio_table.add_column("Label", style="cyan")
        portfolio_table.add_column("Value", style="bold")
        
        if total_active_usdc > 0:
            portfolio_table.add_row("Active Portfolio (Current Epoch)", f"${total_active_usdc:,.2f} USDC")
        if total_verified_usdc > 0 and total_verified_usdc != total_active_usdc:
            portfolio_table.add_row("Verified Portfolio (Next Epoch)", f"${total_verified_usdc:,.2f} USDC")
        if total_portfolio_usdc == 0:
            portfolio_table.add_row("Total Portfolio", "[dim]$0.00 USDC[/]")
        
        console.print(portfolio_table)
        
        # Warning if total portfolio is under 100k USDC threshold
        if total_portfolio_usdc < MIN_PORTFOLIO_THRESHOLD_USDC:
            console.print()
            warning_msg = (
                f"[bold red]⚠ MINIMUM THRESHOLD WARNING[/]\n\n"
                f"Your total portfolio is [bold]{total_portfolio_usdc:,.2f} USDC[/], "
                f"which is below the [bold]100,000 USDC[/] minimum threshold.\n\n"
                f"[yellow]Miners with less than 100k USDC total locked will receive [bold]score=0[/] "
                f"and [bold]no rewards[/] from validators.[/]\n\n"
                f"To receive rewards, you must lock at least [bold]100,000 USDC[/] total across all pools.\n"
                f"Use [cyan]https://liquidity.0xmarkets.io[/] to top up or add new positions."
            )
            console.print(Panel(warning_msg, title="[bold red]Action Required[/]", border_style="red"))

        # Link to web interface
        console.print()
        console.print("[bold cyan]━━━ Web Interface ━━━[/]")
        console.print(
            "[cyan]🌐 Manage your positions:[/] [bold]https://liquidity.0xmarkets.io[/]"
        )
        console.print(
            "[dim]  • Deposit new lock positions[/]"
        )
        console.print(
            "[dim]  • View all your lock positions[/]"
        )
        console.print(
            "[dim]  • Extend lock days[/]"
        )
        console.print(
            "[dim]  • Top up existing positions[/]"
        )

    return
