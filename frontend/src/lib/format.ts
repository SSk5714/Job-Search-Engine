import type { State } from "./api";

export const STATE_LABEL: Record<State, string> = {
  discovered: "Discovered",
  classified: "To review",
  approved_for_preparation: "Approved for prep",
  documents_ready: "Documents ready",
  form_prepared: "Form prepared",
  awaiting_user_review: "Awaiting your review",
  submitted: "Submitted",
  follow_up: "Follow-up",
  closed: "Closed",
  rejected: "Rejected",
  failed: "Failed",
  expired: "Expired",
  withdrawn: "Withdrawn",
  needs_manual_input: "Needs your input",
};

export const STATE_TONE: Partial<Record<State, "accent" | "good" | "warn" | "bad" | "muted">> = {
  classified: "accent",
  approved_for_preparation: "accent",
  awaiting_user_review: "warn",
  needs_manual_input: "warn",
  submitted: "good",
  follow_up: "good",
  failed: "bad",
  rejected: "muted",
  withdrawn: "muted",
  expired: "muted",
  closed: "muted",
};

export const TRACKS: Record<string, string> = {
  A: "Android & Mobile",
  B: "Java & Backend",
  C: "Embedded & Automotive",
  D: "Student & Early-career",
  other: "Other",
};

export const REC_LABEL: Record<string, string> = {
  apply: "Recommend applying",
  review: "Manual review",
  low_priority: "Low priority",
  reject: "Not eligible",
};

export function date(value: string | null | undefined): string {
  if (!value) return "—";
  const d = new Date(value);
  return d.toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" });
}

export function dateTime(value: string | null | undefined): string {
  if (!value) return "—";
  return new Date(value).toLocaleString("en-GB", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
}

export function salary(min: number | null, max: number | null, cur: string | null): string | null {
  if (min === null && max === null) return null;
  const f = (n: number) => n.toLocaleString("en-GB");
  if (min !== null && max !== null) return `${f(min)}–${f(max)} ${cur ?? ""}`.trim();
  return `${f((min ?? max) as number)} ${cur ?? ""}`.trim();
}
