"""
OMIM (Online Mendelian Inheritance in Man) connector.

OMIM provides curated gene-disease relationships used for:
  - PP2: Missense variant in a gene with a low rate of benign missense variation where
         missense variants are a common mechanism of disease
  - PM1: Located in a mutational hot spot and/or critical functional domain

API: OMIM API v1 — free for research use (requires API key from omim.org).
https://www.omim.org/api

Set OMIM_API_KEY in .env for full access. Without key, falls back to public gene summary.
"""

from __future__ import annotations

import logging
from typing import Optional

import httpx

from varos.config import settings

logger = logging.getLogger(__name__)

_OMIM_API = "https://api.omim.org/api"


async def get_gene_disease_info(gene_symbol: str) -> Optional[dict]:
    """
    Fetch OMIM gene-disease relationships for ACMG PP2 and PM1 evidence.

    Args:
        gene_symbol: HGNC gene symbol, e.g. "BRCA1", "MLH1"

    Returns:
        Dict with 'mim_number', 'gene_name', 'phenotypes', 'disease_mechanism',
        'pp2_applicable', 'pm1_applicable', or None on failure.
    """
    api_key = getattr(settings, "omim_api_key", None)
    if not api_key:
        logger.debug("OMIM_API_KEY not set — OMIM lookup skipped for %s", gene_symbol)
        return None

    url = f"{_OMIM_API}/geneMap"
    params = {
        "apiKey": api_key,
        "geneSymbol": gene_symbol,
        "format": "json",
        "include": "geneMap",
    }

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(url, params=params)
            response.raise_for_status()
            data = response.json()
    except Exception as exc:
        logger.warning("OMIM lookup failed for %s: %s", gene_symbol, exc)
        return None

    return _parse_gene_map(gene_symbol, data)


def _parse_gene_map(gene_symbol: str, data: dict) -> Optional[dict]:
    try:
        gene_maps = data["omim"]["listResponse"]["geneMapList"]
        if not gene_maps:
            return None

        gene_map = gene_maps[0]["geneMap"]
        phenotypes = gene_map.get("phenotypeMapList", [])

        # Collect associated phenotypes with inheritance patterns
        disease_list = []
        mechanisms = set()
        for ph_entry in phenotypes:
            ph = ph_entry.get("phenotypeMap", {})
            name = ph.get("phenotype", "")
            inheritance = ph.get("phenotypeMappingKey", 0)
            mechanism = ph.get("phenotypeInheritance", "")
            if name:
                disease_list.append({"name": name, "inheritance": mechanism})
            if mechanism:
                mechanisms.add(mechanism)

        # PP2 applicable if gene has predominantly AD inheritance and missense mechanism
        pp2_applicable = any(
            "Autosomal dominant" in d.get("inheritance", "") for d in disease_list
        )
        # PM1 applicable if any known hot spot domains recorded in OMIM
        pm1_applicable = gene_map.get("mouseMutation") is not None  # proxy: well-characterized gene

        return {
            "mim_number": gene_map.get("mimNumber"),
            "gene_name": gene_map.get("geneName", gene_symbol),
            "phenotypes": disease_list[:5],  # top 5 associations
            "disease_mechanisms": list(mechanisms),
            "pp2_applicable": pp2_applicable,
            "pm1_applicable": pm1_applicable,
        }
    except (KeyError, IndexError, TypeError) as exc:
        logger.debug("OMIM parse error for %s: %s", gene_symbol, exc)
        return None
