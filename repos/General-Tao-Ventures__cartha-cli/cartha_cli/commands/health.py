"""Health check command - verify CLI connectivity and configuration."""

from __future__ import annotations

import os
import time
from typing import Any

import bittensor as bt
import typer
from rich.console import Console
from rich.table import Table

from ..config import Settings, settings
from ..verifier import VerifierError, _build_url, _request
from .common import console

import requests  # type: ignore[import-untyped]


def health_check(
    verbose: bool = typer.Option(
        False, "--verbose", "-v", help="Show detailed information for each check."
    ),
) -> None:
    """Check CLI health: verifier connectivity, Bittensor network, and configuration.
    
    USAGE:
    ------
    cartha utils health (or: cartha u health)
    cartha utils health --verbose (or: -v)
    
    CHECKS:
    -------
    1. Verifier connectivity and response time
    2. Bittensor network connectivity
    3. Configuration validation
    4. Subnet metadata (slots, tempo, block)
    5. Environment variables status
    
    Use this to diagnose issues before running other commands.
    """
    checks_passed = 0
    checks_failed = 0
    checks_warning = 0
    
    results: list[dict[str, Any]] = []
    
    # Track subtensor connections for cleanup
    subtensor_connections: list[Any] = []
    
    try:
        # Check 1: Verifier connectivity
        console.print("\n[bold cyan]━━━ Health Check ━━━[/]")
        console.print()
        
        verifier_url = settings.verifier_url
        console.print(f"[bold]Checking verifier connectivity...[/]")
        console.print(f"[dim]URL: {verifier_url}[/]")
        
        verifier_ok = False
        verifier_status = "Unknown"
        verifier_latency_ms = None
        
        try:
            start_time = time.time()
            # Try to hit a simple endpoint (health or root)
            try:
                # Try /health endpoint first
                health_url = _build_url("/health")
                response = requests.get(health_url, timeout=(5, 10))
                if response.status_code == 200:
                    verifier_ok = True
                    verifier_status = "Healthy"
                elif response.status_code == 404:
                    # 404 is OK - means verifier is up but endpoint doesn't exist
                    # Try a simple GET request to verify connectivity
                    try:
                        _request("GET", "/v1/miner/status", params={"hotkey": "test", "slot": "0"}, retry=False)
                        verifier_ok = True
                        verifier_status = "Reachable (no /health endpoint)"
                    except VerifierError as exc:
                        # 404 or 400 means verifier is reachable, just wrong params
                        if exc.status_code in (400, 404):
                            verifier_ok = True
                            verifier_status = "Reachable"
                        else:
                            verifier_status = f"Error: {exc}"
                else:
                    verifier_status = f"HTTP {response.status_code}"
            except requests.RequestException as exc:
                # Connection error - verifier is not reachable
                verifier_status = f"Connection error: {exc}"
            except VerifierError as exc:
                # This shouldn't happen for /health, but handle it anyway
                if exc.status_code == 404:
                    verifier_ok = True
                    verifier_status = "Reachable (no /health endpoint)"
                else:
                    verifier_status = f"Error: {exc}"
            except Exception as exc:
                verifier_status = f"Error: {exc}"
            
            if verifier_ok:
                latency_ms = int((time.time() - start_time) * 1000)
                verifier_latency_ms = latency_ms
                console.print(f"[bold green]✓ Verifier is reachable[/] ({latency_ms}ms)")
                checks_passed += 1
            else:
                console.print(f"[bold red]✗ Verifier check failed[/]: {verifier_status}")
                checks_failed += 1
            
            results.append({
                "name": "Verifier Connectivity",
                "status": "pass" if verifier_ok else "fail",
                "details": verifier_status,
                "latency_ms": verifier_latency_ms,
            })
        except Exception as exc:
            console.print(f"[bold red]✗ Verifier check error[/]: {exc}")
            checks_failed += 1
            results.append({
                "name": "Verifier Connectivity",
                "status": "fail",
                "details": str(exc),
            })
        
        # Check 2: Bittensor network connectivity
        console.print()
        console.print(f"[bold]Checking Bittensor network...[/]")
        console.print(f"[dim]Network: {settings.network}, NetUID: {settings.netuid}[/]")
        
        bt_ok = False
        bt_status = "Unknown"
        bt_latency_ms = None
        bt_is_dns_error = False
    
        try:
            start_time = time.time()
            subtensor = bt.subtensor(network=settings.network)
            subtensor_connections.append(subtensor)
            current_block = subtensor.get_current_block()
            latency_ms = int((time.time() - start_time) * 1000)
            bt_latency_ms = latency_ms
            
            if current_block and current_block > 0:
                bt_ok = True
                bt_status = f"Connected (block: {current_block})"
                console.print(f"[bold green]✓ Bittensor network is reachable[/] ({latency_ms}ms, block: {current_block})")
                checks_passed += 1
            else:
                bt_status = "Connected but invalid block number"
                console.print(f"[bold yellow]⚠ Bittensor network check warning[/]: {bt_status}")
                checks_warning += 1
        except OSError as exc:
            # DNS resolution errors (Errno 8)
            error_str = str(exc)
            if "nodename nor servname provided" in error_str or "Errno 8" in error_str:
                bt_is_dns_error = True
                bt_status = "DNS resolution failed - cannot resolve Bittensor network endpoints"
                console.print(f"[bold yellow]⚠ Bittensor network check failed[/]: DNS resolution error")
                console.print("[dim]This usually indicates a network connectivity or DNS configuration issue.[/]")
                checks_warning += 1  # Make it a warning since verifier is working
            else:
                bt_status = f"Network error: {exc}"
                console.print(f"[bold red]✗ Bittensor network check failed[/]: {exc}")
                checks_failed += 1
        except Exception as exc:
            error_str = str(exc)
            # Check if it's a DNS/network related error
            if any(keyword in error_str.lower() for keyword in ["dns", "resolve", "nodename", "servname", "network", "connection"]):
                bt_is_dns_error = True
                bt_status = f"Network connectivity issue: {exc}"
                console.print(f"[bold yellow]⚠ Bittensor network check failed[/]: {exc}")
                console.print("[dim]This may be a temporary network issue. The CLI can still work if the verifier is accessible.[/]")
                checks_warning += 1
            else:
                bt_status = f"Error: {exc}"
                console.print(f"[bold red]✗ Bittensor network check failed[/]: {exc}")
                checks_failed += 1
        
        results.append({
            "name": "Bittensor Network",
            "status": "pass" if bt_ok else ("warning" if checks_warning > 0 else "fail"),
            "details": bt_status,
            "latency_ms": bt_latency_ms,
            "is_dns_error": bt_is_dns_error,
        })
        
        # Check 3: Configuration validation
        console.print()
        console.print(f"[bold]Checking configuration...[/]")
        
        config_issues: list[str] = []
        
        if not settings.verifier_url:
            config_issues.append("Verifier URL is not set")
        elif not settings.verifier_url.startswith(("http://", "https://")):
            config_issues.append("Verifier URL must start with http:// or https://")
        
        if not settings.network:
            config_issues.append("Network is not set")
        
        if settings.netuid <= 0:
            config_issues.append(f"Invalid netuid: {settings.netuid}")
        
        if config_issues:
            console.print(f"[bold yellow]⚠ Configuration issues found[/]:")
            for issue in config_issues:
                console.print(f"  • {issue}")
            checks_warning += 1
            config_status = "Issues found"
        else:
            console.print("[bold green]✓ Configuration is valid[/]")
            checks_passed += 1
            config_status = "Valid"
        
        results.append({
            "name": "Configuration",
            "status": "pass" if not config_issues else "warning",
            "details": config_status,
            "issues": config_issues if config_issues else None,
        })
        
        # Check 4: Subnet metadata
        console.print()
        console.print(f"[bold]Checking subnet metadata...[/]")
        console.print(f"[dim]NetUID: {settings.netuid}[/]")
        
        subnet_ok = False
        subnet_status = "Unknown"
        subnet_latency_ms = None
        subnet_info: dict[str, Any] = {}
        subnet_is_dns_error = False
    
        try:
            start_time = time.time()
            subtensor = bt.subtensor(network=settings.network)
            subtensor_connections.append(subtensor)
            metagraph = subtensor.metagraph(netuid=settings.netuid)
            metagraph.sync(subtensor=subtensor)
            latency_ms = int((time.time() - start_time) * 1000)
            subnet_latency_ms = latency_ms
            
            # Get subnet metadata
            total_miners = len(metagraph.neurons) if hasattr(metagraph, "neurons") else 0
            tempo = getattr(metagraph, "tempo", None)
            block = getattr(metagraph, "block", None)
            
            # Convert block to int if it's an array
            if hasattr(block, "__iter__") and not isinstance(block, (str, int)):
                try:
                    block = int(block[0]) if len(block) > 0 else None
                except (ValueError, TypeError, IndexError):
                    block = None
            
            subnet_info = {
                "total_slots": total_miners,
                "tempo": tempo,
                "block": block,
            }
            
            subnet_status_parts = []
            if total_miners > 0:
                subnet_status_parts.append(f"{total_miners} registered slots")
            if tempo is not None:
                subnet_status_parts.append(f"tempo: {tempo}")
            if block is not None:
                subnet_status_parts.append(f"block: {block}")
            
            subnet_status = ", ".join(subnet_status_parts) if subnet_status_parts else "Connected"
            subnet_ok = True
            
            console.print(f"[bold green]✓ Subnet metadata retrieved[/] ({latency_ms}ms)")
            if verbose:
                console.print(f"  • Registered slots: {total_miners}")
                if tempo is not None:
                    console.print(f"  • Tempo: {tempo}")
                if block is not None:
                    console.print(f"  • Block: {block}")
            checks_passed += 1
        except OSError as exc:
            # DNS resolution errors (Errno 8)
            error_str = str(exc)
            if "nodename nor servname provided" in error_str or "Errno 8" in error_str:
                subnet_is_dns_error = True
                subnet_status = "DNS resolution failed - cannot resolve Bittensor network endpoints"
                console.print(f"[bold yellow]⚠ Subnet metadata check failed[/]: DNS resolution error")
                checks_warning += 1  # Make it a warning since verifier is working
            else:
                subnet_status = f"Network error: {exc}"
                console.print(f"[bold red]✗ Subnet metadata check failed[/]: {exc}")
                checks_failed += 1
        except Exception as exc:
            error_str = str(exc)
            # Check if it's a DNS/network related error
            if any(keyword in error_str.lower() for keyword in ["dns", "resolve", "nodename", "servname", "network", "connection"]):
                subnet_is_dns_error = True
                subnet_status = f"Network connectivity issue: {exc}"
                console.print(f"[bold yellow]⚠ Subnet metadata check failed[/]: {exc}")
                checks_warning += 1
            else:
                subnet_status = f"Error: {exc}"
                console.print(f"[bold red]✗ Subnet metadata check failed[/]: {exc}")
                checks_failed += 1
        
        results.append({
            "name": "Subnet Metadata",
            "status": "pass" if subnet_ok else ("warning" if checks_warning > 0 else "fail"),
            "details": subnet_status,
            "latency_ms": subnet_latency_ms,
            "info": subnet_info if subnet_ok else None,
            "is_dns_error": subnet_is_dns_error,
        })
        
        # Check 5: Environment Variables
        console.print()
        console.print(f"[bold]Checking Environment Variables...[/]")
        
        env_vars_ok = True
        env_status = "OK"
        env_details: dict[str, dict[str, Any]] = {}
        
        # Get default values from Settings model
        default_settings = Settings()
        
        # Check each configurable env var
        env_var_mapping = {
            "CARTHA_VERIFIER_URL": ("verifier_url", default_settings.verifier_url),
            "CARTHA_NETWORK": ("network", default_settings.network),
            "CARTHA_NETUID": ("netuid", str(default_settings.netuid)),
            "CARTHA_EVM_PK": ("evm_private_key", None),  # Sensitive, don't show value
            "CARTHA_RETRY_MAX_ATTEMPTS": ("retry_max_attempts", str(default_settings.retry_max_attempts)),
            "CARTHA_RETRY_BACKOFF_FACTOR": ("retry_backoff_factor", str(default_settings.retry_backoff_factor)),
        }
        
        for env_var, (setting_key, default_value) in env_var_mapping.items():
            env_value = os.getenv(env_var)
            is_set = env_value is not None
            
            # For sensitive values, don't show the actual value
            display_value = "[REDACTED]" if env_var == "CARTHA_EVM_PK" and is_set else env_value
            
            env_details[env_var] = {
                "is_set": is_set,
                "value": display_value,
                "default": default_value,
                "source": "environment" if is_set else "default",
            }
        
        # Count how many are set vs defaults
        set_count = sum(1 for details in env_details.values() if details["is_set"])
        total_count = len(env_details)
        
        env_status = f"{set_count}/{total_count} Environment Variables set"
        
        console.print(f"[bold green]✓ Environment Variables checked[/] ({set_count}/{total_count} set)")
        if verbose:
            for env_var, details in env_details.items():
                source_indicator = "[green]●[/]" if details["is_set"] else "[dim]○[/]"
                console.print(f"  {source_indicator} {env_var}: {details['value'] or details['default']} ({details['source']})")
        
        checks_passed += 1
        
        results.append({
            "name": "Environment Variables",
            "status": "pass",
            "details": env_status,
            "info": env_details if verbose else None,
        })
        
        # Summary
        console.print()
        console.print("[bold cyan]━━━ Summary ━━━[/]")
        
        summary_table = Table(show_header=True, header_style="bold cyan")
        summary_table.add_column("Check", style="cyan")
        summary_table.add_column("Status", justify="center")
        summary_table.add_column("Details", style="dim")
        summary_table.add_column("Latency", justify="right", style="dim")
        
        for result in results:
            status_icon = {
                "pass": "[bold green]✓[/]",
                "warning": "[bold yellow]⚠[/]",
                "fail": "[bold red]✗[/]",
            }.get(result["status"], "?")
            
            latency_str = f"{result['latency_ms']}ms" if result.get("latency_ms") else "-"
            details = result["details"]
            if result.get("issues"):
                details += f" ({len(result['issues'])} issue(s))"
            
            summary_table.add_row(
                result["name"],
                status_icon,
                details,
                latency_str,
            )
        
        console.print(summary_table)
        console.print()
        
        # Overall status
        total_checks = checks_passed + checks_failed + checks_warning
        if checks_failed == 0 and checks_warning == 0:
            console.print("[bold green]✓ All checks passed![/] CLI is ready to use.")
            raise typer.Exit(code=0)
        elif checks_failed == 0:
            # Check if warnings are DNS-related
            dns_warnings = [r for r in results if r.get("is_dns_error") and r.get("status") == "warning"]
            if dns_warnings:
                console.print(
                    f"[bold yellow]⚠ {checks_warning} warning(s) found[/] (including DNS resolution issues). "
                    "CLI should work for most commands, but Bittensor network features may be limited."
                )
                console.print("[dim]If you need to register or check miner status, ensure Bittensor network connectivity.[/]")
            else:
                console.print(
                    f"[bold yellow]⚠ {checks_warning} warning(s) found[/], but CLI should work. "
                    "Review configuration if needed."
                )
            raise typer.Exit(code=0)
        else:
            console.print(
                f"[bold red]✗ {checks_failed} check(s) failed[/], {checks_warning} warning(s). "
                "Please fix issues before using the CLI."
            )
            if verbose:
                console.print("\n[bold]Troubleshooting:[/]")
                console.print("• Check your network connectivity")
                console.print(f"• Verify verifier URL: {settings.verifier_url}")
                console.print(f"• Verify Bittensor network: {settings.network}")
                console.print("• Check environment variables: CARTHA_VERIFIER_URL, CARTHA_NETWORK, CARTHA_NETUID")
                
                # Check if DNS errors occurred
                dns_errors = [r for r in results if r.get("is_dns_error")]
                if dns_errors:
                    console.print("\n[bold yellow]DNS Resolution Issues Detected:[/]")
                    console.print("The following checks failed due to DNS resolution errors:")
                    for result in dns_errors:
                        console.print(f"  • {result['name']}: {result['details']}")
                    console.print("\n[bold]DNS Troubleshooting Steps:[/]")
                    console.print("  1. Check your internet connection")
                    console.print("  2. Try flushing DNS cache:")
                    console.print("     • macOS: sudo dscacheutil -flushcache; sudo killall -HUP mDNSResponder")
                    console.print("     • Linux: sudo systemd-resolve --flush-caches (or sudo resolvectl flush-caches)")
                    console.print("     • Windows: ipconfig /flushdns")
                    console.print("  3. Check if you're behind a firewall or proxy")
                    console.print("  4. Try using a different network (e.g., mobile hotspot)")
                    console.print("  5. Check if DNS servers are reachable: nslookup <domain>")
                    console.print("\n[dim]Note: If the verifier check passed, you can still use most CLI commands.[/]")
                    console.print("[dim]Bittensor network connectivity is only needed for registration and status checks.[/]")
            raise typer.Exit(code=1)
    finally:
        # Clean up subtensor connections
        for subtensor in subtensor_connections:
            try:
                if hasattr(subtensor, "close"):
                    subtensor.close()
            except Exception:
                pass

