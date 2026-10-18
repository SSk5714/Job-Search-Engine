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
    documents_dir: str = "./storage/documents"  # generated CV/cover-letter files (keep private, back up)

    # Application form preparation (Playwright)
    browser_headless: bool = True
    browser_timeout_s: float = 30.0
    browser_allow_private_hosts: bool = False  # only for local test portals
    follow_up_days: int = 10

    # Phase 5: scheduler, monitor, notifications
    public_base_url: str = "http://localhost:3000"  # used for links in emails
    scheduler_interval_s: int = 60
    monitor_interval_s: int = 60
    run_stall_minutes: int = 30  # a run still "running" after this is marked failed (the worker hard limit is 15)
    monitor_fallback_log: str = "./storage/monitor-fallback.jsonl"  # written when the database is unreachable
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_username: str | None = None
    smtp_password: str | None = None
    smtp_starttls: bool = True
    smtp_ssl: bool = False
    smtp_timeout_s: float = 15.0
    email_from: str | None = None
    notify_email_to: str | None = None  # your address; kept in the environment, never in the repository

    # Phase 6: production readiness
    env: str = Field(default="development", pattern="^(development|production)$")
    api_docs: bool | None = None  # /docs and /openapi.json; default: on in development, off in production
    max_request_bytes: int = 2_000_000
    login_max_failures: int = 5  # per username within the window, then wait
    login_window_minutes: int = 15
    login_global_max_failures: int = 50  # all usernames together (password spraying)
    backup_dir: str = "./storage/backups"
    backup_keep: int = 14  # newest scheduled backups kept
    backup_at: str = "03:15"  # daily, Europe/Berlin; empty to disable scheduled backups
    test_jobs: bool | None = None  # the Mock job board; default: on in development (tests), off in production
    pg_dump_path: str = "pg_dump"
    pg_restore_path: str = "pg_restore"

    @property
    def test_jobs_enabled(self) -> bool:
        return self.test_jobs if self.test_jobs is not None else self.env != "production"

    @property
    def email_configured(self) -> bool:
        return bool(self.smtp_host and self.email_from and self.notify_email_to)


@lru_cache
def get_settings() -> Settings:
    return Settings()
