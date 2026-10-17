from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """All runtime configuration comes from environment variables (see .env.example)."""

    model_config = SettingsConfigDict(env_prefix="JOBPILOT_", env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://postgres@localhost:5432/jobpilot"
    redis_url: str | None = None  # when unset, search runs execute in-process
    secret_key: str = Field(default="change-me-in-production", min_length=16)
    session_max_age_s: int = 60 * 60 * 12
    cookie_secure: bool = False  # set True behind HTTPS
    admin_username: str | None = None  # bootstrap user, created once if no user exists
    admin_password: str | None = None
    cors_origins: list[str] = ["http://localhost:3000"]

    # AI (used from Phase 2; the key never leaves the server)
    anthropic_api_key: str | None = None
    claude_model: str | None = None  # default: claude-haiku-5-5
    ai_timeout_s: float = 60.0
    ai_prices: dict[str, list[float]] = {}  # override: {"model-id": [usd_per_mtok_in, usd_per_mtok_out]}

    # Outbound HTTP to job sources
    http_user_agent: str = "JobPilotEurope/0.2 (personal job search; contact via repository)"
    http_timeout_s: float = 30.0

    # Workflow
    availability_recheck_hours: int = 24


@lru_cache
def get_settings() -> Settings:
    return Settings()
