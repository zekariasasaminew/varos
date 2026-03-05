"""VAROS CLI — main Typer application."""

from __future__ import annotations

import typer
from rich.console import Console

app = typer.Typer(
    name="varos",
    help="[bold blue]VAROS[/] — Variant Autonomous Reclassification & Observation System\n\n"
         "Classify genetic variants using ACMG/AMP guidelines + AI evidence synthesis.",
    rich_markup_mode="rich",
    no_args_is_help=True,
    pretty_exceptions_enable=True,
)
console = Console()

# Import sub-commands
from varos.cli.classify import classify_cmd  # noqa: E402
from varos.cli.analyze import analyze_cmd    # noqa: E402
from varos.cli.watch import watch_app        # noqa: E402

app.command(name="classify", help="Classify a single variant")(classify_cmd)
app.command(name="analyze", help="Analyze all variants in a VCF file")(analyze_cmd)
app.add_typer(watch_app, name="watch")


@app.command(name="setup", help="Download required databases (AlphaMissense, etc.)")
def setup_cmd(
    alphamissense: bool = typer.Option(True, "--alphamissense/--no-alphamissense", help="Download AlphaMissense v1 (~3.5 GB)"),
) -> None:
    """Download and index required databases for offline use."""
    console.print("[bold blue]VAROS Setup[/]")
    if alphamissense:
        from varos.connectors.alphamissense import download_and_index, is_indexed
        if is_indexed():
            console.print("[green]✓ AlphaMissense already indexed[/]")
        else:
            console.print("Downloading AlphaMissense v1 (~3.5 GB)...")
            download_and_index()
            console.print("[green]✓ AlphaMissense indexed[/]")


@app.command(name="serve", help="Start the VAROS API server")
def serve_cmd(
    host: str = typer.Option("0.0.0.0", "--host", help="Bind host"),
    port: int = typer.Option(8000, "--port", "-p", help="Bind port"),
    reload: bool = typer.Option(False, "--reload", help="Auto-reload on code changes (dev only)"),
    workers: int = typer.Option(1, "--workers", help="Number of worker processes"),
) -> None:
    """Start the VAROS REST API server (uvicorn)."""
    import uvicorn
    console.print(f"[bold blue]VAROS API[/] starting on [green]http://{host}:{port}[/]")
    uvicorn.run(
        "varos.api.app:app",
        host=host,
        port=port,
        reload=reload,
        workers=workers if not reload else 1,
    )


def version_cmd() -> None:
    from varos import __version__
    console.print(f"[bold]VAROS[/] v{__version__}")


if __name__ == "__main__":
    app()
