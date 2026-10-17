"use client";

import { useCallback, useEffect, useState } from "react";
import { ApiError, type State } from "@/lib/api";
import { STATE_LABEL, STATE_TONE } from "@/lib/format";

export function useLoad<T>(fn: () => Promise<T>, deps: unknown[] = []) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const reload = useCallback(async () => {
    setLoading(true);
    try {
      setData(await fn());
      setError(null);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Could not reach the server");
    } finally {
      setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);
  useEffect(() => {
    reload();
  }, [reload]);
  return { data, error, loading, reload, setData };
}

export function errorText(e: unknown): string {
  if (e instanceof ApiError) return e.message;
  return "Something went wrong; try again";
}

export function StateBadge({ state }: { state: State }) {
  return <span className={`badge ${STATE_TONE[state] ?? ""}`}>{STATE_LABEL[state] ?? state}</span>;
}

export function Score({ value }: { value: number | null | undefined }) {
  if (value === null || value === undefined) return <span className="score lo">—</span>;
  const tone = value >= 75 ? "hi" : value >= 55 ? "mid" : "lo";
  return <span className={`score ${tone}`} aria-label={`Score ${value} of 100`}>{value}</span>;
}

export function ErrorBox({ message }: { message: string | null }) {
  if (!message) return null;
  return <div className="errbox" role="alert">{message}</div>;
}

export function Loading() {
  return <p className="muted">Loading…</p>;
}
