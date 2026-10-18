"""Notifications: the right events, no noise, email with safe retries."""

import socket
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from aiosmtpd.controller import Controller
from sqlalchemy import func, select

from jobpilot.config import get_settings
from jobpilot.db import models as m
from jobpilot.db.session import SessionLocal
from jobpilot.notify import Finding, notify, raise_alert
from jobpilot.notify import delivery

from tests.conftest import STANDARD_ANSWERS, answer, documents_ready_app


class Inbox:
    """A local SMTP server. `script` lists replies for the next DATA commands (None = accept)."""

    def __init__(self):
        self.messages, self.script = [], []

    async def handle_DATA(self, server, session, envelope):
        reply = self.script.pop(0) if self.script else None
        if reply:
            return reply
        self.messages.append(envelope.content.decode("utf8", "replace"))
        return "250 OK"


def _free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


@pytest.fixture
def smtp(monkeypatch):
    inbox = Inbox()
    port = _free_port()
    ctl = Controller(inbox, hostname="127.0.0.1", port=port)
    ctl.start()
    for k, v in {"SMTP_HOST": "127.0.0.1", "SMTP_PORT": str(port), "SMTP_STARTTLS": "false",
                 "EMAIL_FROM": "jobpilot@example.org", "NOTIFY_EMAIL_TO": "candidate@example.org"}.items():
        monkeypatch.setenv(f"JOBPILOT_{k}", v)
    get_settings.cache_clear()
    yield inbox
    ctl.stop()
    monkeypatch.undo()
    get_settings.cache_clear()


def _email_on(api, **extra):
    r = api.put("/settings/notifications", {"email_enabled": True, **extra}, key=None)
    assert r.status_code == 200, r.text
    return r.json()


def _deliveries():
    with SessionLocal() as db:
        return db.scalars(select(m.NotificationDelivery).order_by(m.NotificationDelivery.created_at)).all()


def _alert(severity="critical", key=None):
    return Finding(key or f"test:{uuid.uuid4()}", severity, "test", "Something broke", "It broke.",
                   "Fix it.", likely_cause="A test", workflow_paused=True)


def test_ready_for_review_and_submitted_are_notified_once(api, clean_portal):
    app_id = documents_ready_app(api)
    api.post(f"/applications/{app_id}/prepare", {"apply_url": clean_portal.url("standard")})
    answer(api, app_id, STANDARD_ANSWERS)
    api.post(f"/applications/{app_id}/approve")
    assert api.post(f"/applications/{app_id}/submit").status_code == 200
    notes = api.get("/notifications?kind=updates").json()
    kinds = [n["kind"] for n in notes]
    assert kinds.count("ready_for_review") == 1 and kinds.count("submitted") == 1
    sent = next(n for n in notes if n["kind"] == "submitted")
    assert "follow-up reminder is set for 20" in sent["body"]  # the real date, not "later"


def test_notify_is_once_per_dedup_key(db):
    assert notify(db, "high_fit", "3 new jobs", dedup_key="high_fit:x") is not None
    assert notify(db, "high_fit", "3 new jobs", dedup_key="high_fit:x") is None
    db.commit()
    assert db.scalar(select(func.count()).select_from(m.Notification)) == 1


def test_repeated_alert_refreshes_instead_of_duplicating(db):
    raise_alert(db, _alert("warning", "test:same"))
    n, created = raise_alert(db, _alert("warning", "test:same"))
    assert not created and n.occurrences == 2
    n, _ = raise_alert(db, _alert("critical", "test:same"))
    assert n.severity == "critical"  # escalates in place
    db.commit()
    assert db.scalar(select(func.count()).select_from(m.Notification)) == 1


def test_no_email_unless_configured_and_enabled(api, db):
    raise_alert(db, _alert())
    db.commit()
    assert _deliveries() == []  # server has no SMTP settings


def test_email_is_sent_with_alert_details(api, db, smtp):
    _email_on(api)
    n, _ = raise_alert(db, _alert())
    db.commit()
    counts = delivery.deliver_due(db)
    assert counts == {"sent": 1, "retrying": 0, "failed": 0}
    msg = smtp.messages[0]
    for part in ("[JobPilot ALERT] Something broke", "Severity: critical", "Component: test", "Likely cause: A test",
                 "What to do: Fix it.", "Workflow paused: yes", f"Message-ID: <delivery-{_deliveries()[0].id}"):
        assert part in msg, part
    assert delivery.deliver_due(db)["sent"] == 0  # never twice


def test_only_chosen_kinds_and_severities_are_emailed(api, db, smtp):
    _email_on(api, email_kinds=["alert"], email_alert_min_severity="critical")
    raise_alert(db, _alert("warning"))
    notify(db, "high_fit", "2 new high-fit jobs", dedup_key="high_fit:k")
    db.commit()
    assert _deliveries() == []
    raise_alert(db, _alert("critical"))
    db.commit()
    assert len(_deliveries()) == 1


def test_transient_failure_backs_off_then_sends(api, db, smtp):
    _email_on(api)
    smtp.script = ["421 Service not available, try later"]
    raise_alert(db, _alert())
    db.commit()
    now = datetime.now(UTC)
    assert delivery.deliver_due(db, now) == {"sent": 0, "retrying": 1, "failed": 0}
    d = _deliveries()[0]
    assert d.status == "pending" and d.attempts == 1 and "421" in d.last_error
    assert d.next_attempt_at >= now + timedelta(seconds=59)
    assert delivery.deliver_due(db, now + timedelta(seconds=30))["sent"] == 0  # not yet
    assert delivery.deliver_due(db, now + timedelta(seconds=61))["sent"] == 1
    assert len(smtp.messages) == 1 and _deliveries()[0].status == "sent"


def test_permanent_failure_stops_and_raises_an_in_app_alert(api, db, smtp):
    _email_on(api)
    smtp.script = ["550 Mailbox unavailable"]
    raise_alert(db, _alert())
    db.commit()
    assert delivery.deliver_due(db)["failed"] == 1
    assert _deliveries()[0].status == "failed"
    alert = next(a for a in api.get("/alerts").json() if a["alert_key"] == "delivery:email")
    assert "SMTP" in alert["remediation"] and alert["deliveries"] == []  # not emailed about email failing
    # retry from the UI after fixing the mail server
    failed_note = next(a for a in api.get("/alerts").json() if a["alert_key"] != "delivery:email")
    r = api.post(f"/notifications/{failed_note['id']}/retry-delivery", key=None)
    assert r.status_code == 200 and r.json()["requeued"] == 1
    assert delivery.deliver_due(db)["sent"] == 1
    assert not [a for a in api.get("/alerts").json() if a["alert_key"] == "delivery:email"]  # email works again


def test_gives_up_after_five_transient_failures(api, db, smtp):
    _email_on(api)
    smtp.script = ["451 Temporary local problem"] * 5
    raise_alert(db, _alert())
    db.commit()
    t = datetime.now(UTC)
    for _ in range(5):
        delivery.deliver_due(db, t)
        t += timedelta(hours=3)
    d = _deliveries()[0]
    assert d.status == "failed" and d.attempts == 5 and smtp.messages == []


def test_unreachable_server_is_transient(api, db, smtp, monkeypatch):
    _email_on(api)
    monkeypatch.setenv("JOBPILOT_SMTP_PORT", str(_free_port()))  # nothing listens there
    get_settings.cache_clear()
    raise_alert(db, _alert())
    db.commit()
    assert delivery.deliver_due(db)["retrying"] == 1


def test_delivery_claimed_by_a_crashed_worker_is_retried(api, db, smtp):
    _email_on(api)
    n, _ = raise_alert(db, _alert())
    db.commit()
    d = _deliveries()[0]
    with SessionLocal() as s:
        row = s.get(m.NotificationDelivery, d.id)
        row.status, row.claimed_at = "sending", datetime.now(UTC) - timedelta(minutes=20)
        s.commit()
    assert delivery.deliver_due(db)["sent"] == 1


def test_test_email_endpoint(api, smtp):
    r = api.post("/settings/notifications/test-email", key=None)
    assert r.status_code == 200 and r.json()["to"].startswith("ca…@")
    assert "Email notifications from JobPilot Europe work." in smtp.messages[0]
    assert api.get("/settings/notifications").json()["email_configured"] is True


def test_test_email_without_settings_says_what_is_missing(api):
    r = api.post("/settings/notifications/test-email", key=None)
    assert r.status_code == 409 and "JOBPILOT_SMTP_HOST" in r.json()["error"]["message"]


def test_inbox_read_ack_and_resolve_rules(api, db):
    notify(db, "high_fit", "2 new high-fit jobs", dedup_key="high_fit:r")
    mon, _ = raise_alert(db, Finding("mon:queue:down", "critical", "queue", "Queue down", "x", "start redis"))
    past, _ = raise_alert(db, Finding("db-outage:20261018T0100", "warning", "database", "DB was down", "x", "check"))
    db.commit()
    s = api.get("/notifications/summary").json()
    assert s["unread"] == 3 and s["open_alerts"]["critical"] == 1
    a = api.post(f"/alerts/{mon.id}/ack", key=None).json()
    assert a["acknowledged_at"] and a["resolved_at"] is None  # still open until fixed
    r = api.post(f"/alerts/{mon.id}/resolve", key=None)
    assert r.status_code == 409  # the monitor closes it once the problem is gone
    assert api.post(f"/alerts/{past.id}/resolve", key=None).json()["resolved_by"] == "user"
    api.post("/notifications/read-all", key=None)
    assert api.get("/notifications/summary").json()["unread"] == 0
