"""
Audit log query routes.

Returns immutable audit trail for the current user/org.
This is the HIPAA-module feature — available to all users for basic access,
with org-wide audit log access gated to Team+ plans.

Endpoints:
  GET /v1/audit-logs       — List audit log entries (newest first)
  GET /v1/audit-logs/export — Export as CSV for compliance
"""

from __future__ import annotations

import csv
import io
import json
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from sqlalchemy.orm import Session

from varos.api.auth import require_api_key
from varos.api.database import get_db
from varos.api.models import AuditLog, Membership, User
from pydantic import BaseModel

router = APIRouter(prefix="/v1/audit-logs", tags=["audit"])


class AuditLogResponse(BaseModel):
    id: int
    action: str
    resource_type: Optional[str]
    resource_id: Optional[str]
    details: Optional[dict]
    ip_address: Optional[str]
    created_at: datetime


@router.get("", response_model=List[AuditLogResponse], summary="List audit log entries")
async def list_audit_logs(
    action: Optional[str] = Query(None, description="Filter by action (e.g. variant.classified)"),
    limit: int = Query(50, ge=1, le=500),
    user: User = Depends(require_api_key),
    db: Session = Depends(get_db),
):
    """
    List immutable audit log entries for your account.

    Returns the most recent entries first.
    Available to all authenticated users — org-wide view requires Team+ plan.

    Actions include: variant.classified, variant.report_downloaded,
    classification.approved, classification.rejected, api_key.created,
    batch.job_submitted, network.share_contributed, and more.
    """
    query = db.query(AuditLog).filter(AuditLog.user_id == user.id)
    if action:
        query = query.filter(AuditLog.action == action)
    logs = query.order_by(AuditLog.created_at.desc()).limit(limit).all()
    return [_to_response(log) for log in logs]


@router.get(
    "/export",
    summary="Export audit log as CSV",
    responses={200: {"content": {"text/csv": {}}}},
)
async def export_audit_csv(
    limit: int = Query(1000, ge=1, le=10000),
    user: User = Depends(require_api_key),
    db: Session = Depends(get_db),
):
    """
    Export your audit log as CSV for compliance reporting.
    Includes all events sorted oldest-first (for chronological audit trail).
    """
    logs = (
        db.query(AuditLog)
        .filter(AuditLog.user_id == user.id)
        .order_by(AuditLog.created_at.asc())
        .limit(limit)
        .all()
    )

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["ID", "Timestamp (UTC)", "Action", "Resource Type", "Resource ID", "Details", "IP Address"])
    for log in logs:
        writer.writerow([
            log.id,
            log.created_at.isoformat() if log.created_at else "",
            log.action,
            log.resource_type or "",
            log.resource_id or "",
            log.details_json or "",
            log.ip_address or "",
        ])

    now = datetime.now(timezone.utc).strftime("%Y%m%d")
    return Response(
        content=buf.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="varos_audit_{now}.csv"'},
    )


def _to_response(log: AuditLog) -> AuditLogResponse:
    details = None
    if log.details_json:
        try:
            details = json.loads(log.details_json)
        except Exception:
            pass
    return AuditLogResponse(
        id=log.id,
        action=log.action,
        resource_type=log.resource_type,
        resource_id=log.resource_id,
        details=details,
        ip_address=log.ip_address,
        created_at=log.created_at,
    )
