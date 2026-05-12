from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt

from neurons.validator.models.track import TrackEnum
from neurons.validator.sandbox.signing_proxy.track_config import TRACK_ALLOWED_PREFIXES

console = Console()

TRACK_CHOICES = [track.value for track in TrackEnum]
DEFAULT_TRACK = TrackEnum.MAIN.value


def prompt_track_selection(
    show_allowlist: bool = True,
    show_credential_fallback: bool = False,
) -> str:
    if show_credential_fallback:
        console.print()
        console.print(
            "[dim]Credentials linked for MAIN are used as fallback for all tracks.\n"
            "Only link for a specific track if you want separate API keys.[/dim]"
        )

    console.print()
    track = Prompt.ask(
        "[bold cyan]Select track[/bold cyan]",
        choices=TRACK_CHOICES,
        default=DEFAULT_TRACK,
    )

    if show_allowlist and track != TrackEnum.MAIN.value:
        allowed = TRACK_ALLOWED_PREFIXES.get(track, [])
        allowed_display = "\n".join(f"  • [cyan]{prefix}[/cyan]" for prefix in allowed)
        console.print()
        console.print(
            Panel.fit(
                f"[yellow]Track {track} — Allowed gateway endpoints:[/yellow]\n\n"
                f"{allowed_display}\n\n"
                "[dim]Your agent will get 403 for any other endpoint.[/dim]",
                border_style="yellow",
            )
        )

    return track
