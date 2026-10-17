"""Approval binding: an approval is valid only for the exact documents and form
values it was given. Any change invalidates it."""

import hashlib
import json
import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from jobpilot.db import models as m
from jobpilot.domain.errors import DomainError
from jobpilot.domain.states import State


def _sha(data: object) -> str:
    return hashlib.sha256(json.dumps(data, sort_keys=True, default=str).encode()).hexdigest()


def current_documents(db: Session, application_id: uuid.UUID) -> dict[str, m.Document]:
    """Latest ready version per kind."""
    docs = db.scalars(
        select(m.Document)
        .where(m.Document.application_id == application_id, m.Document.status == "ready")
        .order_by(m.Document.kind, m.Document.version_no.desc())
    ).all()
    latest: dict[str, m.Document] = {}
    for d in docs:
        latest.setdefault(d.kind, d)
    return latest


def document_hashes(db: Session, application_id: uuid.UUID) -> dict[str, str]:
    return {kind: d.content_hash for kind, d in current_documents(db, application_id).items()}


def form_hash(db: Session, application_id: uuid.UUID) -> str:
    fields = db.scalars(select(m.FormField).where(m.FormField.application_id == application_id)).all()
    return _sha(sorted((f.field_key, f.proposed_value) for f in fields))


def valid_approval(db: Session, application_id: uuid.UUID) -> m.Approval | None:
    return db.scalar(
        select(m.Approval).where(
            m.Approval.application_id == application_id,
            m.Approval.decision == "approved",
            m.Approval.invalidated_at.is_(None),
        )
    )


def unresolved_fields(db: Session, application_id: uuid.UUID) -> list[m.FormField]:
    return list(
        db.scalars(
            select(m.FormField).where(
                m.FormField.application_id == application_id,
                m.FormField.needs_manual.is_(True),
                m.FormField.proposed_value.is_(None),
            )
        ).all()
    )


def approve(db: Session, app: m.Application) -> m.Approval:
    if app.state != State.AWAITING_USER_REVIEW:
        raise DomainError("invalid_state", "Only applications awaiting your review can be approved",
                          {"state": app.state})
    pending = unresolved_fields(db, app.id)
    if pending:
        raise DomainError("unresolved_fields", "Some form fields still need your input",
                          {"fields": [f.field_key for f in pending]})
    docs = document_hashes(db, app.id)
    if not {"cv", "cover_letter"} <= docs.keys():
        raise DomainError("documents_missing", "A ready CV and cover letter are required before approval")
    existing = valid_approval(db, app.id)
    if existing:
        invalidate(db, app.id, "superseded by a new approval")
    approval = m.Approval(
        application_id=app.id, decision="approved", document_hashes=docs, form_hash=form_hash(db, app.id)
    )
    db.add(approval)
    db.flush()
    return approval


def invalidate(db: Session, application_id: uuid.UUID, reason: str) -> bool:
    approval = valid_approval(db, application_id)
    if approval is None:
        return False
    approval.invalidated_at = datetime.now(UTC)
    approval.invalidated_reason = reason
    db.flush()
    return True


def require_fresh_approval(db: Session, app: m.Application) -> m.Approval:
    """Raise unless a valid approval exists and still matches the current content."""
    approval = valid_approval(db, app.id)
    if approval is None:
        raise DomainError("approval_required", "This application has no valid approval")
    if approval.document_hashes != document_hashes(db, app.id) or approval.form_hash != form_hash(db, app.id):
        invalidate(db, app.id, "content changed after approval")
        raise DomainError("approval_stale", "Documents or form values changed after approval; review again")
    return approval
