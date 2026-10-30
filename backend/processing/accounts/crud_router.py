"""Account CRUD endpoints. Implements PRD §13 (Account Management).

CRUD operates on the mutable `accounts` table (TRD §3.2).
Balance derivation replays the immutable event log (TRD §9.2 — DERIVATION).
Deactivation is soft (sync_status = "deactivated") — the event log must remain
intact; hard delete would break replay (TRD §3.1).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from api_errors import (
    BALANCE_NOT_SUPPORTED,
    DERIVATION_ERROR_RESPONSES,
    ApiError,
    ledger_integrity_error,
)
from core.events.store import read_since_seq
from core.models.mutable import Account
from db import get_db
from processing.accounts.contract import (
    balance_legs_from_events,
    derive_cc_outstanding_liability,
    derive_savings_balance,
    load_statement_anchor,
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
_BALANCE_ACCOUNT_TYPES = frozenset({"savings", "current", "credit_card"})


def _require_account(db: Session, user_id: uuid.UUID, account_id: uuid.UUID) -> Account:
    account = db.scalar(select(Account).where(Account.id == account_id, Account.user_id == user_id))
    if account is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Account not found")
    return account


# ---------------------------------------------------------------------------
# CRUD routes
# ---------------------------------------------------------------------------


@router.get("", response_model=list[AccountResponse])
def list_accounts(db: Session = Depends(get_db)) -> list[Account]:  # noqa: B008
    """List all accounts for the authenticated user."""
    return list(db.scalars(select(Account).where(Account.user_id == _STUB_USER_ID)).all())


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
        created_at=datetime.now(UTC),
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


@router.get(
    "/{account_id}/balance",
    response_model=AccountBalanceResponse,
    responses=DERIVATION_ERROR_RESPONSES,
)
def get_account_balance(
    account_id: uuid.UUID,
    db: Session = Depends(get_db),  # noqa: B008
) -> AccountBalanceResponse:
    """Derive the account's balance from its latest statement anchor (PRD §8.1, ADR-022).

    DERIVATION: latest statement closing balance + every ingested leg dated after that
    statement, resolver-paired legs included (exclusion is for flow totals, not balances).
    savings/current → derived_balance_paise; credit_card → outstanding_liability_paise
    (−balance, unclamped: negative = credit balance). No anchor → the field is null and
    anchor_period_end is null: the balance is unknown, not zero.
    """
    account = _require_account(db, _STUB_USER_ID, account_id)

    if account.account_ref is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Account has no account_ref — cannot derive balance from event log",
        )

    account_type = account.account_type or "savings"
    if account_type not in _BALANCE_ACCOUNT_TYPES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=ApiError(
                code=BALANCE_NOT_SUPPORTED,
                message=f"No balance derivation for account_type={account_type!r}",
            ).model_dump(),
        )
    try:
        anchor = load_statement_anchor(db, _STUB_USER_ID, account.account_ref)
        legs = balance_legs_from_events(read_since_seq(db, _STUB_USER_ID), account.account_ref)
        if account_type == "credit_card":
            summary = derive_cc_outstanding_liability(account.account_ref, anchor, legs)
        else:
            summary = derive_savings_balance(account.account_ref, account_type, anchor, legs)
    except (ValueError, TypeError) as err:
        raise ledger_integrity_error(err) from err

    return AccountBalanceResponse(
        account_ref=account.account_ref,
        account_type=summary.account_type,
        derived_balance_paise=_money(summary.derived_balance_paise),
        outstanding_liability_paise=_money(summary.outstanding_liability_paise),
        anchor_period_end=None if anchor is None else anchor.period_end,
    )


def _money(paise: int | None) -> str | None:
    return None if paise is None else str(paise)
