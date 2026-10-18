"""In-app notifications and monitor alerts."""

import uuid
from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, Depends
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from jobpilot.api.deps import current_user
from jobpilot.db import models as m
from jobpilot.db.session import get_db
from jobpilot.domain.errors import DomainError, NotFound
from jobpilot.notify import delivery

router = APIRouter(tags=["notifications"], dependencies=[Depends(current_user)])

MANUAL_RESOLVE_PREFIXES = ("db-outage:", "delivery:", "submission-unknown:")


def out(n: m.Notification, deliveries: list[m.NotificationDelivery] | None = None) -> dict:
    return {
        "id": n.id, "kind": n.kind, "severity": n.severity, "title": n.title, "body": n.body, "link": n.link,
        "created_at": n.created_at, "last_seen_at": n.last_seen_at, "read_at": n.read_at,
        "acknowledged_at": n.acknowledged_at, "resolved_at": n.resolved_at, "resolved_by": n.resolved_by,
        "alert_key": n.alert_key, "component": n.component, "run_id": n.run_id, "task_id": n.task_id,
        "likely_cause": n.likely_cause, "remediation": n.remediation, "workflow_paused": n.workflow_paused,
        "occurrences": n.occurrences, "context": n.context or {},
        "can_resolve": bool(n.kind == "alert" and n.resolved_at is None and n.alert_key and
                            not n.alert_key.startswith("mon:") and not n.alert_key.startswith("heartbeat:")),
        "deliveries": [{"channel": d.channel, "status": d.status, "attempts": d.attempts, "last_error": d.last_error,
                        "sent_at": d.sent_at, "next_attempt_at": d.next_attempt_at} for d in deliveries or []],
    }


def _with_deliveries(db: Session, rows: list[m.Notification]) -> list[dict]:
    ids = [n.id for n in rows]
    by: dict = {}
    if ids:
        for d in db.scalars(select(m.NotificationDelivery).where(m.NotificationDelivery.notification_id.in_(ids))):
            by.setdefault(d.notification_id, []).append(d)
    return [out(n, by.get(n.id)) for n in rows]


@router.get("/notifications")
def list_notifications(kind: Literal["all", "alerts", "updates"] = "all", status: Literal["open", "all"] = "all",
                       limit: int = 50, db: Session = Depends(get_db)):
    q = select(m.Notification)
    if kind == "alerts":
        q = q.where(m.Notification.kind == "alert")
    elif kind == "updates":
        q = q.where(m.Notification.kind != "alert")
    if status == "open":
        q = q.where(m.Notification.resolved_at.is_(None), m.Notification.kind == "alert")
    rows = db.scalars(q.order_by(m.Notification.resolved_at.is_not(None), m.Notification.created_at.desc())
                      .limit(min(limit, 200))).all()
    return _with_deliveries(db, rows)


@router.get("/notifications/summary")
def summary(db: Session = Depends(get_db)):
    unread = db.scalar(select(func.count()).select_from(m.Notification).where(
        m.Notification.read_at.is_(None), m.Notification.resolved_at.is_(None))) or 0
    rows = db.execute(select(m.Notification.severity, func.count()).where(
        m.Notification.kind == "alert", m.Notification.resolved_at.is_(None)).group_by(m.Notification.severity)).all()
    alerts = {k: 0 for k in ("critical", "warning", "info")} | {s: n for s, n in rows}
    return {"unread": unread, "open_alerts": alerts}


def _get(db: Session, nid: uuid.UUID) -> m.Notification:
    n = db.get(m.Notification, nid)
    if n is None:
        raise NotFound("Notification")
    return n


@router.post("/notifications/{nid}/read")
def mark_read(nid: uuid.UUID, db: Session = Depends(get_db)):
    n = _get(db, nid)
    n.read_at = n.read_at or datetime.now(UTC)
    db.commit()
    return _with_deliveries(db, [n])[0]


@router.post("/notifications/read-all")
def read_all(db: Session = Depends(get_db)):
    res = db.execute(update(m.Notification).where(m.Notification.read_at.is_(None))
                     .values(read_at=datetime.now(UTC)))
    db.commit()
    return {"marked": res.rowcount}


@router.post("/notifications/{nid}/retry-delivery")
def retry_delivery(nid: uuid.UUID, db: Session = Depends(get_db)):
    _get(db, nid)
    n = delivery.retry(db, nid)
    if not n:
        raise DomainError("nothing_to_retry", "No failed email for this notification")
    db.commit()
    return {"requeued": n, "note": "It will be sent with the next scheduler tick (within a minute)."}


@router.get("/alerts")
def list_alerts(status: Literal["open", "all"] = "open", db: Session = Depends(get_db)):
    return list_notifications(kind="alerts", status=status, limit=100, db=db)


@router.post("/alerts/{nid}/ack")
def ack(nid: uuid.UUID, db: Session = Depends(get_db)):
    """Acknowledging says you have seen it. It stays open until the monitor sees the problem gone."""
    n = _get(db, nid)
    if n.kind != "alert":
        raise DomainError("validation_error", "Not an alert", status_code=422)
    now = datetime.now(UTC)
    n.acknowledged_at, n.read_at = n.acknowledged_at or now, n.read_at or now
    db.commit()
    return _with_deliveries(db, [n])[0]


@router.post("/alerts/{nid}/resolve")
def resolve(nid: uuid.UUID, db: Session = Depends(get_db)):
    """Only for alerts nothing can check automatically (e.g. a past outage). Monitor alerts close themselves."""
    n = _get(db, nid)
    if n.kind != "alert" or n.resolved_at is not None:
        raise DomainError("invalid_state", "This alert is not open")
    if not out(n)["can_resolve"]:
        raise DomainError("invalid_state", "This alert closes by itself once the monitor sees the problem fixed")
    if n.alert_key and n.alert_key.startswith("submission-unknown:"):
        app_id = n.alert_key.split(":", 1)[1]
        pending = db.scalar(select(m.SubmissionAttempt.id).where(
            m.SubmissionAttempt.application_id == uuid.UUID(app_id), m.SubmissionAttempt.status == "unknown"))
        if pending:
            raise DomainError("invalid_state", "Record whether the application arrived first (Application Review)")
    now = datetime.now(UTC)
    n.resolved_at, n.resolved_by, n.read_at = now, "user", n.read_at or now
    db.commit()
    return _with_deliveries(db, [n])[0]
