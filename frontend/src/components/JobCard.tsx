"use client";

import Link from "next/link";
import { useState } from "react";
import { api, type MyJob } from "@/lib/api";
import { date } from "@/lib/format";
import { ErrorBox, Score, errorText } from "@/components/ui";
import { KIND_LABEL } from "@/lib/places";

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

export function JobCard({ job, onChange, onGone }: { job: MyJob; onChange: (j: MyJob) => void; onGone: () => void }) {
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
          <h2 style={{ margin: 0, fontSize: 18 }}>
            {job.title}{" "}
            {job.kind !== "job" && <span className="badge accent" style={{ fontSize: 12 }}>{KIND_LABEL[job.kind]}</span>}{" "}
            {job.target_company && <span className="badge good" style={{ fontSize: 12 }}>★ {job.target_company}</span>}
          </h2>
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
        {job.has_link && <a className="btn" href={job.url} target="_blank" rel="noopener noreferrer nofollow">Job listing ↗</a>}
        {hasDocs ? <DocLinks job={job} /> : null}
        <button className="btn" disabled={!!busy}
          onClick={() => act("docs", async () => onChange(await api.makeDocuments(job.application_id)))}>
          {busy === "docs" ? "Writing…" : hasDocs ? "Recreate CV & letter" : "Create CV & cover letter"}
        </button>
        {job.has_link && <a className="btn primary" href={job.url} target="_blank" rel="noopener noreferrer nofollow"
          title="Opens the listing; apply there with your CV and cover letter">Apply ↗</a>}
        <Link className="btn" href={`/assistant?job=${job.application_id}`}>Ask about it</Link>
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

