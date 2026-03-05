"""User management routes — register, profile, usage."""

from __future__ import annotations

from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from varos.api.auth import require_api_key, record_usage
from varos.api.database import get_db
from varos.api.models import ApiKey, User, UsageRecord
from varos.api.schemas import RegisterRequest, UserResponse, UsageResponse

router = APIRouter(prefix="/v1", tags=["users"])


@router.post("/register", response_model=UserResponse, status_code=201, summary="Register and get API key")
async def register(body: RegisterRequest, db: Session = Depends(get_db)) -> UserResponse:
    """
    Create a free account and receive an API key instantly.
    No credit card required. Free tier: 10 variants/month.
    """
    existing = db.query(User).filter(User.email == body.email).first()
    if existing:
        raise HTTPException(status_code=409, detail="Email already registered. Use GET /v1/me to retrieve your key.")

    user = User(
        email=body.email,
        name=body.name,
        organization=body.organization,
        tier="free",
    )
    db.add(user)
    db.flush()  # get user.id

    key_value = ApiKey.generate()
    api_key = ApiKey(key=key_value, user_id=user.id)
    db.add(api_key)
    db.commit()
    db.refresh(user)

    # Fire welcome email (non-blocking)
    _send_welcome_email_background(user.email, user.name, key_value)

    return UserResponse(
        email=user.email,
        name=user.name,
        organization=user.organization,
        tier=user.tier,
        api_key=key_value,
        credits_used=0,
        credits_limit=user.credits_limit,
        credits_remaining=user.credits_limit,
        member_since=user.created_at,
    )


@router.get("/me", response_model=UserResponse, summary="Get your account info")
async def get_me(
    user: User = Depends(require_api_key),
) -> UserResponse:
    """Return your account details, tier, and API key."""
    used = user.credits_used_this_month
    return UserResponse(
        email=user.email,
        name=user.name,
        organization=user.organization,
        tier=user.tier,
        api_key=user.api_key.key if user.api_key else "",
        credits_used=used,
        credits_limit=user.credits_limit,
        credits_remaining=max(0, user.credits_limit - used),
        member_since=user.created_at,
    )


@router.get("/usage", response_model=UsageResponse, summary="Get monthly usage stats")
async def get_usage(
    user: User = Depends(require_api_key),
    db: Session = Depends(get_db),
) -> UsageResponse:
    """Return this month's usage and quota."""
    now = datetime.now(timezone.utc)
    used = user.credits_used_this_month

    # Last 10 variants classified
    recent = (
        db.query(UsageRecord)
        .filter(UsageRecord.user_id == user.id)
        .order_by(UsageRecord.created_at.desc())
        .limit(10)
        .all()
    )
    # Next month reset
    if now.month == 12:
        reset = f"January 1, {now.year + 1}"
    else:
        import calendar
        month_name = calendar.month_name[now.month + 1]
        reset = f"{month_name} 1, {now.year}"

    return UsageResponse(
        tier=user.tier,
        credits_used=used,
        credits_limit=user.credits_limit,
        credits_remaining=max(0, user.credits_limit - used),
        reset_date=reset,
        recent_variants=[r.variant for r in recent],
    )


def _send_welcome_email_background(email: str, name: str, api_key: str) -> None:
    """Fire-and-forget SendGrid welcome email."""
    import threading
    threading.Thread(target=_send_welcome_email, args=(email, name, api_key), daemon=True).start()


def _send_welcome_email(email: str, name: str, api_key: str) -> None:
    try:
        from varos.config import settings
        if not settings.sendgrid_api_key:
            return
        import sendgrid
        from sendgrid.helpers.mail import Mail

        greeting = f"Hi {name}," if name else "Hi,"
        sg = sendgrid.SendGridAPIClient(api_key=settings.sendgrid_api_key)
        message = Mail(
            from_email=settings.sendgrid_from_email,
            to_emails=email,
            subject="Welcome to VAROS — your API key is inside",
            html_content=f"""
<h2>Welcome to VAROS 🧬</h2>
<p>{greeting}</p>
<p>Your API key is ready:</p>
<pre style="background:#f4f4f4;padding:12px;border-radius:6px;font-size:14px;">{api_key}</pre>
<h3>Quick start</h3>
<pre style="background:#f4f4f4;padding:12px;border-radius:6px;font-size:13px;">
curl -X POST https://api.varos.io/v1/classify \\
  -H "X-VAROS-KEY: {api_key}" \\
  -H "Content-Type: application/json" \\
  -d '{{"variant": "BRCA1:c.5266dupC"}}'
</pre>
<p>Or with the CLI:</p>
<pre style="background:#f4f4f4;padding:12px;border-radius:6px;font-size:13px;">
pip install varos
varos classify "BRCA1:c.5266dupC"
</pre>
<p><strong>Free tier:</strong> 10 variants/month. <a href="https://varos.io/pricing">Upgrade anytime →</a></p>
<hr>
<small>VAROS — Variant Autonomous Reclassification & Observation System</small>
""",
        )
        sg.send(message)
    except Exception:
        pass  # Non-critical, don't crash registration
