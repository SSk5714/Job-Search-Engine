"use client";

import { useEffect, useState } from "react";
import { api, type NotificationPrefs } from "@/lib/api";
import { ErrorBox, Loading, errorText, useLoad } from "@/components/ui";

const KIND_LABEL: Record<string, string> = {
  alert: "System alerts", high_fit: "New high-fit jobs", ready_for_review: "Ready for your approval",
  submitted: "Submission confirmed", follow_up: "Follow-up reminders",
};

export function NotificationSettings() {
  const { data, error } = useLoad(api.notificationPrefs);
  const [p, setP] = useState<NotificationPrefs | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => { if (data) setP(data); }, [data]);
  if (!p) return error ? <ErrorBox message={error} /> : <Loading />;

  async function run(fn: () => Promise<string>) {
    setBusy(true); setErr(null); setMsg(null);
    try { setMsg(await fn()); } catch (e) { setErr(errorText(e)); } finally { setBusy(false); }
  }
  const toggle = (k: string) => setP({ ...p, email_kinds: p.email_kinds.includes(k) ? p.email_kinds.filter((x) => x !== k) : [...p.email_kinds, k] });

  return (
    <section className="card" style={{ marginBottom: 16 }}>
      <h2>Notifications</h2>
      <p className="small muted" style={{ marginTop: 0 }}>
        In-app notifications are always on. Only useful events notify you: new high-fit jobs (one summary per search),
        applications ready for approval, confirmed submissions, follow-ups and system alerts.
      </p>
      <div className="form-grid">
        <label>Notify about new jobs scoring at least
          <input type="number" min={0} max={100} value={p.high_fit_min_score}
            onChange={(e) => setP({ ...p, high_fit_min_score: Number(e.target.value) })} />
        </label>
        <label>Remind me of follow-ups this many days ahead
          <input type="number" min={0} max={14} value={p.follow_up_lead_days}
            onChange={(e) => setP({ ...p, follow_up_lead_days: Number(e.target.value) })} />
        </label>
      </div>
      <div className="sep" />
      {!p.email_configured ? (
        <p className="notice small">
          Email is not set up on the server. To add it, set <span className="mono">JOBPILOT_SMTP_HOST</span>,{" "}
          <span className="mono">JOBPILOT_SMTP_USERNAME</span>/<span className="mono">PASSWORD</span>,{" "}
          <span className="mono">JOBPILOT_EMAIL_FROM</span> and <span className="mono">JOBPILOT_NOTIFY_EMAIL_TO</span>, then restart.
        </p>
      ) : (
        <>
          <label className="row" style={{ display: "flex" }}>
            <input type="checkbox" style={{ width: "auto" }} checked={p.email_enabled}
              onChange={(e) => setP({ ...p, email_enabled: e.target.checked })} />
            Also email me at {p.email_to_hint}
          </label>
          {p.email_enabled && (
            <div style={{ margin: "8px 0 0 24px" }}>
              <div className="row small">
                {(p.kinds ?? Object.keys(KIND_LABEL)).map((k) => (
                  <label key={k} className="row" style={{ display: "flex" }}>
                    <input type="checkbox" style={{ width: "auto" }} checked={p.email_kinds.includes(k)} onChange={() => toggle(k)} />
                    {KIND_LABEL[k] ?? k}
                  </label>
                ))}
              </div>
              <label className="small" style={{ maxWidth: 280, marginTop: 6 }}>Email alerts from severity
                <select value={p.email_alert_min_severity}
                  onChange={(e) => setP({ ...p, email_alert_min_severity: e.target.value as NotificationPrefs["email_alert_min_severity"] })}>
                  <option value="critical">Critical only</option><option value="warning">Warning and critical</option>
                  <option value="info">Everything</option>
                </select>
              </label>
            </div>
          )}
        </>
      )}
      <div className="row" style={{ marginTop: 12 }}>
        <button className="btn primary" disabled={busy}
          onClick={() => run(async () => { setP(await api.saveNotificationPrefs(p)); return "Saved"; })}>Save</button>
        {p.email_configured && (
          <button className="btn" disabled={busy}
            onClick={() => run(async () => `Test email sent to ${(await api.testEmail()).to}`)}>Send test email</button>
        )}
        {msg && <span className="small muted">{msg}</span>}
      </div>
      <ErrorBox message={err} />
    </section>
  );
}
