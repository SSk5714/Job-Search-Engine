"""Auth, CSRF, profile versioning, tracker, CSV export, dashboard (criteria 11, 13 support)."""

import csv
import io

from tests.conftest import USER, Api, run_mock_search, verify_facts


def test_endpoints_require_login(client):
    assert client.get("/api/v1/jobs").status_code == 401
    assert client.get("/api/v1/health").status_code == 200


def test_wrong_password_is_rejected(client):
    r = Api(client).post("/auth/login", {"username": USER, "password": "nope"}, key=None)
    assert r.status_code == 401


def test_writes_without_csrf_header_are_refused(api):
    r = api.c.post("/api/v1/profile/facts/00000000-0000-0000-0000-000000000000/verify", json={"verified": True})
    assert r.status_code == 403 and r.json()["error"]["code"] == "csrf_failed"


def test_seed_profile_is_unverified_and_has_blanks_for_eligibility(api):
    p = api.get("/profile").json()
    assert p["verified_count"] == 0
    elig = {f["key"]: f["value"] for f in p["facts"] if f["category"] == "eligibility"}
    assert elig == {"enrolment_status": "", "work_authorization": "", "sponsorship_required": "", "availability": ""}
    assert all(f["value"] == "" for f in p["facts"] if f["category"] == "contact")  # no personal data in seed
    emp = {f["key"]: f["value"] for f in p["facts"] if f["category"] == "employment"}
    assert emp["start"] == "2024-10" and emp["end"] == "2025-08" and emp["employer"] == "Sasken Technologies"


def test_empty_fact_cannot_be_verified(api):
    p = api.get("/profile").json()
    blank = next(f for f in p["facts"] if f["key"] == "work_authorization")
    r = api.post(f"/profile/facts/{blank['id']}/verify", {"verified": True}, key=None)
    assert r.status_code == 422


def test_profile_edit_creates_version_and_resets_changed_verification(api):
    p = verify_facts(api, skills=("Java", "Kotlin"))
    assert p["version_no"] == 2
    facts = [{k: f[k] for k in ("category", "entry", "key", "value", "context", "source_note")} for f in p["facts"]]
    for f in facts:
        if f["key"] == "kotlin":
            f["context"] = "project"  # changed -> must be re-verified
    p3 = api.put("/profile", {"facts": facts}).json()
    assert p3["version_no"] == 3
    by_key = {f["key"]: f for f in p3["facts"]}
    assert by_key["java"]["verified"] is True
    assert by_key["kotlin"]["verified"] is False
    assert len(api.get("/profile/versions").json()) == 3


def test_skill_without_context_is_rejected(api):
    r = api.put("/profile", {"facts": [{"category": "skill", "key": "go", "value": "Go"}]})
    assert r.status_code == 422


def test_tracker_csv_export_round_trip(api):
    run_mock_search(api)
    jobs = api.get("/jobs").json()["items"]
    api.post(f"/jobs/{jobs[0]['id']}/decision", {"decision": "approve"})
    api.post(f"/jobs/{jobs[1]['id']}/decision", {"decision": "reject", "reason": "senior role"})
    tracker = api.get("/applications").json()
    assert {r["state"] for r in tracker} == {"approved_for_preparation", "rejected"}

    r = api.get("/applications/export.csv")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
    rows = list(csv.DictReader(io.StringIO(r.text)))
    assert len(rows) == 7
    assert {"company", "role", "country", "score", "state", "next_follow_up", "outcome"} <= set(rows[0])


def test_tracker_follow_up_and_outcome_edit(api):
    run_mock_search(api)
    job = api.get("/jobs").json()["items"][0]
    app_id = job["application"]["id"]
    r = api.patch(f"/applications/{app_id}", {"next_follow_up": "2026-11-01", "outcome": "no reply"}, key=None)
    assert r.status_code == 200
    d = api.get(f"/applications/{app_id}").json()
    assert d["next_follow_up"] == "2026-11-01" and d["outcome"] == "no reply"
    assert d["state"] == "classified"  # tracker edits never change state


def test_dashboard_counts(api):
    verify_facts(api)
    run_mock_search(api)
    d = api.get("/dashboard").json()
    assert d["counts"]["new_jobs"] == 7
    assert d["last_run"]["status"] == "completed"
    assert set(d["counts"]) == {"new_jobs", "high_fit", "awaiting_review", "documents_ready", "submitted",
                                "follow_ups_due", "failed_tasks", "warnings"}


def test_health_details_reports_missing_integrations(api):
    h = api.get("/health/details").json()
    assert h["checks"]["database"]["status"] == "ok"
    assert h["checks"]["monitor"]["status"] == "not_implemented"
    assert h["checks"]["claude_api"]["status"] in ("not_configured", "configured_untested")


def test_job_filters(api):
    verify_facts(api)
    run_mock_search(api)
    all_jobs = api.get("/jobs").json()
    assert all_jobs["total"] == 7
    scores = [j["evaluation"]["score"] for j in all_jobs["items"]]
    assert scores == sorted(scores, reverse=True)
    assert api.get("/jobs", params={"include_duplicates": True, "include_closed": True}).json()["total"] == 9
    android = api.get("/jobs", params={"q": "android"}).json()
    assert android["total"] >= 1 and all("android" in j["title"].lower() for j in android["items"])
