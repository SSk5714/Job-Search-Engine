from abc import ABC, abstractmethod

from jobpilot.schemas.agents import RawJob, SearchFilters


class AdapterNotImplemented(Exception):
    def __init__(self, code: str):
        super().__init__(f"No automated adapter for source '{code}'")
        self.code = code


class Adapter(ABC):
    """Fetch raw jobs from one source. Must not score, classify or write to the DB."""

    code: str

    @abstractmethod
    def fetch(self, filters: SearchFilters) -> list[RawJob]: ...

    def is_available(self, url: str) -> bool | None:
        """Recheck a listing. None = cannot tell (treated as unknown)."""
        return None
