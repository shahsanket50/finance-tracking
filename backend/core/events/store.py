"""Event-log primitives: append and read from the transaction_events table.

Implements the write side of the event-sourcing core.
Absorbs TRD requirements C4 (event_version + upcasters) and H2 (payload encryption).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from core.events.encryption import decrypt_payload, encrypt_payload
from core.events.models import TransactionEvent
from core.events.upcasters import upcast


@dataclass
class Event:
    id: uuid.UUID
    seq: int
    event_version: int
    event_type: str
    user_id: uuid.UUID
    aggregate_id: str  # maps to account_ref for transaction_events
    payload: dict[str, object]  # decrypted + upcasted to latest version
    created_at: datetime


def append_event(
    session: Session,
    user_id: uuid.UUID,
    event_type: str,
    aggregate_id: str,  # maps to account_ref
    payload: dict[str, Any],  # plain dict — encrypted internally
    *,
    event_version: int = 1,
    # Required transaction_events columns — pulled from payload if not supplied:
    value_date: date | None = None,
    amount_paise: int = 0,
    idempotency_hash: str | None = None,
    occurrence_index: int = 0,
    transaction_type: str = "expense",
    narration: str = "",
    actor: str = "system",
    ingestion_event_id: uuid.UUID | None = None,
    confidence: int | None = None,
    running_balance_paise: int | None = None,
    normalized_narration: str | None = None,
) -> int:
    """Append a TransactionEvent to the event log.

    Returns the global seq number of the appended event.
    Encrypts the payload before writing (H2).
    """
    encrypted_bytes, key_id = encrypt_payload(session, user_id, payload)

    # If ingestion_event_id is not supplied, look up or create one.
    # For scaffold tests, supply ingestion_event_id explicitly.
    # (Phase 1 ingestion pipeline will always supply it.)

    row = TransactionEvent(
        user_id=user_id,
        event_type=event_type,
        event_version=event_version,
        account_ref=aggregate_id,
        value_date=value_date or date.today(),
        amount_paise=amount_paise,
        idempotency_hash=idempotency_hash or "",
        occurrence_index=occurrence_index,
        transaction_type=transaction_type,
        narration=narration,
        normalized_narration=normalized_narration,
        running_balance_paise=running_balance_paise,
        actor=actor,
        confidence=confidence,
        payload=encrypted_bytes,
        encryption_key_id=key_id,
        ingestion_event_id=ingestion_event_id,
    )
    session.add(row)
    session.flush()  # populates row.seq from DB
    session.refresh(row)
    return int(row.seq)


def read_stream(
    session: Session,
    user_id: uuid.UUID,
    aggregate_id: str,
    *,
    since_seq: int = 0,
) -> list[Event]:
    """Read transaction events for (user_id, account_ref), ordered by seq.

    Decrypts each payload (H2) and upcasts to latest event_version (C4).
    """
    stmt = (
        select(TransactionEvent)
        .where(
            TransactionEvent.user_id == user_id,
            TransactionEvent.account_ref == aggregate_id,
            TransactionEvent.seq > since_seq,
        )
        .order_by(TransactionEvent.seq)
    )
    rows = session.scalars(stmt).all()
    return [_to_event(session, row) for row in rows]


def read_since_seq(
    session: Session,
    user_id: uuid.UUID,
    since_seq: int = 0,
) -> list[Event]:
    """Read all transaction events for user_id after since_seq, ordered by seq."""
    stmt = (
        select(TransactionEvent)
        .where(
            TransactionEvent.user_id == user_id,
            TransactionEvent.seq > since_seq,
        )
        .order_by(TransactionEvent.seq)
    )
    rows = session.scalars(stmt).all()
    return [_to_event(session, row) for row in rows]


def _to_event(session: Session, row: TransactionEvent) -> Event:
    raw_payload = decrypt_payload(session, row.encryption_key_id, row.payload)
    upcasted = upcast(row.event_type, row.event_version, raw_payload)
    return Event(
        id=row.id,
        seq=int(row.seq),
        event_version=row.event_version,
        event_type=row.event_type,
        user_id=row.user_id,
        aggregate_id=row.account_ref,
        payload=upcasted,
        created_at=row.created_at,
    )
