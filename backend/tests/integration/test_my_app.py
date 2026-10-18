"""The simple app: matching jobs with CV, letter and apply link; history of applied jobs."""

from tests.conftest import load_test_profile, run_mock_search


def _jobs(api, **kw):
    r = api.get("/my/jobs", params=kw)
    assert r.status_code == 200, r.text
    return r.json()


def test_only_matching_jobs_best_first_with_link_and_description(api):
    load_test_profile(api)
    run_mock_search(api)
    data = _jobs(api)
    jobs = data["jobs"]
    assert jobs and all(j["recommendation"] in ("apply", "review") for j in jobs)
    assert [j["score"] for j in jobs] == sorted((j["score"] for j in jobs), reverse=True)
    top = jobs[0]
    assert top["url"].startswith("http") and top["summary"] and top["why"]
    assert len(_jobs(api, include_weak=True)["jobs"]) >= len(jobs)


def test_one_click_cv_and_letter_then_applied_moves_to_history(api):
    load_test_profile(api)
    run_mock_search(api)
    job = _jobs(api)["jobs"][0]
    r = api.post(f"/my/jobs/{job['application_id']}/documents", key=None)
    assert r.status_code == 200, r.text
    card = r.json()
    assert set(card["documents"]) == {"cv", "cover_letter"}
    cv = card["documents"]["cv"]
    pdf = api.get(f"/applications/{job['application_id']}/documents/{cv['id']}/download?format=pdf")
    assert pdf.status_code == 200 and pdf.content[:5] == b"%PDF-"

    r = api.post(f"/my/jobs/{job['application_id']}/applied", {"note": "via company site"}, key=None)
    assert r.status_code == 200 and r.json()["state"] == "submitted" and r.json()["next_follow_up"]
    assert job["application_id"] not in [j["application_id"] for j in _jobs(api)["jobs"]]
    hist = api.get("/my/history").json()
    assert hist[0]["application_id"] == job["application_id"] and hist[0]["url"] == job["url"]
    assert api.post(f"/my/jobs/{job['application_id']}/applied", {}, key=None).status_code == 409

    r = api.patch(f"/my/history/{job['application_id']}", {"outcome": "interview"}, key=None)
    assert r.status_code == 200 and r.json()["outcome"] == "interview"


def test_applied_without_documents_and_dismiss(api):
    load_test_profile(api)
    run_mock_search(api)
    a, b = _jobs(api)["jobs"][:2]
    assert api.post(f"/my/jobs/{a['application_id']}/applied", {}, key=None).status_code == 200
    assert api.post(f"/my/jobs/{b['application_id']}/dismiss", key=None).status_code == 200
    ids = [j["application_id"] for j in _jobs(api, include_weak=True)["jobs"]]
    assert a["application_id"] not in ids and b["application_id"] not in ids


def test_generic_transition_still_cannot_jump_to_submitted(api):
    load_test_profile(api)
    run_mock_search(api)
    job = _jobs(api)["jobs"][0]
    r = api.post(f"/applications/{job['application_id']}/transitions", {"to_state": "submitted"})
    assert r.status_code in (403, 409)
