"""Email delivery with safe retries.

Each delivery is claimed (`sending`) and committed before the SMTP call, so two workers never
send the same row. Transient failures (connection problems, 4xx replies) back off and retry;
permanent ones (5xx, rejected login) fail at once. A row stuck in `sending` (worker died
mid-send) is retried after 10 minutes; the Message-ID is fixed per delivery, so a rare
duplicate is recognisable as the same message.
"""

from __future__ import annotations

import logging
import smtplib
import socket
import ssl
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from email.message import EmailMessage

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from jobpilot.config import get_settings
from jobpilot.db import models as m
from jobpilot.notify import Finding, raise_alert, resolve_alert

log = logging.getLogger("jobpilot.notify.delivery")

BACKOFF_S = [60, 300, 1800, 7200]  # then give up: 5 attempts in about 2.5 hours
MAX_ATTEMPTS = len(BACKOFF_S) + 1
CLAIM_TIMEOUT = timedelta(minutes=10)


class TransientError(Exception):
    pass


class PermanentError(Exception):
    pass


def build_message(n: m.Notification, delivery_id) -> EmailMessage:
    s = get_settings()
    msg = EmailMessage()
    prefix = {"critical": "[JobPilot ALERT]", "warning": "[JobPilot warning]"}.get(n.severity, "[JobPilot]")
    msg["Subject"] = f"{prefix} {n.title}"
    msg["From"] = s.email_from
    msg["To"] = s.notify_email_to
    msg["Message-ID"] = f"<delivery-{delivery_id}@jobpilot.local>"
    lines = [n.title, "", n.body or ""]
    if n.kind == "alert":
        lines += ["", f"Severity: {n.severity}", f"Component: {n.component or '-'}",
                  f"Detected: {n.created_at:%Y-%m-%d %H:%M UTC}" if n.created_at else ""]
        if n.run_id:
            lines.append(f"Run: {n.run_id}")
        if n.task_id:
            lines.append(f"Task: {n.task_id}")
        if n.likely_cause:
            lines.append(f"Likely cause: {n.likely_cause}")
        lines.append(f"What to do: {n.remediation or '-'}")
        lines.append("Workflow paused: " + ("yes" if n.workflow_paused else "no"))
    if n.link:
        lines += ["", f"Open: {s.public_base_url.rstrip('/')}{n.link}"]
    lines += ["", "— JobPilot Europe (change what you receive in Settings & Health)"]
    msg.set_content("\n".join(x for x in lines if x is not None))
    return msg


def smtp_send(msg: EmailMessage) -> None:
    s = get_settings()
    try:
        if s.smtp_ssl:
            client = smtplib.SMTP_SSL(s.smtp_host, s.smtp_port, timeout=s.smtp_timeout_s,
                                      context=ssl.create_default_context())
        else:
            client = smtplib.SMTP(s.smtp_host, s.smtp_port, timeout=s.smtp_timeout_s)
        with client:
            if s.smtp_starttls and not s.smtp_ssl:
                client.starttls(context=ssl.create_default_context())
            if s.smtp_username:
                client.login(s.smtp_username, s.smtp_password or "")
            client.send_message(msg)
    except smtplib.SMTPAuthenticationError as e:
        raise PermanentError(f"SMTP login rejected ({e.smtp_code})") from e
    except smtplib.SMTPRecipientsRefused as e:
        raise PermanentError("Recipient address refused") from e
    except smtplib.SMTPResponseException as e:
        if 400 <= e.smtp_code < 500:
            raise TransientError(f"SMTP {e.smtp_code}: {e.smtp_error!r}"[:300]) from e
        raise PermanentError(f"SMTP {e.smtp_code}: {e.smtp_error!r}"[:300]) from e
    except smtplib.SMTPNotSupportedError as e:
        raise PermanentError(f"SMTP server does not support this: {e}"[:300]) from e
    except (smtplib.SMTPServerDisconnected, smtplib.SMTPConnectError, ConnectionError, socket.timeout,
            TimeoutError, OSError) as e:
        raise TransientError(f"{type(e).__name__}: {e}"[:300]) from e


Sender = Callable[[EmailMessage], None]


def deliver_due(db: Session, now: datetime | None = None, sender: Sender | None = None, limit: int = 20) -> dict:
    """Send due email deliveries. Commits per delivery. Returns counts."""
    now = now or datetime.now(UTC)
    sender = sender or smtp_send
    counts = {"sent": 0, "retrying": 0, "failed": 0}
    rows = db.scalars(
        select(m.NotificationDelivery)
        .where(or_(m.NotificationDelivery.status == "pending",
                   (m.NotificationDelivery.status == "sending") & (m.NotificationDelivery.claimed_at < now - CLAIM_TIMEOUT)),
               m.NotificationDelivery.next_attempt_at <= now)
        .order_by(m.NotificationDelivery.next_attempt_at).limit(limit).with_for_update(skip_locked=True)).all()
    for d in rows:
        d.status, d.claimed_at, d.attempts = "sending", now, d.attempts + 1
    db.commit()
    for d in rows:
        n = db.get(m.Notification, d.notification_id)
        try:
            if not get_settings().email_configured:
                raise PermanentError("Email is not configured on the server")
            sender(build_message(n, d.id))
        except TransientError as e:
            d.last_error = str(e)
            if d.attempts >= MAX_ATTEMPTS:
                _give_up(db, d, n)
                counts["failed"] += 1
            else:
                d.status, d.next_attempt_at = "pending", now + timedelta(seconds=BACKOFF_S[d.attempts - 1])
                counts["retrying"] += 1
        except PermanentError as e:
            d.last_error = str(e)
            _give_up(db, d, n)
            counts["failed"] += 1
        except Exception as e:  # unexpected: treat as transient, but never loop forever
            d.last_error = f"{type(e).__name__}: {e}"[:300]
            if d.attempts >= MAX_ATTEMPTS:
                _give_up(db, d, n)
                counts["failed"] += 1
            else:
                d.status, d.next_attempt_at = "pending", now + timedelta(seconds=BACKOFF_S[d.attempts - 1])
                counts["retrying"] += 1
        else:
            d.status, d.sent_at, d.last_error = "sent", datetime.now(UTC), None
            counts["sent"] += 1
            resolve_alert(db, "delivery:email")  # email works again
        db.commit()
    return counts


def _give_up(db: Session, d: m.NotificationDelivery, n: m.Notification) -> None:
    d.status = "failed"
    log.error("email delivery %s failed for good: %s", d.id, d.last_error)
    raise_alert(db, Finding(
        key="delivery:email", severity="warning", component="notifications",
        title="Email notifications are failing",
        summary=f"Could not email “{n.title}” after {d.attempts} attempt(s): {d.last_error}",
        likely_cause="SMTP settings, credentials or the mail server" if "login" in (d.last_error or "").lower()
        or "configured" in (d.last_error or "") else "The mail server is unreachable or refused the message",
        remediation="Check JOBPILOT_SMTP_* settings, send a test email from Settings & Health, then press Retry "
                    "on the failed notification. In-app notifications are unaffected.",
        task_id=d.id, link="/notifications"), email=False)


def retry(db: Session, notification_id) -> int:
    """User-triggered retry of failed email deliveries for one notification."""
    rows = db.scalars(select(m.NotificationDelivery).where(m.NotificationDelivery.notification_id == notification_id,
                                                           m.NotificationDelivery.status == "failed")).all()
    for d in rows:
        d.status, d.next_attempt_at, d.attempts, d.last_error = "pending", datetime.now(UTC), 0, None
    db.flush()
    return len(rows)
