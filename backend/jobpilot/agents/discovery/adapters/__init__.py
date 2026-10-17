"""Source adapters. Each adapter is isolated: one failing never stops the others.

Registry entries also declare access mode and whether the adapter is implemented,
so the UI can label sources honestly (Automated / Manual / Mock / Not implemented).
"""

from jobpilot.agents.discovery.adapters.base import Adapter, AdapterNotImplemented
from jobpilot.agents.discovery.adapters.mock import MockAdapter, MockBrokenAdapter

# code -> (name, access_mode, adapter class or None, notes)
SOURCES: dict[str, tuple[str, str, type[Adapter] | None, str]] = {
    "mock": ("Mock job board (three feed formats)", "mock", MockAdapter,
             "Offline fixtures for development and tests."),
    "mock_broken": ("Mock source that always fails", "mock", MockBrokenAdapter,
                    "Used in tests to prove one broken source does not stop a run."),
    "ba_jobsuche": ("Bundesagentur für Arbeit Jobsuche", "api", None,
                    "Planned for Phase 2 via the documented REST search API; terms to verify."),
    "greenhouse": ("Company careers on Greenhouse", "api", None, "Planned for Phase 2 (public Job Board API)."),
    "lever": ("Company careers on Lever", "api", None, "Planned for Phase 2 (public Postings API)."),
    "personio": ("Company careers on Personio", "feed", None, "Planned for Phase 2 (public XML feed)."),
    "germantechjobs": ("GermanTechJobs", "manual", None, "Manual URL import until a feed or permission is confirmed."),
    "stepstone": ("StepStone", "manual", None, "Terms restrict automated scraping: manual URL import only."),
    "indeed": ("Indeed", "manual", None, "Terms restrict automated scraping: manual URL import only."),
    "xing": ("XING", "manual", None, "Terms restrict automated scraping: manual URL import only."),
    "linkedin": ("LinkedIn", "manual", None, "No scraping or auto-apply: manual URL import and manual apply only."),
}


def get_adapter(code: str) -> Adapter:
    entry = SOURCES.get(code)
    if entry is None or entry[2] is None:
        raise AdapterNotImplemented(code)
    return entry[2]()


__all__ = ["SOURCES", "Adapter", "AdapterNotImplemented", "get_adapter"]
