"""JSON report output — structured, pipeline-friendly."""

from __future__ import annotations

import json
from pathlib import Path

from varos.models import ClassificationResult


def to_json(result: ClassificationResult, indent: int = 2) -> str:
    """Serialize a ClassificationResult to a JSON string."""
    return result.model_dump_json(indent=indent)


def save_json(result: ClassificationResult, output_path: Path | str) -> Path:
    output_path = Path(output_path)
    output_path.write_text(to_json(result), encoding="utf-8")
    return output_path
