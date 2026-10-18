"use client";

import Link from "next/link";
import { useState } from "react";
import { api, type MyJob } from "@/lib/api";
import { date } from "@/lib/format";
import { ErrorBox, Loading, Score, errorText, useLoad } from "@/components/ui";
import { ImportJob } from "@/components/ImportJob";

function DocLinks({ job }: { job: MyJob }) {
  const docs = job.documents;
  const cv = docs.cv, letter = docs.cover_letter;
  if (!cv || !letter) return null;
  const problems = (cv.problem_count ?? 0) + (letter.problem_count ?? 0);
  return (
    <>
      <a className="btn" href={api.docUrl(job.application_id, cv.id, "pdf")}>CV (PDF)</a>
      <a className="btn" href={api.docUrl(job.application_id, letter.id, "pdf")}>Cover letter (PDF)</a>
      <span className="small muted">
        Word: <a href={api.docUrl(job.application_id, cv.id, "docx")}>CV</a> ·{" "}
        <a href={api.docUrl(job.application_id, letter.id, "docx")}>letter</a> ·{" "}
        <Link href={`/review?id=${job.application_id}`}>edit</Link>
      </span>
      {problems > 0 && (
        <div className="warnbox small" style={{ width: "100%" }}>
          {problems} line{problems > 1 ? "s are" : " is"} not backed by your verified profile
          {[...(cv.problems ?? []), ...(letter.problems ?? [])].slice(0, 2).map((p) => <div key={p}>· {p}</div>)}
          <div>Check your <Link href="/settings">profile</Link> (press Verify), then <b>Recreate</b>.</div>
        </div>
      )}
    </>
  );
}

function JobCard({ job, onChange, onGone }: { job: MyJob; onChange: (j: MyJob) => void; onGone: () => void }) {
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [open, setOpen] = useState(false);
  const hasDocs = !!(job.documents.cv && job.documents.cover_letter);

  async function act(name: string, fn: () => Promise<unknown>) {
    setBusy(name); setError(null);
    try { await fn(); } catch (e) { setError(errorText(e)); } finally { setBusy(null); }
  }

  return (
    <article className="card" style={{ marginBottom: 12 }}>
      <div className="row" style={{ justifyContent: "space-between", alignItems: "flex-start", flexWrap: "nowrap" }}>
        <div>
          <h2 style={{ margin: 0, fontSize: 18 }}>{job.title}</h2>
          <div className="small muted">
            {job.company}{job.city ? ` · ${job.city}` : ""}{job.work_mode ? ` · ${job.work_mode}` : ""}
            {job.posted ? ` · posted ${date(job.posted)}` : ""} · {job.source}
          </div>
        </div>
        <Score value={job.score} />
      </div>

      {job.summary && (
        <p className="small" style={{ margin: "8px 0 6px" }}>
          {open ? job.summary : job.summary.slice(0, 220)}{job.summary.length > 220 && !open && "…"}{" "}
          {job.summary.length > 220 && <button className="btn small" onClick={() => setOpen(!open)}>{open ? "less" : "more"}</button>}
        </p>
      )}
      <div className="small" style={{ marginBottom: 6 }}>
        {job.matched.map((s) => <span key={s} className="chip ok">{s}</span>)}
        {job.missing.slice(0, 3).map((s) => <span key={s} className="chip miss">{s}</span>)}
      </div>
      {job.warnings.length > 0 && <div className="small" style={{ color: "var(--warn)", marginBottom: 6 }}>⚠ {job.warnings.join(" · ")}</div>}

      <div className="row" style={{ marginTop: 8 }}>
        <a className="btn" href={job.url} target="_blank" rel="noopener noreferrer nofollow">Job listing ↗</a>
        {hasDocs ? <DocLinks job={job} /> : null}
        <button className="btn" disabled={!!busy}
          onClick={() => act("docs", async () => onChange(await api.makeDocuments(job.application_id)))}>
          {busy === "docs" ? "Writing…" : hasDocs ? "Recreate CV & letter" : "Create CV & cover letter"}
        </button>
        <a className="btn primary" href={job.url} target="_blank" rel="noopener noreferrer nofollow"
          title="Opens the listing; apply there with your CV and cover letter">Apply ↗</a>
        <button className="btn" disabled={!!busy} onClick={() => {
          if (confirm(`Did you apply to ${job.company}? It moves to “Applied” with a reminder to follow up.`)) {
            act("applied", async () => { await api.markApplied(job.application_id); onGone(); });
          }
        }}>I applied ✓</button>
        <button className="btn small" disabled={!!busy}
          onClick={() => act("dismiss", async () => { await api.dismissJob(job.application_id); onGone(); })}>Not interested</button>
      </div>
      <ErrorBox message={error} />
    </article>
  );
}

export default function JobsPage() {
  const [weak, setWeak] = useState(false);
  const { data, error, setData, reload } = useLoad(() => api.myJobs(weak), [weak]);

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Jobs for you</h1>
          <p className="sub">Real, open jobs that match your verified profile, best first.</p>
        </div>
        <div className="row">
          <label className="row small" style={{ display: "flex" }}>
            <input type="checkbox" style={{ width: "auto" }} checked={weak} onChange={(e) => setWeak(e.target.checked)} />
            Show weaker matches
          </label>
          <ImportJob onImported={() => reload()} />
        </div>
      </div>
      <p className="small muted" style={{ marginTop: -10 }}>
        Found a job on LinkedIn or StepStone? Use <b>Add job from URL</b>: paste the link and its text, and it gets a score,
        CV and cover letter like the others.
      </p>
      <ErrorBox message={error} />
      {!data ? <Loading /> : data.jobs.length === 0 ? (
        <p className="notice">
          No matching jobs yet. Open <Link href="/monitor">Search monitor</Link> and press <b>Search now</b>.
          Scores use only facts you verified in your <Link href="/settings">profile</Link>.
        </p>
      ) : (
        <>
          <p className="small muted" style={{ marginTop: 0 }}>
            {data.jobs.length} job{data.jobs.length > 1 ? "s" : ""}
            {!weak && data.hidden_weak > 0 && ` · ${data.hidden_weak} weaker or ineligible matches hidden`}
          </p>
          {data.jobs.map((j) => (
            <JobCard key={j.application_id} job={j}
              onChange={(nj) => setData({ ...data, jobs: data.jobs.map((x) => (x.application_id === nj.application_id ? nj : x)) })}
              onGone={() => setData({ ...data, jobs: data.jobs.filter((x) => x.application_id !== j.application_id) })} />
          ))}
        </>
      )}
    </>
  );
}
