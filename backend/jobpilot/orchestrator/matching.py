"""Matching step, run by the orchestrator. Chooses Claude or rules per job,
enforces per-run and daily AI budgets, records usage and cost per attempt, and
falls back to rules visibly (never silently) when Claude is unavailable."""

import logging
import time
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from jobpilot.agents.matching import claude_matcher
from jobpilot.ai.provider import AIError, AIProvider, get_provider
from jobpilot.db import models as m
from jobpilot.domain import settings as app_settings
from jobpilot.domain import transitions
from jobpilot.domain.profile import current_version, profile_view
from jobpilot.domain.scoring import ProfileView, rules_extract, score_extraction
from jobpilot.domain.states import Actor, State

log = logging.getLogger("jobpilot.matching")


@dataclass
class MatchContext:
    version: m.ProfileVersion
    view: ProfileView
    scoring: app_settings.ScoringSettings
    ai: app_settings.AISettings
    provider: AIProvider | None
    preferred_countries: list[str] | None
    agent_run: m.AgentRun
    ai_calls_left: int
    budget_left_usd: float
    stats: dict = field(default_factory=lambda: {"claude": 0, "rules": 0, "fallbacks": 0, "cost_usd": 0.0})
    notes: set[str] = field(default_factory=set)


def spent_today_usd(db: Session) -> float:
    start = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    total = db.scalar(select(func.coalesce(func.sum(m.TaskAttempt.ai_cost_usd), 0))
                      .where(m.TaskAttempt.created_at >= start))
    return float(total or 0)


def make_context(db: Session, run_id: uuid.UUID | None, preferred_countries: list[str] | None,
                 provider: AIProvider | None = None, subject: str = "classification") -> MatchContext:
    ai = app_settings.get(db, "ai")
    if provider is None and ai.matcher != "rules":
        provider = get_provider()
    if ai.matcher == "rules":
        provider = None
    version = current_version(db)
    agent_run = m.AgentRun(run_id=run_id, agent="matching", subject=subject)
    db.add(agent_run)
    db.flush()
    ctx = MatchContext(
        version=version, view=profile_view(version), scoring=app_settings.get(db, "scoring"), ai=ai,
        provider=provider, preferred_countries=preferred_countries, agent_run=agent_run,
        ai_calls_left=ai.max_ai_jobs_per_run, budget_left_usd=ai.daily_budget_usd - spent_today_usd(db),
    )
    if ai.matcher == "claude" and provider is None:
        ctx.notes.add("Claude matcher selected but JOBPILOT_ANTHROPIC_API_KEY is not set; using rules")
    return ctx


def _job_dict(job: m.Job) -> dict:
    return {"title": job.title, "company": job.company, "description_text": job.description_text,
            "skills": job.skills, "seniority": job.seniority, "language_reqs": job.language_reqs,
            "country": job.country, "work_mode": job.work_mode, "location_text": job.location_text,
            "city": job.city}


def evaluate(db: Session, job: m.Job, ctx: MatchContext) -> m.JobMatchEvaluation:
    jd = _job_dict(job)
    ex, report, usage, error = None, {}, None, None
    started = time.monotonic()
    use_ai = ctx.provider is not None and ctx.ai_calls_left > 0 and ctx.budget_left_usd > 0
    if ctx.provider is not None and not use_ai:
        ctx.notes.add("AI limit for this run or the daily budget was reached; remaining jobs used rules")
    if use_ai:
        ctx.ai_calls_left -= 1
        try:
            ex, report, usage = claude_matcher.extract(ctx.provider, jd, ctx.view)
        except AIError as e:
            error = e
            usage = e.usage
            ctx.stats["fallbacks"] += 1
            db.add(m.ErrorEvent(component="matching:claude", severity="warning", run_id=ctx.agent_run.run_id,
                                task_id=ctx.agent_run.id, code=e.code, message=e.message[:1000],
                                context={"job_id": str(job.id), "retryable": e.retryable}))
    if ex is None:
        ex = rules_extract(jd, ctx.view)
    if usage:
        ctx.budget_left_usd -= usage.cost_usd
        ctx.stats["cost_usd"] = round(ctx.stats["cost_usd"] + usage.cost_usd, 6)
    db.add(m.TaskAttempt(
        agent_run_id=ctx.agent_run.id, attempt_no=1, status="failed" if error else "succeeded",
        error_code=error.code if error else None, duration_ms=int((time.monotonic() - started) * 1000),
        ai_tokens_in=usage.input_tokens if usage else None, ai_tokens_out=usage.output_tokens if usage else None,
        ai_cost_usd=usage.cost_usd if usage else None,
    ))

    result = score_extraction(ex, jd, ctx.view, ctx.scoring.weights, ctx.scoring.thresholds,
                              ctx.preferred_countries)
    if ex.matcher == "claude":
        model_version = f"claude/{claude_matcher.PROMPT_VERSION}/{ctx.provider.model}/w{ctx.scoring.version_tag()}"
        ctx.stats["claude"] += 1
    else:
        model_version = f"rules-v0/w{ctx.scoring.version_tag()}"
        ctx.stats["rules"] += 1
    explanation = result.explanation
    if error:
        explanation += f" (Claude unavailable: {error.code}; rule-based fallback.)"
    if report.get("dropped_skill_matches"):
        explanation += f" {len(report['dropped_skill_matches'])} unsupported skill claims were discarded."

    existing = db.scalar(select(m.JobMatchEvaluation).where(
        m.JobMatchEvaluation.job_id == job.id, m.JobMatchEvaluation.profile_version_id == ctx.version.id,
        m.JobMatchEvaluation.model_version == model_version))
    if existing is not None:
        return existing
    ev = m.JobMatchEvaluation(
        job_id=job.id, profile_version_id=ctx.version.id, model_version=model_version, matcher=ex.matcher,
        weights={**ctx.scoring.weights, "_thresholds": ctx.scoring.thresholds}, breakdown=result.breakdown,
        score=result.score, track=result.track, seniority=result.seniority, recommendation=result.recommendation,
        eligibility={**result.eligibility, "requirements": ex.requirements, "validation": report},
        matched_skills=result.matched_skills, missing_skills=result.missing_skills,
        explanation=explanation, evidence=result.evidence,
    )
    db.add(ev)
    db.flush()
    return ev


def finish(db: Session, ctx: MatchContext) -> dict:
    ctx.agent_run.status = "succeeded"
    ctx.agent_run.finished_at = datetime.now(UTC)
    ctx.agent_run.output_summary = {**ctx.stats, "notes": sorted(ctx.notes)}
    for note in ctx.notes:
        db.add(m.ErrorEvent(component="matching", severity="info", run_id=ctx.agent_run.run_id,
                            task_id=ctx.agent_run.id, code="matcher_notice", message=note))
    db.flush()
    return ctx.agent_run.output_summary


def classify_pending(db: Session, run_id: uuid.UUID | None = None, preferred_countries: list[str] | None = None,
                     provider: AIProvider | None = None) -> dict:
    """Evaluate every `discovered` application, then move it to `classified`."""
    apps = db.scalars(select(m.Application).where(m.Application.state == State.DISCOVERED.value)).all()
    if not apps:
        return {"classified": 0}
    ctx = make_context(db, run_id, preferred_countries, provider)
    for app in apps:
        ev = evaluate(db, app.job, ctx)
        transitions.apply(db, app.id, State.CLASSIFIED, Actor.ORCHESTRATOR, reason=ev.model_version)
    return {"classified": len(apps), **finish(db, ctx)}


def rescore(db: Session, preferred_countries: list[str] | None = None, provider: AIProvider | None = None,
            app_ids: list[uuid.UUID] | None = None) -> dict:
    """Re-evaluate classified jobs against the current profile, weights and matcher. State is unchanged."""
    stmt = select(m.Application).where(m.Application.state == State.CLASSIFIED.value)
    if app_ids:
        stmt = stmt.where(m.Application.id.in_(app_ids))
    apps = db.scalars(stmt).all()
    if not apps:
        return {"rescored": 0}
    ctx = make_context(db, None, preferred_countries, provider, subject="rescore")
    for app in apps:
        evaluate(db, app.job, ctx)
    return {"rescored": len(apps), **finish(db, ctx)}
