"use client";

import { useEffect, useState } from "react";
import { api, type SearchConfig, type SearchRun } from "@/lib/api";
import { TRACKS, dateTime } from "@/lib/format";
import { ErrorBox, Loading, errorText, useLoad } from "@/components/ui";
import { ScheduleCard } from "@/components/ScheduleCard";

const list = (s: string) => s.split(",").map((x) => x.trim()).filter(Boolean);

const OPTION_FIELDS: Record<string, { key: string; label: string; placeholder: string; kind?: "list" | "number" | "region" }[]> = {
  greenhouse: [{ key: "boards", label: "Board tokens", placeholder: "e.g. gitlab, celonis", kind: "list" }],
  lever: [
    { key: "sites", label: "Site names", placeholder: "e.g. exampleco", kind: "list" },
    { key: "region", label: "Region", placeholder: "", kind: "region" },
  ],
  personio: [{ key: "companies", label: "Company subdomains", placeholder: "e.g. acme for acme.jobs.personio.de", kind: "list" }],
  ba_jobsuche: [{ key: "radius_km", label: "Radius around each city (km)", placeholder: "50", kind: "number" }],
};
const LABEL_TONE: Record<string, string> = { Automated: "good", Untested: "warn", Mock: "accent" };

function RunStatus({ run, onStop }: { run: SearchRun; onStop: () => void }) {
  const tone = run.status === "completed" ? "good" : run.status === "running" ? "accent" : run.status === "partial" ? "warn" : "bad";
  const s = run.summary as Record<string, number>;
  return (
    <tr>
      <td>{dateTime(run.started_at)}<div className="small muted">{run.trigger === "schedule" ? "scheduled" : "by you"}</div></td>
      <td><span className={`badge ${tone}`}>{run.status}</span>
        {run.status === "running" && Date.now() - new Date(run.started_at).getTime() > 10 * 60_000 && (
          <button className="btn small" style={{ marginLeft: 6 }} title="Mark this stuck run as failed so the search can run again"
            onClick={async () => { if (confirm("Stop this run? Jobs it already saved are kept.")) { await api.stopRun(run.id).catch(() => undefined); onStop(); } }}>
            Stop</button>
        )}
        {run.status === "failed" && typeof run.summary.error === "string" && <div className="small muted">{run.summary.error as string}</div>}
      </td>
      <td className="small">
        {run.status === "running" ? "…" : `${s.fetched ?? 0} fetched · ${s.new ?? 0} new · ${(s.duplicate_url ?? 0) + (s.duplicate_fingerprint ?? 0)} duplicates`}
      </td>
      <td className="small">
        {Object.entries(run.summary.sources ?? {}).map(([code, r]) => (
          <span key={code} className={`chip ${r.status === "ok" ? "ok" : "miss"}`}>{code}: {r.status === "ok" ? "ok" : r.error}</span>
        ))}
      </td>
    </tr>
  );
}

export default function DiscoveryPage() {
  const configs = useLoad(api.configs);
  const sources = useLoad(api.sources);
  const runs = useLoad(api.runs);
  const [draft, setDraft] = useState<SearchConfig | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (configs.data && !draft) setDraft(configs.data[0] ?? null);
  }, [configs.data, draft]);

  const running = runs.data?.some((r) => r.status === "running");
  useEffect(() => {
    if (!running) return;
    const t = setInterval(runs.reload, 2000);
    return () => clearInterval(t);
  }, [running, runs.reload]);

  if (!draft) return configs.error ? <ErrorBox message={configs.error} /> : <Loading />;

  const f = draft.filters;
  const setF = (patch: Partial<typeof f>) => setDraft({ ...draft, filters: { ...f, ...patch } });
  const toggle = (arr: string[], v: string) => (arr.includes(v) ? arr.filter((x) => x !== v) : [...arr, v]);

  async function save() {
    setBusy(true); setError(null);
    try {
      const saved = await api.saveConfig(draft!);
      setDraft(saved); setMsg("Search saved"); configs.reload();
    } catch (e) { setError(errorText(e)); } finally { setBusy(false); }
  }

  async function run() {
    setBusy(true); setError(null); setMsg(null);
    try {
      await api.saveConfig(draft!);
      await api.startRun(draft!.id);
      runs.reload();
      setMsg("Search started");
    } catch (e) { setError(errorText(e)); } finally { setBusy(false); }
  }

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Job Discovery</h1>
          <p className="sub">Germany first, then other European countries. Each source runs in isolation.</p>
        </div>
        <div className="row">
          <button className="btn" onClick={save} disabled={busy}>Save</button>
          <button className="btn primary" onClick={run} disabled={busy || running}>{running ? "Search running…" : "Run search"}</button>
        </div>
      </div>
      <ErrorBox message={error} />
      {msg && <p className="small muted" style={{ marginBottom: 8 }}>{msg}</p>}

      <section className="card" style={{ marginBottom: 16 }}>
        <div className="form-grid">
          <label>Search name<input value={draft.name} onChange={(e) => setDraft({ ...draft, name: e.target.value })} /></label>
          <label>Countries (ISO codes, first is preferred)<input value={f.countries.join(", ")} onChange={(e) => setF({ countries: list(e.target.value).map((c) => c.toUpperCase()) })} /></label>
          <label>Cities<input value={f.cities.join(", ")} placeholder="Any" onChange={(e) => setF({ cities: list(e.target.value) })} /></label>
          <label>Keywords<input value={f.keywords.join(", ")} placeholder="Any" onChange={(e) => setF({ keywords: list(e.target.value) })} /></label>
          <label>Published within (days)<input type="number" min={1} value={f.max_age_days ?? ""} onChange={(e) => setF({ max_age_days: e.target.value ? Number(e.target.value) : null })} /></label>
          <label>Work arrangement
            <select value={f.work_modes[0] ?? ""} onChange={(e) => setF({ work_modes: e.target.value ? [e.target.value] : [] })}>
              <option value="">Any</option><option value="remote">Remote</option><option value="hybrid">Hybrid</option><option value="onsite">On-site</option>
            </select>
          </label>
        </div>
        <div className="sep" />
        <div className="small muted" style={{ marginBottom: 6 }}>Job tracks</div>
        <div className="row">
          {Object.entries(TRACKS).filter(([k]) => k !== "other").map(([k, label]) => (
            <button key={k} className={`btn small${f.tracks.includes(k) ? " primary" : ""}`} onClick={() => setF({ tracks: toggle(f.tracks, k) })}>
              {k} · {label}
            </button>
          ))}
        </div>
        <div className="sep" />
        <div className="small muted" style={{ marginBottom: 6 }}>Sources</div>
        {sources.data ? (
          <div className="list">
            {sources.data.filter((s) => s.code !== "mock_broken").map((s) => {
              const usable = s.implemented;
              const on = draft.source_codes.includes(s.code);
              const opts = (draft.source_options?.[s.code] ?? {}) as Record<string, unknown>;
              const setOpt = (key: string, value: unknown) => setDraft({
                ...draft, source_options: { ...(draft.source_options ?? {}), [s.code]: { ...opts, [key]: value } },
              });
              return (
                <div key={s.code}>
                  <label className="row" style={{ display: "flex", color: "var(--ink)", opacity: usable ? 1 : 0.65 }}>
                    <input type="checkbox" style={{ width: "auto" }} disabled={!usable} checked={on}
                      onChange={() => setDraft({ ...draft, source_codes: toggle(draft.source_codes, s.code) })} />
                    <span style={{ minWidth: 240 }}>{s.name}</span>
                    <span className={`badge ${LABEL_TONE[s.label] ?? ""}`}
                      title={s.label === "Untested" ? "Built and tested against recorded responses; becomes Automated after its first successful live run" : undefined}>
                      {s.label}</span>
                    <span className="small muted">{s.notes}</span>
                  </label>
                  {on && OPTION_FIELDS[s.code] && (
                    <div className="form-grid" style={{ margin: "6px 0 4px 28px" }}>
                      {OPTION_FIELDS[s.code].map((f) => (
                        <label key={f.key}>{f.label}
                          {f.kind === "region" ? (
                            <select value={(opts[f.key] as string) ?? "global"} onChange={(e) => setOpt(f.key, e.target.value)}>
                              <option value="global">Global (api.lever.co)</option><option value="eu">EU (api.eu.lever.co)</option>
                            </select>
                          ) : f.kind === "number" ? (
                            <input type="number" min={0} placeholder={f.placeholder} value={(opts[f.key] as number) ?? ""}
                              onChange={(e) => setOpt(f.key, e.target.value ? Number(e.target.value) : undefined)} />
                          ) : (
                            <input placeholder={f.placeholder} value={((opts[f.key] as string[]) ?? []).join(", ")}
                              onChange={(e) => setOpt(f.key, list(e.target.value))} />
                          )}
                        </label>
                      ))}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        ) : <Loading />}
        <p className="small muted" style={{ marginTop: 10 }}>
          Manual-only sites (LinkedIn, StepStone, Indeed, XING) are added one at a time with “Add job from URL” in Job Review.
        </p>
      </section>

      <ScheduleCard key={`${draft.id}-${draft.cron}-${draft.paused_reason}`} config={draft} onSaved={(c) => {
        setDraft({ ...draft, cron: c.cron, timezone: c.timezone, allow_overlap: c.allow_overlap, schedule_text: c.schedule_text,
          next_run_at: c.next_run_at, paused_reason: c.paused_reason, last_dispatch: c.last_dispatch });
        configs.reload();
      }} />

      <section className="card">
        <h2>Recent runs</h2>
        {runs.data && runs.data.length > 0 ? (
          <div className="table-wrap">
            <table>
              <thead><tr><th>Started</th><th>Status</th><th>Result</th><th>Sources</th></tr></thead>
              <tbody>{runs.data.map((r) => <RunStatus key={r.id} run={r} onStop={runs.reload} />)}</tbody>
            </table>
          </div>
        ) : <p className="small muted">No runs yet.</p>}
      </section>
    </>
  );
}
