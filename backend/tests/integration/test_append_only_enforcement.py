"""Integration test: append-only enforcement.

The DB trigger must prevent UPDATE and DELETE on immutable event tables.
"""

from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import text
from sqlalchemy.exc import InternalError, ProgrammingError
from sqlalchemy.orm import Session

from core.events.models import IngestionEvent, User
from core.events.store import append_event
from core.hashing.hash import compute_idempotency_hash


@pytest.mark.integration
def test_update_transaction_event_raises(
    pg_session: Session,
    test_user: User,
    test_ingestion_event: IngestionEvent,
) -> None:
    """UPDATE on transaction_events must be rejected by the append-only trigger."""
    h = compute_idempotency_hash("ACC010", date(2026, 1, 1), -5_000, "test trigger", 0)
    seq = append_event(
        pg_session,
        user_id=test_user.id,
        event_type="TransactionIngested",
        aggregate_id="ACC010",
        payload={"narration": "test trigger"},
        value_date=date(2026, 1, 1),
        amount_paise=-5_000,
        idempotency_hash=h,
        transaction_type="expense",
        narration="test trigger",
        actor="system",
        ingestion_event_id=test_ingestion_event.id,
    )
    pg_session.flush()

    with pytest.raises((ProgrammingError, InternalError)):
        pg_session.execute(
            text("UPDATE transaction_events SET narration = 'tampered' WHERE seq = :seq"),
            {"seq": seq},
        )
        pg_session.flush()


@pytest.mark.integration
def test_delete_transaction_event_raises(
    pg_session: Session,
    test_user: User,
    test_ingestion_event: IngestionEvent,
) -> None:
    """DELETE on transaction_events must be rejected by the append-only trigger."""
    h = compute_idempotency_hash("ACC011", date(2026, 1, 1), -5_000, "test delete trigger", 0)
    seq = append_event(
        pg_session,
        user_id=test_user.id,
        event_type="TransactionIngested",
        aggregate_id="ACC011",
        payload={"narration": "test delete trigger"},
        value_date=date(2026, 1, 1),
        amount_paise=-5_000,
        idempotency_hash=h,
        transaction_type="expense",
        narration="test delete trigger",
        actor="system",
        ingestion_event_id=test_ingestion_event.id,
    )
    pg_session.flush()

    with pytest.raises((ProgrammingError, InternalError)):
        pg_session.execute(
            text("DELETE FROM transaction_events WHERE seq = :seq"),
            {"seq": seq},
        )
        pg_session.flush()
