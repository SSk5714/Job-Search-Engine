"use client";

import { useState } from "react";
import { api, type ApplicationDetail, type FormFieldT } from "@/lib/api";
import { ErrorBox, errorText } from "@/components/ui";

const SENS_LABEL = { sensitive: "Personal", legal: "Legal", normal: "" };

function FieldRow({ appId, f, hint, locked, onChange }: {
  appId: string; f: FormFieldT; hint?: string; locked: boolean; onChange: (d: ApplicationDetail) => void;
}) {
  const [value, setValue] = useState(f.proposed_value ?? "");
  const [error, setError] = useState<string | null>(null);
  const resolved = !f.needs_manual || f.value_source === "user" || f.value_source === "skipped";
  const isFile = f.field_type === "file";

  async function save(body: { proposed_value?: string; skip?: boolean }) {
    setError(null);
    try { onChange(await api.answerField(appId, f.id, body)); } catch (e) { setError(errorText(e)); }
  }

  let control: React.ReactNode;
  if (isFile) {
    control = <span className="small">{f.proposed_value === "document:cv" ? "Your verified CV (PDF)" :
      f.proposed_value === "document:cover_letter" ? "Your verified cover letter (PDF)" : "No file attached"}</span>;
  } else if (f.field_type === "checkbox") {
    control = (
      <div className="row">
        <button className={`btn small${f.proposed_value === "checked" ? " primary" : ""}`} disabled={locked}
          onClick={() => save({ proposed_value: "checked" })}>Tick it</button>
        <button className={`btn small${f.proposed_value === "unchecked" ? " primary" : ""}`} disabled={locked}
          onClick={() => save({ proposed_value: "unchecked" })}>Leave unticked</button>
      </div>
    );
  } else if (f.field_type === "select" || f.field_type === "radio") {
    control = (
      <select value={value} disabled={locked} aria-label={f.label} onChange={(e) => { setValue(e.target.value); if (e.target.value) save({ proposed_value: e.target.value }); }}>
        <option value="">{resolved && f.value_source === "skipped" ? "Left empty" : "Choose…"}</option>
        {f.options.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
      </select>
    );
  } else {
    const long = f.field_type === "textarea";
    control = (
      <div className="row" style={{ flexWrap: "nowrap", alignItems: "flex-start" }}>
        {long
          ? <textarea rows={4} value={value} disabled={locked} aria-label={f.label} onChange={(e) => setValue(e.target.value)} />
          : <input value={value} disabled={locked} aria-label={f.label} type={f.field_type === "date" ? "date" : "text"}
              onChange={(e) => setValue(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter" && value.trim()) save({ proposed_value: value }); }} />}
        <button className="btn small" disabled={locked || !value.trim() || (value === f.proposed_value && f.value_source === "user")}
          onClick={() => save({ proposed_value: value })}>
          {f.needs_manual && f.proposed_value && f.value_source !== "user" && value === f.proposed_value ? "Confirm" : "Save"}
        </button>
      </div>
    );
  }

  return (
    <div style={{ borderLeft: `3px solid ${resolved ? "var(--good)" : "var(--warn)"}`, paddingLeft: 10 }}>
      <div className="row small" style={{ justifyContent: "space-between" }}>
        <span><strong>{f.label || f.field_key}</strong>{f.required && !(f.label || "").trim().endsWith("*") ? " *" : ""}{" "}
          {f.sensitivity !== "normal" && <span className="badge warn">{SENS_LABEL[f.sensitivity]}</span>}</span>
        <span className="muted">
          {f.value_source?.startsWith("fact:") ? "from your verified profile" :
            f.value_source?.startsWith("document:") ? "from your verified documents" :
            f.value_source === "user" ? "your answer" : f.value_source === "skipped" ? "left empty" :
            f.sensitivity !== "normal" ? "you answer this" : "needs you"}
        </span>
      </div>
      {control}
      {hint && <div className="small muted">{hint}</div>}
      {!f.required && !isFile && f.needs_manual && f.value_source !== "skipped" && !locked && (
        <button className="btn small" style={{ marginTop: 4 }} onClick={() => save({ skip: true })}>Leave empty</button>
      )}
      <ErrorBox message={error} />
    </div>
  );
}

export function ApplicationForm({ d, onChange }: { d: ApplicationDetail; onChange: (d: ApplicationDetail) => void }) {
  const [url, setUrl] = useState(d.apply_url ?? d.job.url);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const prep = d.preparation ?? {};
  const locked = ["submitted", "follow_up", "closed"].includes(d.state);

  async function prepare() {
    setBusy(true); setError(null);
    try { onChange(await api.prepare(d.id, url)); } catch (e) { setError(errorText(e)); } finally { setBusy(false); }
  }

  return (
    <section className="card" style={{ marginBottom: 16 }}>
      <h2>Application form</h2>
      {d.state === "documents_ready" && (
        <>
          <label>Application page
            <input value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://… (the page with the application form)" />
          </label>
          <p className="small muted" style={{ margin: "6px 0 10px" }}>
            An isolated browser opens only this site, fills what your verified profile supports, attaches your verified
            documents and takes a screenshot. It never clicks submit. LinkedIn, StepStone, Indeed and XING are never automated.
          </p>
          <ErrorBox message={error} />
          <button className="btn primary" disabled={busy || !url} onClick={prepare}>{busy ? "Preparing the form…" : "Prepare form"}</button>
        </>
      )}

      {prep.mode === "manual" && (
        <div className="notice">
          <strong>Apply on the site yourself.</strong> {prep.reason}
          <div className="row" style={{ marginTop: 8 }}>
            {d.apply_url && <a className="btn small" href={d.apply_url} target="_blank" rel="noopener noreferrer nofollow">Open application page ↗</a>}
            <span className="small muted">Use the verified CV and cover letter above. Approve below, then record that you applied.</span>
          </div>
          {prep.screenshot && <p className="small" style={{ marginTop: 6 }}><a href={api.evidenceUrl(d.id, prep.screenshot)} target="_blank">What the browser saw</a></p>}
        </div>
      )}

      {prep.mode === "browser" && (
        <>
          <p className="small" style={{ marginBottom: 8 }}>
            {prep.auto_filled} of {prep.fields} fields filled from your verified profile · {d.unresolved_fields.length} need your answer ·{" "}
            destination <span className="mono">{prep.host}</span>
            {prep.screenshot && <> · <a href={api.evidenceUrl(d.id, prep.screenshot)} target="_blank">screenshot</a></>}
          </p>
          {(prep.blocked_requests ?? []).length > 0 && (
            <div className="warnbox small" style={{ marginBottom: 8 }}>Blocked attempts to leave the site: {prep.blocked_requests!.join(", ")}</div>
          )}
          <div className="list">
            {[...d.form_fields].sort((a, b) => Number(!a.needs_manual) - Number(!b.needs_manual) || a.position - b.position).map((f) => (
              <FieldRow key={`${f.id}-${f.proposed_value}-${f.value_source}`} appId={d.id} f={f} hint={prep.hints?.[f.field_key]}
                locked={locked} onChange={onChange} />
            ))}
          </div>
        </>
      )}
    </section>
  );
}
