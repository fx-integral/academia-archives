import socket
import subprocess
import time
from pathlib import Path

import httpx
from rich.console import Console

console = Console()

GATEWAY_PORT = 8000
GATEWAY_URL = f"http://localhost:{GATEWAY_PORT}"
GATEWAY_LOG_FILE = Path("gateway.log")


def is_port_in_use(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(1)
        return s.connect_ex(("localhost", port)) == 0


def check_gateway_health() -> bool:
    try:
        response = httpx.get(f"{GATEWAY_URL}/api/health", timeout=2.0)
        return response.status_code == 200
    except Exception:
        return False


def get_gateway_pid() -> int | None:
    try:
        result = subprocess.run(
            ["pgrep", "-f", "neurons.miner.gateway.app"],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0 and result.stdout.strip():
            return int(result.stdout.strip().split()[0])
    except Exception:
        pass
    return None


def get_port_pid(port: int) -> int | None:
    try:
        result = subprocess.run(
            ["lsof", "-ti", f"tcp:{port}"],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0 and result.stdout.strip():
            return int(result.stdout.strip().split()[0])
    except Exception:
        pass
    return None


def _kill_pid(pid: int) -> bool:
    try:
        subprocess.run(["kill", str(pid)], check=True)
        time.sleep(1)
        return True
    except Exception:
        return False


def kill_port(port: int) -> bool:
    pid = get_port_pid(port)
    if not pid:
        return False
    return _kill_pid(pid)


def stop_gateway() -> bool:
    pid = get_gateway_pid()
    if not pid:
        return False
    return _kill_pid(pid)


def start_gateway() -> tuple[bool, int | None, Path | None]:
    if is_port_in_use(GATEWAY_PORT):
        console.print(f" [red]✗[/red] Port {GATEWAY_PORT} is already in use by another process.")
        console.print(
            f"  [dim]Run [cyan]numi gateway stop[/cyan] or check what is using port {GATEWAY_PORT}.[/dim]"
        )
        return False, None, None

    try:
        log_handle = open(GATEWAY_LOG_FILE, "a")

        process = subprocess.Popen(
            [
                "python",
                "-m",
                "uvicorn",
                "neurons.miner.gateway.app:app",
                "--host",
                "0.0.0.0",
                "--port",
                str(GATEWAY_PORT),
            ],
            stdout=log_handle,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )

        console.print("  [cyan]Starting gateway...[/cyan]", end="")
        for _ in range(10):
            time.sleep(0.5)
            if check_gateway_health():
                console.print(" [green]✓[/green]")
                return True, process.pid, GATEWAY_LOG_FILE
            console.print(".", end="")

        console.print(" [red]✗[/red]")
        log_handle.close()
        return False, None, None

    except Exception as e:
        console.print(f" [red]✗[/red] Error: {e}")
        return False, None, None


def show_gateway_status() -> None:
    console.print()
    console.print("[cyan]🌐 Gateway Status[/cyan]")
    console.print()

    is_healthy = check_gateway_health()
    pid = get_gateway_pid()

    if is_healthy and pid:
        console.print("  [green]✓[/green] Running")
        console.print(f"  [dim]URL:[/dim] {GATEWAY_URL}")
        console.print(f"  [dim]PID:[/dim] {pid}")
        console.print(f"  [dim]Logs:[/dim] {GATEWAY_LOG_FILE.absolute()}")
        console.print()
        console.print("  [yellow]📋 View logs:[/yellow] [cyan]numi gateway logs[/cyan]")
        console.print("  [yellow]🛑 Stop:[/yellow] [cyan]numi gateway stop[/cyan]")
    elif pid:
        console.print("  [yellow]⚠[/yellow] Process running but not responding")
        console.print(f"  [dim]PID:[/dim] {pid}")
        console.print()
        console.print("  [yellow]🛑 Stop:[/yellow] [cyan]numi gateway stop[/cyan]")
    else:
        console.print("  [red]✗[/red] Not running")
        console.print()
        console.print("  [yellow]🚀 Start:[/yellow] [cyan]numi gateway start[/cyan]")

    console.print()


def tail_logs(follow: bool = True) -> None:
    if not GATEWAY_LOG_FILE.exists():
        console.print()
        console.print(f"[yellow]⚠ Log file not found: {GATEWAY_LOG_FILE}[/yellow]")
        console.print()
        return

    try:
        if follow:
            subprocess.run(["tail", "-f", str(GATEWAY_LOG_FILE)])
        else:
            subprocess.run(["tail", "-n", "50", str(GATEWAY_LOG_FILE)])
    except KeyboardInterrupt:
        console.print()
        console.print("[dim]Log viewing stopped[/dim]")
        console.print()
    except Exception as e:
        console.print()
        console.print(f"[red]✗ Error viewing logs: {e}[/red]")
        console.print()
