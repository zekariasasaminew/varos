"""
ClinicalTrials.gov API connector.

Queries the ClinicalTrials.gov v2 REST API (free, no auth) for clinical trials
relevant to a genomic variant. Used to:
1. Find trials with the variant as an inclusion/exclusion biomarker
2. Pharma drug discovery teams use this to find patient populations
3. Show researchers which trials their patients may qualify for

ClinicalTrials.gov API v2 docs:
https://clinicaltrials.gov/data-api/api

No API key required — fully open.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import List, Optional

import httpx

logger = logging.getLogger("varos.connectors.clinicaltrials")

_API_BASE = "https://clinicaltrials.gov/api/v2/studies"

# Trial status categories
_OPEN_STATUSES = {
    "RECRUITING",
    "ENROLLING_BY_INVITATION",
    "NOT_YET_RECRUITING",
    "AVAILABLE",
}


@dataclass
class ClinicalTrial:
    """A single clinical trial result."""
    nct_id: str
    title: str
    status: str
    phase: Optional[str]
    sponsor: str
    enrollment: Optional[int]
    conditions: List[str]
    interventions: List[str]
    is_recruiting: bool
    url: str
    start_date: Optional[str]
    primary_completion_date: Optional[str]
    brief_summary: Optional[str]


@dataclass
class TrialSearchResult:
    """Result of a ClinicalTrials.gov search for a variant."""
    variant_hgvs: str
    gene: Optional[str]
    tumor_type: Optional[str]
    total_found: int
    open_trials: int
    trials: List[ClinicalTrial] = field(default_factory=list)
    query_used: str = ""


async def search_trials_for_variant(
    variant_hgvs: str,
    gene: Optional[str] = None,
    tumor_type: Optional[str] = None,
    max_results: int = 10,
    open_only: bool = True,
) -> TrialSearchResult:
    """
    Search ClinicalTrials.gov for trials relevant to a genomic variant.

    Strategy:
    1. Search by gene name (most specific, e.g. "BRCA1")
    2. Optionally filter by tumor type (e.g. "breast cancer", "colorectal")
    3. Return structured trial list sorted by enrollment size

    Args:
        variant_hgvs: Variant in HGVS notation (used for display; gene used for search)
        gene: Gene symbol (e.g. "BRCA1") — primary search term
        tumor_type: Optional tumor/disease type to filter results
        max_results: Maximum trials to return
        open_only: If True, only return actively recruiting trials

    Returns:
        TrialSearchResult with list of ClinicalTrial objects
    """
    if not gene and not variant_hgvs:
        return TrialSearchResult(
            variant_hgvs=variant_hgvs,
            gene=gene,
            tumor_type=tumor_type,
            total_found=0,
            open_trials=0,
        )

    # Build search query
    query_terms = []
    if gene:
        query_terms.append(gene)
    if tumor_type:
        query_terms.append(tumor_type)

    query = " AND ".join(query_terms) if query_terms else variant_hgvs
    status_filter = ",".join(_OPEN_STATUSES) if open_only else None

    try:
        trials = await _fetch_trials(
            query=query,
            status_filter=status_filter,
            max_results=max_results,
        )
        open_count = sum(1 for t in trials if t.is_recruiting)
        return TrialSearchResult(
            variant_hgvs=variant_hgvs,
            gene=gene,
            tumor_type=tumor_type,
            total_found=len(trials),
            open_trials=open_count,
            trials=trials,
            query_used=query,
        )
    except Exception as exc:
        logger.warning("ClinicalTrials.gov search failed: %s", exc)
        return TrialSearchResult(
            variant_hgvs=variant_hgvs,
            gene=gene,
            tumor_type=tumor_type,
            total_found=0,
            open_trials=0,
            query_used=query,
        )


async def _fetch_trials(
    query: str,
    status_filter: Optional[str],
    max_results: int,
) -> List[ClinicalTrial]:
    """Fetch trials from ClinicalTrials.gov v2 API."""
    params = {
        "query.term": query,
        "pageSize": min(max_results, 20),
        "format": "json",
        "fields": ",".join([
            "NCTId",
            "BriefTitle",
            "OverallStatus",
            "Phase",
            "LeadSponsorName",
            "EnrollmentCount",
            "Condition",
            "InterventionName",
            "StartDate",
            "PrimaryCompletionDate",
            "BriefSummary",
        ]),
    }
    if status_filter:
        params["filter.overallStatus"] = status_filter

    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.get(_API_BASE, params=params)
        resp.raise_for_status()
        data = resp.json()

    studies = data.get("studies", [])
    trials = []
    for study in studies:
        ps = study.get("protocolSection", {})
        id_module = ps.get("identificationModule", {})
        status_module = ps.get("statusModule", {})
        sponsor_module = ps.get("sponsorCollaboratorsModule", {})
        desc_module = ps.get("descriptionModule", {})
        design_module = ps.get("designModule", {})
        conditions_module = ps.get("conditionsModule", {})
        arms_module = ps.get("armsInterventionsModule", {})

        nct_id = id_module.get("nctId", "")
        status = status_module.get("overallStatus", "UNKNOWN")
        phases = design_module.get("phases", [])
        phase_str = "/".join(phases) if phases else None

        interventions = [
            iv.get("name", "")
            for iv in arms_module.get("interventions", [])
            if iv.get("name")
        ]

        enrollment = None
        enroll_info = design_module.get("enrollmentInfo", {})
        if enroll_info.get("count"):
            try:
                enrollment = int(enroll_info["count"])
            except (ValueError, TypeError):
                pass

        trials.append(ClinicalTrial(
            nct_id=nct_id,
            title=id_module.get("briefTitle", ""),
            status=status,
            phase=phase_str,
            sponsor=sponsor_module.get("leadSponsor", {}).get("name", ""),
            enrollment=enrollment,
            conditions=conditions_module.get("conditions", []),
            interventions=interventions[:5],  # limit to first 5
            is_recruiting=status in _OPEN_STATUSES,
            url=f"https://clinicaltrials.gov/study/{nct_id}",
            start_date=status_module.get("startDateStruct", {}).get("date"),
            primary_completion_date=status_module.get("primaryCompletionDateStruct", {}).get("date"),
            brief_summary=desc_module.get("briefSummary", "")[:500] if desc_module.get("briefSummary") else None,
        ))

    # Sort: recruiting first, then by enrollment descending
    trials.sort(key=lambda t: (not t.is_recruiting, -(t.enrollment or 0)))
    return trials
