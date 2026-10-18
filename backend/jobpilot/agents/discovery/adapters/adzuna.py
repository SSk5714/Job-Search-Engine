"""Adzuna job search API (developer.adzuna.com): collects jobs from many German
job boards and company sites. Needs a free app id and key in .env
(JOBPILOT_ADZUNA_APP_ID / JOBPILOT_ADZUNA_APP_KEY). Descriptions are snippets;
the link leads to the full listing."""

from datetime import date

from jobpilot.agents.discovery.adapters.base import (
    Adapter,
    AdapterConfigError,
    company_matches,
    job_type,
    relevant,
)
from jobpilot.agents.discovery.http import SourceClient, SourceHTTPError
from jobpilot.agents.discovery.text import html_to_text
from jobpilot.config import get_settings
from jobpilot.schemas.agents import RawJob, SearchFilters

API = "https://api.adzuna.com/v1/api/jobs/de/search/{page}"
TYPE_WORDS = {"job": "", "werkstudent": "Werkstudent", "praktikum": "Praktikum", "abschlussarbeit": "Abschlussarbeit"}


def _date(value) -> date | None:
    try:
        return date.fromisoformat(str(value)[:10]) if value else None
    except ValueError:
        return None


class AdzunaAdapter(Adapter):
    code = "adzuna"
    rate_limit_per_min = 20  # the free plan allows 25 calls a minute

    def __init__(self):
        self.http = SourceClient(self.code, self.rate_limit_per_min)

    def _to_raw(self, j: dict) -> RawJob:
        loc = j.get("location") or {}
        area = loc.get("area") or []
        city = area[-1] if len(area) >= 3 else None
        return RawJob(
            external_id=f"az:{j['id']}",
            url=j["redirect_url"],
            company=((j.get("company") or {}).get("display_name") or "Unknown employer").strip()[:255],
            title=html_to_text(j.get("title") or "Untitled")[:255] or "Untitled",
            location_text=loc.get("display_name") or "",
            city=city,
            country="DE",
            published_at=_date(j.get("created")),
            description_text=html_to_text(j.get("description")),
            salary_min=None,  # Adzuna often estimates salaries; never show a guess as fact
            employment_type=j.get("contract_time"),
        )

    def _search(self, what: str, where: str | None, filters: SearchFilters, options: dict, page: int) -> list[dict]:
        s = get_settings()
        params = {"app_id": s.adzuna_app_id, "app_key": s.adzuna_app_key, "what": what,
                  "results_per_page": 50, "content-type": "application/json"}
        if where:
            params |= {"where": where, "distance": int(options.get("radius_km", 50))}
        if filters.max_age_days is not None:
            params["max_days_old"] = filters.max_age_days
        data = self.http.get(API.format(page=page), params=params).json()
        if not isinstance(data, dict) or not isinstance(data.get("results"), list):
            raise SourceHTTPError("unexpected_format", "adzuna: answered in an unknown format")
        return data["results"]

    def fetch(self, filters: SearchFilters, options: dict | None = None) -> list[RawJob]:
        options = options or {}
        s = get_settings()
        if not (s.adzuna_app_id and s.adzuna_app_key):
            raise AdapterConfigError("Adzuna needs a free key: add JOBPILOT_ADZUNA_APP_ID and JOBPILOT_ADZUNA_APP_KEY "
                                     "to .env (developer.adzuna.com), then restart")
        if filters.countries and "DE" not in filters.countries:
            return []
        max_pages = int(options.get("max_pages", 1))
        types = filters.job_types or ["job"]
        searches: list[tuple[str, str | None, str | None]] = []
        for kw in filters.keywords or ["Softwareentwickler"]:
            for t in types:
                what = f"{TYPE_WORDS[t]} {kw}".strip()
                searches += [(what, c, None) for c in (filters.cities or [None])]
        for company in filters.companies:
            for t in filters.job_types or ["werkstudent", "praktikum", "abschlussarbeit"]:
                searches.append((f"{TYPE_WORDS[t] or 'Software'} {company}", None, company))
        seen: dict[str, RawJob] = {}
        for what, where, company in searches:
            for page in range(1, max_pages + 1):
                items = self._search(what, where, filters, options, page)
                for j in items:
                    if not isinstance(j, dict) or not j.get("id") or not j.get("redirect_url"):
                        continue
                    raw = self._to_raw(j)
                    if company and (not company_matches(raw.company, [company]) or
                                    (filters.job_types and job_type(raw.title) not in filters.job_types)):
                        continue
                    if company or relevant(raw, filters.model_copy(update={"cities": []}), require_tech_title=False):
                        seen.setdefault(raw.external_id, raw)
                if len(items) < 50:
                    break
        return list(seen.values())
