"""
CIViC (Clinical Interpretation of Variants in Cancer) connector.

CIViC is a community-curated knowledgebase for the clinical interpretation of variants
in cancer. Free, open API — no authentication required.
https://civicdb.org/api

Evidence types:
  - Predictive: Drug response (sensitivity, resistance)
  - Diagnostic: Diagnostic markers
  - Prognostic: Outcome association
  - Predisposing: Germline cancer risk

Evidence levels (A=highest, E=lowest):
  - A: Validated association (published large RCT or meta-analysis)
  - B: Clinical evidence (published case series or retrospective)
  - C: Case study (single case report)
  - D: Preclinical evidence
  - E: Inferential evidence (biological reasoning only)
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

import httpx

logger = logging.getLogger(__name__)

_CIVIC_API = "https://civicdb.org/api/graphql"


async def get_civic_evidence(gene: str, variant: str) -> Optional[Dict[str, Any]]:
    """
    Fetch CIViC evidence items for a gene variant.

    Args:
        gene:    HGNC gene symbol, e.g. "BRAF", "EGFR"
        variant: Protein change or descriptor, e.g. "V600E", "Exon 19 Deletion"

    Returns:
        Dict with 'evidence_items', 'civic_actionability_score', 'variant_id',
        'gene_id', 'predictive_evidence', 'diagnostic_evidence', or None on failure.
    """
    query = """
    query SearchVariant($gene: String!, $variant: String!) {
      genes(name: [$gene]) {
        nodes {
          id
          name
          variants {
            nodes {
              id
              name
              civicActionabilityScore
              evidenceItems {
                nodes {
                  id
                  status
                  evidenceType
                  evidenceLevel
                  evidenceDirection
                  significance
                  description
                  disease { name }
                  therapies { name }
                  source { citation pmid }
                }
              }
            }
          }
        }
      }
    }
    """

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(
                _CIVIC_API,
                json={"query": query, "variables": {"gene": gene, "variant": variant}},
                headers={"Accept": "application/json"},
            )
            response.raise_for_status()
            data = response.json()
    except Exception as exc:
        logger.warning("CIViC lookup failed for %s %s: %s", gene, variant, exc)
        return None

    return _parse_civic_response(data, variant)


def _parse_civic_response(data: dict, query_variant: str) -> Optional[Dict[str, Any]]:
    try:
        gene_nodes = data["data"]["genes"]["nodes"]
        if not gene_nodes:
            return None

        gene_node = gene_nodes[0]
        gene_id = gene_node["id"]

        # Find the closest matching variant
        best_variant = _find_best_variant(gene_node["variants"]["nodes"], query_variant)
        if not best_variant:
            return None

        variant_id = best_variant["id"]
        civic_score = best_variant.get("civicActionabilityScore", 0.0)

        # Collect accepted evidence items only
        evidence_items = []
        predictive = []
        diagnostic = []

        for ev in best_variant["evidenceItems"]["nodes"]:
            if ev.get("status") != "ACCEPTED":
                continue
            item = {
                "id": ev["id"],
                "type": ev.get("evidenceType"),
                "level": ev.get("evidenceLevel"),
                "direction": ev.get("evidenceDirection"),
                "significance": ev.get("significance"),
                "description": (ev.get("description", "") or "")[:200],
                "disease": ev.get("disease", {}).get("name") if ev.get("disease") else None,
                "therapies": [t["name"] for t in (ev.get("therapies") or [])],
                "pmid": ev.get("source", {}).get("pmid") if ev.get("source") else None,
            }
            evidence_items.append(item)
            if ev.get("evidenceType") == "PREDICTIVE":
                predictive.append(item)
            elif ev.get("evidenceType") == "DIAGNOSTIC":
                diagnostic.append(item)

        return {
            "gene_id": gene_id,
            "variant_id": variant_id,
            "variant_name": best_variant.get("name"),
            "civic_actionability_score": float(civic_score) if civic_score else 0.0,
            "evidence_items": evidence_items,
            "predictive_evidence": predictive,
            "diagnostic_evidence": diagnostic,
            "total_evidence_count": len(evidence_items),
        }

    except (KeyError, TypeError, IndexError) as exc:
        logger.debug("CIViC parse error: %s", exc)
        return None


def _find_best_variant(variants: List[dict], query: str) -> Optional[dict]:
    """Find the variant whose name best matches the query string."""
    query_lower = query.lower().replace("p.", "")
    best = None
    best_score = 0

    for v in variants:
        name = (v.get("name") or "").lower()
        # Exact match
        if name == query_lower:
            return v
        # Partial match scoring
        score = sum(1 for word in query_lower.split() if word in name)
        if score > best_score:
            best_score = score
            best = v

    return best if best_score > 0 else (variants[0] if variants else None)
