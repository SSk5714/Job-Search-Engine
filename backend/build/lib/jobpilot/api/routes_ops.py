"""Usage and cost overview, and backups (restores are CLI-only on purpose)."""

from datetime import UTC, date, datetime, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import Date, cast, func, select
from sqlalchemy.orm import Session

from jobpilot.api.deps import current_user
from jobpilot.config import get_settings
from jobpilot.db import models as m
from jobpilot.db.session import get_db
from jobpilot.domain import settings as app_settings
from jobpilot.domain.errors import DomainError

router = APIRouter(tags=["operations"], dependencies=[Depends(current_user)])

FUNNEL = ["classified", "approved_for_preparation", "documents_ready", "awaiting_user_review", "submitted",
          "follow_up", "closed", "rejected", "withdrawn", "expired", "needs_manual_input", "failed"]


@router.get("/usage")
def usage(days: int = 30, db: Session = Depends(get_db)):
    days = max(1, min(days, 365))
    since = datetime.now(UTC) - timedelta(days=days)
    day = cast(m.TaskAttempt.created_at, Date)
    ai_rows = db.execute(
        select(day, m.AgentRun.agent, func.count(), func.coalesce(func.sum(m.TaskAttempt.ai_tokens_in), 0),
               func.coalesce(func.sum(m.TaskAttempt.ai_tokens_out), 0),
               func.coalesce(func.sum(m.TaskAttempt.ai_cost_usd), 0))
        .join(m.AgentRun, m.AgentRun.id == m.TaskAttempt.agent_run_id)
        .where(m.TaskAttempt.created_at >= since, m.TaskAttempt.ai_tokens_in.is_not(None))
        .group_by(day, m.AgentRun.agent).order_by(day)).all()
    per_day: dict[str, dict] = {}
    per_agent: dict[str, dict] = {}
    for d, agent, calls, tin, tout, cost in ai_rows:
        k = d.isoformat()
        e = per_day.setdefault(k, {"date": k, "calls": 0, "tokens_in": 0, "tokens_out": 0, "cost_usd": 0.0})
        a = per_agent.setdefault(agent, {"agent": agent, "calls": 0, "tokens_in": 0, "tokens_out": 0, "cost_usd": 0.0})
        for x in (e, a):
            x["calls"] += calls
            x["tokens_in"] += int(tin)
            x["tokens_out"] += int(tout)
            x["cost_usd"] = round(x["cost_usd"] + float(cost), 4)
    run_day = cast(m.SearchRun.started_at, Date)
    runs = db.execute(select(run_day, m.SearchRun.status, func.count()).where(m.SearchRun.started_at >= since)
                      .group_by(run_day, m.SearchRun.status)).all()
    run_stats: dict[str, int] = {}
    for _, status, n in runs:
        run_stats[status] = run_stats.get(status, 0) + n
    jobs_new = db.scalar(select(func.count()).select_from(m.Job).where(m.Job.retrieved_at >= since,
                                                                       m.Job.duplicate_of_id.is_(None))) or 0
    funnel = dict(db.execute(select(m.Application.state, func.count()).group_by(m.Application.state)).all())
    submitted = db.scalar(select(func.count()).select_from(m.SubmissionAttempt).where(
        m.SubmissionAttempt.status == "succeeded", m.SubmissionAttempt.started_at >= since)) or 0
    ai = app_settings.get(db, "ai")
    today = date.today()
    month_start = datetime(today.year, today.month, 1, tzinfo=UTC)
    month_cost = db.scalar(select(func.coalesce(func.sum(m.TaskAttempt.ai_cost_usd), 0))
                           .where(m.TaskAttempt.created_at >= month_start)) or 0
    day_start = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    today_cost = db.scalar(select(func.coalesce(func.sum(m.TaskAttempt.ai_cost_usd), 0))
                           .where(m.TaskAttempt.created_at >= day_start)) or 0
    total = sum(x["cost_usd"] for x in per_day.values())
    return {
        "days": days,
        "ai": {"per_day": list(per_day.values()), "per_agent": sorted(per_agent.values(), key=lambda x: -x["cost_usd"]),
               "total_cost_usd": round(total, 4), "today_cost_usd": round(float(today_cost), 4),
               "month_cost_usd": round(float(month_cost), 4), "daily_budget_usd": ai.daily_budget_usd,
               "budget_used_pct": round(100 * float(today_cost) / ai.daily_budget_usd, 1) if ai.daily_budget_usd else None,
               "api_key_configured": bool(get_settings().anthropic_api_key)},
        "searches": {"runs": run_stats, "new_jobs": jobs_new},
        "applications": {"funnel": {s: funnel.get(s, 0) for s in FUNNEL}, "submitted_in_period": submitted},
    }


def _backup_out(b: m.Backup) -> dict:
    return {"name": b.name, "kind": b.kind, "status": b.status, "size_bytes": b.size_bytes,
            "started_at": b.started_at, "finished_at": b.finished_at, "detail": b.detail}


@router.get("/backups")
def list_backups(db: Session = Depends(get_db)):
    from jobpilot.ops import backup

    s = get_settings()
    rows = db.scalars(select(m.Backup).order_by(m.Backup.started_at.desc()).limit(30)).all()
    last = backup.last_ok(db)
    return {"schedule": f"Daily at {s.backup_at} (Europe/Berlin)" if s.backup_at else "Off",
            "keep": s.backup_keep, "last_ok": _backup_out(last) if last else None,
            "history": [_backup_out(b) for b in rows],
            "restore_hint": "Restores run from the command line only: python -m jobpilot.ops restore NAME --yes "
                            "(see docs/operations.md)."}


@router.post("/backups", status_code=201)
def make_backup(db: Session = Depends(get_db)):
    from jobpilot.ops import backup

    running = db.scalar(select(m.Backup.id).where(m.Backup.status == "running",
                                                  m.Backup.started_at > datetime.now(UTC) - timedelta(minutes=30)))
    if running:
        raise DomainError("backup_in_progress", "A backup is already running")
    try:
        b = backup.create("manual")
    except backup.BackupError as e:
        raise DomainError("backup_failed", str(e), status_code=500)
    db.expire_all()
    row = db.scalar(select(m.Backup).where(m.Backup.name == b.name))
    return _backup_out(row)
