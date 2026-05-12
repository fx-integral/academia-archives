"""Register command."""

from __future__ import annotations

import bittensor as bt
import typer
from rich.prompt import Confirm
from rich.table import Table

from ..bt import (
    RegistrationResult,
    get_burn_cost,
    get_subtensor,
    get_wallet,
    register_hotkey,
)
from ..config import settings
from ..display import display_clock_and_countdown
from ..verifier import VerifierError
from .common import (
    console,
    handle_unexpected_exception,
    handle_wallet_exception,
)
from .shared_options import (
    wallet_name_option,
    wallet_hotkey_option,
    network_option,
    netuid_option,
)


def register(
    wallet_name: str | None = wallet_name_option(required=False),
    wallet_hotkey: str | None = wallet_hotkey_option(required=False),
    network: str = network_option(),
    netuid: int = netuid_option(),
    burned: bool = typer.Option(
        True,
        "--burned/--pow",
        help="Burned registration by default; pass --pow to run PoW registration.",
    ),
    cuda: bool = typer.Option(
        False, "--cuda", help="Enable CUDA for PoW registration."
    ),
) -> None:
    """Register your hotkey on the Cartha subnet (subnet 35 on finney, subnet 78 on testnet).
    
    USAGE:
    ------
    Interactive mode (recommended): 'cartha miner register' (will prompt for wallet)
    With arguments: 'cartha miner register -w cold -wh hot'
    
    ALIASES:
    --------
    Wallet: --wallet-name, --coldkey, -w  |  --wallet-hotkey, --hotkey, -wh
    Network: --network, -n
    
    REGISTRATION OPTIONS:
    ---------------------
    --burned (default): Register using burned TAO
    --pow: Register using Proof of Work
    --cuda: Enable CUDA for PoW registration
    
    After registration, use 'cartha vault lock' to create lock positions.
    
    ⚠️  Note: Password generation is no longer supported. The new lock flow uses 
    session tokens instead of passwords.
    """

    # Prompt for wallet name and hotkey if not provided
    if wallet_name is None:
        wallet_name = typer.prompt("Coldkey wallet name", default="default")
    if wallet_hotkey is None:
        wallet_hotkey = typer.prompt("Hotkey name", default="default")

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

    subtensor = None
    try:
        # Initialize subtensor and wallet to get info before registration
        try:
            subtensor = get_subtensor(network)
            wallet = get_wallet(wallet_name, wallet_hotkey)
        except bt.KeyFileError as exc:
            handle_wallet_exception(
                wallet_name=wallet_name, wallet_hotkey=wallet_hotkey, exc=exc
            )
        except typer.Exit:
            raise
        except Exception as exc:
            handle_unexpected_exception("Failed to initialize wallet/subtensor", exc)

        hotkey_ss58 = wallet.hotkey.ss58_address
        coldkey_ss58 = wallet.coldkeypub.ss58_address

        # Check if already registered
        if subtensor.is_hotkey_registered(hotkey_ss58, netuid=netuid):
            neuron = subtensor.get_neuron_for_pubkey_and_subnet(hotkey_ss58, netuid)
            uid = (
                None if getattr(neuron, "is_null", False) else getattr(neuron, "uid", None)
            )
            if uid is not None:
                console.print(f"[bold yellow]Hotkey already registered[/]. UID: {uid}")
                raise typer.Exit(code=0)

        # Get registration cost and balance
        registration_cost = None
        balance = None

        if burned:
            try:
                registration_cost = get_burn_cost(network, netuid)
            except Exception as exc:
                # Log warning but continue - cost may not be available on all networks
                console.print(
                    f"[bold yellow]Warning: Could not fetch registration cost[/]: {exc}"
                )

        try:
            balance_obj = subtensor.get_balance(coldkey_ss58)
            # Convert Balance object to float using .tao property
            balance = balance_obj.tao if hasattr(balance_obj, "tao") else float(balance_obj)
        except Exception:
            pass

        # Display registration summary table (like btcli)
        console.print(f"[bold]Using the wallet path from config:[/] {wallet.path}")

        summary_table = Table(title="Registration Summary")
        summary_table.add_column("Field", style="cyan")
        summary_table.add_column("Value", style="yellow")

        summary_table.add_row("Netuid", str(netuid))
        if burned:
            if registration_cost is not None:
                summary_table.add_row("Cost", f"τ {registration_cost:.4f}")
            else:
                summary_table.add_row("Cost", "Unable to fetch")
        summary_table.add_row("Hotkey", hotkey_ss58)
        summary_table.add_row("Coldkey", coldkey_ss58)
        summary_table.add_row("Network", network)

        console.print(summary_table)

        # Display balance and cost (already converted to float above)
        if balance is not None:
            console.print(f"\n[bold]Your balance is:[/] {balance:.4f} τ")

        if registration_cost is not None:
            console.print(
                f"[bold]The cost to register by recycle is[/] {registration_cost:.4f} τ"
            )

        # Display clock and countdown
        console.print()
        display_clock_and_countdown()

        # Confirmation prompt
        if not typer.confirm("\nDo you want to continue?", default=False):
            console.print("[bold yellow]Registration cancelled.[/]")
            raise typer.Exit(code=0)

        console.print("\n[bold cyan]Registering...[/]")

        try:
            result: RegistrationResult = register_hotkey(
                network=network,
                wallet_name=wallet_name,
                hotkey_name=wallet_hotkey,
                netuid=netuid,
                burned=burned,
                cuda=cuda,
            )
        except bt.KeyFileError as exc:
            handle_wallet_exception(
                wallet_name=wallet_name, wallet_hotkey=wallet_hotkey, exc=exc
            )
        except typer.Exit:
            raise
        except Exception as exc:
            handle_unexpected_exception("Registration failed unexpectedly", exc)

        if result.status == "already":
            console.print(f"[bold yellow]Hotkey already registered[/]. UID: {result.uid}")
            raise typer.Exit(code=0)

        if not result.success:
            console.print("[bold red]Registration failed.[/]")
            raise typer.Exit(code=1)

        # Display extrinsic if available
        if result.extrinsic:
            console.print(
                f"[bold green]✔ Your extrinsic has been included as[/] [cyan]{result.extrinsic}[/]"
            )

        # Display balance update if available (already converted to float in register_hotkey)
        if result.balance_before is not None and result.balance_after is not None:
            console.print(
                f"[bold]Balance:[/] {result.balance_before:.4f} τ -> {result.balance_after:.4f} τ"
            )

        # Display success message with UID
        if result.status == "burned":
            console.print(
                "[bold green]✔ Registered on netuid[/] "
                f"[cyan]{netuid}[/] [bold green]with UID[/] [cyan]{result.uid}[/]"
            )
        else:
            console.print(
                "[bold green]✔ Registered on netuid[/] "
                f"[cyan]{netuid}[/] [bold green]with UID[/] [cyan]{result.uid}[/]"
            )

        if result.uid is not None:
            slot_uid = str(result.uid)
            console.print()
            console.print(
                "[bold green]✓ Registration complete![/] "
                f"Hotkey: {result.hotkey}, Slot UID: {slot_uid}"
            )
            console.print()
            console.print(
                "[bold cyan]Next steps:[/]"
            )
            console.print(
                "  • Use [green]cartha vault lock[/] to create a lock position"
            )
            console.print(
                "  • Use [green]cartha miner status[/] to check your miner status"
            )
            console.print()
            console.print(
                "[dim]Note: The new lock flow uses session tokens instead of passwords. "
                "Password generation is no longer supported.[/]"
            )
        else:
            console.print(
                "[bold yellow]UID not yet available[/] (node may still be syncing)."
            )
        
        raise typer.Exit(code=0)
    finally:
        # Clean up subtensor connection
        if subtensor is not None:
            try:
                if hasattr(subtensor, "close"):
                    subtensor.close()
            except Exception:
                pass
