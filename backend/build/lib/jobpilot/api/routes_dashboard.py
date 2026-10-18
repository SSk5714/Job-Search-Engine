from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from jobpilot.api import serializers as s
from jobpilot.api.deps import current_user
from jobpilot.api.routes_jobs import latest_evaluations
from jobpilot.config import get_settings
from jobpilot.db import models as m
from jobpilot.db import heartbeat
from jobpilot.db.session import get_db
from jobpilot.domain import settings as app_settings
from jobpilot.domain.states import State

router = APIRouter(tags=["dashboard"])


def _count_state(db: Session, *states: State) -> int:
    return db.scalar(select(func.count()).select_from(m.Application)
                     .where(m.Application.state.in_([x.value for x in states]))) or 0


@router.get("/dashboard", dependencies=[Depends(current_user)])
def dashboard(db: Session = Depends(get_db)):
    now = datetime.now(UTC)
    week = now - timedelta(days=7)
    classified = db.scalars(select(m.Application).where(m.Application.state == State.CLASSIFIED.value)).all()
    evs = latest_evaluations(db, [a.job_id for a in classified])
    high_fit = [a for a in classified if a.job_id in evs and evs[a.job_id].score >= 75]
    new_jobs = sum(1 for a in classified if a.created_at and a.created_at >= week)
    failed_tasks = db.scalar(select(func.count()).select_from(m.TaskAttempt)
                             .where(m.TaskAttempt.status == "failed", m.TaskAttempt.created_at >= week)) or 0
    failed_apps = _count_state(db, State.FAILED)
    warnings = db.scalar(select(func.count()).select_from(m.Notification)
                         .where(m.Notification.kind == "alert", m.Notification.resolved_at.is_(None))) or 0
    follow_ups = db.scalar(select(func.count()).select_from(m.Application)
                           .where(m.Application.next_follow_up.is_not(None),
                                  m.Application.next_follow_up <= (now + timedelta(days=7)).date(),
                                  m.Application.state.in_([State.SUBMITTED.value, State.FOLLOW_UP.value]))) or 0
    review = db.scalars(select(m.Application).where(m.Application.state.in_(
        [State.AWAITING_USER_REVIEW.value, State.NEEDS_MANUAL_INPUT.value])).limit(10)).all()
    last_run = db.scalar(select(m.SearchRun).order_by(m.SearchRun.started_at.desc()).limit(1))
    recent_errors = db.scalars(select(m.ErrorEvent).where(m.ErrorEvent.at >= week)
                               .order_by(m.ErrorEvent.at.desc()).limit(5)).all()
    return {
        "counts": {
            "new_jobs": new_jobs,
            "high_fit": len(high_fit),
            "awaiting_review": _count_state(db, State.AWAITING_USER_REVIEW, State.NEEDS_MANUAL_INPUT),
            "documents_ready": _count_state(db, State.DOCUMENTS_READY),
            "submitted": _count_state(db, State.SUBMITTED, State.FOLLOW_UP),
            "follow_ups_due": follow_ups,
            "failed_tasks": failed_tasks + failed_apps,
            "warnings": warnings,
        },
        "review_queue": [s.application_row(a, None) for a in review],
        "top_jobs": sorted(
            [{"application_id": a.id, "job_id": a.job_id, "company": a.job.company, "title": a.job.title,
              "score": evs[a.job_id].score, "recommendation": evs[a.job_id].recommendation} for a in high_fit],
            key=lambda r: -r["score"])[:5],
        "last_run": s.run(last_run) if last_run else None,
        "recent_errors": [{"component": e.component, "severity": e.severity, "code": e.code,
                           "message": e.message, "at": e.at} for e in recent_errors],
        "open_alerts": [{"id": n.id, "severity": n.severity, "title": n.title, "remediation": n.remediation,
                         "workflow_paused": n.workflow_paused, "link": n.link, "created_at": n.created_at}
                        for n in db.scalars(select(m.Notification).where(
                            m.Notification.kind == "alert", m.Notification.resolved_at.is_(None))
                            .order_by(m.Notification.created_at.desc()).limit(5))],
        "upcoming_follow_ups": [{"application_id": a.id, "company": a.job.company, "title": a.job.title,
                                 "due": a.next_follow_up} for a in db.scalars(select(m.Application).where(
                                     m.Application.next_follow_up.is_not(None),
                                     m.Application.state.in_([State.SUBMITTED.value, State.FOLLOW_UP.value]))
                                     .order_by(m.Application.next_follow_up).limit(5))],
    }


@router.get("/health")
def health():
    return {"status": "ok"}


@router.get("/health/details", dependencies=[Depends(current_user)])
def health_details(db: Session = Depends(get_db)):
    checks: dict[str, dict] = {}
    try:
        db.execute(text("SELECT 1"))
        checks["database"] = {"status": "ok"}
    except Exception as exc:  # pragma: no cover - reported, not raised
        checks["database"] = {"status": "down", "detail": type(exc).__name__}
    url = get_settings().redis_url
    if url:
        try:
            import redis

            redis.Redis.from_url(url, socket_timeout=2).ping()
            checks["queue"] = {"status": "ok"}
        except Exception as exc:
            checks["queue"] = {"status": "down", "detail": type(exc).__name__}
    else:
        checks["queue"] = {"status": "not_configured", "detail": "Runs execute in-process (no Redis URL)"}
    factor = app_settings.get(db, "monitor").heartbeat_missed_factor
    scheduled = db.scalar(select(func.count()).select_from(m.SearchConfig).where(
        m.SearchConfig.cron.is_not(None), m.SearchConfig.enabled.is_(True))) or 0
    for comp, start in (("scheduler", "docker compose up -d beat worker (or python -m jobpilot.scheduler)"),
                        ("monitor", "docker compose up -d monitor (or python -m jobpilot.monitor)")):
        hb, age = heartbeat.age(db, comp)
        if hb is None:
            checks[comp] = {"status": "not_running" if comp == "monitor" or scheduled else "not_started",
                            "detail": f"Never started. Start it: {start}"}
        elif age > factor * hb.interval_s:
            checks[comp] = {"status": "down", "detail": f"Last heartbeat {int(age // 60)} min ago. Restart: {start}",
                            "last_beat": hb.beat_at}
        else:
            checks[comp] = {"status": "ok", "detail": f"Heartbeat {int(age)} s ago", "last_beat": hb.beat_at}
    st = get_settings()
    prefs = app_settings.get(db, "notifications")
    failed_mail = db.scalar(select(func.count()).select_from(m.NotificationDelivery).where(
        m.NotificationDelivery.status == "failed")) or 0
    if not st.email_configured:
        checks["email"] = {"status": "not_configured", "detail": "In-app notifications only. Set JOBPILOT_SMTP_* to add email"}
    elif not prefs.email_enabled:
        checks["email"] = {"status": "off", "detail": "Configured, but turned off in notification settings"}
    else:
        last_sent = db.scalar(select(func.max(m.NotificationDelivery.sent_at)))
        checks["email"] = {"status": "degraded" if failed_mail else ("ok" if last_sent else "configured_untested"),
                           "detail": (f"{failed_mail} failed deliveries" if failed_mail else
                                      f"Last sent {last_sent:%Y-%m-%d %H:%M} UTC" if last_sent else "Nothing sent yet; "
                                      "use Send test email")}
    if not get_settings().anthropic_api_key:
        checks["claude_api"] = {"status": "not_configured", "detail": "Set JOBPILOT_ANTHROPIC_API_KEY; rules-v0 is used meanwhile"}
    else:
        last = db.scalar(select(m.TaskAttempt).join(m.AgentRun).where(
            m.AgentRun.agent == "matching", m.TaskAttempt.ai_tokens_in.is_not(None))
            .order_by(m.TaskAttempt.created_at.desc()).limit(1))
        if last is None:
            checks["claude_api"] = {"status": "configured_untested", "detail": "No Claude call made yet"}
        else:
            checks["claude_api"] = {"status": "ok" if last.status == "succeeded" else "degraded",
                                    "detail": f"Last call {last.status}" + (f" ({last.error_code})" if last.error_code else "")}
    sources = [s.source(x) for x in db.scalars(select(m.JobSource).order_by(m.JobSource.code)).all()]
    history = db.scalars(select(m.HealthCheck).order_by(m.HealthCheck.at.desc()).limit(20)).all()
    errors = db.scalars(select(m.ErrorEvent).order_by(m.ErrorEvent.at.desc()).limit(20)).all()
    return {"checks": checks, "sources": sources,
            "monitor_history": [{"check": h.check_name, "status": h.status, "detail": h.detail, "at": h.at}
                                for h in history],
            "recent_errors": [{"component": e.component, "severity": e.severity, "code": e.code,
                               "message": e.message[:300], "at": e.at, "run_id": e.run_id} for e in errors]}
