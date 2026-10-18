"""Criterion 12 end to end with the real processes: Redis, a Celery worker and Celery beat.
Nobody calls the API: beat sends the tick, the worker starts the due search and runs it."""

import os
import subprocess
import sys
import time
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select, update

from jobpilot.db import models as m
from jobpilot.db.session import SessionLocal

from tests.conftest import BACKEND, verify_facts

REDIS = "redis://127.0.0.1:6379/15"


def _redis_up() -> bool:
    try:
        import redis

        redis.Redis.from_url(REDIS, socket_timeout=1).ping()
        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(not _redis_up(), reason="needs a local Redis")


def test_celery_beat_runs_a_scheduled_search_unattended(api, tmp_path):
    import redis

    redis.Redis.from_url(REDIS).flushdb()
    verify_facts(api)
    cfg = api.get("/search-configs").json()[0]
    api.put(f"/search-configs/{cfg['id']}/schedule", {"kind": "every_hours", "every_hours": 6}, key=None)
    with SessionLocal() as db:
        db.execute(update(m.SearchConfig).values(next_run_at=datetime.now(UTC) - timedelta(minutes=1)))
        db.commit()

    env = {**os.environ, "JOBPILOT_REDIS_URL": REDIS, "JOBPILOT_SCHEDULER_INTERVAL_S": "3"}
    common = [sys.executable, "-m", "celery", "-A", "jobpilot.worker"]
    worker = subprocess.Popen(common + ["worker", "--pool", "solo", "-l", "warning"], cwd=BACKEND, env=env,
                              stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    beat = subprocess.Popen(common + ["beat", "-l", "warning", "-s", str(tmp_path / "beat-schedule")],
                            cwd=BACKEND, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    try:
        deadline = time.time() + 60
        run = None
        while time.time() < deadline:
            with SessionLocal() as db:
                run = db.scalar(select(m.SearchRun).where(m.SearchRun.trigger == "schedule"))
                if run is not None and run.status != "running":
                    break
            time.sleep(1)
        else:
            out = worker.stdout.read1().decode()[-3000:] + beat.stdout.read1().decode()[-2000:]
            pytest.fail(f"no finished scheduled run (run={run and run.status}):\n{out}")
        assert run.status == "completed" and run.summary["new"] == 7
        time.sleep(7)  # two more ticks: nothing else is due, so no second run
        with SessionLocal() as db:
            assert len(db.scalars(select(m.SearchRun)).all()) == 1
            c = db.get(m.SearchConfig, uuid.UUID(cfg["id"]))
            assert c.next_run_at > datetime.now(UTC)  # advanced to the next 6-hour slot
            hb = db.get(m.Heartbeat, "scheduler")
            assert (datetime.now(UTC) - hb.beat_at).total_seconds() < 10
    finally:
        for p in (beat, worker):
            p.terminate()
        for p in (beat, worker):
            try:
                p.wait(15)
            except subprocess.TimeoutExpired:
                p.kill()
