from fastapi import APIRouter, Depends
from pydantic import ValidationError
from sqlalchemy.orm import Session

from jobpilot.agents.matching.claude_matcher import PROMPT_VERSION
from jobpilot.ai.claude import DEFAULT_MODEL
from jobpilot.api.deps import current_user
from jobpilot.config import get_settings
from jobpilot.db.session import get_db
from jobpilot.domain import settings as app_settings
from jobpilot.domain.errors import DomainError
from jobpilot.orchestrator.matching import spent_today_usd

router = APIRouter(prefix="/settings", tags=["settings"], dependencies=[Depends(current_user)])


def _validated(model, body: dict):
    try:
        return model(**body)
    except ValidationError as e:
        raise DomainError("validation_error", e.errors()[0]["msg"].replace("Value error, ", ""), status_code=422)


@router.get("/scoring")
def get_scoring(db: Session = Depends(get_db)):
    sc = app_settings.get(db, "scoring")
    return {**sc.model_dump(), "version_tag": sc.version_tag()}


@router.put("/scoring")
def put_scoring(body: dict, db: Session = Depends(get_db)):
    sc = _validated(app_settings.ScoringSettings, body)
    app_settings.put(db, "scoring", sc)
    db.commit()
    return {**sc.model_dump(), "version_tag": sc.version_tag(),
            "note": "New evaluations use these settings. Use Re-score to update jobs awaiting review."}


@router.get("/ai")
def get_ai(db: Session = Depends(get_db)):
    s = get_settings()
    ai = app_settings.get(db, "ai")
    configured = bool(s.anthropic_api_key)
    active = configured and ai.matcher != "rules"
    return {
        **ai.model_dump(),
        "api_key_configured": configured,
        "model": s.claude_model or DEFAULT_MODEL,
        "prompt_version": PROMPT_VERSION,
        "active_matcher": "claude" if active else "rules",
        "spent_today_usd": round(spent_today_usd(db), 4),
    }


@router.put("/ai")
def put_ai(body: dict, db: Session = Depends(get_db)):
    ai = _validated(app_settings.AISettings, body)
    app_settings.put(db, "ai", ai)
    db.commit()
    return get_ai(db)


@router.get("/notifications")
def get_notifications(db: Session = Depends(get_db)):
    s = get_settings()
    prefs = app_settings.get(db, "notifications")
    return {**prefs.model_dump(), "email_configured": s.email_configured,
            "email_to_hint": _mask(s.notify_email_to) if s.notify_email_to else None,
            "kinds": list(app_settings.EMAIL_KINDS)}


def _mask(addr: str) -> str:
    name, _, domain = addr.partition("@")
    return f"{name[:2]}…@{domain}" if domain else "…"


@router.put("/notifications")
def put_notifications(body: dict, db: Session = Depends(get_db)):
    prefs = _validated(app_settings.NotificationSettings, body)
    app_settings.put(db, "notifications", prefs)
    db.commit()
    return get_notifications(db)


@router.post("/notifications/test-email")
def test_email(db: Session = Depends(get_db)):
    """Sends one email right now (not queued) so you can check the SMTP settings."""
    from email.message import EmailMessage

    from jobpilot.notify.delivery import PermanentError, TransientError, smtp_send

    s = get_settings()
    if not s.email_configured:
        raise DomainError("not_configured", "Set JOBPILOT_SMTP_HOST, JOBPILOT_EMAIL_FROM and "
                          "JOBPILOT_NOTIFY_EMAIL_TO on the server first")
    msg = EmailMessage()
    msg["Subject"], msg["From"], msg["To"] = "[JobPilot] Test email", s.email_from, s.notify_email_to
    msg.set_content("Email notifications from JobPilot Europe work.")
    try:
        smtp_send(msg)
    except (TransientError, PermanentError) as e:
        raise DomainError("email_failed", f"Could not send: {e}", status_code=502)
    return {"sent": True, "to": _mask(s.notify_email_to)}


@router.get("/monitor")
def get_monitor(db: Session = Depends(get_db)):
    return app_settings.get(db, "monitor").model_dump()


@router.put("/monitor")
def put_monitor(body: dict, db: Session = Depends(get_db)):
    cfg = _validated(app_settings.MonitorSettings, {**app_settings.get(db, "monitor").model_dump(), **body})
    app_settings.put(db, "monitor", cfg)
    db.commit()
    return cfg.model_dump()
