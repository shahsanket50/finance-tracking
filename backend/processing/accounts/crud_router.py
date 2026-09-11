"""Account CRUD endpoints. Implements PRD §13 (Account Management).

CRUD operates on the mutable `accounts` table (TRD §3.2).
Balance derivation replays the immutable event log (TRD §9.2 — DERIVATION).
Deactivation is soft (sync_status = "deactivated") — the event log must remain
intact; hard delete would break replay (TRD §3.1).
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Generator
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from core.events.models import TransactionEvent
from core.events.types import RESOLVER_EVENT_TYPES, TRANSACTION_INGESTED
from core.models.mutable import Account
from processing.accounts.balance import (
    derive_cc_outstanding_liability,
    derive_savings_balance,
)
from processing.accounts.schemas import (
    AccountBalanceResponse,
    AccountCreate,
    AccountResponse,
    AccountUpdate,
)

router = APIRouter(prefix="/accounts", tags=["accounts"])

# TODO: replace with real auth dependency in Phase 5
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


def _require_account(db: Session, user_id: uuid.UUID, account_id: uuid.UUID) -> Account:
    account = db.scalar(
        select(Account).where(Account.id == account_id, Account.user_id == user_id)
    )
    if account is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Account not found")
    return account


# ---------------------------------------------------------------------------
# CRUD routes
# ---------------------------------------------------------------------------


@router.get("", response_model=list[AccountResponse])
def list_accounts(db: Session = Depends(get_db)) -> list[Account]:  # noqa: B008
    """List all accounts for the authenticated user."""
    return list(
        db.scalars(select(Account).where(Account.user_id == _STUB_USER_ID)).all()
    )


@router.post("", response_model=AccountResponse, status_code=status.HTTP_201_CREATED)
def create_account(body: AccountCreate, db: Session = Depends(get_db)) -> Account:  # noqa: B008
    """Create a new account record. Does not trigger statement ingestion."""
    account = Account(
        user_id=_STUB_USER_ID,
        account_ref=body.account_ref,
        nickname=body.nickname,
        account_type=body.account_type,
        last4=body.last4,
        sync_status="pending",
        created_at=datetime.now(timezone.utc),
    )
    db.add(account)
    db.commit()
    db.refresh(account)
    return account


@router.get("/{account_id}", response_model=AccountResponse)
def get_account(account_id: uuid.UUID, db: Session = Depends(get_db)) -> Account:  # noqa: B008
    """Get a single account by ID."""
    return _require_account(db, _STUB_USER_ID, account_id)


@router.patch("/{account_id}", response_model=AccountResponse)
def update_account(
    account_id: uuid.UUID,
    body: AccountUpdate,
    db: Session = Depends(get_db),  # noqa: B008
) -> Account:
    """Update account metadata (nickname, type, last4)."""
    account = _require_account(db, _STUB_USER_ID, account_id)
    if body.nickname is not None:
        account.nickname = body.nickname
    if body.account_type is not None:
        account.account_type = body.account_type
    if body.last4 is not None:
        account.last4 = body.last4
    db.commit()
    db.refresh(account)
    return account


@router.delete("/{account_id}", status_code=status.HTTP_204_NO_CONTENT)
def deactivate_account(
    account_id: uuid.UUID,
    db: Session = Depends(get_db),  # noqa: B008
) -> None:
    """Soft-deactivate an account (sync_status = "deactivated").

    Hard delete is not permitted — the event log references this account_ref
    and must remain intact for replay (TRD §3.1). Per TRD §9.3 (crypto-shredding),
    deactivation destroys the active encryption key; the account data is recoverable
    by re-issuing a key. UI must say "deactivated," never "deleted."
    """
    account = _require_account(db, _STUB_USER_ID, account_id)
    account.sync_status = "deactivated"
    db.commit()


# ---------------------------------------------------------------------------
# Balance derivation
# ---------------------------------------------------------------------------


@router.get("/{account_id}/balance", response_model=AccountBalanceResponse)
def get_account_balance(
    account_id: uuid.UUID,
    db: Session = Depends(get_db),  # noqa: B008
) -> AccountBalanceResponse:
    """Derive the current balance for an account from the event log.

    DERIVATION — replays TransactionIngested events. Two formulas, kept separate:
    - savings/current: net signed sum of non-excluded amounts (asset)
    - credit_card: sum of non-excluded amounts floored at 0 (liability)

    Excluded transactions (MarkedInternalTransfer, MarkedCCPayment, etc.) are
    identified by querying the resolver's exclusion event types from the event log.
    """
    account = _require_account(db, _STUB_USER_ID, account_id)

    if account.account_ref is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Account has no account_ref — cannot derive balance from event log",
        )

    # Fetch all TRANSACTION_INGESTED events for this account_ref
    txn_rows = db.scalars(
        select(TransactionEvent).where(
            TransactionEvent.user_id == _STUB_USER_ID,
            TransactionEvent.account_ref == account.account_ref,
            TransactionEvent.event_type == TRANSACTION_INGESTED,
        )
    ).all()

    # Fetch hashes of excluded transactions (resolver events)
    excluded_hashes: set[str] = set(
        db.scalars(
            select(TransactionEvent.idempotency_hash).where(
                TransactionEvent.user_id == _STUB_USER_ID,
                TransactionEvent.event_type.in_(list(RESOLVER_EVENT_TYPES)),
            )
        ).all()
    )

    non_excluded_amounts: list[int] = [
        row.amount_paise
        for row in txn_rows
        if row.idempotency_hash not in excluded_hashes
    ]

    account_type = account.account_type or "savings"

    if account_type == "credit_card":
        summary = derive_cc_outstanding_liability(
            account_ref=account.account_ref,
            non_excluded_amounts_paise=non_excluded_amounts,
        )
        return AccountBalanceResponse(
            account_ref=account.account_ref,
            account_type=account_type,
            derived_balance_paise=None,
            outstanding_liability_paise=str(summary.outstanding_liability_paise),
        )
    else:
        summary = derive_savings_balance(
            account_ref=account.account_ref,
            account_type=account_type,
            non_excluded_amounts_paise=non_excluded_amounts,
        )
        return AccountBalanceResponse(
            account_ref=account.account_ref,
            account_type=account_type,
            derived_balance_paise=str(summary.derived_balance_paise),
            outstanding_liability_paise=None,
        )
