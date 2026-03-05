"""ClinVar connector — submission history and aggregate classification."""

from __future__ import annotations

import asyncio
import xml.etree.ElementTree as ET

import httpx
from Bio import Entrez
from tenacity import retry, stop_after_attempt, wait_exponential

from varos.config import settings
from varos.models import ClinVarEvidence, ClinVarSubmission

Entrez.email = settings.ncbi_email
if settings.ncbi_api_key:
    Entrez.api_key = settings.ncbi_api_key

REVIEW_STATUS_STARS = {
    "practice guideline": 4,
    "reviewed by expert panel": 3,
    "criteria provided, multiple submitters, no conflicts": 2,
    "criteria provided, single submitter": 1,
    "no assertion criteria provided": 0,
    "no interpretation for the single variant": 0,
}


@retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=10))
async def fetch_clinvar_evidence(hgvs: str) -> ClinVarEvidence:
    """Fetch ClinVar submissions for a variant by HGVS notation."""
    loop = asyncio.get_event_loop()

    # Step 1: Search ClinVar for the variant
    search_handle = await loop.run_in_executor(
        None,
        lambda: Entrez.esearch(db="clinvar", term=f"{hgvs}[HGVS]", retmax=5),
    )
    search_results = Entrez.read(search_handle)
    search_handle.close()

    ids = search_results.get("IdList", [])
    if not ids:
        return ClinVarEvidence(not_found=True)

    variation_id = ids[0]

    # Step 2: Fetch variant summary
    fetch_handle = await loop.run_in_executor(
        None,
        lambda: Entrez.efetch(db="clinvar", id=variation_id, rettype="vcv", retmode="xml", is_variationid=True),
    )
    xml_content = fetch_handle.read()
    fetch_handle.close()

    return _parse_clinvar_xml(xml_content, variation_id)


def _parse_clinvar_xml(xml_content: bytes | str, variation_id: str) -> ClinVarEvidence:
    """Parse ClinVar VCV XML into structured ClinVarEvidence."""
    try:
        root = ET.fromstring(xml_content)
    except ET.ParseError:
        return ClinVarEvidence(variation_id=variation_id, not_found=True)

    submissions: list[ClinVarSubmission] = []
    aggregate_class = None
    review_status = None

    # Extract aggregate classification
    interp = root.find(".//Interpretations/Interpretation")
    if interp is not None:
        description = interp.find("Description")
        if description is not None:
            aggregate_class = description.text
        review_elem = interp.find("ReviewStatus")
        if review_elem is not None:
            review_status = review_elem.text

    # Extract individual submissions
    for scv in root.findall(".//ClassifiedConditionList/..[@Type='SCV']"):
        submitter_elem = scv.find(".//SubmitterName")
        clinsig_elem = scv.find(".//Interpretation/Description")
        if submitter_elem is not None and clinsig_elem is not None:
            rs = scv.find(".//ReviewStatus")
            conditions = [c.text for c in scv.findall(".//ConditionList/TraitSet/Trait/Name/ElementValue[@Type='Preferred']") if c.text]
            submissions.append(
                ClinVarSubmission(
                    variation_id=variation_id,
                    clinical_significance=clinsig_elem.text or "Unknown",
                    review_status=rs.text if rs is not None else "unknown",
                    gold_stars=REVIEW_STATUS_STARS.get(rs.text.lower() if rs is not None else "", 0),
                    submitter=submitter_elem.text or "Unknown",
                    conditions=conditions,
                )
            )

    # Check for conflicting interpretations
    classes = {s.clinical_significance.lower() for s in submissions}
    path_classes = {"pathogenic", "likely pathogenic"}
    benign_classes = {"benign", "likely benign"}
    conflicting = bool(classes & path_classes and classes & benign_classes)

    gold_stars = REVIEW_STATUS_STARS.get(review_status.lower() if review_status else "", 0)

    return ClinVarEvidence(
        variation_id=variation_id,
        aggregate_classification=aggregate_class,
        review_status=review_status,
        gold_stars=gold_stars,
        submissions=submissions,
        conflicting_interpretations=conflicting,
    )
