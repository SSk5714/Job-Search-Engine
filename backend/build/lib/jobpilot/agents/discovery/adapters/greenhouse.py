"""Greenhouse public Job Board API (no auth for GET).
https://developers.greenhouse.io/job-board.html — needs the company's board token."""

import re
from datetime import date

from jobpilot.agents.discovery.adapters.base import Adapter, AdapterConfigError, relevant
from jobpilot.agents.discovery.http import SourceClient
from jobpilot.agents.discovery.text import html_to_text, location_parts
from jobpilot.schemas.agents import RawJob, SearchFilters

BASE = "https://boards-api.greenhouse.io/v1/boards"
URL_RE = re.compile(r"(?:job-)?boards(?:\.eu)?\.greenhouse\.io/(?P<board>[\w-]+)/jobs/(?P<id>\d+)", re.I)


def _date(value: str | None) -> date | None:
    try:
        return date.fromisoformat(value[:10]) if value else None
    except ValueError:
        return None


class GreenhouseAdapter(Adapter):
    code = "greenhouse"
    rate_limit_per_min = 60

    def __init__(self):
        self.http = SourceClient(self.code, self.rate_limit_per_min)

    def _to_raw(self, board: str, j: dict) -> RawJob:
        loc = (j.get("location") or {}).get("name") or ""
        city, country = location_parts(loc)
        if not country:
            for office in j.get("offices") or []:
                _, country = location_parts(office.get("name"))
                if country:
                    break
        mode = "remote" if "remote" in loc.lower() else ("hybrid" if "hybrid" in loc.lower() else None)
        return RawJob(
            external_id=f"gh:{board}:{j['id']}",
            url=j["absolute_url"],
            company=j.get("company_name") or board.replace("-", " ").title(),
            title=j["title"],
            city=city,
            country=country,
            location_text=loc,
            work_mode=mode,
            published_at=_date(j.get("first_published") or j.get("updated_at")),
            description_text=html_to_text(j.get("content")),
        )

    def fetch(self, filters: SearchFilters, options: dict | None = None) -> list[RawJob]:
        boards = (options or {}).get("boards") or []
        if not boards:
            raise AdapterConfigError("Add Greenhouse board tokens (e.g. 'gitlab') in the search's source options")
        jobs: list[RawJob] = []
        for board in boards:
            data = self.http.get(f"{BASE}/{board}/jobs", params={"content": "true"}).json()
            for j in data.get("jobs", []):
                raw = self._to_raw(board, j)
                if relevant(raw, filters):
                    jobs.append(raw)
        return jobs

    def check_available(self, url: str, external_id: str | None) -> bool | None:
        if not external_id or not external_id.startswith("gh:"):
            return None
        _, board, job_id = external_id.split(":", 2)
        return self.http.get(f"{BASE}/{board}/jobs/{job_id}", allow_404=True) is not None

    @classmethod
    def parse_url(cls, url: str) -> dict | None:
        m = URL_RE.search(url)
        return {"board": m.group("board"), "id": m.group("id")} if m else None

    def fetch_one(self, ref: dict) -> RawJob | None:
        resp = self.http.get(f"{BASE}/{ref['board']}/jobs/{ref['id']}", allow_404=True)
        return self._to_raw(ref["board"], resp.json()) if resp is not None else None
