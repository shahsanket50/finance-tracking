"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import type { AppContext } from "./app-shell";

interface NavItem {
  label: string;
  href: string;
  glyph: string;
  available: boolean;
}

const EXPENSE_NAV: NavItem[] = [
  { label: "Home", href: "/home", glyph: "⌂", available: false },
  {
    label: "Transactions",
    href: "/transactions",
    glyph: "⇅",
    available: false,
  },
  { label: "Budgets", href: "/budgets", glyph: "◉", available: false },
  { label: "Categories", href: "/categories", glyph: "⊞", available: false },
  { label: "Audit", href: "/audit", glyph: "⧖", available: true },
];

const CA_NAV: NavItem[] = [
  { label: "Tax Health", href: "/tax-health", glyph: "♥", available: false },
  {
    label: "FY Checklist",
    href: "/fy-checklist",
    glyph: "☑",
    available: false,
  },
  { label: "Advance Tax", href: "/advance-tax", glyph: "◷", available: false },
  { label: "Deductions", href: "/deductions", glyph: "−", available: false },
  {
    label: "Capital Gains",
    href: "/capital-gains",
    glyph: "↗",
    available: false,
  },
  { label: "Income & TDS", href: "/income-tds", glyph: "₹", available: false },
  { label: "Documents", href: "/documents", glyph: "⚏", available: false },
];

const SHARED_NAV: NavItem[] = [
  { label: "Accounts", href: "/accounts", glyph: "⊕", available: false },
  {
    label: "Notifications",
    href: "/notifications",
    glyph: "◎",
    available: false,
  },
  { label: "Settings", href: "/settings", glyph: "⚙", available: false },
];

function isActive(pathname: string, href: string): boolean {
  if (href === "/") return pathname === "/";
  return pathname === href || pathname.startsWith(href + "/");
}

interface Props {
  context: AppContext;
  onContextChange: (c: AppContext) => void;
}

export function Sidebar({ context, onContextChange }: Props) {
  const pathname = usePathname();
  const contextNav = context === "expense" ? EXPENSE_NAV : CA_NAV;

  return (
    <aside className="sidebar">
      <div className="side-top">
        <div className="logo">fintrack</div>

        <div className="ctx-switch">
          <button
            className={`ctx-btn${context === "expense" ? " active" : ""}`}
            onClick={() => onContextChange("expense")}
          >
            Expense
          </button>
          <button
            className={`ctx-btn${context === "ca" ? " active" : ""}`}
            onClick={() => onContextChange("ca")}
          >
            CA View
          </button>
        </div>
      </div>

      <nav className="nav-list">
        {contextNav.map((item) =>
          item.available ? (
            <Link
              key={item.href}
              href={item.href}
              className={`nav-item${isActive(pathname, item.href) ? " active" : ""}`}
            >
              <span className="nav-glyph">{item.glyph}</span>
              {item.label}
            </Link>
          ) : (
            <span
              key={item.href}
              className="nav-item disabled"
              aria-disabled="true"
            >
              <span className="nav-glyph">{item.glyph}</span>
              {item.label}
            </span>
          ),
        )}
      </nav>

      <div className="side-bottom">
        {SHARED_NAV.map((item) =>
          item.available ? (
            <Link
              key={item.href}
              href={item.href}
              className={`nav-item${isActive(pathname, item.href) ? " active" : ""}`}
            >
              <span className="nav-glyph">{item.glyph}</span>
              {item.label}
            </Link>
          ) : (
            <span
              key={item.href}
              className="nav-item disabled"
              aria-disabled="true"
            >
              <span className="nav-glyph">{item.glyph}</span>
              {item.label}
            </span>
          ),
        )}
      </div>
    </aside>
  );
}
