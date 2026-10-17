"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { api } from "@/lib/api";

const NAV = [
  { href: "/", label: "Dashboard" },
  { href: "/discovery", label: "Job Discovery" },
  { href: "/jobs", label: "Job Review" },
  { href: "/review", label: "Application Review" },
  { href: "/tracker", label: "Tracker" },
  { href: "/settings", label: "Settings & Health" },
];

export function Shell({ children }: { children: React.ReactNode }) {
  const path = usePathname();
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
            </Link>
          );
        })}
        <div className="spacer" />
        <button
          className="btn small logout"
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
