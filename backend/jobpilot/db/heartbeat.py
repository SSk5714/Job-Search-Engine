"""Heartbeats: the scheduler and the monitor each write one and check the other's."""

import os
import socket
from datetime import UTC, datetime

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from jobpilot.db import models as m


def beat(db: Session, component: str, interval_s: int, detail: dict | None = None) -> None:
    now = datetime.now(UTC)
    stmt = pg_insert(m.Heartbeat).values(component=component, beat_at=now, interval_s=interval_s, started_at=now,
                                         detail={"host": socket.gethostname(), "pid": os.getpid(), **(detail or {})})
    db.execute(stmt.on_conflict_do_update(index_elements=["component"], set_={
        "beat_at": now, "interval_s": interval_s, "detail": stmt.excluded.detail}))


def age(db: Session, component: str, now: datetime | None = None) -> tuple[m.Heartbeat | None, float | None]:
    hb = db.get(m.Heartbeat, component)
    if hb is None:
        return None, None
    return hb, ((now or datetime.now(UTC)) - hb.beat_at).total_seconds()
