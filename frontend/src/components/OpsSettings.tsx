"use client";

import { useState } from "react";
import { api } from "@/lib/api";
import { dateTime } from "@/lib/format";
import { ErrorBox, Loading, errorText, useLoad } from "@/components/ui";

const usd = (n: number) => `$${n.toFixed(n < 1 ? 3 : 2)}`;
const STATE_LABEL: Record<string, string> = {
  classified: "To review", approved_for_preparation: "Approved", documents_ready: "Documents ready",
  awaiting_user_review: "Awaiting approval", submitted: "Submitted", follow_up: "Follow-up", closed: "Closed",
  rejected: "Rejected", withdrawn: "Withdrawn", expired: "Expired", needs_manual_input: "Needs you", failed: "Failed",
};

export function AccountSettings() {
  const [cur, setCur] = useState("");
  const [next, setNext] = useState("");
  const [again, setAgain] = useState("");
  const [msg, setMsg] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function save() {
    setErr(null); setMsg(null);
    if (next !== again) { setErr("The new passwords do not match"); return; }
    setBusy(true);
    try {
      await api.changePassword(cur, next);
      setCur(""); setNext(""); setAgain("");
      setMsg("Password changed. Other devices are signed out.");
    } catch (e) { setErr(errorText(e)); } finally { setBusy(false); }
  }

  return (
    <section className="card" style={{ marginBottom: 16 }}>
      <h2>Account</h2>
      <div className="form-grid">
        <label>Current password<input type="password" autoComplete="current-password" value={cur} onChange={(e) => setCur(e.target.value)} /></label>
        <label>New password (12+ characters)<input type="password" autoComplete="new-password" value={next} onChange={(e) => setNext(e.target.value)} /></label>
        <label>New password again<input type="password" autoComplete="new-password" value={again} onChange={(e) => setAgain(e.target.value)} /></label>
      </div>
      <div className="row" style={{ marginTop: 10 }}>
        <button className="btn primary" disabled={busy || !cur || next.length < 12} onClick={save}>Change password</button>
        {msg && <span className="small muted">{msg}</span>}
      </div>
      <ErrorBox message={err} />
      <p className="small muted" style={{ marginTop: 8 }}>
        Signing out ends your session on every device. After 5 wrong passwords, sign-in pauses for 15 minutes.
      </p>
    </section>
  );
}

export function UsageCard() {
  const [days, setDays] = useState(30);
  const { data, error } = useLoad(() => api.usage(days), [days]);
  if (!data) return error ? <ErrorBox message={error} /> : <Loading />;
  const ai = data.ai;
  const funnel = Object.entries(data.applications.funnel).filter(([, n]) => n > 0);
  return (
    <section className="card" style={{ marginBottom: 16 }}>
      <div className="row" style={{ justifyContent: "space-between" }}>
        <h2 style={{ margin: 0 }}>Usage and cost</h2>
        <select aria-label="Period" value={days} onChange={(e) => setDays(Number(e.target.value))} style={{ width: "auto" }}>
          <option value={7}>Last 7 days</option><option value={30}>Last 30 days</option><option value={90}>Last 90 days</option>
        </select>
      </div>
      <div className="grid tiles" style={{ margin: "12px 0" }}>
        <div className="card tile"><div className="n">{usd(ai.today_cost_usd)}</div>
          <div className="l">Claude today, of {usd(ai.daily_budget_usd)} budget{ai.budget_used_pct !== null ? ` (${ai.budget_used_pct}%)` : ""}</div></div>
        <div className="card tile"><div className="n">{usd(ai.month_cost_usd)}</div><div className="l">Claude this month</div></div>
        <div className="card tile"><div className="n">{Object.values(data.searches.runs).reduce((a, b) => a + b, 0)}</div>
          <div className="l">Searches ({data.searches.runs.failed ?? 0} failed)</div></div>
        <div className="card tile"><div className="n">{data.searches.new_jobs}</div><div className="l">Jobs found</div></div>
        <div className="card tile"><div className="n">{data.applications.submitted_in_period}</div><div className="l">Applications sent</div></div>
      </div>
      {!ai.api_key_configured && <p className="small muted">No Claude API key is set, so nothing is spent; rule-based matching and the template writer are used.</p>}
      {ai.per_agent.length > 0 && (
        <div className="table-wrap" style={{ marginBottom: 10 }}>
          <table className="small">
            <thead><tr><th>Used for</th><th>Calls</th><th>Tokens in / out</th><th>Cost</th></tr></thead>
            <tbody>
              {ai.per_agent.map((a) => (
                <tr key={a.agent}><td>{a.agent === "matching" ? "Job matching" : a.agent === "documents" ? "CV and letter writing" : a.agent}</td>
                  <td>{a.calls}</td><td>{a.tokens_in.toLocaleString()} / {a.tokens_out.toLocaleString()}</td><td>{usd(a.cost_usd)}</td></tr>
              ))}
              <tr><td><strong>Total</strong></td><td /><td /><td><strong>{usd(ai.total_cost_usd)}</strong></td></tr>
            </tbody>
          </table>
        </div>
      )}
      {funnel.length > 0 && (
        <p className="small"><span className="muted">Applications now: </span>
          {funnel.map(([s, n]) => `${STATE_LABEL[s] ?? s} ${n}`).join(" · ")}</p>
      )}
    </section>
  );
}

export function BackupCard() {
  const { data, error, reload } = useLoad(api.backups);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  if (!data) return error ? <ErrorBox message={error} /> : <Loading />;
  const kb = (b: number | null) => (b === null ? "" : b > 1 << 20 ? `${(b / (1 << 20)).toFixed(1)} MB` : `${Math.round(b / 1024)} KB`);
  return (
    <section className="card" style={{ marginBottom: 16 }}>
      <h2>Backups</h2>
      <p className="small" style={{ marginTop: 0 }}>
        {data.schedule} · newest {data.keep} kept ·{" "}
        {data.last_ok ? <>last good backup {dateTime(data.last_ok.started_at)} ({kb(data.last_ok.size_bytes)})</> :
          <span className="badge warn">no backup yet</span>}
      </p>
      <div className="row">
        <button className="btn" disabled={busy} onClick={async () => {
          setBusy(true); setErr(null);
          try { await api.backupNow(); reload(); } catch (e) { setErr(errorText(e)); } finally { setBusy(false); }
        }}>{busy ? "Backing up…" : "Back up now"}</button>
        <span className="small muted">Database and all generated documents, with checksums. Copy the backup folder off the server too.</span>
      </div>
      <ErrorBox message={err} />
      {data.history.length > 0 && (
        <details className="small" style={{ marginTop: 8 }}>
          <summary>History</summary>
          <div className="list" style={{ marginTop: 6 }}>
            {data.history.map((b) => (
              <div key={b.name}>
                <span className={`badge ${b.status === "ok" || b.status === "verified" ? "good" : b.status === "running" ? "accent" : "bad"}`}>{b.status}</span>{" "}
                {dateTime(b.started_at)} · {b.kind.replace("_", " ")} · {kb(b.size_bytes)}
                {typeof b.detail.error === "string" && <div className="muted">{b.detail.error as string}</div>}
              </div>
            ))}
          </div>
        </details>
      )}
      <p className="small muted" style={{ marginTop: 8 }}>{data.restore_hint}</p>
    </section>
  );
}
