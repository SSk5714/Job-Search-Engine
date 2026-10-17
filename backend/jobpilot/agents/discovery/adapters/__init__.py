"""Source adapters. Each adapter is isolated: one failing never stops the others.

The registry declares access mode and implementation, so the UI labels sources
honestly: Automated (built and verified by a real run), Untested (built, never
run live), Manual, Mock, Planned.
"""

from urllib.parse import urlsplit

from jobpilot.agents.discovery.adapters.ba_jobsuche import BAJobsucheAdapter
from jobpilot.agents.discovery.adapters.base import Adapter, AdapterConfigError, AdapterNotImplemented
from jobpilot.agents.discovery.adapters.greenhouse import GreenhouseAdapter
from jobpilot.agents.discovery.adapters.lever import LeverAdapter
from jobpilot.agents.discovery.adapters.mock import MockAdapter, MockBrokenAdapter
from jobpilot.agents.discovery.adapters.personio import PersonioAdapter

# code -> (name, access_mode, adapter class or None, notes)
SOURCES: dict[str, tuple[str, str, type[Adapter] | None, str]] = {
    "mock": ("Mock job board (three feed formats)", "mock", MockAdapter,
             "Offline fixtures for development and tests."),
    "mock_broken": ("Mock source that always fails", "mock", MockBrokenAdapter,
                    "Used in tests to prove one broken source does not stop a run."),
    "ba_jobsuche": ("Bundesagentur für Arbeit Jobsuche", "api", BAJobsucheAdapter,
                    "Germany only. Community-documented REST API (bundesAPI); no official terms published."),
    "greenhouse": ("Company careers on Greenhouse", "api", GreenhouseAdapter,
                   "Public Job Board API. Add board tokens per search, e.g. 'gitlab'."),
    "lever": ("Company careers on Lever", "api", LeverAdapter,
              "Public Postings API. Add site names per search; set region 'eu' for EU-hosted boards."),
    "personio": ("Company careers on Personio", "feed", PersonioAdapter,
                 "Public XML feed. Add company subdomains per search, e.g. 'acme' for acme.jobs.personio.de."),
    "manual": ("Manual import (any site)", "manual", None, "Paste a URL and the job details yourself."),
    "germantechjobs": ("GermanTechJobs", "manual", None, "Manual URL import until a feed or permission is confirmed."),
    "stepstone": ("StepStone", "manual", None, "Terms restrict automated scraping: manual URL import only."),
    "indeed": ("Indeed", "manual", None, "Terms restrict automated scraping: manual URL import only."),
    "xing": ("XING", "manual", None, "Terms restrict automated scraping: manual URL import only."),
    "linkedin": ("LinkedIn", "manual", None, "No scraping or auto-apply: manual URL import and manual apply only."),
}

# Domains whose pages we never fetch; imports from them need the details pasted in.
MANUAL_DOMAINS = {
    "linkedin.com": "linkedin", "stepstone.de": "stepstone", "stepstone.at": "stepstone",
    "indeed.com": "indeed", "indeed.de": "indeed", "de.indeed.com": "indeed", "xing.com": "xing",
    "germantechjobs.de": "germantechjobs",
}
URL_ADAPTERS: list[type[Adapter]] = [BAJobsucheAdapter, GreenhouseAdapter, LeverAdapter, PersonioAdapter]


def get_adapter(code: str) -> Adapter:
    entry = SOURCES.get(code)
    if entry is None or entry[2] is None:
        raise AdapterNotImplemented(code)
    return entry[2]()


def resolve_url(url: str) -> tuple[str, dict | None]:
    """Which source a pasted URL belongs to, and the API reference if we can fetch it."""
    for cls in URL_ADAPTERS:
        ref = cls.parse_url(url)
        if ref:
            return cls.code, ref
    host = (urlsplit(url).hostname or "").lower()
    for domain, code in MANUAL_DOMAINS.items():
        if host == domain or host.endswith("." + domain):
            return code, None
    return "manual", None


__all__ = ["SOURCES", "Adapter", "AdapterConfigError", "AdapterNotImplemented", "get_adapter", "resolve_url"]
