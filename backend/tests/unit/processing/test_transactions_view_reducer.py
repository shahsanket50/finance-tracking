"""Independent tests for the 'transactions_view' projection reducer (Wave 3).

Written from spec (task-3-brief.md) + Event dataclass + builder interface only.
reducer.py did not exist at time of authoring — independence confirmed by commit order.

Invariants verified:
  - Invariant 4: no excluded transaction appears in expense/income totals
  - Invariant 3: deterministic — same events produce identical output
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

import pytest

from core.events.store import Event
from core.projections.builder import build_projection_from_events

_UTC = timezone.utc
_USER = uuid.uuid4()
_NOW = datetime(2026, 1, 1, tzinfo=_UTC)


def _txn(
    idempotency_hash: str,
    amount_paise: int,
    transaction_type: str = "expense",
    value_date: str = "2026-01-15",
    account_ref: str = "HDFC_SAVINGS",
) -> Event:
    return Event(
        id=uuid.uuid4(),
        seq=1,
        event_version=1,
        event_type="TransactionIngested",
        user_id=_USER,
        aggregate_id=account_ref,
        payload={
            "idempotency_hash": idempotency_hash,
            "amount_paise": amount_paise,
            "value_date": value_date,
            "account_ref": account_ref,
            "canonical_narration": "TEST NARRATION",
            "transaction_type": transaction_type,
        },
        created_at=_NOW,
    )


def _resolver_event(event_type: str, payload: dict[str, object]) -> Event:
    return Event(
        id=uuid.uuid4(),
        seq=2,
        event_version=1,
        event_type=event_type,
        user_id=_USER,
        aggregate_id="RESOLVER",
        payload=payload,
        created_at=_NOW,
    )


# ── Registration ───────────────────────────────────────────────────────────────


def test_projection_type_registered() -> None:
    """'transactions_view' must be registered — no ValueError from builder."""
    result = build_projection_from_events([], "transactions_view")
    assert isinstance(result, dict)


# ── Empty state ────────────────────────────────────────────────────────────────


def test_empty_events_produces_zero_state() -> None:
    result = build_projection_from_events([], "transactions_view")
    assert result["transactions"] == []
    assert result["excluded_hashes"] == []
    totals = result["totals"]
    assert totals["income_paise"] == 0  # type: ignore[index]
    assert totals["expense_paise"] == 0  # type: ignore[index]
    assert totals["excluded_count"] == 0  # type: ignore[index]


# ── Single transaction ─────────────────────────────────────────────────────────


def test_single_expense_transaction() -> None:
    events = [_txn("a" * 64, -50000, "expense")]
    result = build_projection_from_events(events, "transactions_view")
    assert len(result["transactions"]) == 1  # type: ignore[arg-type]
    totals = result["totals"]
    assert totals["expense_paise"] == 50000  # type: ignore[index]
    assert totals["income_paise"] == 0  # type: ignore[index]
    assert totals["excluded_count"] == 0  # type: ignore[index]


def test_single_income_transaction() -> None:
    events = [_txn("b" * 64, 100000, "income")]
    result = build_projection_from_events(events, "transactions_view")
    totals = result["totals"]
    assert totals["income_paise"] == 100000  # type: ignore[index]
    assert totals["expense_paise"] == 0  # type: ignore[index]


def test_two_transactions_totals_accumulate() -> None:
    events = [
        _txn("a" * 64, -30000, "expense"),
        _txn("b" * 64, -20000, "expense"),
    ]
    result = build_projection_from_events(events, "transactions_view")
    assert len(result["transactions"]) == 2  # type: ignore[arg-type]
    assert result["totals"]["expense_paise"] == 50000  # type: ignore[index]


def test_income_and_expense_accounted_separately() -> None:
    events = [
        _txn("a" * 64, 80000, "income"),
        _txn("b" * 64, -30000, "expense"),
    ]
    result = build_projection_from_events(events, "transactions_view")
    totals = result["totals"]
    assert totals["income_paise"] == 80000  # type: ignore[index]
    assert totals["expense_paise"] == 30000  # type: ignore[index]


# ── Invariant 4 — exclusion via resolver events ────────────────────────────────


def test_marked_internal_transfer_excludes_both_legs() -> None:
    """INVARIANT 4: transfer pair must not appear in expense totals."""
    debit_hash = "d" * 64
    credit_hash = "c" * 64
    events = [
        _txn(debit_hash, -50000, "expense"),
        _txn(credit_hash, 50000, "income"),
        _resolver_event(
            "MarkedInternalTransfer",
            {
                "debit_hash": debit_hash,
                "credit_hash": credit_hash,
                "matched_by": "transfer_v1",
                "confidence": 9500,
            },
        ),
    ]
    result = build_projection_from_events(events, "transactions_view")
    totals = result["totals"]
    assert totals["expense_paise"] == 0, "Transfer debit must not count as expense"
    assert totals["income_paise"] == 0, "Transfer credit must not count as income"
    assert totals["excluded_count"] == 2  # type: ignore[index]


def test_marked_cc_payment_excludes_both_legs() -> None:
    savings_hash = "s" * 64
    cc_hash = "c" * 64
    events = [
        _txn(savings_hash, -10000, "expense", account_ref="HDFC_SAVINGS"),
        _txn(cc_hash, 10000, "income", account_ref="HDFC_CC"),
        _resolver_event(
            "MarkedCCPayment",
            {
                "savings_debit_hash": savings_hash,
                "cc_credit_hash": cc_hash,
                "matched_by": "cc_payment_v1",
                "confidence": 9000,
                "match_window_days": 3,
            },
        ),
    ]
    result = build_projection_from_events(events, "transactions_view")
    totals = result["totals"]
    assert totals["expense_paise"] == 0
    assert totals["income_paise"] == 0
    assert totals["excluded_count"] == 2  # type: ignore[index]


def test_marked_fd_booking_excludes_both_legs() -> None:
    savings_hash = "s" * 64
    fd_hash = "f" * 64
    events = [
        _txn(savings_hash, -200000, "expense", account_ref="SBI_SAVINGS"),
        _txn(fd_hash, 200000, "income", account_ref="SBI_FD"),
        _resolver_event(
            "MarkedFDBooking",
            {
                "savings_debit_hash": savings_hash,
                "fd_credit_hash": fd_hash,
                "matched_by": "fd_booking_v1",
                "confidence": 9000,
                "match_window_days": 3,
            },
        ),
    ]
    result = build_projection_from_events(events, "transactions_view")
    totals = result["totals"]
    assert totals["expense_paise"] == 0
    assert totals["income_paise"] == 0
    assert totals["excluded_count"] == 2  # type: ignore[index]


def test_two_transfer_pairs_both_excluded() -> None:
    """Two simultaneous transfer pairs: both pairs excluded → zero totals."""
    d1, c1 = "1" * 64, "2" * 64
    d2, c2 = "3" * 64, "4" * 64
    events = [
        _txn(d1, -50000, "expense", account_ref="HDFC_SAVINGS"),
        _txn(c1, 50000, "income", account_ref="SBI_SAVINGS"),
        _txn(d2, -30000, "expense", account_ref="AXIS_SAVINGS"),
        _txn(c2, 30000, "income", account_ref="ICICI_SAVINGS"),
        _resolver_event(
            "MarkedInternalTransfer",
            {"debit_hash": d1, "credit_hash": c1, "matched_by": "transfer_v1", "confidence": 9500},
        ),
        _resolver_event(
            "MarkedInternalTransfer",
            {"debit_hash": d2, "credit_hash": c2, "matched_by": "transfer_v1", "confidence": 9500},
        ),
    ]
    result = build_projection_from_events(events, "transactions_view")
    totals = result["totals"]
    assert totals["expense_paise"] == 0, "Both transfer debits must be excluded from expense totals"
    assert totals["income_paise"] == 0, "Both transfer credits must be excluded from income totals"
    assert totals["excluded_count"] == 4  # type: ignore[index]


def test_marked_reversal_excludes_both_legs() -> None:
    original_hash = "o" * 64
    reversal_hash = "r" * 64
    events = [
        _txn(original_hash, -15000, "expense"),
        _txn(reversal_hash, 15000, "income"),
        _resolver_event(
            "MarkedReversal",
            {
                "original_hash": original_hash,
                "reversal_hash": reversal_hash,
                "matched_by": "reversal_v1",
                "confidence": 9500,
            },
        ),
    ]
    result = build_projection_from_events(events, "transactions_view")
    totals = result["totals"]
    assert totals["expense_paise"] == 0
    assert totals["income_paise"] == 0
    assert totals["excluded_count"] == 2  # type: ignore[index]


def test_non_excluded_transaction_still_counts() -> None:
    """Only the matched pair is excluded; unrelated transactions still count."""
    debit_hash = "d" * 64
    credit_hash = "c" * 64
    other_hash = "e" * 64
    events = [
        _txn(debit_hash, -50000, "expense"),
        _txn(credit_hash, 50000, "income"),
        _txn(other_hash, -12000, "expense"),
        _resolver_event(
            "MarkedInternalTransfer",
            {
                "debit_hash": debit_hash,
                "credit_hash": credit_hash,
                "matched_by": "transfer_v1",
                "confidence": 9500,
            },
        ),
    ]
    result = build_projection_from_events(events, "transactions_view")
    totals = result["totals"]
    assert totals["expense_paise"] == 12000
    assert totals["income_paise"] == 0
    assert totals["excluded_count"] == 2  # type: ignore[index]
    assert len(result["transactions"]) == 3  # type: ignore[arg-type]


# ── Out-of-order resolver events ───────────────────────────────────────────────


def test_resolver_event_before_transaction_still_excludes() -> None:
    """Resolver event arrives before TransactionIngested — hash still excluded."""
    hash_val = "x" * 64
    events = [
        _resolver_event(
            "MarkedInternalTransfer",
            {
                "debit_hash": hash_val,
                "credit_hash": "y" * 64,
                "matched_by": "transfer_v1",
                "confidence": 9500,
            },
        ),
        _txn(hash_val, -50000, "expense"),
    ]
    result = build_projection_from_events(events, "transactions_view")
    totals = result["totals"]
    assert totals["expense_paise"] == 0, "Pre-declared exclusion must apply retroactively"
    assert totals["excluded_count"] == 1  # type: ignore[index]


# ── Unknown event type ─────────────────────────────────────────────────────────


def test_unknown_event_type_is_silently_ignored() -> None:
    events = [
        _txn("a" * 64, -10000, "expense"),
        Event(
            id=uuid.uuid4(),
            seq=99,
            event_version=1,
            event_type="SomeFutureEventType",
            user_id=_USER,
            aggregate_id="UNKNOWN",
            payload={"some": "data"},
            created_at=_NOW,
        ),
    ]
    result = build_projection_from_events(events, "transactions_view")
    assert len(result["transactions"]) == 1  # type: ignore[arg-type]
    assert result["totals"]["expense_paise"] == 10000  # type: ignore[index]


# ── Determinism (Invariant 3) ──────────────────────────────────────────────────


def test_projection_is_deterministic() -> None:
    """Same events twice → byte-identical output (Invariant 3)."""
    events = [
        _txn("a" * 64, -30000, "expense"),
        _txn("b" * 64, 80000, "income"),
        _resolver_event(
            "MarkedInternalTransfer",
            {
                "debit_hash": "a" * 64,
                "credit_hash": "b" * 64,
                "matched_by": "transfer_v1",
                "confidence": 9500,
            },
        ),
    ]
    result_a = build_projection_from_events(events, "transactions_view")
    result_b = build_projection_from_events(events, "transactions_view")
    assert json.dumps(result_a, sort_keys=True) == json.dumps(result_b, sort_keys=True)


# ── State structure ────────────────────────────────────────────────────────────


def test_transactions_list_contains_expected_fields() -> None:
    events = [_txn("a" * 64, -50000, "expense")]
    result = build_projection_from_events(events, "transactions_view")
    txns = result["transactions"]
    assert isinstance(txns, list)  # type: ignore[arg-type]
    assert len(txns) == 1  # type: ignore[arg-type]
    txn = txns[0]  # type: ignore[index]
    assert "idempotency_hash" in txn
    assert "amount_paise" in txn
    assert "value_date" in txn
    assert "transaction_type" in txn


def test_excluded_hashes_is_a_list() -> None:
    """excluded_hashes must be JSON-serializable (list, not set)."""
    result = build_projection_from_events([], "transactions_view")
    assert isinstance(result["excluded_hashes"], list)


def test_excluded_hashes_populated_after_resolver_event() -> None:
    h1 = "d" * 64
    h2 = "c" * 64
    events = [
        _resolver_event(
            "MarkedInternalTransfer",
            {"debit_hash": h1, "credit_hash": h2, "matched_by": "v1", "confidence": 9000},
        )
    ]
    result = build_projection_from_events(events, "transactions_view")
    excluded = result["excluded_hashes"]
    assert h1 in excluded  # type: ignore[operator]
    assert h2 in excluded  # type: ignore[operator]


def test_transactions_list_preserves_all_events_including_excluded() -> None:
    """transactions list contains ALL ingested transactions, not just active ones."""
    h = "a" * 64
    events = [
        _txn(h, -50000, "expense"),
        _resolver_event(
            "MarkedInternalTransfer",
            {"debit_hash": h, "credit_hash": "b" * 64, "matched_by": "v1", "confidence": 9000},
        ),
    ]
    result = build_projection_from_events(events, "transactions_view")
    assert len(result["transactions"]) == 1  # type: ignore[arg-type]
    assert result["totals"]["excluded_count"] == 1  # type: ignore[index]
