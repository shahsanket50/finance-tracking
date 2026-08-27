/** Pure functions for the 4 audit screens. API types are generated from openapi.json. */

import type { components } from "./api-types";

// ── Generated API types ───────────────────────────────────────────────────────

export type SyncHistoryEntry = components["schemas"]["SyncHistoryEntry"];
export type StatementBar = components["schemas"]["StatementBar"];
export type AccountOverlap = components["schemas"]["AccountOverlap"];
export type OverlapMapResponse = components["schemas"]["OverlapMapResponse"];
export type DedupLedgerEntry = components["schemas"]["DedupLedgerEntry"];
export type DedupLedgerResponse = components["schemas"]["DedupLedgerResponse"];
export type PairingLeg = components["schemas"]["PairingLeg"];
export type ResolverPairing = components["schemas"]["ResolverPairing"];
export type AccountTransaction = components["schemas"]["AccountTransaction"];

// ── Pure functions ────────────────────────────────────────────────────────────

const EXCLUSION_LABELS: Record<string, string> = {
  internal_transfer: "Transfer excluded",
  cc_payment: "CC payment excluded",
  fd_booking: "FD booking excluded",
  reversal: "Reversal excluded",
};

const PAIRING_LABELS: Record<string, string> = {
  MarkedInternalTransfer: "Internal Transfer",
  MarkedCCPayment: "CC Payment",
  MarkedFDBooking: "FD Booking",
  MarkedReversal: "Reversal",
};

export type BadgeVariant = "success" | "warning" | "danger";

/** Maps a DedupLedgerEntry to a Badge variant + label for the status column. */
export function rowStatus(entry: DedupLedgerEntry): {
  variant: BadgeVariant;
  label: string;
} {
  if (entry.is_counted) {
    return { variant: "success", label: "Counted" };
  }
  const label = entry.exclusion_reason
    ? (EXCLUSION_LABELS[entry.exclusion_reason] ?? "Excluded")
    : "Excluded";
  return { variant: "warning", label };
}

/** Returns a human-readable label for a resolver event_type constant. */
export function pairingLabel(event_type: string): string {
  return PAIRING_LABELS[event_type] ?? event_type;
}

/** Converts a basis-points confidence value to a display string (e.g. 9500 → "95.0%"). */
export function confidencePct(bps: number): string {
  return (bps / 100).toFixed(1) + "%";
}
