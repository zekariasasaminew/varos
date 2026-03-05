"""VAROS monitoring daemon — daily re-evaluation of watched variants."""

from __future__ import annotations

import asyncio
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

DB_PATH = Path.home() / ".varos" / "watches.db"


def _get_conn() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("""
        CREATE TABLE IF NOT EXISTS watches (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            variant TEXT NOT NULL,
            email TEXT NOT NULL,
            label TEXT DEFAULT '',
            last_classification TEXT,
            last_confidence INTEGER,
            last_checked TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    return conn


def add_watch(variant: str, email: str, label: str = "") -> int:
    with _get_conn() as conn:
        cursor = conn.execute(
            "INSERT INTO watches (variant, email, label) VALUES (?, ?, ?)",
            (variant, email, label),
        )
        return cursor.lastrowid


def remove_watch(watch_id: int) -> None:
    with _get_conn() as conn:
        conn.execute("DELETE FROM watches WHERE id = ?", (watch_id,))


def list_watches() -> list[dict]:
    with _get_conn() as conn:
        rows = conn.execute("SELECT * FROM watches ORDER BY created_at DESC").fetchall()
        return [dict(r) for r in rows]


async def _check_watch(watch: dict) -> None:
    """Re-classify a watched variant and alert if classification changed."""
    from varos.agents.orchestrator import run_classification
    from varos.models import VariantInput

    variant = watch["variant"]
    result = await run_classification(VariantInput(hgvs=variant))
    new_class = result.classification.value
    old_class = watch.get("last_classification")

    with _get_conn() as conn:
        conn.execute(
            "UPDATE watches SET last_classification=?, last_confidence=?, last_checked=? WHERE id=?",
            (new_class, result.confidence, datetime.now(timezone.utc).isoformat(), watch["id"]),
        )

    # Alert if classification changed
    if old_class and new_class != old_class:
        await _send_alert(watch, old_class, new_class, result)


async def _send_alert(watch: dict, old_class: str, new_class: str, result) -> None:
    """Send an email alert when a variant is reclassified."""
    from varos.config import settings

    if not settings.sendgrid_api_key:
        print(f"[ALERT] {watch['variant']}: {old_class} → {new_class} (SendGrid not configured)")
        return

    import sendgrid
    from sendgrid.helpers.mail import Mail

    sg = sendgrid.SendGridAPIClient(api_key=settings.sendgrid_api_key)
    message = Mail(
        from_email=settings.sendgrid_from_email,
        to_emails=watch["email"],
        subject=f"VAROS Alert: {watch['variant']} reclassified",
        html_content=f"""
<h2>Variant Reclassification Alert</h2>
<p><strong>Variant:</strong> {watch['variant']}</p>
<p><strong>Previous classification:</strong> {old_class}</p>
<p><strong>New classification:</strong> <strong>{new_class}</strong></p>
<p><strong>Confidence:</strong> {result.confidence}/100</p>
<p><strong>Key triggered criteria:</strong></p>
<ul>
{"".join(f"<li>{c.code}: {c.evidence_text[:100]}</li>" for c in result.criteria_triggered)}
</ul>
<p>Log in to <a href="https://app.varos.io">app.varos.io</a> for the full report.</p>
<hr><small>VAROS — Variant Autonomous Reclassification & Observation System</small>
""",
    )
    sg.send(message)


async def run_daily_check() -> None:
    """Check all watched variants — called by the scheduler."""
    watches = list_watches()
    if not watches:
        return
    print(f"[{datetime.now()}] Checking {len(watches)} watched variants...")
    await asyncio.gather(*[_check_watch(w) for w in watches])
    print(f"[{datetime.now()}] Daily check complete.")


def start_daemon(interval_hours: int = 24, background: bool = False) -> None:
    """Start the APScheduler-based daemon."""
    from apscheduler.schedulers.blocking import BlockingScheduler
    from apscheduler.schedulers.background import BackgroundScheduler

    def job():
        asyncio.run(run_daily_check())

    SchedulerClass = BackgroundScheduler if background else BlockingScheduler
    scheduler = SchedulerClass()
    scheduler.add_job(job, "interval", hours=interval_hours, id="daily_check")
    # Run immediately on start
    scheduler.add_job(job, "date", id="initial_check")
    print(f"VAROS daemon started. Checking every {interval_hours}h.")
    scheduler.start()
