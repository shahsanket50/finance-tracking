"""Domain enumerations for event classification. Implements TRD §3.1, T16."""

from enum import StrEnum


class TransactionType(StrEnum):
    income = "income"
    expense = "expense"
    transfer = "transfer"
    investment = "investment"


class Actor(StrEnum):
    system = "system"
    user = "user"
    ai = "ai"


class BalanceCheck(StrEnum):
    pass_ = "pass"
    fail = "fail"


class IngestionStatus(StrEnum):
    success = "success"
    partial = "partial"
    failed = "failed"
    rejected = "rejected"


# Canonical event_type strings for transaction_events.event_type.
# All writers (confirm.py) and readers (reducer.py, pipeline.py) must import
# from here. No bare string literals in production code — drift in casing
# silently breaks replay determinism (Invariant 3).
TRANSACTION_INGESTED: str = "TransactionIngested"
MARKED_INTERNAL_TRANSFER: str = "MarkedInternalTransfer"
MARKED_CC_PAYMENT: str = "MarkedCCPayment"
MARKED_FD_BOOKING: str = "MarkedFDBooking"
MARKED_REVERSAL: str = "MarkedReversal"

RESOLVER_EVENT_TYPES: frozenset[str] = frozenset(
    {
        MARKED_INTERNAL_TRANSFER,
        MARKED_CC_PAYMENT,
        MARKED_FD_BOOKING,
        MARKED_REVERSAL,
    }
)

# Canonical account_type strings for CandidateTxn.account_type, ParsedStatement.account_type,
# and matcher gate expressions. Drift between parsers and matchers silently routes
# transactions through the wrong matcher bucket — same bug class as event_type casing.
ACCOUNT_TYPE_SAVINGS: str = "savings"
ACCOUNT_TYPE_CREDIT_CARD: str = "credit_card"
ACCOUNT_TYPE_FD: str = "fd"
