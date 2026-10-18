"""Agent input/output contracts (design pack, section 5). Phase 1 uses discovery."""

import uuid
from datetime import date
from typing import Literal

from pydantic import BaseModel, Field, HttpUrl


class SearchFilters(BaseModel):
    countries: list[str] = Field(default_factory=lambda: ["DE"])
    cities: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)
    tracks: list[str] = Field(default_factory=lambda: ["A", "B", "C", "D"])
    work_modes: list[str] = Field(default_factory=list)  # onsite | hybrid | remote
    employment_types: list[str] = Field(default_factory=list)
    seniority: list[str] = Field(default_factory=list)
    max_age_days: int | None = 30
    # job | werkstudent | praktikum | abschlussarbeit; empty = every kind
    job_types: list[Literal["job", "werkstudent", "praktikum", "abschlussarbeit"]] = Field(default_factory=list)
    companies: list[str] = Field(default_factory=list, max_length=40)  # employers you want, e.g. BMW


class DiscoveryInput(BaseModel):
    run_id: uuid.UUID
    source_code: str
    filters: SearchFilters


class RawJob(BaseModel):
    """Untrusted data from a source. Stored and shown, never executed or obeyed."""

    external_id: str | None = None
    url: HttpUrl
    company: str = Field(min_length=1, max_length=255)
    title: str = Field(min_length=1, max_length=255)
    location_text: str = ""
    city: str | None = None
    country: str | None = Field(default=None, min_length=2, max_length=2)
    work_mode: str | None = None
    published_at: date | None = None
    description_text: str = ""
    salary_min: float | None = None
    salary_max: float | None = None
    currency: str | None = None
    employment_type: str | None = None
    available: bool = True


class SourceError(BaseModel):
    source_code: str
    code: str
    message: str


class DiscoveryOutput(BaseModel):
    jobs: list[RawJob]
    source_errors: list[SourceError] = Field(default_factory=list)
