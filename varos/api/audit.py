"""
Audit log helper functions.

Usage:
    from varos.api.audit import log_action

    log_action(
        db, user_id=user.id, action="variant.classified",
        resource_type="variant", resource_id="NM_007294.4:c.5266dupC",
        details={"classification": "Likely Pathogenic", "confidence": 78},
    )

The audit log is append-only (no UPDATE/DELETE operations ever touch it).
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, Optional

from sqlalchemy.orm import Session

from varos.api.models import AuditLog

logger = logging.getLogger("varos.audit")


def log_action(
    db: Session,
    action: str,
    user_id: Optional[int] = None,
    org_id: Optional[int] = None,
    resource_type: Optional[str] = None,
    resource_id: Optional[str] = None,
    details: Optional[Dict[str, Any]] = None,
    ip_address: Optional[str] = None,
    user_agent: Optional[str] = None,
) -> AuditLog:
    """
    Append an immutable audit log entry.

    Never raises — if DB write fails, logs a warning and continues.
    Audit logs must never block the main request path.
    """
    try:
        entry = AuditLog(
            user_id=user_id,
            org_id=org_id,
            action=action,
            resource_type=resource_type,
            resource_id=str(resource_id)[:255] if resource_id else None,
            details_json=json.dumps(details) if details else None,
            ip_address=ip_address,
            user_agent=user_agent[:500] if user_agent else None,
        )
        db.add(entry)
        db.commit()
        return entry
    except Exception as exc:
        logger.warning("Failed to write audit log (action=%s): %s", action, exc)
        try:
            db.rollback()
        except Exception:
            pass
        return None


def log_from_request(
    db: Session,
    request,
    action: str,
    user_id: Optional[int] = None,
    org_id: Optional[int] = None,
    resource_type: Optional[str] = None,
    resource_id: Optional[str] = None,
    details: Optional[Dict[str, Any]] = None,
) -> AuditLog:
    """
    Log an action with IP address and user agent extracted from a FastAPI Request.
    """
    ip = None
    ua = None
    if request:
        ip = getattr(request.client, "host", None)
        ua = request.headers.get("user-agent")
    return log_action(
        db=db,
        action=action,
        user_id=user_id,
        org_id=org_id,
        resource_type=resource_type,
        resource_id=resource_id,
        details=details,
        ip_address=ip,
        user_agent=ua,
    )
