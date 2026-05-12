"""Pools command - show current available pools."""

from __future__ import annotations

import typer

from .common import console
from ..verifier import VerifierError, fetch_pools


def pools(
    json_output: bool = typer.Option(
        False, "--json", help="Emit responses as JSON."
    ),
) -> None:
    """Show all available pools with their names, IDs, vault addresses, and chain IDs.
    
    USAGE:
    ------
    cartha vault pools (or: cartha v pools)
    cartha vault pools --json (for JSON output)
    
    OUTPUT:
    -------
    - Pool names: BTC/USD, ETH/USD, EUR/USD, etc.
    - Pool IDs: Full hex identifiers (0x...)
    - Vault addresses: Contract addresses for each pool
    - Chain IDs: Which blockchain network (8453 for Base Mainnet, 84532 for Base Sepolia)
    
    Use these pool names directly in 'cartha vault lock -p BTCUSD ...'
    """
    try:
        # Fetch pools from verifier API
        pools_list = fetch_pools()

        if json_output:
            # JSON output format
            import json
            console.print(json.dumps(pools_list, indent=2))
            return

        # Multi-line text output
        if not pools_list:
            console.print("[yellow]No pools available.[/]")
            return

        console.print("\n[bold cyan]Available Pools[/]\n")

        for idx, pool in enumerate(pools_list, 1):
            pool_name = pool.get("name", "Unknown")
            # Verifier returns camelCase keys
            pool_id_hex = pool.get("poolId", "")
            vault_addr = pool.get("vaultAddress")
            chain_id = pool.get("chainId")
            network = pool.get("network", "")

            # Ensure full pool ID is displayed (normalize to ensure 0x prefix)
            pool_id_display = pool_id_hex if pool_id_hex.startswith("0x") else f"0x{pool_id_hex}"
            
            # Ensure full vault address is displayed
            vault_display = vault_addr if vault_addr else "[dim]N/A[/]"
            
            # Format chain display with network name
            if chain_id:
                if chain_id == 8453:
                    chain_display = f"{chain_id} (Base Mainnet)"
                elif chain_id == 84532:
                    chain_display = f"{chain_id} (Base Sepolia)"
                else:
                    chain_display = str(chain_id)
            else:
                chain_display = "[dim]N/A[/]"

            console.print(f"[bold cyan]Pool {idx}:[/] {pool_name}")
            console.print(f"  [yellow]Pool ID:[/]      {pool_id_display}")
            console.print(f"  [green]Vault Address:[/] {vault_display}")
            console.print(f"  [dim]Chain ID:[/]     {chain_display}")
            
            # Add spacing between pools except for the last one
            if idx < len(pools_list):
                console.print()

    except VerifierError as exc:
        console.print(f"[bold red]Error:[/] Failed to fetch pools from verifier: {exc}")
        console.print("[dim]Tip: Check your network connection and verifier URL configuration.[/]")
        raise typer.Exit(code=1)
    except Exception as exc:
        console.print(f"[bold red]Error:[/] Failed to list pools: {exc}")
        raise typer.Exit(code=1)
