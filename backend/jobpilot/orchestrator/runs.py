"""Search runs: the orchestrator plans the run, calls each source adapter in
isolation, persists validated results, and advances state through `transitions`.

Workers (adapters, matcher) return data; only this module writes it.
"""

import logging
import time
import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from jobpilot.agents.discovery.adapters import SOURCES, AdapterNotImplemented, get_adapter
from jobpilot.config import get_settings
from jobpilot.db import models as m
from jobpilot.db.session import SessionLocal
from jobpilot.domain import transitions
from jobpilot.domain.dedup import fingerprint, normalize_url
from jobpilot.domain.errors import DomainError
from jobpilot.domain.profile import current_version, profile_view
from jobpilot.domain.scoring import DEFAULT_WEIGHTS, detect_languages, detect_seniority, extract_skills, score_job
from jobpilot.domain.states import Actor, State
from jobpilot.schemas.agents import RawJob, SearchFilters

log = logging.getLogger("jobpilot.orchestrator")


def sync_sources(db: Session) -> None:
    """Keep job_sources in step with the adapter registry."""
    existing = {s.code: s for s in db.scalars(select(m.JobSource)).all()}
    for code, (name, mode, cls, notes) in SOURCES.items():
        src = existing.get(code)
        if src is None:
            db.add(m.JobSource(code=code, name=name, access_mode=mode, implemented=cls is not None,
                               enabled=code == "mock", notes=notes))
        else:
            src.name, src.access_mode, src.implemented, src.notes = name, mode, cls is not None, notes
    db.flush()


def start_run(db: Session, config_id: uuid.UUID, trigger: str = "manual") -> m.SearchRun:
    config = db.get(m.SearchConfig, config_id)
    if config is None:
        raise DomainError("not_found", "Search configuration not found", status_code=404)
    run = m.SearchRun(config_id=config.id, trigger=trigger, status="running", allow_overlap=config.allow_overlap)
    db.add(run)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise DomainError("run_in_progress", "A run for this search is already in progress")
    return run


def _ingest(db: Session, source: m.JobSource, raw: RawJob, run_id: uuid.UUID) -> str:
    url_norm = normalize_url(str(raw.url))
    now = datetime.now(UTC)
    existing = db.scalar(select(m.Job).where(m.Job.url_normalized == url_norm))
    if existing is not None:
        existing.retrieved_at = now
        existing.availability = "open" if raw.available else "closed"
        existing.availability_checked_at = now
        return "duplicate_url"

    fp = fingerprint(raw.company, raw.title, raw.city)
    original = db.scalar(select(m.Job).where(m.Job.fingerprint == fp, m.Job.duplicate_of_id.is_(None)).limit(1))
    text = f"{raw.title}\n{raw.description_text}"
    job = m.Job(
        source_id=source.id,
        external_id=raw.external_id,
        url=str(raw.url),
        url_normalized=url_norm,
        fingerprint=fp,
        duplicate_of_id=original.id if original else None,
        company=raw.company,
        title=raw.title,
        country=raw.country,
        city=raw.city,
        location_text=raw.location_text,
        work_mode=raw.work_mode,
        employment_type=raw.employment_type,
        seniority=detect_seniority(raw.title, raw.description_text),
        language_reqs=detect_languages(raw.description_text),
        skills=extract_skills(text),
        salary_min=raw.salary_min,
        salary_max=raw.salary_max,
        currency=raw.currency,
        published_at=raw.published_at,
        retrieved_at=now,
        first_seen_run_id=run_id,
        availability="open" if raw.available else "closed",
        availability_checked_at=now,
        description_text=raw.description_text,
    )
    db.add(job)
    db.flush()
    if original is not None:
        return "duplicate_fingerprint"
    if not raw.available:
        return "closed"
    transitions.create_application(db, job.id)
    return "new"


def classify_pending(db: Session, preferred_countries: list[str] | None = None) -> int:
    """Evaluate every `discovered` application against the current verified profile."""
    version = current_version(db)
    view = profile_view(version)
    model_version = get_settings().matching_model_version
    apps = db.scalars(select(m.Application).where(m.Application.state == State.DISCOVERED.value)).all()
    for app in apps:
        job = app.job
        result = score_job(
            {"title": job.title, "description_text": job.description_text, "skills": job.skills,
             "seniority": job.seniority, "language_reqs": job.language_reqs, "country": job.country,
             "work_mode": job.work_mode},
            view, DEFAULT_WEIGHTS, preferred_countries,
        )
        exists = db.scalar(select(m.JobMatchEvaluation).where(
            m.JobMatchEvaluation.job_id == job.id,
            m.JobMatchEvaluation.profile_version_id == version.id,
            m.JobMatchEvaluation.model_version == model_version,
        ))
        if exists is None:
            db.add(m.JobMatchEvaluation(
                job_id=job.id, profile_version_id=version.id, model_version=model_version,
                weights=DEFAULT_WEIGHTS, breakdown=result.breakdown, score=result.score, track=result.track,
                seniority=result.seniority, recommendation=result.recommendation, eligibility=result.eligibility,
                matched_skills=result.matched_skills, missing_skills=result.missing_skills,
                explanation=result.explanation, evidence=result.evidence,
            ))
            db.flush()
        transitions.apply(db, app.id, State.CLASSIFIED, Actor.ORCHESTRATOR, reason=f"{model_version} evaluation")
    return len(apps)


def execute_run(run_id: uuid.UUID) -> dict:
    """Run every source of the config in isolation; persist per source."""
    db = SessionLocal()
    try:
        run = db.get(m.SearchRun, run_id)
        if run is None or run.status != "running":
            return {"skipped": True}
        config = db.get(m.SearchConfig, run.config_id)
        filters = SearchFilters(**(config.filters or {}))
        sync_sources(db)
        db.commit()

        counts = {"new": 0, "duplicate_url": 0, "duplicate_fingerprint": 0, "closed": 0, "fetched": 0}
        per_source: dict[str, dict] = {}
        ok_sources = failed_sources = 0

        for code in config.source_codes or ["mock"]:
            source = db.scalar(select(m.JobSource).where(m.JobSource.code == code))
            agent_run = m.AgentRun(run_id=run.id, agent="discovery", subject=code)
            db.add(agent_run)
            db.commit()
            started = time.monotonic()
            try:
                if source is None:
                    raise AdapterNotImplemented(code)
                adapter = get_adapter(code)
                raw_jobs = adapter.fetch(filters)
                src_counts = {"fetched": len(raw_jobs)}
                for raw in raw_jobs:
                    outcome = _ingest(db, source, raw, run.id)
                    src_counts[outcome] = src_counts.get(outcome, 0) + 1
                agent_run.status = "succeeded"
                agent_run.output_summary = src_counts
                db.add(m.TaskAttempt(agent_run_id=agent_run.id, attempt_no=1, status="succeeded",
                                     duration_ms=int((time.monotonic() - started) * 1000)))
                db.commit()
                ok_sources += 1
                per_source[code] = {"status": "ok", **src_counts}
                for k, v in src_counts.items():
                    counts[k] = counts.get(k, 0) + v
            except Exception as exc:  # one broken source never stops the run
                db.rollback()
                failed_sources += 1
                error_code = "not_implemented" if isinstance(exc, AdapterNotImplemented) else type(exc).__name__
                agent_run = db.merge(agent_run)
                agent_run.status = "failed"
                agent_run.output_summary = {"error": str(exc)[:500]}
                db.add(m.TaskAttempt(agent_run_id=agent_run.id, attempt_no=1, status="failed",
                                     error_code=error_code, duration_ms=int((time.monotonic() - started) * 1000)))
                db.add(m.ErrorEvent(component=f"discovery:{code}", severity="warning", run_id=run.id,
                                    task_id=agent_run.id, code=error_code, message=str(exc)[:1000]))
                db.commit()
                per_source[code] = {"status": "failed", "error": error_code}
                log.warning("source %s failed: %s", code, exc)
            finally:
                agent_run.finished_at = datetime.now(UTC)
                db.commit()

        classified = 0
        try:
            classified = classify_pending(db, filters.countries)
            db.commit()
        except Exception as exc:
            db.rollback()
            db.add(m.ErrorEvent(component="matching", severity="critical", run_id=run.id,
                                code=type(exc).__name__, message=str(exc)[:1000]))
            db.commit()
            failed_sources += 1

        run = db.get(m.SearchRun, run_id)
        run.status = "completed" if failed_sources == 0 else ("partial" if ok_sources else "failed")
        run.finished_at = datetime.now(UTC)
        run.summary = {**counts, "classified": classified, "sources": per_source}
        db.commit()
        return run.summary
    except Exception as exc:
        db.rollback()
        run = db.get(m.SearchRun, run_id)
        if run is not None:
            run.status = "failed"
            run.finished_at = datetime.now(UTC)
            run.summary = {"error": str(exc)[:500]}
            db.add(m.ErrorEvent(component="orchestrator", severity="critical", run_id=run_id,
                                code=type(exc).__name__, message=str(exc)[:1000]))
            db.commit()
        raise
    finally:
        db.close()
