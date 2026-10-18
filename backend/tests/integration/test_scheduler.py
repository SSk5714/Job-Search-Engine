"""Acceptance criterion 12: scheduled searches run without manual intervention, safely."""

import threading
import uuid
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import func, select, update

from jobpilot.db import models as m
from jobpilot.db.session import SessionLocal
from jobpilot.orchestrator import runs
from jobpilot.orchestrator.scheduler import tick

from tests.conftest import verify_facts


def sync_enqueue(run_id):
    runs.execute_run(run_id)


def _cfg(api, **schedule):
    cfg = api.get("/search-configs").json()[0]
    if schedule:
        r = api.put(f"/search-configs/{cfg['id']}/schedule", schedule, key=None)
        assert r.status_code == 200, r.text
        cfg = r.json()
    return cfg


def _make_due(cfg_id, when=None):
    with SessionLocal() as db:
        db.execute(update(m.SearchConfig).where(m.SearchConfig.id == uuid.UUID(str(cfg_id)))
                   .values(next_run_at=when or datetime.now(UTC) - timedelta(minutes=1)))
        db.commit()


def _count(model, *where):
    with SessionLocal() as db:
        return db.scalar(select(func.count()).select_from(model).where(*where))


def test_schedule_api_sets_cadence_and_refuses_too_frequent(api):
    cfg = _cfg(api, kind="weekdays", at="07:30")
    assert cfg["cron"] == "30 7 * * 1-5"
    assert cfg["schedule_text"] == "Weekdays at 07:30 (Europe/Berlin)"
    assert datetime.fromisoformat(cfg["next_run_at"]) > datetime.now(UTC)
    bad = api.put(f"/search-configs/{cfg['id']}/schedule", {"kind": "cron", "cron": "*/10 * * * *"}, key=None)
    assert bad.status_code == 422 and "once an hour" in bad.json()["error"]["message"]
    off = api.put(f"/search-configs/{cfg['id']}/schedule", {"kind": "off"}, key=None).json()
    assert off["cron"] is None and off["next_run_at"] is None


def test_scheduled_search_runs_unattended(api):
    verify_facts(api)
    cfg = _cfg(api, kind="daily", at="06:00")
    _make_due(cfg["id"])
    summary = tick(enqueue=sync_enqueue)
    assert [d["outcome"] for d in summary["dispatched"]] == ["started"]
    with SessionLocal() as db:
        run = db.scalar(select(m.SearchRun).where(m.SearchRun.trigger == "schedule"))
        assert run.status == "completed" and run.summary["new"] == 7
        c = db.get(m.SearchConfig, uuid.UUID(cfg["id"]))
        assert c.next_run_at > datetime.now(UTC)  # advanced to tomorrow 06:00
        assert db.get(m.Heartbeat, "scheduler") is not None
    # nothing is due any more: the next tick starts nothing
    assert tick(enqueue=sync_enqueue)["dispatched"] == []
    assert _count(m.SearchRun) == 1
    shown = api.get("/search-configs").json()[0]
    assert shown["last_dispatch"]["outcome"] == "started"


def test_new_high_fit_jobs_make_one_summary_notification(api):
    verify_facts(api)
    api.put("/settings/notifications", {"high_fit_min_score": 50}, key=None)
    cfg = _cfg(api, kind="daily", at="06:00")
    _make_due(cfg["id"])
    tick(enqueue=sync_enqueue)
    notes = [n for n in api.get("/notifications").json() if n["kind"] == "high_fit"]
    assert len(notes) == 1, notes  # one summary for the run, not one per job
    assert "matching 50% or more" in notes[0]["title"] and notes[0]["link"] == "/"
    assert "http" in notes[0]["body"]  # each job comes with its link


def test_two_schedulers_at_once_start_one_run(api):
    cfg = _cfg(api, kind="daily", at="06:00")
    _make_due(cfg["id"])
    started = []
    barrier = threading.Barrier(4)

    def go():
        barrier.wait()
        started.append(tick(enqueue=lambda rid: None))

    threads = [threading.Thread(target=go) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert _count(m.SearchRun) == 1
    assert _count(m.ScheduleDispatch) == 1


def test_missed_times_are_caught_up_once(api):
    cfg = _cfg(api, kind="daily", at="06:00")
    _make_due(cfg["id"], datetime.now(UTC) - timedelta(days=5))
    out = tick(enqueue=lambda rid: None)["dispatched"]
    assert len(out) == 1 and out[0]["outcome"] == "started"
    with SessionLocal() as db:
        d = db.scalar(select(m.ScheduleDispatch))
        assert "missed" in d.detail
    assert _count(m.SearchRun) == 1


def test_overlap_is_skipped_and_recorded(api):
    cfg = _cfg(api, kind="daily", at="06:00")
    with SessionLocal() as db:
        db.add(m.SearchRun(config_id=uuid.UUID(cfg["id"]), trigger="manual", status="running"))
        db.commit()
    _make_due(cfg["id"])
    out = tick(enqueue=lambda rid: None)["dispatched"]
    assert out[0]["outcome"] == "skipped_overlap"
    assert _count(m.SearchRun) == 1
    # allowed overlap starts a second run
    _cfg(api, kind="daily", at="06:00", allow_overlap=True)
    _make_due(cfg["id"])
    assert tick(enqueue=lambda rid: None)["dispatched"][0]["outcome"] == "started"
    assert _count(m.SearchRun) == 2


def test_queue_down_fails_the_run_visibly(api):
    cfg = _cfg(api, kind="daily", at="06:00")
    _make_due(cfg["id"])

    def broken(_):
        raise ConnectionError("redis refused")

    tick(enqueue=broken)
    with SessionLocal() as db:
        run = db.scalar(select(m.SearchRun))
        assert run.status == "failed" and "queue" in run.summary["error"].lower()
        d = db.scalar(select(m.ScheduleDispatch))
        assert d.outcome == "failed_to_start"
    alert = next(a for a in api.get("/alerts").json() if a["alert_key"] == "queue:enqueue")
    assert alert["severity"] == "critical" and alert["workflow_paused"] and "Redis" in alert["remediation"]
    # when the queue works again the alert closes on the next dispatch
    _make_due(cfg["id"])
    tick(enqueue=lambda rid: None)
    assert not [a for a in api.get("/alerts").json() if a["alert_key"] == "queue:enqueue"]


def test_stalled_run_is_marked_failed_so_the_schedule_continues(api):
    cfg = _cfg(api, kind="daily", at="06:00")
    with SessionLocal() as db:
        db.add(m.SearchRun(config_id=uuid.UUID(cfg["id"]), trigger="schedule", status="running",
                           started_at=datetime.now(UTC) - timedelta(hours=2)))
        db.commit()
    out = tick(enqueue=lambda rid: None)
    assert len(out["stalled_marked_failed"]) == 1
    with SessionLocal() as db:
        r = db.scalar(select(m.SearchRun))
        assert r.status == "failed" and "stalled" in r.summary["error"]
    _make_due(cfg["id"])
    assert tick(enqueue=lambda rid: None)["dispatched"][0]["outcome"] == "started"


def test_stop_a_stuck_run_by_hand(api):
    cfg = _cfg(api)
    with SessionLocal() as db:
        r = m.SearchRun(config_id=uuid.UUID(cfg["id"]), trigger="manual", status="running")
        db.add(r)
        db.commit()
        rid = r.id
    res = api.post(f"/search-runs/{rid}/stop", key=None)
    assert res.status_code == 200 and res.json()["status"] == "failed"
    assert api.post(f"/search-runs/{rid}/stop", key=None).status_code == 409


def test_repeated_failures_pause_the_schedule_until_resumed(api):
    cfg = api.post("/search-configs", {"name": "Broken Greenhouse", "source_codes": ["greenhouse"]}).json()
    api.put(f"/search-configs/{cfg['id']}/schedule", {"kind": "daily", "at": "06:00"}, key=None)
    for _ in range(3):
        _make_due(cfg["id"])
        tick(enqueue=sync_enqueue)
    with SessionLocal() as db:
        c = db.get(m.SearchConfig, uuid.UUID(cfg["id"]))
        assert c.paused_reason and "needs_configuration" in c.paused_reason
    alert = next(a for a in api.get("/alerts").json() if a["alert_key"] == f"schedule-paused:{cfg['id']}")
    assert alert["workflow_paused"] and "Resume" in alert["remediation"]
    # paused: due times start nothing
    _make_due(cfg["id"])
    assert tick(enqueue=sync_enqueue)["dispatched"] == []
    # resume clears the alert and earlier failures no longer count
    r = api.post(f"/search-configs/{cfg['id']}/resume", key=None).json()
    assert r["paused_reason"] is None
    assert not [a for a in api.get("/alerts").json() if a["alert_key"] == f"schedule-paused:{cfg['id']}"]
    _make_due(cfg["id"])
    tick(enqueue=sync_enqueue)
    with SessionLocal() as db:
        assert db.get(m.SearchConfig, uuid.UUID(cfg["id"])).paused_reason is None


def test_follow_up_reminder_is_sent_once(api):
    verify_facts(api)
    api.post("/search-runs", {"config_id": _cfg(api)["id"]})
    with SessionLocal() as db:
        app = db.scalar(select(m.Application).limit(1))
        app.state, app.next_follow_up = "submitted", date.today() + timedelta(days=1)
        db.commit()
    tick(enqueue=lambda rid: None)
    tick(enqueue=lambda rid: None)
    notes = [n for n in api.get("/notifications").json() if n["kind"] == "follow_up"]
    assert len(notes) == 1 and "Follow up" in notes[0]["title"]


def test_scheduler_watches_the_monitor_heartbeat(api):
    with SessionLocal() as db:
        db.add(m.Heartbeat(component="monitor", beat_at=datetime.now(UTC) - timedelta(minutes=30),
                           interval_s=60, started_at=datetime.now(UTC) - timedelta(hours=1), detail={}))
        db.commit()
    assert tick(enqueue=lambda rid: None)["monitor"] == "stale"
    alert = next(a for a in api.get("/alerts").json() if a["alert_key"] == "heartbeat:monitor")
    assert alert["severity"] == "critical" and "monitor" in alert["remediation"]
    with SessionLocal() as db:
        db.get(m.Heartbeat, "monitor").beat_at = datetime.now(UTC)
        db.commit()
    assert tick(enqueue=lambda rid: None)["monitor"] == "ok"
    assert not [a for a in api.get("/alerts").json() if a["alert_key"] == "heartbeat:monitor"]
    health = api.get("/health/details").json()["checks"]
    assert health["scheduler"]["status"] == "ok" and health["monitor"]["status"] == "ok"
