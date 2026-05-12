"""Pair status command."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import bittensor as bt
import typer
from rich.json import JSON
from rich.table import Table

from ..config import settings
from ..display import display_clock_and_countdown
from ..pair import (
    build_pair_auth_payload,
    get_uid_from_hotkey,
)
from ..utils import format_timestamp, format_timestamp_multiline, format_evm_address
from ..verifier import VerifierError, fetch_pair_status
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
)

# Import pool name helper from pool_client (fetches from verifier API)
from ..pool_client import pool_id_to_name


def pair_status(
    wallet_name: str = wallet_name_option(required=True),
    wallet_hotkey: str = wallet_hotkey_option(required=True),
    slot: int | None = slot_option(),
    auto_fetch_uid: bool = auto_fetch_uid_option(),
    network: str = network_option(),
    netuid: int = netuid_option(),
    json_output: bool = json_output_option(),
) -> None:
    """Show the verifier state for a miner pair (legacy - use 'cartha miner status' instead).

    USAGE:
    ------
    Interactive mode: 'cartha pair status' (will prompt for wallet)
    With arguments: 'cartha pair status -w cold -wh hot'
    
    ALIASES:
    --------
    Wallet: --wallet-name, --coldkey, -w  |  --wallet-hotkey, --hotkey, -wh
    Slot: --slot, --uid, -u  |  Network: --network, -n

    DEPRECATED: Use 'cartha miner status' instead for faster status checks without authentication.

    State Legend:
    ════════════════════════════════════════════════════════════════

    1. active   - In current frozen epoch, earning rewards

    2. verified - Has lock proof, not in current active epoch

    3. pending  - Registered, no lock proof submitted yet

    4. revoked  - Revoked (deregistered or evicted)

    5. unknown  - No pair record found

    ════════════════════════════════════════════════════════════════
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
        
        console.print("[bold cyan]Loading wallet...[/]")
        wallet = load_wallet(wallet_name, wallet_hotkey, None)
        hotkey = wallet.hotkey.ss58_address

        # Fetch UID automatically by default, prompt if disabled
        if slot is None:
            if auto_fetch_uid:
                # Auto-fetch enabled (default) - try to fetch from network
                console.print("[bold cyan]Fetching UID from subnet...[/]")
                try:
                    slot = get_uid_from_hotkey(
                        network=network, netuid=netuid, hotkey=hotkey
                    )
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
                    console.print(f"[bold green]Found UID: {slot}[/]")
                except typer.Exit:
                    raise
                except Exception as exc:
                    console.print(
                        "[bold red]Failed to fetch UID automatically[/]: This may be due to Bittensor network issues."
                    )
                    console.print("[yellow]Falling back to manual input...[/]")
                    try:
                        slot_input = typer.prompt("Enter your slot UID", type=int)
                        slot = slot_input
                        console.print(f"[bold green]Using UID: {slot}[/]")
                    except (ValueError, KeyboardInterrupt):
                        console.print("[bold red]Invalid UID or cancelled.[/]")
                        raise typer.Exit(code=1) from exc
            else:
                # Auto-fetch disabled (--no-auto-fetch-uid) - prompt for UID
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
                    console.print(f"[bold green]Using UID: {slot}[/]")
                except (ValueError, KeyboardInterrupt):
                    console.print("[bold red]Invalid UID or cancelled.[/]")
                    raise typer.Exit(code=1)

        slot_id = str(slot)
        # Skip metagraph check - verifier will validate the pair anyway
        # This avoids slow metagraph() calls that cause timeouts

        console.print("[bold cyan]Signing hotkey ownership challenge...[/]")
        auth_payload = build_pair_auth_payload(
            network=network,
            netuid=netuid,
            slot=slot_id,
            hotkey=hotkey,
            wallet_name=wallet_name,
            wallet_hotkey=wallet_hotkey,
        )
        with console.status(
            "[bold cyan]Verifying ownership with Cartha verifier...[/]",
            spinner="dots",
        ):
            status = fetch_pair_status(
                hotkey=hotkey,
                slot=slot_id,
                network=network,
                netuid=netuid,
                message=auth_payload["message"],
                signature=auth_payload["signature"],
            )
    except bt.KeyFileError as exc:
        handle_wallet_exception(
            wallet_name=wallet_name, wallet_hotkey=wallet_hotkey, exc=exc
        )
    except typer.Exit:
        raise
    except VerifierError as exc:
        # VerifierError handling
        error_msg = str(exc)
        if "timed out" in error_msg.lower() or "timeout" in error_msg.lower():
            console.print(f"[bold red]Request timed out[/]")
            # Print the full error message (may be multi-line)
            console.print(f"[yellow]{error_msg}[/]")
        else:
            console.print(f"[bold red]Verifier request failed[/]: {exc}")
        raise typer.Exit(code=1) from exc
    except Exception as exc:
        # Check if it's a timeout-related error (even if wrapped)
        error_msg = str(exc)
        error_type = type(exc).__name__

        # Check for timeout indicators in the exception
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

        handle_unexpected_exception("Unable to fetch pair status", exc)

    initial_status = dict(status)
    password_payload: dict[str, Any] | None = None

    existing_pwd = initial_status.get("pwd")
    state = initial_status.get("state") or "unknown"
    has_pwd_flag = initial_status.get("has_pwd") or bool(existing_pwd)

    # Note: Password registration removed - new lock flow uses session tokens instead
    # The has_pwd flag is kept for backward compatibility but passwords are no longer used

    sanitized = dict(status)
    sanitized.setdefault("state", "unknown")
    sanitized["hotkey"] = hotkey
    sanitized["slot"] = slot_id
    password = sanitized.get("pwd")

    if json_output:
        console.print(JSON.from_data(sanitized))
        if password:
            console.print(
                "[bold yellow]Keep it safe[/] — for your eyes only. Exposure might allow others to steal your locked USDC rewards."
            )
        return

    # Display clock and countdown
    display_clock_and_countdown()

    table = Table(title="Pair Status", show_header=False)
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

    table.add_row("Password issued", "yes" if sanitized.get("has_pwd") else "no")
    issued_at = sanitized.get("issued_at")
    if issued_at:
        # Try to parse and format the timestamp
        try:
            if isinstance(issued_at, (int, float)) or (
                isinstance(issued_at, str) and issued_at.isdigit()
            ):
                # Numeric timestamp
                formatted_time = format_timestamp(issued_at)
            elif isinstance(issued_at, str):
                # Try parsing as ISO format datetime string
                try:
                    dt = datetime.fromisoformat(issued_at.replace("Z", "+00:00"))
                    timestamp = dt.timestamp()
                    formatted_time = format_timestamp(timestamp)
                except (ValueError, AttributeError):
                    # If parsing fails, display as-is
                    formatted_time = issued_at
            else:
                formatted_time = str(issued_at)
            table.add_row("Password issued at", formatted_time)
        except Exception:
            table.add_row("Password issued at", str(issued_at))
    if password:
        table.add_row("Pair password", password)
    console.print(table)

    # Show warnings and reminders
    if password:
        console.print()
        console.print(
            "[bold yellow]🔐 Keep your password safe[/] — Exposure might allow others to steal your locked USDC rewards."
        )

    # Show detailed status information for verified/active pairs
    if state in ("verified", "active"):
        pools = sanitized.get("pools", [])
        in_upcoming_epoch = sanitized.get("in_upcoming_epoch")
        expires_at = sanitized.get("expires_at")

        # Display per-pool table (primary display for lock information)
        if pools:
            console.print()
            console.print("[bold cyan]━━━ Active Pools ━━━[/]")

            pool_table = Table(show_header=True, header_style="bold cyan")
            pool_table.add_column("Pool Name", style="cyan", no_wrap=True)
            pool_table.add_column("Amount Locked", style="green", justify="right")
            pool_table.add_column("Lock Days", justify="center")
            pool_table.add_column("Expires At", style="yellow")
            pool_table.add_column("Status", justify="center")
            pool_table.add_column("EVM Address", style="dim")

            for pool in pools:
                # Format pool name - use human-readable name if available
                pool_name = pool.get("pool_name")
                if not pool_name:
                    # Fallback to pool_id if name not available
                    pool_id = pool.get("pool_id", "")
                    if pool_id:
                        # Try to convert pool_id to name
                        pool_name = pool_id_to_name(pool_id) or pool_id[:10] + "..."
                    else:
                        pool_name = "Unknown"
                pool_display = pool_name

                # Format amount locked
                amount_usdc = pool.get("amount_usdc", 0)
                amount_str = f"{amount_usdc:.2f}"

                # Format lock days
                lock_days = pool.get("lock_days", 0)
                lock_days_str = str(lock_days)

                # Format expiration
                pool_expires_at = pool.get("expires_at")
                expires_str = "N/A"
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
                            expires_str = format_timestamp(exp_dt.timestamp())
                    except Exception:
                        expires_str = str(pool_expires_at)

                # Format status - show which pools are active, verified, and included in next epoch
                is_active = pool.get("is_active", False)
                is_verified = pool.get("is_verified", False)
                pool_in_upcoming = pool.get("in_upcoming_epoch", False)

                status_parts = []
                if is_active:
                    status_parts.append("[green]Active[/]")
                if is_verified:
                    status_parts.append("[cyan]Verified[/]")
                if pool_in_upcoming:
                    status_parts.append("[bold green]In Next Epoch[/]")
                if not status_parts:
                    status_parts.append("[dim]None[/]")

                status_str = " / ".join(status_parts)

                # EVM address (full address for clarity)
                evm_addr = pool.get("evm_address", "")
                evm_display = (
                    evm_addr
                    if len(evm_addr) <= 42
                    else (evm_addr[:20] + "..." + evm_addr[-6:])
                )

                pool_table.add_row(
                    pool_display,
                    f"{amount_str} USDC",
                    lock_days_str,
                    expires_str,
                    status_str,
                    evm_display,
                )

            console.print(pool_table)

        console.print()
        console.print("[bold cyan]━━━ Epoch Status ━━━[/]")

        # Upcoming epoch inclusion status
        if in_upcoming_epoch:
            console.print(
                "[bold green]✓ Included in upcoming epoch[/] — You will receive rewards for the next epoch."
            )
        elif in_upcoming_epoch is False:
            console.print(
                "[bold yellow]⚠ Not included in upcoming epoch[/] — Use [bold]cartha vault lock[/] to be included."
            )

        # Expiration date information and warnings (aggregated)
        if expires_at:
            try:
                # Parse expiration datetime
                if isinstance(expires_at, str):
                    exp_dt = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
                elif isinstance(expires_at, datetime):
                    exp_dt = expires_at
                else:
                    exp_dt = None

                if exp_dt:
                    now = datetime.now(UTC)
                    time_until_expiry = (exp_dt - now).total_seconds()
                    days_until_expiry = time_until_expiry / 86400

                    console.print()
                    console.print("[bold cyan]━━━ Lock Expiration ━━━[/]")

                    if days_until_expiry < 0:
                        console.print(
                            "[bold red]⚠ EXPIRED[/] — Some locks expired. USDC will be returned. No more emissions for expired pools."
                        )
                    elif days_until_expiry <= 7:
                        console.print(
                            f"[bold red]⚠ Expiring in {days_until_expiry:.1f} days[/] — Make a new lock transaction on-chain to continue receiving emissions."
                        )
                    elif days_until_expiry <= 30:
                        console.print(
                            f"[bold yellow]⚠ Expiring in {days_until_expiry:.0f} days[/] — Consider making a new lock transaction on-chain soon."
                        )
                    else:
                        console.print(
                            f"[bold green]✓ Valid for {days_until_expiry:.0f} days[/]"
                        )
            except Exception:
                pass

        # Concise reminder
        console.print()
        console.print("[bold cyan]━━━ Reminders ━━━[/]")
        console.print(
            "• Lock expiration: USDC returned automatically, emissions stop for that pool."
        )
        console.print(
            "• Top-ups/extensions: Happen automatically on-chain. No CLI action needed."
        )
        if pools and len(pools) > 1:
            console.print(
                "• Multiple pools: Each pool is tracked separately. Expired pools stop earning, others continue."
            )

    # Explicitly return to ensure clean exit
    return
