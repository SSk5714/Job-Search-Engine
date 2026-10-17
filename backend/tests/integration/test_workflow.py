"""State machine, approval enforcement, idempotency and failure safety
(acceptance criteria 7, 8, 9 and the transition rules)."""

import hashlib
import threading
import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import func, select

from jobpilot.db import models as m
from jobpilot.db.session import SessionLocal
from jobpilot.domain import approvals, transitions
from jobpilot.domain.errors import DomainError
from jobpilot.domain.states import Actor, State
from tests.conftest import run_mock_search, verify_facts


def _first_job(api) -> dict:
    run_mock_search(api)
    return api.get("/jobs").json()["items"][0]


def _move(db, app_id, *states):
    for s in states:
        transitions.apply(db, app_id, s, Actor.ORCHESTRATOR)
    db.commit()


def _prepare_for_review(db, app_id) -> None:
    """Simulate Phases 3-4 output: verified documents and prepared form fields."""
    app = db.get(m.Application, app_id)
    version_id = db.scalar(select(m.CandidateProfile.current_version_id))
    for kind in ("cv", "cover_letter"):
        db.add(m.Document(application_id=app_id, kind=kind, version_no=1, profile_version_id=version_id,
                          content_hash=hashlib.sha256(kind.encode()).hexdigest(), status="ready",
                          verification={"unsupported_claims": []}))
    db.add(m.FormField(application_id=app_id, field_key="email", label="Email", field_type="email",
                       proposed_value="me@example.org", needs_manual=False, confidence=0.99))
    db.add(m.FormField(application_id=app_id, field_key="salary", label="Salary expectation", field_type="text",
                       sensitivity="sensitive", proposed_value=None, needs_manual=True))
    app.job.availability_checked_at = datetime.now(UTC)
    db.flush()
    _move(db, app_id, State.DOCUMENTS_READY, State.FORM_PREPARED, State.AWAITING_USER_REVIEW)


def test_user_approves_and_rejects_jobs_through_the_state_machine(api, db):
    job = _first_job(api)
    r = api.post(f"/jobs/{job['id']}/decision", {"decision": "approve"})
    assert r.status_code == 200, r.text
    assert r.json()["application"]["state"] == "approved_for_preparation"
    hist = api.get(f"/applications/{job['application']['id']}").json()["history"]
    assert [h["to_state"] for h in hist] == ["discovered", "classified", "approved_for_preparation"]
    assert hist[-1]["actor"] == "user"


def test_invalid_transition_is_refused_and_changes_nothing(api, db):
    job = _first_job(api)
    app_id = job["application"]["id"]
    r = api.post(f"/applications/{app_id}/transitions", {"to_state": "submitted"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "invalid_transition"
    assert api.get(f"/applications/{app_id}").json()["state"] == "classified"


def test_user_cannot_make_orchestrator_moves(api):
    job = _first_job(api)
    api.post(f"/jobs/{job['id']}/decision", {"decision": "approve"})
    r = api.post(f"/applications/{job['application']['id']}/transitions", {"to_state": "documents_ready"})
    assert r.status_code == 403 and r.json()["error"]["code"] == "forbidden_actor"


def test_guard_blocks_documents_ready_without_verified_documents(api, db):
    job = _first_job(api)
    api.post(f"/jobs/{job['id']}/decision", {"decision": "approve"})
    with pytest.raises(DomainError) as e:
        transitions.apply(db, uuid.UUID(job["application"]["id"]), State.DOCUMENTS_READY, Actor.ORCHESTRATOR)
    assert e.value.code == "guard_failed"


def test_idempotent_replay_applies_once(api, db):
    job = _first_job(api)
    key = str(uuid.uuid4())
    r1 = api.post(f"/jobs/{job['id']}/decision", {"decision": "approve"}, key=key)
    r2 = api.post(f"/jobs/{job['id']}/decision", {"decision": "approve"}, key=key)
    assert r1.status_code == r2.status_code == 200
    assert r2.headers.get("Idempotent-Replay") == "true"
    n = db.scalar(select(func.count()).select_from(m.ApplicationStateHistory).where(
        m.ApplicationStateHistory.to_state == "approved_for_preparation"))
    assert n == 1


def test_reused_key_with_different_body_is_rejected(api):
    job = _first_job(api)
    key = str(uuid.uuid4())
    api.post(f"/jobs/{job['id']}/decision", {"decision": "later"}, key=key)
    r = api.post(f"/jobs/{job['id']}/decision", {"decision": "reject"}, key=key)
    assert r.status_code == 422 and r.json()["error"]["code"] == "idempotency_key_reused"


def test_state_changes_require_an_idempotency_key(api):
    job = _first_job(api)
    r = api.post(f"/jobs/{job['id']}/decision", {"decision": "approve"}, key=None)
    assert r.status_code == 400 and r.json()["error"]["code"] == "idempotency_key_required"


def test_stale_version_is_refused(api):
    job = _first_job(api)
    app_id = job["application"]["id"]
    r = api.post(f"/applications/{app_id}/transitions", {"to_state": "withdrawn", "expected_version": 1})
    assert r.status_code == 409 and r.json()["error"]["code"] == "stale_version"


def test_submit_is_blocked_without_approval(api, db):
    verify_facts(api)
    job = _first_job(api)
    app_id = uuid.UUID(job["application"]["id"])
    api.post(f"/jobs/{job['id']}/decision", {"decision": "approve"})
    _prepare_for_review(db, app_id)
    r = api.post(f"/applications/{app_id}/submit")
    assert r.status_code == 409 and r.json()["error"]["code"] == "approval_required"
    with pytest.raises(DomainError) as e:
        transitions.apply(db, app_id, State.SUBMITTED, Actor.ORCHESTRATOR)
    assert e.value.code == "approval_required"


def test_approval_requires_resolving_manual_fields_first(api, db):
    job = _first_job(api)
    app_id = uuid.UUID(job["application"]["id"])
    api.post(f"/jobs/{job['id']}/decision", {"decision": "approve"})
    _prepare_for_review(db, app_id)
    r = api.post(f"/applications/{app_id}/approve")
    assert r.status_code == 409 and r.json()["error"]["code"] == "unresolved_fields"
    assert r.json()["error"]["details"]["fields"] == ["salary"]


def test_editing_a_form_value_invalidates_the_approval(api, db):
    job = _first_job(api)
    app_id = uuid.UUID(job["application"]["id"])
    api.post(f"/jobs/{job['id']}/decision", {"decision": "approve"})
    _prepare_for_review(db, app_id)
    detail = api.get(f"/applications/{app_id}").json()
    salary = next(f for f in detail["form_fields"] if f["field_key"] == "salary")
    api.patch(f"/applications/{app_id}/form-fields/{salary['id']}", {"proposed_value": "Negotiable"}, key=None)
    r = api.post(f"/applications/{app_id}/approve")
    assert r.status_code == 200, r.text
    assert api.get(f"/applications/{app_id}").json()["approval"] is not None

    email = next(f for f in detail["form_fields"] if f["field_key"] == "email")
    r = api.patch(f"/applications/{app_id}/form-fields/{email['id']}", {"proposed_value": "other@example.org"},
                  key=None)
    assert r.json()["approval_invalidated"] is True
    r = api.post(f"/applications/{app_id}/submit")
    assert r.json()["error"]["code"] == "approval_required"


def test_changed_document_makes_approval_stale(api, db):
    job = _first_job(api)
    app_id = uuid.UUID(job["application"]["id"])
    api.post(f"/jobs/{job['id']}/decision", {"decision": "approve"})
    _prepare_for_review(db, app_id)
    salary = db.scalar(select(m.FormField).where(m.FormField.field_key == "salary"))
    salary.proposed_value, salary.value_source = "Negotiable", "user"  # your answer, as the UI records it
    db.commit()
    assert api.post(f"/applications/{app_id}/approve").status_code == 200

    db.expire_all()
    db.add(m.Document(application_id=app_id, kind="cv", version_no=2,
                      profile_version_id=db.scalar(select(m.CandidateProfile.current_version_id)),
                      content_hash="changed", status="ready", verification={"unsupported_claims": []}))
    db.commit()
    r = api.post(f"/applications/{app_id}/submit")
    assert r.json()["error"]["code"] == "approval_stale"
    db.expire_all()
    assert approvals.valid_approval(db, app_id) is None  # invalidation persisted


def test_failed_operation_leaves_records_consistent(api, db):
    """A guard failure mid-request rolls back fully: no half-written state or history."""
    job = _first_job(api)
    app_id = job["application"]["id"]
    before = api.get(f"/applications/{app_id}").json()
    api.post(f"/applications/{app_id}/transitions", {"to_state": "submitted"})
    after = api.get(f"/applications/{app_id}").json()
    assert after["state"] == before["state"]
    assert after["state_version"] == before["state_version"]
    assert after["history"] == before["history"]


def test_concurrent_transitions_apply_exactly_once(api):
    job = _first_job(api)
    app_id = uuid.UUID(job["application"]["id"])
    results: list[str] = []

    def worker():
        s = SessionLocal()
        try:
            transitions.apply(s, app_id, State.APPROVED_FOR_PREPARATION, Actor.USER)
            s.commit()
            results.append("ok")
        except DomainError as e:
            s.rollback()
            results.append(e.code)
        finally:
            s.close()

    threads = [threading.Thread(target=worker) for _ in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert results.count("ok") == 1
    assert set(results) - {"ok"} <= {"invalid_transition"}


def test_only_one_active_application_per_job(api, db):
    job = _first_job(api)
    with pytest.raises(Exception):
        transitions.create_application(db, uuid.UUID(job["id"]))
        db.commit()
    db.rollback()


def test_interrupt_returns_to_previous_state(api, db):
    job = _first_job(api)
    app_id = uuid.UUID(job["application"]["id"])
    _move(db, app_id, State.NEEDS_MANUAL_INPUT)
    r = api.post(f"/applications/{app_id}/transitions", {"to_state": "approved_for_preparation"})
    assert r.json()["error"]["code"] == "invalid_transition"
    r = api.post(f"/applications/{app_id}/transitions", {"to_state": "classified", "reason": "resolved"})
    assert r.status_code == 200 and r.json()["state"] == "classified"
