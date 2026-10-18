"""Bundesagentur für Arbeit Jobsuche.

Endpoints and the public client key as documented by the community project
https://github.com/bundesAPI/jobsuche-api (the Bundesagentur publishes no
official API documentation). Germany only. Search results carry no description,
so each new posting is fetched once from the detail endpoint, capped per run.
"""

import base64
import re
from datetime import date

from jobpilot.agents.discovery.adapters.base import Adapter, company_matches, relevant
from jobpilot.agents.discovery.http import SourceClient, SourceHTTPError
from jobpilot.agents.discovery.text import html_to_text
from jobpilot.schemas.agents import RawJob, SearchFilters

BASE = "https://rest.arbeitsagentur.de/jobboerse/jobsuche-service"
HEADERS = {"X-API-Key": "jobboerse-jobsuche"}
# Both search versions are documented by the community project; the service has moved between them.
SEARCH_PATHS = ["/pc/v4/jobs", "/pc/v6/jobs", "/pc/v4/app/jobs"]
DETAIL_PATHS = ["/pc/v4/jobdetails", "/pc/v3/jobdetails"]
DETAIL_URL = "https://www.arbeitsagentur.de/jobsuche/jobdetail/{refnr}"
URL_RE = re.compile(r"arbeitsagentur\.de/jobsuche/jobdetail/(?P<refnr>[\w-]+)", re.I)

TRACK_QUERIES = {
    "A": ["Android Entwickler", "Kotlin Entwickler"],
    "B": ["Java Entwickler", "Backend Entwickler Java"],
    "C": ["Embedded Software Entwickler", "C++ Entwickler"],
    "D": ["Werkstudent Softwareentwicklung"],
}


# Words the Bundesagentur search understands for each kind of position.
TYPE_WORDS = {"werkstudent": "Werkstudent", "abschlussarbeit": "Abschlussarbeit"}
COMPANY_WORDS = {"job": "Software", "werkstudent": "Werkstudent", "praktikum": "Praktikum",
                 "abschlussarbeit": "Abschlussarbeit"}
# Common short names -> how the employer appears in Bundesagentur listings.
EMPLOYER_NAMES = {"bmw": "Bayerische Motoren Werke", "vw": "Volkswagen", "mercedes": "Mercedes-Benz",
                  "bosch": "Bosch", "porsche": "Porsche"}


def _encode(refnr: str) -> str:
    return base64.b64encode(refnr.encode()).decode()


def _date(value: str | None) -> date | None:
    try:
        return date.fromisoformat(value[:10]) if value else None
    except (TypeError, ValueError):
        return None


def _ref(item: dict) -> str | None:
    """v4 calls the reference `refnr`, v6 `referenznummer`."""
    return item.get("refnr") or item.get("referenznummer")


def _text(*values) -> str | None:
    for v in values:
        if isinstance(v, str) and v.strip():
            return v.strip()
        if isinstance(v, dict):  # e.g. {"name": "..."} in newer answers
            inner = v.get("name") or v.get("firmenname") or v.get("bezeichnung")
            if isinstance(inner, str) and inner.strip():
                return inner.strip()
    return None


def _place(item: dict) -> dict:
    ort = item.get("arbeitsort")
    if not isinstance(ort, dict):
        orte = item.get("arbeitsorte")
        ort = orte[0] if isinstance(orte, list) and orte and isinstance(orte[0], dict) else {}
    return ort.get("adresse") if isinstance(ort.get("adresse"), dict) else ort


def _plan(filters: SearchFilters, queries: list[str]) -> list[dict]:
    """One search per keyword and kind of position: (was, angebotsart or None)."""
    types = filters.job_types or []
    if not types:  # no choice made: regular jobs, plus internships for the student track
        return [{"was": q, "angebotsart": a} for q in queries
                for a in (["1"] + (["34"] if "D" in (filters.tracks or []) else []))]
    plan = []
    for q in queries:
        for t in types:
            if t == "job":
                plan.append({"was": q, "angebotsart": "1"})
            elif t == "praktikum":
                plan.append({"was": q, "angebotsart": "34"})
            elif t in TYPE_WORDS:
                plan.append({"was": f"{TYPE_WORDS[t]} {q}", "angebotsart": None})
    return plan


class BAJobsucheAdapter(Adapter):
    code = "ba_jobsuche"
    rate_limit_per_min = 60

    def __init__(self):
        self.http = SourceClient(self.code, self.rate_limit_per_min)
        self._paths = list(SEARCH_PATHS)
        self._detail_paths = list(DETAIL_PATHS)

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
            items = data.get("stellenangebote") if isinstance(data, dict) else None
            readable = isinstance(data, dict) and ({"stellenangebote", "maxErgebnisse"} & data.keys()) and (
                not items or any(isinstance(it, dict) and _ref(it) for it in items))
            if not readable:
                # answered, but not in the format we read: never report that as "0 jobs found"
                keys = ", ".join(sorted(data)[:8]) if isinstance(data, dict) else type(data).__name__
                if items:
                    keys = "jobs with " + ", ".join(sorted(items[0])[:8]) if isinstance(items[0], dict) else keys
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
        """The full description. A refused detail endpoint costs the description, never the job."""
        while self._detail_paths:
            path = self._detail_paths[0]
            try:
                resp = self.http.get(f"{BASE}{path}/{_encode(refnr)}", headers=HEADERS, allow_404=True)
                return resp.json() if resp is not None else None
            except SourceHTTPError as e:
                if e.code not in ("forbidden", "http_error"):
                    raise
                self._detail_paths.pop(0)  # this version is refused: don't ask it again this run
        return None

    def _to_raw(self, item: dict, detail: dict | None) -> RawJob:
        refnr = _ref(item)
        ort = _place(item)
        d = detail or {}
        description = html_to_text(d.get("stellenangebotsBeschreibung") or d.get("stellenbeschreibung")
                                   or item.get("stellenbeschreibung") or "")
        title = _text(item.get("titel"), item.get("stellenangebotsTitel"), d.get("stellenangebotsTitel"),
                      d.get("titel"), item.get("beruf")) or "Untitled"
        company = _text(item.get("arbeitgeber"), item.get("firma"), item.get("arbeitgeberName"), d.get("firma"),
                        d.get("arbeitgeber")) or "Unknown employer"
        city = _text(ort.get("ort"), ort.get("stadt"))
        return RawJob(
            external_id=f"ba:{refnr}",
            url=item.get("externeUrl") or DETAIL_URL.format(refnr=refnr),
            company=company[:255],
            title=title[:255],
            location_text=", ".join(x for x in (ort.get("plz"), city, ort.get("region")) if isinstance(x, str) and x),
            city=city,
            country="DE",
            published_at=_date(item.get("aktuelleVeroeffentlichungsdatum") or item.get("veroeffentlichungsdatum")
                               or d.get("aktuelleVeroeffentlichungsdatum")),
            description_text=description or title,
            employment_type=None,
        )

    def fetch(self, filters: SearchFilters, options: dict | None = None) -> list[RawJob]:
        options = options or {}
        if filters.countries and "DE" not in filters.countries:
            return []
        known: set[str] = set(options.get("_known_external_ids", []))
        size = int(options.get("page_size", 25))
        max_pages = int(options.get("max_pages", 2))
        max_details = int(options.get("max_details", 60))
        cities = filters.cities or [options.get("wo", "")]
        searches = [(p, wo, None) for p in _plan(filters, self._queries(filters)) for wo in cities]
        # Your target companies, across Germany: student and entry positions by employer name.
        company_types = filters.job_types or ["werkstudent", "praktikum", "abschlussarbeit"]
        for company in filters.companies:
            for t in company_types:
                plan = {"was": COMPANY_WORDS[t], "angebotsart": "34" if t == "praktikum" else None}
                searches.append((plan, "", company.strip()))
        seen: dict[str, dict] = {}
        for plan, wo, company in searches:
            for page in range(1, (1 if company else max_pages) + 1):
                params = {"was": plan["was"], "page": page, "size": size, "pav": "false"}
                if plan["angebotsart"]:
                    params["angebotsart"] = plan["angebotsart"]
                if wo:
                    params |= {"wo": wo, "umkreis": int(options.get("radius_km", 50))}
                if company:
                    params["arbeitgeber"] = EMPLOYER_NAMES.get(company.lower(), company)
                if filters.max_age_days is not None:
                    params["veroeffentlichtseit"] = min(filters.max_age_days, 100)
                items = self._search(params).get("stellenangebote") or []
                for it in items:
                    if not (isinstance(it, dict) and _ref(it)):
                        continue
                    if company and not company_matches(_text(it.get("arbeitgeber"), it.get("firma")) or "", [company]):
                        continue  # the employer filter is a hint to the service; keep only that employer
                    seen.setdefault(_ref(it), it)
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
            # The API already matched the words and the distance around each city;
            # only the country and age checks are left (a city 30 km away is a match, not a miss).
            if relevant(raw, filters.model_copy(update={"keywords": [], "cities": []}), require_tech_title=False):
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
