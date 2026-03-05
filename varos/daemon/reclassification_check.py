"""
VAROS Weekly ClinVar Diff Reclassification Job.

Runs weekly (via APScheduler) to:
1. Pull latest ClinVar variant submissions for all watched variants
2. Detect any classification changes since last check
3. Update ReclassificationWatch records with new classifications
4. Send email + webhook notifications for changed variants
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from datetime import datetime, timezone
from typing import Optional

import httpx

logger = logging.getLogger("varos.daemon.reclassification")


# ---------------------------------------------------------------------------
# ClinVar variant lookup via Entrez E-Utilities (free, no key needed)
# ---------------------------------------------------------------------------

CLINVAR_ESEARCH = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
CLINVAR_ESUMMARY = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi"

# ClinVar clinical significance → normalized VAROS label
_CLINVAR_SIG_MAP = {
    "pathogenic": "Pathogenic",
    "likely pathogenic": "Likely Pathogenic",
    "uncertain significance": "Uncertain Significance",
    "likely benign": "Likely Benign",
    "benign": "Benign",
    "pathogenic/likely pathogenic": "Likely Pathogenic",
    "benign/likely benign": "Likely Benign",
}


async def fetch_clinvar_classification(hgvs: str, clinvar_id: Optional[str] = None) -> Optional[str]:
    """
    Fetch the current aggregate ClinVar classification for a variant.

    Tries by ClinVar accession (VCV/RCV) if provided, otherwise searches by HGVS.
    Returns normalized classification string or None if not found.
    """
    async with httpx.AsyncClient(timeout=10.0) as client:
        if clinvar_id and clinvar_id.startswith(("VCV", "RCV")):
            return await _fetch_by_accession(client, clinvar_id)
        return await _fetch_by_hgvs(client, hgvs)


async def _fetch_by_accession(client: httpx.AsyncClient, accession: str) -> Optional[str]:
    try:
        resp = await client.get(
            CLINVAR_ESUMMARY,
            params={"db": "clinvar", "id": accession, "retmode": "json"},
        )
        data = resp.json()
        uid = next(iter(data.get("result", {}).get("uids", [])), None)
        if not uid:
            return None
        record = data["result"].get(str(uid), {})
        sig = record.get("clinical_significance", {}).get("description", "").lower()
        return _CLINVAR_SIG_MAP.get(sig)
    except Exception:
        return None


async def _fetch_by_hgvs(client: httpx.AsyncClient, hgvs: str) -> Optional[str]:
    try:
        resp = await client.get(
            CLINVAR_ESEARCH,
            params={"db": "clinvar", "term": hgvs, "retmode": "json", "retmax": 1},
        )
        ids = resp.json().get("esearchresult", {}).get("idlist", [])
        if not ids:
            return None
        return await _fetch_by_accession(client, ids[0])
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Main reclassification check job
# ---------------------------------------------------------------------------

async def run_reclassification_check() -> dict:
    """
    Main weekly job:
    - Queries all active ReclassificationWatch records
    - Checks ClinVar for classification changes
    - Updates DB and sends alerts for changes
    Returns summary dict: {checked, changed, errors}
    """
    from varos.api.database import SessionLocal
    from varos.api.models import ReclassificationWatch

    db = SessionLocal()
    checked = 0
    changed = 0
    errors = 0

    try:
        # Get all active watches
        watches = db.query(ReclassificationWatch).filter(
            ReclassificationWatch.is_active == True  # noqa: E712
        ).all()

        logger.info("Starting reclassification check for %d watched variants", len(watches))

        for watch in watches:
            try:
                new_class = await fetch_clinvar_classification(
                    hgvs=watch.variant_hgvs,
                    clinvar_id=watch.clinvar_variation_id,
                )
                checked += 1

                if new_class and new_class != watch.original_classification:
                    old_class = watch.original_classification or watch.current_classification
                    watch.current_classification = new_class
                    watch.last_checked_at = datetime.now(timezone.utc)
                    db.commit()
                    changed += 1

                    # Fire notifications
                    await _notify_reclassification(watch, old_class, new_class)
                    logger.info(
                        "Reclassification detected: %s  %s -> %s",
                        watch.variant_hgvs, old_class, new_class,
                    )
                else:
                    watch.last_checked_at = datetime.now(timezone.utc)
                    db.commit()

            except Exception as exc:
                errors += 1
                logger.warning("Error checking watch %s: %s", watch.variant_hgvs, exc)

        summary = {"checked": checked, "changed": changed, "errors": errors}
        logger.info("Reclassification check complete: %s", summary)
        return summary

    finally:
        db.close()


async def _notify_reclassification(watch, old_class: str, new_class: str) -> None:
    """Send email + webhook for a reclassification event."""
    await asyncio.gather(
        _send_email_alert(watch, old_class, new_class),
        _send_webhook_alert(watch, old_class, new_class),
        return_exceptions=True,
    )


async def _send_email_alert(watch, old_class: str, new_class: str) -> None:
    """Send email notification via SendGrid."""
    from varos.config import settings
    from varos.api.database import SessionLocal
    from varos.api.models import User

    db = SessionLocal()
    try:
        user = db.query(User).filter(User.id == watch.user_id).first()
        if not user or not user.email:
            return
    finally:
        db.close()

    if not settings.sendgrid_api_key:
        logger.info(
            "[EMAIL] Would notify user %s: %s reclassified %s -> %s",
            watch.user_id, watch.variant_hgvs, old_class, new_class,
        )
        return

    try:
        import sendgrid
        from sendgrid.helpers.mail import Mail

        sg = sendgrid.SendGridAPIClient(api_key=settings.sendgrid_api_key)
        message = Mail(
            from_email=settings.sendgrid_from_email,
            to_emails=user.email,
            subject=f"VAROS Alert: {watch.variant_hgvs} reclassified",
            html_content=f"""
<h2>Variant Reclassification Alert</h2>
<p>A variant you are monitoring has been reclassified in ClinVar.</p>
<table>
  <tr><td><strong>Variant</strong></td><td>{watch.variant_hgvs}</td></tr>
  <tr><td><strong>Previous classification</strong></td><td>{old_class}</td></tr>
  <tr><td><strong>New classification</strong></td><td><strong>{new_class}</strong></td></tr>
  <tr><td><strong>Detected</strong></td><td>{datetime.now(timezone.utc).strftime('%Y-%m-%d')}</td></tr>
</table>
<p>
  <a href="https://app.varos.io/watch">View your watchlist &rarr;</a>
</p>
<hr>
<small>VAROS — Variant Autonomous Reclassification and Observation System<br>
Unsubscribe from alerts in your account settings.</small>
""",
        )
        sg.send(message)
    except Exception as exc:
        logger.warning("Failed to send email alert: %s", exc)


async def _send_webhook_alert(watch, old_class: str, new_class: str) -> None:
    """POST to webhook URL if configured on the watch record."""
    if not watch.webhook_url:
        return
    payload = {
        "event": "variant.reclassified",
        "variant_hgvs": watch.variant_hgvs,
        "old_classification": old_class,
        "new_classification": new_class,
        "detected_at": datetime.now(timezone.utc).isoformat(),
        "watch_id": watch.id,
    }
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            await client.post(watch.webhook_url, json=payload)
    except Exception as exc:
        logger.warning("Failed to send webhook to %s: %s", watch.webhook_url, exc)


# ---------------------------------------------------------------------------
# Scheduler integration
# ---------------------------------------------------------------------------

def schedule_weekly_check(scheduler) -> None:
    """
    Register the weekly reclassification check with an existing APScheduler instance.

    Usage in daemon/scheduler.py:
        from varos.daemon.reclassification_check import schedule_weekly_check
        schedule_weekly_check(scheduler)
    """
    def _job():
        asyncio.run(run_reclassification_check())

    scheduler.add_job(
        _job,
        trigger="cron",
        day_of_week="sun",
        hour=2,
        minute=0,
        id="weekly_reclassification_check",
        replace_existing=True,
    )
    logger.info("Scheduled weekly reclassification check (Sun 02:00 UTC)")
