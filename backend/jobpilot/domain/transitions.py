"""The ONLY code path that changes an application's state.

`apply()` locks the row, checks the transition table and guard, writes history and
bumps `state_version` — all inside the caller's transaction. Callers commit.
"""

import uuid
from collections.abc import Callable
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from jobpilot.db import models as m
from jobpilot.domain import approvals
from jobpilot.domain.errors import DomainError, NotFound
from jobpilot.domain.states import INTERRUPTS, Actor, State, find_rule

Guard = Callable[[Session, m.Application], str | None]  # returns an error message or None


def _has_evaluation(db: Session, app: m.Application) -> str | None:
    found = db.scalar(select(m.JobMatchEvaluation.id).where(m.JobMatchEvaluation.job_id == app.job_id).limit(1))
    return None if found else "The job has not been evaluated yet"


def _job_available(db: Session, app: m.Application) -> str | None:
    job = db.get(m.Job, app.job_id)
    if job is None or job.availability != "open":
        return "The listing is no longer open"
    if job.duplicate_of_id is not None:
        return "This listing duplicates another job; act on the original instead"
    return None


def _documents_verified(db: Session, app: m.Application) -> str | None:
    docs = approvals.current_documents(db, app.id)
    for kind in ("cv", "cover_letter"):
        doc = docs.get(kind)
        if doc is None or doc.status != "ready":
            return f"No verified {kind.replace('_', ' ')}"
        if doc.verification.get("unsupported_claims"):
            return f"The {kind.replace('_', ' ')} has unsupported claims"
    return None


def _form_fields_resolved(db: Session, app: m.Application) -> str | None:
    job = db.get(m.Job, app.job_id)
    checked = job.availability_checked_at if job else None
    if checked is None or (datetime.now(UTC) - checked).total_seconds() > 24 * 3600:
        return "Availability must be rechecked within 24 hours before preparing the form"
    fields = db.scalars(select(m.FormField).where(m.FormField.application_id == app.id)).all()
    if not fields:
        return "No form fields were prepared"
    for f in fields:
        if f.proposed_value is None and not f.needs_manual:
            return f"Field '{f.field_key}' has no value and is not flagged for manual input"
    return None


def _manual_apply_source(db: Session, app: m.Application) -> str | None:
    job = db.get(m.Job, app.job_id)
    return None if job and job.source.access_mode == "manual" else "Only manual-apply sources skip form preparation"


def _submission_succeeded(db: Session, app: m.Application) -> str | None:
    approvals.require_fresh_approval(db, app)
    ok = db.scalar(
        select(m.SubmissionAttempt.id).where(
            m.SubmissionAttempt.application_id == app.id, m.SubmissionAttempt.status == "succeeded"
        )
    )
    return None if ok else "No confirmed submission"


def _follow_up_set(db: Session, app: m.Application) -> str | None:
    return None if app.next_follow_up else "Set a follow-up date first"


def _outcome_set(db: Session, app: m.Application) -> str | None:
    return None if app.outcome else "Record the outcome first"


GUARDS: dict[str, Guard] = {
    "has_evaluation": _has_evaluation,
    "job_available": _job_available,
    "documents_verified": _documents_verified,
    "form_fields_resolved": _form_fields_resolved,
    "manual_apply_source": _manual_apply_source,
    "submission_succeeded": _submission_succeeded,
    "follow_up_set": _follow_up_set,
    "outcome_set": _outcome_set,
}


def _state_before_interrupt(db: Session, app: m.Application) -> State | None:
    row = db.scalar(
        select(m.ApplicationStateHistory)
        .where(
            m.ApplicationStateHistory.application_id == app.id,
            m.ApplicationStateHistory.to_state == app.state,
        )
        .order_by(m.ApplicationStateHistory.at.desc())
        .limit(1)
    )
    return State(row.from_state) if row and row.from_state else None


def allowed_targets(db: Session, app: m.Application, actor: Actor) -> list[State]:
    """For the UI: which moves this actor can request now (guards not evaluated)."""
    from jobpilot.domain.states import rules_from

    current = State(app.state)
    targets = [r.to for r in rules_from(current) if actor in r.actors]
    if current in INTERRUPTS and actor == Actor.USER:
        prev = _state_before_interrupt(db, app)
        if prev:
            targets.insert(0, prev)
    return targets


def apply(
    db: Session,
    application_id: uuid.UUID,
    to_state: State | str,
    actor: Actor,
    reason: str | None = None,
    idempotency_key: str | None = None,
    expected_version: int | None = None,
) -> m.Application:
    to_state = State(to_state)

    if idempotency_key:
        done = db.scalar(
            select(m.ApplicationStateHistory).where(m.ApplicationStateHistory.idempotency_key == idempotency_key)
        )
        if done is not None:
            app = db.get(m.Application, done.application_id)
            assert app is not None
            return app  # already applied; safe replay

    app = db.scalar(select(m.Application).where(m.Application.id == application_id).with_for_update())
    if app is None:
        raise NotFound("Application")
    if expected_version is not None and app.state_version != expected_version:
        raise DomainError("stale_version", "The application changed since you loaded it; reload and retry",
                          {"current_version": app.state_version})

    current = State(app.state)
    if current in INTERRUPTS and actor == Actor.USER and to_state != State.WITHDRAWN:
        prev = _state_before_interrupt(db, app)
        if prev != to_state:
            raise DomainError("invalid_transition", f"From {current} you can only return to {prev}",
                              {"from": current, "to": to_state, "allowed": [prev] if prev else []})
    else:
        rule = find_rule(current, to_state)
        if rule is None:
            raise DomainError("invalid_transition", f"Cannot move from {current} to {to_state}",
                              {"from": current, "to": to_state})
        if actor not in rule.actors:
            raise DomainError("forbidden_actor", f"{actor} may not move {current} to {to_state}",
                              {"from": current, "to": to_state}, status_code=403)
        if rule.guard:
            problem = GUARDS[rule.guard](db, app)
            if problem:
                raise DomainError("guard_failed", problem, {"guard": rule.guard, "from": current, "to": to_state})

    now = datetime.now(UTC)
    app.state = to_state.value
    app.state_version += 1
    app.last_action = f"{current.value} → {to_state.value}" + (f": {reason}" if reason else "")
    app.last_action_at = now
    if to_state == State.SUBMITTED:
        app.submitted_at = now
    db.add(
        m.ApplicationStateHistory(
            application_id=app.id,
            from_state=current.value,
            to_state=to_state.value,
            actor=actor.value,
            reason=reason,
            idempotency_key=idempotency_key,
        )
    )
    db.flush()
    return app


def create_application(db: Session, job_id: uuid.UUID, actor: Actor = Actor.ORCHESTRATOR) -> m.Application:
    """New pipeline item in `discovered`, with its first history row."""
    app = m.Application(job_id=job_id, state=State.DISCOVERED.value, state_version=1,
                        last_action="discovered", last_action_at=datetime.now(UTC))
    db.add(app)
    db.flush()
    db.add(m.ApplicationStateHistory(application_id=app.id, from_state=None,
                                     to_state=State.DISCOVERED.value, actor=actor.value))
    db.flush()
    return app
