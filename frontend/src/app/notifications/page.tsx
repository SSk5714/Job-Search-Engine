"use client";

import Link from "next/link";
import { useState } from "react";
import { api, type NotificationT } from "@/lib/api";
import { dateTime } from "@/lib/format";
import { ErrorBox, Loading, errorText, useLoad } from "@/components/ui";

const TONE = { critical: "bad", warning: "warn", info: "accent" } as const;
const KIND_LABEL: Record<string, string> = {
  alert: "Alert", high_fit: "New matches", ready_for_review: "Ready for approval", submitted: "Submitted",
  follow_up: "Follow-up",
};

function AlertCard({ n, onChange }: { n: NotificationT; onChange: () => void }) {
  const [open, setOpen] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const resolved = !!n.resolved_at;
  const failedMail = n.deliveries.find((d) => d.status === "failed");

  async function act(fn: () => Promise<unknown>) {
    setError(null);
    try { await fn(); onChange(); } catch (e) { setError(errorText(e)); }
  }

  return (
    <article className="card" style={{ marginBottom: 10, opacity: resolved ? 0.7 : 1,
      borderLeft: `4px solid var(--${resolved ? "line" : n.severity === "critical" ? "bad" : n.severity === "warning" ? "warn" : "accent"})` }}>
      <div className="row" style={{ justifyContent: "space-between", alignItems: "flex-start" }}>
        <div>
          <div className="row">
            <span className={`badge ${resolved ? "good" : TONE[n.severity]}`}>{resolved ? "Resolved" : n.severity}</span>
            {n.kind !== "alert" && <span className="badge">{KIND_LABEL[n.kind]}</span>}
            {n.workflow_paused && !resolved && <span className="badge warn">workflow paused</span>}
            {!n.read_at && !resolved && <span className="badge accent">new</span>}
            <strong>{n.title}</strong>
          </div>
          <div className="small muted" style={{ marginTop: 2 }}>
            {n.component && <>{n.component} · </>}detected {dateTime(n.created_at)}
            {n.occurrences > 1 && <> · seen {n.occurrences}× (last {dateTime(n.last_seen_at ?? n.created_at)})</>}
            {resolved && <> · resolved {dateTime(n.resolved_at!)} {n.resolved_by === "monitor" ? "(problem gone)" : "by you"}</>}
          </div>
        </div>
        <div className="row">
          {n.link && <Link className="btn small" href={n.link} onClick={() => api.markRead(n.id).catch(() => undefined)}>Open</Link>}
          {n.kind === "alert" && !resolved && !n.acknowledged_at && (
            <button className="btn small" onClick={() => act(() => api.ackAlert(n.id))}>Got it</button>
          )}
          {n.kind !== "alert" && !n.read_at && (
            <button className="btn small" onClick={() => act(() => api.markRead(n.id))}>Mark read</button>
          )}
          {n.can_resolve && <button className="btn small" onClick={() => act(() => api.resolveAlert(n.id))}>Resolve</button>}
        </div>
      </div>
      {n.body && <p className="small" style={{ whiteSpace: "pre-line", margin: "8px 0 0" }}>{n.body}</p>}
      {n.kind === "alert" && (
        <div className="small" style={{ marginTop: 6 }}>
          {n.likely_cause && <div><span className="muted">Likely cause:</span> {n.likely_cause}</div>}
          {n.remediation && <div><span className="muted">What to do:</span> {n.remediation}</div>}
          {n.kind === "alert" && !resolved && n.acknowledged_at && (
            <div className="muted">You acknowledged this {dateTime(n.acknowledged_at)}. It closes once the problem is gone.</div>
          )}
        </div>
      )}
      {failedMail && (
        <div className="warnbox small" style={{ marginTop: 8 }}>
          Email not delivered: {failedMail.last_error}{" "}
          <button className="btn small" onClick={() => act(() => api.retryDelivery(n.id))}>Retry email</button>
        </div>
      )}
      {(n.run_id || n.task_id || Object.keys(n.context).length > 0) && (
        <>
          <button className="btn small" style={{ marginTop: 6 }} onClick={() => setOpen(!open)}>{open ? "Hide" : "Technical"} details</button>
          {open && (
            <pre className="small mono" style={{ whiteSpace: "pre-wrap", margin: "6px 0 0" }}>
              {JSON.stringify({ alert: n.alert_key, run_id: n.run_id, task_id: n.task_id, ...n.context }, null, 2)}
            </pre>
          )}
        </>
      )}
      <ErrorBox message={error} />
    </article>
  );
}

export default function NotificationsPage() {
  const [tab, setTab] = useState<"open" | "updates" | "all">("open");
  const { data, error, reload } = useLoad(
    () => tab === "open" ? api.notifications("alerts", "open") : api.notifications(tab === "updates" ? "updates" : "all"),
    [tab]);

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Notifications</h1>
          <p className="sub">Alerts from the system monitor and updates about your applications. Low-level errors stay in Settings & Health.</p>
        </div>
        <button className="btn" onClick={async () => { await api.readAll(); reload(); }}>Mark all read</button>
      </div>
      <div className="row" style={{ marginBottom: 12 }} role="tablist">
        {([["open", "Open alerts"], ["updates", "Updates"], ["all", "Everything"]] as const).map(([k, label]) => (
          <button key={k} role="tab" aria-selected={tab === k} className={`btn small${tab === k ? " primary" : ""}`}
            onClick={() => setTab(k)}>{label}</button>
        ))}
      </div>
      <ErrorBox message={error} />
      {!data ? <Loading /> : data.length === 0 ? (
        <p className="notice">{tab === "open" ? "No open alerts. Everything the monitor checks looks healthy." : "Nothing yet."}</p>
      ) : data.map((n) => <AlertCard key={`${n.id}-${n.read_at}-${n.acknowledged_at}-${n.resolved_at}`} n={n} onChange={reload} />)}
    </>
  );
}
