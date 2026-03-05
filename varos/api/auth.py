"""API key authentication middleware and dependency."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import Header, HTTPException, Depends
from sqlalchemy.orm import Session

from varos.api.database import get_db
from varos.api.models import ApiKey, User, UsageRecord


async def require_api_key(
    x_varos_key: str | None = Header(None, alias="X-VAROS-KEY"),
    authorization: str | None = Header(None),
    db: Session = Depends(get_db),
) -> User:
    """FastAPI dependency — validates API key, returns User."""
    raw_key = x_varos_key

    # Also accept Bearer token in Authorization header
    if not raw_key and authorization and authorization.startswith("Bearer vrs_"):
        raw_key = authorization.removeprefix("Bearer ")

    if not raw_key:
        raise HTTPException(
            status_code=401,
            detail="API key required. Pass X-VAROS-KEY header or Authorization: Bearer vrs_xxx",
            headers={"WWW-Authenticate": "Bearer"},
        )

    api_key_row = db.query(ApiKey).filter(ApiKey.key == raw_key).first()
    if not api_key_row:
        raise HTTPException(status_code=401, detail="Invalid API key")

    user = api_key_row.user
    if not user or not user.is_active:
        raise HTTPException(status_code=403, detail="Account disabled")

    # Update last used
    api_key_row.last_used_at = datetime.now(timezone.utc)
    db.commit()

    return user


async def require_quota(
    user: User = Depends(require_api_key),
    db: Session = Depends(get_db),
) -> User:
    """Extends require_api_key — also checks monthly quota."""
    if user.credits_remaining <= 0:
        raise HTTPException(
            status_code=429,
            detail=(
                f"Monthly quota exceeded ({user.credits_limit} variants for {user.tier} tier). "
                "Upgrade at https://varos.io/pricing"
            ),
            headers={"X-Quota-Limit": str(user.credits_limit), "X-Quota-Used": str(user.credits_used_this_month)},
        )
    return user


def record_usage(db: Session, user: User, variant: str, classification: str | None, confidence: int | None) -> None:
    """Log a variant classification to the usage table."""
    record = UsageRecord(
        user_id=user.id,
        variant=variant,
        classification=classification,
        confidence=confidence,
    )
    db.add(record)
    db.commit()

    # Send 80% quota warning email once per month (fire-and-forget)
    used = user.credits_used_this_month
    limit = user.credits_limit
    if limit > 0 and used / limit >= 0.8:
        import threading
        threading.Thread(
            target=_send_quota_warning_email,
            args=(user.email, user.name, used, limit, user.tier),
            daemon=True,
        ).start()


def _send_quota_warning_email(email: str, name: str, used: int, limit: int, tier: str) -> None:
    """Send a quota warning email when user hits 80% of monthly limit."""
    try:
        from varos.config import settings
        if not settings.sendgrid_api_key:
            return
        import sendgrid
        from sendgrid.helpers.mail import Mail

        remaining = limit - used
        greeting = f"Hi {name}," if name else "Hi,"
        upgrade_url = "https://varos.io/pricing"
        sg = sendgrid.SendGridAPIClient(api_key=settings.sendgrid_api_key)
        message = Mail(
            from_email=settings.sendgrid_from_email,
            to_emails=email,
            subject=f"VAROS: You've used {used}/{limit} variants this month",
            html_content=f"""
<h2>🧬 VAROS — Quota Alert</h2>
<p>{greeting}</p>
<p>You've used <strong>{used} of {limit} variants</strong> ({used * 100 // limit}%) on your {tier} plan this month.
You have <strong>{remaining} variant{'s' if remaining != 1 else ''} remaining</strong>.</p>
<p>To avoid interruptions, <a href="{upgrade_url}">upgrade your plan →</a></p>
<table style="border-collapse:collapse;margin:12px 0">
  <tr><td style="padding:4px 12px 4px 0;color:#666">Current plan</td><td><strong>{tier.title()}</strong></td></tr>
  <tr><td style="padding:4px 12px 4px 0;color:#666">Used this month</td><td><strong>{used} / {limit}</strong></td></tr>
  <tr><td style="padding:4px 12px 4px 0;color:#666">Remaining</td><td><strong>{remaining}</strong></td></tr>
</table>
<p><a href="{upgrade_url}" style="background:#6366f1;color:white;padding:10px 20px;border-radius:6px;text-decoration:none;display:inline-block">Upgrade Now</a></p>
<hr>
<small>VAROS — Variant Autonomous Reclassification & Observation System | <a href="https://varos.io">varos.io</a></small>
""",
        )
        sg.send(message)
    except Exception:
        pass  # Non-critical

