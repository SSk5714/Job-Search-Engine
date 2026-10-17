"use client";

import { useEffect, useState } from "react";
import { api, type Fact } from "@/lib/api";
import { dateTime } from "@/lib/format";
import { ErrorBox, Loading, errorText, useLoad } from "@/components/ui";
import { MatchingSettings } from "@/components/MatchingSettings";

const SECTIONS: { category: string; title: string; hint: string }[] = [
  { category: "education", title: "Education", hint: "Degree, university, graduation (YYYY-MM), grade." },
  { category: "employment", title: "Employment", hint: "Use exact dates (YYYY-MM). Only verified facts appear in documents." },
  { category: "skill", title: "Skills", hint: "Context separates professional experience from projects, coursework and things you are learning." },
  { category: "project", title: "Projects", hint: "Personal or academic projects. Never presented as employment." },
  { category: "gap", title: "Since August 2025", hint: "Describe the period accurately, e.g. master's preparation and technical learning." },
  { category: "language", title: "Languages", hint: "CEFR level: A1–C2 or native." },
  { category: "eligibility", title: "Eligibility", hint: "Enrolment status, work authorization and sponsorship. Student roles and legal fields stay blocked until these are verified." },
  { category: "location", title: "Location", hint: "Current city and relocation preferences." },
];
const CONTEXTS = ["professional", "project", "coursework", "learning", "unspecified"];

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
        <button className="btn primary" disabled={!dirty} onClick={save}>{dirty ? "Save changes" : "Saved"}</button>
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
                setFacts([...facts, { category: s.category, key: "", value: "", context: s.category === "skill" ? "unspecified" : null, source_note: null, verified: false }]);
                setDirty(true);
              }}>Add</button>
            </div>
            <p className="small muted" style={{ marginBottom: 6 }}>{s.hint}</p>
            <div className="list">
              {rows.map(({ f, i }) => (
                <div key={f.id ?? `new-${i}`} className="row" style={{ alignItems: "center", flexWrap: "nowrap" }}>
                  <input aria-label="Field" style={{ maxWidth: 180 }} value={f.key} placeholder="field" onChange={(e) => update(i, { key: e.target.value })} />
                  <input aria-label="Value" value={f.value} placeholder="Not set" onChange={(e) => update(i, { value: e.target.value })} />
                  {s.category === "skill" && (
                    <select aria-label="Context" style={{ maxWidth: 150 }} value={f.context ?? "unspecified"} onChange={(e) => update(i, { context: e.target.value })}>
                      {CONTEXTS.map((c) => <option key={c} value={c}>{c}</option>)}
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
  const tone = (s: string) => (s === "ok" ? "ok" : s === "down" ? "down" : "warn");
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
              <span className={`dot ${tone(c.status)}`} /><strong>{k.replace("_", " ")}</strong> · {c.status.replace("_", " ")}
              {c.detail && <div className="muted" style={{ marginLeft: 16 }}>{c.detail}</div>}
            </div>
          ))}
        </div>
        <p className="small muted" style={{ marginTop: 12 }}>Checked {dateTime(new Date().toISOString())}</p>
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
          <p className="sub">Your verified profile is the only source for scores and, later, for generated documents.</p>
        </div>
      </div>
      <ProfileEditor />
      <MatchingSettings />
      <Health />
    </>
  );
}
