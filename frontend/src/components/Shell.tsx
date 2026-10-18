"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { usePathname } from "next/navigation";
import { api } from "@/lib/api";

const NAV = [
  { href: "/", label: "Dashboard" },
  { href: "/discovery", label: "Job Discovery" },
  { href: "/jobs", label: "Job Review" },
  { href: "/review", label: "Application Review" },
  { href: "/tracker", label: "Tracker" },
  { href: "/notifications", label: "Notifications" },
  { href: "/settings", label: "Settings & Health" },
];

export function Shell({ children }: { children: React.ReactNode }) {
  const path = usePathname();
  const [counts, setCounts] = useState<{ unread: number; critical: number }>({ unread: 0, critical: 0 });
  useEffect(() => {
    if (path === "/login") return;
    const load = () => api.notificationSummary()
      .then((s) => setCounts({ unread: s.unread, critical: s.open_alerts.critical })).catch(() => undefined);
    load();
    const t = setInterval(load, 30_000);
    return () => clearInterval(t);
  }, [path]);
  if (path === "/login") return <main className="main" style={{ margin: "0 auto", maxWidth: 420 }}>{children}</main>;
  return (
    <div className="shell">
      <nav className="side" aria-label="Main">
        <div className="brand">Job<span>Pilot</span></div>
        {NAV.map((n) => {
          const active = n.href === "/" ? path === "/" : path.startsWith(n.href);
          return (
            <Link key={n.href} href={n.href} className={`nav-link${active ? " active" : ""}`}>
              {n.label}
              {n.href === "/notifications" && counts.unread > 0 && (
                <span className={`badge ${counts.critical ? "bad" : "accent"}`} style={{ marginLeft: 6 }}
                  aria-label={`${counts.unread} unread`}>{counts.unread}</span>
              )}
            </Link>
          );
        })}
        <div className="spacer" />
        <button
          className="btn small logout"
          title="Ends your session on every device"
          onClick={async () => {
            await api.logout().catch(() => undefined);
            window.location.href = "/login";
          }}
        >
          Sign out
        </button>
      </nav>
      <main className="main">{children}</main>
    </div>
  );
}
