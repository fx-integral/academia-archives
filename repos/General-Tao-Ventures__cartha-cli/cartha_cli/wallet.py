"""Wallet handling utilities for the Cartha CLI."""

from __future__ import annotations

import bittensor as bt
import typer
from rich.console import Console

from .bt import get_wallet
from .utils import format_timestamp

console = Console()

CHALLENGE_PREFIX = "cartha-pair-auth"
CHALLENGE_TTL_SECONDS = 120


def load_wallet(
    wallet_name: str, wallet_hotkey: str, expected_hotkey: str | None = None
) -> bt.wallet:
    """Load a Bittensor wallet.

    Args:
        wallet_name: Coldkey wallet name
        wallet_hotkey: Hotkey name
        expected_hotkey: Optional expected hotkey SS58 address to validate

    Returns:
        Loaded wallet object

    Raises:
        typer.Exit: If wallet cannot be loaded or hotkey mismatch
    """
    try:
        wallet = get_wallet(wallet_name, wallet_hotkey)
    except bt.KeyFileError as exc:
        detail = str(exc).strip()
        name = wallet_name or "<unknown>"
        hotkey = wallet_hotkey or "<unknown>"
        message = (
            f"Unable to open coldkey '{name}' hotkey '{hotkey}'. "
            "Ensure the wallet exists, hotkey files are present, and the key is unlocked."
        )
        if detail:
            message += f" ({detail})"
        console.print(f"[bold red]{message}[/]")
        raise typer.Exit(code=1) from exc
    except Exception as exc:  # pragma: no cover - defensive
        console.print(f"[bold red]Failed to load wallet '{wallet_name}/{wallet_hotkey}': {exc}[/]")
        raise typer.Exit(code=1) from exc

    if expected_hotkey and wallet.hotkey.ss58_address != expected_hotkey:
        console.print(
            "[bold red]Hotkey mismatch: loaded wallet hotkey does not match the supplied address.[/]"
        )
        raise typer.Exit(code=1)

    return wallet

