"""Acceptance criteria 1, 2, 14 and source isolation."""

from sqlalchemy import func, select

from jobpilot.db import models as m
from tests.conftest import run_mock_search, verify_facts


def test_multiple_jobs_retrieved_and_normalized(api, db):
    run = run_mock_search(api)
    assert run["status"] == "completed", run
    s = run["summary"]
    # 12 raw jobs; the default search is Germany-only, so the NL and CZ jobs are filtered out
    assert s["fetched"] == 10
    assert s["new"] == 7  # 10 - 1 URL variant - 1 cross-source duplicate - 1 closed
    assert s["duplicate_url"] == 1
    assert s["duplicate_fingerprint"] == 1
    assert s["closed"] == 1
    jobs = db.scalars(select(m.Job)).all()
    assert len(jobs) == 9  # duplicates by fingerprint and closed listings are kept for provenance
    for j in jobs:
        assert j.url_normalized.startswith("https://")
        assert j.company and j.title and j.retrieved_at and j.published_at
        assert j.country is None or len(j.country) == 2
    remote = db.scalar(select(m.Job).where(m.Job.title == "Kotlin Developer"))
    assert remote.work_mode == "remote" and float(remote.salary_min) == 48000 and remote.currency == "EUR"


def test_running_the_same_search_twice_inserts_no_duplicates(api, db):
    run_mock_search(api)
    jobs_before = db.scalar(select(func.count()).select_from(m.Job))
    apps_before = db.scalar(select(func.count()).select_from(m.Application))
    second = run_mock_search(api)
    assert second["summary"]["new"] == 0
    assert db.scalar(select(func.count()).select_from(m.Job)) == jobs_before
    assert db.scalar(select(func.count()).select_from(m.Application)) == apps_before


def test_every_new_job_is_classified_with_score_explanation_and_evidence(api, db):
    verify_facts(api)
    run_mock_search(api)
    apps = db.scalars(select(m.Application)).all()
    assert apps and all(a.state == "classified" for a in apps)
    for a in apps:
        ev = db.scalar(select(m.JobMatchEvaluation).where(m.JobMatchEvaluation.job_id == a.job_id))
        assert ev is not None
        assert 0 <= ev.score <= 100 and ev.explanation and isinstance(ev.evidence, list) and ev.evidence
        assert sum(ev.breakdown.values()) == ev.score
        assert ev.model_version.startswith("rules-v0")


def test_one_broken_source_does_not_stop_the_others(api, db):
    cfg = api.get("/search-configs").json()[0]
    body = {"name": cfg["name"], "filters": cfg["filters"], "source_codes": ["mock_broken", "mock"]}
    assert api.patch(f"/search-configs/{cfg['id']}", body, key=None).status_code == 200
    run = run_mock_search(api)
    assert run["status"] == "partial"
    assert run["summary"]["sources"]["mock_broken"]["status"] == "failed"
    assert run["summary"]["sources"]["mock"]["status"] == "ok"
    assert run["summary"]["new"] == 7
    err = db.scalar(select(m.ErrorEvent).where(m.ErrorEvent.component == "discovery:mock_broken"))
    assert err is not None and err.code == "ConnectionError"


def test_manual_only_sources_cannot_be_scheduled_for_automated_search(api):
    cfg = api.get("/search-configs").json()[0]
    body = {"name": cfg["name"], "filters": cfg["filters"], "source_codes": ["stepstone"]}
    r = api.patch(f"/search-configs/{cfg['id']}", body, key=None)
    assert r.status_code == 422 and "URL import" in r.json()["error"]["message"]


def test_source_needing_configuration_reports_it(api):
    cfg = api.get("/search-configs").json()[0]
    body = {"name": cfg["name"], "filters": cfg["filters"], "source_codes": ["greenhouse", "mock"]}
    api.patch(f"/search-configs/{cfg['id']}", body, key=None)
    run = run_mock_search(api)
    assert run["status"] == "partial"
    assert run["summary"]["sources"]["greenhouse"] == {"status": "failed", "error": "needs_configuration"}


def test_source_labels_are_honest(api):
    sources = {s["code"]: s for s in api.get("/sources").json()}
    assert sources["mock"]["label"] == "Mock"
    assert sources["linkedin"]["label"] == "Manual"
    assert sources["ba_jobsuche"]["label"] == "Untested"  # built, never run against the live API
    assert sources["greenhouse"]["label"] == "Untested"
    assert not any(s["label"] == "Automated" for s in sources.values())
    r = api.patch("/sources/stepstone", {"enabled": True}, key=None)
    assert r.status_code == 409 and r.json()["error"]["code"] == "not_implemented"


def test_overlapping_runs_for_the_same_search_are_blocked(api, db):
    cfg_id = api.get("/search-configs").json()[0]["id"]
    db.add(m.SearchRun(config_id=cfg_id, trigger="manual", status="running"))
    db.commit()
    r = api.post("/search-runs", {"config_id": cfg_id})
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "run_in_progress"


def test_europe_wide_search_includes_other_countries(api, db):
    cfg = api.get("/search-configs").json()[0]
    filters = {**cfg["filters"], "countries": ["DE", "NL", "CZ"]}
    api.patch(f"/search-configs/{cfg['id']}", {"name": "Europe", "filters": filters, "source_codes": ["mock"]},
              key=None)
    run = run_mock_search(api)
    assert run["summary"]["fetched"] == 12 and run["summary"]["new"] == 9
    assert {j.country for j in db.scalars(select(m.Job)).all()} == {"DE", "NL", "CZ"}
