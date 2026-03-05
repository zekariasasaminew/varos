"""gnomAD GraphQL connector — population allele frequencies."""

from __future__ import annotations

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from varos.models import PopulationFrequency

GNOMAD_API = "https://gnomad.broadinstitute.org/api"

_VARIANT_QUERY = """
query VariantFrequency($variantId: String!, $datasetId: DatasetId!) {
  variant(variantId: $variantId, dataset: $datasetId) {
    variantId
    exome {
      ac
      an
      ac_hom
      populations {
        id
        ac
        an
        ac_hom
      }
    }
    genome {
      ac
      an
      ac_hom
      populations {
        id
        ac
        an
        ac_hom
      }
    }
  }
}
"""


def _build_variant_id(chrom: str, pos: int, ref: str, alt: str) -> str:
    """Build gnomAD variant ID: chr-pos-ref-alt."""
    chrom = chrom.replace("chr", "")
    return f"{chrom}-{pos}-{ref}-{alt}"


@retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=10))
async def fetch_gnomad_frequency(
    chrom: str,
    pos: int,
    ref: str,
    alt: str,
    genome_build: str = "GRCh38",
) -> PopulationFrequency:
    """Fetch allele frequency from gnomAD v4.1 (GRCh38) or v2.1 (GRCh37)."""
    dataset = "gnomad_r4" if genome_build == "GRCh38" else "gnomad_r2_1"
    variant_id = _build_variant_id(chrom, pos, ref, alt)

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            GNOMAD_API,
            json={"query": _VARIANT_QUERY, "variables": {"variantId": variant_id, "datasetId": dataset}},
        )
        resp.raise_for_status()
        data = resp.json()

    variant = data.get("data", {}).get("variant")
    if not variant:
        return PopulationFrequency(not_found=True, genome_build=genome_build)

    # Prefer exome data, fall back to genome
    cohort = variant.get("exome") or variant.get("genome") or {}
    ac = cohort.get("ac", 0) or 0
    an = cohort.get("an", 0) or 0
    ac_hom = cohort.get("ac_hom", 0) or 0
    af = ac / an if an > 0 else 0.0

    # Ancestry breakdown + popmax
    ancestry: dict[str, float] = {}
    popmax_af = 0.0
    popmax_pop = None
    for pop in cohort.get("populations", []):
        pop_an = pop.get("an", 0) or 0
        pop_ac = pop.get("ac", 0) or 0
        pop_af = pop_ac / pop_an if pop_an > 0 else 0.0
        ancestry[pop["id"]] = pop_af
        if pop_af > popmax_af:
            popmax_af = pop_af
            popmax_pop = pop["id"]

    return PopulationFrequency(
        source=f"gnomAD v4.1 ({dataset})",
        allele_count=ac,
        allele_number=an,
        allele_frequency=af,
        homozygote_count=ac_hom,
        popmax_af=popmax_af,
        popmax_population=popmax_pop,
        ancestry_breakdown=ancestry,
        genome_build=genome_build,
    )
