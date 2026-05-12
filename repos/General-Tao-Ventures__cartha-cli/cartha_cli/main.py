"""Primary Typer application for the Cartha CLI."""

from __future__ import annotations

import typer

from .commands import (
    config,
    health,
    miner_status,
    pair_status,
    pools,
    prove_lock,
    register,
    version,
)
from .commands.common import log_endpoint_banner, set_trace_enabled
from .commands.help import print_root_help

app = typer.Typer(
    help="Miner-facing tooling for registering on the Cartha subnet and managing lock positions. Cartha is the Liquidity Provider for 0xMarkets DEX.",
    add_completion=False,
)

# Create command groups
miner_app = typer.Typer(
    help="Miner management commands: register, check status, and manage passwords.",
    name="miner",
    invoke_without_command=True,
)
miner_app_alias = typer.Typer(
    help="Miner management commands: register, check status, and manage passwords.",
    name="m",
    invoke_without_command=True,
)
vault_app = typer.Typer(
    help="Vault management commands: lock funds and claim deposits.",
    name="vault",
    invoke_without_command=True,
)
vault_app_alias = typer.Typer(
    help="Vault management commands: lock funds and claim deposits.",
    name="v",
    invoke_without_command=True,
)


# Define callbacks for groups (show help when invoked without subcommand)
def miner_group_callback(
    ctx: typer.Context,
    help_option: bool = typer.Option(
        False,
        "--help",
        "-h",
        help="Show this message and exit.",
        is_eager=True,
    ),
) -> None:
    """Miner management commands."""
    if ctx.invoked_subcommand is None or help_option:
        ctx.get_help()
        raise typer.Exit()


def vault_group_callback(
    ctx: typer.Context,
    help_option: bool = typer.Option(
        False,
        "--help",
        "-h",
        help="Show this message and exit.",
        is_eager=True,
    ),
) -> None:
    """Vault management commands."""
    if ctx.invoked_subcommand is None or help_option:
        ctx.get_help()
        raise typer.Exit()


# Register callbacks for both miner apps (main and alias)
miner_app.callback(invoke_without_command=True)(miner_group_callback)
miner_app_alias.callback(invoke_without_command=True)(miner_group_callback)

# Register callbacks for both vault apps (main and alias)
vault_app.callback(invoke_without_command=True)(vault_group_callback)
vault_app_alias.callback(invoke_without_command=True)(vault_group_callback)

# Register commands in both miner apps (main and alias)
for miner_group in [miner_app, miner_app_alias]:
    miner_group.command("status")(miner_status.miner_status)
    miner_group.command("register")(register.register)

# Register commands in both vault apps (main and alias)
for vault_group in [vault_app, vault_app_alias]:
    vault_group.command("lock")(prove_lock.prove_lock)
    vault_group.command("pools")(pools.pools)

# Add groups with short aliases (after callbacks and commands are registered)
app.add_typer(miner_app, name="miner")
app.add_typer(miner_app_alias, name="m")  # Short alias
app.add_typer(vault_app, name="vault")
app.add_typer(vault_app_alias, name="v")  # Short alias

# Keep pair_app for backward compatibility (deprecated)
pair_app = typer.Typer(
    help="Pair status commands (deprecated - use 'cartha miner status')."
)
app.add_typer(pair_app, name="pair")


@app.callback(invoke_without_command=True)
def cli_root(
    ctx: typer.Context,
    help_option: bool = typer.Option(
        False,
        "--help",
        "-h",
        help="Show this message and exit.",
        is_eager=True,
    ),
    trace: bool = typer.Option(
        False,
        "--trace",
        help="Show full stack traces when errors occur.",
    ),
) -> None:
    """Top-level callback to provide rich help and endpoint banner."""
    set_trace_enabled(trace)
    if ctx.obj is None:
        ctx.obj = {}
    ctx.obj["trace"] = trace

    if help_option:
        print_root_help()
        raise typer.Exit()

    if ctx.invoked_subcommand is None:
        print_root_help()
        raise typer.Exit()

    log_endpoint_banner()


# Register top-level commands
app.command("version")(version.version_command)

# Create utils command group
utils_app = typer.Typer(
    help="Utility commands: health checks and configuration management.",
    name="utils",
    invoke_without_command=True,
)
utils_app_alias = typer.Typer(
    help="Utility commands: health checks and configuration management.",
    name="u",
    invoke_without_command=True,
)

def utils_group_callback(
    ctx: typer.Context,
    help_option: bool = typer.Option(
        False,
        "--help",
        "-h",
        help="Show this message and exit.",
        is_eager=True,
    ),
) -> None:
    """Utility commands."""
    if ctx.invoked_subcommand is None or help_option:
        ctx.get_help()
        raise typer.Exit()

# Register callbacks for both utils apps (main and alias)
utils_app.callback(invoke_without_command=True)(utils_group_callback)
utils_app_alias.callback(invoke_without_command=True)(utils_group_callback)

# Register commands in both utils apps (main and alias)
for utils_group in [utils_app, utils_app_alias]:
    utils_group.command("health")(health.health_check)

# Create config subcommand group under utils
config_app = typer.Typer(
    help="Configuration commands: view and set environment variables.",
    name="config",
    invoke_without_command=True,
)

def config_group_callback(
    ctx: typer.Context,
    help_option: bool = typer.Option(
        False,
        "--help",
        "-h",
        help="Show this message and exit.",
        is_eager=True,
    ),
) -> None:
    """Configuration commands."""
    if ctx.invoked_subcommand is None or help_option:
        if ctx.invoked_subcommand is None:
            # Show list by default
            config.config_list()
        else:
            ctx.get_help()
        raise typer.Exit()

config_app.callback(invoke_without_command=True)(config_group_callback)
config_app.command("list")(config.config_list)
config_app.command("set")(config.config_set)
config_app.command("get")(config.config_get)
config_app.command("unset")(config.config_unset)

# Add config to both utils apps (main and alias)
for utils_group in [utils_app, utils_app_alias]:
    utils_group.add_typer(config_app)

# Add groups with short aliases (after callbacks and commands are registered)
app.add_typer(utils_app, name="utils")
app.add_typer(utils_app_alias, name="u")  # Short alias


def help_command() -> None:
    """Show help message."""
    print_root_help()
    raise typer.Exit()


app.command("help")(help_command)

# Keep deprecated commands for backward compatibility
pair_app.command("status")(pair_status.pair_status)


if __name__ == "__main__":  # pragma: no cover
    app()
