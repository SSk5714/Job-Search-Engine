"""Deterministic health checks. Each returns findings; none of them writes anything.

The monitor turns findings into alerts (and closes alerts whose condition cleared). It never
changes applications, runs, approvals or attempts: it reads them and tells you what to do.
"""

from __future__ import annotations

import zipfile
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from jobpilot.config import get_settings
from jobpilot.db import models as m
from jobpilot.domain.settings import MonitorSettings
from jobpilot.notify import Finding

P = "mon:"  # every alert the monitor owns starts with this, so it can close them when they clear
AI_CODES = {"rate_limited", "unreachable", "auth_failed", "api_error", "invalid_output", "truncated", "bad_request"}
PRE_SUBMIT = ("approved_for_preparation", "documents_ready", "form_prepared", "awaiting_user_review",
              "needs_manual_input")


class Ctx:
    def __init__(self, db: Session, now: datetime, cfg: MonitorSettings):
        self.db, self.now, self.cfg = db, now, cfg


def _ago(now: datetime, then: datetime) -> str:
    mins = int((now - then).total_seconds() // 60)
    return f"{mins} min" if mins < 120 else (f"{mins // 60} h" if mins < 48 * 60 else f"{mins // 1440} days")


# ── Infrastructure ──────────────────────────────────────────────────────────


def database(c: Ctx) -> list[Finding]:
    import time

    t = time.monotonic()
    c.db.execute(text("SELECT 1"))
    ms = (time.monotonic() - t) * 1000
    if ms > 1000:
        return [Finding(f"{P}db:slow", "warning", "database", "The database is slow",
                        f"A trivial query took {ms:.0f} ms.", "Check the database server load and disk.",
                        likely_cause="Database overloaded or low on resources")]
    return []


def queue(c: Ctx) -> list[Finding]:
    url = get_settings().redis_url
    if not url:
        return []
    import redis

    try:
        r = redis.Redis.from_url(url, socket_timeout=2)
        r.ping()
        depth = r.llen("celery")
    except Exception as e:
        return [Finding(f"{P}queue:down", "critical", "queue", "The task queue is unreachable",
                        f"Redis did not answer: {type(e).__name__}.",
                        "Start Redis (docker compose up -d redis) and check JOBPILOT_REDIS_URL.",
                        likely_cause="Redis stopped or the network is down", workflow_paused=True)]
    out = []
    if depth > 50:
        out.append(Finding(f"{P}queue:backlog", "warning", "queue", "Tasks are piling up",
                           f"{depth} tasks are waiting in the queue.",
                           "Check that the worker is running: docker compose up -d worker.",
                           likely_cause="No worker is consuming the queue, or it is overloaded"))
    return out


def _heartbeat(c: Ctx, component: str, title: str, remediation: str, paused: bool) -> list[Finding]:
    hb = c.db.get(m.Heartbeat, component)
    if hb is None:
        return []
    age = (c.now - hb.beat_at).total_seconds()
    if age > c.cfg.heartbeat_missed_factor * hb.interval_s:
        return [Finding(f"{P}heartbeat:{component}", "critical", component, title,
                        f"Last heartbeat {_ago(c.now, hb.beat_at)} ago (expected every {hb.interval_s}s).",
                        remediation, likely_cause="The process crashed, was stopped, or cannot reach the database",
                        workflow_paused=paused, context={"last_beat": hb.beat_at.isoformat(),
                                                         "host": (hb.detail or {}).get("host")})]
    return []


def scheduler(c: Ctx) -> list[Finding]:
    scheduled = c.db.scalar(select(func.count()).select_from(m.SearchConfig).where(
        m.SearchConfig.cron.is_not(None), m.SearchConfig.enabled.is_(True))) or 0
    hb = c.db.get(m.Heartbeat, "scheduler")
    if scheduled and hb is None:
        return [Finding(f"{P}heartbeat:scheduler", "critical", "scheduler", "Scheduled searches are not running",
                        f"{scheduled} search(es) have a schedule, but the scheduler has never started.",
                        "Start it: docker compose up -d beat worker (or python -m jobpilot.scheduler).",
                        likely_cause="The scheduler process is not deployed or not started", workflow_paused=True)]
    return _heartbeat(c, "scheduler", "The scheduler has stopped",
                      "Restart it: docker compose up -d beat worker (or python -m jobpilot.scheduler). "
                      "Missed searches run once when it is back.", paused=bool(scheduled))


def schedules(c: Ctx) -> list[Finding]:
    out = []
    grace = timedelta(minutes=10)
    hb = c.db.get(m.Heartbeat, "scheduler")
    alive = hb is not None and (c.now - hb.beat_at).total_seconds() <= c.cfg.heartbeat_missed_factor * hb.interval_s
    for cfg in c.db.scalars(select(m.SearchConfig).where(m.SearchConfig.cron.is_not(None),
                                                         m.SearchConfig.enabled.is_(True),
                                                         m.SearchConfig.paused_reason.is_(None))).all():
        if alive and cfg.next_run_at and cfg.next_run_at < c.now - grace:
            out.append(Finding(f"{P}schedule-overdue:{cfg.id}", "warning", "scheduler",
                               f"Scheduled search “{cfg.name}” did not start",
                               f"It was due {_ago(c.now, cfg.next_run_at)} ago and the scheduler is running.",
                               "Check the scheduler logs; run the search by hand meanwhile.",
                               likely_cause="The scheduler tick fails before starting searches", link="/discovery"))
        last = c.db.scalar(select(m.ScheduleDispatch).where(m.ScheduleDispatch.config_id == cfg.id)
                           .order_by(m.ScheduleDispatch.due_at.desc()).limit(1))
        if last is not None and last.outcome == "failed_to_start":
            out.append(Finding(f"{P}schedule-failed:{cfg.id}", "critical", "scheduler",
                               f"Scheduled search “{cfg.name}” failed to start", last.detail or "",
                               "Run it by hand in Job Discovery to see the error; fix the cause.",
                               link="/discovery", context={"due_at": last.due_at.isoformat()}))
        skipped = c.db.scalars(select(m.ScheduleDispatch).where(m.ScheduleDispatch.config_id == cfg.id)
                               .order_by(m.ScheduleDispatch.due_at.desc()).limit(3)).all()
        if len(skipped) == 3 and all(d.outcome == "skipped_overlap" for d in skipped):
            out.append(Finding(f"{P}schedule-overlap:{cfg.id}", "warning", "scheduler",
                               f"“{cfg.name}” keeps skipping: the previous run never finishes",
                               "The last 3 scheduled times were skipped because a run was still in progress.",
                               "Open the run in Job Discovery; if it is stuck, press Stop. Or schedule less often.",
                               likely_cause="A stuck run, or runs longer than the schedule interval", link="/discovery"))
    return out


# ── Runs and tasks ──────────────────────────────────────────────────────────


def stalled_runs(c: Ctx) -> list[Finding]:
    limit = c.now - timedelta(minutes=c.cfg.run_stall_alert_minutes)
    out = []
    for r in c.db.scalars(select(m.SearchRun).where(m.SearchRun.status == "running",
                                                    m.SearchRun.started_at < limit)).all():
        busy = c.db.scalar(select(m.AgentRun).where(m.AgentRun.run_id == r.id, m.AgentRun.status == "running")
                           .order_by(m.AgentRun.started_at.desc()).limit(1))
        out.append(Finding(f"{P}run-stalled:{r.id}", "warning", "orchestrator", "A search run looks stuck",
                           f"Running for {_ago(c.now, r.started_at)}" +
                           (f"; still waiting on {busy.agent}:{busy.subject}." if busy else "."),
                           f"It is marked failed automatically after {get_settings().run_stall_minutes} min. "
                           "To stop it now, press Stop on the run in Job Discovery.",
                           likely_cause="The worker stopped, or a source is very slow",
                           run_id=r.id, task_id=busy.id if busy else None, link="/discovery"))
    return out


def failed_runs(c: Ctx) -> list[Finding]:
    out = []
    for cfg in c.db.scalars(select(m.SearchConfig)).all():
        last = c.db.scalar(select(m.SearchRun).where(m.SearchRun.config_id == cfg.id, m.SearchRun.status != "running")
                           .order_by(m.SearchRun.started_at.desc()).limit(1))
        if last is not None and last.status == "failed" and last.finished_at and \
                c.now - last.finished_at < timedelta(days=2):
            summ = last.summary or {}
            errs = summ.get("error") or ", ".join(f"{k}: {v.get('error')}" for k, v in (summ.get("sources") or {}).items()
                                                 if v.get("status") == "failed")
            out.append(Finding(f"{P}run-failed:{cfg.id}", "warning", "orchestrator",
                               f"The last run of “{cfg.name}” failed", errs or "No details recorded.",
                               "Check the source settings and run again. One broken source never stops the others.",
                               run_id=last.id, link="/discovery"))
    return out


SOURCE_HINTS = {
    "forbidden": ("The source refused access (HTTP 403)", "Run `./jp exec api python -m jobpilot.ops probe-ba` "
                  "(for Bundesagentur) to see what the source accepts, and check for a JobPilot update. If it stays "
                  "refused, untick the source in Job Discovery."),
    "http_403": ("The source refused access", "Check whether the source changed its terms or blocks automated access; "
                 "disable it if so."),
    "http_404": ("A board or company name no longer exists", "Fix the company/board names in the search settings."),
    "http_429": ("Rate limited by the source", "Search less often."),
    "timeout": ("The source is slow or down", "Usually temporary; it retries next run."),
    "unexpected_format": ("The source answered in a format JobPilot does not read", "Run `./jp exec api python -m "
                          "jobpilot.ops probe-ba` and check for a JobPilot update."),
    "needs_configuration": ("The source needs settings", "Add the company/board names in the search settings."),
}


def repeated_failures(c: Ctx) -> list[Finding]:
    out = []
    since = c.now - timedelta(days=3)
    rows = c.db.execute(
        select(m.AgentRun.agent, m.AgentRun.subject, m.TaskAttempt.status, m.TaskAttempt.error_code,
               m.AgentRun.run_id, m.AgentRun.id)
        .join(m.TaskAttempt, m.TaskAttempt.agent_run_id == m.AgentRun.id)
        .where(m.TaskAttempt.created_at >= since, m.AgentRun.agent == "discovery")
        .order_by(m.TaskAttempt.created_at.desc())).all()
    by: dict[str, list] = defaultdict(list)
    for agent, subject, status, code, run_id, ar_id in rows:
        by[f"{agent}:{subject}"].append((status, code, run_id, ar_id))
    n = c.cfg.repeated_failures
    for key, items in by.items():
        last = items[:n]
        if len(last) == n and all(s == "failed" for s, *_ in last):
            codes = Counter(code for _, code, *_ in last)
            code = codes.most_common(1)[0][0] or "unknown"
            cause, fix = SOURCE_HINTS.get(code, (None, "Open the latest run in Job Discovery for the error message."))
            out.append(Finding(f"{P}repeated:{key}", "warning", key.split(":")[0],
                               f"{key.split(':', 1)[1]} failed {n} times in a row",
                               f"Last error: {code}.", fix, likely_cause=cause, run_id=last[0][2],
                               task_id=last[0][3], link="/discovery"))
    return out


def error_spike(c: Ctx) -> list[Finding]:
    since = c.now - timedelta(hours=1)
    rows = c.db.execute(select(m.ErrorEvent.component, func.count()).where(m.ErrorEvent.at >= since)
                        .group_by(m.ErrorEvent.component)).all()
    total = sum(n for _, n in rows)
    if total >= c.cfg.error_spike_per_hour:
        top = ", ".join(f"{comp} ({n})" for comp, n in sorted(rows, key=lambda r: -r[1])[:4])
        return [Finding(f"{P}error-spike", "warning", "system", "Unusually many errors",
                        f"{total} errors in the last hour: {top}.",
                        "Open Settings & Health → recent errors to see what is failing.",
                        likely_cause="One failing component retrying, or an outage of a dependency")]
    return []


def claude_api(c: Ctx) -> list[Finding]:
    since = c.now - timedelta(hours=1)
    rows = c.db.execute(select(m.ErrorEvent.code, func.count(), func.max(m.ErrorEvent.at))
                        .where(m.ErrorEvent.at >= since, m.ErrorEvent.component.like("%:claude"),
                               m.ErrorEvent.code.in_(AI_CODES)).group_by(m.ErrorEvent.code)).all()
    counts = {code: n for code, n, _ in rows}
    out = []
    if counts.get("auth_failed"):
        out.append(Finding(f"{P}claude:auth", "critical", "claude_api", "Claude rejected the API key",
                           "Matching and document writing fall back to the no-AI versions until this is fixed.",
                           "Set a valid JOBPILOT_ANTHROPIC_API_KEY on the server and restart the API and worker.",
                           likely_cause="The key is wrong, revoked or has no credit"))
    if counts.get("rate_limited", 0) >= 1:
        out.append(Finding(f"{P}claude:rate", "warning", "claude_api", "Claude API rate limits hit",
                           f"{counts['rate_limited']} rate-limited call(s) in the last hour; those jobs were "
                           "scored by rules instead.",
                           "Lower “AI jobs per run” in Settings & Health, or search less often.",
                           likely_cause="Too many requests for your API tier"))
    transient = sum(counts.get(k, 0) for k in ("unreachable", "api_error", "truncated", "invalid_output"))
    if transient >= c.cfg.claude_failures_per_hour:
        out.append(Finding(f"{P}claude:errors", "warning", "claude_api", "Claude API calls are failing",
                           f"{transient} failed call(s) in the last hour (" +
                           ", ".join(f"{k} {v}" for k, v in counts.items() if k not in ("auth_failed", "rate_limited")) +
                           "). The rule-based fallback was used.",
                           "Usually temporary. If it persists, check status.anthropic.com and the server's network.",
                           likely_cause="Timeouts, outages or malformed outputs"))
    return out


def browser(c: Ctx) -> list[Finding]:
    since = c.now - timedelta(hours=24)
    rows = c.db.scalars(select(m.ErrorEvent).where(m.ErrorEvent.at >= since, m.ErrorEvent.component == "browser")
                        .order_by(m.ErrorEvent.at.desc())).all()
    # a wrong or invented address is the link's problem, not the browser's
    rows = [r for r in rows if "ERR_NAME_NOT_RESOLVED" not in (r.message or "")]
    if not rows:
        return []
    codes = Counter(r.code for r in rows)
    return [Finding(f"{P}browser", "warning", "browser", "The application browser had problems",
                    f"{len(rows)} browser failure(s) in the last 24 h: " +
                    ", ".join(f"{k} ×{v}" for k, v in codes.most_common(3)) + f". Latest: {rows[0].message[:200]}",
                    "Retry the preparation. If one site keeps failing, apply there yourself. If all fail, check "
                    "that Chromium is installed in the API image (playwright install chromium).",
                    likely_cause="Slow or changed employer page, or a missing/crashed browser",
                    task_id=rows[0].task_id)]


# ── Applications and documents ──────────────────────────────────────────────


def documents(c: Ctx) -> list[Finding]:
    root = Path(get_settings().documents_dir)
    out = []
    docs = c.db.execute(
        select(m.Document, m.Application.state).join(m.Application, m.Application.id == m.Document.application_id)
        .where(m.Document.status == "ready", m.Application.state.in_(PRE_SUBMIT))).all()
    for doc, _state in docs:
        problems = []
        for fmt, rel in (("PDF", doc.pdf_path), ("DOCX", doc.docx_path)):
            if not rel:
                problems.append(f"{fmt} missing")
                continue
            p = root / rel
            try:
                if not p.is_file() or p.stat().st_size < 200:
                    problems.append(f"{fmt} file missing or empty")
                elif fmt == "PDF" and not p.read_bytes()[:5] == b"%PDF-":
                    problems.append("PDF file corrupt")
                elif fmt == "DOCX" and not (zipfile.is_zipfile(p) and "word/document.xml" in zipfile.ZipFile(p).namelist()):
                    problems.append("DOCX file corrupt")
            except OSError as e:
                problems.append(f"{fmt} unreadable ({type(e).__name__})")
        if problems:
            kind = "CV" if doc.kind == "cv" else "cover letter"
            out.append(Finding(f"{P}document:{doc.id}", "critical", "documents",
                               f"Your {kind} v{doc.version_no} file is damaged",
                               "; ".join(problems) + ". It cannot be attached or downloaded safely.",
                               "Open Application Review and press Regenerate (or edit and save a new version). "
                               "Check the documents volume and its backups.",
                               likely_cause="The documents volume was lost, changed or not mounted",
                               workflow_paused=True, task_id=doc.id, link=f"/review?id={doc.application_id}"))
    return out


def listings(c: Ctx) -> list[Finding]:
    out = []
    rows = c.db.execute(select(m.Application, m.Job).join(m.Job, m.Job.id == m.Application.job_id)
                        .where(m.Application.state.in_(PRE_SUBMIT), m.Job.availability == "closed")).all()
    for app, job in rows:
        out.append(Finding(f"{P}listing-closed:{app.id}", "warning", "discovery",
                           f"Listing closed: {job.title} at {job.company}",
                           "The job you are preparing is no longer listed.",
                           "Check the employer's site. If it is gone, withdraw the application in the Tracker.",
                           likely_cause="The employer filled or removed the role", link=f"/review?id={app.id}"))
    return out


def stuck_applications(c: Ctx) -> list[Finding]:
    out = []
    labels = {"approved_for_preparation": ("info", "Generate the CV and cover letter, or reject the job."),
              "documents_ready": ("info", "Prepare the application form, or withdraw."),
              "form_prepared": ("warning", "Open Application Review; prepare the form again if needed."),
              "awaiting_user_review": ("info", "Review and approve, or withdraw it."),
              "needs_manual_input": ("warning", "Open the application and answer what it asks."),
              "failed": ("warning", "Open the application in the Tracker and retry or withdraw.")}
    for state, hours in c.cfg.stuck_hours.items():
        limit = c.now - timedelta(hours=hours)
        for app in c.db.scalars(select(m.Application).where(m.Application.state == state,
                                                            m.Application.last_action_at < limit)).all():
            sev, fix = labels.get(state, ("info", "Open the application."))
            out.append(Finding(f"{P}stuck:{app.id}", sev, "workflow",
                               f"Waiting {_ago(c.now, app.last_action_at)} in “{state.replace('_', ' ')}”: "
                               f"{app.job.title} at {app.job.company}",
                               f"Threshold for this state is {hours} h.", fix,
                               workflow_paused=state == "needs_manual_input", link=f"/review?id={app.id}"))
    return out


def duplicates(c: Ctx) -> list[Finding]:
    out = []
    for app_id, n in c.db.execute(select(m.SubmissionAttempt.application_id, func.count())
                                  .where(m.SubmissionAttempt.status == "succeeded")
                                  .group_by(m.SubmissionAttempt.application_id).having(func.count() > 1)).all():
        out.append(Finding(f"{P}dup-submit:{app_id}", "critical", "submission", "Possible duplicate submission",
                           f"{n} successful submissions recorded for one application.",
                           "Check the employer portal; if you applied twice, tell the employer and keep one.",
                           link=f"/review?id={app_id}"))
    for a in c.db.scalars(select(m.SubmissionAttempt).where(
            m.SubmissionAttempt.status == "pending",
            m.SubmissionAttempt.started_at < c.now - timedelta(minutes=10))).all():
        out.append(Finding(f"{P}submit-stuck:{a.id}", "critical", "submission", "A submission never finished",
                           f"Started {_ago(c.now, a.started_at)} ago and still pending.",
                           "Do not submit again. Check the employer portal, then record the outcome. "
                           "It will not retry on its own.", likely_cause="The API stopped during submission",
                           workflow_paused=True, task_id=a.id, link=f"/review?id={a.application_id}"))
    for a in c.db.scalars(select(m.SubmissionAttempt).where(m.SubmissionAttempt.status == "unknown")).all():
        app = c.db.get(m.Application, a.application_id)
        if app is not None and app.state != "needs_manual_input":
            out.append(Finding(f"{P}submit-unknown:{a.id}", "critical", "submission",
                               "A submission's outcome is unclear",
                               f"Attempt {a.id} has an unknown outcome but the application is in “{app.state}”.",
                               "Check the employer portal, then record whether it arrived.",
                               workflow_paused=True, task_id=a.id, link=f"/review?id={app.id}"))
    # the same role (company + title) being worked on, or sent, twice through different listings
    rows = c.db.execute(select(m.Application.id, m.Application.state, m.Job.fingerprint, m.Job.title, m.Job.company)
                        .join(m.Job, m.Job.id == m.Application.job_id)
                        .where(m.Application.state.in_(PRE_SUBMIT + ("submitted", "follow_up")))).all()
    groups: dict[str, list] = defaultdict(list)
    for r in rows:
        groups[r.fingerprint].append(r)
    for fp, items in groups.items():
        if len(items) > 1:
            out.append(Finding(f"{P}dup-app:{fp[:16]}", "warning", "workflow",
                               f"Two applications for the same role: {items[0].title} at {items[0].company}",
                               f"{len(items)} applications ({', '.join(i.state for i in items)}).",
                               "Keep one and withdraw the other in the Tracker, so you do not apply twice.",
                               likely_cause="The role was listed on two sites", link="/tracker"))
    return out


def deliveries(c: Ctx) -> list[Finding]:
    out = []
    failed = c.db.scalar(select(func.count()).select_from(m.NotificationDelivery).where(
        m.NotificationDelivery.status == "failed",
        m.NotificationDelivery.updated_at >= c.now - timedelta(days=7))) or 0
    if failed:
        out.append(Finding(f"{P}delivery:failed", "warning", "notifications",
                           f"{failed} email notification(s) could not be delivered in the last 7 days",
                           "In-app notifications are unaffected.",
                           "Check the SMTP settings and send a test email from Settings & Health; then press Retry "
                           "on the failed notifications.", link="/notifications"))
    overdue = c.db.scalar(select(func.count()).select_from(m.NotificationDelivery).where(
        m.NotificationDelivery.status.in_(["pending", "sending"]),
        m.NotificationDelivery.next_attempt_at < c.now - timedelta(minutes=30))) or 0
    if overdue:
        out.append(Finding(f"{P}delivery:stuck", "warning", "notifications", "Emails are not being sent",
                           f"{overdue} email(s) have been waiting for more than 30 minutes.",
                           "The scheduler sends emails; check that it is running.",
                           likely_cause="The scheduler is stopped", link="/settings"))
    return out


def backups(c: Ctx) -> list[Finding]:
    s = get_settings()
    if not s.backup_at:
        return [Finding(f"{P}backup:off", "info", "backup", "Daily backups are turned off",
                        "JOBPILOT_BACKUP_AT is empty, so nothing backs up your data automatically.",
                        "Set JOBPILOT_BACKUP_AT (e.g. 03:15) and copy the backup folder off the server regularly.")]
    last = c.db.scalar(select(m.Backup).where(m.Backup.status == "ok", m.Backup.kind.in_(["scheduled", "manual"]))
                       .order_by(m.Backup.started_at.desc()).limit(1))
    first_user = c.db.scalar(select(func.min(m.User.created_at)))
    age_ref = last.started_at if last else first_user
    if age_ref is not None and c.now - age_ref > timedelta(hours=26):
        return [Finding(f"{P}backup:stale", "warning", "backup", "No recent backup",
                        ("Last successful backup " + _ago(c.now, last.started_at) + " ago.") if last else
                        "No backup has been made yet.",
                        "Check that the scheduler is running and the backup folder is writable; make one now with "
                        "`python -m jobpilot.ops backup` or the button in Settings & Health.",
                        likely_cause="Scheduler stopped, or backups keep failing", link="/settings")]
    return []


def ai_budget(c: Ctx) -> list[Finding]:
    from jobpilot.domain import settings as app_settings

    budget = app_settings.get(c.db, "ai").daily_budget_usd
    if not budget:
        return []
    start = c.now.replace(hour=0, minute=0, second=0, microsecond=0)
    spent = float(c.db.scalar(select(func.coalesce(func.sum(m.TaskAttempt.ai_cost_usd), 0))
                              .where(m.TaskAttempt.created_at >= start)) or 0)
    if spent >= 0.8 * budget:
        full = spent >= budget
        return [Finding(f"{P}ai-budget", "warning" if full else "info", "claude_api",
                        "Daily Claude budget used up" if full else "Daily Claude budget almost used",
                        f"${spent:.2f} of ${budget:.2f} spent today (UTC).",
                        "Nothing breaks: rule-based matching and the template writer take over. Raise the budget "
                        "in Settings & Health if you want more Claude evaluations today.")]
    return []


CHECKS = [("database", database), ("queue", queue), ("scheduler", scheduler), ("schedules", schedules),
          ("stalled_runs", stalled_runs), ("failed_runs", failed_runs), ("repeated_failures", repeated_failures),
          ("error_spike", error_spike), ("claude_api", claude_api), ("browser", browser),
          ("documents", documents), ("listings", listings), ("stuck_applications", stuck_applications),
          ("duplicates", duplicates), ("deliveries", deliveries), ("backups", backups), ("ai_budget", ai_budget)]

# alert-key prefix owned by each check, so a check that errored never closes its own alerts
OWNS = {"database": ["db:"], "queue": ["queue:"], "scheduler": ["heartbeat:scheduler"],
        "schedules": ["schedule-overdue:", "schedule-failed:", "schedule-overlap:"],
        "stalled_runs": ["run-stalled:"], "failed_runs": ["run-failed:"], "repeated_failures": ["repeated:"],
        "error_spike": ["error-spike"], "claude_api": ["claude:"], "browser": ["browser"],
        "documents": ["document:"], "listings": ["listing-closed:"], "stuck_applications": ["stuck:"],
        "duplicates": ["dup-submit:", "submit-stuck:", "submit-unknown:", "dup-app:"],
        "deliveries": ["delivery:"], "backups": ["backup:"], "ai_budget": ["ai-budget"]}
