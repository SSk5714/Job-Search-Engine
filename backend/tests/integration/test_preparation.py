"""Phase 4: form preparation and submission against the mock portal
(acceptance criteria 6, 7, 8, 9 end to end)."""

import pytest
from sqlalchemy import select

from jobpilot.config import get_settings
from jobpilot.db import models as m
from tests.conftest import STANDARD_ANSWERS, answer, documents_ready_app


def _prepare(api, app_id, url):
    r = api.post(f"/applications/{app_id}/prepare", {"apply_url": url})
    assert r.status_code == 200, r.text
    return r.json()


def test_preparation_fills_only_safe_fields_and_never_submits(api, clean_portal):
    app_id = documents_ready_app(api)
    d = _prepare(api, app_id, clean_portal.url("standard"))
    assert d["state"] == "awaiting_user_review"
    assert d["preparation"]["mode"] == "browser" and d["preparation"]["host"] == "127.0.0.1"
    f = {x["field_key"]: x for x in d["form_fields"]}

    auto = {"first_name": "Alex", "last_name": "Example", "email": "alex@example.org", "phone": "+49 000 0000000",
            "city": "Chemnitz", "resume": "document:cv", "cover": "document:cover_letter", "german": "A2"}
    for key, value in auto.items():
        assert f[key]["proposed_value"] == value and f[key]["needs_manual"] is False, key

    for key in ("salary", "start", "permit", "sponsorship", "gender", "privacy"):
        assert f[key]["sensitivity"] in ("sensitive", "legal"), key
        assert f[key]["proposed_value"] is None and f[key]["needs_manual"] is True, key  # never guessed
    assert f["motivation"]["needs_manual"] is True and f["motivation"]["proposed_value"]  # proposal to confirm
    assert set(d["unresolved_fields"]) == {"salary", "start", "permit", "sponsorship", "gender", "privacy",
                                           "motivation", "source", "linkedin"}  # no LinkedIn fact: never invented
    assert clean_portal.submissions == []  # preparation never submits

    shot = d["preparation"]["screenshot"]
    r = api.get(f"/applications/{app_id}/evidence", params={"file": shot})
    assert r.status_code == 200 and r.content[:4] == b"\x89PNG"


def test_full_submission_with_approval(api, db, clean_portal):
    app_id = documents_ready_app(api)
    _prepare(api, app_id, clean_portal.url("standard"))

    r = api.post(f"/applications/{app_id}/approve")
    assert r.status_code == 409 and r.json()["error"]["code"] == "unresolved_fields"
    r = api.post(f"/applications/{app_id}/submit")
    assert r.status_code == 409 and r.json()["error"]["code"] == "approval_required"

    answer(api, app_id, STANDARD_ANSWERS)
    assert api.post(f"/applications/{app_id}/approve").status_code == 200
    r = api.post(f"/applications/{app_id}/submit")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["attempt"]["status"] == "succeeded" and body["attempt"]["result"].startswith("MP-")
    assert body["state"] == "submitted" and body["next_follow_up"] is not None

    assert len(clean_portal.submissions) == 1
    sent = clean_portal.submissions[0]
    assert sent["first_name"] == "Alex" and sent["email"] == "alex@example.org" and sent["german"] == "A2"
    assert sent["permit"] == "yes" and sent["sponsorship"] == "no" and sent["privacy"] == "accepted"
    assert sent["salary"] == "" and sent["gender"] == ""  # left empty on purpose
    assert sent["resume"]["filename"].endswith(".pdf") and sent["resume"]["size"] > 1000
    assert sent["cover"]["size"] > 1000


def test_retries_never_submit_twice(api, clean_portal):
    app_id = documents_ready_app(api)
    _prepare(api, app_id, clean_portal.url("standard"))
    answer(api, app_id, STANDARD_ANSWERS)
    api.post(f"/applications/{app_id}/approve")
    key = "submit-once"
    first = api.post(f"/applications/{app_id}/submit", key=key).json()
    replay = api.post(f"/applications/{app_id}/submit", key=key).json()  # double click / network retry
    assert replay["attempt"]["id"] == first["attempt"]["id"]
    r = api.post(f"/applications/{app_id}/submit")  # a fresh attempt after success
    assert r.status_code == 409
    assert len(clean_portal.submissions) == 1


def test_unclear_outcome_stops_until_you_check(api, db, clean_portal):
    app_id = documents_ready_app(api)
    _prepare(api, app_id, clean_portal.url("ambiguous"))
    answer(api, app_id, STANDARD_ANSWERS)
    api.post(f"/applications/{app_id}/approve")
    r = api.post(f"/applications/{app_id}/submit").json()
    assert r["attempt"]["status"] == "unknown" and r["state"] == "needs_manual_input"
    alert = db.scalar(select(m.Notification).where(m.Notification.alert_key == f"submission-unknown:{app_id}"))
    assert alert is not None and alert.severity == "critical"

    r = api.post(f"/applications/{app_id}/submit")
    assert r.status_code == 409  # no blind retry
    assert len(clean_portal.submissions) == 1

    d = api.post(f"/applications/{app_id}/submission-outcome", {"submitted": True, "note": "email received"},
                 key=None).json()
    assert d["state"] == "submitted"
    db.expire_all()
    assert db.scalar(select(m.Notification).where(m.Notification.alert_key == f"submission-unknown:{app_id}")
                     ).resolved_at is not None


def test_server_error_is_unknown_not_failed(api, clean_portal):
    """A 500 after posting may still have stored the application, so it is never retried automatically."""
    app_id = documents_ready_app(api)
    _prepare(api, app_id, clean_portal.url("error"))
    answer(api, app_id, STANDARD_ANSWERS)
    api.post(f"/applications/{app_id}/approve")
    r = api.post(f"/applications/{app_id}/submit").json()
    assert r["attempt"]["status"] == "unknown"
    assert len(clean_portal.submissions) == 1  # the portal did receive it
    d = api.post(f"/applications/{app_id}/submission-outcome", {"submitted": False}, key=None).json()
    assert d["state"] == "awaiting_user_review"  # you checked: not received, you may try again


def test_form_validation_failure_sends_nothing(api, clean_portal):
    app_id = documents_ready_app(api)
    _prepare(api, app_id, clean_portal.url("standard"))
    answer(api, app_id, {**STANDARD_ANSWERS, "privacy": "unchecked"})  # required consent not given
    api.post(f"/applications/{app_id}/approve")
    r = api.post(f"/applications/{app_id}/submit").json()
    assert r["attempt"]["status"] == "failed" and r["state"] == "awaiting_user_review"
    assert clean_portal.submissions == []


def test_required_fields_cannot_be_skipped(api, clean_portal):
    app_id = documents_ready_app(api)
    d = _prepare(api, app_id, clean_portal.url("standard"))
    privacy = next(f for f in d["form_fields"] if f["field_key"] == "privacy")
    r = api.patch(f"/applications/{app_id}/form-fields/{privacy['id']}", {"skip": True}, key=None)
    assert r.status_code == 422


def test_invalid_option_is_rejected(api, clean_portal):
    app_id = documents_ready_app(api)
    d = _prepare(api, app_id, clean_portal.url("standard"))
    permit = next(f for f in d["form_fields"] if f["field_key"] == "permit")
    r = api.patch(f"/applications/{app_id}/form-fields/{permit['id']}", {"proposed_value": "maybe"}, key=None)
    assert r.status_code == 422


def test_changing_a_value_after_approval_requires_new_approval(api, clean_portal):
    app_id = documents_ready_app(api)
    _prepare(api, app_id, clean_portal.url("standard"))
    answer(api, app_id, STANDARD_ANSWERS)
    api.post(f"/applications/{app_id}/approve")
    d = answer(api, app_id, {"salary": "55000"})
    assert d["approval"] is None
    r = api.post(f"/applications/{app_id}/submit")
    assert r.json()["error"]["code"] == "approval_required"
    assert clean_portal.submissions == []


@pytest.mark.parametrize("variant,reason", [("captcha", "CAPTCHA"), ("login", "signing in"), ("offsite", "leave")])
def test_human_only_pages_become_manual_handoffs(api, clean_portal, variant, reason):
    app_id = documents_ready_app(api)
    d = _prepare(api, app_id, clean_portal.url(variant))
    assert d["state"] == "awaiting_user_review" and d["preparation"]["mode"] == "manual"
    assert reason in d["preparation"]["reason"] and d["form_fields"] == []
    if variant == "offsite":
        assert any("tracker.invalid" in b for b in d["preparation"]["blocked_requests"])
    r = api.post(f"/applications/{app_id}/submit")
    assert r.status_code == 409 and r.json()["error"]["code"] == "wrong_mode"


def test_manual_application_is_recorded_after_approval(api, clean_portal):
    app_id = documents_ready_app(api)
    d = _prepare(api, app_id, "https://www.linkedin.com/jobs/view/4012345678/apply")
    assert d["preparation"]["mode"] == "manual" and "Linkedin" in d["preparation"]["reason"]
    r = api.post(f"/applications/{app_id}/mark-submitted", {"note": "Easy Apply"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "approval_required"
    assert api.post(f"/applications/{app_id}/approve").status_code == 200
    d = api.post(f"/applications/{app_id}/mark-submitted", {"note": "Easy Apply"}).json()
    assert d["state"] == "submitted"
    assert d["submission_attempts"][0]["mode"] == "manual"


def test_private_addresses_blocked_by_default(api, clean_portal, monkeypatch):
    app_id = documents_ready_app(api)
    monkeypatch.setattr(get_settings(), "browser_allow_private_hosts", False)
    r = api.post(f"/applications/{app_id}/prepare", {"apply_url": clean_portal.url("standard")})
    assert r.status_code == 422 and r.json()["error"]["code"] == "blocked"
    r = api.post(f"/applications/{app_id}/prepare", {"apply_url": "file:///etc/passwd"})
    assert r.status_code == 422


def test_preparation_requires_verified_documents(api, clean_portal):
    from tests.conftest import approved_job, load_test_profile

    load_test_profile(api)
    job = approved_job(api)
    r = api.post(f"/applications/{job['application']['id']}/prepare", {"apply_url": clean_portal.url("standard")})
    assert r.status_code == 409 and r.json()["error"]["code"] == "invalid_state"
