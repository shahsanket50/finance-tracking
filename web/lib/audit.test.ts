/**
 * Unit tests for lib/audit.ts pure functions.
 *
 * R1: rowStatus — all 4 exclusion reasons, null reason, unknown key fallback
 * R2: pairingLabel — all 4 event types, unknown-type passthrough
 * R3: confidencePct — boundary values
 */

import { describe, it, expect } from "vitest";
import { rowStatus, pairingLabel, confidencePct } from "./audit";
import type { DedupLedgerEntry } from "./audit";

function entry(overrides: Partial<DedupLedgerEntry>): DedupLedgerEntry {
  return {
    idempotency_hash: "abc",
    amount_paise: "100",
    value_date: "2026-01-01",
    account_ref: "HDFC",
    transaction_type: "debit",
    is_counted: true,
    exclusion_reason: null,
    covering_ingestion_event_ids: [],
    ...overrides,
  };
}

// ── R1: rowStatus ─────────────────────────────────────────────────────────────

describe("R1: rowStatus", () => {
  it("counted entry → success badge", () => {
    const r = rowStatus(entry({ is_counted: true, exclusion_reason: null }));
    expect(r.variant).toBe("success");
    expect(r.label).toBe("Counted");
  });

  it("internal_transfer exclusion → warning badge with label", () => {
    const r = rowStatus(
      entry({ is_counted: false, exclusion_reason: "internal_transfer" }),
    );
    expect(r.variant).toBe("warning");
    expect(r.label).toBe("Transfer excluded");
  });

  it("cc_payment exclusion → warning badge with label", () => {
    const r = rowStatus(
      entry({ is_counted: false, exclusion_reason: "cc_payment" }),
    );
    expect(r.variant).toBe("warning");
    expect(r.label).toBe("CC payment excluded");
  });

  it("fd_booking exclusion → warning badge with label", () => {
    const r = rowStatus(
      entry({ is_counted: false, exclusion_reason: "fd_booking" }),
    );
    expect(r.variant).toBe("warning");
    expect(r.label).toBe("FD booking excluded");
  });

  it("reversal exclusion → warning badge with label", () => {
    const r = rowStatus(
      entry({ is_counted: false, exclusion_reason: "reversal" }),
    );
    expect(r.variant).toBe("warning");
    expect(r.label).toBe("Reversal excluded");
  });

  it("null exclusion_reason → warning badge with generic Excluded label", () => {
    const r = rowStatus(entry({ is_counted: false, exclusion_reason: null }));
    expect(r.variant).toBe("warning");
    expect(r.label).toBe("Excluded");
  });

  it("unknown exclusion_reason key → warning badge with generic Excluded label", () => {
    const r = rowStatus(
      entry({ is_counted: false, exclusion_reason: "some_future_reason" }),
    );
    expect(r.variant).toBe("warning");
    expect(r.label).toBe("Excluded");
  });
});

// ── R2: pairingLabel ──────────────────────────────────────────────────────────

describe("R2: pairingLabel", () => {
  it("MarkedInternalTransfer → Internal Transfer", () => {
    expect(pairingLabel("MarkedInternalTransfer")).toBe("Internal Transfer");
  });

  it("MarkedCCPayment → CC Payment", () => {
    expect(pairingLabel("MarkedCCPayment")).toBe("CC Payment");
  });

  it("MarkedFDBooking → FD Booking", () => {
    expect(pairingLabel("MarkedFDBooking")).toBe("FD Booking");
  });

  it("MarkedReversal → Reversal", () => {
    expect(pairingLabel("MarkedReversal")).toBe("Reversal");
  });

  it("unknown type → passthrough verbatim (intentional fallback)", () => {
    expect(pairingLabel("SomeFutureType")).toBe("SomeFutureType");
  });
});

// ── R3: confidencePct ─────────────────────────────────────────────────────────

describe("R3: confidencePct", () => {
  it("9500 bp → 95.0%", () => {
    expect(confidencePct(9500)).toBe("95.0%");
  });

  it("8500 bp → 85.0%", () => {
    expect(confidencePct(8500)).toBe("85.0%");
  });

  it("0 bp → 0.0%", () => {
    expect(confidencePct(0)).toBe("0.0%");
  });

  it("10000 bp → 100.0%", () => {
    expect(confidencePct(10000)).toBe("100.0%");
  });

  it("9999 bp → rounds to 100.0% with one decimal", () => {
    expect(confidencePct(9999)).toBe("100.0%");
  });
});
