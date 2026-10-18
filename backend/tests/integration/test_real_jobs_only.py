"""Real jobs only: the Mock job board is off in production and its data can be removed completely."""

import uuid
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from jobpilot.config import get_settings
from jobpilot.db import models as m
from jobpilot.db.session import SessionLocal
from jobpilot.ops.purge import purge_test_jobs
from jobpilot.orchestrator import runs

from tests.conftest import PASSWORD, USER, Api, documents_ready_app

GOOD_SECRET = "f" * 64


def _count(model, *where):
    with SessionLocal() as db:
        return db.scalar(select(func.count()).select_from(model).where(*where))


def _real_job() -> uuid.UUID:
    with SessionLocal() as db:
        src = db.scalar(select(m.JobSource).where(m.JobSource.code == "ba_jobsuche"))
        job = m.Job(source_id=src.id, external_id="ba:REAL-1", url="https://www.arbeitsagentur.de/jobsuche/jobdetail/REAL-1",
                    url_normalized="https://www.arbeitsagentur.de/jobsuche/jobdetail/real-1", fingerprint="real-fp",
                    company="Real GmbH", title="Android Developer", country="DE", description_text="Kotlin")
        db.add(job)
        db.flush()
        from jobpilot.domain import transitions

        transitions.create_application(db, job.id)
        db.commit()
        return job.id


def test_purge_removes_every_test_job_and_its_files_but_keeps_real_ones(api):
    app_id = documents_ready_app(api)  # mock job with CV, letter, history
    real = _real_job()
    root = Path(get_settings().documents_dir)
    assert (root / app_id).exists()
    with SessionLocal() as db:
        out = purge_test_jobs(db)
        db.commit()
    assert out["jobs"] >= 7 and out["applications"] >= 7 and out["runs"] == 1
    mock_src = _count(m.Job, m.Job.source.has(m.JobSource.code == "mock"))
    assert mock_src == 0
    assert _count(m.Document) == 0 and _count(m.SearchRun) == 0
    assert not (root / app_id).exists()
    assert _count(m.Job, m.Job.id == real) == 1 and _count(m.Application, m.Application.job_id == real) == 1
    with SessionLocal() as db:
        cfg = db.scalar(select(m.SearchConfig))
        assert cfg.source_codes == ["ba_jobsuche"]
        assert db.scalar(select(m.JobSource).where(m.JobSource.code == "mock")).enabled is False
    # running it again is harmless
    with SessionLocal() as db:
        assert purge_test_jobs(db)["jobs"] == 0


def test_production_hides_the_test_board_and_cleans_up_at_start(api, monkeypatch):
    documents_ready_app(api)
    assert _count(m.Job) > 0
    monkeypatch.setenv("JOBPILOT_ENV", "production")
    monkeypatch.setenv("JOBPILOT_SECRET_KEY", GOOD_SECRET)
    get_settings.cache_clear()
    try:
        from jobpilot.main import create_app

        with TestClient(create_app(run_bootstrap=True)) as c:
            a = Api(c)
            assert a.post("/auth/login", {"username": USER, "password": PASSWORD}, key=None).status_code == 200
            codes = [x["code"] for x in a.get("/sources").json()]
            assert "mock" not in codes and "ba_jobsuche" in codes
            cfg = a.get("/search-configs").json()[0]
            assert cfg["source_codes"] == ["ba_jobsuche"]
            r = a.post("/search-configs", {"name": "x", "source_codes": ["mock"]})
            assert r.status_code == 422
        assert _count(m.Job) == 0  # every test job removed at start-up
        with SessionLocal() as db:  # a run on an old config never touches the test board
            run = runs.start_run(db, db.scalar(select(m.SearchConfig.id)), trigger="manual")
            db.commit()
            assert run is not None
    finally:
        monkeypatch.undo()
        get_settings.cache_clear()


def test_purge_command(api):
    import subprocess
    import sys

    from tests.conftest import BACKEND

    documents_ready_app(api)
    r = subprocess.run([sys.executable, "-m", "jobpilot.ops", "purge-test-jobs"], cwd=BACKEND,
                       capture_output=True, text=True, timeout=120)
    assert r.returncode == 0 and '"jobs":' in r.stdout
    assert _count(m.Job) == 0
