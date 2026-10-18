"use client";

import Link from "next/link";
import { useState } from "react";
import { api, type MyJob } from "@/lib/api";
import { ErrorBox, errorText } from "@/components/ui";
import { JobCard } from "@/components/JobCard";

export default function PastePage() {
  const [f, setF] = useState({ title: "", company: "", city: "", url: "", job_text: "", company_details: "" });
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [result, setResult] = useState<MyJob | null>(null);
  const set = (k: keyof typeof f) => (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) =>
    setF({ ...f, [k]: e.target.value });

  async function create() {
    setErr(null); setResult(null);
    if (f.job_text.trim().length < 50) { setErr("Paste the whole job description (at least a few sentences)."); return; }
    setBusy(true);
    try {
      setResult(await api.pasteJob({
        title: f.title.trim(), company: f.company.trim(), job_text: f.job_text,
        company_details: f.company_details.trim() || null, url: f.url.trim() || null, city: f.city.trim() || null,
      }));
    } catch (e) { setErr(errorText(e)); } finally { setBusy(false); }
  }

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Paste a job</h1>
          <p className="sub">Paste a job description from anywhere (LinkedIn, Indeed, a company site, an email). You get a
            match score, a tailored CV and a cover letter, written only from your verified profile.</p>
        </div>
      </div>
      <section className="card" style={{ marginBottom: 16 }}>
        <div className="form-grid">
          <label>Job title *<input value={f.title} onChange={set("title")} placeholder="Werkstudent Android Entwicklung" /></label>
          <label>Company *<input value={f.company} onChange={set("company")} placeholder="BMW Group" /></label>
          <label>City<input value={f.city} onChange={set("city")} placeholder="Leipzig" /></label>
          <label>Link to the job (optional)<input value={f.url} onChange={set("url")} placeholder="https://…" /></label>
        </div>
        <label style={{ display: "block", marginTop: 10 }}>Job description *
          <textarea rows={12} value={f.job_text} onChange={set("job_text")}
            placeholder="Paste the full text: tasks, requirements, what they offer…" /></label>
        <label style={{ display: "block", marginTop: 10 }}>About the company (optional)
          <textarea rows={4} value={f.company_details} onChange={set("company_details")}
            placeholder="What they do, products, values, why you want to work there. Used in the cover letter." /></label>
        <div className="row" style={{ marginTop: 10 }}>
          <button className="btn primary" disabled={busy || !f.title.trim() || !f.company.trim()} onClick={create}>
            {busy ? "Writing CV and cover letter…" : "Create CV & cover letter"}</button>
          <span className="small muted">Takes up to a minute with Claude. The job is also added to your Jobs list.</span>
        </div>
        <ErrorBox message={err} />
      </section>
      {result && (
        <>
          <h2 style={{ fontSize: 16 }}>Result</h2>
          <JobCard job={result} onChange={setResult} onGone={() => setResult(null)} />
          <p className="small muted">Want changes? <Link href={`/assistant?job=${result.application_id}`}>Ask about this job</Link>,
            or use <b>edit</b> next to the Word links.</p>
        </>
      )}
    </>
  );
}
