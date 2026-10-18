# 2. Code flow

How a click travels through the code, for the five main journeys. File paths are under `backend/jobpilot/`
unless they start with `frontend/`.

## 0. Every request

```mermaid
sequenceDiagram
  participant B as Browser
  participant W as web (Next.js)
  participant A as api (FastAPI)
  participant DB as PostgreSQL
  B->>W: click → fetch /api/v1/... (cookie + X-Requested-With header)
  W->>A: rewrite (next.config.ts) to http://api:8000/api/v1/...
  A->>A: HardeningMiddleware: size limit, security headers (security.py)
  A->>A: csrf_protect + current_user (api/deps.py): header check, signed cookie, session version
  A->>DB: route handler → domain/orchestrator code
  DB-->>A: rows
  A-->>B: JSON (errors always {"error":{code,message,details}})
```

Typed client for every call: `frontend/src/lib/api.ts`. State-changing calls send an `Idempotency-Key`;
`run_idempotent()` stores the response in the **same transaction**, so a double click applies once.

## 1. Search for jobs

```mermaid
sequenceDiagram
  participant U as You / scheduler
  participant A as api
  participant Q as Redis
  participant K as worker
  participant S as Job sources
  participant DB as PostgreSQL
  U->>A: POST /search-runs  (or beat → tick → scheduler.py)
  A->>DB: start_run(): insert search_runs (unique index blocks a 2nd running one)
  A->>Q: run_search.delay(run_id)
  Q->>K: task
  loop each source, isolated
    K->>S: adapter.fetch(filters) via agents/discovery/http.py (rate limit, retries)
    K->>DB: _ingest(): normalize URL, fingerprint, dedup, insert job + application(discovered)
  end
  K->>K: matching.classify_pending(): rules-v0 or Claude
  K->>DB: job_match_evaluations, transition discovered → classified
  K->>DB: summary, one "N new high-fit jobs" notification
```

Code: `orchestrator/runs.py` (`start_run`, `execute_run`, `_ingest`), adapters in `agents/discovery/adapters/`,
dedup in `domain/dedup.py`. A broken source is recorded in `error_events` and never stops the others.

## 2. Score a job (matching)

1. `orchestrator/matching.py::evaluate()` builds the context: **verified facts only** (`domain/profile.py`).
2. If Claude is on and within budget: `agents/matching/claude_matcher.py` sends the posting and fact ids through
   `ai/claude.py` (`messages.parse` with a Pydantic schema = structured output).
3. Code **discards** any fact id not in your verified facts and any quote not found in the posting.
4. `domain/scoring.py` computes the score with the weights (technical 30, experience 25, track 20, language 10,
   location 15) and the eligibility rules → recommendation *apply / review / low priority / reject*.
5. Cost and tokens go to `task_attempts`; on any AI error the rules matcher is used and the reason is shown.

## 3. Generate CV and cover letter

```mermaid
flowchart LR
  F["factbook.build()<br/>verified facts +<br/>derived durations"] --> G{Claude on?}
  G -- yes --> C["claude_gen.py<br/>claims citing fact ids"]
  G -- no --> T["template.py<br/>fixed sentence patterns"]
  C --> V["verify.py<br/>check every claim"]
  T --> V
  V -- unsupported claim --> D["status: draft<br/>flagged in the UI"]
  V -- all supported --> R["render.py<br/>DOCX + PDF"] --> S["documents row (new version)<br/>→ documents_ready"]
```

Entry: `POST /applications/{id}/documents/generate` → `documents/service.py::generate()`. Editing a sentence
creates a new verified version and cancels any approval. Contact facts (name, email, phone, date of birth) are
rendered by code and **never sent to Claude**.

## 4. Prepare the form, approve, submit

```mermaid
sequenceDiagram
  participant U as You
  participant A as api
  participant P as Playwright (Chromium)
  participant E as Employer site
  participant DB as PostgreSQL
  U->>A: POST /applications/{id}/prepare {apply_url}
  A->>P: inspect_form(): isolated context, only that host, no private IPs
  P->>E: open page, read fields (EXTRACT_JS)
  A->>A: fields.py: classify each field, propose values from verified facts
  A->>P: fill safe fields, attach verified PDFs, screenshot — NEVER submit
  A->>DB: form_fields, → form_prepared → awaiting_user_review
  U->>A: answer remaining fields, POST /approve
  A->>DB: approvals row with hashes of docs + form values
  U->>A: POST /submit (Idempotency-Key)
  A->>DB: submission_attempts row FIRST (pending)
  A->>P: submit_plan(): replay approved values, verify, click submit
  P-->>A: success / validation error / unclear
  A->>DB: succeeded → submitted (+ follow-up in 10 days)<br/>unclear → needs_manual_input + critical alert, no retry
```

Code: `agents/preparation/service.py`, `browser.py`, `fields.py`; hashes in `domain/approvals.py`.
CAPTCHA, sign-in walls, off-site redirects and LinkedIn/StepStone/Indeed/XING become a manual handoff.

## 5. Every minute: scheduler and monitor

```mermaid
flowchart TB
  B[beat: every 60 s] -->|tick| W[worker: scheduler.tick]
  W --> L{pg advisory lock}
  L --> H[heartbeat 'scheduler']
  H --> D[start due searches<br/>schedule_dispatches unique per due time]
  D --> X[mark runs stuck > 30 min as failed]
  X --> P[pause a schedule after 3 failed runs]
  P --> F[follow-up reminders]
  F --> MW[check monitor heartbeat]
  MW --> BK[daily backup at 03:15]
  BK --> HK[hourly housekeeping]
  HK --> E[send due emails, with retries]

  M[monitor: own loop, every 60 s] --> C[17 checks]
  C --> AL[open / refresh / close alerts]
  AL --> MH[heartbeat 'monitor']
```

The scheduler watches the monitor's heartbeat and the monitor watches the scheduler's, so either one stopping
raises an alert. Code: `orchestrator/scheduler.py`, `monitor/checks.py`, `monitor/service.py`, `notify/`.

Next: [3. Block diagrams](03-block-diagrams.md)
