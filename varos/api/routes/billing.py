"""Stripe billing routes — checkout sessions and webhook handler."""

from __future__ import annotations

import json
from fastapi import APIRouter, Depends, HTTPException, Request, Header
from sqlalchemy.orm import Session

from varos.api.auth import require_api_key
from varos.api.database import get_db
from varos.api.models import User
from varos.api.schemas import CheckoutRequest, CheckoutResponse
from varos.config import settings

router = APIRouter(prefix="/v1/billing", tags=["billing"])

# Stripe price IDs — set these in .env after creating products in Stripe dashboard
STRIPE_PRICES = {
    "starter": settings.stripe_starter_price_id if hasattr(settings, "stripe_starter_price_id") else "",
    "pro": settings.stripe_pro_price_id if hasattr(settings, "stripe_pro_price_id") else "",
}

TIER_FROM_PRICE = {v: k for k, v in STRIPE_PRICES.items() if v}


@router.post("/checkout", response_model=CheckoutResponse, summary="Create Stripe checkout session")
async def create_checkout(
    body: CheckoutRequest,
    user: User = Depends(require_api_key),
) -> CheckoutResponse:
    """Create a Stripe Checkout session to upgrade your tier."""
    if body.tier not in STRIPE_PRICES:
        raise HTTPException(status_code=400, detail=f"Unknown tier: {body.tier}. Choose: starter, pro")

    if not settings.stripe_secret_key:
        raise HTTPException(status_code=503, detail="Billing not configured on this server")

    try:
        import stripe
        stripe.api_key = settings.stripe_secret_key

        session = stripe.checkout.Session.create(
            customer_email=user.email,
            mode="subscription",
            line_items=[{"price": STRIPE_PRICES[body.tier], "quantity": 1}],
            success_url=body.success_url + "?session_id={CHECKOUT_SESSION_ID}",
            cancel_url=body.cancel_url,
            metadata={"user_email": user.email, "tier": body.tier},
        )
        return CheckoutResponse(checkout_url=session.url, session_id=session.id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Stripe error: {e}")


@router.post("/webhook", summary="Stripe webhook handler", status_code=200)
async def stripe_webhook(
    request: Request,
    stripe_signature: str | None = Header(None, alias="stripe-signature"),
    db: Session = Depends(get_db),
) -> dict:
    """
    Handle Stripe events:
    - checkout.session.completed → activate subscription tier
    - customer.subscription.deleted → downgrade to free
    - invoice.payment_failed → send warning email
    """
    if not settings.stripe_secret_key:
        return {"status": "billing not configured"}

    try:
        import stripe
        stripe.api_key = settings.stripe_secret_key

        payload = await request.body()
        event = stripe.Webhook.construct_event(
            payload, stripe_signature, settings.stripe_webhook_secret
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Webhook error: {e}")

    event_type = event["type"]
    data = event["data"]["object"]

    if event_type == "checkout.session.completed":
        email = data.get("customer_email") or data.get("metadata", {}).get("user_email", "")
        tier = data.get("metadata", {}).get("tier", "starter")
        subscription_id = data.get("subscription")
        customer_id = data.get("customer")

        user = db.query(User).filter(User.email == email).first()
        if user:
            user.tier = tier
            user.stripe_customer_id = customer_id
            user.stripe_subscription_id = subscription_id
            db.commit()

    elif event_type == "customer.subscription.deleted":
        subscription_id = data.get("id")
        user = db.query(User).filter(User.stripe_subscription_id == subscription_id).first()
        if user:
            user.tier = "free"
            user.stripe_subscription_id = None
            db.commit()

    elif event_type == "invoice.payment_failed":
        customer_id = data.get("customer")
        user = db.query(User).filter(User.stripe_customer_id == customer_id).first()
        if user:
            _send_payment_failed_email(user.email)

    return {"status": "ok", "event": event_type}


def _send_payment_failed_email(email: str) -> None:
    import threading
    threading.Thread(target=_do_send_payment_failed, args=(email,), daemon=True).start()


def _do_send_payment_failed(email: str) -> None:
    try:
        if not settings.sendgrid_api_key:
            return
        import sendgrid
        from sendgrid.helpers.mail import Mail
        sg = sendgrid.SendGridAPIClient(api_key=settings.sendgrid_api_key)
        sg.send(Mail(
            from_email=settings.sendgrid_from_email,
            to_emails=email,
            subject="VAROS — payment failed",
            html_content=(
                "<p>Your VAROS payment failed. Please update your payment method at "
                "<a href='https://varos.io/billing'>varos.io/billing</a> to keep your subscription active.</p>"
            ),
        ))
    except Exception:
        pass
