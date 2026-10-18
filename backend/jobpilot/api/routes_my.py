"""The simple app: my matching jobs (with CV, cover letter, apply link), and the jobs I applied to."""

import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Literal
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from jobpilot.agents.discovery.adapters.base import company_matches, job_type
from jobpilot.api.deps import current_user
from jobpilot.api.routes_jobs import latest_evaluations
from jobpilot.config import get_settings
from jobpilot.db import models as m
from jobpilot.db.session import get_db
from jobpilot.documents import service as documents
from jobpilot.domain import transitions
from jobpilot.domain.errors import DomainError, NotFound
from jobpilot.domain.states import INACTIVE, Actor, State
from jobpilot.orchestrator import matching, runs

router = APIRouter(prefix="/my", tags=["my"], dependencies=[Depends(current_user)])

OPEN_STATES = ["classified", "approved_for_preparation", "documents_ready", "form_prepared", "awaiting_user_review",
               "needs_manual_input"]
APPLIED_STATES = ["submitted", "follow_up", "closed"]
PASTED_HOST = "pasted.jobpilot.invalid"  # jobs you pasted without a link; never opened, never fetched


def _summary(text: str, n: int = 320) -> str:
    t = " ".join((text or "").split())
    return t if len(t) <= n else t[:n].rsplit(" ", 1)[0] + " …"


def _docs(db: Session, app_id) -> dict:
    out = {}
    for kind, d in documents_latest(db, app_id).items():
        problems = d.verification.get("unsupported_claims") or []
        out[kind] = {"id": d.id, "version": d.version_no, "ready": d.status == "ready",
                     "problems": [str(p)[:200] for p in problems[:3]], "problem_count": len(problems)}
    return out


def documents_latest(db: Session, app_id) -> dict[str, m.Document]:
    rows = db.scalars(select(m.Document).where(m.Document.application_id == app_id)
                      .order_by(m.Document.version_no.desc())).all()
    latest: dict[str, m.Document] = {}
    for d in rows:
        latest.setdefault(d.kind, d)
    return latest


def _targets(db: Session) -> list[str]:
    """The companies you listed in any search ("BMW", "Mercedes-Benz" …)."""
    out: list[str] = []
    for f in db.scalars(select(m.SearchConfig.filters)).all():
        out += [c for c in (f or {}).get("companies", []) if isinstance(c, str) and c.strip()]
    return list(dict.fromkeys(out))


def _card(db: Session, app: m.Application, ev: m.JobMatchEvaluation | None, targets: list[str] | None = None) -> dict:
    j = app.job
    targets = _targets(db) if targets is None else targets
    return {
        "kind": job_type(j.title), "target_company": company_matches(j.company, targets) if targets else None,
        "application_id": app.id, "job_id": j.id, "state": app.state,
        "title": j.title, "company": j.company, "city": j.city, "country": j.country, "work_mode": j.work_mode,
        "posted": j.published_at, "found": j.retrieved_at, "url": j.url, "source": j.source.name,
        "has_link": urlsplit(j.url).hostname != PASTED_HOST, "added_by_you": j.source.access_mode == "manual",
        "summary": _summary(j.description_text),
        "score": ev.score if ev else None, "recommendation": ev.recommendation if ev else None,
        "why": (ev.explanation or "")[:400] if ev else "", "matched": (ev.matched_skills or [])[:8] if ev else [],
        "missing": (ev.missing_skills or [])[:5] if ev else [],
        "warnings": ((ev.eligibility or {}).get("failed", []) + (ev.eligibility or {}).get("uncertain", []))[:3]
        if ev else [],
        "documents": _docs(db, app.id),
        "applied_on": app.submitted_at, "outcome": app.outcome, "next_follow_up": app.next_follow_up,
    }


@router.get("/jobs")
def my_jobs(include_weak: bool = False, db: Session = Depends(get_db)):
    """Open, real jobs that match your verified profile, best first."""
    apps = db.scalars(select(m.Application).join(m.Job, m.Job.id == m.Application.job_id)
                      .where(m.Application.state.in_(OPEN_STATES), m.Job.availability != "closed",
                             m.Job.duplicate_of_id.is_(None))).all()
    evs = latest_evaluations(db, [a.job_id for a in apps])
    wanted = {"apply", "review"} | ({"low_priority"} if include_weak else set())
    targets = _targets(db)
    cards = [_card(db, a, evs.get(a.job_id), targets) for a in apps
             if a.job.source.access_mode != "mock" or get_settings().test_jobs_enabled]
    # a company you asked for is shown even when the score is low (never when you are not eligible)
    cards = [c for c in cards if c["recommendation"] in wanted or c["added_by_you"]
             or (c["target_company"] and c["recommendation"] == "low_priority")]
    cards.sort(key=lambda c: (-(c["score"] or 0), str(c["found"])))
    hidden = len(apps) - len(cards)
    return {"jobs": cards, "hidden_weak": hidden}


def _app(db: Session, app_id: uuid.UUID) -> m.Application:
    app = db.get(m.Application, app_id)
    if app is None:
        raise NotFound("Job")
    return app


@router.post("/jobs/{app_id}/documents")
def make_documents(app_id: uuid.UUID, db: Session = Depends(get_db)):
    """One click: approve the job for preparation if needed, then write the CV and cover letter."""
    return _make_documents(db, app_id)


def _make_documents(db: Session, app_id: uuid.UUID) -> dict:
    app = _app(db, app_id)
    if app.state == State.CLASSIFIED:
        if app.job.source.access_mode in ("api", "feed") and runs.recheck_availability(db, app.job) == "closed":
            transitions.apply(db, app.id, State.EXPIRED, Actor.ORCHESTRATOR, "listing closed on recheck")
            db.commit()
            raise DomainError("listing_closed", "This job is no longer online, so it was removed from your list")
        transitions.apply(db, app.id, State.APPROVED_FOR_PREPARATION, Actor.USER, "CV and cover letter requested")
        app.decision = "approve"
        db.flush()
    if app.state not in (State.APPROVED_FOR_PREPARATION, State.DOCUMENTS_READY):
        raise DomainError("invalid_state", "Documents can't be changed at this stage", {"state": app.state})
    documents.generate(db, app.id)
    db.commit()
    db.refresh(app)
    return _card(db, app, latest_evaluations(db, [app.job_id]).get(app.job_id))


class AppliedIn(BaseModel):
    note: str | None = Field(default=None, max_length=300)


@router.post("/jobs/{app_id}/applied")
def mark_applied(app_id: uuid.UUID, body: AppliedIn, db: Session = Depends(get_db)):
    """You applied on the employer's site yourself: move the job to your history with a follow-up reminder."""
    app = db.scalar(select(m.Application).where(m.Application.id == app_id).with_for_update())
    if app is None:
        raise NotFound("Job")
    if app.state in APPLIED_STATES:
        raise DomainError("already_applied", "This job is already in your history")
    due = date.today() + timedelta(days=get_settings().follow_up_days)
    app.next_follow_up = due
    transitions.apply(db, app.id, State.SUBMITTED, Actor.USER_RECORD,
                      "applied on the employer's site" + (f": {body.note}" if body.note else ""))
    db.add(m.FollowUp(application_id=app.id, due_on=due, note="Check for a reply"))
    db.commit()
    return _card(db, app, latest_evaluations(db, [app.job_id]).get(app.job_id))


@router.post("/jobs/{app_id}/dismiss")
def dismiss(app_id: uuid.UUID, db: Session = Depends(get_db)):
    """Not interested: hide this job."""
    app = _app(db, app_id)
    if State(app.state) in INACTIVE or app.state in APPLIED_STATES:
        raise DomainError("invalid_state", "This job is not in your list")
    to = State.REJECTED if app.state == State.CLASSIFIED else State.WITHDRAWN
    transitions.apply(db, app.id, to, Actor.USER, "not interested")
    app.decision = "reject"
    db.commit()
    return {"ok": True}


@router.get("/history")
def history(db: Session = Depends(get_db)):
    """Jobs you applied to, newest first."""
    apps = db.scalars(select(m.Application).where(m.Application.state.in_(APPLIED_STATES))
                      .order_by(m.Application.submitted_at.desc().nulls_last())).all()
    evs = latest_evaluations(db, [a.job_id for a in apps])
    targets = _targets(db)
    return [_card(db, a, evs.get(a.job_id), targets) for a in apps]


class OutcomeIn(BaseModel):
    outcome: str | None = Field(default=None, max_length=64)
    next_follow_up: date | None = None


@router.patch("/history/{app_id}")
def update_history(app_id: uuid.UUID, body: OutcomeIn, db: Session = Depends(get_db)):
    app = _app(db, app_id)
    if app.state not in APPLIED_STATES:
        raise DomainError("invalid_state", "Only jobs you applied to can be tracked here")
    fields = body.model_fields_set
    if "outcome" in fields:
        app.outcome = body.outcome or None
    if "next_follow_up" in fields:
        app.next_follow_up = body.next_follow_up
    app.last_action, app.last_action_at = "updated in history", datetime.now(UTC)
    db.commit()
    return _card(db, app, latest_evaluations(db, [app.job_id]).get(app.job_id))


class PasteIn(BaseModel):
    title: str = Field(min_length=2, max_length=255)
    company: str = Field(min_length=1, max_length=255)
    job_text: str = Field(min_length=50, max_length=20000)
    company_details: str | None = Field(default=None, max_length=6000)
    url: str | None = Field(default=None, max_length=2000, pattern=r"^https?://")
    city: str | None = Field(default=None, max_length=120)
    work_mode: Literal["onsite", "hybrid", "remote"] | None = None


@router.post("/paste", status_code=201)
def paste_job(body: PasteIn, db: Session = Depends(get_db)):
    """A job description you pasted: score it and write the CV and cover letter in one go."""
    text = body.job_text.strip()
    if body.company_details and body.company_details.strip():
        text += "\n\nAbout the company:\n" + body.company_details.strip()
    url = body.url or f"https://{PASTED_HOST}/{uuid.uuid4()}"
    job, outcome = runs.import_url(db, url, {"title": body.title.strip(), "company": body.company.strip(),
                                             "city": body.city, "country": "DE" if body.city else None,
                                             "work_mode": body.work_mode, "description": text})
    if outcome == "new":
        matching.classify_pending(db)
    db.flush()
    app = db.scalar(select(m.Application).where(m.Application.job_id == job.id)
                    .order_by(m.Application.created_at.desc()))
    if app is None:
        raise DomainError("not_scored", "The job was saved but could not be scored; open Jobs and try again")
    if app.state in (State.CLASSIFIED, State.APPROVED_FOR_PREPARATION, State.DOCUMENTS_READY):
        card = _make_documents(db, app.id)
    else:
        db.commit()
        card = _card(db, app, latest_evaluations(db, [job.id]).get(job.id))
    return {**card, "outcome": outcome}


class Turn(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=8000)


class AskIn(BaseModel):
    messages: list[Turn] = Field(min_length=1, max_length=40)
    application_id: uuid.UUID | None = None


@router.post("/assistant")
def ask_assistant(body: AskIn, db: Session = Depends(get_db)):
    from jobpilot import assistant

    return assistant.ask(db, [t.model_dump() for t in body.messages], body.application_id)
