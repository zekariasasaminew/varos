"""varos watch — monitor variants for evidence changes."""

from __future__ import annotations

import typer
from rich.console import Console
from rich.table import Table
from rich import box

watch_app = typer.Typer(help="Monitor variants for evidence updates")
console = Console()


@watch_app.command(name="add")
def watch_add(
    variant: str = typer.Argument(..., help="Variant to watch (HGVS notation)"),
    email: str = typer.Option(..., "--email", "-e", help="Email for alerts"),
    label: str = typer.Option("", "--label", "-l", help="Optional label for this watch"),
) -> None:
    """Add a variant to the watch list."""
    from varos.daemon.scheduler import add_watch
    watch_id = add_watch(variant, email, label)
    console.print(f"[green]✓[/] Watching [bold cyan]{variant}[/] (ID: {watch_id})")
    console.print(f"  Alerts will be sent to: [bold]{email}[/]")
    console.print(f"  Run [bold]varos watch status[/] to see all watched variants.")


@watch_app.command(name="status")
def watch_status() -> None:
    """Show all watched variants and their current classifications."""
    from varos.daemon.scheduler import list_watches
    watches = list_watches()

    if not watches:
        console.print("[dim]No variants being watched. Use [bold]varos watch add[/] to start.[/]")
        return

    table = Table(title="Watched Variants", box=box.ROUNDED)
    table.add_column("ID", width=8)
    table.add_column("Variant", style="cyan")
    table.add_column("Classification")
    table.add_column("Last Checked")
    table.add_column("Alert Email")

    for w in watches:
        table.add_row(
            str(w.get("id", "")),
            w.get("variant", ""),
            w.get("last_classification", "Not yet classified"),
            w.get("last_checked", "Never"),
            w.get("email", ""),
        )
    console.print(table)


@watch_app.command(name="remove")
def watch_remove(
    watch_id: int = typer.Argument(..., help="Watch ID to remove"),
) -> None:
    """Remove a variant from the watch list."""
    from varos.daemon.scheduler import remove_watch
    remove_watch(watch_id)
    console.print(f"[green]✓[/] Removed watch ID {watch_id}")


@watch_app.command(name="start-daemon")
def daemon_start(
    interval_hours: int = typer.Option(24, "--interval", help="Check interval in hours"),
    background: bool = typer.Option(False, "--background", "-b", help="Run as background process"),
) -> None:
    """Start the monitoring daemon to check for evidence updates."""
    from varos.daemon.scheduler import start_daemon
    console.print(f"[bold blue]Starting VAROS daemon[/] (interval: every {interval_hours}h)")
    start_daemon(interval_hours=interval_hours, background=background)
