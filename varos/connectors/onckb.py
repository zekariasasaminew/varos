"""
OncoKB connector — FDA-approved therapies and oncogenic variant tiers.

OncoKB is a precision oncology knowledge base curated by Memorial Sloan Kettering.
Free API for academic/research use (requires free registration for API token).
https://www.oncokb.org/api-access

OncoKB Levels of Evidence:
  - LEVEL_1:  FDA-recognized biomarker, same tumor type
  - LEVEL_2:  Standard care biomarker, same tumor type
  - LEVEL_3A: Compelling clinical evidence, same tumor type
  - LEVEL_3B: Clinical evidence, different tumor type
  - LEVEL_4:  Biological evidence
  - LEVEL_R1: Standard care resistance, FDA-recognized
  - LEVEL_R2: Resistance biomarker, clinical evidence

Set ONCKB_API_TOKEN in .env (free for research at oncokb.org).
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

import httpx

from varos.config import settings

logger = logging.getLogger(__name__)

_ONCKB_API = "https://www.oncokb.org/api/v1"

# OncoKB actionability levels that map to AMP/ASCO/CAP Tier I
TIER_I_LEVELS = {"LEVEL_1", "LEVEL_R1", "LEVEL_2"}
# Maps to Tier II
TIER_II_LEVELS = {"LEVEL_3A", "LEVEL_3B", "LEVEL_4", "LEVEL_R2"}


async def get_onckb_annotation(
    gene: str,
    variant: str,
    tumor_type: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """
    Fetch OncoKB annotation for a somatic variant.

    Args:
        gene:       HGNC gene symbol, e.g. "BRAF", "EGFR"
        variant:    Protein change or HGVS, e.g. "V600E" or "p.Val600Glu"
        tumor_type: OncoKB tumor type code, e.g. "NSCLC", "BREAST" (optional)

    Returns:
        Dict with 'oncogenic', 'highestSensitiveLevel', 'highestResistanceLevel',
        'geneRole', 'treatments', or None on failure/unavailable.
    """
    api_token = getattr(settings, "onckb_api_token", None)
    if not api_token:
        logger.debug("ONCKB_API_TOKEN not set — OncoKB lookup skipped for %s %s", gene, variant)
        return None

    # Normalize protein change (remove "p." prefix if present)
    protein_change = variant.replace("p.", "").replace("(", "").replace(")", "")

    url = f"{_ONCKB_API}/annotate/mutations/byProteinChange"
    params: Dict[str, Any] = {
        "hugoSymbol": gene,
        "alteration": protein_change,
        "referenceGenome": "GRCh38",
    }
    if tumor_type:
        params["tumorType"] = tumor_type

    headers = {
        "Authorization": f"Bearer {api_token}",
        "Accept": "application/json",
    }

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(url, params=params, headers=headers)
            response.raise_for_status()
            data = response.json()
    except Exception as exc:
        logger.warning("OncoKB lookup failed for %s %s: %s", gene, variant, exc)
        return None

    return _parse_annotation(data)


def _parse_annotation(data: Dict[str, Any]) -> Dict[str, Any]:
    """Extract clinically relevant fields from OncoKB annotation response."""
    query = data.get("query", {})
    oncogenic = data.get("oncogenic", "Unknown")
    highest_sensitive = data.get("highestSensitiveLevel")
    highest_resistance = data.get("highestResistanceLevel")
    gene_summary = data.get("geneSummary", "")
    variant_summary = data.get("variantSummary", "")
    tumor_summary = data.get("tumorTypeSummary", "")

    # Extract treatment list
    treatments: List[Dict[str, Any]] = []
    for treatment in data.get("treatments", []):
        drugs = treatment.get("drugs", [])
        treatments.append({
            "level": treatment.get("level"),
            "drugs": [d.get("drugName", "") for d in drugs],
            "pmids": treatment.get("pmids", []),
            "abstracts": treatment.get("abstracts", []),
            "tumor_type": treatment.get("levelAssociatedCancerType", {}).get("mainType", {}).get("name"),
        })

    # Gene role (oncogene, TSG, both)
    gene_info = data.get("geneExist", False)
    gene_role = query.get("hugoSymbol", "")

    return {
        "oncogenic": oncogenic,
        "highestSensitiveLevel": highest_sensitive,
        "highestResistanceLevel": highest_resistance,
        "geneRole": gene_role,
        "treatments": treatments,
        "gene_summary": gene_summary[:300] if gene_summary else "",
        "variant_summary": variant_summary[:300] if variant_summary else "",
        "tumor_summary": tumor_summary[:300] if tumor_summary else "",
        "is_tier_i": highest_sensitive in TIER_I_LEVELS,
        "is_tier_ii": highest_sensitive in TIER_II_LEVELS,
    }
