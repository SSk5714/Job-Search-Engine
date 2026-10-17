"use client";

import Link from "next/link";
import { api } from "@/lib/api";
import { REC_LABEL, dateTime } from "@/lib/format";
import { ErrorBox, Loading, Score, StateBadge, useLoad } from "@/components/ui";

const TILES: { key: keyof import("@/lib/api").Dashboard["counts"]; label: string; href: string; focus?: boolean; alert?: boolean }[] = [
  { key: "new_jobs", label: "New jobs this week", href: "/jobs" },
  { key: "high_fit", label: "High fit (75+)", href: "/jobs?min_score=75" },
  { key: "awaiting_review", label: "Awaiting your review", href: "/review", focus: true },
  { key: "documents_ready", label: "Documents ready", href: "/tracker?state=documents_ready" },
  { key: "submitted", label: "Submitted", href: "/tracker?state=submitted" },
  { key: "follow_ups_due", label: "Follow-ups due (7 days)", href: "/tracker" },
  { key: "failed_tasks", label: "Failed tasks", href: "/settings", alert: true },
  { key: "warnings", label: "Active warnings", href: "/settings", alert: true },
];

export default function DashboardPage() {
  const { data, error, loading } = useLoad(api.dashboard);

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Today</h1>
          <p className="sub">
            {data?.last_run
              ? `Last search ${data.last_run.status} · ${dateTime(data.last_run.finished_at ?? data.last_run.started_at)}`
              : "No search has run yet"}
          </p>
        </div>
        <Link className="btn primary" href="/discovery">Run a search</Link>
      </div>
      <ErrorBox message={error} />
      {loading && !data ? <Loading /> : null}
      {data && (
        <>
          <div className="grid tiles" style={{ marginBottom: 20 }}>
            {TILES.map((t) => (
              <Link key={t.key} href={t.href} className={`card tile${t.focus ? " focus" : ""}${t.alert && data.counts[t.key] > 0 ? " alert" : ""}`} style={{ color: "inherit", textDecoration: "none" }}>
                <div className="n">{data.counts[t.key]}</div>
                <div className="l">{t.label}</div>
              </Link>
            ))}
          </div>

          <div className="grid two">
            <section className="card">
              <h2>Best matches waiting for a decision</h2>
              {data.top_jobs.length === 0 ? (
                <p className="notice">
                  No high-fit jobs yet. Scores only use <Link href="/settings">verified profile facts</Link>, so verify your skills first.
                </p>
              ) : (
                <div className="list">
                  {data.top_jobs.map((j) => (
                    <Link key={j.job_id} href={`/jobs?focus=${j.job_id}`} className="row" style={{ justifyContent: "space-between", color: "inherit" }}>
                      <div>
                        <div style={{ fontWeight: 600 }}>{j.title}</div>
                        <div className="small muted">{j.company} · {REC_LABEL[j.recommendation]}</div>
                      </div>
                      <Score value={j.score} />
                    </Link>
                  ))}
                </div>
              )}
              <div className="sep" />
              <h2>Awaiting your review</h2>
              {data.review_queue.length === 0 ? (
                <p className="small muted">Nothing needs your approval right now.</p>
              ) : (
                <div className="list">
                  {data.review_queue.map((a) => (
                    <Link key={a.id} href={`/review?id=${a.id}`} className="row" style={{ justifyContent: "space-between", color: "inherit" }}>
                      <span>{a.role} · <span className="muted">{a.company}</span></span>
                      <StateBadge state={a.state} />
                    </Link>
                  ))}
                </div>
              )}
            </section>

            <section className="card">
              <h2>System</h2>
              {data.recent_errors.length === 0 ? (
                <p className="small"><span className="dot ok" />No errors in the last 7 days</p>
              ) : (
                <div className="list small">
                  {data.recent_errors.map((e, i) => (
                    <div key={i}>
                      <span className={`dot ${e.severity === "critical" ? "down" : "warn"}`} />
                      <strong>{e.component}</strong> · {e.code}
                      <div className="muted">{e.message}</div>
                    </div>
                  ))}
                </div>
              )}
              <div className="sep" />
              <Link href="/settings" className="small">Service health and sources →</Link>
            </section>
          </div>
        </>
      )}
    </>
  );
}
