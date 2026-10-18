"use client";

import { useEffect, useState } from "react";
import { api, type SearchConfig, type SearchRun } from "@/lib/api";
import { dateTime } from "@/lib/format";
import { ErrorBox, Loading, errorText, useLoad } from "@/components/ui";
import { ScheduleCard } from "@/components/ScheduleCard";

const list = (s: string) => s.split(",").map((x) => x.trim()).filter(Boolean);
const SEARCH_COMPONENTS = ["discovery", "scheduler", "queue", "orchestrator"];

function runText(r: SearchRun) {
  const s = r.summary as Record<string, number>;
  if (r.status === "running") return "searching…";
  return `${s.fetched ?? 0} found · ${s.new ?? 0} new`;
}

function SearchSettings({ cfg, onSaved }: { cfg: SearchConfig; onSaved: (c: SearchConfig) => void }) {
  const [keywords, setKeywords] = useState(cfg.filters.keywords.join(", "));
  const [cities, setCities] = useState(cfg.filters.cities.join(", "));
  const [radius, setRadius] = useState(String((cfg.source_options?.ba_jobsuche as { radius_km?: number })?.radius_km ?? 50));
  const [days, setDays] = useState(String(cfg.filters.max_age_days ?? 30));
  const [msg, setMsg] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);

  async function save() {
    setErr(null); setMsg(null);
    try {
      const codes = cfg.source_codes.length ? cfg.source_codes : ["ba_jobsuche"];
      const saved = await api.saveConfig({
        ...cfg, source_codes: codes,
        filters: { ...cfg.filters, keywords: list(keywords), cities: list(cities), max_age_days: Number(days) || 30 },
        source_options: { ...(cfg.source_options ?? {}), ba_jobsuche: { radius_km: Number(radius) || 50 } },
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
      <div className="row" style={{ marginTop: 10 }}>
        <button className="btn primary" onClick={save}>Save</button>
        {msg && <span className="small muted">{msg}</span>}
      </div>
      <ErrorBox message={err} />
      <p className="small muted" style={{ marginTop: 8 }}>
        Source: Bundesagentur für Arbeit (Germany&apos;s official job portal). LinkedIn and StepStone do not allow automatic
        searching; add a job from there by hand with “Add job from URL” on the Jobs page.
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

      <SearchSettings key={cfg.id} cfg={cfg} onSaved={(c) => setCfg({ ...cfg, ...c })} />
      <ScheduleCard key={`${cfg.id}-${cfg.cron}-${cfg.paused_reason}`} config={cfg}
        onSaved={(c) => setCfg({ ...cfg, cron: c.cron, timezone: c.timezone, allow_overlap: c.allow_overlap,
          schedule_text: c.schedule_text, next_run_at: c.next_run_at, paused_reason: c.paused_reason, last_dispatch: c.last_dispatch })} />

      <section className="card">
        <h2>Recent searches</h2>
        {runs.data && runs.data.length > 0 ? (
          <div className="table-wrap">
            <table>
              <thead><tr><th>When</th><th>Status</th><th>Result</th><th>Problem</th></tr></thead>
              <tbody>
                {runs.data.slice(0, 15).map((r) => {
                  const errs = Object.entries(r.summary.sources ?? {}).filter(([, v]) => v.status !== "ok")
                    .map(([k, v]) => `${k}: ${v.error}`).join(", ") || (typeof r.summary.error === "string" ? r.summary.error : "");
                  return (
                    <tr key={r.id}>
                      <td>{dateTime(r.started_at)}<div className="small muted">{r.trigger === "schedule" ? "automatic" : "by you"}</div></td>
                      <td><span className={`badge ${r.status === "completed" ? "good" : r.status === "running" ? "accent" : r.status === "partial" ? "warn" : "bad"}`}>{r.status}</span></td>
                      <td className="small">{runText(r)}</td>
                      <td className="small muted">{errs}</td>
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
