"""
Clinical Trial matching routes.

Provides trial intelligence for a specific variant — used by pharma teams
to find patient populations for trials and by researchers to find trial options.

Endpoints:
  GET /v1/trials/{variant_hgvs}  — List clinical trials matching a variant/gene
  GET /v1/trials/summary          — Summary stats for trial intelligence

This is the "Trial Intelligence" API package — separate revenue stream.
"""

from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from varos.api.auth import require_api_key
from varos.api.models import User

router = APIRouter(prefix="/v1/trials", tags=["trials"])


# ---------------------------------------------------------------------------
# Response schemas
# ---------------------------------------------------------------------------

class ClinicalTrialResponse(BaseModel):
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


class TrialsResponse(BaseModel):
    variant_hgvs: str
    gene: Optional[str]
    tumor_type: Optional[str]
    total_found: int
    open_trials: int
    trials: List[ClinicalTrialResponse]
    query_used: str


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get(
    "/{variant_hgvs:path}",
    response_model=TrialsResponse,
    summary="Find clinical trials for a variant or gene",
)
async def get_trials_for_variant(
    variant_hgvs: str,
    gene: Optional[str] = Query(None, description="Gene symbol (e.g. BRCA1, EGFR, KRAS)"),
    tumor_type: Optional[str] = Query(None, description="Tumor/disease type (e.g. breast cancer, NSCLC)"),
    open_only: bool = Query(True, description="Only return actively recruiting trials"),
    max_results: int = Query(10, ge=1, le=50, description="Max trials to return"),
    user: User = Depends(require_api_key),
):
    """
    Find clinical trials relevant to a variant or gene.

    Uses gene symbol as the primary search term (most accurate),
    optionally filtered by tumor type.

    This endpoint is part of the **Trial Intelligence** feature set —
    available on Pro and Lab plans.

    **Use cases:**
    - Pharma: Find all trials recruiting patients with BRCA1/2 mutations
    - Researchers: Identify if their patient's variant has matching trials
    - Oncology teams: Discover investigational therapies for specific variants

    **Returns trials sorted by:** Recruiting status (open first), then enrollment size.
    """
    from varos.connectors.clinicaltrials import search_trials_for_variant

    try:
        result = await search_trials_for_variant(
            variant_hgvs=variant_hgvs,
            gene=gene,
            tumor_type=tumor_type,
            max_results=max_results,
            open_only=open_only,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Trial search failed: {exc}")

    return TrialsResponse(
        variant_hgvs=result.variant_hgvs,
        gene=result.gene,
        tumor_type=result.tumor_type,
        total_found=result.total_found,
        open_trials=result.open_trials,
        query_used=result.query_used,
        trials=[
            ClinicalTrialResponse(
                nct_id=t.nct_id,
                title=t.title,
                status=t.status,
                phase=t.phase,
                sponsor=t.sponsor,
                enrollment=t.enrollment,
                conditions=t.conditions,
                interventions=t.interventions,
                is_recruiting=t.is_recruiting,
                url=t.url,
                start_date=t.start_date,
                primary_completion_date=t.primary_completion_date,
                brief_summary=t.brief_summary,
            )
            for t in result.trials
        ],
    )
