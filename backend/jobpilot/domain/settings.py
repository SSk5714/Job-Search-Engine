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


EMAIL_KINDS = ("alert", "high_fit", "ready_for_review", "submitted", "follow_up")


class NotificationSettings(BaseModel):
    """What reaches you, and where. In-app notifications are always on."""

    email_enabled: bool = False
    email_kinds: list[str] = Field(default_factory=lambda: ["alert", "high_fit", "ready_for_review",
                                                            "submitted", "follow_up"])
    email_alert_min_severity: str = Field(default="critical", pattern="^(info|warning|critical)$")
    high_fit_min_score: int = Field(default=60, ge=0, le=100)
    follow_up_lead_days: int = Field(default=2, ge=0, le=14)

    @model_validator(mode="after")
    def check(self):
        bad = [k for k in self.email_kinds if k not in EMAIL_KINDS]
        if bad:
            raise ValueError(f"Unknown notification kinds: {', '.join(bad)}")
        return self


class MonitorSettings(BaseModel):
    """Thresholds for the independent monitor. Hours unless noted."""

    stuck_hours: dict[str, int] = Field(default_factory=lambda: {
        "approved_for_preparation": 72, "documents_ready": 72, "form_prepared": 24,
        "awaiting_user_review": 120, "needs_manual_input": 48, "failed": 24})
    run_stall_alert_minutes: int = Field(default=20, ge=5, le=240)
    error_spike_per_hour: int = Field(default=20, ge=3, le=1000)
    repeated_failures: int = Field(default=3, ge=2, le=20)
    claude_failures_per_hour: int = Field(default=3, ge=1, le=100)
    heartbeat_missed_factor: int = Field(default=3, ge=2, le=20)  # stale after N intervals

    @model_validator(mode="after")
    def check(self):
        if any(v < 1 or v > 24 * 60 for v in self.stuck_hours.values()):
            raise ValueError("stuck thresholds must be between 1 hour and 60 days")
        return self


SEVERITY_RANK = {"info": 0, "warning": 1, "critical": 2}

_MODELS = {"scoring": ScoringSettings, "ai": AISettings, "notifications": NotificationSettings,
           "monitor": MonitorSettings}


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
