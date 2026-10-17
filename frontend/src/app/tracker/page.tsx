"use client";

import { Suspense, useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import { api, type ApplicationDetail, type State } from "@/lib/api";
import { STATE_LABEL, date, dateTime } from "@/lib/format";
import { ErrorBox, Loading, Score, StateBadge, errorText, useLoad } from "@/components/ui";

const USER_MOVES: Partial<Record<State, string>> = {
  withdrawn: "Withdraw",
  rejected: "Reject",
  closed: "Close",
  approved_for_preparation: "Approve for preparation",
};

function Drawer({ id, onClose, onChanged }: { id: string; onClose: () => void; onChanged: () => void }) {
  const [d, setD] = useState<ApplicationDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [followUp, setFollowUp] = useState("");
  const [outcome, setOutcome] = useState("");

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  useEffect(() => {
    api.application(id).then((x) => {
      setD(x); setFollowUp(x.next_follow_up ?? ""); setOutcome(x.outcome ?? "");
    }).catch((e) => setError(errorText(e)));
  }, [id]);

  async function saveTracking() {
    try {
      setD(await api.track(id, { next_follow_up: followUp || null, outcome: outcome || null }));
      onChanged();
    } catch (e) { setError(errorText(e)); }
  }

  async function move(to: State) {
    if (!d) return;
    if (to === "withdrawn" && !confirm("Withdraw this application?")) return;
    try {
      setD(await api.transition(id, to, undefined, d.state_version));
      onChanged();
    } catch (e) { setError(errorText(e)); }
  }

  return (
    <>
      <div className="scrim" onClick={onClose} />
      <aside className="drawer" aria-label="Application history">
        <div className="row" style={{ justifyContent: "space-between" }}>
          <h2 style={{ margin: 0 }}>{d ? d.role : "Loading…"}</h2>
          <button className="btn small" onClick={onClose}>Close</button>
        </div>
        <ErrorBox message={error} />
        {d && (
          <>
            <p className="small muted">{d.company} · {d.city ?? ""} {d.country ?? ""} · <a href={d.source_url} target="_blank" rel="noopener noreferrer nofollow">listing ↗</a></p>
            <div className="row" style={{ margin: "12px 0" }}><StateBadge state={d.state} /><Score value={d.score} /></div>

            <div className="form-grid" style={{ gridTemplateColumns: "1fr 1fr" }}>
              <label>Next follow-up<input type="date" value={followUp} onChange={(e) => setFollowUp(e.target.value)} /></label>
              <label>Outcome<input value={outcome} placeholder="e.g. interview, offer, no reply" onChange={(e) => setOutcome(e.target.value)} /></label>
            </div>
            <button className="btn small" style={{ marginTop: 8 }} onClick={saveTracking}>Save tracking</button>

            {d.allowed_transitions.some((t) => USER_MOVES[t]) && (
              <>
                <div className="sep" />
                <div className="row">
                  {d.allowed_transitions.filter((t) => USER_MOVES[t]).map((t) => (
                    <button key={t} className={`btn small${t === "withdrawn" || t === "rejected" ? " danger" : ""}`} onClick={() => move(t)}>{USER_MOVES[t]}</button>
                  ))}
                </div>
              </>
            )}

            <div className="sep" />
            <h2>History</h2>
            <ul className="timeline">
              {d.history.map((h, i) => (
                <li key={i}>
                  <span className="muted">{dateTime(h.at)}</span>
                  <span>{STATE_LABEL[h.to_state]} <span className="muted">by {h.actor}{h.reason ? ` — ${h.reason}` : ""}</span></span>
                </li>
              ))}
            </ul>
          </>
        )}
      </aside>
    </>
  );
}

function TrackerInner() {
  const params = useSearchParams();
  const [state, setState] = useState(params.get("state") ?? "");
  const [q, setQ] = useState("");
  const [country, setCountry] = useState("");
  const [all, setAll] = useState(false);
  const [open, setOpen] = useState<string | null>(null);
  const { data, error, loading, reload } = useLoad(
    () => api.applications({ state: state || undefined, q, country: country || undefined, include_unreviewed: all }),
    [state, q, country, all],
  );

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Application Tracker</h1>
          <p className="sub">Every application with its full history. Jobs you have not decided on stay in Job Review unless you include them.</p>
        </div>
        <a className="btn" href={api.exportCsvUrl}>Export CSV</a>
      </div>
      <div className="card form-grid" style={{ marginBottom: 16, gridTemplateColumns: "2fr 1fr 1fr 1fr" }}>
        <label>Search<input placeholder="Company or role" value={q} onChange={(e) => setQ(e.target.value)} /></label>
        <label>Status
          <select value={state} onChange={(e) => setState(e.target.value)}>
            <option value="">All decided</option>
            {Object.entries(STATE_LABEL).map(([k, l]) => <option key={k} value={k}>{l}</option>)}
          </select>
        </label>
        <label>Country<input placeholder="DE" value={country} onChange={(e) => setCountry(e.target.value.toUpperCase())} /></label>
        <label className="row" style={{ display: "flex", alignSelf: "end", color: "var(--ink)" }}>
          <input type="checkbox" style={{ width: "auto" }} checked={all} onChange={(e) => setAll(e.target.checked)} /> Include undecided
        </label>
      </div>
      <ErrorBox message={error} />
      {loading && !data ? <Loading /> : null}
      {data && (
        <div className="card table-wrap" style={{ padding: 0 }}>
          <table>
            <thead>
              <tr><th>Company</th><th>Role</th><th>Country</th><th>Score</th><th>Applied</th><th>Status</th><th>Last action</th><th>Follow-up</th><th>Outcome</th></tr>
            </thead>
            <tbody>
              {data.map((r) => (
                <tr key={r.id} className="click" onClick={() => setOpen(r.id)}>
                  <td>{r.company}</td>
                  <td>{r.role}</td>
                  <td>{r.country ?? "—"}</td>
                  <td><Score value={r.score} /></td>
                  <td>{date(r.applied_on)}</td>
                  <td><StateBadge state={r.state} /></td>
                  <td className="small muted">{r.last_action ?? "—"}</td>
                  <td>{date(r.next_follow_up)}</td>
                  <td>{r.outcome ?? "—"}</td>
                </tr>
              ))}
              {data.length === 0 && <tr><td colSpan={9} className="muted">No applications yet. Approve or reject jobs in Job Review.</td></tr>}
            </tbody>
          </table>
        </div>
      )}
      {open && <Drawer id={open} onClose={() => setOpen(null)} onChanged={reload} />}
    </>
  );
}

export default function TrackerPage() {
  return <Suspense fallback={<Loading />}><TrackerInner /></Suspense>;
}
