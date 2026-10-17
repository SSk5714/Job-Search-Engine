"""Editable settings with defaults and validation. Stored in app_settings."""

import hashlib
import json

from pydantic import BaseModel, Field, model_validator
from sqlalchemy.orm import Session

from jobpilot.db import models as m
from jobpilot.domain.scoring import DEFAULT_WEIGHTS, THRESHOLDS


class ScoringSettings(BaseModel):
    weights: dict[str, int] = Field(default_factory=lambda: dict(DEFAULT_WEIGHTS))
    thresholds: dict[str, int] = Field(default_factory=lambda: dict(THRESHOLDS))

    @model_validator(mode="after")
    def check(self):
        if set(self.weights) != set(DEFAULT_WEIGHTS):
            raise ValueError(f"weights must have exactly: {', '.join(DEFAULT_WEIGHTS)}")
        if any(v < 0 for v in self.weights.values()) or sum(self.weights.values()) != 100:
            raise ValueError("weights must be non-negative and sum to 100")
        a, r = self.thresholds.get("apply"), self.thresholds.get("review")
        if a is None or r is None or not (0 <= r < a <= 100):
            raise ValueError("thresholds need 0 <= review < apply <= 100")
        return self

    def version_tag(self) -> str:
        raw = json.dumps({"w": self.weights, "t": self.thresholds}, sort_keys=True).encode()
        return hashlib.sha256(raw).hexdigest()[:8]


class AISettings(BaseModel):
    matcher: str = Field(default="auto", pattern="^(auto|claude|rules)$")  # auto = Claude when a key is set
    max_ai_jobs_per_run: int = Field(default=50, ge=0, le=500)
    daily_budget_usd: float = Field(default=1.0, ge=0, le=50)


_MODELS = {"scoring": ScoringSettings, "ai": AISettings}


def get(db: Session, key: str):
    row = db.get(m.AppSetting, key)
    model = _MODELS[key]
    return model(**row.value) if row else model()


def put(db: Session, key: str, value: BaseModel) -> None:
    row = db.get(m.AppSetting, key)
    if row is None:
        db.add(m.AppSetting(key=key, value=value.model_dump()))
    else:
        row.value = value.model_dump()
    db.flush()
