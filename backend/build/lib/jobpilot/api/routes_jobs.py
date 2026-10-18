import uuid
from typing import Literal

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from jobpilot.api import serializers as s
from jobpilot.api.deps import current_user, run_idempotent
from jobpilot.db import models as m
from jobpilot.db.session import get_db
from jobpilot.domain import transitions
from jobpilot.domain.errors import DomainError, NotFound
from jobpilot.domain.states import INACTIVE, Actor, State
from jobpilot.orchestrator import matching, runs

router = APIRouter(prefix="/jobs", tags=["jobs"], dependencies=[Depends(current_user)])


def latest_evaluations(db: Session, job_ids: list[uuid.UUID]) -> dict[uuid.UUID, m.JobMatchEvaluation]:
    if not job_ids:
        return {}
    rows = db.scalars(select(m.JobMatchEvaluation).where(m.JobMatchEvaluation.job_id.in_(job_ids))
                      .order_by(m.JobMatchEvaluation.created_at.desc())).all()
    out: dict[uuid.UUID, m.JobMatchEvaluation] = {}
    for r in rows:
        out.setdefault(r.job_id, r)
    return out


def current_applications(db: Session, job_ids: list[uuid.UUID]) -> dict[uuid.UUID, m.Application]:
    """The active application per job, else the most recent one."""
    if not job_ids:
        return {}
    rows = db.scalars(select(m.Application).where(m.Application.job_id.in_(job_ids))
                      .order_by(m.Application.created_at.desc())).all()
    out: dict[uuid.UUID, m.Application] = {}
    for r in rows:
        cur = out.get(r.job_id)
        if cur is None or (State(cur.state) in INACTIVE and State(r.state) not in INACTIVE):
            out[r.job_id] = r
    return out


@router.get("")
def list_jobs(
    db: Session = Depends(get_db),
    state: str | None = None,
    track: str | None = None,
    min_score: int | None = None,
    q: str | None = None,
    include_duplicates: bool = False,
    include_closed: bool = False,
    limit: int = 50,
    offset: int = 0,
):
    stmt = select(m.Job)
    if not include_duplicates:
        stmt = stmt.where(m.Job.duplicate_of_id.is_(None))
    if not include_closed:
        stmt = stmt.where(m.Job.availability != "closed")
    jobs = db.scalars(stmt).all()
    ids = [j.id for j in jobs]
    evs, apps = latest_evaluations(db, ids), current_applications(db, ids)

    def keep(j: m.Job) -> bool:
        ev, app = evs.get(j.id), apps.get(j.id)
        if state and (app is None or app.state != state):
            return False
        if track and (ev is None or ev.track != track):
            return False
        if min_score is not None and (ev is None or ev.score < min_score):
            return False
        if q and q.lower() not in f"{j.company} {j.title} {j.city}".lower():
            return False
        return True

    rows = [j for j in jobs if keep(j)]
    rows.sort(key=lambda j: (-(evs[j.id].score if j.id in evs else -1), -(j.published_at.toordinal()
                                                                          if j.published_at else 0)))
    page = rows[offset : offset + min(limit, 200)]
    return {"total": len(rows), "items": [s.job(j, evs.get(j.id), apps.get(j.id)) for j in page]}


class ImportIn(BaseModel):
    url: str = Field(min_length=8, max_length=2000, pattern=r"^https?://")
    title: str | None = Field(default=None, max_length=255)
    company: str | None = Field(default=None, max_length=255)
    city: str | None = Field(default=None, max_length=120)
    country: str | None = Field(default=None, min_length=2, max_length=2)
    work_mode: Literal["onsite", "hybrid", "remote"] | None = None
    description: str | None = Field(default=None, max_length=20000)


@router.post("/import-url", status_code=201)
def import_url(body: ImportIn, request: Request, db: Session = Depends(get_db)):
    """Greenhouse, Lever, Personio and Bundesagentur links are fetched through their APIs.
    Links from LinkedIn, StepStone, Indeed, XING or anywhere else are never fetched:
    send the title, company and description with them."""
    def handler():
        manual = body.model_dump(exclude={"url"})
        if manual.get("country"):
            manual["country"] = manual["country"].upper()
        job, outcome = runs.import_url(db, body.url, manual)
        if outcome == "new":
            matching.classify_pending(db)
        db.flush()
        app = current_applications(db, [job.id]).get(job.id)
        return 201, {"outcome": outcome, "job": s.job(job, latest_evaluations(db, [job.id]).get(job.id), app)}

    return run_idempotent(db, request, "POST /jobs/import-url", body.model_dump(), handler)


class RescoreIn(BaseModel):
    application_ids: list[uuid.UUID] | None = None


@router.post("/rescore")
def rescore(body: RescoreIn, request: Request, db: Session = Depends(get_db)):
    """Re-evaluate jobs awaiting your decision with the current profile, weights and matcher."""
    def handler():
        result = matching.rescore(db, app_ids=body.application_ids)
        return 200, result

    return run_idempotent(db, request, "POST /jobs/rescore", body.model_dump(), handler)


@router.post("/{job_id}/recheck")
def recheck(job_id: uuid.UUID, db: Session = Depends(get_db)):
    job = db.get(m.Job, job_id)
    if job is None:
        raise NotFound("Job")
    status = runs.recheck_availability(db, job)
    app = current_applications(db, [job.id]).get(job.id)
    if status == "closed" and app and State(app.state) not in INACTIVE and app.state != State.SUBMITTED:
        transitions.apply(db, app.id, State.EXPIRED, Actor.ORCHESTRATOR, "listing closed on recheck")
    db.commit()
    return {"availability": status, **s.job(job, latest_evaluations(db, [job.id]).get(job.id),
                                             current_applications(db, [job.id]).get(job.id))}


@router.get("/{job_id}")
def get_job(job_id: uuid.UUID, db: Session = Depends(get_db)):
    j = db.get(m.Job, job_id)
    if j is None:
        raise NotFound("Job")
    return s.job(j, latest_evaluations(db, [j.id]).get(j.id), current_applications(db, [j.id]).get(j.id),
                 detail=True)


class DecisionIn(BaseModel):
    decision: Literal["approve", "reject", "later"]
    reason: str | None = Field(default=None, max_length=500)


@router.post("/{job_id}/decision")
def decide(job_id: uuid.UUID, body: DecisionIn, request: Request, db: Session = Depends(get_db)):
    if body.decision == "approve":
        # Recheck the listing before any preparation work starts.
        job = db.get(m.Job, job_id)
        if job is not None and job.source.access_mode in ("api", "feed"):
            if runs.recheck_availability(db, job) == "closed":
                app = current_applications(db, [job.id]).get(job.id)
                if app and State(app.state) not in INACTIVE:
                    transitions.apply(db, app.id, State.EXPIRED, Actor.ORCHESTRATOR, "listing closed on recheck")
                db.commit()
                raise DomainError("listing_closed", "The listing is no longer open; it was marked expired")
            db.commit()

    def handler():
        job = db.get(m.Job, job_id)
        if job is None:
            raise NotFound("Job")
        app = current_applications(db, [job.id]).get(job.id)
        if app is None or State(app.state) in INACTIVE:
            raise DomainError("no_active_application", "This job has no active pipeline item",
                              {"state": app.state if app else None})
        key = request.headers.get("idempotency-key")
        if body.decision == "approve":
            transitions.apply(db, app.id, State.APPROVED_FOR_PREPARATION, Actor.USER, body.reason, key)
        elif body.decision == "reject":
            transitions.apply(db, app.id, State.REJECTED, Actor.USER, body.reason, key)
        else:
            if app.state != State.CLASSIFIED:
                raise DomainError("invalid_state", "Only classified jobs can be kept for later")
            app.last_action = "kept for later" + (f": {body.reason}" if body.reason else "")
        app.decision = body.decision
        db.flush()
        return 200, s.job(job, latest_evaluations(db, [job.id]).get(job.id), app)

    return run_idempotent(db, request, f"POST /jobs/{job_id}/decision", body.model_dump(), handler)
