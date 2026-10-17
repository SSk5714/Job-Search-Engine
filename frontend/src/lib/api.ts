// Typed client for the JobPilot API. Every write sends the CSRF header; state
// changes also send a fresh Idempotency-Key so a double click applies once.

export type State =
  | "discovered" | "classified" | "approved_for_preparation" | "documents_ready" | "form_prepared"
  | "awaiting_user_review" | "submitted" | "follow_up" | "closed" | "rejected" | "failed" | "expired"
  | "withdrawn" | "needs_manual_input";

export interface Evaluation {
  id: string;
  score: number;
  breakdown: Record<string, number>;
  weights: Record<string, number>;
  track: string;
  seniority: string;
  recommendation: "apply" | "review" | "low_priority" | "reject";
  eligibility: { failed: string[]; uncertain: string[]; requirements?: Requirement[];
                 validation?: { dropped_skill_matches?: string[] } };
  matched_skills: string[];
  missing_skills: string[];
  explanation: string;
  evidence: { criterion: string; job_quote: string; fact_id: string | null; skill?: string }[];
  model_version: string;
  matcher?: "rules" | "claude";
}

export interface Requirement {
  text: string;
  category: string;
  mandatory: boolean;
  status: "met" | "not_met" | "unknown";
  fact_id: string | null;
  job_quote: string;
}

export interface Job {
  id: string;
  company: string;
  title: string;
  country: string | null;
  city: string | null;
  location_text: string | null;
  work_mode: string | null;
  employment_type: string | null;
  seniority: string | null;
  skills: string[];
  language_reqs: { language: string; level: string; mandatory: boolean }[];
  salary_min: number | null;
  salary_max: number | null;
  currency: string | null;
  published_at: string | null;
  retrieved_at: string;
  availability: string;
  url: string;
  source: string;
  source_name: string;
  duplicate_of_id: string | null;
  description_text?: string;
  evaluation: Evaluation | null;
  application: { id: string; state: State; state_version: number; decision: string | null } | null;
}

export interface TrackerRow {
  id: string;
  job_id: string;
  company: string;
  role: string;
  country: string | null;
  city: string | null;
  score: number | null;
  state: State;
  state_version: number;
  decision: string | null;
  applied_on: string | null;
  last_action: string | null;
  last_action_at: string | null;
  next_follow_up: string | null;
  outcome: string | null;
  source_url: string;
  discovered_at: string;
}

export interface ApplicationDetail extends TrackerRow {
  job: Job;
  history: { from_state: State | null; to_state: State; actor: string; reason: string | null; at: string }[];
  documents: DocumentVersion[];
  form_fields: FormFieldT[];
  unresolved_fields: string[];
  apply_url: string | null;
  prepared_at: string | null;
  preparation: {
    mode?: "browser" | "manual"; reason?: string; host?: string; screenshot?: string; blocked_requests?: string[];
    fields?: number; auto_filled?: number; needs_you?: number; hints?: Record<string, string>;
  };
  submission_attempts: AttemptT[];
  approval: { id: string; approved_at: string } | null;
  allowed_transitions: State[];
}

export interface FormFieldT {
  id: string; field_key: string; label: string; field_type: string; category: string;
  sensitivity: "normal" | "sensitive" | "legal"; proposed_value: string | null; value_source: string | null;
  needs_manual: boolean; required: boolean; options: { value: string; label: string }[]; confidence: number;
  position: number;
}
export interface AttemptT {
  id: string; status: "pending" | "succeeded" | "failed" | "unknown"; mode: "browser" | "manual";
  result: string | null; evidence: string | null; started_at: string; finished_at: string | null;
}
export interface ClaimT { text: string; fact_ids: string[] }
export interface ClaimResult { where: string; text: string; fact_ids: string[]; status: "ok" | "unsupported"; reasons: string[] }
export interface CVContentT {
  headline: ClaimT;
  summary: ClaimT[];
  skill_groups: { name: string; skill_fact_ids: string[] }[];
  experience: { entry: string; bullets: ClaimT[] }[];
  projects: { entry: string; bullets: ClaimT[] }[];
  education_entries: string[];
  certification_fact_ids: string[];
}
export interface LetterContentT {
  subject: string;
  salutation: string;
  paragraphs: { sentences: ClaimT[] }[];
  sign_off: string;
}
export interface DocumentVersion {
  id: string;
  kind: "cv" | "cover_letter";
  version_no: number;
  status: "draft" | "ready" | "superseded";
  content_hash: string;
  generator: "template" | "claude" | "user";
  model_version: string | null;
  created_at: string;
  content: CVContentT | LetterContentT;
  verification: {
    claims: ClaimResult[];
    unsupported_claims: string[];
    structure_problems?: string[];
    notes?: string[];
    checked: number;
    passed: number;
  };
}

export interface Fact {
  id?: string;
  entry?: string | null;
  category: string;
  key: string;
  value: string;
  context: string | null;
  verified?: boolean;
  source_note: string | null;
}

export interface Profile {
  version_id: string;
  version_no: number;
  note: string | null;
  created_at: string;
  facts: Fact[];
  verified_count: number;
  filled_count: number;
  total_count: number;
}

export interface Filters {
  countries: string[];
  cities: string[];
  keywords: string[];
  tracks: string[];
  work_modes: string[];
  employment_types: string[];
  seniority: string[];
  max_age_days: number | null;
}

export interface SearchConfig {
  id: string;
  name: string;
  filters: Filters;
  source_codes: string[];
  source_options: Record<string, Record<string, unknown>>;
  cron: string | null;
  allow_overlap: boolean;
  enabled: boolean;
}

export interface SearchRun {
  id: string;
  config_id: string;
  trigger: string;
  status: "running" | "completed" | "partial" | "failed" | "cancelled";
  started_at: string;
  finished_at: string | null;
  summary: Record<string, unknown> & { sources?: Record<string, { status: string; error?: string }> };
}

export interface Source {
  code: string;
  name: string;
  access_mode: string;
  implemented: boolean;
  enabled: boolean;
  label: "Automated" | "Untested" | "Manual" | "Mock" | "Planned";
  notes: string | null;
  live_verified_at: string | null;
}

export interface ScoringSettings {
  weights: Record<"technical" | "experience" | "track" | "language" | "location", number>;
  thresholds: { apply: number; review: number };
  version_tag?: string;
}

export interface AISettings {
  matcher: "auto" | "claude" | "rules";
  max_ai_jobs_per_run: number;
  daily_budget_usd: number;
  api_key_configured?: boolean;
  model?: string;
  active_matcher?: "claude" | "rules";
  spent_today_usd?: number;
}

export interface ImportIn {
  url: string;
  title?: string;
  company?: string;
  city?: string;
  country?: string;
  work_mode?: "onsite" | "hybrid" | "remote";
  description?: string;
}

export interface Dashboard {
  counts: Record<
    "new_jobs" | "high_fit" | "awaiting_review" | "documents_ready" | "submitted" | "follow_ups_due"
    | "failed_tasks" | "warnings",
    number
  >;
  review_queue: TrackerRow[];
  top_jobs: { application_id: string; job_id: string; company: string; title: string; score: number;
              recommendation: string }[];
  last_run: SearchRun | null;
  recent_errors: { component: string; severity: string; code: string; message: string; at: string }[];
}

export interface HealthDetails {
  checks: Record<string, { status: string; detail?: string }>;
  sources: Source[];
}

export class ApiError extends Error {
  constructor(public status: number, public code: string, message: string, public details: unknown = {}) {
    super(message);
  }
}

const BASE = "/api/v1";

async function request<T>(method: string, path: string, body?: unknown, idempotent = false): Promise<T> {
  const headers: Record<string, string> = { "X-Requested-With": "jobpilot" };
  if (body !== undefined) headers["Content-Type"] = "application/json";
  if (idempotent) headers["Idempotency-Key"] = crypto.randomUUID();
  const res = await fetch(`${BASE}${path}`, {
    method,
    headers,
    body: body === undefined ? undefined : JSON.stringify(body),
    credentials: "same-origin",
    cache: "no-store",
  });
  if (res.status === 401 && typeof window !== "undefined" && !path.startsWith("/auth/")) {
    window.location.href = "/login";
  }
  const data = res.headers.get("content-type")?.includes("json") ? await res.json() : null;
  if (!res.ok) {
    const err = data?.error ?? {};
    throw new ApiError(res.status, err.code ?? "http_error", err.message ?? res.statusText, err.details);
  }
  return data as T;
}

const qs = (params: Record<string, string | number | boolean | undefined | null>) => {
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) if (v !== undefined && v !== null && v !== "") p.set(k, String(v));
  const s = p.toString();
  return s ? `?${s}` : "";
};

export const api = {
  login: (username: string, password: string) => request<{ username: string }>("POST", "/auth/login", { username, password }),
  logout: () => request("POST", "/auth/logout", {}),
  me: () => request<{ username: string }>("GET", "/auth/me"),

  dashboard: () => request<Dashboard>("GET", "/dashboard"),
  health: () => request<HealthDetails>("GET", "/health/details"),

  profile: () => request<Profile>("GET", "/profile"),
  saveProfile: (facts: Fact[], note?: string) =>
    request<Profile>("PUT", "/profile", {
      facts: facts.map(({ category, entry, key, value, context, source_note }) => ({ category, entry: entry || null, key, value, context, source_note })),
      note,
    }, true),
  verifyFact: (id: string, verified: boolean) => request<Fact>("POST", `/profile/facts/${id}/verify`, { verified }),

  sources: () => request<Source[]>("GET", "/sources"),
  configs: () => request<SearchConfig[]>("GET", "/search-configs"),
  saveConfig: (c: Omit<SearchConfig, "id"> & { id?: string }) =>
    c.id ? request<SearchConfig>("PATCH", `/search-configs/${c.id}`, c) : request<SearchConfig>("POST", "/search-configs", c),
  runs: () => request<SearchRun[]>("GET", "/search-runs"),
  startRun: (config_id: string) => request<SearchRun>("POST", "/search-runs", { config_id }, true),

  jobs: (p: { state?: string; track?: string; min_score?: number; q?: string } = {}) =>
    request<{ total: number; items: Job[] }>("GET", `/jobs${qs(p)}`),
  job: (id: string) => request<Job>("GET", `/jobs/${id}`),
  importUrl: (body: ImportIn) => request<{ outcome: string; job: Job }>("POST", "/jobs/import-url", body, true),
  recheck: (id: string) => request<Job & { availability: string }>("POST", `/jobs/${id}/recheck`, {}),
  rescore: () => request<{ rescored: number; claude?: number; rules?: number }>("POST", "/jobs/rescore", {}, true),
  scoring: () => request<ScoringSettings>("GET", "/settings/scoring"),
  saveScoring: (s: ScoringSettings) => request<ScoringSettings>("PUT", "/settings/scoring", { weights: s.weights, thresholds: s.thresholds }),
  ai: () => request<AISettings>("GET", "/settings/ai"),
  saveAi: (a: AISettings) => request<AISettings>("PUT", "/settings/ai", { matcher: a.matcher, max_ai_jobs_per_run: a.max_ai_jobs_per_run, daily_budget_usd: a.daily_budget_usd }),
  decide: (id: string, decision: "approve" | "reject" | "later", reason?: string) =>
    request<Job>("POST", `/jobs/${id}/decision`, { decision, reason }, true),

  applications: (p: { state?: string; q?: string; country?: string; include_unreviewed?: boolean } = {}) =>
    request<TrackerRow[]>("GET", `/applications${qs(p)}`),
  application: (id: string) => request<ApplicationDetail>("GET", `/applications/${id}`),
  transition: (id: string, to_state: State, reason?: string, expected_version?: number) =>
    request<ApplicationDetail>("POST", `/applications/${id}/transitions`, { to_state, reason, expected_version }, true),
  track: (id: string, patch: { next_follow_up?: string | null; outcome?: string | null }) =>
    request<ApplicationDetail>("PATCH", `/applications/${id}`, patch),
  exportCsvUrl: `${BASE}/applications/export.csv`,
  generateDocs: (id: string) => request<ApplicationDetail>("POST", `/applications/${id}/documents/generate`, {}, true),
  saveDoc: (id: string, kind: string, content: CVContentT | LetterContentT) =>
    request<ApplicationDetail>("PUT", `/applications/${id}/documents/${kind}`, { content }),
  docUrl: (appId: string, docId: string, format: "pdf" | "docx") =>
    `${BASE}/applications/${appId}/documents/${docId}/download?format=${format}`,
  masterCvUrl: (format: "pdf" | "docx") => `${BASE}/profile/master-cv?format=${format}`,
  prepare: (id: string, apply_url: string) => request<ApplicationDetail>("POST", `/applications/${id}/prepare`, { apply_url }, true),
  answerField: (id: string, fieldId: string, body: { proposed_value?: string; skip?: boolean }) =>
    request<ApplicationDetail & { approval_invalidated: boolean }>("PATCH", `/applications/${id}/form-fields/${fieldId}`, body),
  approve: (id: string) => request<ApplicationDetail>("POST", `/applications/${id}/approve`, {}, true),
  submit: (id: string) => request<ApplicationDetail & { attempt: AttemptT }>("POST", `/applications/${id}/submit`, {}, true),
  confirmOutcome: (id: string, submitted: boolean, note?: string) =>
    request<ApplicationDetail>("POST", `/applications/${id}/submission-outcome`, { submitted, note }),
  markSubmitted: (id: string, note?: string) => request<ApplicationDetail>("POST", `/applications/${id}/mark-submitted`, { note }, true),
  evidenceUrl: (id: string, file: string) => `${BASE}/applications/${id}/evidence?file=${encodeURIComponent(file)}`,
  exportProfile: () => request<{ format: string; facts: Fact[] }>("GET", "/profile/export"),
  importProfile: (data: { format: string; facts: Fact[] }) =>
    request<Profile>("POST", "/profile/import", { format: data.format, facts: data.facts.map(({ category, entry, key, value, context, source_note }) => ({ category, entry: entry ?? null, key, value: value ?? "", context: context ?? null, source_note: source_note ?? null })) }, true),
};
