"""
CADD (Combined Annotation Dependent Depletion) connector.

CADD v1.7 REST API — free, no authentication required.
https://cadd.gs.washington.edu/score

CADD scores deleteriousness of SNVs and short indels:
  - Raw score: unscaled Phred-like score
  - PHRED score: -10 * log10(rank/total) — values above 20 = top 1%, above 30 = top 0.1%

ACMG evidence mapping:
  - PHRED ≥ 20: PP3 supporting (computational evidence of pathogenicity)
  - PHRED ≥ 25: PP3 moderate (commonly used threshold in literature)
  - PHRED ≤ 10: BP4 supporting (benign computational evidence)

Note: CADD should be combined with other predictors (REVEL, AlphaMissense) for robust PP3/BP4.
"""

from __future__ import annotations

import logging
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

_CADD_API = "https://cadd.gs.washington.edu/api/v1.0"

# PHRED thresholds per ClinGen SVI recommendations
PHRED_PATHOGENIC_SUPPORTING = 20.0
PHRED_PATHOGENIC_MODERATE = 25.0
PHRED_BENIGN_SUPPORTING = 10.0


async def get_cadd_score(chrom: str, pos: int, ref: str, alt: str) -> Optional[dict]:
    """
    Fetch CADD PHRED score for a single variant.

    Args:
        chrom: Chromosome without 'chr' prefix, e.g. "17"
        pos:   1-based genomic position
        ref:   Reference allele
        alt:   Alternate allele

    Returns:
        Dict with 'phred', 'raw_score', 'pp3', 'bp4' keys, or None on failure.
    """
    # CADD uses GRCh38 by default; variant must be in chr:pos:ref:alt format
    variant_str = f"{chrom}_{pos}_{ref}_{alt}"
    url = f"{_CADD_API}/grch38/{variant_str}"

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(url, headers={"Accept": "application/json"})
            response.raise_for_status()
            data = response.json()
    except Exception as exc:
        logger.warning("CADD lookup failed for %s: %s", variant_str, exc)
        return None

    # CADD returns a list of scored annotations; take the highest PHRED
    if not data or not isinstance(data, list):
        return None

    phred_scores = [item.get("PHRED") for item in data if item.get("PHRED") is not None]
    if not phred_scores:
        return None

    phred = max(float(p) for p in phred_scores)
    raw = max(float(item.get("RawScore", 0)) for item in data if item.get("RawScore") is not None)

    return {
        "phred": phred,
        "raw_score": raw,
        "pp3": phred >= PHRED_PATHOGENIC_SUPPORTING,
        "pp3_moderate": phred >= PHRED_PATHOGENIC_MODERATE,
        "bp4": phred <= PHRED_BENIGN_SUPPORTING,
        "interpretation": _interpret(phred),
    }


def _interpret(phred: float) -> str:
    if phred >= PHRED_PATHOGENIC_MODERATE:
        return "likely_deleterious"
    if phred >= PHRED_PATHOGENIC_SUPPORTING:
        return "possibly_deleterious"
    if phred <= PHRED_BENIGN_SUPPORTING:
        return "likely_benign"
    return "uncertain"
