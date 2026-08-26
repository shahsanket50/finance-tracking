/**
 * Wave 2 behavioral tests: app shell, context switch, placeholder routing.
 *
 * E1: Context switch (Expense ⇄ CA) swaps sidebar nav without a page reload.
 * E2: Shared utilities (Accounts, Notifications, Settings) visible from both contexts.
 * E3: Every non-Audit expense screen renders its Phase 3.5 placeholder, not 404.
 * E4: Every shared utility screen renders its Phase 3.5 placeholder, not 404.
 * E5: Every CA-context screen renders its Phase 4.5 placeholder, not 404.
 *
 * Pages are rendered directly (no router) to confirm the route file exists and
 * mounts correctly — which is sufficient proof it would not 404 in the app.
 */

import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { AppShell } from "../app-shell";

// Placeholder page components — imported here so vitest resolves the module
// at collection time; a missing file is an immediate import error, not a test failure.
import HomePage from "../../app/(expense)/home/page";
import TransactionsPage from "../../app/(expense)/transactions/page";
import BudgetsPage from "../../app/(expense)/budgets/page";
import CategoriesPage from "../../app/(expense)/categories/page";
import AccountsPage from "../../app/accounts/page";
import NotificationsPage from "../../app/notifications/page";
import SettingsPage from "../../app/settings/page";
import TaxHealthPage from "../../app/(ca)/tax-health/page";
import FyChecklistPage from "../../app/(ca)/fy-checklist/page";
import AdvanceTaxPage from "../../app/(ca)/advance-tax/page";
import DeductionsPage from "../../app/(ca)/deductions/page";
import CapitalGainsPage from "../../app/(ca)/capital-gains/page";
import IncomeTdsPage from "../../app/(ca)/income-tds/page";
import DocumentsPage from "../../app/(ca)/documents/page";

// ── Next.js shims ──────────────────────────────────────────────────────────────

vi.mock("next/navigation", () => ({
  usePathname: vi.fn(() => "/"),
}));

vi.mock("next/link", () => ({
  default: ({
    children,
    href,
    className,
  }: {
    children: React.ReactNode;
    href: string;
    className?: string;
  }) => (
    <a href={href} className={className}>
      {children}
    </a>
  ),
}));

// ── E1: Context switch ────────────────────────────────────────────────────────

describe("E1: context switch swaps sidebar nav without reload", () => {
  it("starts in Expense context — expense nav visible, CA nav absent", () => {
    render(
      <AppShell>
        <div />
      </AppShell>,
    );
    expect(screen.getByText("Transactions")).toBeInTheDocument();
    expect(screen.getByText("Budgets")).toBeInTheDocument();
    expect(screen.getByText("Categories")).toBeInTheDocument();
    expect(screen.queryByText("Tax Health")).not.toBeInTheDocument();
    expect(screen.queryByText("FY Checklist")).not.toBeInTheDocument();
  });

  it("clicking CA View replaces expense nav with CA nav", async () => {
    const user = userEvent.setup();
    render(
      <AppShell>
        <div />
      </AppShell>,
    );

    await user.click(screen.getByRole("button", { name: "CA View" }));

    expect(screen.queryByText("Transactions")).not.toBeInTheDocument();
    expect(screen.queryByText("Budgets")).not.toBeInTheDocument();
    expect(screen.getByText("Tax Health")).toBeInTheDocument();
    expect(screen.getByText("FY Checklist")).toBeInTheDocument();
    expect(screen.getByText("Advance Tax")).toBeInTheDocument();
    expect(screen.getByText("Deductions")).toBeInTheDocument();
    expect(screen.getByText("Capital Gains")).toBeInTheDocument();
    expect(screen.getByText("Income & TDS")).toBeInTheDocument();
    expect(screen.getByText("Documents")).toBeInTheDocument();
  });

  it("switching back to Expense restores expense nav", async () => {
    const user = userEvent.setup();
    render(
      <AppShell>
        <div />
      </AppShell>,
    );

    await user.click(screen.getByRole("button", { name: "CA View" }));
    await user.click(screen.getByRole("button", { name: "Expense" }));

    expect(screen.getByText("Transactions")).toBeInTheDocument();
    expect(screen.queryByText("Tax Health")).not.toBeInTheDocument();
  });
});

// ── E2: Shared utilities ──────────────────────────────────────────────────────

describe("E2: shared utilities visible from both contexts", () => {
  it("Accounts, Notifications, Settings present in Expense context", () => {
    render(
      <AppShell>
        <div />
      </AppShell>,
    );
    expect(screen.getByText("Accounts")).toBeInTheDocument();
    expect(screen.getByText("Notifications")).toBeInTheDocument();
    expect(screen.getByText("Settings")).toBeInTheDocument();
  });

  it("Accounts, Notifications, Settings persist after switching to CA View", async () => {
    const user = userEvent.setup();
    render(
      <AppShell>
        <div />
      </AppShell>,
    );

    await user.click(screen.getByRole("button", { name: "CA View" }));

    expect(screen.getByText("Accounts")).toBeInTheDocument();
    expect(screen.getByText("Notifications")).toBeInTheDocument();
    expect(screen.getByText("Settings")).toBeInTheDocument();
  });
});

// ── E3: Expense placeholder screens ──────────────────────────────────────────

describe("E3: non-Audit expense screens render Phase 3.5 placeholder, not 404", () => {
  it.each([
    ["Home", HomePage],
    ["Transactions", TransactionsPage],
    ["Budgets", BudgetsPage],
    ["Categories", CategoriesPage],
  ] as const)('%s page renders "Coming in Phase 3.5"', (_label, Page) => {
    render(<Page />);
    expect(screen.getByText(/Coming in Phase 3\.5/)).toBeInTheDocument();
  });
});

// ── E4: Shared utility screens ────────────────────────────────────────────────

describe("E4: shared utility screens render Phase 3.5 placeholder, not 404", () => {
  it.each([
    ["Accounts", AccountsPage],
    ["Notifications", NotificationsPage],
    ["Settings", SettingsPage],
  ] as const)('%s page renders "Coming in Phase 3.5"', (_label, Page) => {
    render(<Page />);
    expect(screen.getByText(/Coming in Phase 3\.5/)).toBeInTheDocument();
  });
});

// ── E5: CA-context screens ────────────────────────────────────────────────────

describe("E5: CA-context screens render Phase 4.5 placeholder, not 404", () => {
  it.each([
    ["Tax Health", TaxHealthPage],
    ["FY Checklist", FyChecklistPage],
    ["Advance Tax", AdvanceTaxPage],
    ["Deductions", DeductionsPage],
    ["Capital Gains", CapitalGainsPage],
    ["Income & TDS", IncomeTdsPage],
    ["Documents", DocumentsPage],
  ] as const)('%s page renders "Coming in Phase 4.5"', (_label, Page) => {
    render(<Page />);
    expect(screen.getByText(/Coming in Phase 4\.5/)).toBeInTheDocument();
  });
});
