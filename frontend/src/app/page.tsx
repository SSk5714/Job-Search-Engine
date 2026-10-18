"use client";

import Link from "next/link";
import { useState } from "react";
import { api, type MyJob } from "@/lib/api";
import { date } from "@/lib/format";
import { ErrorBox, Loading, Score, errorText, useLoad } from "@/components/ui";
import { ImportJob } from "@/components/ImportJob";
import { KINDS, KIND_LABEL, careerPage, jobSiteLinks } from "@/lib/places";

function SearchElsewhere() {
  const { data: configs } = useLoad(api.configs);
  const cfg = configs?.[0];
  const words = cfg?.filters.keywords.length ? cfg.filters.keywords : ["Softwareentwickler"];
  const cities = cfg?.filters.cities ?? [];
  const radius = Number((cfg?.source_options?.ba_jobsuche as { radius_km?: number } | undefined)?.radius_km ?? 30);
  const companies = cfg?.filters.companies ?? [];
  const [word, setWord] = useState(0);
  const [kind, setKind] = useState("job");
  const [city, setCity] = useState(0);
  if (!cfg) return null;
  const k = KINDS.find((x) => x.code === kind)!;
  const query = `${k.word} ${words[word] ?? words[0]}`.trim();
  return (
    <details className="card" style={{ marginBottom: 12 }}>
      <summary><b>Search Indeed, LinkedIn, StepStone, XING</b> <span className="small muted">
        · they don&apos;t allow automatic searching, so these open your search there</span></summary>
      <div className="row small" style={{ marginTop: 10 }}>
        <select aria-label="Keyword" value={word} onChange={(e) => setWord(Number(e.target.value))} style={{ width: "auto" }}>
          {words.map((w, i) => <option key={w} value={i}>{w}</option>)}
        </select>
        <select aria-label="Kind" value={kind} onChange={(e) => setKind(e.target.value)} style={{ width: "auto" }}>
          {KINDS.map((x) => <option key={x.code} value={x.code}>{x.label}</option>)}
        </select>
        <select aria-label="City" value={city} onChange={(e) => setCity(Number(e.target.value))} style={{ width: "auto" }}>
          {cities.length === 0 && <option value={0}>All of Germany</option>}
          {cities.map((c, i) => <option key={c} value={i}>{c}</option>)}
        </select>
      </div>
      <div className="row" style={{ marginTop: 8 }}>
        {jobSiteLinks(query, cities[city] ?? "", radius).map((l) => (
          <a key={l.name} className="btn" href={l.url} target="_blank" rel="noopener noreferrer nofollow">{l.name} ↗</a>
        ))}
      </div>
      {companies.length > 0 && (
        <>
          <div className="small muted" style={{ marginTop: 10 }}>Career pages of your companies:</div>
          <div className="row" style={{ marginTop: 4 }}>
            {companies.map((c) => {
              const url = careerPage(c);
              return url
                ? <a key={c} className="btn small" href={url} target="_blank" rel="noopener noreferrer nofollow">{c} ↗</a>
                : <a key={c} className="btn small" target="_blank" rel="noopener noreferrer nofollow"
                    href={`https://www.arbeitsagentur.de/jobsuche/suche?was=${encodeURIComponent(`${k.word} ${c}`.trim())}`}>{c} ↗</a>;
            })}
          </div>
        </>
      )}
      <p className="small muted" style={{ marginBottom: 0 }}>Found one you like? Copy its link and use <b>Add job from URL</b>:
        it gets a score, CV and cover letter like the others.</p>
    </details>
  );
}

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
  const [show, setShow] = useState<"all" | "student" | "companies">("all");
  const { data, error, setData, reload } = useLoad(() => api.myJobs(weak), [weak]);
  const visible = (data?.jobs ?? []).filter((j) => show === "all" || (show === "student" ? j.kind !== "job" : !!j.target_company));

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
      <SearchElsewhere />
      <ErrorBox message={error} />
      {!data ? <Loading /> : data.jobs.length === 0 ? (
        <p className="notice">
          No matching jobs yet. Open <Link href="/monitor">Search monitor</Link> and press <b>Search now</b>.
          Scores use only facts you verified in your <Link href="/settings">profile</Link>.
        </p>
      ) : (
        <>
          <div className="row small" style={{ marginBottom: 8 }}>
            {([["all", "All"], ["student", "Student jobs"], ["companies", "★ My companies"]] as const).map(([v, l]) => (
              <button key={v} className={`btn small${show === v ? " primary" : ""}`} onClick={() => setShow(v)}>{l}</button>
            ))}
            <span className="muted">
              {visible.length} job{visible.length === 1 ? "" : "s"}
              {!weak && data.hidden_weak > 0 && ` · ${data.hidden_weak} weaker or ineligible matches hidden`}
            </span>
          </div>
          {visible.length === 0 && <p className="notice">None in this view yet.</p>}
          {visible.map((j) => (
            <JobCard key={j.application_id} job={j}
              onChange={(nj) => setData({ ...data, jobs: data.jobs.map((x) => (x.application_id === nj.application_id ? nj : x)) })}
              onGone={() => setData({ ...data, jobs: data.jobs.filter((x) => x.application_id !== j.application_id) })} />
          ))}
        </>
      )}
    </>
  );
}
