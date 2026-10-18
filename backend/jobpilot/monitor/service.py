"""The independent monitor: its own loop, its own heartbeat, no dependency on Celery or the
scheduler. Run with `python -m jobpilot.monitor`.

Per cycle: run every check (a crashing check becomes its own alert), open or refresh alerts
for what was found, close monitor alerts whose condition cleared, record health status changes,
and write the heartbeat. If the database itself is unreachable, it logs to a local fallback file
and, when email is configured, sends one direct email per outage.
"""

from __future__ import annotations

import json
import logging
import time
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select

from jobpilot.config import get_settings
from jobpilot.db import models as m
from jobpilot.db.session import SessionLocal
from jobpilot.domain import settings as app_settings
from jobpilot.monitor import checks
from jobpilot.notify import Finding, raise_alert, resolve_cleared
from jobpilot.db.heartbeat import beat

log = logging.getLogger("jobpilot.monitor")


def _structured(event: str, **kw) -> None:
    log.info(json.dumps({"event": event, "at": datetime.now(UTC).isoformat(), **kw}, default=str))


def run_once(now: datetime | None = None) -> dict:
    """One monitoring cycle against the database. Raises if the database is unreachable."""
    now = now or datetime.now(UTC)
    db = SessionLocal()
    try:
        cfg = app_settings.get(db, "monitor")
        ctx = checks.Ctx(db, now, cfg)
        found: list[Finding] = []
        status: dict[str, str] = {}
        for name, fn in checks.CHECKS:
            try:
                res = fn(ctx)
                found += res
                status[name] = "ok" if not res else max((f.severity for f in res),
                                                         key=lambda s: app_settings.SEVERITY_RANK[s])
                db.rollback()  # checks only read; end their snapshot
            except Exception as e:
                db.rollback()
                if name == "database":
                    raise
                status[name] = "error"
                found.append(Finding(f"{checks.P}check-error:{name}", "warning", "monitor",
                                     f"Monitor check “{name}” failed", f"{type(e).__name__}: {e}"[:400],
                                     "Usually a bug or a schema mismatch; check the monitor logs.",
                                     likely_cause="The check itself crashed"))
        keys = {f.key for f in found}
        opened = 0
        for f in found:
            _, created = raise_alert(db, f)
            opened += created
            if created:
                _structured("alert_opened", key=f.key, severity=f.severity, component=f.component, title=f.title)
        closed = 0
        for name, prefixes in checks.OWNS.items():
            if status.get(name) == "error":
                continue
            for p in prefixes:
                closed += resolve_cleared(db, checks.P + p, keys)
        closed += resolve_cleared(db, f"{checks.P}check-error:", keys)
        _record_health(db, status, now)
        beat(db, "monitor", get_settings().monitor_interval_s,
             {"checks": len(checks.CHECKS), "findings": len(found), "status": status})
        db.commit()
        summary = {"findings": len(found), "opened": opened, "closed": closed, "status": status}
        _structured("monitor_cycle", **summary)
        return summary
    finally:
        db.close()


def _record_health(db, status: dict[str, str], now: datetime) -> None:
    """health_checks keeps status CHANGES only (a history, not one row per minute)."""
    for name, st in status.items():
        mapped = {"ok": "ok", "info": "ok", "warning": "degraded", "critical": "down", "error": "degraded"}[st]
        last = db.scalar(select(m.HealthCheck).where(m.HealthCheck.check_name == name)
                         .order_by(m.HealthCheck.at.desc()).limit(1))
        if last is None or last.status != mapped:
            db.add(m.HealthCheck(check_name=name, status=mapped, detail=st, at=now))


class Monitor:
    """Loop with outage handling. Kept as a class so tests can drive single cycles."""

    def __init__(self, sender=None):
        self.db_down_since: datetime | None = None
        self.outage_emailed = False
        self.sender = sender

    def cycle(self) -> dict:
        try:
            summary = run_once()
        except Exception as e:
            return self._db_unreachable(e)
        if self.db_down_since is not None:
            self._db_recovered()
        return summary

    def _fallback(self, record: dict) -> None:
        p = Path(get_settings().monitor_fallback_log)
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("a") as fh:
            fh.write(json.dumps(record, default=str) + "\n")

    def _db_unreachable(self, e: Exception) -> dict:
        now = datetime.now(UTC)
        first = self.db_down_since is None
        self.db_down_since = self.db_down_since or now
        rec = {"event": "database_unreachable", "at": now.isoformat(), "since": self.db_down_since.isoformat(),
               "error": f"{type(e).__name__}: {e}"[:300], "severity": "critical",
               "remediation": "Start PostgreSQL (docker compose up -d postgres) and check JOBPILOT_DATABASE_URL."}
        self._fallback(rec)
        log.critical(json.dumps(rec))
        if first and not self.outage_emailed and get_settings().email_configured:
            from email.message import EmailMessage

            from jobpilot.notify.delivery import smtp_send

            s = get_settings()
            msg = EmailMessage()
            msg["Subject"], msg["From"], msg["To"] = "[JobPilot ALERT] Database unreachable", s.email_from, s.notify_email_to
            msg.set_content(f"The monitor cannot reach the database since {self.db_down_since:%Y-%m-%d %H:%M UTC}.\n"
                            f"Error: {rec['error']}\nWhat to do: {rec['remediation']}\n"
                            "Searches, preparation and submissions cannot run until it is back.")
            try:
                (self.sender or smtp_send)(msg)
                self.outage_emailed = True
            except Exception as mail_err:  # nothing else we can do; the fallback log has it
                self._fallback({"event": "outage_email_failed", "error": str(mail_err)[:300]})
        return {"database": "down", "since": self.db_down_since.isoformat()}

    def _db_recovered(self) -> None:
        since, self.db_down_since, self.outage_emailed = self.db_down_since, None, False
        now = datetime.now(UTC)
        try:
            with SessionLocal() as db:
                raise_alert(db, Finding(
                    f"db-outage:{since:%Y%m%dT%H%M}", "warning", "database", "The database was unreachable",
                    f"From {since:%Y-%m-%d %H:%M} to {now:%H:%M} UTC. Work that ran during the outage may have "
                    "failed; check recent runs and any application in “needs manual input”.",
                    "Resolve this alert once you have checked. Details are in the monitor fallback log.",
                    likely_cause="PostgreSQL was stopped, restarting or out of resources"))
                db.commit()
        except Exception:
            log.exception("could not record the database outage")
        self._fallback({"event": "database_recovered", "at": now.isoformat(), "since": since.isoformat()})


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    interval = get_settings().monitor_interval_s
    mon = Monitor()
    log.info("monitor started, every %ss", interval)
    while True:
        started = time.monotonic()
        try:
            mon.cycle()
        except Exception:  # never let the monitor die on a bug; the next cycle tries again
            log.exception("monitor cycle crashed")
        time.sleep(max(1.0, interval - (time.monotonic() - started)))
