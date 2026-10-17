import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from jobpilot.agents.discovery.adapters import SOURCES
from jobpilot.api import serializers as s
from jobpilot.api.deps import current_user, run_idempotent
from jobpilot.config import get_settings
from jobpilot.db import models as m
from jobpilot.db.session import get_db
from jobpilot.domain.errors import DomainError, NotFound
from jobpilot.orchestrator import runs
from jobpilot.schemas.agents import SearchFilters

router = APIRouter(tags=["search"], dependencies=[Depends(current_user)])


@router.get("/sources")
def list_sources(db: Session = Depends(get_db)):
    return [s.source(x) for x in db.scalars(select(m.JobSource).order_by(m.JobSource.code)).all()]


class SourcePatch(BaseModel):
    enabled: bool


@router.patch("/sources/{code}")
def patch_source(code: str, body: SourcePatch, db: Session = Depends(get_db)):
    src = db.scalar(select(m.JobSource).where(m.JobSource.code == code))
    if src is None:
        raise NotFound("Source")
    if body.enabled and not src.implemented:
        raise DomainError("not_implemented", f"{src.name} has no automated adapter yet; it cannot be enabled")
    src.enabled = body.enabled
    db.commit()
    return s.source(src)


def _config_out(c: m.SearchConfig) -> dict:
    return {"id": c.id, "name": c.name, "filters": c.filters, "source_codes": c.source_codes,
            "source_options": c.source_options or {}, "cron": c.cron,
            "allow_overlap": c.allow_overlap, "enabled": c.enabled}


class ConfigIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    filters: SearchFilters = Field(default_factory=SearchFilters)
    source_codes: list[str] = Field(default_factory=lambda: ["mock"])
    source_options: dict[str, dict] = Field(default_factory=dict)
    cron: str | None = Field(default=None, max_length=64)
    allow_overlap: bool = False
    enabled: bool = True


def _check_sources(codes: list[str]) -> None:
    unknown = [c for c in codes if c not in SOURCES]
    if unknown:
        raise DomainError("validation_error", f"Unknown sources: {', '.join(unknown)}", status_code=422)
    manual = [c for c in codes if SOURCES[c][2] is None]
    if manual:
        raise DomainError("validation_error", f"Not searchable automatically: {', '.join(manual)}. "
                          "Use URL import for these.", status_code=422)


@router.get("/search-configs")
def list_configs(db: Session = Depends(get_db)):
    return [_config_out(c) for c in db.scalars(select(m.SearchConfig).order_by(m.SearchConfig.created_at)).all()]


@router.post("/search-configs", status_code=201)
def create_config(body: ConfigIn, db: Session = Depends(get_db)):
    _check_sources(body.source_codes)
    c = m.SearchConfig(**{**body.model_dump(), "filters": body.filters.model_dump()})
    db.add(c)
    db.commit()
    return _config_out(c)


@router.patch("/search-configs/{config_id}")
def update_config(config_id: uuid.UUID, body: ConfigIn, db: Session = Depends(get_db)):
    c = db.get(m.SearchConfig, config_id)
    if c is None:
        raise NotFound("Search configuration")
    _check_sources(body.source_codes)
    for k, v in body.model_dump().items():
        setattr(c, k, v)
    c.filters = body.filters.model_dump()
    db.commit()
    return _config_out(c)


class RunIn(BaseModel):
    config_id: uuid.UUID


@router.post("/search-runs", status_code=202)
def create_run(body: RunIn, request: Request, background: BackgroundTasks, db: Session = Depends(get_db)):
    def handler():
        run = runs.start_run(db, body.config_id, trigger="manual")
        return 202, s.run(run)

    def dispatch(payload: dict) -> None:
        run_id = payload["id"]
        if get_settings().redis_url:
            from jobpilot.worker import run_search

            run_search.delay(str(run_id))
        else:
            background.add_task(runs.execute_run, run_id)

    return run_idempotent(db, request, "POST /search-runs", body.model_dump(), handler, after_commit=dispatch)


@router.get("/search-runs")
def list_runs(limit: int = 20, db: Session = Depends(get_db)):
    rows = db.scalars(select(m.SearchRun).order_by(m.SearchRun.started_at.desc()).limit(min(limit, 100))).all()
    return [s.run(r) for r in rows]


@router.get("/search-runs/{run_id}")
def get_run(run_id: uuid.UUID, db: Session = Depends(get_db)):
    r = db.get(m.SearchRun, run_id)
    if r is None:
        raise NotFound("Search run")
    attempts = db.scalars(select(m.AgentRun).where(m.AgentRun.run_id == r.id)).all()
    return {**s.run(r), "agents": [{"agent": a.agent, "subject": a.subject, "status": a.status,
                                    "summary": a.output_summary, "started_at": a.started_at,
                                    "finished_at": a.finished_at} for a in attempts]}
