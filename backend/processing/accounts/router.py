"""Account transaction list endpoint. Implements PRD §15 E12 (audit drill-down).

Minimal scope: returns TRANSACTION_INGESTED rows for one account_ref filtered by
value_date range. No search, no pagination, no category joins. Phase 3.5 will
replace this with the full transaction list (PRD §4).
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Generator
from datetime import date

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from core.events.models import TransactionEvent
from core.events.types import TRANSACTION_INGESTED

router = APIRouter(tags=["accounts"])

_STUB_USER_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")

DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql+psycopg://localhost/finance")
_engine = None
_SessionLocal = None


def _get_session_local() -> sessionmaker:  # type: ignore[type-arg]
    global _engine, _SessionLocal  # noqa: PLW0603
    if _SessionLocal is None:
        _engine = create_engine(DATABASE_URL)
        _SessionLocal = sessionmaker(bind=_engine)
    return _SessionLocal


def get_db() -> Generator[Session, None, None]:
    db = _get_session_local()()
    try:
        yield db
    finally:
        db.close()


class AccountTransaction(BaseModel):
    idempotency_hash: str
    value_date: date
    amount_paise: str  # string — JSON numbers lose paise precision
    narration: str
    transaction_type: str
    account_ref: str


def get_account_transactions(
    session: Session,
    user_id: uuid.UUID,
    account_ref: str,
    from_date: date | None,
    to_date: date | None,
) -> list[AccountTransaction]:
    """Return TRANSACTION_INGESTED rows for account_ref, optionally filtered by value_date."""
    q = select(TransactionEvent).where(
        TransactionEvent.user_id == user_id,
        TransactionEvent.event_type == TRANSACTION_INGESTED,
        TransactionEvent.account_ref == account_ref,
    )
    if from_date is not None:
        q = q.where(TransactionEvent.value_date >= from_date)
    if to_date is not None:
        q = q.where(TransactionEvent.value_date <= to_date)
    q = q.order_by(TransactionEvent.value_date.desc(), TransactionEvent.seq.desc())

    rows = session.scalars(q).all()
    return [
        AccountTransaction(
            idempotency_hash=row.idempotency_hash,
            value_date=row.value_date,
            amount_paise=str(row.amount_paise),
            narration=row.narration,
            transaction_type=row.transaction_type,
            account_ref=row.account_ref,
        )
        for row in rows
    ]


# Minimal E12 drill-down only. Phase 3.5 adds search, filters, and pagination (PRD §4).
@router.get("/{account_ref}/transactions", response_model=list[AccountTransaction])
def account_transactions(
    account_ref: str,
    from_date: date | None = Query(None, alias="from"),  # noqa: B008
    to_date: date | None = Query(None, alias="to"),  # noqa: B008
    db: Session = Depends(get_db),  # noqa: B008
) -> list[AccountTransaction]:
    """List transactions for an account, filtered by value_date range."""
    return get_account_transactions(db, _STUB_USER_ID, account_ref, from_date, to_date)
