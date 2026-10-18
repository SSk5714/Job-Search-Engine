# 4. Database schema

PostgreSQL 16, created by Alembic migrations `0001`–`0006` (`backend/migrations/versions/`). Models: `backend/jobpilot/db/models.py`. 29 tables in 4 groups. This page is generated from the models, so it matches the code.

## Rules the database itself enforces

| Rule | How |
| --- | --- |
| One active application per job | partial unique index `uq_applications_one_active_per_job` (state not rejected/withdrawn/closed/expired) |
| One running search per saved search (unless overlap allowed) | partial unique index `uq_search_runs_one_running` |
| One valid approval per application | partial unique index `uq_approvals_one_valid` |
| One successful submission per application | partial unique index `uq_submission_one_success` |
| A scheduled time starts only once | unique `(config_id, due_at)` on `schedule_dispatches` |
| No duplicate jobs | unique `url_normalized`; unique `(source_id, external_id)`; `fingerprint` links cross-site duplicates |
| One open alert per problem | partial unique index on `notifications.alert_key` where not resolved |
| A notification is sent once | partial unique index on `notifications.dedup_key` |
| One email per notification | unique `(notification_id, channel)` on `notification_deliveries` |
| A state change applies once | unique `idempotency_key` on `application_state_history` |

Only `domain/transitions.py` changes `applications.state`: it locks the row, checks the rule table and guard, writes `application_state_history` and bumps `state_version`, all in one transaction.


## Identity and profile

```mermaid
erDiagram
  users {
    uuid id PK
    string username
    string password_hash
    int session_version
    timestamptz password_changed_at
  }
  login_attempts {
    uuid id PK
    string username
    string ip
    bool success
    timestamptz at
  }
  candidate_profiles {
    uuid id PK
    uuid user_id FK
    uuid current_version_id FK
  }
  profile_versions {
    uuid id PK
    uuid profile_id FK
    int version_no
    string content_hash
    string note
  }
  profile_facts {
    uuid id PK
    uuid version_id FK
    string category
    string entry
    string key
    text value
    string context
    bool verified
    string source_note
    int sort_order
  }
  users ||--o{ candidate_profiles : "user_id"
  profile_versions ||--o{ candidate_profiles : "current_version_id"
  candidate_profiles ||--o{ profile_versions : "profile_id"
  profile_versions ||--o{ profile_facts : "version_id"
```

| Table | What it holds |
| --- | --- |
| `users` | Your login (Argon2 password hash, session version) |
| `login_attempts` | Every sign-in attempt, for rate limiting (kept 30 days) |
| `candidate_profiles` | Your profile; points at its current version |
| `profile_versions` | Each saved version of your profile (never overwritten) |
| `profile_facts` | One fact per row (skill, job, degree, language...), with verified flag |

## Jobs and searching

```mermaid
erDiagram
  job_sources {
    uuid id PK
    string code
    string name
    string access_mode
    bool enabled
    bool implemented
    int rate_limit_per_min
    text notes
    timestamptz live_verified_at
  }
  search_configs {
    uuid id PK
    string name
    jsonb filters
    jsonb source_codes
    jsonb source_options
    string cron
    bool allow_overlap
    bool enabled
    string timezone
    timestamptz next_run_at
    text paused_reason
    timestamptz paused_at
    timestamptz resumed_at
  }
  schedule_dispatches {
    uuid id PK
    uuid config_id FK
    timestamptz due_at
    string outcome
    uuid run_id FK
    text detail
  }
  search_runs {
    uuid id PK
    uuid config_id FK
    string trigger
    string status
    bool allow_overlap
    timestamptz started_at
    timestamptz finished_at
    jsonb summary
  }
  agent_runs {
    uuid id PK
    uuid run_id FK
    string agent
    string subject
    string status
    timestamptz started_at
    timestamptz finished_at
    jsonb output_summary
  }
  task_attempts {
    uuid id PK
    uuid agent_run_id FK
    int attempt_no
    string status
    string error_code
    int duration_ms
    int ai_tokens_in
    int ai_tokens_out
    numeric ai_cost_usd
  }
  jobs {
    uuid id PK
    uuid source_id FK
    string external_id
    text url
    text url_normalized
    string fingerprint
    uuid duplicate_of_id FK
    string company
    string title
    string country
    string city
    string location_text
    string work_mode
    string employment_type
    string seniority
    jsonb language_reqs
    jsonb skills
    numeric salary_min
    numeric salary_max
    string currency
    date published_at
    timestamptz retrieved_at
    uuid first_seen_run_id FK
    string availability
    timestamptz availability_checked_at
    text description_text
  }
  job_match_evaluations {
    uuid id PK
    uuid job_id FK
    uuid profile_version_id FK
    string model_version
    string matcher
    jsonb weights
    jsonb breakdown
    int score
    string track
    string seniority
    string recommendation
    jsonb eligibility
    jsonb matched_skills
    jsonb missing_skills
    text explanation
    jsonb evidence
  }
  search_configs ||--o{ schedule_dispatches : "config_id"
  search_runs ||--o{ schedule_dispatches : "run_id"
  search_configs ||--o{ search_runs : "config_id"
  search_runs ||--o{ agent_runs : "run_id"
  agent_runs ||--o{ task_attempts : "agent_run_id"
  job_sources ||--o{ jobs : "source_id"
  jobs ||--o{ jobs : "duplicate_of_id"
  search_runs ||--o{ jobs : "first_seen_run_id"
  jobs ||--o{ job_match_evaluations : "job_id"
```

| Table | What it holds |
| --- | --- |
| `job_sources` | Bundesagentur, Greenhouse, Lever, Personio, manual sites, mock |
| `search_configs` | Your saved searches: filters, sources, schedule (cron, time zone, pause) |
| `schedule_dispatches` | One row per scheduled due time; unique, so a time starts only once |
| `search_runs` | Each search execution and its summary |
| `agent_runs` | Each worker step inside a run (one per source, matching, documents) |
| `task_attempts` | Each attempt of a step: status, error code, duration, Claude tokens and cost |
| `jobs` | Every job found, normalized; dedup by URL and fingerprint |
| `job_match_evaluations` | Score, breakdown, evidence for a job against a profile version |

Links to other groups: `job_match_evaluations.profile_version_id` → `profile_versions`.

## Applications

```mermaid
erDiagram
  applications {
    uuid id PK
    uuid job_id FK
    string state
    int state_version
    string decision
    string last_action
    timestamptz last_action_at
    timestamptz submitted_at
    date next_follow_up
    string outcome
    text apply_url
    timestamptz prepared_at
    jsonb preparation
  }
  application_state_history {
    uuid id PK
    uuid application_id FK
    string from_state
    string to_state
    string actor
    text reason
    string idempotency_key
    timestamptz at
  }
  documents {
    uuid id PK
    uuid application_id FK
    string kind
    int version_no
    uuid profile_version_id FK
    string content_hash
    text docx_path
    text pdf_path
    jsonb verification
    string status
    jsonb content
    string generator
    string model_version
  }
  form_fields {
    uuid id PK
    uuid application_id FK
    string field_key
    text label
    string field_type
    string sensitivity
    string category
    text selector
    jsonb options
    bool required
    int position
    text proposed_value
    string value_source
    float confidence
    bool needs_manual
  }
  approvals {
    uuid id PK
    uuid application_id FK
    string decision
    jsonb document_hashes
    string form_hash
    timestamptz approved_at
    timestamptz invalidated_at
    text invalidated_reason
  }
  submission_attempts {
    uuid id PK
    uuid application_id FK
    uuid approval_id FK
    string idempotency_key
    string status
    string mode
    timestamptz started_at
    timestamptz finished_at
    text result
    text evidence_path
  }
  follow_ups {
    uuid id PK
    uuid application_id FK
    date due_on
    text note
    bool done
  }
  recruiter_interactions {
    uuid id PK
    uuid application_id FK
    timestamptz at
    string channel
    text summary
  }
  applications ||--o{ application_state_history : "application_id"
  applications ||--o{ documents : "application_id"
  applications ||--o{ form_fields : "application_id"
  applications ||--o{ approvals : "application_id"
  applications ||--o{ submission_attempts : "application_id"
  approvals ||--o{ submission_attempts : "approval_id"
  applications ||--o{ follow_ups : "application_id"
  applications ||--o{ recruiter_interactions : "application_id"
```

| Table | What it holds |
| --- | --- |
| `applications` | The pipeline item for a job: its state and everything about applying |
| `application_state_history` | Every state change: from, to, who, why |
| `documents` | Every CV / cover-letter version: structured content, verification, file paths |
| `form_fields` | Fields read from an application form, with proposed values and their source |
| `approvals` | Your approval: hashes of the exact documents and form values |
| `submission_attempts` | Each submission: idempotency key, status, evidence screenshot |
| `follow_ups` | Follow-up reminders |
| `recruiter_interactions` | Notes on contact with recruiters |

Links to other groups: `applications.job_id` → `jobs`, `documents.profile_version_id` → `profile_versions`.

## Operations

```mermaid
erDiagram
  notifications {
    uuid id PK
    string kind
    string severity
    string title
    text body
    string channel
    string delivery_status
    int attempts
    string alert_key
    timestamptz read_at
    timestamptz resolved_at
    string dedup_key
    string component
    uuid run_id
    uuid task_id
    text likely_cause
    text remediation
    bool workflow_paused
    string link
    jsonb context
    int occurrences
    timestamptz last_seen_at
    timestamptz acknowledged_at
    string resolved_by
  }
  notification_deliveries {
    uuid id PK
    uuid notification_id FK
    string channel
    string status
    int attempts
    timestamptz next_attempt_at
    timestamptz claimed_at
    timestamptz sent_at
    text last_error
  }
  heartbeats {
    string component PK
    timestamptz beat_at
    int interval_s
    timestamptz started_at
    jsonb detail
  }
  health_checks {
    uuid id PK
    string check_name
    string status
    text detail
    timestamptz at
  }
  error_events {
    uuid id PK
    string component
    string severity
    uuid run_id
    uuid task_id
    string code
    text message
    jsonb context
    timestamptz at
  }
  backups {
    uuid id PK
    string name
    string kind
    string status
    int size_bytes
    jsonb detail
    timestamptz started_at
    timestamptz finished_at
  }
  idempotency_keys {
    string key PK
    string endpoint
    string request_hash
    int status_code
    jsonb response
  }
  app_settings {
    string key PK
    jsonb value
  }
  notifications ||--o{ notification_deliveries : "notification_id"
```

| Table | What it holds |
| --- | --- |
| `notifications` | In-app notifications and monitor alerts (cause, remediation, paused) |
| `notification_deliveries` | Email copies with retry state |
| `heartbeats` | Last sign of life of the scheduler and the monitor |
| `health_checks` | History of health status changes |
| `error_events` | Technical errors (kept 90 days) |
| `backups` | Backup and restore history |
| `idempotency_keys` | Stored responses so a repeated click is applied once (kept 7 days) |
| `app_settings` | Editable settings: scoring weights, AI limits, notifications, monitor thresholds |


## Application states

```mermaid
stateDiagram-v2
  [*] --> discovered
  discovered --> classified: scored
  classified --> approved_for_preparation: you approve
  classified --> rejected
  approved_for_preparation --> documents_ready: CV + letter verified
  documents_ready --> form_prepared: form read and filled
  documents_ready --> awaiting_user_review: manual site
  form_prepared --> awaiting_user_review
  awaiting_user_review --> submitted: your approval + confirmed submission
  awaiting_user_review --> approved_for_preparation: you send it back
  submitted --> follow_up
  submitted --> closed
  follow_up --> closed
  note right of awaiting_user_review: Any active state can also go to\nneeds_manual_input, failed, expired (system)\nor withdrawn (you). Interrupts return\nonly to the state they came from.
```

## Where files live (not in the database)

| What | Where |
| --- | --- |
| CV / cover letter DOCX and PDF, evidence screenshots | `documents` volume (`JOBPILOT_DOCUMENTS_DIR`), paths stored in `documents.docx_path` / `pdf_path` |
| Backups | `backups` volume (`JOBPILOT_BACKUP_DIR`), history in `backups` table |
| Task queue messages | Redis (temporary, not saved) |
