"""Help and root command utilities."""

from rich import box
from rich.console import Console
from rich.rule import Rule
from rich.table import Table

from ..display import get_clock_table
from .common import console


def print_root_help() -> None:
    """Print the root help message."""
    console.print(Rule("[bold cyan]Cartha CLI[/]"))
    console.print(
        "Miner-facing command line tool for Cartha subnet miners.\n"
        "Cartha is the Liquidity Provider for 0xMarkets DEX.\n"
        "Register on the subnet, manage lock positions, and track your mining status."
    )
    console.print()
    console.print("[bold]Usage[/]: cartha [OPTIONS] COMMAND [ARGS]...")
    console.print()

    options = Table(title="Options", box=box.SQUARE_DOUBLE_HEAD, show_header=False)
    options.add_row("[cyan]-h[/], [cyan]--help[/]", "Show this message and exit.")
    console.print(options)
    console.print()

    commands = Table(title="Commands", box=box.SQUARE_DOUBLE_HEAD, show_header=False)
    commands.add_row("[green]help[/]", "Show this help message.")
    commands.add_row("[green]version[/]", "Show CLI version.")
    commands.add_row(
        "[green]miner[/] [dim](or [green]m[/])[/]", "Miner management commands."
    )
    commands.add_row(
        "[green]vault[/] [dim](or [green]v[/])[/]", "Vault management commands."
    )
    commands.add_row(
        "[green]utils[/] [dim](or [green]u[/])[/]", "Utility commands: health checks and configuration."
    )
    console.print(commands)
    console.print()

    # Display clock and countdown in a separate table
    clock_table = get_clock_table()
    console.print(clock_table)
    console.print()

    console.print("[dim]Made with ❤ by GTV[/]")
