"use client";

import Link from "next/link";
import { api } from "@/lib/api";
import { ErrorBox, Loading, StateBadge, useLoad } from "@/components/ui";

export default function ReviewPage() {
  const { data, error, loading } = useLoad(async () => {
    const [awaiting, manual, approved] = await Promise.all([
      api.applications({ state: "awaiting_user_review" }),
      api.applications({ state: "needs_manual_input" }),
      api.applications({ state: "approved_for_preparation" }),
    ]);
    return { queue: [...manual, ...awaiting], approved };
  });

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Application Review</h1>
          <p className="sub">The exact CV, cover letter and form values you approve before anything is submitted.</p>
        </div>
      </div>
      <p className="notice" style={{ marginBottom: 16 }}>
        Document generation (Phase 3) and form preparation (Phase 4) are not built yet, so no application can reach
        this review step today. The backend already blocks submission without an approval bound to the exact document
        and form-value hashes.
      </p>
      <ErrorBox message={error} />
      {loading && !data ? <Loading /> : null}
      {data && (
        <div className="grid two">
          <section className="card">
            <h2>Waiting for you</h2>
            {data.queue.length === 0 ? <p className="small muted">Nothing to review.</p> : (
              <div className="list">
                {data.queue.map((a) => (
                  <div key={a.id} className="row" style={{ justifyContent: "space-between" }}>
                    <span>{a.role} · <span className="muted">{a.company}</span></span>
                    <StateBadge state={a.state} />
                  </div>
                ))}
              </div>
            )}
          </section>
          <section className="card">
            <h2>In preparation</h2>
            {data.approved.length === 0 ? <p className="small muted">Approve jobs in <Link href="/jobs">Job Review</Link> to start preparation.</p> : (
              <div className="list small">
                {data.approved.map((a) => <div key={a.id}>{a.role} · <span className="muted">{a.company}</span></div>)}
              </div>
            )}
          </section>
        </div>
      )}
    </>
  );
}
