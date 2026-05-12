"""Version command."""

from importlib.metadata import PackageNotFoundError, version

from .common import console


def version_command() -> None:
    """Print the CLI version."""
    try:
        console.print(f"[bold white]cartha-cli[/] {version('cartha-cli')}")
    except PackageNotFoundError:  # pragma: no cover
        console.print("[bold white]cartha-cli[/] 0.0.0")
    console.print("[dim]Cartha is the Liquidity Provider for 0xMarkets DEX[/]")

