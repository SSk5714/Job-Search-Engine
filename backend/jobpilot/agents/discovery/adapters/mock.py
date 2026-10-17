import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from jobpilot.agents.discovery.adapters.base import Adapter
from jobpilot.schemas.agents import RawJob, SearchFilters

FIXTURES = Path(__file__).parent / "fixtures" / "mock_jobs.json"
COUNTRY_NAMES = {"deutschland": "DE", "germany": "DE", "netherlands": "NL", "czechia": "CZ",
                 "czech republic": "CZ", "austria": "AT", "österreich": "AT"}


def _today() -> date:
    return datetime.now(UTC).date()


def _country(name: str | None) -> str | None:
    if not name:
        return None
    name = name.strip()
    return name.upper() if len(name) == 2 else COUNTRY_NAMES.get(name.lower())


class MockAdapter(Adapter):
    """Reads three differently shaped fixture feeds, like real sources would return."""

    code = "mock"

    def fetch(self, filters: SearchFilters, options: dict | None = None) -> list[RawJob]:
        data = json.loads(FIXTURES.read_text())
        jobs = [*map(self._feed_a, data["feed_a"]), *map(self._feed_b, data["feed_b"]),
                *map(self._feed_c, data["feed_c"])]
        return [j for j in jobs if self._passes(j, filters)]

    @staticmethod
    def _passes(job: RawJob, f: SearchFilters) -> bool:
        if f.countries and job.country and job.country not in f.countries and job.work_mode != "remote":
            return False
        if f.max_age_days is not None and job.published_at:
            if (_today() - job.published_at).days > f.max_age_days:
                return False
        if f.keywords:
            text = f"{job.title} {job.description_text}".lower()
            if not any(k.lower() in text for k in f.keywords):
                return False
        return True

    @staticmethod
    def _feed_a(r: dict) -> RawJob:
        return RawJob(
            external_id=f"a:{r['refnr']}",
            url=r["externeUrl"],
            company=r["arbeitgeber"],
            title=r["titel"],
            city=r["arbeitsort"]["ort"],
            country=_country(r["arbeitsort"]["land"]),
            location_text=f"{r['arbeitsort']['ort']}, {r['arbeitsort']['land']}",
            published_at=_today() - timedelta(days=r["days_ago"]),
            description_text=r["beschreibung"],
            employment_type={"Vollzeit": "full_time", "Teilzeit": "part_time"}.get(r.get("arbeitszeit")),
        )

    @staticmethod
    def _feed_b(r: dict) -> RawJob:
        loc = r["location"]["name"]
        city, _, rest = loc.partition(",")
        mode = "hybrid" if "hybrid" in loc.lower() else ("remote" if "remote" in loc.lower() else "onsite")
        country = rest.replace("(Hybrid)", "").replace("(Remote)", "").strip()
        return RawJob(
            external_id=f"b:{r['id']}",
            url=r["absolute_url"],
            company=r["company"],
            title=r["title"],
            city=city.strip(),
            country=_country(country),
            location_text=loc,
            work_mode=mode,
            published_at=_today() - timedelta(days=r["days_ago"]),
            description_text=r["content"],
            employment_type="full_time",
        )

    @staticmethod
    def _feed_c(r: dict) -> RawJob:
        smin = smax = cur = None
        if r.get("salary"):
            rng, cur = r["salary"].split()
            lo, hi = rng.split("-")
            smin, smax = float(lo), float(hi)
        return RawJob(
            external_id=None,
            url=r["url"],
            company=r["company"],
            title=r["title"],
            city=r["city"],
            country=r["country"],
            location_text=f"{r['city']}, {r['country']}" + (" (remote)" if r["remote"] else ""),
            work_mode="remote" if r["remote"] else "onsite",
            published_at=_today() - timedelta(days=r["days_ago"]),
            description_text=r["description"],
            salary_min=smin,
            salary_max=smax,
            currency=cur,
            available=r["status"] == "open",
        )


class MockBrokenAdapter(Adapter):
    code = "mock_broken"

    def fetch(self, filters: SearchFilters, options: dict | None = None) -> list[RawJob]:
        raise ConnectionError("Simulated upstream outage (mock_broken)")
