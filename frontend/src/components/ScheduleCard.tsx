"use client";

import { useState } from "react";
import { api, type Cadence, type SearchConfig } from "@/lib/api";
import { dateTime } from "@/lib/format";
import { ErrorBox, errorText } from "@/components/ui";

const DAYS = ["sun", "mon", "tue", "wed", "thu", "fri", "sat"] as const;
const DAY_LABEL: Record<string, string> = { mon: "Monday", tue: "Tuesday", wed: "Wednesday", thu: "Thursday",
  fri: "Friday", sat: "Saturday", sun: "Sunday" };
const OUTCOME: Record<string, [string, string]> = {
  started: ["Started", "good"], skipped_overlap: ["Skipped: previous run still going", "warn"],
  failed_to_start: ["Could not start", "bad"],
};

function fromCron(cron: string | null | undefined): Cadence {
  if (!cron) return { kind: "off", at: "08:00" };
  const [mi, h, dom, mon, dow] = cron.split(" ");
  const at = /^\d+$/.test(h) && /^\d+$/.test(mi) ? `${h.padStart(2, "0")}:${mi.padStart(2, "0")}` : "08:00";
  if (dom === "*" && mon === "*") {
    if (h.startsWith("*/") && dow === "*") return { kind: "every_hours", every_hours: Number(h.slice(2)), at: `00:${mi.padStart(2, "0")}` };
    if (dow === "*") return { kind: "daily", at };
    if (dow === "1-5") return { kind: "weekdays", at };
    if (/^\d$/.test(dow)) return { kind: "weekly", at, weekday: DAYS[Number(dow) % 7] };
  }
  return { kind: "cron", cron };
}

export function ScheduleCard({ config, onSaved }: { config: SearchConfig; onSaved: (c: SearchConfig) => void }) {
  const [cad, setCad] = useState<Cadence>(fromCron(config.cron));
  const [overlap, setOverlap] = useState(config.allow_overlap);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);

  async function act(fn: () => Promise<SearchConfig>, done: string) {
    setBusy(true); setError(null); setMsg(null);
    try { const c = await fn(); onSaved(c); setMsg(done); } catch (e) { setError(errorText(e)); } finally { setBusy(false); }
  }

  const last = config.last_dispatch;
  return (
    <section className="card" style={{ marginBottom: 16 }}>
      <h2>Schedule</h2>
      {config.paused_reason && (
        <div className="warnbox" style={{ marginBottom: 10 }}>
          <strong>Paused.</strong> {config.paused_reason}
          <div style={{ marginTop: 6 }}>
            <button className="btn small primary" disabled={busy}
              onClick={() => act(() => api.resumeSchedule(config.id), "Schedule resumed")}>Resume</button>
            <span className="small muted"> Fix the cause first (try Run search).</span>
          </div>
        </div>
      )}
      <div className="form-grid">
        <label>How often
          <select value={cad.kind} onChange={(e) => setCad({ ...cad, kind: e.target.value as Cadence["kind"] })}>
            <option value="off">Off (I run it by hand)</option>
            <option value="every_hours">Every few hours</option>
            <option value="daily">Every day</option>
            <option value="weekdays">Weekdays</option>
            <option value="weekly">Once a week</option>
            <option value="cron">Custom (cron)</option>
          </select>
        </label>
        {cad.kind === "every_hours" && (
          <label>Every
            <select value={cad.every_hours ?? 6} onChange={(e) => setCad({ ...cad, every_hours: Number(e.target.value) })}>
              {[2, 3, 4, 6, 8, 12].map((h) => <option key={h} value={h}>{h} hours</option>)}
            </select>
          </label>
        )}
        {["daily", "weekdays", "weekly"].includes(cad.kind) && (
          <label>At (Berlin time)<input type="time" value={cad.at ?? "08:00"} onChange={(e) => setCad({ ...cad, at: e.target.value })} /></label>
        )}
        {cad.kind === "weekly" && (
          <label>On
            <select value={cad.weekday ?? "mon"} onChange={(e) => setCad({ ...cad, weekday: e.target.value as Cadence["weekday"] })}>
              {["mon", "tue", "wed", "thu", "fri", "sat", "sun"].map((d) => <option key={d} value={d}>{DAY_LABEL[d]}</option>)}
            </select>
          </label>
        )}
        {cad.kind === "cron" && (
          <label>Cron (5 fields, Berlin time)<input className="mono" value={cad.cron ?? ""} placeholder="30 7 * * 1-5"
            onChange={(e) => setCad({ ...cad, cron: e.target.value })} /></label>
        )}
      </div>
      <label className="row small" style={{ display: "flex", marginTop: 8 }}>
        <input type="checkbox" style={{ width: "auto" }} checked={overlap} onChange={(e) => setOverlap(e.target.checked)} />
        Allow a new run to start while the previous one is still running
      </label>
      <div className="row" style={{ marginTop: 10 }}>
        <button className="btn primary" disabled={busy}
          onClick={() => act(() => api.setSchedule(config.id, { ...cad, timezone: "Europe/Berlin", allow_overlap: overlap }),
            cad.kind === "off" ? "Schedule turned off" : "Schedule saved")}>Save schedule</button>
        <span className="small">{config.schedule_text}</span>
        {config.next_run_at && !config.paused_reason && <span className="small muted">· next run {dateTime(config.next_run_at)}</span>}
      </div>
      {last && (
        <p className="small" style={{ marginTop: 8 }}>
          Last scheduled time {dateTime(last.due_at)}:{" "}
          <span className={`badge ${OUTCOME[last.outcome]?.[1] ?? ""}`}>{OUTCOME[last.outcome]?.[0] ?? last.outcome}</span>
          {last.detail && <span className="muted"> {last.detail}</span>}
        </p>
      )}
      <ErrorBox message={error} />
      {msg && <p className="small muted">{msg}</p>}
      <p className="small muted" style={{ marginTop: 6 }}>
        At most once an hour. If the scheduler was off, missed times are caught up with one run. After three failed
        scheduled runs in a row the schedule pauses and you get an alert.
      </p>
    </section>
  );
}
