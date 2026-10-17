"""Lever public Postings API. https://github.com/lever/postings-api
Needs the company's site name; EU-hosted companies use api.eu.lever.co."""

import re
from datetime import UTC, datetime

from jobpilot.agents.discovery.adapters.base import Adapter, AdapterConfigError, relevant
from jobpilot.agents.discovery.http import SourceClient
from jobpilot.agents.discovery.text import html_to_text, location_parts
from jobpilot.schemas.agents import RawJob, SearchFilters

URL_RE = re.compile(r"jobs\.(?P<eu>eu\.)?lever\.co/(?P<site>[\w.-]+)/(?P<id>[0-9a-f-]{36})", re.I)
MODES = {"remote": "remote", "hybrid": "hybrid", "on-site": "onsite"}


def _base(region: str) -> str:
    return "https://api.eu.lever.co/v0/postings" if region == "eu" else "https://api.lever.co/v0/postings"


class LeverAdapter(Adapter):
    code = "lever"
    rate_limit_per_min = 60

    def __init__(self):
        self.http = SourceClient(self.code, self.rate_limit_per_min)

    def _to_raw(self, site: str, region: str, p: dict, names: dict) -> RawJob:
        cats = p.get("categories") or {}
        loc = cats.get("location") or ""
        city, country = location_parts(loc)
        parts = [p.get("descriptionPlain") or html_to_text(p.get("description"))]
        for lst in p.get("lists") or []:
            parts.append(f"{lst.get('text', '')}\n{html_to_text(lst.get('content'))}")
        parts.append(p.get("additionalPlain") or "")
        sal = p.get("salaryRange") or {}
        created = p.get("createdAt")
        return RawJob(
            external_id=f"lever:{region}:{site}:{p['id']}",
            url=p["hostedUrl"],
            company=names.get(site) or site.replace("-", " ").title(),
            title=p["text"],
            city=city,
            country=(p.get("country") or country),
            location_text=loc,
            work_mode=MODES.get(p.get("workplaceType") or ""),
            published_at=datetime.fromtimestamp(created / 1000, UTC).date() if created else None,
            description_text="\n\n".join(x for x in parts if x).strip()[:20000],
            salary_min=sal.get("min"),
            salary_max=sal.get("max"),
            currency=sal.get("currency"),
            employment_type=cats.get("commitment"),
        )

    def fetch(self, filters: SearchFilters, options: dict | None = None) -> list[RawJob]:
        options = options or {}
        sites = options.get("sites") or []
        if not sites:
            raise AdapterConfigError("Add Lever site names in the search's source options")
        region = options.get("region", "global")
        names = options.get("names", {})
        jobs: list[RawJob] = []
        for site in sites:
            data = self.http.get(f"{_base(region)}/{site}", params={"mode": "json"}).json()
            for p in data if isinstance(data, list) else []:
                raw = self._to_raw(site, region, p, names)
                if relevant(raw, filters):
                    jobs.append(raw)
        return jobs

    def check_available(self, url: str, external_id: str | None) -> bool | None:
        if not external_id or not external_id.startswith("lever:"):
            return None
        _, region, site, pid = external_id.split(":", 3)
        return self.http.get(f"{_base(region)}/{site}/{pid}", params={"mode": "json"}, allow_404=True) is not None

    @classmethod
    def parse_url(cls, url: str) -> dict | None:
        m = URL_RE.search(url)
        if not m:
            return None
        return {"site": m.group("site"), "id": m.group("id"), "region": "eu" if m.group("eu") else "global"}

    def fetch_one(self, ref: dict) -> RawJob | None:
        resp = self.http.get(f"{_base(ref['region'])}/{ref['site']}/{ref['id']}", params={"mode": "json"},
                             allow_404=True)
        return self._to_raw(ref["site"], ref["region"], resp.json(), {}) if resp is not None else None
