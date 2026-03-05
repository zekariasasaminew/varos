"""
Organization management routes.

Endpoints:
  POST /v1/organizations           — Create a new organization
  GET  /v1/organizations/me        — Get current user's organization
  POST /v1/organizations/invite    — Invite a team member by email
  GET  /v1/organizations/members   — List all members
  POST /v1/organizations/accept    — Accept an invitation (from email link token)
"""

from __future__ import annotations

import re
import secrets
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr
from sqlalchemy.orm import Session

from varos.api.auth import require_api_key
from varos.api.database import get_db
from varos.api.models import Membership, Organization, User

router = APIRouter(prefix="/v1/organizations", tags=["organizations"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class OrgCreate(BaseModel):
    name: str
    slug: Optional[str] = None  # auto-generated from name if not provided


class OrgResponse(BaseModel):
    id: int
    name: str
    slug: str
    tier: str
    max_seats: int
    credits_limit: int
    credits_used_this_month: int
    credits_remaining: int
    member_count: int
    created_at: datetime

    class Config:
        from_attributes = True


class MemberResponse(BaseModel):
    id: int
    email: Optional[str]
    name: Optional[str]
    role: str
    joined_at: Optional[datetime]
    invite_email: Optional[str]
    is_pending: bool


class InviteRequest(BaseModel):
    email: EmailStr
    role: str = "analyst"  # owner | analyst | viewer


class AcceptInviteRequest(BaseModel):
    token: str


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.post("", status_code=201, response_model=OrgResponse, summary="Create an organization")
async def create_organization(
    body: OrgCreate,
    user: User = Depends(require_api_key),
    db: Session = Depends(get_db),
):
    """Create a new organization and make the caller its owner."""
    # Check if user already owns an org
    existing_membership = db.query(Membership).filter(
        Membership.user_id == user.id,
        Membership.role == "owner",
        Membership.joined_at.isnot(None),
    ).first()
    if existing_membership:
        raise HTTPException(status_code=409, detail="You already own an organization")

    slug = body.slug or _slugify(body.name)
    if db.query(Organization).filter(Organization.slug == slug).first():
        raise HTTPException(status_code=409, detail=f"Organization slug '{slug}' already taken")

    org = Organization(name=body.name, slug=slug)
    db.add(org)
    db.flush()  # get org.id

    membership = Membership(
        org_id=org.id,
        user_id=user.id,
        role="owner",
        joined_at=datetime.now(timezone.utc),
    )
    db.add(membership)
    db.commit()
    db.refresh(org)

    return _org_to_response(org)


@router.get("/me", response_model=OrgResponse, summary="Get current user's organization")
async def get_my_organization(
    user: User = Depends(require_api_key),
    db: Session = Depends(get_db),
):
    """Get the organization the current user belongs to."""
    membership = db.query(Membership).filter(
        Membership.user_id == user.id,
        Membership.joined_at.isnot(None),
    ).first()
    if not membership:
        raise HTTPException(status_code=404, detail="You are not a member of any organization")

    return _org_to_response(membership.org)


@router.get("/members", response_model=List[MemberResponse], summary="List organization members")
async def list_members(
    user: User = Depends(require_api_key),
    db: Session = Depends(get_db),
):
    """List all members and pending invites in the user's organization."""
    membership = _require_org_membership(user, db)
    _require_role(membership, ["owner", "analyst", "viewer"])

    members = db.query(Membership).filter(Membership.org_id == membership.org_id).all()
    return [_member_to_response(m) for m in members]


@router.post("/invite", status_code=201, summary="Invite a team member by email")
async def invite_member(
    body: InviteRequest,
    user: User = Depends(require_api_key),
    db: Session = Depends(get_db),
):
    """Invite a new member to the organization. Only owners can invite."""
    membership = _require_org_membership(user, db)
    _require_role(membership, ["owner"])
    org = membership.org

    # Check seat limit
    active_members = db.query(Membership).filter(
        Membership.org_id == org.id,
        Membership.joined_at.isnot(None),
    ).count()
    if active_members >= org.max_seats:
        raise HTTPException(
            status_code=429,
            detail=f"Seat limit reached ({org.max_seats} for {org.tier} tier). Upgrade to add more members.",
        )

    # Check if email already invited or is a member
    existing = db.query(Membership).filter(
        Membership.org_id == org.id,
        Membership.invite_email == body.email,
    ).first()
    if existing:
        raise HTTPException(status_code=409, detail=f"{body.email} is already a member or has a pending invite")

    if body.role not in ("owner", "analyst", "viewer"):
        raise HTTPException(status_code=422, detail="Role must be owner, analyst, or viewer")

    token = secrets.token_urlsafe(32)
    invite = Membership(
        org_id=org.id,
        role=body.role,
        invite_email=body.email,
        invite_token=token,
    )
    db.add(invite)
    db.commit()

    # Fire-and-forget invite email
    import threading
    threading.Thread(
        target=_send_invite_email,
        args=(body.email, user.name or user.email, org.name, token),
        daemon=True,
    ).start()

    return {"message": f"Invite sent to {body.email}", "token": token}


@router.post("/accept", summary="Accept an organization invite")
async def accept_invite(
    body: AcceptInviteRequest,
    user: User = Depends(require_api_key),
    db: Session = Depends(get_db),
):
    """Accept an invitation using the token from the invite email."""
    membership = db.query(Membership).filter(
        Membership.invite_token == body.token,
        Membership.joined_at.is_(None),
    ).first()
    if not membership:
        raise HTTPException(status_code=404, detail="Invalid or expired invite token")

    # Check seat limit again at accept time
    org = membership.org
    active_count = db.query(Membership).filter(
        Membership.org_id == org.id,
        Membership.joined_at.isnot(None),
    ).count()
    if active_count >= org.max_seats:
        raise HTTPException(status_code=429, detail="Organization is at seat capacity")

    membership.user_id = user.id
    membership.joined_at = datetime.now(timezone.utc)
    membership.invite_token = None  # invalidate token
    db.commit()

    return {"message": f"Welcome to {org.name}!", "role": membership.role}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _slugify(name: str) -> str:
    slug = name.lower().strip()
    slug = re.sub(r"[^\w\s-]", "", slug)
    slug = re.sub(r"[\s_-]+", "-", slug)
    return slug[:50]


def _require_org_membership(user: User, db: Session) -> Membership:
    membership = db.query(Membership).filter(
        Membership.user_id == user.id,
        Membership.joined_at.isnot(None),
    ).first()
    if not membership:
        raise HTTPException(status_code=403, detail="You must be a member of an organization")
    return membership


def _require_role(membership: Membership, allowed: list) -> None:
    if membership.role not in allowed:
        raise HTTPException(status_code=403, detail=f"Requires role: {' or '.join(allowed)}")


def _org_to_response(org: Organization) -> OrgResponse:
    return OrgResponse(
        id=org.id,
        name=org.name,
        slug=org.slug,
        tier=org.tier,
        max_seats=org.max_seats,
        credits_limit=org.credits_limit,
        credits_used_this_month=org.credits_used_this_month,
        credits_remaining=org.credits_remaining,
        member_count=len([m for m in org.memberships if m.joined_at is not None]),
        created_at=org.created_at,
    )


def _member_to_response(m: Membership) -> MemberResponse:
    return MemberResponse(
        id=m.id,
        email=m.user.email if m.user else None,
        name=m.user.name if m.user else None,
        role=m.role,
        joined_at=m.joined_at,
        invite_email=m.invite_email,
        is_pending=m.joined_at is None,
    )


def _send_invite_email(to_email: str, inviter_name: str, org_name: str, token: str) -> None:
    try:
        from varos.config import settings
        if not settings.sendgrid_api_key:
            return
        import sendgrid
        from sendgrid.helpers.mail import Mail
        accept_url = f"https://varos.io/accept-invite?token={token}"
        sg = sendgrid.SendGridAPIClient(api_key=settings.sendgrid_api_key)
        message = Mail(
            from_email=settings.sendgrid_from_email,
            to_emails=to_email,
            subject=f"You've been invited to join {org_name} on VAROS",
            html_content=f"""
<h2>VAROS Team Invite</h2>
<p>{inviter_name} has invited you to join <strong>{org_name}</strong> on VAROS.</p>
<p><a href="{accept_url}" style="background:#6366f1;color:white;padding:10px 20px;border-radius:6px;text-decoration:none;display:inline-block">Accept Invite</a></p>
<p>Or copy this link: {accept_url}</p>
<small>VAROS — Variant Autonomous Reclassification & Observation System</small>
""",
        )
        sg.send(message)
    except Exception:
        pass
