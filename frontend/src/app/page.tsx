"use client";

import Link from "next/link";
import { useState } from "react";
import { api } from "@/lib/api";
import { ErrorBox, Loading, useLoad } from "@/components/ui";
import { ImportJob } from "@/components/ImportJob";
import { JobCard } from "@/components/JobCard";
import { KINDS, careerPage, jobSiteLinks } from "@/lib/places";

function SearchElsewhere() {
  const { data: configs } = useLoad(api.configs);
  const cfg = configs?.[0];
  const words = cfg?.filters.keywords.length ? cfg.filters.keywords : ["Softwareentwickler"];
  const cities = cfg?.filters.cities ?? [];
  const radius = Number((cfg?.source_options?.ba_jobsuche as { radius_km?: number } | undefined)?.radius_km ?? 30);
  const companies = cfg?.filters.companies ?? [];
  const [word, setWord] = useState(0);
  const [kind, setKind] = useState("job");
  const [city, setCity] = useState(0);
  if (!cfg) return null;
  const k = KINDS.find((x) => x.code === kind)!;
  const query = `${k.word} ${words[word] ?? words[0]}`.trim();
  return (
    <details className="card" style={{ marginBottom: 12 }}>
      <summary><b>Search Indeed, LinkedIn, StepStone, XING</b> <span className="small muted">
        · they don&apos;t allow automatic searching, so these open your search there</span></summary>
      <div className="row small" style={{ marginTop: 10 }}>
        <select aria-label="Keyword" value={word} onChange={(e) => setWord(Number(e.target.value))} style={{ width: "auto" }}>
          {words.map((w, i) => <option key={w} value={i}>{w}</option>)}
        </select>
        <select aria-label="Kind" value={kind} onChange={(e) => setKind(e.target.value)} style={{ width: "auto" }}>
          {KINDS.map((x) => <option key={x.code} value={x.code}>{x.label}</option>)}
        </select>
        <select aria-label="City" value={city} onChange={(e) => setCity(Number(e.target.value))} style={{ width: "auto" }}>
          {cities.length === 0 && <option value={0}>All of Germany</option>}
          {cities.map((c, i) => <option key={c} value={i}>{c}</option>)}
        </select>
      </div>
      <div className="row" style={{ marginTop: 8 }}>
        {jobSiteLinks(query, cities[city] ?? "", radius).map((l) => (
          <a key={l.name} className="btn" href={l.url} target="_blank" rel="noopener noreferrer nofollow">{l.name} ↗</a>
        ))}
      </div>
      {companies.length > 0 && (
        <>
          <div className="small muted" style={{ marginTop: 10 }}>Career pages of your companies:</div>
          <div className="row" style={{ marginTop: 4 }}>
            {companies.map((c) => {
              const url = careerPage(c);
              return url
                ? <a key={c} className="btn small" href={url} target="_blank" rel="noopener noreferrer nofollow">{c} ↗</a>
                : <a key={c} className="btn small" target="_blank" rel="noopener noreferrer nofollow"
                    href={`https://www.arbeitsagentur.de/jobsuche/suche?was=${encodeURIComponent(`${k.word} ${c}`.trim())}`}>{c} ↗</a>;
            })}
          </div>
        </>
      )}
      <p className="small muted" style={{ marginBottom: 0 }}>Found one you like? Copy its link and use <b>Add job from URL</b>:
        it gets a score, CV and cover letter like the others.</p>
    </details>
  );
}

export default function JobsPage() {
  const [weak, setWeak] = useState(false);
  const [show, setShow] = useState<"all" | "student" | "companies">("all");
  const { data, error, setData, reload } = useLoad(() => api.myJobs(weak), [weak]);
  const visible = (data?.jobs ?? []).filter((j) => show === "all" || (show === "student" ? j.kind !== "job" : !!j.target_company));

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Jobs for you</h1>
          <p className="sub">Real, open jobs that match your verified profile, best first.</p>
        </div>
        <div className="row">
          <label className="row small" style={{ display: "flex" }}>
            <input type="checkbox" style={{ width: "auto" }} checked={weak} onChange={(e) => setWeak(e.target.checked)} />
            Show weaker matches
          </label>
          <ImportJob onImported={() => reload()} />
        </div>
      </div>
      <SearchElsewhere />
      <ErrorBox message={error} />
      {!data ? <Loading /> : data.jobs.length === 0 ? (
        <p className="notice">
          No matching jobs yet. Open <Link href="/monitor">Search monitor</Link> and press <b>Search now</b>.
          Scores use only facts you verified in your <Link href="/settings">profile</Link>.
        </p>
      ) : (
        <>
          <div className="row small" style={{ marginBottom: 8 }}>
            {([["all", "All"], ["student", "Student jobs"], ["companies", "★ My companies"]] as const).map(([v, l]) => (
              <button key={v} className={`btn small${show === v ? " primary" : ""}`} onClick={() => setShow(v)}>{l}</button>
            ))}
            <span className="muted">
              {visible.length} job{visible.length === 1 ? "" : "s"}
              {!weak && data.hidden_weak > 0 && ` · ${data.hidden_weak} weaker or ineligible matches hidden`}
            </span>
          </div>
          {visible.length === 0 && <p className="notice">None in this view yet.</p>}
          {visible.map((j) => (
            <JobCard key={j.application_id} job={j}
              onChange={(nj) => setData({ ...data, jobs: data.jobs.map((x) => (x.application_id === nj.application_id ? nj : x)) })}
              onGone={() => setData({ ...data, jobs: data.jobs.filter((x) => x.application_id !== j.application_id) })} />
          ))}
        </>
      )}
    </>
  );
}
