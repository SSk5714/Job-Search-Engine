"""Bundesagentur für Arbeit Jobsuche.

Endpoints and the public client key as documented by the community project
https://github.com/bundesAPI/jobsuche-api (the Bundesagentur publishes no
official API documentation). Germany only. Search results carry no description,
so each new posting is fetched once from the detail endpoint, capped per run.
"""

import base64
import re
from datetime import date

from jobpilot.agents.discovery.adapters.base import Adapter, relevant
from jobpilot.agents.discovery.http import SourceClient, SourceHTTPError
from jobpilot.agents.discovery.text import html_to_text
from jobpilot.schemas.agents import RawJob, SearchFilters

BASE = "https://rest.arbeitsagentur.de/jobboerse/jobsuche-service"
HEADERS = {"X-API-Key": "jobboerse-jobsuche"}
# Both search versions are documented by the community project; the service has moved between them.
SEARCH_PATHS = ["/pc/v4/jobs", "/pc/v6/jobs"]
DETAIL_URL = "https://www.arbeitsagentur.de/jobsuche/jobdetail/{refnr}"
URL_RE = re.compile(r"arbeitsagentur\.de/jobsuche/jobdetail/(?P<refnr>[\w-]+)", re.I)

TRACK_QUERIES = {
    "A": ["Android Entwickler", "Kotlin Entwickler"],
    "B": ["Java Entwickler", "Backend Entwickler Java"],
    "C": ["Embedded Software Entwickler", "C++ Entwickler"],
    "D": ["Werkstudent Softwareentwicklung"],
}


def _encode(refnr: str) -> str:
    return base64.b64encode(refnr.encode()).decode()


def _date(value: str | None) -> date | None:
    try:
        return date.fromisoformat(value[:10]) if value else None
    except ValueError:
        return None


class BAJobsucheAdapter(Adapter):
    code = "ba_jobsuche"
    rate_limit_per_min = 60

    def __init__(self):
        self.http = SourceClient(self.code, self.rate_limit_per_min)
        self._paths = list(SEARCH_PATHS)

    def _search(self, params: dict) -> dict:
        """Search with the first endpoint version that answers; remember it for the rest of the run."""
        last: SourceHTTPError | None = None
        for i, path in enumerate(list(self._paths)):
            try:
                data = self.http.get(f"{BASE}{path}", params=params, headers=HEADERS).json()
            except SourceHTTPError as e:
                if e.code in ("forbidden", "http_error") and i < len(self._paths) - 1:
                    last = e
                    continue
                if last is not None:
                    raise SourceHTTPError(e.code, f"{e} (also tried {', '.join(self._paths[:i])})", e.status) from e
                raise
            if not isinstance(data, dict) or not ({"stellenangebote", "maxErgebnisse"} & data.keys()):
                # answered, but not in the format we read: never report that as "0 jobs found"
                keys = ", ".join(sorted(data)[:8]) if isinstance(data, dict) else type(data).__name__
                last = SourceHTTPError("unexpected_format", f"ba_jobsuche: {path} answered in an unknown format ({keys})")
                if i < len(self._paths) - 1:
                    continue
                raise last
            self._paths = [path] + [p for p in self._paths if p != path]
            return data
        raise last or SourceHTTPError("exhausted", "no search endpoint answered")

    def _queries(self, filters: SearchFilters) -> list[str]:
        if filters.keywords:
            return filters.keywords
        out: list[str] = []
        for t in filters.tracks or ["A", "B", "C", "D"]:
            out += TRACK_QUERIES.get(t, [])
        return out

    def _detail(self, refnr: str) -> dict | None:
        resp = self.http.get(f"{BASE}/pc/v4/jobdetails/{_encode(refnr)}", headers=HEADERS, allow_404=True)
        return resp.json() if resp is not None else None

    def _to_raw(self, item: dict, detail: dict | None) -> RawJob:
        refnr = item["refnr"]
        ort = item.get("arbeitsort") or {}
        description = ""
        if detail:
            description = html_to_text(detail.get("stellenangebotsBeschreibung") or detail.get("stellenbeschreibung"))
        return RawJob(
            external_id=f"ba:{refnr}",
            url=item.get("externeUrl") or DETAIL_URL.format(refnr=refnr),
            company=(item.get("arbeitgeber") or "Unknown employer").strip(),
            title=(item.get("titel") or item.get("beruf") or "Untitled").strip(),
            city=ort.get("ort"),
            country="DE",
            location_text=", ".join(x for x in (ort.get("plz"), ort.get("ort"), ort.get("region")) if x),
            published_at=_date(item.get("aktuelleVeroeffentlichungsdatum")),
            description_text=description,
            employment_type=None,
        )

    def fetch(self, filters: SearchFilters, options: dict | None = None) -> list[RawJob]:
        options = options or {}
        if filters.countries and "DE" not in filters.countries:
            return []
        known: set[str] = set(options.get("_known_external_ids", []))
        size = int(options.get("page_size", 25))
        max_pages = int(options.get("max_pages", 2))
        max_details = int(options.get("max_details", 40))
        cities = filters.cities or [options.get("wo", "")]
        angebotsart = ["1"] + (["34"] if "D" in (filters.tracks or []) else [])
        seen: dict[str, dict] = {}
        for query in self._queries(filters):
            for wo in cities:
                for art in angebotsart:
                    for page in range(1, max_pages + 1):
                        params = {"was": query, "page": page, "size": size, "angebotsart": art, "pav": "false"}
                        if wo:
                            params |= {"wo": wo, "umkreis": int(options.get("radius_km", 50))}
                        if filters.max_age_days is not None:
                            params["veroeffentlichtseit"] = min(filters.max_age_days, 100)
                        data = self._search(params)
                        items = data.get("stellenangebote") or []
                        for it in items:
                            if it.get("refnr"):
                                seen.setdefault(it["refnr"], it)
                        if len(items) < size:
                            break
        jobs: list[RawJob] = []
        details_left = max_details
        for refnr, item in seen.items():
            detail = None
            if f"ba:{refnr}" not in known and details_left > 0:
                detail = self._detail(refnr)
                details_left -= 1
            raw = self._to_raw(item, detail)
            # The API already matched the search terms; only apply country/age/city checks here.
            if relevant(raw, filters.model_copy(update={"keywords": []}), require_tech_title=False):
                jobs.append(raw)
        return jobs

    def check_available(self, url: str, external_id: str | None) -> bool | None:
        if not external_id or not external_id.startswith("ba:"):
            return None
        return self._detail(external_id[3:]) is not None

    @classmethod
    def parse_url(cls, url: str) -> dict | None:
        m = URL_RE.search(url)
        return {"refnr": m.group("refnr")} if m else None

    def fetch_one(self, ref: dict) -> RawJob | None:
        detail = self._detail(ref["refnr"])
        if detail is None:
            return None
        ort = (detail.get("arbeitsorte") or [{}])[0] if isinstance(detail.get("arbeitsorte"), list) else {}
        item = {
            "refnr": ref["refnr"],
            "titel": detail.get("stellenangebotsTitel") or detail.get("titel"),
            "arbeitgeber": detail.get("firma") or detail.get("arbeitgeber"),
            "arbeitsort": ort.get("adresse", ort) if isinstance(ort, dict) else {},
            "aktuelleVeroeffentlichungsdatum": detail.get("aktuelleVeroeffentlichungsdatum"),
        }
        return self._to_raw(item, detail)
