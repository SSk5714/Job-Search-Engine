"""Personio public XML job feed: https://<company>.jobs.personio.de/xml
(documented at support.personio.de, article 207576365). Element names follow the
widely used feed format; the feed has no country field, so it is inferred from
the office name when possible. XML is parsed with defusedxml (untrusted input)."""

import re
from datetime import date

from defusedxml import ElementTree as ET

from jobpilot.agents.discovery.adapters.base import Adapter, AdapterConfigError, relevant
from jobpilot.agents.discovery.http import SourceClient
from jobpilot.agents.discovery.text import html_to_text, location_parts
from jobpilot.schemas.agents import RawJob, SearchFilters

URL_RE = re.compile(r"(?P<co>[\w-]+)\.jobs\.personio\.(?:de|com)/job/(?P<id>\d+)", re.I)


def _t(el, tag: str) -> str | None:
    child = el.find(tag)
    return child.text.strip() if child is not None and child.text else None


class PersonioAdapter(Adapter):
    code = "personio"
    rate_limit_per_min = 30

    def __init__(self):
        self.http = SourceClient(self.code, self.rate_limit_per_min)
        self._feeds: dict[str, list] = {}

    def _feed(self, company: str, language: str = "en") -> list:
        key = f"{company}:{language}"
        if key not in self._feeds:
            resp = self.http.get(f"https://{company}.jobs.personio.de/xml", params={"language": language},
                                 headers={"Accept": "application/xml"})
            root = ET.fromstring(resp.content)
            self._feeds[key] = root.findall(".//position")
        return self._feeds[key]

    def _to_raw(self, company: str, pos, names: dict) -> RawJob:
        pid = _t(pos, "id") or "0"
        office = _t(pos, "office")
        city, country = location_parts(office)
        sections = []
        for d in pos.findall("./jobDescriptions/jobDescription"):
            sections.append(f"{_t(d, 'name') or ''}\n{html_to_text(_t(d, 'value'))}")
        created = _t(pos, "createdAt")
        try:
            published = date.fromisoformat(created[:10]) if created else None
        except ValueError:
            published = None
        return RawJob(
            external_id=f"personio:{company}:{pid}",
            url=f"https://{company}.jobs.personio.de/job/{pid}",
            company=_t(pos, "subcompany") or names.get(company) or company.replace("-", " ").title(),
            title=_t(pos, "name") or "Untitled",
            city=city or office,
            country=country,
            location_text=office or "",
            published_at=published,
            description_text="\n\n".join(sections).strip()[:20000],
            employment_type=_t(pos, "employmentType"),
        )

    def fetch(self, filters: SearchFilters, options: dict | None = None) -> list[RawJob]:
        options = options or {}
        companies = options.get("companies") or []
        if not companies:
            raise AdapterConfigError("Add Personio company subdomains in the search's source options")
        names = options.get("names", {})
        jobs = []
        for co in companies:
            for pos in self._feed(co, options.get("language", "en")):
                raw = self._to_raw(co, pos, names)
                if relevant(raw, filters):
                    jobs.append(raw)
        return jobs

    def check_available(self, url: str, external_id: str | None) -> bool | None:
        if not external_id or not external_id.startswith("personio:"):
            return None
        _, co, pid = external_id.split(":", 2)
        return any(_t(p, "id") == pid for p in self._feed(co))

    @classmethod
    def parse_url(cls, url: str) -> dict | None:
        m = URL_RE.search(url)
        return {"company": m.group("co"), "id": m.group("id")} if m else None

    def fetch_one(self, ref: dict) -> RawJob | None:
        for pos in self._feed(ref["company"]):
            if _t(pos, "id") == ref["id"]:
                return self._to_raw(ref["company"], pos, {})
        return None
