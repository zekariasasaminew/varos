"""
Classification approval workflow routes.

Implements DRAFT → PENDING_REVIEW → APPROVED/REJECTED state machine.
This is the CLIA-module compliance feature (Phase 3C premium add-on).

Even without the CLIA billing module, users can use this for internal QA workflows.

Endpoints:
  GET  /v1/approvals              — List approvals (filter by state)
  POST /v1/approvals/{id}/submit  — Submit for review (DRAFT → PENDING_REVIEW)
  POST /v1/approvals/{id}/approve — Approve (PENDING_REVIEW → APPROVED)
  POST /v1/approvals/{id}/reject  — Reject with comment (PENDING_REVIEW → REJECTED)
  GET  /v1/approvals/{id}         — Get single approval with history
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from varos.api.audit import log_action
from varos.api.auth import require_api_key
from varos.api.database import get_db
from varos.api.models import ClassificationApproval, User

router = APIRouter(prefix="/v1/approvals", tags=["approvals"])

_VALID_STATES = {"draft", "pending_review", "approved", "rejected", "superseded"}
_STATE_TRANSITIONS = {
    "draft": {"pending_review"},
    "pending_review": {"approved", "rejected"},
    "rejected": {"pending_review"},  # can re-submit after rejection
}


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class ApprovalResponse(BaseModel):
    id: int
    usage_record_id: int
    state: str
    internal_ref: Optional[str]
    submitted_by_id: Optional[int]
    submitted_at: Optional[datetime]
    reviewed_by_id: Optional[int]
    reviewed_at: Optional[datetime]
    review_comment: Optional[str]
    created_at: datetime
    updated_at: datetime


class SubmitRequest(BaseModel):
    internal_ref: Optional[str] = None


class ReviewRequest(BaseModel):
    comment: Optional[str] = None


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get("", response_model=List[ApprovalResponse], summary="List classification approvals")
async def list_approvals(
    state: Optional[str] = None,
    user: User = Depends(require_api_key),
    db: Session = Depends(get_db),
):
    """
    List classification approvals for your account.
    Optionally filter by state: draft, pending_review, approved, rejected.
    """
    query = db.query(ClassificationApproval).filter(
        ClassificationApproval.user_id == user.id
    )
    if state:
        if state not in _VALID_STATES:
            raise HTTPException(status_code=422, detail=f"Invalid state: {state}")
        query = query.filter(ClassificationApproval.state == state)
    approvals = query.order_by(ClassificationApproval.created_at.desc()).limit(100).all()
    return [_to_response(a) for a in approvals]


@router.get("/{approval_id}", response_model=ApprovalResponse, summary="Get approval details")
async def get_approval(
    approval_id: int,
    user: User = Depends(require_api_key),
    db: Session = Depends(get_db),
):
    approval = _get_or_404(approval_id, user.id, db)
    return _to_response(approval)


@router.post(
    "/{approval_id}/submit",
    response_model=ApprovalResponse,
    summary="Submit classification for curator review",
)
async def submit_for_review(
    approval_id: int,
    body: SubmitRequest,
    user: User = Depends(require_api_key),
    db: Session = Depends(get_db),
):
    """
    Submit a draft classification for curator review.
    Transitions state: **draft** → **pending_review**
    (Also allowed: **rejected** → **pending_review**)
    """
    approval = _get_or_404(approval_id, user.id, db)
    _assert_transition(approval.state, "pending_review")

    approval.state = "pending_review"
    approval.submitted_by_id = user.id
    approval.submitted_at = datetime.now(timezone.utc)
    if body.internal_ref:
        approval.internal_ref = body.internal_ref
    db.commit()
    db.refresh(approval)

    log_action(
        db, action="classification.submitted_for_review",
        user_id=user.id, resource_type="approval", resource_id=str(approval_id),
        details={"state": "pending_review", "internal_ref": approval.internal_ref},
    )
    return _to_response(approval)


@router.post(
    "/{approval_id}/approve",
    response_model=ApprovalResponse,
    summary="Approve a classification",
)
async def approve_classification(
    approval_id: int,
    body: ReviewRequest,
    user: User = Depends(require_api_key),
    db: Session = Depends(get_db),
):
    """
    Approve a classification that is pending review.
    Transitions state: **pending_review** → **approved**

    The approver must be different from the submitter (four-eyes principle).
    """
    approval = _get_or_404(approval_id, user.id, db)
    _assert_transition(approval.state, "approved")

    if approval.submitted_by_id and approval.submitted_by_id == user.id:
        raise HTTPException(
            status_code=403,
            detail="Approver cannot be the same person who submitted (four-eyes principle).",
        )

    approval.state = "approved"
    approval.reviewed_by_id = user.id
    approval.reviewed_at = datetime.now(timezone.utc)
    approval.review_comment = body.comment
    db.commit()
    db.refresh(approval)

    log_action(
        db, action="classification.approved",
        user_id=user.id, resource_type="approval", resource_id=str(approval_id),
        details={"state": "approved", "comment": body.comment},
    )
    return _to_response(approval)


@router.post(
    "/{approval_id}/reject",
    response_model=ApprovalResponse,
    summary="Reject a classification",
)
async def reject_classification(
    approval_id: int,
    body: ReviewRequest,
    user: User = Depends(require_api_key),
    db: Session = Depends(get_db),
):
    """
    Reject a classification that is pending review.
    Transitions state: **pending_review** → **rejected**

    A rejection comment is required — document the reason for returning for re-analysis.
    """
    approval = _get_or_404(approval_id, user.id, db)
    _assert_transition(approval.state, "rejected")

    if not body.comment:
        raise HTTPException(status_code=422, detail="Rejection comment is required.")

    approval.state = "rejected"
    approval.reviewed_by_id = user.id
    approval.reviewed_at = datetime.now(timezone.utc)
    approval.review_comment = body.comment
    db.commit()
    db.refresh(approval)

    log_action(
        db, action="classification.rejected",
        user_id=user.id, resource_type="approval", resource_id=str(approval_id),
        details={"state": "rejected", "comment": body.comment},
    )
    return _to_response(approval)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_or_404(approval_id: int, user_id: int, db: Session) -> ClassificationApproval:
    approval = db.query(ClassificationApproval).filter(
        ClassificationApproval.id == approval_id,
        ClassificationApproval.user_id == user_id,
    ).first()
    if not approval:
        raise HTTPException(status_code=404, detail=f"Approval {approval_id} not found")
    return approval


def _assert_transition(current: str, target: str) -> None:
    allowed = _STATE_TRANSITIONS.get(current, set())
    if target not in allowed:
        raise HTTPException(
            status_code=409,
            detail=f"Cannot transition from '{current}' to '{target}'. "
                   f"Allowed transitions: {sorted(allowed) or 'none'}",
        )


def _to_response(a: ClassificationApproval) -> ApprovalResponse:
    return ApprovalResponse(
        id=a.id,
        usage_record_id=a.usage_record_id,
        state=a.state,
        internal_ref=a.internal_ref,
        submitted_by_id=a.submitted_by_id,
        submitted_at=a.submitted_at,
        reviewed_by_id=a.reviewed_by_id,
        reviewed_at=a.reviewed_at,
        review_comment=a.review_comment,
        created_at=a.created_at,
        updated_at=a.updated_at,
    )
