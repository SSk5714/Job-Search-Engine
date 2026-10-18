"use client";

import { api, type MyJob } from "@/lib/api";
import { date } from "@/lib/format";
import { ErrorBox, Loading, useLoad } from "@/components/ui";

const OUTCOMES = [["", "Waiting for reply"], ["interview", "Interview"], ["offer", "Offer"], ["rejected", "Rejected"],
  ["no_reply", "No reply"], ["withdrawn", "I withdrew"]] as const;

function Row({ job, onChange }: { job: MyJob; onChange: (j: MyJob) => void }) {
  const cv = job.documents.cv, letter = job.documents.cover_letter;
  const due = job.next_follow_up && !job.outcome && new Date(job.next_follow_up) <= new Date();
  return (
    <tr>
      <td>
        <strong>{job.title}</strong>
        <div className="small muted">{job.company}{job.city ? ` · ${job.city}` : ""}</div>
      </td>
      <td className="small">{date(job.applied_on)}</td>
      <td className="small">
        <a href={job.url} target="_blank" rel="noopener noreferrer nofollow">Job listing ↗</a>
        {cv && <> · <a href={api.docUrl(job.application_id, cv.id, "pdf")}>CV sent</a></>}
        {letter && <> · <a href={api.docUrl(job.application_id, letter.id, "pdf")}>letter</a></>}
      </td>
      <td>
        <select aria-label={`Status for ${job.company}`} value={job.outcome ?? ""}
          onChange={async (e) => onChange(await api.updateHistory(job.application_id, { outcome: e.target.value || null }))}>
          {OUTCOMES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
        </select>
      </td>
      <td className="small">
        {job.outcome ? "—" : <>
          <input type="date" aria-label="Follow up on" value={job.next_follow_up ?? ""} style={{ width: 150 }}
            onChange={async (e) => onChange(await api.updateHistory(job.application_id, { next_follow_up: e.target.value || null }))} />
          {due && <div className="badge warn" style={{ marginTop: 4 }}>follow up now</div>}
        </>}
      </td>
    </tr>
  );
}

export default function HistoryPage() {
  const { data, error, setData } = useLoad(api.myHistory);
  return (
    <>
      <div className="page-head">
        <div>
          <h1>Applied</h1>
          <p className="sub">Every job you applied to, with its link and the documents you sent. Update the status when you hear back.</p>
        </div>
      </div>
      <ErrorBox message={error} />
      {!data ? <Loading /> : data.length === 0 ? (
        <p className="notice">Nothing yet. On <b>Jobs</b>, press <b>I applied ✓</b> after applying and it appears here.</p>
      ) : (
        <section className="card">
          <div className="table-wrap">
            <table>
              <thead><tr><th>Job</th><th>Applied</th><th>Links</th><th>Status</th><th>Follow up</th></tr></thead>
              <tbody>
                {data.map((j) => <Row key={j.application_id} job={j}
                  onChange={(nj) => setData(data.map((x) => (x.application_id === nj.application_id ? nj : x)))} />)}
              </tbody>
            </table>
          </div>
        </section>
      )}
    </>
  );
}
