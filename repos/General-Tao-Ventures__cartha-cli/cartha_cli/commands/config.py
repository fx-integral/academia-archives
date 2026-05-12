"""Configuration command - view and set environment variables."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import typer
from rich.table import Table

from ..config import Settings
from .common import console


# Environment variable documentation
ENV_VAR_DOCS: dict[str, dict[str, Any]] = {
    "CARTHA_VERIFIER_URL": {
        "description": "URL of the Cartha verifier service",
        "default": "https://api.cartha.finance",
        "required": False,
    },
    "CARTHA_NETWORK": {
        "description": "Bittensor network name (e.g., 'finney', 'test')",
        "default": "finney",
        "required": False,
    },
    "CARTHA_NETUID": {
        "description": "Subnet UID (netuid) for the Cartha subnet",
        "default": "35",
        "required": False,
    },
    "CARTHA_EVM_PK": {
        "description": "EVM private key for signing transactions (sensitive)",
        "default": None,
        "required": False,
        "sensitive": True,
    },
    "CARTHA_RETRY_MAX_ATTEMPTS": {
        "description": "Maximum number of retry attempts for failed requests",
        "default": "3",
        "required": False,
    },
    "CARTHA_RETRY_BACKOFF_FACTOR": {
        "description": "Backoff factor for exponential retry delays",
        "default": "1.5",
        "required": False,
    },
    "CARTHA_LOCK_UI_URL": {
        "description": "URL of the Cartha Lock UI frontend",
        "default": "https://liquidity.0xmarkets.io",
        "required": False,
    },
}


def _get_env_file_path() -> Path:
    """Get the path to the .env file in the current directory."""
    return Path.cwd() / ".env"


def _read_env_file() -> dict[str, str]:
    """Read existing .env file and return as dict."""
    env_file = _get_env_file_path()
    env_vars: dict[str, str] = {}
    
    if env_file.exists():
        try:
            with open(env_file, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    # Skip empty lines and comments
                    if not line or line.startswith("#"):
                        continue
                    # Parse KEY=VALUE format
                    if "=" in line:
                        key, value = line.split("=", 1)
                        env_vars[key.strip()] = value.strip().strip('"').strip("'")
        except Exception:
            pass
    
    return env_vars


def _write_env_file(env_vars: dict[str, str], remove_vars: set[str] | None = None) -> None:
    """Write environment variables to .env file.
    
    Args:
        env_vars: Dictionary of variables to set/update
        remove_vars: Optional set of variable names to remove from file
    """
    env_file = _get_env_file_path()
    remove_vars = remove_vars or set()
    
    # Read existing file to preserve comments and other vars
    existing_lines: list[str] = []
    existing_vars: set[str] = set()
    
    if env_file.exists():
        with open(env_file, "r", encoding="utf-8") as f:
            for line in f:
                stripped = line.strip()
                if stripped and not stripped.startswith("#") and "=" in stripped:
                    key = stripped.split("=", 1)[0].strip()
                    existing_vars.add(key)
                    # Skip lines for variables we want to remove
                    if key in remove_vars:
                        continue
                existing_lines.append(line.rstrip())
    
    # Update or add new vars
    for key, value in env_vars.items():
        if key in existing_vars and key not in remove_vars:
            # Update existing line
            for i, line in enumerate(existing_lines):
                if line.strip() and not line.strip().startswith("#") and line.startswith(f"{key}="):
                    existing_lines[i] = f"{key}={value}"
                    break
        elif key not in remove_vars:
            # Add new line
            existing_lines.append(f"{key}={value}")
    
    # Write back to file
    with open(env_file, "w", encoding="utf-8") as f:
        for line in existing_lines:
            f.write(line + "\n")


def config_list() -> None:
    """List all available environment variables and their current values."""
    console.print("\n[bold cyan]━━━ Configuration ━━━[/]")
    console.print()
    
    # Get default values
    default_settings = Settings()
    
    # Get current values from environment
    current_values: dict[str, str | None] = {}
    for env_var in ENV_VAR_DOCS.keys():
        current_values[env_var] = os.getenv(env_var)
    
    # Create table
    table = Table(show_header=True, header_style="bold cyan")
    table.add_column("Variable", style="cyan", no_wrap=True)
    table.add_column("Description", style="dim")
    table.add_column("Current Value", style="green")
    table.add_column("Default", style="dim")
    table.add_column("Source", justify="center")
    
    for env_var, doc in ENV_VAR_DOCS.items():
        current_val = current_values.get(env_var)
        default_val = doc.get("default")
        is_sensitive = doc.get("sensitive", False)
        
        # Format current value
        if current_val is not None:
            if is_sensitive:
                display_current = "[REDACTED]"
            else:
                display_current = current_val
            source = "[green]●[/] env"
        else:
            display_current = default_val or "-"
            source = "[dim]○[/] default"
        
        # Format default value
        display_default = default_val or "-"
        
        table.add_row(
            env_var,
            doc["description"],
            display_current,
            display_default,
            source,
        )
    
    console.print(table)
    console.print()
    console.print("[dim]● = Set via environment variable[/]")
    console.print("[dim]○ = Using default value[/]")
    console.print()
    console.print(f"[dim]Environment file: {_get_env_file_path()}[/]")
    console.print("[dim]Use 'cartha config set <VAR> <VALUE>' to set a value[/]")


def config_set(
    variable: str = typer.Argument(..., help="Environment variable name (e.g., CARTHA_VERIFIER_URL)"),
    value: str = typer.Argument(..., help="Value to set"),
    env_file: bool = typer.Option(
        True,
        "--env-file/--no-env-file",
        help="Write to .env file (default: True). If False, only sets in current session.",
    ),
) -> None:
    """Set an environment variable value.
    
    By default, writes to .env file in the current directory. Use --no-env-file
    to only set for the current session (doesn't persist).
    """
    # Validate variable name
    if variable not in ENV_VAR_DOCS:
        console.print(f"[bold red]✗ Unknown variable: {variable}[/]")
        console.print(f"\nAvailable variables:")
        for var_name in ENV_VAR_DOCS.keys():
            console.print(f"  • {var_name}")
        raise typer.Exit(code=1)
    
    doc = ENV_VAR_DOCS[variable]
    is_sensitive = doc.get("sensitive", False)
    
    if env_file:
        # Read existing .env file
        env_vars = _read_env_file()
        
        # Update the variable
        env_vars[variable] = value
        
        # Write back
        try:
            _write_env_file(env_vars)
            display_value = "[REDACTED]" if is_sensitive else value
            console.print(f"[bold green]✓ Set {variable}={display_value}[/]")
            console.print(f"[dim]Written to: {_get_env_file_path()}[/]")
            console.print("[yellow]Note: Restart your terminal or run 'source .env' to apply changes[/]")
        except Exception as exc:
            console.print(f"[bold red]✗ Failed to write to .env file: {exc}[/]")
            raise typer.Exit(code=1)
    else:
        # Only set for current session
        os.environ[variable] = value
        display_value = "[REDACTED]" if is_sensitive else value
        console.print(f"[bold green]✓ Set {variable}={display_value}[/] (current session only)")
        console.print("[yellow]Note: This will not persist after the terminal session ends[/]")


def config_get(
    variable: str = typer.Argument(..., help="Environment variable name (e.g., CARTHA_VERIFIER_URL)"),
) -> None:
    """Get the current value of an environment variable."""
    if variable not in ENV_VAR_DOCS:
        console.print(f"[bold red]✗ Unknown variable: {variable}[/]")
        console.print(f"\nAvailable variables:")
        for var_name in ENV_VAR_DOCS.keys():
            console.print(f"  • {var_name}")
        raise typer.Exit(code=1)
    
    doc = ENV_VAR_DOCS[variable]
    is_sensitive = doc.get("sensitive", False)
    
    # Get current value
    current_val = os.getenv(variable)
    default_val = doc.get("default")
    
    console.print(f"\n[bold cyan]{variable}[/]")
    console.print(f"Description: {doc['description']}")
    console.print(f"Default: {default_val or 'None'}")
    
    if current_val is not None:
        display_value = "[REDACTED]" if is_sensitive else current_val
        console.print(f"Current Value: [green]{display_value}[/] (from environment)")
    else:
        console.print(f"Current Value: [dim]{default_val or 'None'}[/] (using default)")


def config_unset(
    variable: str = typer.Argument(..., help="Environment variable name to unset"),
    env_file: bool = typer.Option(
        True,
        "--env-file/--no-env-file",
        help="Remove from .env file (default: True). If False, only unsets in current session.",
    ),
) -> None:
    """Unset an environment variable (remove from .env file or current session)."""
    if variable not in ENV_VAR_DOCS:
        console.print(f"[bold red]✗ Unknown variable: {variable}[/]")
        raise typer.Exit(code=1)
    
    if env_file:
        # Read existing .env file to check if it exists
        env_vars = _read_env_file()
        
        if variable in env_vars:
            # Remove from file
            _write_env_file({}, remove_vars={variable})
            console.print(f"[bold green]✓ Removed {variable} from .env file[/]")
        else:
            console.print(f"[yellow]⚠ {variable} not found in .env file[/]")
    else:
        # Remove from current session
        if variable in os.environ:
            del os.environ[variable]
            console.print(f"[bold green]✓ Removed {variable} from current session[/]")
        else:
            console.print(f"[yellow]⚠ {variable} not set in current session[/]")
