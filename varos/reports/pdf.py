"""PDF report generator using WeasyPrint + Jinja2."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from varos.models import ACMGClassification, ClassificationResult

TEMPLATES_DIR = Path(__file__).parent / "templates"


def _get_jinja_env() -> Environment:
    return Environment(
        loader=FileSystemLoader(str(TEMPLATES_DIR)),
        autoescape=select_autoescape(["html"]),
    )


def to_html(result: ClassificationResult) -> str:
    """Render the classification result as an HTML string."""
    env = _get_jinja_env()
    template = env.get_template("report.html.j2")
    return template.render(
        result=result,
        generated_at=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        ACMGClassification=ACMGClassification,
    )


def save_html(result: ClassificationResult, output_path: Path | str) -> Path:
    output_path = Path(output_path)
    output_path.write_text(to_html(result), encoding="utf-8")
    return output_path


def save_pdf(result: ClassificationResult, output_path: Path | str) -> Path:
    """Render and save a PDF report. Requires WeasyPrint."""
    try:
        from weasyprint import HTML
    except ImportError:
        raise RuntimeError(
            "WeasyPrint is required for PDF output. "
            "Install with: pip install weasyprint"
        )
    output_path = Path(output_path)
    html_content = to_html(result)
    HTML(string=html_content).write_pdf(str(output_path))
    return output_path
