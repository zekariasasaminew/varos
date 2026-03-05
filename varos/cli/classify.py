"""varos classify — classify a single variant."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.table import Table
from rich import box

from varos.models import ACMGClassification, VariantInput

console = Console()

# ANSI color map for classification
CLASSIFICATION_STYLES = {
    ACMGClassification.PATHOGENIC: "bold red",
    ACMGClassification.LIKELY_PATHOGENIC: "bold orange3",
    ACMGClassification.VUS: "bold yellow",
    ACMGClassification.LIKELY_BENIGN: "bold cyan",
    ACMGClassification.BENIGN: "bold green",
}


def classify_cmd(
    variant: str = typer.Argument(..., help="Variant in HGVS, rsID, or 'GENE:p.XXX' format"),
    output: Optional[Path] = typer.Option(None, "--output", "-o", help="Output file path (.pdf, .html, or .json)"),
    genome_build: str = typer.Option("GRCh38", "--build", "-b", help="Genome build: GRCh38 or GRCh37"),
    audience: str = typer.Option("clinician", "--audience", "-a", help="Report audience: clinician | patient | researcher"),
    no_llm: bool = typer.Option(False, "--no-llm", help="Skip LLM reasoning (faster, offline)"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Show all evaluated criteria"),
) -> None:
    """Classify a single genetic variant using ACMG/AMP 2015 guidelines."""
    asyncio.run(_classify_async(variant, output, genome_build, audience, no_llm, verbose))


async def _classify_async(
    variant: str,
    output: Optional[Path],
    genome_build: str,
    audience: str,
    no_llm: bool,
    verbose: bool,
) -> None:
    from varos.agents.orchestrator import run_classification
    from varos.config import settings

    vi = VariantInput(hgvs=variant, genome_build=genome_build)

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
        transient=True,
    ) as progress:
        progress.add_task(f"Classifying [bold cyan]{variant}[/] ...", total=None)
        try:
            result = await run_classification(vi)
        except Exception as e:
            console.print(f"[red]Error:[/] {e}")
            raise typer.Exit(1)

    # --- Terminal output ---
    style = CLASSIFICATION_STYLES.get(result.classification, "white")
    classification_line = f"[{style}]{result.classification.value}[/]"

    console.print()
    console.print(Panel(
        f"[bold]{result.variant.hgvs_cdna}[/]\n"
        f"Gene: [bold]{result.variant.gene_symbol}[/]  |  Type: {result.variant.variant_type or 'unknown'}\n\n"
        f"Classification:  {classification_line}\n"
        f"Confidence:      {result.confidence}/100\n"
        f"Criteria met:    {len(result.criteria_triggered)} triggered",
        title="[bold blue]VAROS Classification Result[/]",
        border_style="blue",
    ))

    # Triggered criteria table
    if result.criteria_triggered:
        table = Table(title="Triggered ACMG Criteria", box=box.SIMPLE, show_lines=False)
        table.add_column("Code", style="bold", width=8)
        table.add_column("Direction", width=12)
        table.add_column("Strength", width=14)
        table.add_column("Evidence", overflow="fold")
        for c in result.criteria_triggered:
            dir_style = "red" if c.direction.value == "pathogenic" else "green"
            table.add_row(
                c.code,
                f"[{dir_style}]{c.direction.value}[/]",
                c.applied_strength.value.replace("_", " "),
                c.evidence_text[:120] + ("..." if len(c.evidence_text) > 120 else ""),
            )
        console.print(table)

    # Verbose: all criteria
    if verbose and result.criteria_evaluated:
        table2 = Table(title="All Evaluated Criteria", box=box.SIMPLE)
        table2.add_column("Code", width=8)
        table2.add_column("Triggered", width=10)
        table2.add_column("Evidence", overflow="fold")
        for c in result.criteria_evaluated:
            table2.add_row(
                c.code,
                "[green]✓[/]" if c.triggered else "[dim]✗[/]",
                c.evidence_text[:100] + ("..." if len(c.evidence_text) > 100 else ""),
            )
        console.print(table2)

    # LLM summary
    if result.llm_summary:
        console.print(Panel(result.llm_summary, title="Evidence Summary", border_style="dim"))
    if audience == "patient" and result.llm_patient_note:
        console.print(Panel(result.llm_patient_note, title="Patient Explanation", border_style="cyan"))

    # Warnings
    for warning in result.warnings:
        console.print(f"[yellow]⚠[/] {warning}")

    # Save output
    if output:
        _save_output(result, output)
        console.print(f"\n[green]✓[/] Report saved to [bold]{output}[/]")


def _save_output(result, output: Path) -> None:
    suffix = output.suffix.lower()
    if suffix == ".json":
        from varos.reports.json_report import save_json
        save_json(result, output)
    elif suffix == ".html":
        from varos.reports.pdf import save_html
        save_html(result, output)
    elif suffix == ".pdf":
        from varos.reports.pdf import save_pdf
        save_pdf(result, output)
    else:
        # Default to JSON
        from varos.reports.json_report import save_json
        save_json(result, output.with_suffix(".json"))
