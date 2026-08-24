import { useState } from "react";
import {
  Activity,
  ClipboardCheck,
  FileClock,
  LayoutDashboard,
  Menu,
  ReceiptText,
  ShieldCheck,
  X,
} from "lucide-react";
import { NavLink, Outlet, useLocation } from "react-router-dom";

const navigation = [
  { label: "Overview", to: "/overview", icon: LayoutDashboard },
  { label: "Cases", to: "/cases", icon: ReceiptText },
  { label: "Approvals", to: "/approvals", icon: ClipboardCheck },
  { label: "Recovery Actions", to: "/recovery-actions", icon: Activity },
  { label: "Decision Audit", to: "/audit", icon: FileClock },
] as const;

function pageName(pathname: string): string {
  if (pathname.startsWith("/cases/")) return "Case Decision Trace";
  return (
    navigation.find((item) => pathname.startsWith(item.to))?.label ??
    "Revenue Recovery"
  );
}

export function AppShell() {
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const location = useLocation();
  const currentPage = pageName(location.pathname);

  return (
    <div className="app-shell">
      <button
        className={`sidebar-overlay ${sidebarOpen ? "open" : ""}`}
        type="button"
        aria-label="Close navigation"
        onClick={() => setSidebarOpen(false)}
      />
      <aside className={`sidebar ${sidebarOpen ? "open" : ""}`}>
        <div className="brand">
          <div className="brand-mark" aria-hidden="true">ARC</div>
          <div>
            <p className="brand-name">ARC</p>
            <p className="brand-subtitle">Autonomous Revenue Control</p>
          </div>
        </div>
        <nav className="sidebar-nav" aria-label="Primary navigation">
          {navigation.map(({ label, to, icon: Icon }) => (
            <NavLink
              className={({ isActive }) => `nav-link ${isActive ? "active" : ""}`}
              key={to}
              to={to}
              onClick={() => setSidebarOpen(false)}
            >
              <Icon size={17} strokeWidth={1.8} aria-hidden="true" />
              {label}
            </NavLink>
          ))}
        </nav>
        <div className="sidebar-footer">
          <strong>ARC</strong>
          Policy-Governed Recovery
          <br />
          Built for Razorpay AI Buildathon
        </div>
      </aside>

      <div className="app-main">
        <header className="topbar">
          <div className="topbar-heading">
            <button
              className="menu-button"
              type="button"
              aria-label={sidebarOpen ? "Close navigation" : "Open navigation"}
              onClick={() => setSidebarOpen((value) => !value)}
            >
              {sidebarOpen ? <X size={18} /> : <Menu size={18} />}
            </button>
            <span>Revenue Recovery /</span>
            <strong>{currentPage}</strong>
          </div>
          <div className="topbar-actions">
            <span
              className="topbar-chip test-mode-chip"
              title="Razorpay Test Mode — no live money"
            >
              TEST MODE
            </span>
            <span className="topbar-chip currency-chip">INR</span>
            <span className="system-status" title="ARC read console is active">
              <span className="status-dot" aria-hidden="true" />
              <span>Operational</span>
              <ShieldCheck className="sr-only" size={14} aria-hidden="true" />
            </span>
          </div>
        </header>
        <main className="page-content">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
