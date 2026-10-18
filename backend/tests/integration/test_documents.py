"""Phase 3: tailored documents end to end (acceptance criteria 4, 5, 8)."""

import io
import uuid
from datetime import UTC, datetime

import pytest
from docx import Document as Docx
from pypdf import PdfReader
from sqlalchemy import select

from jobpilot.db import models as m
from jobpilot.documents import service as documents
from jobpilot.documents.schema import CVContent
from jobpilot.domain import transitions
from jobpilot.domain.states import Actor, State
from tests.conftest import FakeProvider, approved_job, load_test_profile


def _pdf_text(data: bytes) -> str:
    return "\n".join(p.extract_text() for p in PdfReader(io.BytesIO(data)).pages)


def _generate(api, app_id):
    r = api.post(f"/applications/{app_id}/documents/generate", {})
    assert r.status_code == 200, r.text
    return r.json()


def test_template_documents_are_verified_rendered_and_advance_state(api, db):
    profile = load_test_profile(api)
    job = approved_job(api)
    app_id = job["application"]["id"]
    detail = _generate(api, app_id)
    assert detail["state"] == "documents_ready"
    docs = {d["kind"]: d for d in detail["documents"]}
    for kind in ("cv", "cover_letter"):
        d = docs[kind]
        assert d["status"] == "ready" and d["generator"] == "template" and d["version_no"] == 1
        assert d["verification"]["unsupported_claims"] == []
        assert d["verification"]["checked"] > 0

    # every claim cites verified facts (or is a pure courtesy sentence)
    verified_ids = {f["id"] for f in profile["facts"] if f["verified"]}
    for c in docs["cv"]["verification"]["claims"]:
        assert all(i in verified_ids or i.startswith("derived:") for i in c["fact_ids"])

    pdf = api.get(f"/applications/{app_id}/documents/{docs['cv']['id']}/download?format=pdf")
    assert pdf.status_code == 200 and pdf.content[:4] == b"%PDF"
    text = _pdf_text(pdf.content)
    for expected in ("Alex Example", "Acme Mobile Ltd", "Oct 2024 – Aug 2025", "Work Experience", "Education",
                     "M.Sc. Web Engineering", "Kotlin", "Binder IPC"):
        assert expected in text, expected
    assert "10 months" in text  # derived from dates, not rounded to "1 year"

    docx = api.get(f"/applications/{app_id}/documents/{docs['cover_letter']['id']}/download?format=docx")
    paragraphs = [p.text for p in Docx(io.BytesIO(docx.content)).paragraphs]
    body = "\n".join(paragraphs)
    assert "Dear Hiring Team," in body and "Android Developer (m/w/d)" in body and "Nordlicht Mobility GmbH" in body
    assert "Part-time up to 20 hours per week" in body


def test_unverified_facts_never_appear(api, db):
    load_test_profile(api, skip=("responsibility", "phone"))
    job = approved_job(api)
    detail = _generate(api, job["application"]["id"])
    cv = next(d for d in detail["documents"] if d["kind"] == "cv")
    text = str(cv["content"])
    assert "Binder IPC" not in text and "tombstones" not in text
    pdf = api.get(f"/applications/{job['application']['id']}/documents/{cv['id']}/download")
    assert "+49 000" not in _pdf_text(pdf.content)


def test_missing_name_blocks_ready(api, db):
    load_test_profile(api, skip=("full_name",))
    job = approved_job(api)
    detail = _generate(api, job["application"]["id"])
    assert detail["state"] == "approved_for_preparation"
    cv = next(d for d in detail["documents"] if d["kind"] == "cv")
    assert cv["status"] == "draft"
    assert any("full name" in x for x in cv["verification"]["structure_problems"])


def _fabricating(posting, facts):
    raise AssertionError("not used for documents")


class FakeDocProvider(FakeProvider):
    """Returns CV/letter content; the CV contains one invented claim."""

    def structured(self, *, system, user, schema, max_tokens=2048):
        from jobpilot.ai.provider import AIResult, AIUsage

        self.calls.append({"system": system, "user": user, "schema": schema})
        facts = __import__("json").loads(user.split("<verified_facts>\n", 1)[1].split("\n</verified_facts>", 1)[0])
        ids = {(f["category"], f.get("entry"), f["key"]): f["id"] for f in facts}
        kotlin = ids[("skill", None, "kotlin")]
        resp = next(f["id"] for f in facts if f["key"] == "responsibility")
        if schema is CVContent:
            out = {"headline": {"text": "Associate Software Engineer",
                                "fact_ids": [ids[("employment", "acme", "first_title")]]},
                   "summary": [{"text": "Android engineer with 3 years of Kotlin and Docker experience.",
                                "fact_ids": [kotlin]}],
                   "skill_groups": [{"name": "Relevant", "skill_fact_ids": [kotlin]}],
                   "experience": [{"entry": "acme", "bullets": [{"text": "Built custom system services using "
                                                                         "Binder IPC and AIDL.", "fact_ids": [resp]}]}],
                   "projects": [], "education_entries": ["master", "bachelor"], "certification_fact_ids": []}
        else:
            out = {"subject": "Application", "salutation": "Dear Hiring Team,", "sign_off": "Kind regards,",
                   "paragraphs": [{"sentences": [{"text": "I build Android system services with Kotlin.",
                                                  "fact_ids": [kotlin, resp]}]}]}
        return AIResult(output=schema(**out), usage=AIUsage(self.model, 3000, 800, 0.004))


@pytest.fixture
def doc_ai(monkeypatch):
    p = FakeDocProvider()
    monkeypatch.setattr(documents, "get_provider", lambda: p)
    return p


def test_claude_fabrication_is_caught_then_fixed_by_editing(api, db, doc_ai):
    load_test_profile(api)
    job = approved_job(api)
    app_id = job["application"]["id"]
    detail = _generate(api, app_id)
    assert detail["state"] == "approved_for_preparation"  # not ready: one claim is unsupported
    cv = next(d for d in detail["documents"] if d["kind"] == "cv")
    assert cv["generator"] == "claude" and cv["status"] == "draft"
    bad = [c for c in cv["verification"]["claims"] if c["status"] == "unsupported"]
    assert len(bad) == 1 and "Docker" in bad[0]["text"]
    reasons = " ".join(bad[0]["reasons"])
    assert "'docker'" in reasons and "'3'" in reasons

    # contact details are never sent to the model
    assert all("alex@example.org" not in c["user"] and "Alex Example" not in c["user"] for c in doc_ai.calls)
    assert "untrusted data" in doc_ai.calls[0]["system"]

    content = cv["content"]
    content["summary"][0]["text"] = "Engineer working with Kotlin."  # only what the cited fact supports
    r = api.c.put(f"/api/v1/applications/{app_id}/documents/cv", json={"content": content},
                  headers={"X-Requested-With": "jobpilot"})
    assert r.status_code == 200, r.text
    detail = r.json()
    cv2 = max((d for d in detail["documents"] if d["kind"] == "cv"), key=lambda d: d["version_no"])
    assert cv2["version_no"] == 2 and cv2["status"] == "ready" and cv2["generator"] == "user"
    assert detail["state"] == "approved_for_preparation"  # the letter still has an unsupported claim

    letter = max((d for d in detail["documents"] if d["kind"] == "cover_letter"), key=lambda d: d["version_no"])
    assert letter["status"] == "draft"
    assert any("'android'" in r for c in letter["verification"]["claims"] for r in c["reasons"])
    lc = letter["content"]
    lc["paragraphs"][0]["sentences"][0]["text"] = "I build system services with Kotlin, Binder IPC and AIDL."
    r = api.c.put(f"/api/v1/applications/{app_id}/documents/cover_letter", json={"content": lc},
                  headers={"X-Requested-With": "jobpilot"})
    detail = r.json()
    assert detail["state"] == "documents_ready"
    versions = db.scalars(select(m.Document).where(m.Document.kind == "cv")
                          .order_by(m.Document.version_no)).all()
    assert [v.status for v in versions] == ["superseded", "ready"]  # history kept

    attempts = db.scalars(select(m.TaskAttempt).join(m.AgentRun).where(m.AgentRun.agent == "documents")).all()
    assert len(attempts) == 2 and all(float(a.ai_cost_usd) == 0.004 for a in attempts)


def test_editing_after_approval_invalidates_it(api, db):
    load_test_profile(api)
    job = approved_job(api)
    app_id = uuid.UUID(job["application"]["id"])
    _generate(api, str(app_id))
    app = db.get(m.Application, app_id)
    app.job.availability_checked_at = datetime.now(UTC)
    db.add(m.FormField(application_id=app_id, field_key="email", label="Email", field_type="email",
                       proposed_value="alex@example.org", needs_manual=False, confidence=1.0))
    db.flush()
    transitions.apply(db, app_id, State.FORM_PREPARED, Actor.ORCHESTRATOR)
    transitions.apply(db, app_id, State.AWAITING_USER_REVIEW, Actor.ORCHESTRATOR)
    db.commit()
    assert api.post(f"/applications/{app_id}/approve").status_code == 200

    letter = max((d for d in api.get(f"/applications/{app_id}").json()["documents"] if d["kind"] == "cover_letter"),
                 key=lambda d: d["version_no"])
    content = letter["content"]
    content["sign_off"] = "Best regards,"
    r = api.c.put(f"/api/v1/applications/{app_id}/documents/cover_letter", json={"content": content},
                  headers={"X-Requested-With": "jobpilot"})
    assert r.status_code == 200 and r.json()["approval"] is None
    assert api.post(f"/applications/{app_id}/submit").json()["error"]["code"] == "approval_required"


def test_generation_requires_an_approved_job(api, db):
    load_test_profile(api)
    from tests.conftest import run_mock_search

    run_mock_search(api)
    job = api.get("/jobs").json()["items"][0]
    r = api.post(f"/applications/{job['application']['id']}/documents/generate", {})
    assert r.status_code == 409 and r.json()["error"]["code"] == "invalid_state"


def test_malformed_edit_is_rejected(api, db):
    load_test_profile(api)
    job = approved_job(api)
    _generate(api, job["application"]["id"])
    r = api.c.put(f"/api/v1/applications/{job['application']['id']}/documents/cv", json={"content": {"headline": 3}},
                  headers={"X-Requested-With": "jobpilot"})
    assert r.status_code == 422


def test_master_cv_and_profile_roundtrip(api, db):
    load_test_profile(api)
    r = api.get("/profile/master-cv?format=pdf")
    assert r.status_code == 200 and r.content[:4] == b"%PDF"
    assert "Alex Example" in _pdf_text(r.content)
    exported = api.get("/profile/export").json()
    assert exported["format"] == "jobpilot-profile-v1" and any(f["entry"] == "acme" for f in exported["facts"])
    r = api.post("/profile/import", {"format": "jobpilot-profile-v1", "facts": exported["facts"]})
    assert r.status_code == 200
    assert r.json()["verified_count"] == len(exported["facts"]) - sum(1 for f in exported["facts"] if not f["value"])
    # identical content keeps verification; changed content would reset it (see test_api)


def test_import_never_marks_new_facts_verified(api):
    r = api.post("/profile/import", {"format": "jobpilot-profile-v1",
                                     "facts": [{"category": "skill", "key": "rust", "value": "Rust",
                                                "context": "learning", "verified": True}]})
    assert r.status_code == 200 and r.json()["verified_count"] == 0
