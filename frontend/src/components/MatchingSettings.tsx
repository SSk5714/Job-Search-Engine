"use client";

import { useEffect, useState } from "react";
import { api, type AISettings, type ScoringSettings } from "@/lib/api";
import { ErrorBox, Loading, errorText, useLoad } from "@/components/ui";

const LABELS: Record<string, string> = {
  technical: "Technical skills",
  experience: "Experience level",
  track: "Career track",
  language: "Language fit",
  location: "Location & eligibility",
};

export function MatchingSettings() {
  const scoring = useLoad(api.scoring);
  const ai = useLoad(api.ai);
  const [sc, setSc] = useState<ScoringSettings | null>(null);
  const [a, setA] = useState<AISettings | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);

  useEffect(() => { if (scoring.data) setSc(scoring.data); }, [scoring.data]);
  useEffect(() => { if (ai.data) setA(ai.data); }, [ai.data]);
  if (!sc || !a) return scoring.error || ai.error ? <ErrorBox message={scoring.error ?? ai.error} /> : <Loading />;

  const total = Object.values(sc.weights).reduce((x, y) => x + y, 0);

  async function save() {
    setErr(null); setMsg(null);
    try {
      await api.saveScoring(sc!);
      setA(await api.saveAi(a!));
      setMsg("Saved. New evaluations use these settings; press Re-score in Job Review to update existing ones.");
      scoring.reload();
    } catch (e) { setErr(errorText(e)); }
  }

  return (
    <section className="card" style={{ marginBottom: 16 }}>
      <div className="row" style={{ justifyContent: "space-between" }}>
        <h2 style={{ margin: 0 }}>Matching</h2>
        <button className="btn primary" onClick={save} disabled={total !== 100}>Save matching settings</button>
      </div>
      <ErrorBox message={err} />
      {msg && <p className="small muted">{msg}</p>}

      <div className="grid two" style={{ marginTop: 12 }}>
        <div>
          <div className="small muted" style={{ marginBottom: 6 }}>Score weights (must total 100; now {total})</div>
          <div className="list">
            {Object.entries(sc.weights).map(([k, v]) => (
              <label key={k} className="row" style={{ display: "flex", color: "var(--ink)", flexWrap: "nowrap" }}>
                <span style={{ minWidth: 170 }}>{LABELS[k] ?? k}</span>
                <input type="range" min={0} max={60} value={v} style={{ flex: 1 }}
                  onChange={(e) => setSc({ ...sc, weights: { ...sc.weights, [k]: Number(e.target.value) } })} />
                <span className="mono" style={{ minWidth: 28, textAlign: "right" }}>{v}</span>
              </label>
            ))}
          </div>
          <div className="form-grid" style={{ gridTemplateColumns: "1fr 1fr", marginTop: 10 }}>
            <label>Recommend applying from<input type="number" min={1} max={100} value={sc.thresholds.apply}
              onChange={(e) => setSc({ ...sc, thresholds: { ...sc.thresholds, apply: Number(e.target.value) } })} /></label>
            <label>Manual review from<input type="number" min={0} max={99} value={sc.thresholds.review}
              onChange={(e) => setSc({ ...sc, thresholds: { ...sc.thresholds, review: Number(e.target.value) } })} /></label>
          </div>
          <p className="small muted" style={{ marginTop: 6 }}>Eligibility rules always apply on top: a failed rule rejects, an uncertain one caps at manual review.</p>
        </div>

        <div>
          <div className="small muted" style={{ marginBottom: 6 }}>Claude</div>
          <p className="small" style={{ marginBottom: 8 }}>
            <span className={`dot ${a.api_key_configured ? "ok" : "warn"}`} />
            {a.api_key_configured
              ? <>API key configured · model <span className="mono">{a.model}</span> · active matcher: <strong>{a.active_matcher}</strong></>
              : <>No API key. Set <span className="mono">JOBPILOT_ANTHROPIC_API_KEY</span> on the server; rule-based matching is used meanwhile.</>}
          </p>
          <div className="form-grid" style={{ gridTemplateColumns: "1fr" }}>
            <label>Matcher
              <select value={a.matcher} onChange={(e) => setA({ ...a, matcher: e.target.value as AISettings["matcher"] })}>
                <option value="auto">Claude when a key is configured (recommended)</option>
                <option value="claude">Claude</option>
                <option value="rules">Rules only (no AI)</option>
              </select>
            </label>
            <label>Max Claude evaluations per search run
              <input type="number" min={0} max={500} value={a.max_ai_jobs_per_run}
                onChange={(e) => setA({ ...a, max_ai_jobs_per_run: Number(e.target.value) })} /></label>
            <label>Daily budget (USD)
              <input type="number" min={0} max={50} step={0.1} value={a.daily_budget_usd}
                onChange={(e) => setA({ ...a, daily_budget_usd: Number(e.target.value) })} /></label>
          </div>
          <p className="small muted" style={{ marginTop: 6 }}>Spent today: ${(a.spent_today_usd ?? 0).toFixed(4)}. When a limit is hit, remaining jobs use rules and a notice is logged.</p>
        </div>
      </div>
    </section>
  );
}
