"""Acceptance criterion 10: the monitor detects simulated failures and raises actionable alerts,
without changing any workflow data."""

import json
import os
import subprocess
import sys
import time
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import select, text, update

from jobpilot.config import get_settings
from jobpilot.db import models as m
from jobpilot.db.session import SessionLocal, reset_engine
from jobpilot.monitor import service
from jobpilot.orchestrator.scheduler import tick

from tests.conftest import BACKEND, documents_ready_app, run_mock_search, verify_facts

WORKFLOW_TABLES = ["applications", "application_state_history", "jobs", "search_runs", "agent_runs", "task_attempts",
                   "submission_attempts", "approvals", "documents", "form_fields", "search_configs",
                   "schedule_dispatches", "follow_ups", "profile_facts"]


def snapshot() -> dict:
    with SessionLocal() as db:
        return {t: db.scalar(text(f"SELECT md5(coalesce(string_agg(x::text, '|' ORDER BY x::text), '')) FROM {t} x"))
                for t in WORKFLOW_TABLES}


def alerts(api, prefix="mon:"):
    return {a["alert_key"]: a for a in api.get("/alerts").json() if (a["alert_key"] or "").startswith(prefix)}


def assert_actionable(a):
    """Spec: severity, component, ids, timestamp, summary, likely cause when known, remediation, paused."""
    assert a["severity"] in ("info", "warning", "critical")
    assert a["component"] and a["title"] and a["body"] and a["remediation"]
    assert a["created_at"] and isinstance(a["workflow_paused"], bool)


def _add(*rows):
    with SessionLocal() as db:
        for r in rows:
            db.add(r)
        db.commit()


def _config_id():
    with SessionLocal() as db:
        return db.scalar(select(m.SearchConfig.id))


def test_healthy_system_has_no_alerts(api):
    verify_facts(api)
    run_mock_search(api)
    out = service.run_once()
    assert out["findings"] == 0, out
    assert set(out["status"].values()) == {"ok"}
    with SessionLocal() as db:
        assert db.get(m.Heartbeat, "monitor") is not None


def test_simulated_failures_raise_actionable_alerts_and_change_nothing(api):
    verify_facts(api)
    run_mock_search(api)
    cfg = _config_id()
    now = datetime.now(UTC)
    with SessionLocal() as db:
        app = db.scalar(select(m.Application).where(m.Application.state == "classified").limit(1))
        app_id, job_id = app.id, app.job_id
    _add(
        # scheduler with a schedule but a stale heartbeat
        m.Heartbeat(component="scheduler", beat_at=now - timedelta(minutes=30), interval_s=60,
                    started_at=now - timedelta(hours=2), detail={}),
        # a run stuck for an hour
        m.SearchRun(config_id=cfg, trigger="schedule", status="running", allow_overlap=True,
                    started_at=now - timedelta(hours=1)),
        # spike of Claude, browser and source errors
        *[m.ErrorEvent(component="matching:claude", severity="warning", code="unreachable", message="timeout")
          for _ in range(4)],
        m.ErrorEvent(component="matching:claude", severity="warning", code="auth_failed", message="401"),
        m.ErrorEvent(component="browser", severity="warning", code="TimeoutError", message="page did not load"),
        *[m.ErrorEvent(component="discovery:greenhouse", severity="warning", code="http_500", message="x")
          for _ in range(16)],
        # a schedule that could not start
        m.ScheduleDispatch(config_id=cfg, due_at=now - timedelta(hours=1), outcome="failed_to_start",
                           detail="ConnectionError: queue"),
    )
    with SessionLocal() as db:
        db.execute(update(m.SearchConfig).values(cron="0 6 * * *", next_run_at=now + timedelta(hours=3)))
        # an application waiting far too long, whose listing has closed
        db.execute(update(m.Application).where(m.Application.id == app_id).values(
            state="needs_manual_input", last_action_at=now - timedelta(days=5)))
        db.execute(update(m.Job).where(m.Job.id == job_id).values(availability="closed"))
        # three failed attempts in a row for one source
        for i in range(3):
            ar = m.AgentRun(agent="discovery", subject="lever", status="failed")
            db.add(ar)
            db.flush()
            db.add(m.TaskAttempt(agent_run_id=ar.id, attempt_no=1, status="failed", error_code="http_404",
                                 created_at=now - timedelta(minutes=i)))
        # a submission that never finished, and an email that could not be delivered
        appr = m.Approval(application_id=app_id, decision="approved", document_hashes={}, form_hash="x", approved_at=now)
        db.add(appr)
        db.flush()
        db.add(m.SubmissionAttempt(application_id=app_id, approval_id=appr.id, idempotency_key="k1",
                                   status="pending", started_at=now - timedelta(minutes=30)))
        n = m.Notification(kind="alert", severity="critical", title="x", body="x")
        db.add(n)
        db.flush()
        db.add(m.NotificationDelivery(notification_id=n.id, channel="email", status="failed", attempts=5))
        db.commit()

    before = snapshot()
    service.run_once()
    assert snapshot() == before, "the monitor must not change workflow data"

    found = alerts(api)
    expected = {
        "mon:heartbeat:scheduler": ("critical", "scheduler"),
        "mon:run-stalled:": ("warning", "orchestrator"),
        "mon:claude:auth": ("critical", "claude_api"),
        "mon:claude:errors": ("warning", "claude_api"),
        "mon:browser": ("warning", "browser"),
        "mon:error-spike": ("warning", "system"),
        "mon:schedule-failed:": ("critical", "scheduler"),
        "mon:stuck:": ("warning", "workflow"),
        "mon:listing-closed:": ("warning", "discovery"),
        "mon:repeated:discovery:lever": ("warning", "discovery"),
        "mon:submit-stuck:": ("critical", "submission"),
        "mon:delivery:failed": ("warning", "notifications"),
    }
    for prefix, (sev, comp) in expected.items():
        match = [a for k, a in found.items() if k.startswith(prefix)]
        assert match, f"no alert for {prefix}; got {sorted(found)}"
        a = match[0]
        assert (a["severity"], a["component"]) == (sev, comp), (prefix, a)
        assert_actionable(a)
    assert found["mon:heartbeat:scheduler"]["workflow_paused"] is True
    assert next(a for k, a in found.items() if k.startswith("mon:run-stalled:"))["run_id"]
    assert next(a for k, a in found.items() if k.startswith("mon:submit-stuck:"))["task_id"]
    assert "board or company name" in found["mon:repeated:discovery:lever"]["likely_cause"]

    # running again does not duplicate anything
    service.run_once()
    again = alerts(api)
    assert set(again) == set(found)
    assert again["mon:browser"]["occurrences"] == 2


def test_alerts_close_when_the_problem_is_fixed(api):
    cfg = _config_id()
    _add(m.SearchRun(config_id=cfg, trigger="manual", status="running", started_at=datetime.now(UTC) - timedelta(hours=1)))
    service.run_once()
    key = next(k for k in alerts(api) if k.startswith("mon:run-stalled:"))
    with SessionLocal() as db:
        db.execute(update(m.SearchRun).values(status="completed", finished_at=datetime.now(UTC)))
        db.commit()
    service.run_once()
    assert key not in alerts(api)
    closed = next(a for a in api.get("/alerts?status=all").json() if a["alert_key"] == key)
    assert closed["resolved_by"] == "monitor"


def test_missing_and_corrupt_documents_are_detected(api):
    app_id = documents_ready_app(api)
    root = Path(get_settings().documents_dir)
    with SessionLocal() as db:
        cv = db.scalar(select(m.Document).where(m.Document.application_id == uuid.UUID(app_id), m.Document.kind == "cv",
                                                m.Document.status == "ready"))
        letter = db.scalar(select(m.Document).where(m.Document.application_id == uuid.UUID(app_id),
                                                    m.Document.kind == "cover_letter", m.Document.status == "ready"))
    (root / cv.pdf_path).unlink()
    (root / letter.docx_path).write_bytes(b"not a zip file" * 100)
    service.run_once()
    found = alerts(api, "mon:document:")
    assert len(found) == 2
    bodies = " ".join(a["body"] for a in found.values())
    assert "PDF file missing" in bodies and "DOCX file corrupt" in bodies
    assert all(a["workflow_paused"] and a["severity"] == "critical" for a in found.values())


def test_duplicate_applications_and_unclear_submissions(api):
    verify_facts(api)
    run_mock_search(api)
    with SessionLocal() as db:
        a1, a2 = db.scalars(select(m.Application).limit(2)).all()
        j2 = db.get(m.Job, a2.job_id)
        j2.fingerprint = db.get(m.Job, a1.job_id).fingerprint  # same role listed twice
        a1.state, a2.state = "submitted", "documents_ready"
        appr = m.Approval(application_id=a1.id, decision="approved", document_hashes={}, form_hash="x", approved_at=datetime.now(UTC))
        db.add(appr)
        db.flush()
        db.add(m.SubmissionAttempt(application_id=a1.id, approval_id=appr.id, idempotency_key="u1", status="unknown"))
        db.commit()
    service.run_once()
    found = alerts(api)
    assert any(k.startswith("mon:dup-app:") for k in found)
    unk = next(a for k, a in found.items() if k.startswith("mon:submit-unknown:"))
    assert unk["severity"] == "critical" and unk["workflow_paused"]


def test_queue_down_is_detected(api, monkeypatch):
    monkeypatch.setenv("JOBPILOT_REDIS_URL", "redis://127.0.0.1:1/0")
    get_settings.cache_clear()
    try:
        service.run_once()
    finally:
        monkeypatch.undo()
        get_settings.cache_clear()
    a = alerts(api)["mon:queue:down"]
    assert a["severity"] == "critical" and "Redis" in a["remediation"]


def test_a_crashing_check_is_reported_and_keeps_its_alerts(api, monkeypatch):
    cfg = _config_id()
    _add(m.SearchRun(config_id=cfg, trigger="manual", status="running", started_at=datetime.now(UTC) - timedelta(hours=1)))
    service.run_once()
    assert any(k.startswith("mon:run-stalled:") for k in alerts(api))

    def boom(ctx):
        raise RuntimeError("bug in check")

    from jobpilot.monitor import checks

    monkeypatch.setattr(checks, "CHECKS", [(n, boom if n == "stalled_runs" else f) for n, f in checks.CHECKS])
    with SessionLocal() as db:
        db.execute(update(m.SearchRun).values(status="completed"))
        db.commit()
    out = service.run_once()
    assert out["status"]["stalled_runs"] == "error"
    found = alerts(api)
    assert "mon:check-error:stalled_runs" in found
    assert any(k.startswith("mon:run-stalled:") for k in found)  # not closed by a check that did not run


def test_database_outage_is_logged_emailed_once_and_recorded_after(api, tmp_path, monkeypatch):
    sent = []
    fallback = tmp_path / "fallback.jsonl"
    real_db = os.environ["JOBPILOT_DATABASE_URL"]
    for k, v in {"MONITOR_FALLBACK_LOG": str(fallback), "SMTP_HOST": "127.0.0.1", "EMAIL_FROM": "a@example.org",
                 "NOTIFY_EMAIL_TO": "b@example.org",
                 "DATABASE_URL": "postgresql+psycopg://postgres@127.0.0.1:1/nowhere"}.items():
        monkeypatch.setenv(f"JOBPILOT_{k}", v)
    get_settings.cache_clear()
    reset_engine()
    mon = service.Monitor(sender=sent.append)
    assert mon.cycle()["database"] == "down"
    assert mon.cycle()["database"] == "down"
    assert len(sent) == 1 and "Database unreachable" in sent[0]["Subject"]
    records = [json.loads(x) for x in fallback.read_text().splitlines()]
    assert len(records) == 2 and records[0]["event"] == "database_unreachable" and records[0]["remediation"]

    monkeypatch.setenv("JOBPILOT_DATABASE_URL", real_db)  # the database is back
    get_settings.cache_clear()
    reset_engine()
    mon.cycle()
    a = next(a for a in api.get("/alerts").json() if a["alert_key"].startswith("db-outage:"))
    assert a["component"] == "database" and a["can_resolve"]
    assert json.loads(fallback.read_text().splitlines()[-1])["event"] == "database_recovered"


def test_monitor_runs_as_its_own_process_and_its_death_is_noticed(api):
    env = {**os.environ, "JOBPILOT_MONITOR_INTERVAL_S": "1", "JOBPILOT_REDIS_URL": ""}
    proc = subprocess.Popen([sys.executable, "-m", "jobpilot.monitor"], cwd=BACKEND, env=env,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    try:
        deadline = time.time() + 30
        while time.time() < deadline:
            with SessionLocal() as db:
                hb = db.get(m.Heartbeat, "monitor")
                if hb and (hb.detail or {}).get("checks"):
                    break
            time.sleep(0.5)
        else:
            pytest.fail("monitor process wrote no heartbeat: " + proc.stdout.read1().decode()[-2000:])
        assert api.get("/health/details").json()["checks"]["monitor"]["status"] == "ok"
    finally:
        proc.terminate()
        proc.wait(10)
    # the monitor is gone: a scheduler tick a few minutes later raises the alarm
    out = tick(now=datetime.now(UTC) + timedelta(minutes=5), enqueue=lambda rid: None)
    assert out["monitor"] == "stale"
    a = next(a for a in api.get("/alerts").json() if a["alert_key"] == "heartbeat:monitor")
    assert a["severity"] == "critical" and "docker compose up -d monitor" in a["remediation"]
