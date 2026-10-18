"""The verified facts a document may use, grouped for rendering, plus a few
facts derived by code (employment durations) so claims can cite them."""

import re
from dataclasses import dataclass, field
from datetime import UTC, datetime

from jobpilot.db import models as m

MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


@dataclass
class Fact:
    id: str
    category: str
    entry: str | None
    key: str
    value: str
    context: str | None = None
    derived: bool = False


@dataclass
class FactBook:
    version_id: str
    facts: dict[str, Fact] = field(default_factory=dict)

    def by(self, category: str, entry: str | None = None, key: str | None = None) -> list[Fact]:
        return [f for f in self.facts.values() if f.category == category
                and (entry is None or f.entry == entry) and (key is None or f.key == key)]

    def one(self, category: str, key: str, entry: str | None = None) -> Fact | None:
        found = self.by(category, entry, key)
        return found[0] if found else None

    def entries(self, category: str) -> list[str]:
        seen: list[str] = []
        for f in self.facts.values():
            if f.category == category and f.entry and f.entry not in seen:
                seen.append(f.entry)
        return seen

    def for_prompt(self) -> list[dict]:
        """Facts an AI may see: never contact details."""
        return [{"id": f.id, "category": f.category, "entry": f.entry, "key": f.key, "value": f.value,
                 **({"context": f.context} if f.context else {})}
                for f in self.facts.values() if f.category != "contact"]


def parse_ym(value: str | None) -> tuple[int, int] | None:
    m_ = re.match(r"^\s*(\d{4})-(\d{1,2})", value or "")
    if not m_:
        return None
    return int(m_.group(1)), int(m_.group(2))


def fmt_ym(value: str | None) -> str:
    ym = parse_ym(value)
    if not ym:
        return (value or "").strip()
    return f"{MONTHS[ym[1] - 1]} {ym[0]}"


def months_between(start: str | None, end: str | None) -> int | None:
    a, b = parse_ym(start), parse_ym(end)
    if not a or not b:
        return None
    return (b[0] - a[0]) * 12 + (b[1] - a[1])


def build(version: m.ProfileVersion) -> FactBook:
    book = FactBook(version_id=str(version.id))
    for f in version.facts:
        if f.verified and f.value:
            book.facts[str(f.id)] = Fact(str(f.id), f.category, f.entry, f.key, f.value, f.context)
    for entry in book.entries("employment"):
        start = book.one("employment", "start", entry)
        end = book.one("employment", "end", entry)
        if start:
            end_value = end.value if end else datetime.now(UTC).strftime("%Y-%m")
            n = months_between(start.value, end_value)
            if n is not None and n > 0:
                text = f"{n} months" if n < 24 else f"{n // 12} years"
                fid = f"derived:{entry}:duration"
                book.facts[fid] = Fact(fid, "employment", entry, "duration", text, derived=True)
    return book
