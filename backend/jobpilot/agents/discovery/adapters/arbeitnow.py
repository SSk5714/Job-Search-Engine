"""Arbeitnow job board: a free public API of jobs in Germany, many from company
career sites (e.g. Bosch via SmartRecruiters). No key. It returns the newest
jobs page by page with no search parameters, so filtering happens here."""

import re
from datetime import UTC, datetime

from jobpilot.agents.discovery.adapters.base import Adapter, relevant
from jobpilot.agents.discovery.http import SourceClient, SourceHTTPError
from jobpilot.agents.discovery.text import html_to_text
from jobpilot.schemas.agents import RawJob, SearchFilters

API = "https://www.arbeitnow.com/api/job-board-api"
URL_RE = re.compile(r"arbeitnow\.com/jobs/companies/[\w-]+/(?P<slug>[\w-]+)", re.I)


def _published(value) -> datetime | None:
    try:
        return datetime.fromtimestamp(int(value), UTC)
    except (TypeError, ValueError, OSError):
        return None


class ArbeitnowAdapter(Adapter):
    code = "arbeitnow"
    rate_limit_per_min = 30

    def __init__(self):
        self.http = SourceClient(self.code, self.rate_limit_per_min)

    def _to_raw(self, j: dict) -> RawJob:
        location = (j.get("location") or "").strip()
        remote = bool(j.get("remote"))
        published = _published(j.get("created_at"))
        return RawJob(
            external_id=f"an:{j['slug']}",
            url=j["url"],
            company=(j.get("company_name") or "Unknown employer").strip()[:255],
            title=(j.get("title") or "Untitled").strip()[:255],
            location_text=location,
            city=location.split(",")[0].strip() or None if location and "remote" not in location.lower() else None,
            country="DE",
            work_mode="remote" if remote else None,
            published_at=published.date() if published else None,
            description_text=html_to_text(j.get("description")),
            employment_type=", ".join(j.get("job_types") or []) or None,
        )

    def fetch(self, filters: SearchFilters, options: dict | None = None) -> list[RawJob]:
        options = options or {}
        if filters.countries and "DE" not in filters.countries:
            return []
        max_pages = int(options.get("max_pages", 5))
        jobs: list[RawJob] = []
        for page in range(1, max_pages + 1):
            data = self.http.get(API, params={"page": page}).json()
            if not isinstance(data, dict) or not isinstance(data.get("data"), list):
                raise SourceHTTPError("unexpected_format", "arbeitnow: answered in an unknown format")
            items = data["data"]
            too_old = 0
            for j in items:
                if not isinstance(j, dict) or not j.get("slug") or not j.get("url"):
                    continue
                raw = self._to_raw(j)
                if filters.max_age_days is not None and raw.published_at and \
                        (datetime.now(UTC).date() - raw.published_at).days > filters.max_age_days:
                    too_old += 1
                    continue
                if relevant(raw, filters):
                    jobs.append(raw)
            if not items or too_old == len(items) or not (data.get("links") or {}).get("next", True):
                break  # newest first: once a whole page is too old, the rest is older still
        return jobs

    @classmethod
    def parse_url(cls, url: str) -> dict | None:
        return None  # the public API has no single-job endpoint; paste the details instead
