"use client";

import { useEffect, useState } from "react";
import { api, type SearchConfig, type SearchRun, type Source } from "@/lib/api";
import { dateTime } from "@/lib/format";
import { ErrorBox, Loading, errorText, useLoad } from "@/components/ui";
import { ScheduleCard } from "@/components/ScheduleCard";

const list = (s: string) => s.split(",").map((x) => x.trim()).filter(Boolean);
const SEARCH_COMPONENTS = ["discovery", "scheduler", "queue", "orchestrator"];

// Sources that need company names, and the option key each one reads them from.
const COMPANY_SOURCES: Record<string, { key: string; hint: string }> = {
  greenhouse: { key: "boards", hint: "Greenhouse board names, e.g. gitlab, n26" },
  lever: { key: "sites", hint: "Lever company names" },
  personio: { key: "companies", hint: "Personio company names (from company.jobs.personio.de)" },
};
const SHORT: Record<string, string> = { ba_jobsuche: "Bundesagentur", greenhouse: "Greenhouse", lever: "Lever", personio: "Personio" };
const ERRORS: Record<string, string> = {
  forbidden: "access refused", needs_configuration: "needs company names", http_error: "a company name was not found",
  unexpected_format: "unknown answer format", timeout: "timed out", unreachable: "unreachable", rate_limited: "too many requests",
};

function sourceText(r: SearchRun) {
  return Object.entries(r.summary.sources ?? {}).map(([code, v]) => {
    const name = SHORT[code] ?? code;
    const x = v as { status: string; error?: string; fetched?: number; new?: number };
    return { name, ok: x.status === "ok", text: x.status === "ok" ? `${x.fetched ?? 0} found, ${x.new ?? 0} new` : ERRORS[x.error ?? ""] ?? x.error ?? "failed" };
  });
}

function runText(r: SearchRun) {
  const s = r.summary as Record<string, number>;
  if (r.status === "running") return "searching…";
  return `${s.fetched ?? 0} found · ${s.new ?? 0} new`;
}

function SearchSettings({ cfg, sources, onSaved }: { cfg: SearchConfig; sources: Source[]; onSaved: (c: SearchConfig) => void }) {
  const automated = sources.filter((x) => x.implemented && (x.access_mode === "api" || x.access_mode === "feed"));
  const opts = (cfg.source_options ?? {}) as Record<string, Record<string, unknown>>;
  const [codes, setCodes] = useState<string[]>(cfg.source_codes.length ? cfg.source_codes : ["ba_jobsuche"]);
  const [companies, setCompanies] = useState<Record<string, string>>(() => Object.fromEntries(
    Object.entries(COMPANY_SOURCES).map(([c, { key }]) => [c, ((opts[c]?.[key] as string[]) ?? []).join(", ")])));
  const [keywords, setKeywords] = useState(cfg.filters.keywords.join(", "));
  const [cities, setCities] = useState(cfg.filters.cities.join(", "));
  const [radius, setRadius] = useState(String((cfg.source_options?.ba_jobsuche as { radius_km?: number })?.radius_km ?? 50));
  const [days, setDays] = useState(String(cfg.filters.max_age_days ?? 30));
  const [msg, setMsg] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);

  async function save() {
    setErr(null); setMsg(null);
    try {
      if (!codes.length) { setErr("Tick at least one place to search."); return; }
      const missing = codes.filter((c) => COMPANY_SOURCES[c] && !list(companies[c] ?? "").length);
      if (missing.length) { setErr(`Add company names for ${missing.map((c) => SHORT[c] ?? c).join(", ")}, or untick it.`); return; }
      const source_options: Record<string, Record<string, unknown>> = { ...opts, ba_jobsuche: { ...(opts.ba_jobsuche ?? {}), radius_km: Number(radius) || 50 } };
      for (const [c, { key }] of Object.entries(COMPANY_SOURCES)) source_options[c] = { ...(opts[c] ?? {}), [key]: list(companies[c] ?? "") };
      const saved = await api.saveConfig({
        ...cfg, source_codes: codes,
        filters: { ...cfg.filters, keywords: list(keywords), cities: list(cities), max_age_days: Number(days) || 30 },
        source_options,
      });
      onSaved(saved); setMsg("Saved. The next search uses these settings.");
    } catch (e) { setErr(errorText(e)); }
  }

  return (
    <section className="card" style={{ marginBottom: 16 }}>
      <h2>What to search for</h2>
      <div className="form-grid">
        <label>Keywords (comma separated)
          <input value={keywords} placeholder="Android, AOSP, Java, Spring Boot" onChange={(e) => setKeywords(e.target.value)} /></label>
        <label>Cities (empty = all of Germany)
          <input value={cities} placeholder="Chemnitz, Leipzig, Berlin" onChange={(e) => setCities(e.target.value)} /></label>
        <label>Distance around each city (km)
          <input type="number" min={0} value={radius} onChange={(e) => setRadius(e.target.value)} /></label>
        <label>Only jobs posted in the last (days)
          <input type="number" min={1} max={100} value={days} onChange={(e) => setDays(e.target.value)} /></label>
      </div>
      <h3 style={{ margin: "14px 0 6px", fontSize: 15 }}>Where to search</h3>
      <div className="list">
        {automated.map((src) => {
          const on = codes.includes(src.code);
          const co = COMPANY_SOURCES[src.code];
          return (
            <div key={src.code}>
              <label className="row small" style={{ display: "flex" }}>
                <input type="checkbox" style={{ width: "auto" }} checked={on}
                  onChange={(e) => setCodes(e.target.checked ? [...codes, src.code] : codes.filter((c) => c !== src.code))} />
                <b>{src.name}</b>{src.code === "ba_jobsuche" && <span className="muted"> · all employers in Germany (recommended)</span>}
                {co && <span className="muted"> · only the companies you list</span>}
              </label>
              {co && on && (
                <input style={{ marginTop: 4 }} value={companies[src.code] ?? ""} placeholder={co.hint}
                  onChange={(e) => setCompanies({ ...companies, [src.code]: e.target.value })} />
              )}
            </div>
          );
        })}
      </div>
      <div className="row" style={{ marginTop: 10 }}>
        <button className="btn primary" onClick={save}>Save</button>
        {msg && <span className="small muted">{msg}</span>}
      </div>
      <ErrorBox message={err} />
      <p className="small muted" style={{ marginTop: 8 }}>
        LinkedIn and StepStone do not allow automatic searching; add a job from there by hand with “Add job from URL” on
        the Jobs page.
      </p>
    </section>
  );
}

export default function MonitorPage() {
  const configs = useLoad(api.configs);
  const runs = useLoad(api.runs);
  const sources = useLoad(api.sources);
  const alerts = useLoad(() => api.notifications("alerts", "open"));
  const [cfg, setCfg] = useState<SearchConfig | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => { if (configs.data && !cfg) setCfg(configs.data[0] ?? null); }, [configs.data, cfg]);
  const running = runs.data?.some((r) => r.status === "running");
  useEffect(() => {
    if (!running) return;
    const t = setInterval(() => { runs.reload(); }, 2000);
    return () => clearInterval(t);
  }, [running, runs]);

  if (!cfg) return configs.error ? <ErrorBox message={configs.error} /> : <Loading />;
  const last = runs.data?.[0];
  const ba = sources.data?.find((s) => s.code === "ba_jobsuche");
  const searchAlerts = (alerts.data ?? []).filter((a) => SEARCH_COMPONENTS.some((c) => (a.component ?? "").startsWith(c)));
  const baState = !ba ? "…" : ba.label === "Automated" ? "working" : ba.label === "Untested" ? "not run yet" : ba.label;

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Search monitor</h1>
          <p className="sub">Is the job search running, and what did it find?</p>
        </div>
        <button className="btn primary" disabled={busy || running} onClick={async () => {
          setBusy(true); setErr(null);
          try { await api.startRun(cfg.id); runs.reload(); } catch (e) { setErr(errorText(e)); } finally { setBusy(false); }
        }}>{running ? "Searching…" : "Search now"}</button>
      </div>
      <ErrorBox message={err} />

      <div className="grid tiles" style={{ marginBottom: 16 }}>
        <div className="card tile"><div className="n" style={{ fontSize: 18 }}>{last ? dateTime(last.started_at) : "never"}</div>
          <div className="l">Last search{last ? ` · ${last.status}` : ""}</div></div>
        <div className="card tile"><div className="n" style={{ fontSize: 18 }}>{last ? runText(last) : "—"}</div><div className="l">Result</div></div>
        <div className="card tile"><div className="n" style={{ fontSize: 18 }}>
          {cfg.paused_reason ? "paused" : cfg.next_run_at ? dateTime(cfg.next_run_at) : "off"}</div><div className="l">Next automatic search</div></div>
        <div className={`card tile${baState === "working" ? "" : " alert"}`}><div className="n" style={{ fontSize: 18 }}>{baState}</div>
          <div className="l">Bundesagentur source</div></div>
      </div>

      {searchAlerts.length > 0 && (
        <section className="card" style={{ marginBottom: 16, borderColor: "var(--warn)" }}>
          <h2>Problems</h2>
          <div className="list small">
            {searchAlerts.map((a) => (
              <div key={a.id}>
                <span className={`badge ${a.severity === "critical" ? "bad" : "warn"}`}>{a.severity}</span> <strong>{a.title}</strong>
                <div>{a.body}</div>
                {a.remediation && <div className="muted">What to do: {a.remediation}</div>}
              </div>
            ))}
          </div>
        </section>
      )}

      {sources.data && <SearchSettings key={cfg.id} cfg={cfg} sources={sources.data} onSaved={(c) => setCfg({ ...cfg, ...c })} />}
      <ScheduleCard key={`${cfg.id}-${cfg.cron}-${cfg.paused_reason}`} config={cfg}
        onSaved={(c) => setCfg({ ...cfg, cron: c.cron, timezone: c.timezone, allow_overlap: c.allow_overlap,
          schedule_text: c.schedule_text, next_run_at: c.next_run_at, paused_reason: c.paused_reason, last_dispatch: c.last_dispatch })} />

      <section className="card">
        <h2>Recent searches</h2>
        {runs.data && runs.data.length > 0 ? (
          <div className="table-wrap">
            <table>
              <thead><tr><th>When</th><th>Status</th><th>Result</th><th>Per source</th></tr></thead>
              <tbody>
                {runs.data.slice(0, 15).map((r) => {
                  const per = sourceText(r);
                  const runErr = typeof r.summary.error === "string" ? r.summary.error : "";
                  return (
                    <tr key={r.id}>
                      <td>{dateTime(r.started_at)}<div className="small muted">{r.trigger === "schedule" ? "automatic" : "by you"}</div></td>
                      <td><span className={`badge ${r.status === "completed" ? "good" : r.status === "running" ? "accent" : r.status === "partial" ? "warn" : "bad"}`}>{r.status}</span></td>
                      <td className="small">{runText(r)}</td>
                      <td className="small">
                        {per.map((p) => <div key={p.name} style={{ color: p.ok ? undefined : "var(--warn)" }}>{p.name}: {p.text}</div>)}
                        {runErr && <div className="muted">{runErr}</div>}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        ) : <p className="small muted">No searches yet. Press Search now.</p>}
      </section>
    </>
  );
}
