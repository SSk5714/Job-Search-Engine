"use client";

import { Suspense, useEffect, useRef, useState } from "react";
import { useSearchParams } from "next/navigation";
import { api } from "@/lib/api";
import { ErrorBox, errorText, useLoad } from "@/components/ui";

type Turn = { role: "user" | "assistant"; content: string };
const STORE = "jobpilot.assistant.v1";
const IDEAS = [
  "Which of my jobs fits me best, and why?",
  "What should I learn next to get more Android/AOSP offers?",
  "Write a short email asking a recruiter about a Werkstudent position.",
  "Prepare me for a technical interview for this job.",
  "Make my cover letter for this job more specific.",
];

function load(): Record<string, Turn[]> {
  try { return JSON.parse(localStorage.getItem(STORE) || "{}"); } catch { return {}; }
}
function save(all: Record<string, Turn[]>) {
  try { localStorage.setItem(STORE, JSON.stringify(all)); } catch { /* private window: keep it in memory */ }
}

function Chat() {
  const params = useSearchParams();
  const jobs = useLoad(() => api.myJobs(true));
  const [job, setJob] = useState(params.get("job") ?? "");
  const [all, setAll] = useState<Record<string, Turn[]>>({});
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const end = useRef<HTMLDivElement>(null);
  const key = job || "general";
  const turns = all[key] ?? [];

  useEffect(() => { setAll(load()); }, []);
  useEffect(() => { end.current?.scrollIntoView({ behavior: "smooth" }); }, [turns.length, busy]);

  async function send(text: string) {
    const q = text.trim();
    if (!q || busy) return;
    const next = [...turns, { role: "user" as const, content: q }];
    const upd = { ...all, [key]: next };
    setAll(upd); setInput(""); setErr(null); setBusy(true);
    try {
      const r = await api.ask(next, job || null);
      const done = { ...upd, [key]: [...next, { role: "assistant" as const, content: r.reply }] };
      setAll(done); save(done);
    } catch (e) {
      setErr(errorText(e));
      setAll({ ...all, [key]: turns }); setInput(q);  // give the question back to try again
    } finally { setBusy(false); }
  }

  const current = jobs.data?.jobs.find((j) => j.application_id === job);
  return (
    <>
      <div className="page-head">
        <div>
          <h1>Ask</h1>
          <p className="sub">Ask Claude anything about your job search. It knows your verified profile (never your contact
            details) and, if you pick one, the job, its score and your CV and cover letter for it.</p>
        </div>
        {turns.length > 0 && (
          <button className="btn small" onClick={() => { const n = { ...all }; delete n[key]; setAll(n); save(n); }}>
            New conversation</button>
        )}
      </div>

      <div className="row small" style={{ marginBottom: 10 }}>
        <label className="row" style={{ display: "flex", gap: 6 }}>About
          <select value={job} onChange={(e) => setJob(e.target.value)} style={{ width: "auto", maxWidth: 520 }}>
            <option value="">my job search in general</option>
            {jobs.data?.jobs.map((j) => (
              <option key={j.application_id} value={j.application_id}>{j.title} · {j.company}</option>
            ))}
          </select>
        </label>
        {current?.score != null && <span className="muted">score {current.score}</span>}
      </div>

      <section className="card chat" style={{ minHeight: 320, display: "flex", flexDirection: "column", gap: 12 }}>
        {turns.length === 0 && !busy && (
          <div>
            <p className="small muted" style={{ marginTop: 0 }}>Try:</p>
            <div className="row">
              {IDEAS.map((i) => <button key={i} className="btn small" onClick={() => send(i)}>{i}</button>)}
            </div>
          </div>
        )}
        {turns.map((t, i) => (
          <div key={i} style={{
            alignSelf: t.role === "user" ? "flex-end" : "flex-start", maxWidth: "85%",
            background: t.role === "user" ? "var(--accent-soft, rgba(30,100,90,.10))" : "transparent",
            border: t.role === "user" ? "none" : "1px solid var(--line, rgba(0,0,0,.1))",
            borderRadius: 10, padding: "8px 12px", whiteSpace: "pre-wrap", lineHeight: 1.5,
          }}>
            {t.content}
            {t.role === "assistant" && (
              <div><button className="btn small" style={{ marginTop: 6 }}
                onClick={() => navigator.clipboard?.writeText(t.content).catch(() => undefined)}>Copy</button></div>
            )}
          </div>
        ))}
        {busy && <div className="small muted">Claude is thinking…</div>}
        <div ref={end} />
      </section>

      <ErrorBox message={err} />
      <form className="row" style={{ marginTop: 10, alignItems: "flex-end", flexWrap: "nowrap" }}
        onSubmit={(e) => { e.preventDefault(); send(input); }}>
        <textarea rows={3} value={input} placeholder="Ask anything… (Enter to send, Shift+Enter for a new line)"
          aria-label="Your message" onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(input); } }} />
        <button className="btn primary" type="submit" disabled={busy || !input.trim()}>Send</button>
      </form>
      <p className="small muted">Each answer uses a little of your daily Claude budget (Profile &amp; settings). Claude only
        answers: it never changes your documents or applies anywhere.</p>
    </>
  );
}

export default function AssistantPage() {
  return <Suspense><Chat /></Suspense>;
}
