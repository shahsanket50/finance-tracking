/** Pure functions and API types for the 4 audit screens. Implements PRD §15. */

// ── API response types (mirror backend Pydantic models) ───────────────────────

export interface SyncHistoryEntry {
  event_id: string;
  account_ref: string;
  bank: string;
  period_start: string | null;
  period_end: string | null;
  status: string;
  records_added: number;
  records_skipped: number;
  balance_check: string | null;
  confidence: number | null;
  created_at: string;
  // Backend-computed from SYNC_STALL_THRESHOLD_DAYS. Do not recompute on the frontend.
  is_stalled: boolean;
}

export interface StatementBar {
  event_id: string;
  period_start: string | null;
  period_end: string | null;
  overlaps_with: string[];
}

export interface AccountOverlap {
  account_ref: string;
  statements: StatementBar[];
}

export interface OverlapMapResponse {
  accounts: AccountOverlap[];
}

export interface DedupLedgerEntry {
  idempotency_hash: string;
  amount_paise: string;
  value_date: string;
  account_ref: string;
  transaction_type: string;
  is_counted: boolean;
  exclusion_reason: string | null;
  // Period-covering approximation — see PROJECT_STATE.md §known-limitations.
  // Includes any IngestionEvent whose statement period covers this value_date;
  // does not guarantee those events' parses actually emitted this hash.
  covering_ingestion_event_ids: string[];
}

export interface DedupLedgerResponse {
  total_seen: number;
  total_counted: number;
  total_excluded: number;
  entries: DedupLedgerEntry[];
}

export interface PairingLeg {
  role: string;
  idempotency_hash: string;
  account_ref: string;
  period_start: string | null;
  period_end: string | null;
}

export interface ResolverPairing {
  event_id: string;
  event_type: string;
  matched_by: string;
  confidence: number;
  value_date: string;
  legs: PairingLeg[];
}

export interface AccountTransaction {
  idempotency_hash: string;
  value_date: string;
  amount_paise: string;
  narration: string;
  transaction_type: string;
  account_ref: string;
}

// ── Pure functions ────────────────────────────────────────────────────────────

const EXCLUSION_LABELS: Record<string, string> = {
  internal_transfer: 'Transfer excluded',
  cc_payment: 'CC payment excluded',
  fd_booking: 'FD booking excluded',
  reversal: 'Reversal excluded',
};

const PAIRING_LABELS: Record<string, string> = {
  MarkedInternalTransfer: 'Internal Transfer',
  MarkedCCPayment: 'CC Payment',
  MarkedFDBooking: 'FD Booking',
  MarkedReversal: 'Reversal',
};

export type BadgeVariant = 'success' | 'warning' | 'danger';

/** Maps a DedupLedgerEntry to a Badge variant + label for the status column. */
export function rowStatus(entry: DedupLedgerEntry): { variant: BadgeVariant; label: string } {
  if (entry.is_counted) {
    return { variant: 'success', label: 'Counted' };
  }
  const label = entry.exclusion_reason
    ? (EXCLUSION_LABELS[entry.exclusion_reason] ?? 'Excluded')
    : 'Excluded';
  return { variant: 'warning', label };
}

/** Returns a human-readable label for a resolver event_type constant. */
export function pairingLabel(event_type: string): string {
  return PAIRING_LABELS[event_type] ?? event_type;
}

/** Converts a basis-points confidence value to a display string (e.g. 9500 → "95.0%"). */
export function confidencePct(bps: number): string {
  return (bps / 100).toFixed(1) + '%';
}

