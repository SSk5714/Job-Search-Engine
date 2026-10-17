"""SQLAlchemy models. One module so the full schema reads top to bottom.

Groups: identity, profile, jobs, applications, operations.
Integrity rules from the design pack live here as constraints and partial indexes.
"""

import uuid
from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

ACTIVE_STATES_SQL = "state NOT IN ('rejected', 'withdrawn', 'closed', 'expired')"


class Base(DeclarativeBase):
    pass


def pk() -> Mapped[uuid.UUID]:
    return mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)


class Timestamped:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


# ── Identity ────────────────────────────────────────────────────────────────


class User(Base, Timestamped):
    __tablename__ = "users"
    id: Mapped[uuid.UUID] = pk()
    username: Mapped[str] = mapped_column(String(80), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))


# ── Profile ─────────────────────────────────────────────────────────────────


class CandidateProfile(Base, Timestamped):
    __tablename__ = "candidate_profiles"
    id: Mapped[uuid.UUID] = pk()
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"), unique=True)
    current_version_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("profile_versions.id", use_alter=True, name="fk_profile_current_version")
    )


class ProfileVersion(Base, Timestamped):
    __tablename__ = "profile_versions"
    __table_args__ = (UniqueConstraint("profile_id", "version_no"),)
    id: Mapped[uuid.UUID] = pk()
    profile_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("candidate_profiles.id"))
    version_no: Mapped[int] = mapped_column(Integer)
    content_hash: Mapped[str] = mapped_column(String(64))
    note: Mapped[str | None] = mapped_column(String(255))
    facts: Mapped[list["ProfileFact"]] = relationship(
        back_populates="version", order_by="ProfileFact.sort_order"
    )


class ProfileFact(Base, Timestamped):
    """One verifiable claim about the candidate. Content is immutable per version;
    the `verified` flag may be toggled on the current version only."""

    __tablename__ = "profile_facts"
    __table_args__ = (Index("ix_profile_facts_version", "version_id"),)
    id: Mapped[uuid.UUID] = pk()
    version_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("profile_versions.id"))
    # education | employment | skill | project | language | eligibility | location | gap | contact | certification
    category: Mapped[str] = mapped_column(String(32))
    # Groups facts that belong together, e.g. one job ("sasken"), one degree ("msc"), one project.
    entry: Mapped[str | None] = mapped_column(String(64))
    key: Mapped[str] = mapped_column(String(80))
    value: Mapped[str] = mapped_column(Text, default="")
    # For skills: professional | project | coursework | learning | unspecified
    context: Mapped[str | None] = mapped_column(String(32))
    verified: Mapped[bool] = mapped_column(Boolean, default=False)
    source_note: Mapped[str | None] = mapped_column(String(255))
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    version: Mapped[ProfileVersion] = relationship(back_populates="facts")


# ── Jobs ────────────────────────────────────────────────────────────────────


class JobSource(Base, Timestamped):
    __tablename__ = "job_sources"
    id: Mapped[uuid.UUID] = pk()
    code: Mapped[str] = mapped_column(String(64), unique=True)
    name: Mapped[str] = mapped_column(String(120))
    access_mode: Mapped[str] = mapped_column(String(16))  # api | feed | manual | mock
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    implemented: Mapped[bool] = mapped_column(Boolean, default=False)
    rate_limit_per_min: Mapped[int] = mapped_column(Integer, default=30)
    notes: Mapped[str | None] = mapped_column(Text)
    # Set the first time a real (non-mock) run fetched jobs successfully.
    live_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class SearchConfig(Base, Timestamped):
    __tablename__ = "search_configs"
    id: Mapped[uuid.UUID] = pk()
    name: Mapped[str] = mapped_column(String(120))
    filters: Mapped[dict] = mapped_column(JSONB, default=dict)
    source_codes: Mapped[list] = mapped_column(JSONB, default=list)
    # Per-source settings, e.g. {"greenhouse": {"boards": ["acme"]}, "ba_jobsuche": {"radius_km": 50}}
    source_options: Mapped[dict] = mapped_column(JSONB, default=dict, server_default=text("'{}'::jsonb"))
    cron: Mapped[str | None] = mapped_column(String(64))
    allow_overlap: Mapped[bool] = mapped_column(Boolean, default=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)


class SearchRun(Base, Timestamped):
    __tablename__ = "search_runs"
    __table_args__ = (
        Index(
            "uq_search_runs_one_running",
            "config_id",
            unique=True,
            postgresql_where=text("status = 'running' AND allow_overlap = false"),
        ),
    )
    id: Mapped[uuid.UUID] = pk()
    config_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("search_configs.id"))
    trigger: Mapped[str] = mapped_column(String(16))  # manual | schedule
    status: Mapped[str] = mapped_column(String(16), default="running")  # running|completed|partial|failed|cancelled
    allow_overlap: Mapped[bool] = mapped_column(Boolean, default=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    summary: Mapped[dict] = mapped_column(JSONB, default=dict)


class Job(Base, Timestamped):
    __tablename__ = "jobs"
    __table_args__ = (
        UniqueConstraint("url_normalized", name="uq_jobs_url_normalized"),
        UniqueConstraint("source_id", "external_id", name="uq_jobs_source_external"),
        Index("ix_jobs_fingerprint", "fingerprint"),
    )
    id: Mapped[uuid.UUID] = pk()
    source_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("job_sources.id"))
    external_id: Mapped[str | None] = mapped_column(String(255))
    url: Mapped[str] = mapped_column(Text)
    url_normalized: Mapped[str] = mapped_column(Text)
    fingerprint: Mapped[str] = mapped_column(String(64))
    duplicate_of_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("jobs.id"))
    company: Mapped[str] = mapped_column(String(255))
    title: Mapped[str] = mapped_column(String(255))
    country: Mapped[str | None] = mapped_column(String(2))
    city: Mapped[str | None] = mapped_column(String(120))
    location_text: Mapped[str | None] = mapped_column(String(255))
    work_mode: Mapped[str | None] = mapped_column(String(16))  # onsite | hybrid | remote
    employment_type: Mapped[str | None] = mapped_column(String(32))
    seniority: Mapped[str | None] = mapped_column(String(16))
    language_reqs: Mapped[list] = mapped_column(JSONB, default=list)
    skills: Mapped[list] = mapped_column(JSONB, default=list)
    salary_min: Mapped[float | None] = mapped_column(Numeric(12, 2))
    salary_max: Mapped[float | None] = mapped_column(Numeric(12, 2))
    currency: Mapped[str | None] = mapped_column(String(3))
    published_at: Mapped[date | None] = mapped_column(Date)
    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    first_seen_run_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("search_runs.id"))
    availability: Mapped[str] = mapped_column(String(16), default="open")  # open | closed | unknown
    availability_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    description_text: Mapped[str] = mapped_column(Text, default="")
    source: Mapped[JobSource] = relationship()


class JobMatchEvaluation(Base, Timestamped):
    __tablename__ = "job_match_evaluations"
    __table_args__ = (UniqueConstraint("job_id", "profile_version_id", "model_version"),)
    id: Mapped[uuid.UUID] = pk()
    job_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("jobs.id"))
    profile_version_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("profile_versions.id"))
    model_version: Mapped[str] = mapped_column(String(128))
    matcher: Mapped[str] = mapped_column(String(16), default="rules", server_default="rules")  # rules | claude
    weights: Mapped[dict] = mapped_column(JSONB)
    breakdown: Mapped[dict] = mapped_column(JSONB)
    score: Mapped[int] = mapped_column(Integer)
    track: Mapped[str] = mapped_column(String(8))
    seniority: Mapped[str] = mapped_column(String(16))
    recommendation: Mapped[str] = mapped_column(String(16))  # apply | review | low_priority | reject
    eligibility: Mapped[dict] = mapped_column(JSONB)
    matched_skills: Mapped[list] = mapped_column(JSONB, default=list)
    missing_skills: Mapped[list] = mapped_column(JSONB, default=list)
    explanation: Mapped[str] = mapped_column(Text)
    evidence: Mapped[list] = mapped_column(JSONB, default=list)


# ── Applications ────────────────────────────────────────────────────────────


class Application(Base, Timestamped):
    """One pipeline item per job. Created at discovery in state `discovered`."""

    __tablename__ = "applications"
    __table_args__ = (
        Index(
            "uq_applications_one_active_per_job",
            "job_id",
            unique=True,
            postgresql_where=text(ACTIVE_STATES_SQL),
        ),
        Index("ix_applications_state", "state"),
    )
    id: Mapped[uuid.UUID] = pk()
    job_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("jobs.id"))
    state: Mapped[str] = mapped_column(String(32), default="discovered")
    state_version: Mapped[int] = mapped_column(Integer, default=1)
    decision: Mapped[str | None] = mapped_column(String(16))  # approve | reject | later
    last_action: Mapped[str | None] = mapped_column(String(255))
    last_action_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_follow_up: Mapped[date | None] = mapped_column(Date)
    outcome: Mapped[str | None] = mapped_column(String(64))
    # Phase 4: where the application form lives (its host is the only one the browser may visit)
    apply_url: Mapped[str | None] = mapped_column(Text)
    prepared_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    preparation: Mapped[dict] = mapped_column(JSONB, default=dict, server_default=text("'{}'::jsonb"))
    job: Mapped[Job] = relationship()


class ApplicationStateHistory(Base):
    __tablename__ = "application_state_history"
    id: Mapped[uuid.UUID] = pk()
    application_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("applications.id"), index=True)
    from_state: Mapped[str | None] = mapped_column(String(32))
    to_state: Mapped[str] = mapped_column(String(32))
    actor: Mapped[str] = mapped_column(String(32))  # user | orchestrator | system
    reason: Mapped[str | None] = mapped_column(Text)
    idempotency_key: Mapped[str | None] = mapped_column(String(128), unique=True)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Document(Base, Timestamped):
    __tablename__ = "documents"
    __table_args__ = (UniqueConstraint("application_id", "kind", "version_no"),)
    id: Mapped[uuid.UUID] = pk()
    application_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("applications.id"), index=True)
    kind: Mapped[str] = mapped_column(String(16))  # cv | cover_letter
    version_no: Mapped[int] = mapped_column(Integer)
    profile_version_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("profile_versions.id"))
    content_hash: Mapped[str] = mapped_column(String(64))
    docx_path: Mapped[str | None] = mapped_column(Text)
    pdf_path: Mapped[str | None] = mapped_column(Text)
    verification: Mapped[dict] = mapped_column(JSONB, default=dict)
    status: Mapped[str] = mapped_column(String(16), default="draft")  # draft | ready | superseded
    # Structured content (claims citing fact ids); files are rendered from this deterministically.
    content: Mapped[dict] = mapped_column(JSONB, default=dict, server_default=text("'{}'::jsonb"))
    generator: Mapped[str] = mapped_column(String(16), default="template", server_default="template")  # template|claude|user
    model_version: Mapped[str | None] = mapped_column(String(128))


class FormField(Base, Timestamped):
    __tablename__ = "form_fields"
    __table_args__ = (UniqueConstraint("application_id", "field_key"),)
    id: Mapped[uuid.UUID] = pk()
    application_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("applications.id"), index=True)
    field_key: Mapped[str] = mapped_column(String(128))
    label: Mapped[str] = mapped_column(Text)
    field_type: Mapped[str] = mapped_column(String(32))
    sensitivity: Mapped[str] = mapped_column(String(16), default="normal")  # normal | sensitive | legal
    category: Mapped[str] = mapped_column(String(32), default="unknown", server_default="unknown")
    selector: Mapped[str | None] = mapped_column(Text)
    options: Mapped[list] = mapped_column(JSONB, default=list, server_default=text("'[]'::jsonb"))
    required: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    position: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    proposed_value: Mapped[str | None] = mapped_column(Text)
    value_source: Mapped[str | None] = mapped_column(String(64))  # fact:<id> | user | none
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    needs_manual: Mapped[bool] = mapped_column(Boolean, default=True)


class Approval(Base, Timestamped):
    __tablename__ = "approvals"
    __table_args__ = (
        Index(
            "uq_approvals_one_valid",
            "application_id",
            unique=True,
            postgresql_where=text("invalidated_at IS NULL AND decision = 'approved'"),
        ),
    )
    id: Mapped[uuid.UUID] = pk()
    application_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("applications.id"), index=True)
    decision: Mapped[str] = mapped_column(String(16))  # approved | rejected
    document_hashes: Mapped[dict] = mapped_column(JSONB, default=dict)
    form_hash: Mapped[str] = mapped_column(String(64))
    approved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    invalidated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    invalidated_reason: Mapped[str | None] = mapped_column(Text)


class SubmissionAttempt(Base, Timestamped):
    __tablename__ = "submission_attempts"
    __table_args__ = (
        Index(
            "uq_submission_one_success",
            "application_id",
            unique=True,
            postgresql_where=text("status = 'succeeded'"),
        ),
    )
    id: Mapped[uuid.UUID] = pk()
    application_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("applications.id"), index=True)
    approval_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("approvals.id"))
    idempotency_key: Mapped[str] = mapped_column(String(128), unique=True)
    status: Mapped[str] = mapped_column(String(16), default="pending")  # pending|succeeded|failed|unknown
    mode: Mapped[str] = mapped_column(String(16), default="browser", server_default="browser")  # browser|manual
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    result: Mapped[str | None] = mapped_column(Text)
    evidence_path: Mapped[str | None] = mapped_column(Text)


class FollowUp(Base, Timestamped):
    __tablename__ = "follow_ups"
    id: Mapped[uuid.UUID] = pk()
    application_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("applications.id"), index=True)
    due_on: Mapped[date] = mapped_column(Date)
    note: Mapped[str | None] = mapped_column(Text)
    done: Mapped[bool] = mapped_column(Boolean, default=False)


class RecruiterInteraction(Base, Timestamped):
    __tablename__ = "recruiter_interactions"
    id: Mapped[uuid.UUID] = pk()
    application_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("applications.id"), index=True)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    channel: Mapped[str] = mapped_column(String(32))
    summary: Mapped[str] = mapped_column(Text)


# ── Operations ──────────────────────────────────────────────────────────────


class AgentRun(Base, Timestamped):
    __tablename__ = "agent_runs"
    id: Mapped[uuid.UUID] = pk()
    run_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("search_runs.id"), index=True)
    agent: Mapped[str] = mapped_column(String(32))  # discovery | matching | documents | preparation
    subject: Mapped[str | None] = mapped_column(String(128))  # e.g. source code or application id
    status: Mapped[str] = mapped_column(String(16), default="running")
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    output_summary: Mapped[dict] = mapped_column(JSONB, default=dict)


class TaskAttempt(Base, Timestamped):
    __tablename__ = "task_attempts"
    id: Mapped[uuid.UUID] = pk()
    agent_run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("agent_runs.id"), index=True)
    attempt_no: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(16))  # succeeded | failed
    error_code: Mapped[str | None] = mapped_column(String(64))
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    ai_tokens_in: Mapped[int | None] = mapped_column(Integer)
    ai_tokens_out: Mapped[int | None] = mapped_column(Integer)
    ai_cost_usd: Mapped[float | None] = mapped_column(Numeric(10, 4))


class ErrorEvent(Base):
    __tablename__ = "error_events"
    id: Mapped[uuid.UUID] = pk()
    component: Mapped[str] = mapped_column(String(64))
    severity: Mapped[str] = mapped_column(String(16))
    run_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    task_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    code: Mapped[str] = mapped_column(String(64))
    message: Mapped[str] = mapped_column(Text)
    context: Mapped[dict] = mapped_column(JSONB, default=dict)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)


class HealthCheck(Base):
    __tablename__ = "health_checks"
    id: Mapped[uuid.UUID] = pk()
    check_name: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(16))  # ok | degraded | down
    detail: Mapped[str | None] = mapped_column(Text)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)


class Notification(Base, Timestamped):
    __tablename__ = "notifications"
    __table_args__ = (
        Index(
            "uq_notifications_open_alert",
            "alert_key",
            unique=True,
            postgresql_where=text("alert_key IS NOT NULL AND resolved_at IS NULL"),
        ),
    )
    id: Mapped[uuid.UUID] = pk()
    kind: Mapped[str] = mapped_column(String(32))  # alert | high_fit | ready_for_review | follow_up | submitted
    severity: Mapped[str] = mapped_column(String(16), default="info")
    title: Mapped[str] = mapped_column(String(255))
    body: Mapped[str] = mapped_column(Text, default="")
    channel: Mapped[str] = mapped_column(String(16), default="in_app")
    delivery_status: Mapped[str] = mapped_column(String(16), default="pending")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    alert_key: Mapped[str | None] = mapped_column(String(128))
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AppSetting(Base):
    """Small JSON settings (scoring weights, AI limits) editable from the UI."""

    __tablename__ = "app_settings"
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[dict] = mapped_column(JSONB)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(),
                                                 onupdate=func.now())


class IdempotencyKey(Base):
    __tablename__ = "idempotency_keys"
    key: Mapped[str] = mapped_column(String(128), primary_key=True)
    endpoint: Mapped[str] = mapped_column(String(128))
    request_hash: Mapped[str] = mapped_column(String(64))
    status_code: Mapped[int] = mapped_column(Integer)
    response: Mapped[dict] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
