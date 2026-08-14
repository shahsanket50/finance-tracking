"""Integration: resolver events correctly exclude transactions from totals (Invariant 4).

Uses ephemeral Postgres via testcontainers (same harness as Phase 1 integration tests).
Verifies the full pipeline: append TransactionIngested + resolver events → build
transactions_view projection → assert excluded_count and zero totals for matched pairs.
"""

import uuid
from datetime import date, datetime, timezone

import pytest

from core.events.models import User
from core.events.store import append_event, read_since_seq
from core.projections.builder import build_projection_from_events
from processing.resolver.audit import build_audit_view


@pytest.mark.integration
def test_transfer_pair_excluded_from_totals(pg_session, test_user, test_ingestion_event_id):
    """Two savings transfers → excluded from expense/income totals via MarkedInternalTransfer."""
    assert isinstance(test_user, User)
    user_id = test_user.id
    debit_hash = "d" * 64
    credit_hash = "c" * 64

    # Ingest debit leg
    append_event(
        pg_session, user_id,
        event_type="TransactionIngested",
        aggregate_id="HDFC_SAVINGS",
        payload={
            "idempotency_hash": debit_hash,
            "amount_paise": -50000,
            "value_date": "2026-01-10",
            "account_ref": "HDFC_SAVINGS",
            "canonical_narration": "TRANSFER TO SBI",
            "transaction_type": "expense",
        },
        value_date=date(2026, 1, 10),
        amount_paise=-50000,
        idempotency_hash=debit_hash,
        transaction_type="expense",
        narration="TRANSFER TO SBI",
        ingestion_event_id=test_ingestion_event_id,
    )

    # Ingest credit leg
    append_event(
        pg_session, user_id,
        event_type="TransactionIngested",
        aggregate_id="SBI_SAVINGS",
        payload={
            "idempotency_hash": credit_hash,
            "amount_paise": 50000,
            "value_date": "2026-01-10",
            "account_ref": "SBI_SAVINGS",
            "canonical_narration": "TRANSFER FROM HDFC",
            "transaction_type": "income",
        },
        value_date=date(2026, 1, 10),
        amount_paise=50000,
        idempotency_hash=credit_hash,
        transaction_type="income",
        narration="TRANSFER FROM HDFC",
        ingestion_event_id=test_ingestion_event_id,
    )

    # Resolver decision
    resolver_hash = "r" * 64  # unique idempotency_hash for this resolver event
    append_event(
        pg_session, user_id,
        event_type="MarkedInternalTransfer",
        aggregate_id="RESOLVER",
        payload={
            "debit_hash": debit_hash,
            "credit_hash": credit_hash,
            "matched_by": "transfer_v1",
            "confidence": 9500,
        },
        value_date=date(2026, 1, 10),
        amount_paise=0,
        idempotency_hash=resolver_hash,
        transaction_type="transfer",
        narration="",
        ingestion_event_id=test_ingestion_event_id,
    )

    pg_session.commit()

    events = read_since_seq(pg_session, user_id, since_seq=0)
    state = build_projection_from_events(events, "transactions_view")

    assert state["totals"]["expense_paise"] == 0, "Transfer debit must not appear in expense totals"
    assert state["totals"]["income_paise"] == 0, "Transfer credit must not appear in income totals"
    assert state["totals"]["excluded_count"] == 2

    audit = build_audit_view(state)
    assert audit["total_seen"] == 2
    assert audit["total_counted"] == 0
    assert audit["total_excluded"] == 2
    for entry in audit["entries"]:
        assert entry["exclusion_reason"] == "internal_transfer"
        assert entry["is_counted"] is False


@pytest.mark.integration
def test_non_transfer_transaction_still_counted(pg_session, test_user, test_ingestion_event_id):
    """Unrelated transaction is not excluded when a transfer pair is marked."""
    assert isinstance(test_user, User)
    user_id = test_user.id
    transfer_debit = "t" * 64
    transfer_credit = "u" * 64
    expense_hash = "e" * 64

    for h, amt, acct, txn_type, narr in [
        (transfer_debit, -50000, "HDFC_SAVINGS", "expense", "TRANSFER"),
        (transfer_credit, 50000, "SBI_SAVINGS", "income", "TRANSFER RECV"),
        (expense_hash, -12000, "HDFC_SAVINGS", "expense", "SWIGGY"),
    ]:
        append_event(
            pg_session, user_id,
            event_type="TransactionIngested",
            aggregate_id=acct,
            payload={
                "idempotency_hash": h,
                "amount_paise": amt,
                "value_date": "2026-01-15",
                "account_ref": acct,
                "canonical_narration": narr,
                "transaction_type": txn_type,
            },
            value_date=date(2026, 1, 15),
            amount_paise=amt,
            idempotency_hash=h,
            transaction_type=txn_type,
            narration=narr,
            ingestion_event_id=test_ingestion_event_id,
        )

    append_event(
        pg_session, user_id,
        event_type="MarkedInternalTransfer",
        aggregate_id="RESOLVER",
        payload={
            "debit_hash": transfer_debit,
            "credit_hash": transfer_credit,
            "matched_by": "transfer_v1",
            "confidence": 9500,
        },
        value_date=date(2026, 1, 15),
        amount_paise=0,
        idempotency_hash="rr" * 32,
        transaction_type="transfer",
        narration="",
        ingestion_event_id=test_ingestion_event_id,
    )

    pg_session.commit()
    events = read_since_seq(pg_session, user_id, since_seq=0)
    state = build_projection_from_events(events, "transactions_view")

    assert state["totals"]["expense_paise"] == 12000, "Swiggy expense must still be counted"
    assert state["totals"]["income_paise"] == 0
    assert state["totals"]["excluded_count"] == 2
