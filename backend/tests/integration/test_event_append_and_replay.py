"""Integration test: append events and build projections.

Tests the full path: write event → read back → build projection.
"""

from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy.orm import Session

from core.events.models import IngestionEvent, User
from core.events.store import append_event, read_since_seq
from core.hashing.hash import compute_idempotency_hash
from core.projections.builder import build_projection


@pytest.mark.integration
def test_append_event_returns_seq(
    pg_session: Session,
    test_user: User,
    test_ingestion_event: IngestionEvent,
) -> None:
    """append_event returns an integer seq number."""
    hash_val = compute_idempotency_hash("ACC001", date(2026, 1, 15), -50_000, "swiggy", 0)
    seq = append_event(
        pg_session,
        user_id=test_user.id,
        event_type="TransactionIngested",
        aggregate_id="ACC001",
        payload={"narration": "Swiggy food order"},
        value_date=date(2026, 1, 15),
        amount_paise=-50_000,
        idempotency_hash=hash_val,
        transaction_type="expense",
        narration="Swiggy food order",
        actor="system",
        ingestion_event_id=test_ingestion_event.id,
    )
    assert isinstance(seq, int)
    assert seq > 0


@pytest.mark.integration
def test_read_stream_returns_events_in_order(
    pg_session: Session,
    test_user: User,
    test_ingestion_event: IngestionEvent,
) -> None:
    """Events read back in seq order (H7)."""
    hashes = [
        compute_idempotency_hash("ACC006", date(2026, 1, i + 1), -50_000 * (i + 1), f"txn{i}", 0)
        for i in range(3)
    ]
    seqs = []
    for i, h in enumerate(hashes):
        seq = append_event(
            pg_session,
            user_id=test_user.id,
            event_type="TransactionIngested",
            aggregate_id="ACC006",
            payload={"index": i},
            value_date=date(2026, 1, i + 1),
            amount_paise=-50_000 * (i + 1),
            idempotency_hash=h,
            transaction_type="expense",
            narration=f"txn{i}",
            actor="system",
            ingestion_event_id=test_ingestion_event.id,
        )
        seqs.append(seq)

    events = read_since_seq(pg_session, test_user.id)
    returned_seqs = [e.seq for e in events]
    assert returned_seqs == sorted(returned_seqs)
    assert len(returned_seqs) >= 3


@pytest.mark.integration
def test_build_projection_events_list(
    pg_session: Session,
    test_user: User,
    test_ingestion_event: IngestionEvent,
) -> None:
    """build_projection returns events_list projection with appended events."""
    h = compute_idempotency_hash("ACC007", date(2026, 2, 1), -100_000, "rent", 0)
    append_event(
        pg_session,
        user_id=test_user.id,
        event_type="TransactionIngested",
        aggregate_id="ACC007",
        payload={"narration": "Rent payment"},
        value_date=date(2026, 2, 1),
        amount_paise=-100_000,
        idempotency_hash=h,
        transaction_type="expense",
        narration="Rent payment",
        actor="system",
        ingestion_event_id=test_ingestion_event.id,
    )

    projection = build_projection(pg_session, test_user.id, "events_list")
    assert isinstance(projection["count"], int)
    assert projection["count"] >= 1


@pytest.mark.integration
def test_payload_round_trip(
    pg_session: Session,
    test_user: User,
    test_ingestion_event: IngestionEvent,
) -> None:
    """Payload survives encrypt → store → read → decrypt unchanged."""
    original_payload: dict[str, object] = {
        "narration": "Salary credit",
        "amount": "5000000",
        "meta": "test",
    }
    h = compute_idempotency_hash("ACC008", date(2026, 4, 1), 5_000_000, "salary credit", 0)

    append_event(
        pg_session,
        user_id=test_user.id,
        event_type="TransactionIngested",
        aggregate_id="ACC008",
        payload=original_payload,
        value_date=date(2026, 4, 1),
        amount_paise=5_000_000,
        idempotency_hash=h,
        transaction_type="income",
        narration="Salary credit",
        actor="system",
        ingestion_event_id=test_ingestion_event.id,
    )

    events = read_since_seq(pg_session, test_user.id)
    matching = [e for e in events if e.aggregate_id == "ACC008"]
    assert len(matching) >= 1
    assert matching[-1].payload == original_payload


@pytest.mark.integration
def test_sequence_is_globally_monotonic(
    pg_session: Session,
    test_user: User,
    test_ingestion_event: IngestionEvent,
) -> None:
    """Sequence numbers are global across aggregates, not reset per-aggregate (TRD §9.1)."""
    h1 = compute_idempotency_hash("AGG_ALPHA", date(2026, 3, 1), -10_000, "txn alpha", 0)
    h2 = compute_idempotency_hash("AGG_BETA", date(2026, 3, 2), -20_000, "txn beta", 0)

    seq_a = append_event(
        pg_session,
        user_id=test_user.id,
        event_type="TransactionIngested",
        aggregate_id="AGG_ALPHA",
        payload={"narration": "txn alpha"},
        value_date=date(2026, 3, 1),
        amount_paise=-10_000,
        idempotency_hash=h1,
        transaction_type="expense",
        narration="txn alpha",
        actor="system",
        ingestion_event_id=test_ingestion_event.id,
    )
    pg_session.flush()

    seq_b = append_event(
        pg_session,
        user_id=test_user.id,
        event_type="TransactionIngested",
        aggregate_id="AGG_BETA",
        payload={"narration": "txn beta"},
        value_date=date(2026, 3, 2),
        amount_paise=-20_000,
        idempotency_hash=h2,
        transaction_type="expense",
        narration="txn beta",
        actor="system",
        ingestion_event_id=test_ingestion_event.id,
    )
    pg_session.flush()

    # Sequence must be globally monotonic — different aggregates share the same counter
    assert seq_b > seq_a, "seq must be globally increasing, not reset per aggregate"
