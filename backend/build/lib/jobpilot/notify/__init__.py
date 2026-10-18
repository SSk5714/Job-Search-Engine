"""Notifications and alerts.

- `notify()` records one user-facing event (high-fit jobs, ready for approval, submitted, follow-up).
  A dedup key makes it once-only, so retries and duplicate ticks never repeat a notification.
- `raise_alert()` opens or refreshes an alert. One open alert per key: repeats bump `occurrences`
  instead of creating noise. Alerts carry component, run/task id, cause, remediation and
  whether the workflow is paused.
- Email copies are queued as `notification_deliveries` and sent by `delivery.deliver_due()`.

Low-level events (each source error, each retry) stay in error_events; only actionable
summaries become notifications.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from jobpilot.config import get_settings
from jobpilot.db import models as m
from jobpilot.domain import settings as app_settings
from jobpilot.domain.settings import SEVERITY_RANK

log = logging.getLogger("jobpilot.notify")


def _wants_email(db: Session, kind: str, severity: str) -> bool:
    if not get_settings().email_configured:
        return False
    prefs = app_settings.get(db, "notifications")
    if not prefs.email_enabled or kind not in prefs.email_kinds:
        return False
    if kind == "alert":
        return SEVERITY_RANK[severity] >= SEVERITY_RANK[prefs.email_alert_min_severity]
    return True


def _queue_email(db: Session, n: m.Notification) -> None:
    db.add(m.NotificationDelivery(notification_id=n.id, channel="email", status="pending",
                                  next_attempt_at=datetime.now(UTC)))


def notify(db: Session, kind: str, title: str, body: str = "", *, dedup_key: str, severity: str = "info",
           link: str | None = None, context: dict | None = None, email: bool = True) -> m.Notification | None:
    """Create a notification once per dedup key. Returns None if it already existed."""
    if db.scalar(select(m.Notification.id).where(m.Notification.dedup_key == dedup_key)):
        return None
    n = m.Notification(kind=kind, severity=severity, title=title[:255], body=body, dedup_key=dedup_key,
                       link=link, context=context or {}, channel="in_app", delivery_status="delivered",
                       last_seen_at=datetime.now(UTC))
    try:
        with db.begin_nested():
            db.add(n)
            db.flush()
    except IntegrityError:  # a concurrent writer created it first
        return None
    if email and _wants_email(db, kind, severity):
        _queue_email(db, n)
    db.flush()
    return n


@dataclass
class Finding:
    """What an alert must say (spec: severity, component, ids, summary, cause, remediation, paused)."""

    key: str
    severity: str
    component: str
    title: str
    summary: str
    remediation: str
    likely_cause: str | None = None
    workflow_paused: bool = False
    run_id: uuid.UUID | None = None
    task_id: uuid.UUID | None = None
    link: str | None = None
    context: dict = field(default_factory=dict)


def raise_alert(db: Session, f: Finding, *, email: bool = True) -> tuple[m.Notification, bool]:
    """Open an alert, or refresh the open one with the same key. Returns (alert, created)."""
    now = datetime.now(UTC)
    open_ = db.scalar(select(m.Notification).where(m.Notification.alert_key == f.key,
                                                   m.Notification.resolved_at.is_(None)).with_for_update())
    if open_ is not None:
        escalated = SEVERITY_RANK[f.severity] > SEVERITY_RANK.get(open_.severity, 0)
        open_.occurrences += 1
        open_.last_seen_at = now
        open_.body, open_.likely_cause, open_.remediation = f.summary, f.likely_cause, f.remediation
        open_.workflow_paused, open_.context = f.workflow_paused, f.context
        if escalated:
            open_.severity, open_.title = f.severity, f.title[:255]
            open_.acknowledged_at = None
            if email and _wants_email(db, "alert", f.severity) and not db.scalar(
                    select(m.NotificationDelivery.id).where(m.NotificationDelivery.notification_id == open_.id)):
                _queue_email(db, open_)
        db.flush()
        return open_, False
    n = m.Notification(kind="alert", severity=f.severity, title=f.title[:255], body=f.summary, alert_key=f.key,
                       component=f.component, run_id=f.run_id, task_id=f.task_id, likely_cause=f.likely_cause,
                       remediation=f.remediation, workflow_paused=f.workflow_paused, link=f.link,
                       context=f.context, channel="in_app", delivery_status="delivered", last_seen_at=now)
    try:
        with db.begin_nested():
            db.add(n)
            db.flush()
    except IntegrityError:  # raced with another writer: refresh theirs instead
        return raise_alert(db, f, email=email)
    log.warning("alert %s [%s] %s: %s", f.severity, f.component, f.title, f.summary)
    if email and _wants_email(db, "alert", f.severity):
        _queue_email(db, n)
    db.flush()
    return n, True


def resolve_alert(db: Session, key: str, by: str = "monitor") -> bool:
    n = db.scalar(select(m.Notification).where(m.Notification.alert_key == key, m.Notification.resolved_at.is_(None)))
    if n is None:
        return False
    n.resolved_at, n.resolved_by = datetime.now(UTC), by
    db.flush()
    return True


def resolve_cleared(db: Session, prefix: str, still_firing: set[str]) -> int:
    """Close monitor alerts under `prefix` whose condition is no longer detected."""
    rows = db.scalars(select(m.Notification).where(m.Notification.alert_key.startswith(prefix),
                                                   m.Notification.resolved_at.is_(None))).all()
    n = 0
    for r in rows:
        if r.alert_key not in still_firing:
            r.resolved_at, r.resolved_by = datetime.now(UTC), "monitor"
            n += 1
    db.flush()
    return n


# ── Events from the workflow ────────────────────────────────────────────────


def on_transition(db: Session, app: m.Application, to_state: str) -> None:
    """Called by transitions.apply inside the same transaction."""
    job = app.job or db.get(m.Job, app.job_id)
    who = f"{job.title} at {job.company}" if job else "an application"
    link = f"/review?id={app.id}"
    if to_state == "awaiting_user_review":
        manual = (app.preparation or {}).get("mode") == "manual"
        notify(db, "ready_for_review", f"Ready for your approval: {who}",
               "Apply on the employer's site yourself, then record it." if manual else
               "Documents and form answers are prepared. Review and approve them before anything is sent.",
               dedup_key=f"ready:{app.id}:{app.state_version}", link=link)
    elif to_state == "submitted":
        notify(db, "submitted", f"Application sent: {who}",
               f"Confirmed. A follow-up reminder is set for {app.next_follow_up or 'later'}.",
               dedup_key=f"submitted:{app.id}", link="/tracker", severity="info")
