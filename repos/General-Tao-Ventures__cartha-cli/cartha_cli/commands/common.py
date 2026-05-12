"""Common utilities and helpers for CLI commands."""

from __future__ import annotations

from typing import NoReturn

import bittensor as bt
import typer
from rich.console import Console

from ..config import settings

console = Console()

_TRACE_ENABLED = False


def set_trace_enabled(enabled: bool) -> None:
    """Set whether trace mode is enabled."""
    global _TRACE_ENABLED
    _TRACE_ENABLED = enabled


def trace_enabled() -> bool:
    """Check if trace mode is enabled."""
    return _TRACE_ENABLED


def exit_with_error(message: str, code: int = 1) -> NoReturn:
    """Exit with an error message."""
    console.print(f"[bold red]{message}[/]")
    raise typer.Exit(code=code)


def handle_wallet_exception(
    *,
    wallet_name: str | None,
    wallet_hotkey: str | None,
    exc: Exception,
) -> None:
    """Handle wallet-related exceptions."""
    detail = str(exc).strip()
    name = wallet_name or "<unknown>"
    hotkey = wallet_hotkey or "<unknown>"
    message = (
        f"Unable to open coldkey '{name}' hotkey '{hotkey}'. "
        "Ensure the wallet exists, hotkey files are present, and the key is unlocked."
    )
    if detail:
        message += f" ({detail})"
    exit_with_error(message)


def handle_unexpected_exception(context: str, exc: Exception) -> None:
    """Handle unexpected exceptions."""
    if trace_enabled():
        raise
    detail = str(exc).strip()
    message = context
    if detail:
        message += f" ({detail})"
    exit_with_error(message)


def log_endpoint_banner() -> None:
    """Log the endpoint banner based on verifier URL."""
    verifier_url = settings.verifier_url.lower()
    if verifier_url.startswith("http://127.0.0.1"):
        console.print("[bold cyan]Using local verifier endpoint[/]")
    elif "pr-" in verifier_url:
        console.print("[bold cyan]Using Cartha DEV network verifier[/]")
    elif "cartha-verifier-826542474079.us-central1.run.app" in verifier_url:
        console.print("[bold cyan]Using Cartha Testnet Verifier[/]")
    else:
        console.print("[bold cyan]Using Cartha network verifier[/]")

