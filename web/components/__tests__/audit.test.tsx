/**
 * Wave 4 RTL tests: audit screens render real fetched data.
 *
 * Each test mocks fetch() with fixture data and asserts that a specific
 * piece of real data renders — not just that the component mounts.
 *
 * A1: Sync history — account_ref renders; stalled entry gets warning badge.
 * A2: Overlap map — account_ref and period render; overlapping bar shows badge.
 * A3: Dedup ledger — money amount renders via <Money>; status badge matches is_counted.
 * A4: Dedup ledger — filter chip shows when URL has from/to params.
 * A5: Resolver pairings — pairing label and confidence render.
 * A6: Resolver pairings — CC payment expand fetches account transactions.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

// ── Page imports ───────────────────────────────────────────────────────────────

import SyncHistoryPage from "../../app/(expense)/audit/sync-history/page";
import OverlapMapPage from "../../app/(expense)/audit/overlap-map/page";
import DedupLedgerPage from "../../app/(expense)/audit/dedup-ledger/page";
import PairingsPage from "../../app/(expense)/audit/pairings/page";

// ── Next.js shims ──────────────────────────────────────────────────────────────

const mockPush = vi.fn();
const mockSearchParams = new Map<string, string>();

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: mockPush }),
  useSearchParams: () => ({
    get: (k: string) => mockSearchParams.get(k) ?? null,
  }),
}));

vi.mock("next/link", () => ({
  default: ({
    children,
    href,
  }: {
    children: React.ReactNode;
    href: string;
  }) => <a href={href}>{children}</a>,
}));

// ── Fetch mock helpers ─────────────────────────────────────────────────────────

function mockFetch(url: string, body: unknown) {
  vi.stubGlobal(
    "fetch",
    vi.fn((input: string) => {
      if (input.includes(url)) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve(body),
        } as Response);
      }
      return Promise.reject(new Error(`Unexpected fetch: ${input}`));
    }),
  );
}

function mockFetchMulti(routes: Record<string, unknown>) {
  vi.stubGlobal(
    "fetch",
    vi.fn((input: string) => {
      for (const [pattern, body] of Object.entries(routes)) {
        if (input.includes(pattern)) {
          return Promise.resolve({
            ok: true,
            json: () => Promise.resolve(body),
          } as Response);
        }
      }
      return Promise.reject(new Error(`Unexpected fetch: ${input}`));
    }),
  );
}

beforeEach(() => {
  vi.restoreAllMocks();
  mockSearchParams.clear();
  mockPush.mockReset();
});

// ── A1: Sync history ──────────────────────────────────────────────────────────

describe("A1: sync history renders real fetched data", () => {
  it("renders account_ref from API response", async () => {
    mockFetch("sync-history", [
      {
        event_id: "evt-1",
        account_ref: "HDFC_SAVINGS",
        bank: "hdfc_savings",
        period_start: "2026-01-01",
        period_end: "2026-01-31",
        status: "ingested",
        records_added: 42,
        records_skipped: 0,
        balance_check: "pass",
        confidence: 9000,
        created_at: "2026-01-31T12:00:00Z",
        is_stalled: false,
      },
    ]);

    render(<SyncHistoryPage />);
    await waitFor(() =>
      expect(screen.getByText("HDFC_SAVINGS")).toBeInTheDocument(),
    );
    expect(screen.getByText(/42 added/)).toBeInTheDocument();
  });

  it("marks a stalled entry with a warning badge", async () => {
    // Backend computes is_stalled — frontend renders it, no client-side threshold recalculation.
    mockFetch("sync-history", [
      {
        event_id: "evt-stale",
        account_ref: "SBI_SAVINGS",
        bank: "sbi_savings",
        period_start: "2026-01-01",
        period_end: "2026-01-31",
        status: "ingested",
        records_added: 5,
        records_skipped: 0,
        balance_check: "pass",
        confidence: 8500,
        created_at: "2026-01-01T12:00:00Z",
        is_stalled: true,
      },
    ]);

    render(<SyncHistoryPage />);
    await waitFor(() =>
      expect(screen.getByText("SBI_SAVINGS")).toBeInTheDocument(),
    );
    expect(screen.getByText("Stalled")).toBeInTheDocument();
  });
});

// ── A2: Overlap map ───────────────────────────────────────────────────────────

describe("A2: overlap map renders real fetched data", () => {
  it("renders account_ref and statement period", async () => {
    mockFetch("overlap-map", {
      accounts: [
        {
          account_ref: "HDFC_CC",
          statements: [
            {
              event_id: "bar-1",
              period_start: "2026-02-01",
              period_end: "2026-03-31",
              overlaps_with: [],
            },
          ],
        },
      ],
    });

    render(<OverlapMapPage />);
    await waitFor(() =>
      expect(screen.getByText("HDFC_CC")).toBeInTheDocument(),
    );
    expect(screen.getByText(/2026-02-01/)).toBeInTheDocument();
  });

  it("shows Overlap badge for overlapping statements", async () => {
    mockFetch("overlap-map", {
      accounts: [
        {
          account_ref: "SBI_SAVINGS",
          statements: [
            {
              event_id: "bar-a",
              period_start: "2026-01-01",
              period_end: "2026-02-28",
              overlaps_with: ["bar-b"],
            },
            {
              event_id: "bar-b",
              period_start: "2026-02-01",
              period_end: "2026-03-31",
              overlaps_with: ["bar-a"],
            },
          ],
        },
      ],
    });

    render(<OverlapMapPage />);
    await waitFor(() => expect(screen.getAllByText("Overlap")).toHaveLength(2));
  });
});

// ── A3: Dedup ledger — data renders ──────────────────────────────────────────

describe("A3: dedup ledger renders real fetched data", () => {
  it("renders money amount via <Money> and counted badge", async () => {
    mockFetch("dedup-ledger", {
      total_seen: 1,
      total_counted: 1,
      total_excluded: 0,
      entries: [
        {
          idempotency_hash: "abc123",
          amount_paise: "50000",
          value_date: "2026-03-10",
          account_ref: "HDFC_SAVINGS",
          transaction_type: "credit",
          is_counted: true,
          exclusion_reason: null,
          covering_ingestion_event_ids: ["ie-1"],
        },
      ],
    });

    render(<DedupLedgerPage />);
    await waitFor(() =>
      expect(screen.getByText(/₹500\.00/)).toBeInTheDocument(),
    );
    // "Counted" appears in both the stats bar and the row badge — assert both present
    expect(screen.getAllByText("Counted").length).toBeGreaterThanOrEqual(2);
  });

  it("renders excluded row with warning badge and ingestion event back-reference", async () => {
    mockFetch("dedup-ledger", {
      total_seen: 1,
      total_counted: 0,
      total_excluded: 1,
      entries: [
        {
          idempotency_hash: "def456",
          amount_paise: "75000",
          value_date: "2026-02-15",
          account_ref: "HDFC_CC",
          transaction_type: "debit",
          is_counted: false,
          exclusion_reason: "cc_payment",
          covering_ingestion_event_ids: ["ie-a", "ie-b"],
        },
      ],
    });

    render(<DedupLedgerPage />);
    await waitFor(() =>
      expect(screen.getByText("CC payment excluded")).toBeInTheDocument(),
    );
    // Both ingestion event back-references appear
    expect(screen.getByText(/ie-a/)).toBeInTheDocument();
    expect(screen.getByText(/ie-b/)).toBeInTheDocument();
  });
});

// ── A4: Dedup ledger — filter chip ────────────────────────────────────────────

describe("A4: dedup ledger shows filter chip when URL has from/to params", () => {
  it("renders filter chip and clear button when from/to present", async () => {
    mockSearchParams.set("from", "2026-02-01");
    mockSearchParams.set("to", "2026-02-28");

    mockFetch("dedup-ledger", {
      total_seen: 0,
      total_counted: 0,
      total_excluded: 0,
      entries: [],
    });

    render(<DedupLedgerPage />);
    await waitFor(() =>
      expect(screen.getByText(/Filtered:/)).toBeInTheDocument(),
    );
    expect(screen.getByText(/2026-02-01/)).toBeInTheDocument();
    expect(screen.getByText(/Clear/)).toBeInTheDocument();
  });

  it("does not render filter chip when no URL params", async () => {
    mockFetch("dedup-ledger", {
      total_seen: 0,
      total_counted: 0,
      total_excluded: 0,
      entries: [],
    });

    render(<DedupLedgerPage />);
    await waitFor(() =>
      expect(screen.queryByText(/Filtered:/)).not.toBeInTheDocument(),
    );
  });
});

// ── A5: Resolver pairings — label and confidence ──────────────────────────────

describe("A5: resolver pairings renders pairing label and confidence", () => {
  it("renders pairing type label and formatted confidence", async () => {
    mockFetch("resolver-pairings", [
      {
        event_id: "pair-1",
        event_type: "MarkedInternalTransfer",
        matched_by: "transfer_v1",
        confidence: 9500,
        value_date: "2026-02-10",
        legs: [
          {
            role: "debit",
            idempotency_hash: "hash1",
            account_ref: "HDFC_SAVINGS",
            period_start: "2026-02-01",
            period_end: "2026-02-28",
          },
          {
            role: "credit",
            idempotency_hash: "hash2",
            account_ref: "SBI_SAVINGS",
            period_start: "2026-02-01",
            period_end: "2026-02-28",
          },
        ],
      },
    ]);

    render(<PairingsPage />);
    await waitFor(() =>
      expect(screen.getByText("Internal Transfer")).toBeInTheDocument(),
    );
    expect(screen.getByText("95.0%")).toBeInTheDocument();
    expect(screen.getByText(/2026-02-10/)).toBeInTheDocument();
  });
});

// ── A6b: CC payment with unresolved cc_credit leg hides drill-down ────────────

describe("A6b: CC payment with empty cc_credit account_ref hides drill-down button", () => {
  it("does not render Show purchases when cc_credit leg has no account_ref", async () => {
    mockFetch("resolver-pairings", [
      {
        event_id: "pair-cc-unresolved",
        event_type: "MarkedCCPayment",
        matched_by: "cc_payment_v1",
        confidence: 9000,
        value_date: "2026-03-15",
        legs: [
          {
            role: "savings_debit",
            idempotency_hash: "hashS",
            account_ref: "HDFC_SAVINGS",
            period_start: "2026-03-01",
            period_end: "2026-03-31",
          },
          // cc_credit leg has empty account_ref — join missed (CC not yet ingested)
          {
            role: "cc_credit",
            idempotency_hash: "hashCC",
            account_ref: "",
            period_start: null,
            period_end: null,
          },
        ],
      },
    ]);

    render(<PairingsPage />);
    await waitFor(() =>
      expect(screen.getByText("CC Payment")).toBeInTheDocument(),
    );
    expect(screen.queryByText(/Show purchases/)).not.toBeInTheDocument();
  });
});

// ── A6: CC payment expand calls accounts endpoint ─────────────────────────────

describe("A6: CC payment expand fetches account transactions for billing period", () => {
  it("shows CC purchases on expand using period from the cc_credit leg", async () => {
    const user = userEvent.setup();

    mockFetchMulti({
      "resolver-pairings": [
        {
          event_id: "pair-cc",
          event_type: "MarkedCCPayment",
          matched_by: "cc_payment_v1",
          confidence: 9000,
          value_date: "2026-03-15",
          legs: [
            {
              role: "savings_debit",
              idempotency_hash: "hashS",
              account_ref: "HDFC_SAVINGS",
              period_start: "2026-03-01",
              period_end: "2026-03-31",
            },
            {
              role: "cc_credit",
              idempotency_hash: "hashCC",
              account_ref: "HDFC_CC_9876",
              period_start: "2026-02-15",
              period_end: "2026-03-14",
            },
          ],
        },
      ],
      "accounts/HDFC_CC_9876/transactions": [
        {
          idempotency_hash: "purchase-1",
          value_date: "2026-02-20",
          amount_paise: "-12000",
          narration: "SWIGGY ORDER",
          transaction_type: "debit",
          account_ref: "HDFC_CC_9876",
        },
      ],
    });

    render(<PairingsPage />);
    await waitFor(() =>
      expect(screen.getByText("CC Payment")).toBeInTheDocument(),
    );

    await user.click(screen.getByText(/Show purchases/));

    await waitFor(() =>
      expect(screen.getByText("SWIGGY ORDER")).toBeInTheDocument(),
    );
    expect(screen.getByText(/₹120\.00/)).toBeInTheDocument();
  });
});
