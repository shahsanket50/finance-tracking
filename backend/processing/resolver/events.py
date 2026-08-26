"""Resolver event payload schemas (TRD §9.1 C3, §9.2).

Each class defines the payload for a resolver DECISION event stored in
transaction_events with a resolver event_type. These payloads are encrypted
and stored in the payload column.

These are DECISIONS — recorded once at resolve time, never re-derived during
replay. Recomputing them on replay would break Invariant 3 (replay determinism).

All four resolver event types are in scope for Phase 2 (owner confirmed 2026-08-14):
  MarkedInternalTransfer — savings↔savings pair (both legs excluded from totals)
  MarkedCCPayment        — savings debit + CC bill credit (both legs excluded)
  MarkedFDBooking        — savings debit + FD creation credit (both legs excluded)
  MarkedReversal         — original debit + reversal credit (both legs excluded)

reverses_transaction_id column (TRD §9.5 M4) is deferred to Wave 2.
"""

from pydantic import BaseModel, Field

from core.events.types import RESOLVER_EVENT_TYPES as RESOLVER_EVENT_TYPES  # re-export


class MarkedInternalTransferPayload(BaseModel):
    """Payload for MarkedInternalTransfer event_type."""

    model_config = {"frozen": True}

    debit_hash: str = Field(..., description="Idempotency hash of the debit leg")
    credit_hash: str = Field(..., description="Idempotency hash of the credit leg")
    matched_by: str = Field(..., description="Resolver algorithm version, e.g. 'transfer_v1'")
    confidence: int = Field(..., ge=0, le=10000, description="Match confidence in basis points")


class MarkedCCPaymentPayload(BaseModel):
    """Payload for MarkedCCPayment event_type."""

    model_config = {"frozen": True}

    savings_debit_hash: str = Field(..., description="Idempotency hash of the savings debit")
    cc_credit_hash: str = Field(..., description="Idempotency hash of the CC bill credit")
    matched_by: str
    confidence: int = Field(..., ge=0, le=10000)
    match_window_days: int = Field(..., description="Actual window used (from config constant)")


class MarkedFDBookingPayload(BaseModel):
    """Payload for MarkedFDBooking event_type."""

    model_config = {"frozen": True}

    savings_debit_hash: str = Field(..., description="Idempotency hash of the savings debit")
    fd_credit_hash: str = Field(..., description="Idempotency hash of the FD credit")
    matched_by: str
    confidence: int = Field(..., ge=0, le=10000)
    match_window_days: int = Field(..., description="Actual window used (from config constant)")


class MarkedReversalPayload(BaseModel):
    """Payload for MarkedReversal event_type (TRD §9.5 M4).

    reverses_transaction_id column on transaction_events is deferred to Wave 2.
    """

    model_config = {"frozen": True}

    original_hash: str = Field(..., description="Idempotency hash of the original transaction")
    reversal_hash: str = Field(..., description="Idempotency hash of the reversal transaction")
    matched_by: str
    confidence: int = Field(..., ge=0, le=10000)


# RESOLVER_EVENT_TYPES is defined in core.events.types and re-exported above.
