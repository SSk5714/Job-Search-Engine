import re
from abc import ABC, abstractmethod
from datetime import UTC, datetime

from jobpilot.schemas.agents import RawJob, SearchFilters

TECH_TITLE = re.compile(
    r"develop|engineer|entwickler|software|programm|werkstudent|working student|intern|praktik|android|"
    r"java|kotlin|backend|back-end|embedded|c\+\+|mobile|devops|firmware|informatik|aosp",
    re.I,
)


JOB_TYPES = {
    "abschlussarbeit": re.compile(r"abschlussarbeit|masterarbeit|bachelorarbeit|master'?s? thesis|bachelor'?s? thesis|"
                                  r"\bthesis\b|diplomarbeit", re.I),
    "werkstudent": re.compile(r"werkstudent|working student|studentische|student assistant|studentjob|hiwi", re.I),
    "praktikum": re.compile(r"praktik|\bintern\b|internship|trainee|volontariat", re.I),
}
_LEGAL = re.compile(r"\b(ag|se|gmbh|kg|co|mbh|inc|ltd|group|gruppe|aktiengesellschaft|holding)\b\.?", re.I)


def job_type(title: str) -> str:
    """'job', 'werkstudent', 'praktikum' or 'abschlussarbeit', from the title."""
    for kind, rx in JOB_TYPES.items():
        if rx.search(title or ""):
            return kind
    return "job"


def _norm_company(name: str) -> str:
    return " ".join(_LEGAL.sub(" ", re.sub(r"[^\w&]+", " ", (name or "").lower())).split())


def company_matches(company: str, targets: list[str]) -> str | None:
    """The target a company name belongs to ('BMW' matches 'BMW AG' and 'Bayerische Motoren Werke AG')."""
    have = _norm_company(company)
    if not have:
        return None
    for t in targets:
        want = _norm_company(COMPANY_ALIASES.get(t.strip().lower(), t))
        short = _norm_company(t)
        if (want and (have == want or have.startswith(want + " ") or f" {want} " in f" {have} ")) or \
                (short and (have == short or have.startswith(short + " ") or f" {short} " in f" {have} ")):
            return t.strip()
    return None


COMPANY_ALIASES = {"bmw": "Bayerische Motoren Werke", "vw": "Volkswagen", "mercedes": "Mercedes-Benz"}


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
    """Client-side filtering for sources that return a whole company's or board's openings."""
    if filters.countries and job.country and job.country not in filters.countries and job.work_mode != "remote":
        return False
    if filters.max_age_days is not None and job.published_at:
        if (datetime.now(UTC).date() - job.published_at).days > filters.max_age_days:
            return False
    if filters.job_types and job_type(job.title) not in filters.job_types:
        return False
    if filters.companies and company_matches(job.company, filters.companies):
        return True  # a company you asked for: anywhere in the country, any subject
    if filters.cities and job.city and job.work_mode != "remote":
        if not any(c.lower() in (job.city or "").lower() for c in filters.cities):
            return False
    text = f"{job.title}\n{job.description_text}".lower()
    if filters.keywords:
        return any(k.lower() in text for k in filters.keywords)
    return bool(TECH_TITLE.search(job.title)) if require_tech_title else True
