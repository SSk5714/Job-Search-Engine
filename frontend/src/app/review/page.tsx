"use client";

import Link from "next/link";
import { Suspense, useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { api, type ApplicationDetail, type DocumentVersion, type TrackerRow } from "@/lib/api";
import { ErrorBox, Loading, Score, StateBadge, errorText, useLoad } from "@/components/ui";
import { DocumentEditor } from "@/components/DocumentEditor";
import { ApplicationForm } from "@/components/ApplicationForm";
import { ApprovalPanel } from "@/components/ApprovalPanel";

const STATES = ["approved_for_preparation", "documents_ready", "form_prepared", "awaiting_user_review", "needs_manual_input", "submitted"];

function latest(docs: DocumentVersion[], kind: string): DocumentVersion | undefined {
  return docs.filter((d) => d.kind === kind).sort((a, b) => b.version_no - a.version_no)[0];
}

function Detail({ id, onChanged }: { id: string; onChanged: () => void }) {
  const [d, setD] = useState<ApplicationDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => { setD(null); api.application(id).then(setD).catch((e) => setError(errorText(e))); }, [id]);

  async function generate() {
    setBusy(true); setError(null);
    try { setD(await api.generateDocs(id)); onChanged(); } catch (e) { setError(errorText(e)); } finally { setBusy(false); }
  }

  if (!d) return error ? <ErrorBox message={error} /> : <Loading />;
  const cv = latest(d.documents, "cv");
  const letter = latest(d.documents, "cover_letter");
  const canGenerate = ["approved_for_preparation", "documents_ready"].includes(d.state);
  const history = d.documents.filter((x) => x.status === "superseded").sort((a, b) => b.version_no - a.version_no);

  return (
    <div>
      <section className="card" style={{ marginBottom: 16 }}>
        <div className="row" style={{ justifyContent: "space-between", alignItems: "flex-start" }}>
          <div>
            <h2 style={{ marginBottom: 2 }}>{d.role}</h2>
            <p className="small muted">{d.company} · {d.city ?? ""} {d.country ?? ""} · <a href={d.source_url} target="_blank" rel="noopener noreferrer nofollow">listing ↗</a></p>
          </div>
          <div className="row"><StateBadge state={d.state} /><Score value={d.score} /></div>
        </div>
        <ErrorBox message={error} />
        <div className="row" style={{ marginTop: 10 }}>
          {canGenerate && (
            <button className="btn primary" disabled={busy} onClick={generate}>
              {busy ? "Generating and verifying…" : cv ? "Regenerate CV and letter" : "Generate CV and cover letter"}
            </button>
          )}
          <span className="small muted">
            Built only from your verified facts. Every sentence is checked; the job moves to “Documents ready” when both pass.
          </span>
        </div>
      </section>

      {!cv && !letter && <p className="notice">No documents yet.</p>}
      {cv && <DocumentEditor appId={id} doc={cv} onSaved={(x) => { setD(x); onChanged(); }} />}
      {letter && <DocumentEditor appId={id} doc={letter} onSaved={(x) => { setD(x); onChanged(); }} />}

      {cv && letter && <ApplicationForm d={d} onChange={(x) => { setD(x); onChanged(); }} />}
      <ApprovalPanel d={d} onChange={(x) => { setD(x); onChanged(); }} />

      {history.length > 0 && (
        <section className="card" style={{ marginBottom: 16 }}>
          <h2>Earlier versions</h2>
          <div className="list small">
            {history.map((h) => (
              <div key={h.id} className="row" style={{ justifyContent: "space-between" }}>
                <span>{h.kind === "cv" ? "CV" : "Cover letter"} v{h.version_no} · {h.generator} · {h.verification.passed}/{h.verification.checked} verified</span>
                <span className="row"><a href={api.docUrl(id, h.id, "pdf")}>PDF</a><a href={api.docUrl(id, h.id, "docx")}>DOCX</a></span>
              </div>
            ))}
          </div>
        </section>
      )}


    </div>
  );
}

function ReviewInner() {
  const params = useSearchParams();
  const router = useRouter();
  const selected = params.get("id");
  const { data, error, reload } = useLoad(async () => {
    const lists = await Promise.all(STATES.map((s) => api.applications({ state: s })));
    return lists.flat() as TrackerRow[];
  });
  useEffect(() => {
    if (!selected && data && data.length) router.replace(`/review?id=${data[0].id}`);
  }, [selected, data, router]);

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Application Review</h1>
          <p className="sub">Tailored CV and cover letter for each job you approved, with every claim checked against your profile.</p>
        </div>
      </div>
      <ErrorBox message={error} />
      {!data ? <Loading /> : data.length === 0 ? (
        <p className="notice">Nothing in preparation. Approve a job in <Link href="/jobs">Job Review</Link> first.</p>
      ) : (
        <div className="grid" style={{ gridTemplateColumns: "minmax(0, 260px) minmax(0, 1fr)" }}>
          <aside className="card list" style={{ alignSelf: "start" }}>
            {data.map((a) => (
              <Link key={a.id} href={`/review?id=${a.id}`} style={{ color: "inherit", textDecoration: "none",
                fontWeight: a.id === selected ? 600 : 400 }}>
                <div>{a.role}</div>
                <div className="small muted">{a.company}</div>
                <StateBadge state={a.state} />
              </Link>
            ))}
          </aside>
          <div>{selected && <Detail id={selected} onChanged={reload} />}</div>
        </div>
      )}
    </>
  );
}

export default function ReviewPage() {
  return <Suspense fallback={<Loading />}><ReviewInner /></Suspense>;
}
