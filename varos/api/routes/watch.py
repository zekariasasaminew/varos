"""
VUS Reclassification Watch routes.

The watch feature lets users subscribe to reclassification alerts for specific variants.
When ClinVar updates a variant's classification, VAROS sends an email + webhook.

Endpoints:
  POST /v1/watch           — Subscribe to a variant
  GET  /v1/watch           — List all watched variants with current vs original classification
  DELETE /v1/watch/{id}    — Unsubscribe from a variant
  GET  /v1/watch/dashboard — Summary dashboard with reclassification probability scores
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, HttpUrl
from sqlalchemy.orm import Session

from varos.api.auth import require_api_key
from varos.api.database import get_db
from varos.api.models import ReclassificationWatch, User

router = APIRouter(prefix="/v1/watch", tags=["watch"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class WatchCreate(BaseModel):
    variant_hgvs: str
    gene: Optional[str] = None
    original_classification: Optional[str] = None  # current classification to track changes from
    clinvar_variation_id: Optional[str] = None
    webhook_url: Optional[str] = None


class WatchResponse(BaseModel):
    id: int
    variant_hgvs: str
    gene: Optional[str]
    original_classification: Optional[str]
    current_classification: Optional[str]
    clinvar_variation_id: Optional[str]
    webhook_url: Optional[str]
    reclassified: bool       # True if current != original
    last_checked_at: Optional[datetime]
    alerted_at: Optional[datetime]
    is_active: bool
    created_at: datetime

    class Config:
        from_attributes = True


class WatchDashboardItem(BaseModel):
    id: int
    variant_hgvs: str
    gene: Optional[str]
    original_classification: Optional[str]
    current_classification: Optional[str]
    reclassified: bool
    reclassification_probability: float  # 0.0 - 1.0 heuristic score
    days_watched: int
    created_at: datetime


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.post("", status_code=201, response_model=WatchResponse, summary="Subscribe to variant reclassification alerts")
async def watch_variant(
    body: WatchCreate,
    user: User = Depends(require_api_key),
    db: Session = Depends(get_db),
):
    """
    Subscribe to reclassification alerts for a variant.

    VAROS checks ClinVar weekly and sends an email + optional webhook if the variant
    classification changes (e.g., VUS -> Likely Pathogenic).
    """
    # Deduplicate: don't allow same user to watch same variant twice
    existing = db.query(ReclassificationWatch).filter(
        ReclassificationWatch.user_id == user.id,
        ReclassificationWatch.variant_hgvs == body.variant_hgvs,
        ReclassificationWatch.is_active == True,
    ).first()
    if existing:
        raise HTTPException(
            status_code=409,
            detail=f"Already watching {body.variant_hgvs}. Use GET /v1/watch/{existing.id} to view."
        )

    watch = ReclassificationWatch(
        user_id=user.id,
        variant_hgvs=body.variant_hgvs,
        gene=body.gene,
        original_classification=body.original_classification,
        current_classification=body.original_classification,
        clinvar_variation_id=body.clinvar_variation_id,
        webhook_url=body.webhook_url,
    )
    db.add(watch)
    db.commit()
    db.refresh(watch)

    return _to_response(watch)


@router.get("", response_model=List[WatchResponse], summary="List all watched variants")
async def list_watches(
    user: User = Depends(require_api_key),
    db: Session = Depends(get_db),
    reclassified_only: bool = False,
):
    """List all variants being monitored for reclassification."""
    query = db.query(ReclassificationWatch).filter(
        ReclassificationWatch.user_id == user.id,
        ReclassificationWatch.is_active == True,
    )
    watches = query.all()

    if reclassified_only:
        watches = [w for w in watches if _is_reclassified(w)]

    return [_to_response(w) for w in watches]


@router.get("/dashboard", response_model=List[WatchDashboardItem], summary="VUS reclassification dashboard")
async def watch_dashboard(
    user: User = Depends(require_api_key),
    db: Session = Depends(get_db),
):
    """
    Dashboard view of all watched variants with predicted reclassification probability.

    The probability score is a heuristic based on:
    - Time watched (older VUS variants have had more time to accumulate evidence)
    - Whether the variant is in a well-studied gene (BRCA1/2, MLH1, etc.)
    - Original classification (VUS has higher reclassification chance than LP/LB)
    """
    watches = db.query(ReclassificationWatch).filter(
        ReclassificationWatch.user_id == user.id,
        ReclassificationWatch.is_active == True,
    ).all()

    return [_to_dashboard(w) for w in watches]


@router.delete("/{watch_id}", status_code=204, summary="Unsubscribe from a variant")
async def delete_watch(
    watch_id: int,
    user: User = Depends(require_api_key),
    db: Session = Depends(get_db),
):
    """Stop monitoring a variant for reclassification."""
    watch = db.query(ReclassificationWatch).filter(
        ReclassificationWatch.id == watch_id,
        ReclassificationWatch.user_id == user.id,
    ).first()
    if not watch:
        raise HTTPException(status_code=404, detail="Watch not found")

    watch.is_active = False
    db.commit()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _is_reclassified(w: ReclassificationWatch) -> bool:
    return (
        w.original_classification is not None
        and w.current_classification is not None
        and w.original_classification != w.current_classification
    )


def _reclassification_probability(w: ReclassificationWatch) -> float:
    """
    Heuristic reclassification probability (0.0-1.0).

    Higher for: VUS classification, well-studied genes, recently submitted variants.
    Based on empirical rates from ClinVar reclassification literature.
    """
    score = 0.0

    # VUS variants are most likely to be reclassified
    if w.original_classification and "uncertain" in w.original_classification.lower():
        score += 0.35
    elif w.original_classification and "likely" in w.original_classification.lower():
        score += 0.10

    # Well-studied cancer genes have higher reclassification rates
    high_evidence_genes = {"BRCA1", "BRCA2", "MLH1", "MSH2", "MSH6", "PMS2", "TP53", "PTEN", "APC"}
    if w.gene and w.gene.upper() in high_evidence_genes:
        score += 0.25

    # Age factor: variants watched for >6 months have had more time to accumulate evidence
    days_watched = (datetime.now(timezone.utc) - w.created_at).days
    if days_watched > 180:
        score += 0.20
    elif days_watched > 60:
        score += 0.10

    # Has ClinVar ID: being tracked in ClinVar = more likely to get updated
    if w.clinvar_variation_id:
        score += 0.15

    return min(1.0, score)


def _to_response(w: ReclassificationWatch) -> WatchResponse:
    return WatchResponse(
        id=w.id,
        variant_hgvs=w.variant_hgvs,
        gene=w.gene,
        original_classification=w.original_classification,
        current_classification=w.current_classification,
        clinvar_variation_id=w.clinvar_variation_id,
        webhook_url=w.webhook_url,
        reclassified=_is_reclassified(w),
        last_checked_at=w.last_checked_at,
        alerted_at=w.alerted_at,
        is_active=w.is_active,
        created_at=w.created_at,
    )


def _to_dashboard(w: ReclassificationWatch) -> WatchDashboardItem:
    days_watched = (datetime.now(timezone.utc) - w.created_at).days
    return WatchDashboardItem(
        id=w.id,
        variant_hgvs=w.variant_hgvs,
        gene=w.gene,
        original_classification=w.original_classification,
        current_classification=w.current_classification,
        reclassified=_is_reclassified(w),
        reclassification_probability=round(_reclassification_probability(w), 2),
        days_watched=days_watched,
        created_at=w.created_at,
    )
