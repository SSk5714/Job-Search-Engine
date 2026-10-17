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
