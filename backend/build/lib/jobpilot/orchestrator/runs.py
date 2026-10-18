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

from jobpilot.agents.discovery.adapters import (
    SOURCES,
    AdapterConfigError,
    AdapterNotImplemented,
    get_adapter,
    resolve_url,
)
from jobpilot.agents.discovery.http import SourceHTTPError
from jobpilot.db import models as m
from jobpilot.db.session import SessionLocal
from jobpilot.domain import transitions
from jobpilot.domain.dedup import fingerprint, normalize_url
from jobpilot.domain.errors import DomainError
from jobpilot.domain.scoring import detect_languages, detect_seniority, extract_skills
from jobpilot.orchestrator import matching
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
    try:
        with db.begin_nested():  # savepoint: the caller's other work survives a conflict
            db.add(run)
            db.flush()
    except IntegrityError:
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


def _notify_high_fit(db: Session, run: m.SearchRun) -> None:
    """One summary per run (never one per job) when new high-fit jobs await review."""
    from jobpilot.domain import settings as app_settings
    from jobpilot.notify import notify

    threshold = app_settings.get(db, "notifications").high_fit_min_score
    rows = db.execute(
        select(m.Job.title, m.Job.company, m.JobMatchEvaluation.score)
        .join(m.Application, m.Application.job_id == m.Job.id)
        .join(m.JobMatchEvaluation, m.JobMatchEvaluation.job_id == m.Job.id)
        .where(m.Job.first_seen_run_id == run.id, m.Application.state == "classified",
               m.JobMatchEvaluation.score >= threshold)
        .order_by(m.JobMatchEvaluation.score.desc())).all()
    seen, top = set(), []
    for title, company, score in rows:
        if (title, company) not in seen:
            seen.add((title, company))
            top.append(f"{score} · {title} at {company}")
    if not top:
        return
    notify(db, "high_fit", f"{len(top)} new high-fit job{'s' if len(top) != 1 else ''} to review",
           "\n".join(top[:5]) + (f"\n…and {len(top) - 5} more" if len(top) > 5 else ""),
           dedup_key=f"high_fit:{run.id}", link="/jobs", context={"run_id": str(run.id), "count": len(top)})


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
                options = dict((config.source_options or {}).get(code, {}))
                options["_known_external_ids"] = list(db.scalars(
                    select(m.Job.external_id).where(m.Job.source_id == source.id, m.Job.external_id.is_not(None))))
                raw_jobs = adapter.fetch(filters, options)
                src_counts = {"fetched": len(raw_jobs)}
                for raw in raw_jobs:
                    outcome = _ingest(db, source, raw, run.id)
                    src_counts[outcome] = src_counts.get(outcome, 0) + 1
                agent_run.status = "succeeded"
                agent_run.output_summary = src_counts
                if source.access_mode != "mock" and raw_jobs and source.live_verified_at is None:
                    source.live_verified_at = datetime.now(UTC)  # first proof the live integration works
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
                if isinstance(exc, AdapterNotImplemented):
                    error_code = "not_implemented"
                elif isinstance(exc, AdapterConfigError):
                    error_code = "needs_configuration"
                elif isinstance(exc, SourceHTTPError):
                    error_code = exc.code
                else:
                    error_code = type(exc).__name__
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

        classified: dict = {"classified": 0}
        try:
            classified = matching.classify_pending(db, run.id, filters.countries)
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
        run.summary = {**counts, "classified": classified.get("classified", 0), "matching": classified,
                       "sources": per_source}
        db.commit()
        try:
            _notify_high_fit(db, run)
            db.commit()
        except Exception:  # a notification problem never fails a finished run
            db.rollback()
            log.exception("high-fit notification failed for run %s", run.id)
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


def recheck_availability(db: Session, job: m.Job) -> str:
    """Ask the source whether the listing is still open. Unknown never counts as open."""
    now = datetime.now(UTC)
    status = "unknown"
    try:
        adapter = get_adapter(job.source.code)
        result = adapter.check_available(job.url, job.external_id)
        status = {True: "open", False: "closed", None: "unknown"}[result]
    except (AdapterNotImplemented, SourceHTTPError) as exc:
        db.add(m.ErrorEvent(component=f"availability:{job.source.code}", severity="info",
                            code=getattr(exc, "code", type(exc).__name__), message=str(exc)[:500],
                            context={"job_id": str(job.id)}))
    if job.source.access_mode == "mock":
        status = job.availability  # fixtures are static
    job.availability = status if status != "unknown" else job.availability
    job.availability_checked_at = now if status != "unknown" else job.availability_checked_at
    db.flush()
    return status


def import_url(db: Session, url: str, manual: dict) -> tuple[m.Job, str]:
    """Add one job from a pasted URL. API-backed sources are fetched; other sites are
    never fetched, so their details must be supplied by the user."""
    code, ref = resolve_url(url)
    raw = None
    if ref is not None:
        try:
            raw = get_adapter(code).fetch_one(ref)
        except SourceHTTPError as exc:
            if not manual.get("title"):
                raise DomainError("source_unreachable", f"Could not fetch the posting ({exc.code}); "
                                  "paste the title, company and description instead", status_code=422)
    if raw is None:
        missing = [k for k in ("title", "company") if not manual.get(k)]
        if missing:
            raise DomainError("details_required", f"{SOURCES[code][0]} pages are not fetched automatically; "
                              f"fill in: {', '.join(missing)}", {"source": code, "missing": missing}, status_code=422)
        raw = RawJob(url=url, company=manual["company"], title=manual["title"], city=manual.get("city"),
                     country=(manual.get("country") or None), location_text=manual.get("city") or "",
                     work_mode=manual.get("work_mode"), description_text=manual.get("description") or "")
    sync_sources(db)
    source = db.scalar(select(m.JobSource).where(m.JobSource.code == code))
    outcome = _ingest(db, source, raw, run_id=None)
    job = db.scalar(select(m.Job).where(m.Job.url_normalized == normalize_url(str(raw.url))))
    if ref is not None and outcome == "new" and source.live_verified_at is None:
        source.live_verified_at = datetime.now(UTC)
    return job, outcome
