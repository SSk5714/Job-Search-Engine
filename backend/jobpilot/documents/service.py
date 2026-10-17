"""Document versions for an application: generate (Claude or template), verify,
render DOCX + PDF, store, supersede old versions, invalidate approvals, and let
the orchestrator advance to documents_ready only when both are verified."""

import hashlib
import json
import logging
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from jobpilot.ai.provider import AIError, AIProvider, get_provider
from jobpilot.config import get_settings
from jobpilot.db import models as m
from jobpilot.documents import claude_gen, factbook, render
from jobpilot.documents.schema import CVContent, LetterContent
from jobpilot.documents.template import TemplateGenerator
from jobpilot.documents.verify import Verifier
from jobpilot.domain import approvals, transitions
from jobpilot.domain import settings as app_settings
from jobpilot.domain.errors import DomainError
from jobpilot.domain.profile import current_version
from jobpilot.domain.states import Actor, State
from jobpilot.orchestrator.matching import spent_today_usd

log = logging.getLogger("jobpilot.documents")
KINDS = ("cv", "cover_letter")
GENERATE_STATES = {State.APPROVED_FOR_PREPARATION, State.DOCUMENTS_READY}
EDIT_STATES = {State.APPROVED_FOR_PREPARATION, State.DOCUMENTS_READY, State.FORM_PREPARED,
               State.AWAITING_USER_REVIEW, State.NEEDS_MANUAL_INPUT}


def storage_root() -> Path:
    root = Path(get_settings().documents_dir)
    root.mkdir(parents=True, exist_ok=True)
    return root


def _job_dict(job: m.Job) -> dict:
    return {"title": job.title, "company": job.company, "description_text": job.description_text,
            "location_text": job.location_text, "city": job.city}


def _evaluation(db: Session, job_id) -> dict | None:
    ev = db.scalar(select(m.JobMatchEvaluation).where(m.JobMatchEvaluation.job_id == job_id)
                   .order_by(m.JobMatchEvaluation.created_at.desc()).limit(1))
    if ev is None:
        return None
    return {"matched_skills": ev.matched_skills, "missing_skills": ev.missing_skills, "track": ev.track,
            "seniority": ev.seniority}


def _hash(kind: str, content: dict, profile_version_id: str) -> str:
    raw = json.dumps({"kind": kind, "content": content, "profile": profile_version_id}, sort_keys=True)
    return hashlib.sha256(raw.encode()).hexdigest()


def _save(db: Session, app: m.Application, kind: str, content: CVContent | LetterContent, book, job: dict,
          generator: str, model_version: str | None, notes: list[str]) -> m.Document:
    verifier = Verifier(book, job)
    report = verifier.cv(content) if kind == "cv" else verifier.letter(content)
    report["notes"] = notes
    report["verified_at"] = datetime.now(UTC).isoformat()
    data = content.model_dump()
    version_no = (db.scalar(select(func.max(m.Document.version_no)).where(
        m.Document.application_id == app.id, m.Document.kind == kind)) or 0) + 1
    folder = storage_root() / str(app.id)
    folder.mkdir(parents=True, exist_ok=True)
    stem = f"{kind}-v{version_no}"
    if kind == "cv":
        docx_bytes, pdf_bytes = render.cv_docx(content, book), render.cv_pdf(content, book)
    else:
        docx_bytes, pdf_bytes = render.letter_docx(content, book, job), render.letter_pdf(content, book, job)
    (folder / f"{stem}.docx").write_bytes(docx_bytes)
    (folder / f"{stem}.pdf").write_bytes(pdf_bytes)

    for old in db.scalars(select(m.Document).where(m.Document.application_id == app.id, m.Document.kind == kind,
                                                   m.Document.status != "superseded")).all():
        old.status = "superseded"
    doc = m.Document(
        application_id=app.id, kind=kind, version_no=version_no, profile_version_id=uuid.UUID(book.version_id),
        content_hash=_hash(kind, data, book.version_id), docx_path=f"{app.id}/{stem}.docx",
        pdf_path=f"{app.id}/{stem}.pdf", verification=report, content=data, generator=generator,
        model_version=model_version, status="ready" if not report["unsupported_claims"] else "draft",
    )
    db.add(doc)
    db.flush()
    if approvals.invalidate(db, app.id, f"new {kind.replace('_', ' ')} version {version_no}"):
        report["notes"].append("The previous approval was invalidated by this change")
    return doc


def _maybe_ready(db: Session, app: m.Application) -> None:
    docs = approvals.current_documents(db, app.id)
    if app.state == State.APPROVED_FOR_PREPARATION and all(
            k in docs and docs[k].status == "ready" for k in KINDS):
        transitions.apply(db, app.id, State.DOCUMENTS_READY, Actor.ORCHESTRATOR, "CV and cover letter verified")


def generate(db: Session, app_id: uuid.UUID, kinds: tuple[str, ...] = KINDS,
             provider: AIProvider | None = None) -> list[m.Document]:
    app = db.scalar(select(m.Application).where(m.Application.id == app_id).with_for_update())
    if app is None:
        raise DomainError("not_found", "Application not found", status_code=404)
    if State(app.state) not in GENERATE_STATES:
        raise DomainError("invalid_state", "Approve the job for preparation before generating documents",
                          {"state": app.state})
    version = current_version(db)
    book = factbook.build(version)
    job, evaluation = _job_dict(app.job), _evaluation(db, app.job_id)
    ai = app_settings.get(db, "ai")
    if provider is None and ai.matcher != "rules":
        provider = get_provider()
    if ai.matcher == "rules":
        provider = None
    budget_left = ai.daily_budget_usd - spent_today_usd(db)
    agent_run = m.AgentRun(agent="documents", subject=str(app.id))
    db.add(agent_run)
    db.flush()

    created = []
    for kind in kinds:
        notes: list[str] = []
        started = time.monotonic()
        usage, error, content, generator, model_version = None, None, None, "template", "template-v1"
        if provider is not None and budget_left > 0:
            try:
                fn = claude_gen.cv if kind == "cv" else claude_gen.letter
                content, usage = fn(provider, book, job, evaluation)
                generator, model_version = "claude", f"claude/{claude_gen.PROMPT_VERSION}/{provider.model}"
                budget_left -= usage.cost_usd
            except AIError as e:
                error, usage = e, e.usage
                notes.append(f"Claude unavailable ({e.code}); generated from the template instead")
                db.add(m.ErrorEvent(component="documents:claude", severity="warning", task_id=agent_run.id,
                                    code=e.code, message=e.message[:1000], context={"application_id": str(app.id)}))
        elif provider is not None:
            notes.append("Daily AI budget reached; generated from the template")
        if content is None:
            gen = TemplateGenerator(book, job, evaluation)
            content = gen.cv() if kind == "cv" else gen.letter()
        db.add(m.TaskAttempt(agent_run_id=agent_run.id, attempt_no=1, status="failed" if error else "succeeded",
                             error_code=error.code if error else None,
                             duration_ms=int((time.monotonic() - started) * 1000),
                             ai_tokens_in=usage.input_tokens if usage else None,
                             ai_tokens_out=usage.output_tokens if usage else None,
                             ai_cost_usd=usage.cost_usd if usage else None))
        created.append(_save(db, app, kind, content, book, job, generator, model_version, notes))
    agent_run.status, agent_run.finished_at = "succeeded", datetime.now(UTC)
    agent_run.output_summary = {d.kind: {"version": d.version_no, "status": d.status, "generator": d.generator}
                                for d in created}
    app.last_action = "documents generated: " + ", ".join(f"{d.kind} v{d.version_no} ({d.status})" for d in created)
    _maybe_ready(db, app)
    db.flush()
    return created


def edit(db: Session, app_id: uuid.UUID, kind: str, content: dict) -> m.Document:
    """Your edits become a new version, are verified like any other, and invalidate approval."""
    if kind not in KINDS:
        raise DomainError("not_found", "Unknown document kind", status_code=404)
    app = db.scalar(select(m.Application).where(m.Application.id == app_id).with_for_update())
    if app is None:
        raise DomainError("not_found", "Application not found", status_code=404)
    if State(app.state) not in EDIT_STATES:
        raise DomainError("invalid_state", "Documents can't be edited in this state", {"state": app.state})
    parsed = CVContent(**content) if kind == "cv" else LetterContent(**content)
    book = factbook.build(current_version(db))
    doc = _save(db, app, kind, parsed, book, _job_dict(app.job), "user", None, ["Edited by you"])
    _maybe_ready(db, app)
    db.flush()
    return doc


def file_path(doc: m.Document, fmt: str) -> Path:
    rel = doc.pdf_path if fmt == "pdf" else doc.docx_path
    path = (storage_root() / rel).resolve()
    if storage_root().resolve() not in path.parents:
        raise DomainError("not_found", "File not found", status_code=404)
    return path


def master_cv(db: Session, fmt: str) -> bytes:
    """Your untailored CV from all verified facts. Never stored, never overwritten by tailoring."""
    book = factbook.build(current_version(db))
    content = TemplateGenerator(book, {"title": "", "description_text": ""}, None).cv()
    return render.cv_pdf(content, book) if fmt == "pdf" else render.cv_docx(content, book)
