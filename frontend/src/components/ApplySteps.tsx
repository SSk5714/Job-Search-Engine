"use client";

import Link from "next/link";
import type { ApplicationDetail, DocumentVersion } from "@/lib/api";

function latest(docs: DocumentVersion[], kind: string) {
  return docs.filter((d) => d.kind === kind).sort((a, b) => b.version_no - a.version_no)[0];
}

const AFTER_DOCS = ["documents_ready", "form_prepared", "awaiting_user_review", "submitted", "follow_up", "closed"];
const AFTER_FORM = ["awaiting_user_review", "submitted", "follow_up", "closed"];
const DONE = ["submitted", "follow_up", "closed"];

/** Always-visible guide: where the job is, and what to do next to apply. */
export function ApplySteps({ d }: { d: ApplicationDetail }) {
  const cv = latest(d.documents, "cv");
  const letter = latest(d.documents, "cover_letter");
  const docsOk = cv?.status === "ready" && letter?.status === "ready";
  const mock = d.job.source === "mock";
  const manualSite = /linkedin\.|stepstone\.|indeed\.|xing\./i.test(d.job.url);
  const steps = [
    {
      done: AFTER_DOCS.includes(d.state) || docsOk,
      title: "CV and cover letter verified",
      todo: !cv || !letter
        ? "Press “Generate CV and cover letter” above."
        : <>Read the red notes on each document. Most come from facts that are not verified yet: open{" "}
            <Link href="/settings">Settings &amp; Health</Link>, check your profile and press <b>Verify section</b>,
            then come back and press <b>Regenerate CV and letter</b>.</>,
    },
    {
      done: AFTER_FORM.includes(d.state),
      title: "Application form prepared",
      todo: manualSite
        ? "Paste the job link below and press Prepare form: for this site you apply yourself, JobPilot gives you the verified CV and letter to upload."
        : "Below, paste the link of the employer's application page (from the listing) and press Prepare form. JobPilot fills safe fields; you answer the rest.",
    },
    {
      done: DONE.includes(d.state),
      title: "You approve, then submit",
      todo: "In Final review, approve the exact documents and answers, then press Submit (or apply on the site yourself and press “I submitted it myself”).",
    },
  ];
  const current = steps.findIndex((s) => !s.done);

  return (
    <section className="card" style={{ marginBottom: 16 }}>
      <div className="row" style={{ justifyContent: "space-between", alignItems: "flex-start" }}>
        <h2 style={{ margin: 0 }}>How to apply</h2>
        <a className="btn small" href={d.job.url} target="_blank" rel="noopener noreferrer nofollow">
          Open job listing ↗</a>
      </div>
      <p className="small muted" style={{ margin: "4px 0 10px", wordBreak: "break-all" }}>
        {d.job.source_name} · {d.job.url}
      </p>
      {mock && (
        <div className="warnbox small" style={{ marginBottom: 10 }}>
          <strong>This is a test job from the Mock job board.</strong> The company and link are invented, so you cannot
          apply to it. In <Link href="/discovery">Job Discovery</Link>, untick “Mock job board”, tick “Bundesagentur
          für Arbeit” and press Run search to get real jobs. You can still use this one to practise the steps.
        </div>
      )}
      <ol className="list" style={{ paddingLeft: 18, margin: 0 }}>
        {steps.map((s, i) => (
          <li key={s.title} style={{ opacity: i > current && current !== -1 ? 0.6 : 1 }}>
            <span className={`badge ${s.done ? "good" : i === current ? "warn" : ""}`} style={{ marginRight: 6 }}>
              {s.done ? "done" : i === current ? "next" : "later"}</span>
            <strong>{s.title}</strong>
            {!s.done && i === current && <div className="small" style={{ marginTop: 4 }}>{s.todo}</div>}
          </li>
        ))}
      </ol>
    </section>
  );
}
