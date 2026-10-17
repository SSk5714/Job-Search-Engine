"use client";

import { useEffect, useMemo, useState } from "react";
import {
  api, type ApplicationDetail, type ClaimResult, type ClaimT, type CVContentT, type DocumentVersion,
  type LetterContentT,
} from "@/lib/api";
import { dateTime } from "@/lib/format";
import { ErrorBox, errorText } from "@/components/ui";

type Ref = { label: string; get: (c: any) => ClaimT; remove: (c: any) => void };

/** Claims in the exact order the backend verifier reports them. */
function claimRefs(kind: DocumentVersion["kind"], content: any): Ref[] {
  const refs: Ref[] = [];
  if (kind === "cv") {
    const c = content as CVContentT;
    refs.push({ label: "Headline", get: (x) => x.headline, remove: () => undefined });
    c.summary.forEach((_, i) => refs.push({ label: "Summary", get: (x) => x.summary[i], remove: (x) => x.summary.splice(i, 1) }));
    c.experience.forEach((blk, b) => blk.bullets.forEach((_, i) => refs.push({
      label: `Experience · ${blk.entry}`, get: (x) => x.experience[b].bullets[i], remove: (x) => x.experience[b].bullets.splice(i, 1),
    })));
    c.projects.forEach((blk, b) => blk.bullets.forEach((_, i) => refs.push({
      label: `Project · ${blk.entry}`, get: (x) => x.projects[b].bullets[i], remove: (x) => x.projects[b].bullets.splice(i, 1),
    })));
  } else {
    const c = content as LetterContentT;
    c.paragraphs.forEach((p, pi) => p.sentences.forEach((_, i) => refs.push({
      label: `Paragraph ${pi + 1}`, get: (x) => x.paragraphs[pi].sentences[i], remove: (x) => x.paragraphs[pi].sentences.splice(i, 1),
    })));
  }
  return refs;
}

const KIND_LABEL = { cv: "CV", cover_letter: "Cover letter" };
const GEN_LABEL = { template: "Template", claude: "Claude", user: "Edited by you" };

export function DocumentEditor({ appId, doc, onSaved }: { appId: string; doc: DocumentVersion; onSaved: (d: ApplicationDetail) => void }) {
  const [content, setContent] = useState<any>(() => structuredClone(doc.content));
  const [dirty, setDirty] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => { setContent(structuredClone(doc.content)); setDirty(false); }, [doc.id, doc.content]);

  const refs = useMemo(() => claimRefs(doc.kind, content), [doc.kind, content]);
  const results: ClaimResult[] = doc.verification.claims ?? [];
  const problems = doc.verification.structure_problems ?? [];

  const update = (fn: (c: any) => void) => {
    const next = structuredClone(content);
    fn(next);
    setContent(next);
    setDirty(true);
  };

  async function save() {
    setBusy(true); setError(null);
    try { onSaved(await api.saveDoc(appId, doc.kind, content)); setDirty(false); }
    catch (e) { setError(errorText(e)); } finally { setBusy(false); }
  }

  return (
    <section className="card" style={{ marginBottom: 16 }}>
      <div className="row" style={{ justifyContent: "space-between" }}>
        <div>
          <h2 style={{ margin: 0 }}>{KIND_LABEL[doc.kind]} · v{doc.version_no}</h2>
          <p className="small muted">{GEN_LABEL[doc.generator]} · {dateTime(doc.created_at)}
            {doc.model_version ? <> · <span className="mono">{doc.model_version}</span></> : null}</p>
        </div>
        <div className="row">
          <span className={`badge ${doc.status === "ready" ? "good" : "warn"}`}>
            {doc.status === "ready" ? "Verified" : "Needs fixes"}</span>
          <a className="btn small" href={api.docUrl(appId, doc.id, "pdf")}>PDF</a>
          <a className="btn small" href={api.docUrl(appId, doc.id, "docx")}>DOCX</a>
        </div>
      </div>
      <p className="small" style={{ margin: "8px 0" }}>
        {doc.verification.passed} of {doc.verification.checked} claims backed by your verified facts.
      </p>
      {problems.length > 0 && <div className="errbox" style={{ marginBottom: 8 }}>{problems.map((p) => <div key={p}>{p}</div>)}</div>}
      {(doc.verification.notes ?? []).map((n) => <p key={n} className="small muted">{n}</p>)}

      {doc.kind === "cover_letter" && (
        <label style={{ marginBottom: 8 }}>Subject
          <input value={(content as LetterContentT).subject} onChange={(e) => update((c) => { c.subject = e.target.value; })} />
        </label>
      )}

      <div className="list">
        {refs.map((r, i) => {
          const claim = r.get(content);
          const res = !dirty ? results[i] : undefined;
          const bad = res?.status === "unsupported";
          return (
            <div key={i} style={{ borderLeft: `3px solid ${bad ? "var(--bad)" : res ? "var(--good)" : "var(--line)"}`, paddingLeft: 10 }}>
              <div className="row small muted" style={{ justifyContent: "space-between" }}>
                <span>{r.label} · {claim.fact_ids.length ? `${claim.fact_ids.length} fact${claim.fact_ids.length > 1 ? "s" : ""}` : "no facts cited"}</span>
                {r.label !== "Headline" && (
                  <button className="btn small danger" onClick={() => update((c) => r.remove(c))} aria-label="Remove sentence">Remove</button>
                )}
              </div>
              <textarea rows={2} value={claim.text} aria-label={`${r.label} text`}
                onChange={(e) => update((c) => { r.get(c).text = e.target.value; })} />
              {bad && <div className="small" style={{ color: "var(--bad)" }}>{res!.reasons.join("; ")}</div>}
            </div>
          );
        })}
      </div>
      <ErrorBox message={error} />
      <div className="row" style={{ marginTop: 12 }}>
        <button className="btn primary" disabled={!dirty || busy} onClick={save}>{busy ? "Verifying…" : "Save as new version"}</button>
        {dirty && <span className="small muted">Saving re-checks every sentence. Editing never adds facts: keep to what the cited facts say.</span>}
      </div>
    </section>
  );
}
