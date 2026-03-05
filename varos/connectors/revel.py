"""
REVEL (Rare Exome Variant Ensemble Learner) connector.

REVEL is an ensemble method for predicting the pathogenicity of missense variants.
Scores range from 0 (benign) to 1 (pathogenic).

Data source: Pre-computed scores from https://sites.google.com/site/revelgenomics/
API wrapper: Uses the dbNSFP-style REST endpoint via Ensembl's REST API for SNVs.

ACMG evidence mapping (per ClinGen Sequence Variant Interpretation Working Group):
  - REVEL >= 0.932: PP3 strong
  - REVEL >= 0.773: PP3 moderate
  - REVEL >= 0.644: PP3 supporting
  - REVEL <= 0.183: BP4 supporting
  - REVEL <= 0.016: BP4 moderate

Note: REVEL only scores missense variants (amino acid change). For other variant types,
returns None and CADD/AlphaMissense should be used instead.
"""

from __future__ import annotations

import logging
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

# Ensembl VEP endpoint with REVEL plugin (grch38)
_VEP_ENDPOINT = "https://rest.ensembl.org/vep/human/hgvs"

# ClinGen SVI-calibrated REVEL thresholds
REVEL_PP3_STRONG = 0.932
REVEL_PP3_MODERATE = 0.773
REVEL_PP3_SUPPORTING = 0.644
REVEL_BP4_SUPPORTING = 0.183
REVEL_BP4_MODERATE = 0.016


async def get_revel_score(hgvs: str) -> Optional[dict]:
    """
    Fetch REVEL score for a missense variant via Ensembl VEP REST API.

    Args:
        hgvs: HGVS notation, e.g. "NM_007294.4:c.5266dupC" or "17:g.43044295A>G"

    Returns:
        Dict with 'score', 'pp3', 'bp4', 'strength', 'interpretation', or None on failure.
        Returns None for non-missense variants (REVEL only scores amino acid changes).
    """
    url = f"{_VEP_ENDPOINT}/{hgvs}"
    headers = {"Content-Type": "application/json", "Accept": "application/json"}

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.get(
                url,
                headers=headers,
                params={"REVEL": 1, "content-type": "application/json"},
            )
            response.raise_for_status()
            data = response.json()
    except Exception as exc:
        logger.warning("REVEL (via VEP) lookup failed for %s: %s", hgvs, exc)
        return None

    # Extract REVEL score from VEP response
    revel_score = _extract_revel(data)
    if revel_score is None:
        return None

    return {
        "score": revel_score,
        "pp3": revel_score >= REVEL_PP3_SUPPORTING,
        "bp4": revel_score <= REVEL_BP4_SUPPORTING,
        "strength": _strength(revel_score),
        "interpretation": _interpret(revel_score),
    }


def _extract_revel(vep_data: list) -> Optional[float]:
    """Walk VEP response JSON to find the REVEL score."""
    if not vep_data or not isinstance(vep_data, list):
        return None
    for consequence in vep_data:
        for tc in consequence.get("transcript_consequences", []):
            revel = tc.get("revel_score")
            if revel is not None:
                return float(revel)
    return None


def _strength(score: float) -> str:
    if score >= REVEL_PP3_STRONG:
        return "strong"
    if score >= REVEL_PP3_MODERATE:
        return "moderate"
    if score >= REVEL_PP3_SUPPORTING:
        return "supporting"
    if score <= REVEL_BP4_MODERATE:
        return "moderate_benign"
    if score <= REVEL_BP4_SUPPORTING:
        return "supporting_benign"
    return "indeterminate"


def _interpret(score: float) -> str:
    if score >= REVEL_PP3_STRONG:
        return "likely_pathogenic"
    if score >= REVEL_PP3_SUPPORTING:
        return "possibly_pathogenic"
    if score <= REVEL_BP4_SUPPORTING:
        return "possibly_benign"
    return "uncertain"
