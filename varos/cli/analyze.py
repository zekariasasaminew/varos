"""varos analyze — batch analyze all variants in a VCF file."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, BarColumn, TaskProgressColumn, TextColumn

from varos.models import VariantInput

console = Console()


def analyze_cmd(
    vcf: Path = typer.Argument(..., exists=True, help="Input VCF file"),
    output_dir: Path = typer.Option(Path("./varos_reports"), "--output", "-o", help="Output directory for reports"),
    panel: str = typer.Option("all", "--panel", "-p", help="Gene panel: all | hereditary_cancer | cardio | neuro"),
    format: str = typer.Option("pdf", "--format", "-f", help="Output format: pdf | html | json"),
    max_variants: int = typer.Option(0, "--max", help="Limit number of variants (0 = all)"),
    parallel: int = typer.Option(4, "--parallel", help="Number of parallel classifications"),
) -> None:
    """Analyze all variants in a VCF file and generate reports."""
    asyncio.run(_analyze_async(vcf, output_dir, panel, format, max_variants, parallel))


GENE_PANELS = {
    "hereditary_cancer": {
        "BRCA1", "BRCA2", "MLH1", "MSH2", "MSH6", "PMS2", "EPCAM",
        "TP53", "PTEN", "APC", "SMAD4", "BMPR1A", "STK11", "CDH1",
        "PALB2", "ATM", "CHEK2", "BARD1", "RAD51C", "RAD51D",
    },
    "cardio": {
        "MYBPC3", "MYH7", "TNNT2", "TNNI3", "MYL2", "MYL3", "ACTC1",
        "TPM1", "SCN5A", "KCNQ1", "KCNH2", "KCNE1", "KCNE2", "RYR2",
    },
    "neuro": {
        "LRRK2", "PARK7", "PINK1", "PRKN", "SNCA", "APP", "PSEN1",
        "PSEN2", "MAPT", "GBA", "ATP7B", "NOTCH3",
    },
}


def _parse_vcf_variants(vcf_path: Path, panel: str, max_variants: int) -> list[VariantInput]:
    """Parse a VCF file and extract variants (HGVS-like format from INFO fields or best effort)."""
    variants: list[VariantInput] = []
    panel_genes = GENE_PANELS.get(panel, None)  # None = all genes

    with open(vcf_path) as f:
        for line in f:
            if line.startswith("#"):
                continue
            parts = line.strip().split("\t")
            if len(parts) < 5:
                continue
            chrom, pos, _id, ref, alt = parts[0], parts[1], parts[2], parts[3], parts[4]
            # Skip multi-allelic sites for now (take first alt)
            first_alt = alt.split(",")[0]
            # Build a genomic notation
            hgvs = f"{chrom}:g.{pos}{ref}>{first_alt}"
            variants.append(VariantInput(hgvs=hgvs, free_text=line.strip()))
            if max_variants and len(variants) >= max_variants:
                break

    return variants


async def _analyze_async(
    vcf: Path,
    output_dir: Path,
    panel: str,
    fmt: str,
    max_variants: int,
    parallel: int,
) -> None:
    from varos.agents.orchestrator import run_classification
    from varos.reports.pdf import save_pdf, save_html
    from varos.reports.json_report import save_json

    output_dir.mkdir(parents=True, exist_ok=True)
    variants = _parse_vcf_variants(vcf, panel, max_variants)
    console.print(f"[bold blue]VAROS Batch Analysis[/] — {len(variants)} variants from [cyan]{vcf.name}[/]")

    sem = asyncio.Semaphore(parallel)
    results = []

    async def classify_one(vi: VariantInput, idx: int) -> tuple[int, object]:
        async with sem:
            result = await run_classification(vi)
            return idx, result

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        console=console,
    ) as progress:
        task = progress.add_task("Classifying...", total=len(variants))
        tasks = [asyncio.create_task(classify_one(v, i)) for i, v in enumerate(variants)]
        for coro in asyncio.as_completed(tasks):
            idx, result = await coro
            results.append((idx, result))
            progress.advance(task)

    # Save reports
    results.sort(key=lambda x: x[0])
    saved = 0
    for _idx, result in results:
        safe_name = (result.variant.hgvs_cdna or "variant").replace(":", "_").replace(">", "_").replace("/", "_")[:60]
        out_path = output_dir / f"{safe_name}.{fmt}"
        if fmt == "pdf":
            save_pdf(result, out_path)
        elif fmt == "html":
            save_html(result, out_path)
        else:
            save_json(result, out_path)
        saved += 1

    console.print(f"\n[green]✓[/] {saved} reports saved to [bold]{output_dir}[/]")
