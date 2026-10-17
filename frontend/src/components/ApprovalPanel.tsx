"use client";

import { useState } from "react";
import { api, type ApplicationDetail, type DocumentVersion } from "@/lib/api";
import { dateTime } from "@/lib/format";
import { ErrorBox, errorText } from "@/components/ui";

function latest(docs: DocumentVersion[], kind: string) {
  return docs.filter((x) => x.kind === kind).sort((a, b) => b.version_no - a.version_no)[0];
}

const ATTEMPT_LABEL = { succeeded: "Submitted", failed: "Not sent", unknown: "Unclear — check", pending: "In progress" };
const ATTEMPT_TONE = { succeeded: "good", failed: "bad", unknown: "warn", pending: "accent" };

export function ApprovalPanel({ d, onChange }: { d: ApplicationDetail; onChange: (d: ApplicationDetail) => void }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [note, setNote] = useState("");
  const manual = d.preparation?.mode === "manual";
  const cv = latest(d.documents, "cv");
  const letter = latest(d.documents, "cover_letter");
  const ev = d.job.evaluation;
  const warnings = [...(ev?.eligibility.failed ?? []), ...(ev?.eligibility.uncertain ?? [])];
  const unknown = d.submission_attempts.find((a) => a.status === "unknown");
  const docsOk = cv?.status === "ready" && letter?.status === "ready";
  const canApprove = d.state === "awaiting_user_review" && !d.approval && d.unresolved_fields.length === 0 && docsOk;

  async function act(fn: () => Promise<ApplicationDetail>) {
    setBusy(true); setError(null);
    try { onChange(await fn()); } catch (e) { setError(errorText(e)); } finally { setBusy(false); }
  }

  if (!["awaiting_user_review", "needs_manual_input", "submitted", "follow_up", "closed"].includes(d.state)) return null;

  return (
    <section className="card" style={{ marginBottom: 16, borderColor: d.approval ? "var(--good)" : undefined }}>
      <h2>Final review</h2>

      {unknown && d.state === "needs_manual_input" && (
        <div className="errbox" style={{ marginBottom: 12 }}>
          <strong>We could not confirm whether your application arrived.</strong> {unknown.result}
          <div className="row" style={{ marginTop: 8 }}>
            {unknown.evidence && <a className="btn small" href={api.evidenceUrl(d.id, unknown.evidence)} target="_blank">What the page showed</a>}
            <input placeholder="Note (optional)" value={note} onChange={(e) => setNote(e.target.value)} style={{ maxWidth: 220 }} />
            <button className="btn small primary" disabled={busy} onClick={() => act(() => api.confirmOutcome(d.id, true, note))}>It arrived</button>
            <button className="btn small" disabled={busy} onClick={() => act(() => api.confirmOutcome(d.id, false, note))}>It did not arrive</button>
          </div>
        </div>
      )}

      <table className="small" style={{ marginBottom: 10 }}>
        <tbody>
          <tr><td className="muted">Job</td><td>{d.role} · {d.company}{ev ? ` · score ${ev.score}` : ""}</td></tr>
          <tr><td className="muted">CV</td><td>{cv ? `v${cv.version_no} · ${cv.status === "ready" ? "verified" : "needs fixes"} · ${cv.content_hash.slice(0, 10)}` : "missing"}</td></tr>
          <tr><td className="muted">Cover letter</td><td>{letter ? `v${letter.version_no} · ${letter.status === "ready" ? "verified" : "needs fixes"} · ${letter.content_hash.slice(0, 10)}` : "missing"}</td></tr>
          <tr><td className="muted">Form</td><td>{manual ? "You apply on the site yourself" : `${d.form_fields.length} fields · ${d.unresolved_fields.length} unanswered`}</td></tr>
          <tr><td className="muted">Sent to</td><td className="mono" style={{ wordBreak: "break-all" }}>{d.apply_url ?? "—"}</td></tr>
        </tbody>
      </table>

      {d.unresolved_fields.length > 0 && <div className="warnbox small" style={{ marginBottom: 8 }}>Still to answer: {d.unresolved_fields.join(", ")}</div>}
      {warnings.length > 0 && <div className="warnbox small" style={{ marginBottom: 8 }}>{warnings.map((w) => <div key={w}>{w}</div>)}</div>}
      <ErrorBox message={error} />

      {d.state === "awaiting_user_review" && !d.approval && (
        <button className="btn primary" disabled={!canApprove || busy} onClick={() => act(() => api.approve(d.id))}>
          Approve these exact documents and answers
        </button>
      )}
      {d.state === "awaiting_user_review" && d.approval && (
        <div className="row">
          <span className="badge good">Approved {dateTime(d.approval.approved_at)}</span>
          {!manual ? (
            <button className="btn primary" disabled={busy} onClick={() => {
              if (confirm(`Send your application to ${d.company} now? This submits the form at ${d.preparation?.host}.`)) {
                act(() => api.submit(d.id));
              }
            }}>{busy ? "Submitting…" : "Submit application now"}</button>
          ) : (
            <>
              <input placeholder="How you applied (optional)" value={note} onChange={(e) => setNote(e.target.value)} style={{ maxWidth: 240 }} />
              <button className="btn primary" disabled={busy} onClick={() => act(() => api.markSubmitted(d.id, note))}>I submitted it myself</button>
            </>
          )}
          <span className="small muted">Changing any document or answer cancels this approval.</span>
        </div>
      )}

      {d.submission_attempts.length > 0 && (
        <div className="list small" style={{ marginTop: 12 }}>
          {d.submission_attempts.map((a) => (
            <div key={a.id} className="row">
              <span className={`badge ${ATTEMPT_TONE[a.status]}`}>{ATTEMPT_LABEL[a.status]}</span>
              <span>{dateTime(a.started_at)} · {a.mode === "manual" ? "by you" : "via JobPilot"}{a.result ? ` · ${a.result}` : ""}</span>
              {a.evidence && <a href={api.evidenceUrl(d.id, a.evidence)} target="_blank">screenshot</a>}
            </div>
          ))}
        </div>
      )}
    </section>
  );
}
