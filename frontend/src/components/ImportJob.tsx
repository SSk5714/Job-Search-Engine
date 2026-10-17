"use client";

import { useState } from "react";
import { api, ApiError, type ImportIn, type Job } from "@/lib/api";
import { ErrorBox, errorText } from "@/components/ui";

const API_HOSTS = /greenhouse\.io|lever\.co|jobs\.personio\.(de|com)|arbeitsagentur\.de\/jobsuche/i;

export function ImportJob({ onImported }: { onImported: (job: Job) => void }) {
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState<ImportIn>({ url: "" });
  const [needDetails, setNeedDetails] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const fetchable = API_HOSTS.test(form.url);
  const set = (patch: Partial<ImportIn>) => setForm({ ...form, ...patch });

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true); setError(null); setMsg(null);
    try {
      const body: ImportIn = Object.fromEntries(Object.entries(form).filter(([, v]) => v)) as unknown as ImportIn;
      const r = await api.importUrl(body);
      setMsg(r.outcome === "new" ? `Added: ${r.job.title} at ${r.job.company}` : "This job is already in your list");
      setForm({ url: "" }); setNeedDetails(false);
      onImported(r.job);
    } catch (err) {
      if (err instanceof ApiError && err.code === "details_required") setNeedDetails(true);
      setError(errorText(err));
    } finally { setBusy(false); }
  }

  if (!open) return <button className="btn" onClick={() => setOpen(true)}>Add job from URL</button>;

  return (
    <form className="card grid" style={{ marginBottom: 16 }} onSubmit={submit}>
      <div className="row" style={{ justifyContent: "space-between" }}>
        <h2 style={{ margin: 0 }}>Add a job from a link</h2>
        <button type="button" className="btn small" onClick={() => setOpen(false)}>Close</button>
      </div>
      <label>Job URL<input type="url" required placeholder="https://…" value={form.url} onChange={(e) => set({ url: e.target.value })} /></label>
      <p className="small muted">
        {form.url && fetchable
          ? "Fetched through the company's public job API."
          : "Links from LinkedIn, StepStone, Indeed, XING and other sites are never opened by JobPilot. Paste the details from the page."}
      </p>
      {(needDetails || (form.url && !fetchable)) && (
        <div className="form-grid">
          <label>Job title<input required value={form.title ?? ""} onChange={(e) => set({ title: e.target.value })} /></label>
          <label>Company<input required value={form.company ?? ""} onChange={(e) => set({ company: e.target.value })} /></label>
          <label>City<input value={form.city ?? ""} onChange={(e) => set({ city: e.target.value })} /></label>
          <label>Country (ISO)<input maxLength={2} placeholder="DE" value={form.country ?? ""} onChange={(e) => set({ country: e.target.value.toUpperCase() })} /></label>
          <label>Work arrangement
            <select value={form.work_mode ?? ""} onChange={(e) => set({ work_mode: (e.target.value || undefined) as ImportIn["work_mode"] })}>
              <option value="">Unknown</option><option value="onsite">On-site</option><option value="hybrid">Hybrid</option><option value="remote">Remote</option>
            </select>
          </label>
          <label style={{ gridColumn: "1 / -1" }}>Job description (paste)
            <textarea rows={6} value={form.description ?? ""} onChange={(e) => set({ description: e.target.value })} />
          </label>
        </div>
      )}
      <ErrorBox message={error} />
      {msg && <p className="small" style={{ color: "var(--good)" }}>{msg}</p>}
      <div><button className="btn primary" disabled={busy}>{busy ? "Adding…" : "Add and score"}</button></div>
    </form>
  );
}
