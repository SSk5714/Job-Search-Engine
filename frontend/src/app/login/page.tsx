"use client";

import { useState } from "react";
import { api } from "@/lib/api";
import { ErrorBox, errorText } from "@/components/ui";

export default function LoginPage() {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await api.login(username, password);
      window.location.href = "/";
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div style={{ paddingTop: "12vh" }}>
      <h1>Job<span style={{ color: "var(--accent)" }}>Pilot</span> Europe</h1>
      <p className="sub" style={{ marginBottom: 20 }}>Sign in to review jobs and applications.</p>
      <form className="card grid" onSubmit={submit}>
        <label>Username<input autoComplete="username" value={username} onChange={(e) => setUsername(e.target.value)} required /></label>
        <label>Password<input type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} required /></label>
        <ErrorBox message={error} />
        <button className="btn primary" disabled={busy}>{busy ? "Signing in…" : "Sign in"}</button>
      </form>
    </div>
  );
}
