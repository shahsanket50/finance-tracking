"""Integration test: replay determinism (I3).

Calling build_projection twice on the same DB state produces identical output.
"""
from __future__ import annotations

import json
from datetime import date

import pytest
from sqlalchemy.orm import Session

from core.events.models import IngestionEvent, User
from core.events.store import append_event
from core.hashing.hash import compute_idempotency_hash
from core.projections.builder import build_projection


@pytest.mark.integration
def test_build_projection_is_deterministic(
    pg_session: Session,
    test_user: User,
    test_ingestion_event: IngestionEvent,
) -> None:
    """build_projection called twice on same state produces identical output (I3)."""
    for i in range(5):
        h = compute_idempotency_hash(
            "ACC009", date(2026, 1, i + 1), -10_000 * (i + 1), f"item{i}", 0
        )
        append_event(
            pg_session,
            user_id=test_user.id,
            event_type="TransactionIngested",
            aggregate_id="ACC009",
            payload={"index": i, "amount": str(-10_000 * (i + 1))},
            value_date=date(2026, 1, i + 1),
            amount_paise=-10_000 * (i + 1),
            idempotency_hash=h,
            transaction_type="expense",
            narration=f"item{i}",
            actor="system",
            ingestion_event_id=test_ingestion_event.id,
        )

    result_a = build_projection(pg_session, test_user.id, "events_list")
    result_b = build_projection(pg_session, test_user.id, "events_list")

    assert json.dumps(result_a, sort_keys=True) == json.dumps(result_b, sort_keys=True)
