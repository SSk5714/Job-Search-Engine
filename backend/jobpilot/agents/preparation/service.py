"""Preparation and submission, run by the orchestrator.

prepare():  documents_ready → (browser) form_prepared → awaiting_user_review
            or a manual handoff when the site must not or cannot be automated.
submit():   only from awaiting_user_review with a fresh approval; one attempt per
            idempotency key; outcome verified; unknown outcomes stop the workflow.
"""

import re
import uuid
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from urllib.parse import urlsplit

from sqlalchemy import select
from sqlalchemy.orm import Session

from jobpilot.agents.discovery.adapters import MANUAL_DOMAINS
from jobpilot.agents.preparation import browser
from jobpilot.agents.preparation.fields import FieldSpec, classify, propose
from jobpilot.config import get_settings
from jobpilot.db import models as m
from jobpilot.notify import Finding, raise_alert, resolve_alert
from jobpilot.documents import factbook
from jobpilot.documents.service import storage_root
from jobpilot.domain import approvals, transitions
from jobpilot.domain.errors import DomainError
from jobpilot.domain.profile import current_version
from jobpilot.domain.states import Actor, State
from jobpilot.orchestrator.runs import recheck_availability


def _evidence_path(app_id, label: str) -> Path:
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S")
    return storage_root() / "evidence" / str(app_id) / f"{label}-{stamp}.png"


def _rel(path: Path | None) -> str | None:
    return str(path.relative_to(storage_root())) if path else None


def _manual_reason(url: str) -> str | None:
    host = (urlsplit(url).hostname or "").lower()
    for domain, code in MANUAL_DOMAINS.items():
        if host == domain or host.endswith("." + domain):
            return f"{code.title()} does not permit automated applications; apply there yourself"
    return None


def _doc_files(db: Session, app: m.Application) -> dict[str, Path]:
    docs = approvals.current_documents(db, app.id)
    return {f"document:{k}": storage_root() / d.pdf_path for k, d in docs.items() if d.status == "ready"}


def _letter_text(db: Session, app: m.Application) -> str | None:
    doc = approvals.current_documents(db, app.id).get("cover_letter")
    if not doc or doc.status != "ready":
        return None
    return "\n\n".join(" ".join(s["text"] for s in p["sentences"]) for p in doc.content.get("paragraphs", []))


def _set_manual(db: Session, app: m.Application, url: str, reason: str, extra: dict | None = None) -> None:
    app.apply_url = url
    app.preparation = {"mode": "manual", "reason": reason, "host": urlsplit(url).hostname, **(extra or {})}
    app.prepared_at = datetime.now(UTC)
    for old in db.scalars(select(m.FormField).where(m.FormField.application_id == app.id)).all():
        db.delete(old)
    db.flush()
    transitions.apply(db, app.id, State.AWAITING_USER_REVIEW, Actor.ORCHESTRATOR, f"manual application: {reason}")


def _browser_failed(db: Session, app: m.Application, url: str, exc: Exception):
    """Record a browser failure in its own transaction (the caller's work is rolled back) and stop."""
    from jobpilot.db.session import SessionLocal

    with SessionLocal() as side:
        side.add(m.ErrorEvent(component="browser", severity="warning", code=type(exc).__name__[:64],
                              message=str(exc)[:1000], context={"application_id": str(app.id), "url": url}))
        side.commit()
    text = str(exc)
    if "ERR_NAME_NOT_RESOLVED" in text:
        why = "That web address does not exist (the domain name could not be found). Check the link"
    elif "ERR_CONNECTION_REFUSED" in text or "ERR_CONNECTION_RESET" in text:
        why = "The site refused the connection. It may be down; try again later"
    elif "ERR_INTERNET_DISCONNECTED" in text or "ERR_NETWORK" in text:
        why = "There is no internet connection from the app. Check your network"
    elif "Timeout" in type(exc).__name__ or "Timeout" in text:
        why = "The page took too long to load. Try again"
    elif "ERR_CERT" in text or "SSL" in text:
        why = "The site's security certificate is not valid"
    else:
        why = f"The browser could not load or read the page ({type(exc).__name__})"
    raise DomainError("browser_failed", f"{why}. Nothing was changed; you can also apply on the site yourself.",
                      {"detail": text[:300]}, status_code=502)


def prepare(db: Session, app_id: uuid.UUID, apply_url: str | None = None) -> m.Application:
    app = db.scalar(select(m.Application).where(m.Application.id == app_id).with_for_update())
    if app is None:
        raise DomainError("not_found", "Application not found", status_code=404)
    if app.state != State.DOCUMENTS_READY:
        raise DomainError("invalid_state", "Generate and verify the documents first", {"state": app.state})
    url = (apply_url or app.apply_url or app.job.url).strip()
    if not re.match(r"^https?://", url):
        raise DomainError("validation_error", "The application link must start with http:// or https://",
                          status_code=422)
    host = (urlsplit(url).hostname or "").lower()
    if host.endswith((".example", ".invalid", ".test")) or host in ("example.com", "example.org"):
        raise DomainError("test_job", "This is a test job from the Mock job board: its address is invented and "
                          "cannot be opened. Turn off the Mock job board in Job Discovery and search a real "
                          "source (e.g. Bundesagentur für Arbeit) to apply for real.", status_code=422)

    if app.job.source.access_mode in ("api", "feed") and recheck_availability(db, app.job) == "closed":
        transitions.apply(db, app.id, State.EXPIRED, Actor.ORCHESTRATOR, "listing closed on recheck")
        return app

    reason = _manual_reason(url)
    if reason or app.job.source.access_mode == "manual" and not apply_url:
        _set_manual(db, app, url, reason or "This job came from a manual source; open the listing and apply there")
        return app

    book = factbook.build(current_version(db))
    docs = approvals.current_documents(db, app.id)
    ready = {k for k, d in docs.items() if d.status == "ready"}
    shot = _evidence_path(app.id, "prepared")

    # Pass 1: read the form. Pass 2 (same call) fills only safe, high-confidence values and screenshots.
    try:
        first = browser.inspect_form(url, shot)
    except browser.BrowserBlocked as e:
        raise DomainError("blocked", str(e), status_code=422)
    except Exception as e:  # browser crash or timeout: logged for the monitor, nothing changed
        _browser_failed(db, app, url, e)
    if first.human_needed or not first.fields:
        why = {"captcha": "The page shows a CAPTCHA", "login": "The page requires signing in"}.get(
            first.human_needed or "", "No application form was found on that page" +
            (" (it tried to leave the site and was stopped)" if first.blocked else ""))
        _set_manual(db, app, url, why + "; apply there yourself",
                    {"screenshot": _rel(first.screenshot), "blocked_requests": first.blocked})
        return app

    letter = _letter_text(db, app)
    rows, fills = [], {}
    for spec in first.fields:
        category, sensitivity = classify(spec)
        prop = propose(spec, category, sensitivity, book, letter, ready)
        rows.append((spec, prop))
        if prop.value is not None and not prop.needs_manual:
            fills[spec.key] = (spec.kind, prop.value)
    files = _doc_files(db, app)
    try:
        snap = browser.inspect_form(url, shot, fill=fills, files=files)
    except browser.BrowserBlocked as e:
        raise DomainError("blocked", str(e), status_code=422)
    except Exception as e:
        _browser_failed(db, app, url, e)

    for old in db.scalars(select(m.FormField).where(m.FormField.application_id == app.id)).all():
        db.delete(old)
    db.flush()
    for spec, prop in rows:
        db.add(m.FormField(
            application_id=app.id, field_key=spec.key[:128], label=spec.label[:1000] or spec.key,
            field_type=spec.kind, sensitivity=prop.sensitivity, category=prop.category, selector=spec.selector,
            options=spec.options, required=spec.required, position=spec.position,
            proposed_value=prop.value, value_source=prop.source, confidence=prop.confidence,
            needs_manual=prop.needs_manual,
        ))
    approvals.invalidate(db, app.id, "form prepared again")
    now = datetime.now(UTC)
    app.apply_url = url
    app.prepared_at = now
    app.job.availability_checked_at = now  # the live application form is current evidence the job is open
    protected = [s.key for s, p in rows if p.sensitivity != "normal"]
    app.preparation = {
        "mode": "browser", "host": urlsplit(url).hostname, "screenshot": _rel(snap.screenshot),
        "blocked_requests": snap.blocked, "fields": len(rows), "auto_filled": len(fills),
        "needs_you": sum(1 for _, p in rows if p.needs_manual), "protected": protected,
        "hints": {s.key: p.hint for s, p in rows if p.hint},
    }
    app.last_action = f"form prepared: {len(fills)} filled, {app.preparation['needs_you']} need you"
    db.flush()
    transitions.apply(db, app.id, State.FORM_PREPARED, Actor.ORCHESTRATOR, "form prepared (not submitted)")
    transitions.apply(db, app.id, State.AWAITING_USER_REVIEW, Actor.ORCHESTRATOR, "ready for your review")
    return app


# ── Submission ──────────────────────────────────────────────────────────────


def _active_attempt(db: Session, app_id) -> m.SubmissionAttempt | None:
    return db.scalar(select(m.SubmissionAttempt).where(
        m.SubmissionAttempt.application_id == app_id,
        m.SubmissionAttempt.status.in_(["pending", "unknown", "succeeded"])))


def _mark_submitted(db: Session, app: m.Application, attempt: m.SubmissionAttempt) -> None:
    due = date.today() + timedelta(days=get_settings().follow_up_days)
    app.next_follow_up = due
    transitions.apply(db, app.id, State.SUBMITTED, Actor.ORCHESTRATOR,
                      f"submission confirmed ({attempt.mode}{', ref ' + attempt.result if attempt.result else ''})")
    db.add(m.FollowUp(application_id=app.id, due_on=due, note="Check for a reply"))


def start_attempt(db: Session, app_id: uuid.UUID, key: str, mode: str) -> tuple[m.Application, m.SubmissionAttempt,
                                                                                bool]:
    """Create the attempt row BEFORE any browser action. Returns (app, attempt, is_new)."""
    existing = db.scalar(select(m.SubmissionAttempt).where(m.SubmissionAttempt.idempotency_key == key))
    if existing is not None:
        return db.get(m.Application, existing.application_id), existing, False
    app = db.scalar(select(m.Application).where(m.Application.id == app_id).with_for_update())
    if app is None:
        raise DomainError("not_found", "Application not found", status_code=404)
    if app.state != State.AWAITING_USER_REVIEW:
        raise DomainError("invalid_state", "Only applications awaiting your review can be submitted",
                          {"state": app.state})
    mode_now = (app.preparation or {}).get("mode", "browser")
    if mode != mode_now:
        raise DomainError("wrong_mode", "Submit this one yourself on the site, then confirm it here"
                          if mode_now == "manual" else "This application is submitted from JobPilot")
    approval = approvals.require_fresh_approval(db, app)
    active = _active_attempt(db, app.id)
    if active is not None:
        code = {"unknown": "submission_outcome_unknown", "pending": "submission_in_progress",
                "succeeded": "already_submitted"}[active.status]
        raise DomainError(code, {"unknown": "A previous attempt ended without a clear result. Check the portal "
                                            "or your email, then record what happened.",
                                 "pending": "A submission is already in progress",
                                 "succeeded": "This application was already submitted"}[active.status])
    attempt = m.SubmissionAttempt(application_id=app.id, approval_id=approval.id, idempotency_key=key,
                                  status="pending", mode=mode)
    db.add(attempt)
    db.flush()
    return app, attempt, True


def run_browser_submission(db: Session, app: m.Application, attempt: m.SubmissionAttempt) -> m.SubmissionAttempt:
    fields = db.scalars(select(m.FormField).where(m.FormField.application_id == app.id)
                        .order_by(m.FormField.position)).all()
    plan = []
    for f in fields:
        if f.proposed_value is None or f.value_source == "skipped":
            continue
        spec = FieldSpec(key=f.field_key, label=f.label, kind=f.field_type, selector=f.selector or "",
                         required=f.required, options=f.options or [], position=f.position)
        plan.append((spec, f.proposed_value))
    result = browser.submit_plan(app.apply_url, plan, _doc_files(db, app), _evidence_path(app.id, "submitted"))
    attempt.status = result.status
    attempt.result = result.reference or result.detail[:500]
    attempt.evidence_path = _rel(result.screenshot)
    attempt.finished_at = datetime.now(UTC)
    if result.status == "succeeded":
        attempt.result = result.reference or "confirmed"
        _mark_submitted(db, app, attempt)
    elif result.status == "unknown":
        transitions.apply(db, app.id, State.NEEDS_MANUAL_INPUT, Actor.ORCHESTRATOR,
                          "submission outcome unknown — check before retrying")
        db.add(m.ErrorEvent(component="submission", severity="critical", task_id=attempt.id,
                            code="outcome_unknown", message=result.detail[:1000],
                            context={"application_id": str(app.id), "url": result.final_url}))
        raise_alert(db, Finding(
            key=f"submission-unknown:{app.id}", severity="critical", component="submission", task_id=attempt.id,
            title=f"Check your application to {app.job.company}", summary=result.detail,
            likely_cause="The portal did not show a clear confirmation or error after submitting",
            remediation="Check your email or the employer's portal, then tell JobPilot whether it arrived "
                        "(Application Review). It will not retry on its own.",
            workflow_paused=True, link=f"/review?id={app.id}", context={"url": result.final_url}))
    else:
        app.last_action = f"submission not sent: {result.detail[:200]}"
    db.flush()
    return attempt


def confirm_outcome(db: Session, app_id: uuid.UUID, submitted: bool, note: str | None) -> m.Application:
    """After an unknown outcome, you record what really happened."""
    app = db.scalar(select(m.Application).where(m.Application.id == app_id).with_for_update())
    attempt = db.scalar(select(m.SubmissionAttempt).where(m.SubmissionAttempt.application_id == app_id,
                                                          m.SubmissionAttempt.status == "unknown"))
    if app is None or attempt is None:
        raise DomainError("nothing_to_confirm", "There is no submission with an unknown outcome")
    resolve_alert(db, f"submission-unknown:{app_id}", by="user")
    attempt.status = "succeeded" if submitted else "failed"
    attempt.result = ("confirmed by you" if submitted else "not received (confirmed by you)") + \
        (f": {note[:200]}" if note else "")
    attempt.finished_at = datetime.now(UTC)
    for n in db.scalars(select(m.Notification).where(m.Notification.alert_key == f"submission-unknown:{app.id}",
                                                     m.Notification.resolved_at.is_(None))).all():
        n.resolved_at = datetime.now(UTC)
    if app.state == State.NEEDS_MANUAL_INPUT:
        transitions.apply(db, app.id, State.AWAITING_USER_REVIEW, Actor.USER, "submission outcome checked")
    db.flush()
    if submitted:
        _mark_submitted(db, app, attempt)
    return app


def mark_manual_submission(db: Session, app_id: uuid.UUID, key: str, note: str | None) -> m.Application:
    app, attempt, new = start_attempt(db, app_id, key, mode="manual")
    if new:
        attempt.status = "succeeded"
        attempt.result = f"submitted by you{': ' + note[:200] if note else ''}"
        attempt.finished_at = datetime.now(UTC)
        db.flush()
        _mark_submitted(db, app, attempt)
    return app
