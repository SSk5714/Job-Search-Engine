import re
from abc import ABC, abstractmethod
from datetime import UTC, datetime

from jobpilot.schemas.agents import RawJob, SearchFilters

TECH_TITLE = re.compile(
    r"develop|engineer|entwickler|software|programm|werkstudent|working student|intern|praktik|android|"
    r"java|kotlin|backend|back-end|embedded|c\+\+|mobile|devops|firmware|informatik|aosp",
    re.I,
)


class AdapterNotImplemented(Exception):
    def __init__(self, code: str):
        super().__init__(f"No automated adapter for source '{code}'")
        self.code = code


class AdapterConfigError(Exception):
    """The search configuration lacks what this source needs (e.g. Greenhouse board names)."""


class Adapter(ABC):
    """Fetch raw jobs from one source. Must not score, classify or write to the DB."""

    code: str
    rate_limit_per_min: int = 30

    @abstractmethod
    def fetch(self, filters: SearchFilters, options: dict | None = None) -> list[RawJob]: ...

    def check_available(self, url: str, external_id: str | None) -> bool | None:
        """Recheck a listing: True open, False gone, None cannot tell."""
        return None

    @classmethod
    def parse_url(cls, url: str) -> dict | None:
        """If this adapter can fetch a single posting from `url`, return its identifiers."""
        return None

    def fetch_one(self, ref: dict) -> RawJob | None:
        return None


def relevant(job: RawJob, filters: SearchFilters, require_tech_title: bool = True) -> bool:
    """Client-side filtering for sources that return a whole company's openings."""
    if filters.countries and job.country and job.country not in filters.countries and job.work_mode != "remote":
        return False
    if filters.max_age_days is not None and job.published_at:
        if (datetime.now(UTC).date() - job.published_at).days > filters.max_age_days:
            return False
    text = f"{job.title}\n{job.description_text}".lower()
    if filters.keywords:
        return any(k.lower() in text for k in filters.keywords)
    if filters.cities and job.city and job.work_mode != "remote":
        if not any(c.lower() in (job.city or "").lower() for c in filters.cities):
            return False
    return bool(TECH_TITLE.search(job.title)) if require_tech_title else True
