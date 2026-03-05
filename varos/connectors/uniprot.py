"""
UniProt protein domain connector.

UniProt provides curated protein domain annotations used for:
  - PM1: Variant located in a mutational hot spot and/or critical functional domain
         with no benign variation
  - PP2: Missense in gene where missense variants are a common disease mechanism

Uses the free UniProt REST API (no authentication required).
https://www.uniprot.org/help/api

Maps HGNC gene symbol -> UniProt canonical accession -> protein features:
  - Active sites, binding sites, transmembrane regions
  - Annotated pathogenic missense positions
  - Domain boundaries for PM1 scoring
"""

from __future__ import annotations

import logging
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

_UNIPROT_API = "https://rest.uniprot.org/uniprotkb"


async def get_protein_domains(gene_symbol: str) -> Optional[dict]:
    """
    Fetch protein domain and functional site annotations from UniProt.

    Args:
        gene_symbol: HGNC gene symbol, e.g. "BRCA1", "TP53"

    Returns:
        Dict with 'accession', 'protein_name', 'domains', 'active_sites',
        'binding_sites', 'total_features', 'pm1_relevant_features', or None on failure.
    """
    try:
        accession = await _search_accession(gene_symbol)
        if not accession:
            return None
        return await _fetch_features(gene_symbol, accession)
    except Exception as exc:
        logger.warning("UniProt lookup failed for %s: %s", gene_symbol, exc)
        return None


async def is_in_functional_domain(gene_symbol: str, protein_position: Optional[int]) -> bool:
    """
    Return True if the given protein position falls within a known functional domain.

    Used as a component of PM1 evidence: variant in critical functional domain.

    Args:
        gene_symbol:      HGNC gene symbol
        protein_position: 1-based amino acid position, or None

    Returns:
        True if position overlaps a domain/active site/binding site.
    """
    if protein_position is None:
        return False
    data = await get_protein_domains(gene_symbol)
    if not data:
        return False
    for feature in data.get("pm1_relevant_features", []):
        start = feature.get("start", 0)
        end = feature.get("end", 0)
        if start <= protein_position <= end:
            return True
    return False


async def _search_accession(gene_symbol: str) -> Optional[str]:
    """Search UniProt for the human canonical accession for a gene."""
    url = f"{_UNIPROT_API}/search"
    params = {
        "query": f"gene_exact:{gene_symbol} AND organism_id:9606 AND reviewed:true",
        "format": "json",
        "size": 1,
        "fields": "accession,protein_name",
    }
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.get(url, params=params)
        response.raise_for_status()
        data = response.json()
    results = data.get("results", [])
    return results[0]["primaryAccession"] if results else None


async def _fetch_features(gene_symbol: str, accession: str) -> dict:
    """Fetch domain/site features for a UniProt accession."""
    url = f"{_UNIPROT_API}/{accession}"
    params = {"format": "json", "fields": "protein_name,ft_domain,ft_act_site,ft_binding,ft_site"}

    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.get(url, params=params)
        response.raise_for_status()
        data = response.json()

    protein_name = (
        data.get("proteinDescription", {})
        .get("recommendedName", {})
        .get("fullName", {})
        .get("value", gene_symbol)
    )

    features = data.get("features", [])
    domains, active_sites, binding_sites = [], [], []
    pm1_relevant = []

    for feat in features:
        ft_type = feat.get("type", "")
        loc = feat.get("location", {})
        start = loc.get("start", {}).get("value")
        end = loc.get("end", {}).get("value")
        description = feat.get("description", "")

        entry = {"type": ft_type, "description": description, "start": start, "end": end}

        if ft_type == "Domain":
            domains.append(entry)
            pm1_relevant.append(entry)
        elif ft_type == "Active site":
            active_sites.append(entry)
            pm1_relevant.append(entry)
        elif ft_type == "Binding site":
            binding_sites.append(entry)
            pm1_relevant.append(entry)

    return {
        "accession": accession,
        "protein_name": protein_name,
        "domains": domains,
        "active_sites": active_sites,
        "binding_sites": binding_sites,
        "total_features": len(features),
        "pm1_relevant_features": pm1_relevant,
    }
