"use client";

import { Suspense, useState } from "react";
import { useSearchParams } from "next/navigation";
import { api, type Job } from "@/lib/api";
import { REC_LABEL, TRACKS, date, salary } from "@/lib/format";
import { ErrorBox, Loading, Score, StateBadge, errorText, useLoad } from "@/components/ui";

const CRITERIA: Record<string, string> = {
  technical: "Technical skills",
  experience: "Experience level",
  track: "Career track",
  language: "Language fit",
  location: "Location & eligibility",
};

function JobCard({ job, onChange, initiallyOpen }: { job: Job; onChange: (j: Job) => void; initiallyOpen: boolean }) {
  const [open, setOpen] = useState(initiallyOpen);
  const [detail, setDetail] = useState<Job | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const ev = job.evaluation;
  const state = job.application?.state;
  const canDecide = state === "classified";
  const pay = salary(job.salary_min, job.salary_max, job.currency);

  async function decide(d: "approve" | "reject" | "later") {
    setBusy(true); setError(null);
    try { onChange(await api.decide(job.id, d)); } catch (e) { setError(errorText(e)); } finally { setBusy(false); }
  }

  async function toggle() {
    setOpen(!open);
    if (!detail) api.job(job.id).then(setDetail).catch(() => undefined);
  }

  return (
    <article className="card">
      <div className="row" style={{ justifyContent: "space-between", alignItems: "flex-start" }}>
        <div style={{ minWidth: 0, flex: 1 }}>
          <div className="row">
            <strong style={{ fontSize: 16 }}>{job.title}</strong>
            {state && <StateBadge state={state} />}
          </div>
          <div className="small muted">
            {job.company} · {job.location_text ?? job.city ?? "Location unknown"}
            {job.work_mode && job.work_mode !== "onsite" ? ` · ${job.work_mode}` : ""} · posted {date(job.published_at)}
            {pay ? ` · ${pay}` : ""}
          </div>
        </div>
        <div style={{ textAlign: "right" }}>
          <Score value={ev?.score} />
          {ev && <div className="small muted">{REC_LABEL[ev.recommendation]}</div>}
        </div>
      </div>

      {ev && (
        <div style={{ marginTop: 10 }}>
          <div>
            {ev.matched_skills.map((s) => <span key={s} className="chip ok">{s}</span>)}
            {ev.missing_skills.map((s) => <span key={s} className="chip miss" title="Not in your verified skills">{s}</span>)}
          </div>
          {(ev.eligibility.failed.length > 0 || ev.eligibility.uncertain.length > 0) && (
            <div className="warnbox" style={{ marginTop: 8 }}>
              {ev.eligibility.failed.map((w) => <div key={w}>✕ {w}</div>)}
              {ev.eligibility.uncertain.map((w) => <div key={w}>? {w}</div>)}
            </div>
          )}
        </div>
      )}

      <ErrorBox message={error} />
      <div className="row" style={{ marginTop: 12, justifyContent: "space-between" }}>
        <div className="row">
          {canDecide && (
            <>
              <button className="btn primary small" disabled={busy} onClick={() => decide("approve")}>Approve for preparation</button>
              <button className="btn small" disabled={busy} onClick={() => decide("later")}>Later</button>
              <button className="btn small danger" disabled={busy} onClick={() => decide("reject")}>Reject</button>
            </>
          )}
          {job.application?.decision === "later" && <span className="small muted">Kept for later</span>}
        </div>
        <div className="row small">
          <a href={job.url} target="_blank" rel="noopener noreferrer nofollow">Original listing ({job.source_name}) ↗</a>
          <button className="btn small" onClick={toggle}>{open ? "Less" : "Details"}</button>
        </div>
      </div>

      {open && (
        <div style={{ marginTop: 12 }}>
          {ev && (
            <>
              <p className="small" style={{ marginBottom: 8 }}>{ev.explanation}</p>
              <div className="bars" style={{ marginBottom: 12 }}>
                {Object.entries(ev.breakdown).map(([k, v]) => (
                  <div key={k} style={{ display: "contents" }}>
                    <span>{CRITERIA[k] ?? k}</span>
                    <div className="bar"><i style={{ width: `${(v / (ev.weights[k] || 1)) * 100}%` }} /></div>
                    <span className="mono">{v}/{ev.weights[k]}</span>
                  </div>
                ))}
              </div>
              <p className="small muted">Track {ev.track} ({TRACKS[ev.track] ?? ev.track}) · {ev.seniority} · model {ev.model_version}</p>
            </>
          )}
          <div className="sep" />
          <div className="small muted" style={{ marginBottom: 4 }}>Job description (from the source, shown as-is)</div>
          <p className="small" style={{ whiteSpace: "pre-wrap" }}>{detail?.description_text ?? "Loading…"}</p>
        </div>
      )}
    </article>
  );
}

function JobsInner() {
  const params = useSearchParams();
  const focus = params.get("focus");
  const [q, setQ] = useState("");
  const [track, setTrack] = useState("");
  const [minScore, setMinScore] = useState(params.get("min_score") ?? "");
  const [state, setState] = useState("classified");
  const { data, error, loading, setData } = useLoad(
    () => api.jobs({ q, track: track || undefined, min_score: minScore ? Number(minScore) : undefined, state: state || undefined }),
    [q, track, minScore, state],
  );

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Job Review</h1>
          <p className="sub">Sorted by fit. Approving a job only starts preparation; nothing is ever submitted without your final approval.</p>
        </div>
      </div>
      <div className="card form-grid" style={{ marginBottom: 16, gridTemplateColumns: "2fr 1fr 1fr 1fr" }}>
        <label>Search<input placeholder="Company, title or city" value={q} onChange={(e) => setQ(e.target.value)} /></label>
        <label>Status
          <select value={state} onChange={(e) => setState(e.target.value)}>
            <option value="classified">To review</option>
            <option value="approved_for_preparation">Approved for prep</option>
            <option value="rejected">Rejected</option>
            <option value="">All</option>
          </select>
        </label>
        <label>Track
          <select value={track} onChange={(e) => setTrack(e.target.value)}>
            <option value="">All</option>
            {Object.entries(TRACKS).map(([k, l]) => <option key={k} value={k}>{k} · {l}</option>)}
          </select>
        </label>
        <label>Minimum score<input type="number" min={0} max={100} value={minScore} onChange={(e) => setMinScore(e.target.value)} /></label>
      </div>
      <p className="notice small" style={{ marginBottom: 16 }}>
        Scores come from the rule-based model <span className="mono">rules-v0</span> using only verified profile facts. Claude-based matching replaces the judgment parts in Phase 2.
      </p>
      <ErrorBox message={error} />
      {loading && !data ? <Loading /> : null}
      {data && (
        <div className="list">
          <p className="small muted">{data.total} job{data.total === 1 ? "" : "s"}</p>
          {data.items.map((j) => (
            <JobCard key={j.id} job={j} initiallyOpen={j.id === focus}
              onChange={(nj) => setData({ ...data, items: data.items.map((x) => (x.id === nj.id ? nj : x)) })} />
          ))}
          {data.total === 0 && <p className="notice">No jobs match. Run a search from Job Discovery.</p>}
        </div>
      )}
    </>
  );
}

export default function JobsPage() {
  return <Suspense fallback={<Loading />}><JobsInner /></Suspense>;
}
