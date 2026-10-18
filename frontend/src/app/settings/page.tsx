"use client";

import { useEffect, useState } from "react";
import { api, type Fact } from "@/lib/api";
import { dateTime } from "@/lib/format";
import { ErrorBox, Loading, errorText, useLoad } from "@/components/ui";
import { MatchingSettings } from "@/components/MatchingSettings";
import { NotificationSettings } from "@/components/NotificationSettings";
import { AccountSettings, BackupCard, UsageCard } from "@/components/OpsSettings";

const SECTIONS: { category: string; title: string; hint: string }[] = [
  { category: "contact", title: "Contact", hint: "Shown on your documents. Never sent to Claude." },
  { category: "education", title: "Education", hint: "One entry per degree (e.g. bachelor, master): degree, university, start and graduation (YYYY-MM), cgpa. Leave graduation empty while studying." },
  { category: "employment", title: "Employment", hint: "One entry per job: employer, location, start, end (YYYY-MM), first_title, promoted_to, promotion_date, focus, and one 'responsibility' fact per bullet." },
  { category: "skill", title: "Skills", hint: "Context separates professional experience from projects, coursework and things you are learning." },
  { category: "project", title: "Projects", hint: "One entry per project: name (context professional or personal) and 'description' facts. Personal projects are never presented as employment." },
  { category: "certification", title: "Certifications", hint: "One fact per certificate, e.g. 'Spring Boot 0 to 1 – Fundamentals, Coding Shuttle (Feb 2026)'." },
  { category: "gap", title: "Since August 2025", hint: "Describe the period accurately, e.g. master's preparation and technical learning." },
  { category: "language", title: "Languages", hint: "CEFR level: A1–C2 or native." },
  { category: "eligibility", title: "Eligibility", hint: "Enrolment status, work authorization, sponsorship and availability (e.g. 'Part-time up to 20 hours per week'). Student roles and legal fields stay blocked until these are verified." },
  { category: "location", title: "Location", hint: "Current city and relocation preferences." },
];
const CONTEXTS = ["professional", "project", "coursework", "learning", "unspecified"];
const ENTRY_CATEGORIES = new Set(["education", "employment", "project"]);

function ProfileEditor() {
  const { data, error, reload } = useLoad(api.profile);
  const [facts, setFacts] = useState<Fact[]>([]);
  const [dirty, setDirty] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    if (data) { setFacts(data.facts); setDirty(false); }
  }, [data]);

  if (!data) return error ? <ErrorBox message={error} /> : <Loading />;

  const update = (i: number, patch: Partial<Fact>) => {
    setFacts(facts.map((f, j) => (j === i ? { ...f, ...patch, verified: false } : f)));
    setDirty(true);
  };

  async function save() {
    setErr(null);
    try {
      await api.saveProfile(facts, "Edited in Settings");
      setMsg("Saved as a new profile version. Changed facts need verifying again.");
      reload();
    } catch (e) { setErr(errorText(e)); }
  }

  async function verify(f: Fact, v: boolean) {
    if (!f.id) return;
    setErr(null);
    try { await api.verifyFact(f.id, v); reload(); } catch (e) { setErr(errorText(e)); }
  }

  return (
    <section className="card" style={{ marginBottom: 16 }}>
      <div className="row" style={{ justifyContent: "space-between" }}>
        <div>
          <h2 style={{ marginBottom: 2 }}>Candidate profile</h2>
          <p className="small muted">Version {data.version_no} · {data.verified_count} of {data.filled_count} filled facts verified. Matching and documents use verified facts only.</p>
        </div>
        <div className="row">
          <a className="btn small" href={api.masterCvUrl("pdf")}>Master CV (PDF)</a>
          <button className="btn small" onClick={async () => {
            const data = await api.exportProfile();
            const url = URL.createObjectURL(new Blob([JSON.stringify(data, null, 2)], { type: "application/json" }));
            const a = document.createElement("a"); a.href = url; a.download = "jobpilot-profile.json"; a.click();
            URL.revokeObjectURL(url);
          }}>Export</button>
          <label className="btn small" style={{ display: "inline-flex", cursor: "pointer" }}>
            Import
            <input type="file" accept="application/json" style={{ display: "none" }} onChange={async (e) => {
              const file = e.target.files?.[0];
              if (!file) return;
              setErr(null);
              try {
                const data = JSON.parse(await file.text());
                if (!confirm(`Replace your profile with ${data.facts?.length ?? 0} facts from ${file.name}? It becomes a new version; you verify each fact afterwards.`)) return;
                await api.importProfile(data);
                setMsg("Imported as a new version. Nothing is verified yet: check each fact and press Verify.");
                reload();
              } catch (x) { setErr(errorText(x)); } finally { e.target.value = ""; }
            }} />
          </label>
          <button className="btn primary" disabled={!dirty} onClick={save}>{dirty ? "Save changes" : "Saved"}</button>
        </div>
      </div>
      {msg && <p className="small muted" style={{ marginTop: 6 }}>{msg}</p>}
      <ErrorBox message={err} />
      {dirty && <div className="warnbox" style={{ marginTop: 8 }}>Unsaved changes. Verify buttons apply to the saved version.</div>}

      {SECTIONS.map((s) => {
        const rows = facts.map((f, i) => ({ f, i })).filter(({ f }) => f.category === s.category);
        return (
          <div key={s.category} style={{ marginTop: 18 }}>
            <div className="row" style={{ justifyContent: "space-between" }}>
              <strong>{s.title}</strong>
              <button className="btn small" onClick={() => {
                setFacts([...facts, { category: s.category, entry: null, key: s.category === "employment" ? "responsibility" : "", value: "", context: s.category === "skill" ? "unspecified" : null, source_note: null, verified: false }]);
                setDirty(true);
              }}>Add</button>
            </div>
            <p className="small muted" style={{ marginBottom: 6 }}>{s.hint}</p>
            <div className="list">
              {rows.map(({ f, i }) => (
                <div key={f.id ?? `new-${i}`} className="row" style={{ alignItems: "center", flexWrap: "nowrap" }}>
                  {ENTRY_CATEGORIES.has(s.category) && (
                    <input aria-label="Entry" style={{ maxWidth: 110 }} value={f.entry ?? ""} placeholder="entry"
                      onChange={(e) => update(i, { entry: e.target.value })} />
                  )}
                  <input aria-label="Field" style={{ maxWidth: 160 }} value={f.key} placeholder="field" onChange={(e) => update(i, { key: e.target.value })} />
                  <input aria-label="Value" value={f.value} placeholder="Not set" onChange={(e) => update(i, { value: e.target.value })} />
                  {(s.category === "skill" || s.category === "project") && (
                    <select aria-label="Context" style={{ maxWidth: 150 }} value={f.context ?? (s.category === "skill" ? "unspecified" : "")} onChange={(e) => update(i, { context: e.target.value || null })}>
                      {s.category === "project" && <option value="">—</option>}
                      {(s.category === "skill" ? CONTEXTS : ["professional", "personal"]).map((c) => <option key={c} value={c}>{c}</option>)}
                    </select>
                  )}
                  {f.id && !dirty ? (
                    <button className={`btn small${f.verified ? " primary" : ""}`} style={{ minWidth: 92 }} disabled={!f.value}
                      title={f.value ? "Toggle verified" : "Fill in a value first"} onClick={() => verify(f, !f.verified)}>
                      {f.verified ? "Verified" : "Verify"}
                    </button>
                  ) : <span className="badge" style={{ minWidth: 92, textAlign: "center" }}>unsaved</span>}
                  <button className="btn small danger" aria-label="Remove" onClick={() => { setFacts(facts.filter((_, j) => j !== i)); setDirty(true); }}>✕</button>
                </div>
              ))}
            </div>
          </div>
        );
      })}
    </section>
  );
}

function Health() {
  const { data, error } = useLoad(api.health);
  if (!data) return error ? <ErrorBox message={error} /> : <Loading />;
  const tone = (s: string) => (s === "ok" ? "ok" : ["down", "not_running"].includes(s) ? "down" : "warn");
  const LABEL: Record<string, string> = { database: "Database", queue: "Task queue", scheduler: "Scheduler",
    monitor: "System monitor", claude_api: "Claude API", email: "Email notifications" };
  return (
    <div className="grid two">
      <section className="card">
        <h2>Job sources</h2>
        <div className="table-wrap">
          <table>
            <thead><tr><th>Source</th><th>Access</th><th>Notes</th></tr></thead>
            <tbody>
              {data.sources.filter((s) => s.code !== "mock_broken").map((s) => (
                <tr key={s.code}>
                  <td>{s.name}</td>
                  <td><span className={`badge ${s.label === "Automated" ? "good" : s.label === "Untested" ? "warn" : s.label === "Mock" ? "accent" : ""}`}>{s.label}</span></td>
                  <td className="small muted">{s.notes}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
      <section className="card">
        <h2>Service health</h2>
        <div className="list small">
          {Object.entries(data.checks).map(([k, c]) => (
            <div key={k}>
              <span className={`dot ${tone(c.status)}`} /><strong>{LABEL[k] ?? k.replace("_", " ")}</strong> · {c.status.replaceAll("_", " ")}
              {c.detail && <div className="muted" style={{ marginLeft: 16 }}>{c.detail}</div>}
            </div>
          ))}
        </div>
        <p className="small muted" style={{ marginTop: 12 }}>Checked {dateTime(new Date().toISOString())}</p>
        {(data.monitor_history ?? []).length > 0 && (
          <details className="small" style={{ marginTop: 8 }}>
            <summary>Monitor history (status changes)</summary>
            <div className="list" style={{ marginTop: 6 }}>
              {data.monitor_history!.map((h, i) => (
                <div key={i}><span className={`dot ${tone(h.status)}`} />{h.check} → {h.status} · <span className="muted">{dateTime(h.at)}</span></div>
              ))}
            </div>
          </details>
        )}
        {(data.recent_errors ?? []).length > 0 && (
          <details className="small" style={{ marginTop: 8 }}>
            <summary>Recent errors (technical)</summary>
            <div className="list" style={{ marginTop: 6 }}>
              {data.recent_errors!.map((e, i) => (
                <div key={i}><strong>{e.component}</strong> · {e.code} · <span className="muted">{dateTime(e.at)}</span>
                  <div className="muted mono" style={{ wordBreak: "break-word" }}>{e.message}</div></div>
              ))}
            </div>
          </details>
        )}
      </section>
    </div>
  );
}

export default function SettingsPage() {
  return (
    <>
      <div className="page-head">
        <div>
          <h1>Settings & Health</h1>
          <p className="sub">Your verified profile is the only source for scores and documents. Below: matching, notifications, usage, backups, account and system health.</p>
        </div>
      </div>
      <ProfileEditor />
      <MatchingSettings />
      <NotificationSettings />
      <UsageCard />
      <BackupCard />
      <AccountSettings />
      <Health />
    </>
  );
}
