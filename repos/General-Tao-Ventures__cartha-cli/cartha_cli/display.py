"""Display and formatting utilities for the Cartha CLI."""

from __future__ import annotations

from datetime import UTC, datetime

from rich import box
from rich.console import Console
from rich.table import Table

from .utils import format_countdown, get_local_timezone, get_next_epoch_freeze_time

console = Console()


def get_clock_table() -> Table:
    """Create a table with current time (UTC and local) and countdown to next epoch freeze.

    Returns:
        Table with clock and countdown information
    """
    now_utc = datetime.now(tz=UTC)
    local_tz = get_local_timezone()
    now_local = now_utc.astimezone(local_tz)

    # Format current time
    utc_str = now_utc.strftime("%Y-%m-%d %H:%M:%S UTC")
    local_str = now_local.strftime("%Y-%m-%d %H:%M:%S %Z")

    # Calculate next epoch freeze
    next_freeze_utc = get_next_epoch_freeze_time(now_utc)
    next_freeze_local = next_freeze_utc.astimezone(local_tz)

    # Calculate countdown
    time_until_freeze = (next_freeze_utc - now_utc).total_seconds()
    countdown_str = format_countdown(time_until_freeze)

    # Format next freeze times
    next_freeze_utc_str = next_freeze_utc.strftime("%Y-%m-%d %H:%M:%S UTC")
    next_freeze_local_str = next_freeze_local.strftime("%Y-%m-%d %H:%M:%S %Z")

    # Create table
    clock_table = Table(show_header=False, box=box.SIMPLE)
    clock_table.add_column(style="cyan")
    clock_table.add_column(style="yellow")

    clock_table.add_row("Current time (UTC)", utc_str)
    clock_table.add_row("Current time (Local)", local_str)
    clock_table.add_row("", "")  # Spacer
    clock_table.add_row("Next epoch freeze (UTC)", next_freeze_utc_str)
    clock_table.add_row("Next epoch freeze (Local)", next_freeze_local_str)
    clock_table.add_row("Countdown", countdown_str)

    return clock_table


def display_clock_and_countdown() -> None:
    """Display the clock table with current time and countdown."""
    clock_table = get_clock_table()
    console.print(clock_table)
    console.print()  # Empty line after table

