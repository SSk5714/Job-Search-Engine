"""Search cadence: friendly presets <-> cron, evaluated in the schedule's time zone.

Deterministic and DST-safe: next times are computed in local time with zoneinfo, then stored in UTC.
Searches run at most once an hour so job sources are never hammered.
"""

from datetime import UTC, datetime, timedelta
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from croniter import croniter
from pydantic import BaseModel, Field, model_validator

MIN_INTERVAL = timedelta(minutes=60)
DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


class Cadence(BaseModel):
    kind: Literal["off", "every_hours", "daily", "weekdays", "weekly", "cron"] = "off"
    every_hours: int = Field(default=6, ge=1, le=24)
    at: str = Field(default="08:00", pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    weekday: Literal["mon", "tue", "wed", "thu", "fri", "sat", "sun"] = "mon"
    cron: str | None = Field(default=None, max_length=64)
    timezone: str = "Europe/Berlin"

    @model_validator(mode="after")
    def check(self):
        try:
            ZoneInfo(self.timezone)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValueError(f"Unknown time zone {self.timezone}")
        expr = self.to_cron()
        if expr is not None:
            validate_cron(expr, self.timezone)
        return self

    def to_cron(self) -> str | None:
        h, mi = (int(x) for x in self.at.split(":"))
        match self.kind:
            case "off":
                return None
            case "every_hours":
                return f"{mi} */{self.every_hours} * * *" if self.every_hours < 24 else f"{mi} {h} * * *"
            case "daily":
                return f"{mi} {h} * * *"
            case "weekdays":
                return f"{mi} {h} * * 1-5"
            case "weekly":
                return f"{mi} {h} * * {DAYS.index(self.weekday) + 1 if self.weekday != 'sun' else 0}"
            case "cron":
                if not self.cron:
                    raise ValueError("Enter a cron expression")
                return self.cron.strip()


def validate_cron(expr: str, tz: str) -> None:
    if not croniter.is_valid(expr) or len(expr.split()) != 5:
        raise ValueError("Not a valid 5-field cron expression")
    start = datetime(2026, 1, 5)  # naive wall-clock time: gaps between runs as written
    it = croniter(expr, start)
    times = [it.get_next(datetime) for _ in range(48)]
    gaps = [b - a for a, b in zip(times, times[1:], strict=False)]
    if min(gaps) < MIN_INTERVAL:
        raise ValueError("Searches can run at most once an hour")


def next_run(expr: str, tz: str, after: datetime) -> datetime:
    """Next due time strictly after `after`, in UTC."""
    # croniter mishandles offsets when a DST change falls between runs, so iterate on naive
    # local wall-clock time and attach the zone afterwards.
    zone = ZoneInfo(tz)
    wall = after.astimezone(zone).replace(tzinfo=None)
    it = croniter(expr, wall)
    for _ in range(10):
        nxt = it.get_next(datetime).replace(tzinfo=zone).astimezone(UTC)
        if nxt > after:
            return nxt
    raise ValueError("Could not compute the next run time")


def describe(expr: str | None, tz: str) -> str:
    if not expr:
        return "Off (run by hand)"
    parts = expr.split()
    mi, h, dom, mon, dow = parts
    at = f"{int(h):02d}:{int(mi):02d}" if h.isdigit() and mi.isdigit() else None
    if dom == mon == "*":
        if h.startswith("*/") and dow == "*":
            return f"Every {h[2:]} hours at :{int(mi):02d} ({tz})"
        if at and dow == "*":
            return f"Daily at {at} ({tz})"
        if at and dow == "1-5":
            return f"Weekdays at {at} ({tz})"
        if at and dow.isdigit():
            return f"Every {['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday'][int(dow) % 7]} at {at} ({tz})"
    return f"Cron {expr} ({tz})"
