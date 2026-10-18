"""The orchestrator's schedule: one `tick()` a minute (Celery beat, or `python -m jobpilot.scheduler`).

Each tick, in order:
1. Heartbeat, so the monitor can tell the scheduler is alive.
2. Start due searches. A dispatch row per (schedule, due time) is unique, so running two
   schedulers, or a retried tick, never starts the same search twice. Missed times while the
   scheduler was down are caught up with ONE run, not one per missed slot.
3. Mark runs failed that have been "running" far beyond the worker's hard time limit (the
   worker died), so the next scheduled run is not blocked forever.
4. Pause a schedule after repeated failed scheduled runs, with an alert (resume in the UI).
5. Follow-up reminders.
6. Check the monitor's heartbeat (the monitor checks ours).
7. Send due email notifications.

Every step is deterministic and recorded; nothing here touches approvals or submissions.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from jobpilot.config import get_settings
from jobpilot.db import models as m
from jobpilot.db.heartbeat import age as heartbeat_age
from jobpilot.db.heartbeat import beat
from jobpilot.db.session import SessionLocal, get_engine
from jobpilot.domain import schedule
from jobpilot.domain import settings as app_settings
from jobpilot.domain.errors import DomainError
from jobpilot.notify import Finding, notify, raise_alert, resolve_alert
from jobpilot.notify import delivery
from jobpilot.orchestrator import runs

log = logging.getLogger("jobpilot.scheduler")

Enqueue = Callable[[uuid.UUID], None]
TICK_LOCK = 0x4A0B_5C4E  # pg advisory lock id: one tick at a time across processes
PAUSE_AFTER_FAILURES = 3


def default_enqueue(run_id: uuid.UUID) -> None:
    if get_settings().redis_url:
        from jobpilot.worker import run_search

        run_search.delay(str(run_id))
    else:
        import threading

        threading.Thread(target=runs.execute_run, args=(run_id,), daemon=False, name=f"run-{run_id}").start()


def _dispatch_due(db: Session, now: datetime, enqueue: Enqueue) -> list[dict]:
    out = []
    # initialise new or edited schedules without running them immediately
    for c in db.scalars(select(m.SearchConfig).where(m.SearchConfig.cron.is_not(None),
                                                     m.SearchConfig.next_run_at.is_(None))).all():
        c.next_run_at = schedule.next_run(c.cron, c.timezone, now)
    db.commit()

    due = db.scalars(select(m.SearchConfig).where(
        m.SearchConfig.enabled.is_(True), m.SearchConfig.cron.is_not(None), m.SearchConfig.paused_reason.is_(None),
        m.SearchConfig.next_run_at <= now).with_for_update(skip_locked=True)).all()
    for c in due:
        due_at = c.next_run_at
        missed, probe = 0, due_at
        while missed < 1000:
            probe = schedule.next_run(c.cron, c.timezone, probe)
            if probe > now:
                break
            missed += 1
        c.next_run_at = probe  # catch up once, not once per missed slot
        disp = m.ScheduleDispatch(config_id=c.id, due_at=due_at, outcome="started",
                                  detail=f"{missed} earlier time(s) missed while the scheduler was down" if missed else None)
        try:
            with db.begin_nested():
                db.add(disp)
                db.flush()
        except IntegrityError:
            continue  # another scheduler already handled this due time
        try:
            with db.begin_nested():
                run = runs.start_run(db, c.id, trigger="schedule")
            disp.run_id = run.id
        except DomainError as e:
            if e.code != "run_in_progress":
                raise
            disp.outcome, disp.detail = "skipped_overlap", "The previous run of this search was still running"
            run = None
        except Exception as e:  # a schedule that cannot start is an alert, never silent
            disp.outcome, disp.detail = "failed_to_start", f"{type(e).__name__}: {e}"[:500]
            run = None
            db.add(m.ErrorEvent(component="scheduler", severity="critical", code="failed_to_start",
                                message=disp.detail, context={"config_id": str(c.id)}))
            raise_alert(db, Finding(
                key=f"schedule-start:{c.id}", severity="critical", component="scheduler",
                title=f"Scheduled search “{c.name}” could not start", summary=disp.detail,
                remediation="Open Job Discovery and run the search by hand to see the error; "
                            "the next scheduled time is kept.", link="/discovery",
                context={"config_id": str(c.id), "due_at": due_at.isoformat()}))
        db.commit()
        if run is not None:
            try:
                enqueue(run.id)
            except Exception as e:  # the queue is down: fail the run visibly instead of leaving it "running"
                r = db.get(m.SearchRun, run.id)
                r.status, r.finished_at = "failed", datetime.now(UTC)
                r.summary = {"error": f"Could not queue the run: {type(e).__name__}"}
                d = db.get(m.ScheduleDispatch, disp.id)
                d.outcome, d.detail = "failed_to_start", f"Queue unavailable: {type(e).__name__}: {e}"[:500]
                raise_alert(db, Finding(
                    key="queue:enqueue", severity="critical", component="queue", run_id=r.id,
                    title="Scheduled searches cannot be queued", summary=d.detail,
                    likely_cause="Redis is down or unreachable",
                    remediation="Start Redis (docker compose up -d redis) and check JOBPILOT_REDIS_URL. "
                                "The next scheduled time will try again.", workflow_paused=True, link="/settings"))
                db.commit()
            else:
                resolve_alert(db, "queue:enqueue")
                resolve_alert(db, f"schedule-start:{c.id}")
                db.commit()
        out.append({"config": c.name, "due_at": due_at.isoformat(), "outcome": disp.outcome,
                    "run_id": str(disp.run_id) if disp.run_id else None})
    db.commit()
    return out


def _expire_stalled(db: Session, now: datetime) -> list[str]:
    limit = now - timedelta(minutes=get_settings().run_stall_minutes)
    stale = db.scalars(select(m.SearchRun).where(m.SearchRun.status == "running", m.SearchRun.started_at < limit)
                       .with_for_update(skip_locked=True)).all()
    for r in stale:
        r.status, r.finished_at = "failed", now
        r.summary = {**(r.summary or {}), "error": f"stalled: still running after {get_settings().run_stall_minutes} "
                     "minutes; the worker probably stopped"}
        for a in db.scalars(select(m.AgentRun).where(m.AgentRun.run_id == r.id, m.AgentRun.status == "running")):
            a.status, a.finished_at = "failed", now
        db.add(m.ErrorEvent(component="orchestrator", severity="warning", run_id=r.id, code="run_stalled",
                            message=r.summary["error"]))
    db.commit()
    return [str(r.id) for r in stale]


def _pause_failing(db: Session, now: datetime) -> list[str]:
    paused = []
    for c in db.scalars(select(m.SearchConfig).where(m.SearchConfig.cron.is_not(None),
                                                     m.SearchConfig.paused_reason.is_(None))).all():
        q = select(m.SearchRun).where(m.SearchRun.config_id == c.id, m.SearchRun.trigger == "schedule",
                                      m.SearchRun.status != "running")
        if c.resumed_at:
            q = q.where(m.SearchRun.started_at > c.resumed_at)
        last = db.scalars(q.order_by(m.SearchRun.started_at.desc()).limit(PAUSE_AFTER_FAILURES)).all()
        if len(last) == PAUSE_AFTER_FAILURES and all(r.status == "failed" for r in last):
            errs = sorted({(r.summary or {}).get("error") or ", ".join(
                f"{k}: {v.get('error')}" for k, v in ((r.summary or {}).get("sources") or {}).items()
                if v.get("status") == "failed") or "unknown" for r in last})
            c.paused_reason = f"Paused after {PAUSE_AFTER_FAILURES} failed scheduled runs in a row: {'; '.join(errs)}"[:1000]
            c.paused_at = now
            raise_alert(db, Finding(
                key=f"schedule-paused:{c.id}", severity="warning", component="scheduler", run_id=last[0].id,
                title=f"Scheduled search “{c.name}” paused", summary=c.paused_reason,
                likely_cause="A source keeps failing (settings, network or the source changed)",
                remediation="Fix the search settings (try Run search to check), then press Resume in Job Discovery.",
                workflow_paused=True, link="/discovery", context={"config_id": str(c.id)}))
            paused.append(c.name)
    db.commit()
    return paused


def _follow_ups(db: Session, today: date) -> int:
    lead = app_settings.get(db, "notifications").follow_up_lead_days
    apps = db.scalars(select(m.Application).where(
        m.Application.state.in_(["submitted", "follow_up"]), m.Application.next_follow_up.is_not(None),
        m.Application.next_follow_up <= today + timedelta(days=lead))).all()
    made = 0
    for a in apps:
        when = "today" if a.next_follow_up == today else ("overdue since " if a.next_follow_up < today else "on ") + \
            f"{a.next_follow_up:%a %d %b}"
        if notify(db, "follow_up", f"Follow up: {a.job.title} at {a.job.company}",
                  f"Your follow-up is due {when}. Check for a reply or send a short, polite message; "
                  "record the outcome in the Tracker.",
                  dedup_key=f"follow_up:{a.id}:{a.next_follow_up.isoformat()}", link="/tracker"):
            made += 1
    db.commit()
    return made


def _scheduled_backup(db: Session, now: datetime) -> dict:
    """Daily backup at JOBPILOT_BACKUP_AT (Berlin time), once per day."""
    from zoneinfo import ZoneInfo

    from jobpilot.ops import backup

    at = get_settings().backup_at
    if not at:
        return {"disabled": True}
    local = now.astimezone(ZoneInfo("Europe/Berlin"))
    h, mi = (int(x) for x in at.split(":"))
    due = local.replace(hour=h, minute=mi, second=0, microsecond=0)
    if local < due:
        return {}
    done = db.scalar(select(m.Backup.id).where(m.Backup.kind == "scheduled", m.Backup.status.in_(["ok", "running"]),
                                               m.Backup.started_at >= due.astimezone(UTC)).limit(1))
    if done:
        return {}
    failures_today = db.scalar(select(m.Backup.id).where(m.Backup.kind == "scheduled", m.Backup.status == "failed",
                                                         m.Backup.started_at >= now - timedelta(minutes=30)).limit(1))
    if failures_today:
        return {"waiting": "retry after a recent failure"}
    try:
        b = backup.create("scheduled")
    except Exception as e:
        raise_alert(db, Finding(
            key="backup:failed", severity="critical", component="backup", title="The daily backup failed",
            summary=f"{type(e).__name__}: {e}"[:800],
            likely_cause="pg_dump missing or wrong version, disk full, or the backup folder is not writable",
            remediation="Run `python -m jobpilot.ops backup` in the API container to see the error; check free "
                        "disk space and JOBPILOT_BACKUP_DIR. It retries in 30 minutes.", link="/settings"))
        db.commit()
        return {"failed": str(e)[:200]}
    resolve_alert(db, "backup:failed")
    db.commit()
    return {"created": b.name}


RETENTION_DAYS = {"idempotency_keys": 7, "login_attempts": 30, "error_events": 90, "health_checks": 90,
                  "resolved_notifications": 180}


def _housekeeping(db: Session, now: datetime) -> dict:
    """Prune operational records past their retention. Never touches applications, jobs or documents."""
    from sqlalchemy import delete

    out = {}
    for name, model, col, extra in (
            ("idempotency_keys", m.IdempotencyKey, m.IdempotencyKey.created_at, None),
            ("login_attempts", m.LoginAttempt, m.LoginAttempt.at, None),
            ("error_events", m.ErrorEvent, m.ErrorEvent.at, None),
            ("health_checks", m.HealthCheck, m.HealthCheck.at, None),
            ("resolved_notifications", m.Notification, m.Notification.resolved_at, m.Notification.resolved_at.is_not(None))):
        q = delete(model).where(col < now - timedelta(days=RETENTION_DAYS[name]))
        if extra is not None:
            q = q.where(extra)
        out[name] = db.execute(q).rowcount
    db.commit()
    return {k: v for k, v in out.items() if v}


def _watch_monitor(db: Session, now: datetime) -> str:
    hb, age = heartbeat_age(db, "monitor", now)
    factor = app_settings.get(db, "monitor").heartbeat_missed_factor
    if hb is None:
        status = "never_started"
    elif age > factor * hb.interval_s:
        status = "stale"
        raise_alert(db, Finding(
            key="heartbeat:monitor", severity="critical", component="monitor",
            title="The system monitor has stopped",
            summary=f"No monitor heartbeat for {int(age // 60)} min (expected every {hb.interval_s}s). "
                    "Failures elsewhere may go unnoticed.",
            likely_cause="The monitor process crashed or was not restarted",
            remediation="Restart it: docker compose up -d monitor (or python -m jobpilot.monitor).",
            link="/settings", context={"last_beat": hb.beat_at.isoformat(), "host": hb.detail.get("host")}))
    else:
        status = "ok"
        resolve_alert(db, "heartbeat:monitor")
    db.commit()
    return status


def tick(now: datetime | None = None, enqueue: Enqueue | None = None, sender=None) -> dict:
    now = now or datetime.now(UTC)
    enqueue = enqueue or default_enqueue
    # The lock lives on its own connection: the session below commits often and may switch connections.
    lock = get_engine().connect()
    try:
        if not lock.scalar(text("SELECT pg_try_advisory_lock(:k)"), {"k": TICK_LOCK}):
            return {"skipped": "another scheduler tick is running"}
        db = SessionLocal()
        try:
            beat(db, "scheduler", get_settings().scheduler_interval_s)
            db.commit()
            summary: dict = {"at": now.isoformat()}
            for name, step in (("dispatched", lambda: _dispatch_due(db, now, enqueue)),
                               ("stalled_marked_failed", lambda: _expire_stalled(db, now)),
                               ("paused", lambda: _pause_failing(db, now)),
                               ("follow_ups", lambda: _follow_ups(db, now.date())),
                               ("monitor", lambda: _watch_monitor(db, now)),
                               ("backup", lambda: _scheduled_backup(db, now)),
                               ("housekeeping", lambda: _housekeeping(db, now) if now.minute < 2 else {}),
                               ("emails", lambda: delivery.deliver_due(db, now, sender))):
                db.expire_all()  # runs execute in other sessions; never act on cached rows
                try:
                    summary[name] = step()
                except Exception as e:  # one failing step never stops the others
                    db.rollback()
                    log.exception("scheduler step %s failed", name)
                    summary[name] = {"error": f"{type(e).__name__}: {e}"[:300]}
                    db.add(m.ErrorEvent(component="scheduler", severity="critical", code=f"step_failed:{name}"[:64],
                                        message=summary[name]["error"]))
                    db.commit()
            beat(db, "scheduler", get_settings().scheduler_interval_s,
                 {"last_summary": {k: (v if not isinstance(v, list) else len(v)) for k, v in summary.items()}})
            db.commit()
            return summary
        finally:
            db.close()
            lock.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": TICK_LOCK})
    finally:
        lock.close()


def resume(db: Session, config_id: uuid.UUID) -> m.SearchConfig:
    c = db.get(m.SearchConfig, config_id)
    if c is None:
        raise DomainError("not_found", "Search configuration not found", status_code=404)
    now = datetime.now(UTC)
    c.paused_reason, c.paused_at, c.resumed_at = None, None, now
    c.next_run_at = schedule.next_run(c.cron, c.timezone, now) if c.cron else None
    resolve_alert(db, f"schedule-paused:{c.id}", by="user")
    db.flush()
    return c


def recover_run(db: Session, run_id: uuid.UUID) -> m.SearchRun:
    """You confirm a stuck run is dead: mark it failed so the search can run again."""
    r = db.scalar(select(m.SearchRun).where(m.SearchRun.id == run_id).with_for_update())
    if r is None:
        raise DomainError("not_found", "Search run not found", status_code=404)
    if r.status != "running":
        raise DomainError("invalid_state", "Only a running search can be stopped", {"status": r.status})
    now = datetime.now(UTC)
    r.status, r.finished_at = "failed", now
    r.summary = {**(r.summary or {}), "error": "stopped by you (marked as stuck)"}
    for a in db.scalars(select(m.AgentRun).where(m.AgentRun.run_id == r.id, m.AgentRun.status == "running")):
        a.status, a.finished_at = "failed", now
    db.add(m.ErrorEvent(component="orchestrator", severity="info", run_id=r.id, code="run_stopped_by_user",
                        message="Run marked as failed by the user"))
    db.flush()
    return r
