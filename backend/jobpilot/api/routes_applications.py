import csv
import io
import uuid
from datetime import date

from fastapi import APIRouter, Depends, Request
from fastapi.responses import FileResponse, StreamingResponse
from typing import Literal

from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from jobpilot.api import serializers as s
from jobpilot.api.deps import current_user, run_idempotent
from jobpilot.api.routes_jobs import latest_evaluations
from jobpilot.db import models as m
from jobpilot.db.session import get_db
from jobpilot.documents import service as documents
from jobpilot.domain import approvals, transitions
from jobpilot.domain.errors import DomainError, NotFound
from jobpilot.domain.states import Actor, State

router = APIRouter(prefix="/applications", tags=["applications"], dependencies=[Depends(current_user)])

CSV_COLUMNS = ["company", "role", "country", "city", "score", "state", "decision", "applied_on",
               "last_action", "next_follow_up", "outcome", "source_url", "discovered_at"]


def _rows(db: Session, state: str | None, q: str | None, country: str | None,
          include_unreviewed: bool) -> list[dict]:
    stmt = select(m.Application).order_by(m.Application.updated_at.desc())
    if state:
        stmt = stmt.where(m.Application.state == state)
    elif not include_unreviewed:
        stmt = stmt.where(m.Application.state.not_in([State.DISCOVERED.value, State.CLASSIFIED.value]))
    apps = db.scalars(stmt).all()
    evs = latest_evaluations(db, [a.job_id for a in apps])
    out = []
    for a in apps:
        if country and (a.job.country or "").upper() != country.upper():
            continue
        if q and q.lower() not in f"{a.job.company} {a.job.title}".lower():
            continue
        ev = evs.get(a.job_id)
        out.append(s.application_row(a, ev.score if ev else None))
    return out


@router.get("")
def list_applications(db: Session = Depends(get_db), state: str | None = None, q: str | None = None,
                      country: str | None = None, include_unreviewed: bool = False):
    return _rows(db, state, q, country, include_unreviewed)


@router.get("/export.csv")
def export_csv(db: Session = Depends(get_db), include_unreviewed: bool = True):
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=CSV_COLUMNS, extrasaction="ignore")
    writer.writeheader()
    for row in _rows(db, None, None, None, include_unreviewed):
        writer.writerow({k: ("" if row.get(k) is None else row[k]) for k in CSV_COLUMNS})
    buf.seek(0)
    return StreamingResponse(iter([buf.getvalue()]), media_type="text/csv",
                             headers={"Content-Disposition": 'attachment; filename="jobpilot-applications.csv"'})


def _doc_out(d: m.Document) -> dict:
    return {"id": d.id, "kind": d.kind, "version_no": d.version_no, "status": d.status,
            "content_hash": d.content_hash, "verification": d.verification, "content": d.content,
            "generator": d.generator, "model_version": d.model_version, "created_at": d.created_at}


def _get(db: Session, app_id: uuid.UUID) -> m.Application:
    app = db.get(m.Application, app_id)
    if app is None:
        raise NotFound("Application")
    return app


def _detail(db: Session, app: m.Application) -> dict:
    ev = latest_evaluations(db, [app.job_id]).get(app.job_id)
    hist = db.scalars(select(m.ApplicationStateHistory)
                      .where(m.ApplicationStateHistory.application_id == app.id)
                      .order_by(m.ApplicationStateHistory.at)).all()
    docs = db.scalars(select(m.Document).where(m.Document.application_id == app.id)
                      .order_by(m.Document.kind, m.Document.version_no)).all()
    fields = db.scalars(select(m.FormField).where(m.FormField.application_id == app.id)).all()
    appr = approvals.valid_approval(db, app.id)
    return {
        **s.application_row(app, ev.score if ev else None),
        "job": s.job(app.job, ev, app, detail=True),
        "history": [s.history(h) for h in hist],
        "documents": [_doc_out(d) for d in docs],
        "form_fields": [{"id": f.id, "field_key": f.field_key, "label": f.label, "field_type": f.field_type,
                         "sensitivity": f.sensitivity, "proposed_value": f.proposed_value,
                         "needs_manual": f.needs_manual, "confidence": f.confidence} for f in fields],
        "approval": {"id": appr.id, "approved_at": appr.approved_at} if appr else None,
        "allowed_transitions": [t.value for t in transitions.allowed_targets(db, app, Actor.USER)],
    }


@router.get("/{app_id}")
def get_application(app_id: uuid.UUID, db: Session = Depends(get_db)):
    return _detail(db, _get(db, app_id))


class TransitionIn(BaseModel):
    to_state: State
    reason: str | None = Field(default=None, max_length=500)
    expected_version: int | None = None


@router.post("/{app_id}/transitions")
def request_transition(app_id: uuid.UUID, body: TransitionIn, request: Request, db: Session = Depends(get_db)):
    def handler():
        app = transitions.apply(db, app_id, body.to_state, Actor.USER, body.reason,
                                request.headers.get("idempotency-key"), body.expected_version)
        return 200, _detail(db, app)

    return run_idempotent(db, request, f"POST /applications/{app_id}/transitions", body.model_dump(), handler)


class TrackerPatch(BaseModel):
    next_follow_up: date | None = None
    outcome: str | None = Field(default=None, max_length=64)


@router.patch("/{app_id}")
def update_tracking(app_id: uuid.UUID, body: TrackerPatch, db: Session = Depends(get_db)):
    """Tracker fields only. State never changes here."""
    app = _get(db, app_id)
    changes = body.model_dump(exclude_unset=True)
    for k, v in changes.items():
        setattr(app, k, v)
    if changes:
        app.last_action = "updated " + ", ".join(changes)
        if "next_follow_up" in changes and changes["next_follow_up"]:
            db.add(m.FollowUp(application_id=app.id, due_on=changes["next_follow_up"]))
    db.commit()
    return _detail(db, app)


class FieldPatch(BaseModel):
    proposed_value: str | None = Field(default=None, max_length=4000)
    needs_manual: bool | None = None


@router.patch("/{app_id}/form-fields/{field_id}")
def edit_field(app_id: uuid.UUID, field_id: uuid.UUID, body: FieldPatch, db: Session = Depends(get_db)):
    """Any edit to a proposed value invalidates the current approval."""
    app = _get(db, app_id)
    field = db.get(m.FormField, field_id)
    if field is None or field.application_id != app.id:
        raise NotFound("Form field")
    changes = body.model_dump(exclude_unset=True)
    for k, v in changes.items():
        setattr(field, k, v)
    if "proposed_value" in changes:
        field.value_source = "user"
    db.flush()
    invalidated = approvals.invalidate(db, app.id, f"form field '{field.field_key}' edited")
    db.commit()
    return {**_detail(db, app), "approval_invalidated": invalidated}


@router.post("/{app_id}/approve")
def approve(app_id: uuid.UUID, request: Request, db: Session = Depends(get_db)):
    def handler():
        app = _get(db, app_id)
        approvals.approve(db, app)
        app.last_action = "approved for submission"
        db.flush()
        return 200, _detail(db, app)

    return run_idempotent(db, request, f"POST /applications/{app_id}/approve", {}, handler)


@router.post("/{app_id}/submit")
def submit(app_id: uuid.UUID, db: Session = Depends(get_db)):
    """Phase 1 enforces the guard only; the browser submission arrives in Phase 4."""
    app = _get(db, app_id)
    if app.state != State.AWAITING_USER_REVIEW:
        raise DomainError("invalid_state", "Only applications awaiting your review can be submitted",
                          {"state": app.state})
    try:
        approvals.require_fresh_approval(db, app)
    except DomainError as err:
        if err.code == "approval_stale":
            db.commit()  # keep the invalidation
        raise
    unknown = db.scalar(select(m.SubmissionAttempt).where(m.SubmissionAttempt.application_id == app.id,
                                                          m.SubmissionAttempt.status == "unknown"))
    if unknown:
        raise DomainError("submission_outcome_unknown",
                          "A previous attempt ended ambiguously; check the portal before trying again")
    raise DomainError("not_implemented", "Automated submission arrives in Phase 4", status_code=501)


class GenerateIn(BaseModel):
    kinds: list[Literal["cv", "cover_letter"]] = Field(default_factory=lambda: ["cv", "cover_letter"])


@router.post("/{app_id}/documents/generate")
def generate_documents(app_id: uuid.UUID, body: GenerateIn, request: Request, db: Session = Depends(get_db)):
    """Tailored CV and cover letter from your verified facts (Claude when configured, else the template).
    Each is verified claim by claim; the application moves to documents_ready only when both pass."""
    def handler():
        documents.generate(db, app_id, tuple(dict.fromkeys(body.kinds)))
        return 200, _detail(db, _get(db, app_id))

    return run_idempotent(db, request, f"POST /applications/{app_id}/documents/generate", body.model_dump(), handler)


class EditIn(BaseModel):
    content: dict


@router.put("/{app_id}/documents/{kind}")
def edit_document(app_id: uuid.UUID, kind: str, body: EditIn, db: Session = Depends(get_db)):
    try:
        documents.edit(db, app_id, kind, body.content)
    except ValidationError as e:
        raise DomainError("validation_error", "Document content is malformed", {"errors": e.errors()[:5]},
                          status_code=422)
    db.commit()
    return _detail(db, _get(db, app_id))


@router.get("/{app_id}/documents/{doc_id}/download")
def download(app_id: uuid.UUID, doc_id: uuid.UUID, format: Literal["pdf", "docx"] = "pdf",
             db: Session = Depends(get_db)):
    doc = db.get(m.Document, doc_id)
    if doc is None or doc.application_id != app_id:
        raise NotFound("Document")
    path = documents.file_path(doc, format)
    if not path.exists():
        raise DomainError("file_missing", "The file for this version is missing; regenerate it", status_code=410)
    app = _get(db, app_id)
    safe = "".join(c if c.isalnum() else "-" for c in app.job.company)[:40].strip("-")
    media = "application/pdf" if format == "pdf" else \
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    return FileResponse(path, media_type=media, filename=f"{doc.kind}-{safe}-v{doc.version_no}.{format}")
