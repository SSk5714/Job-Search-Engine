"""Phase 2 endpoints: settings, rescore, URL import, availability rechecks,
real-adapter runs and the Automated label."""

from sqlalchemy import func, select

from jobpilot.db import models as m
from tests.conftest import run_mock_search, verify_facts


def _set_sources(api, codes, options=None, filters=None):
    cfg = api.get("/search-configs").json()[0]
    body = {"name": cfg["name"], "filters": {**cfg["filters"], **(filters or {})}, "source_codes": codes,
            "source_options": options or {}}
    r = api.patch(f"/search-configs/{cfg['id']}", body, key=None)
    assert r.status_code == 200, r.text


def test_scoring_settings_validation_and_rescore(api, db):
    verify_facts(api)
    run_mock_search(api)
    before = db.scalar(select(func.count()).select_from(m.JobMatchEvaluation))
    bad = api._write("PUT", "/settings/scoring", {"weights": {"technical": 50, "experience": 25, "track": 20,
                                                              "language": 10, "location": 15},
                                                  "thresholds": {"apply": 75, "review": 55}}, key=None)
    assert bad.status_code == 422 and "sum to 100" in bad.json()["error"]["message"]
    good = api._write("PUT", "/settings/scoring", {"weights": {"technical": 40, "experience": 20, "track": 20,
                                                               "language": 5, "location": 15},
                                                   "thresholds": {"apply": 70, "review": 50}}, key=None)
    assert good.status_code == 200
    r = api.post("/jobs/rescore", {})
    assert r.status_code == 200 and r.json()["rescored"] == 7
    after = db.scalar(select(func.count()).select_from(m.JobMatchEvaluation))
    assert after == before + 7  # old evaluations are kept for comparison
    latest = api.get("/jobs").json()["items"][0]["evaluation"]
    assert latest["weights"]["technical"] == 40 and latest["model_version"].endswith(good.json()["version_tag"])


def test_ai_settings_report_status(api):
    s = api.get("/settings/ai").json()
    assert s["api_key_configured"] is False and s["active_matcher"] == "rules"
    assert s["model"] == "claude-haiku-5-5"
    r = api._write("PUT", "/settings/ai", {"matcher": "claude", "max_ai_jobs_per_run": 10,
                                            "daily_budget_usd": 0.5}, key=None)
    assert r.status_code == 200 and r.json()["active_matcher"] == "rules"  # still no key
    assert api._write("PUT", "/settings/ai", {"matcher": "gpt"}, key=None).status_code == 422


def test_real_adapters_in_a_run_and_live_verification(api, db, fake_sources):
    _set_sources(api, ["greenhouse", "lever", "personio"],
                 {"greenhouse": {"boards": ["examplemobility"]},
                  "lever": {"sites": ["exampleauto"], "region": "eu"},
                  "personio": {"companies": ["example-embedded"]}},
                 {"max_age_days": None})
    run = run_mock_search(api)
    assert run["status"] == "completed", run
    assert run["summary"]["new"] == 4
    labels = {s["code"]: s["label"] for s in api.get("/sources").json()}
    assert labels["greenhouse"] == "Automated" and labels["lever"] == "Automated"
    assert labels["ba_jobsuche"] == "Untested"
    titles = {j["title"] for j in api.get("/jobs").json()["items"]}
    assert "Account Executive DACH" not in titles and "HR Business Partner" not in titles


def test_import_from_api_backed_url(api, db, fake_sources):
    r = api.post("/jobs/import-url", {"url": "https://job-boards.greenhouse.io/examplemobility/jobs/7001001"})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["outcome"] == "new"
    assert body["job"]["title"] == "Junior Android Engineer (Kotlin)"
    assert body["job"]["application"]["state"] == "classified"
    assert body["job"]["evaluation"] is not None


def test_linkedin_urls_are_never_fetched(api, db, fake_sources):
    url = "https://www.linkedin.com/jobs/view/4012345678"
    r = api.post("/jobs/import-url", {"url": url})
    assert r.status_code == 422 and r.json()["error"]["code"] == "details_required"
    r = api.post("/jobs/import-url", {"url": url, "title": "Android Engineer", "company": "Example GmbH",
                                      "city": "Leipzig", "country": "de",
                                      "description": "Kotlin, Android, Jetpack Compose"})
    assert r.status_code == 201
    job = r.json()["job"]
    assert job["source"] == "linkedin" and job["country"] == "DE"
    assert job["application"]["state"] == "classified"
    assert fake_sources.calls == []  # no request to LinkedIn or anywhere else


def test_import_same_url_twice_is_a_duplicate(api, fake_sources):
    url = "https://job-boards.greenhouse.io/examplemobility/jobs/7001001"
    api.post("/jobs/import-url", {"url": url})
    r = api.post("/jobs/import-url", {"url": url + "?gh_src=abc"})
    assert r.json()["outcome"] == "duplicate_url"


def test_recheck_closed_listing_expires_application(api, db, fake_sources):
    r = api.post("/jobs/import-url", {"url": "https://job-boards.greenhouse.io/examplemobility/jobs/7001002"})
    job_id = r.json()["job"]["id"]
    fake_sources.gh_open.discard("7001002")
    r = api.post(f"/jobs/{job_id}/recheck", key=None)
    assert r.json()["availability"] == "closed"
    assert r.json()["application"]["state"] == "expired"


def test_approval_rechecks_availability_first(api, db, fake_sources):
    r = api.post("/jobs/import-url", {"url": "https://job-boards.greenhouse.io/examplemobility/jobs/7001001"})
    job_id = r.json()["job"]["id"]
    fake_sources.gh_open.discard("7001001")
    r = api.post(f"/jobs/{job_id}/decision", {"decision": "approve"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "listing_closed"
    assert api.get(f"/jobs/{job_id}").json()["application"]["state"] == "expired"


def test_source_outage_is_reported_per_source(api, db, fake_sources):
    import httpx

    fake_sources.overrides["https://boards-api.greenhouse.io"] = [httpx.Response(503) for _ in range(3)]
    _set_sources(api, ["greenhouse", "mock"], {"greenhouse": {"boards": ["examplemobility"]}})
    run = run_mock_search(api)
    assert run["status"] == "partial"
    assert run["summary"]["sources"]["greenhouse"] == {"status": "failed", "error": "server_error"}
    assert run["summary"]["sources"]["mock"]["status"] == "ok"
