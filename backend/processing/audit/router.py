"""Audit API endpoints: sync-history, overlap-map, dedup-ledger, resolver-pairings.

Implements PRD §15 (Audit Trail). All endpoints are read-only; they derive views
from the immutable event log. Wired by confirm.py + run_resolver() (TRD §2.3).
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Generator
from datetime import date, datetime
from typing import cast

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from core.events.encryption import decrypt_payload
from core.events.models import IngestionEvent, TransactionEvent
from core.events.types import (
    MARKED_CC_PAYMENT,
    MARKED_FD_BOOKING,
    MARKED_INTERNAL_TRANSFER,
    MARKED_REVERSAL,
    RESOLVER_EVENT_TYPES,
)
from core.projections.builder import build_projection
from processing.resolver.audit import build_audit_view

router = APIRouter()

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


# ── Response models ────────────────────────────────────────────────────────────


class SyncHistoryEntry(BaseModel):
    event_id: str
    account_ref: str
    bank: str
    period_start: date | None
    period_end: date | None
    status: str
    records_added: int
    records_skipped: int
    balance_check: str | None
    confidence: int | None
    created_at: datetime


class StatementBar(BaseModel):
    event_id: str
    period_start: date | None
    period_end: date | None
    overlaps_with: list[str]


class AccountOverlap(BaseModel):
    account_ref: str
    statements: list[StatementBar]


class OverlapMapResponse(BaseModel):
    accounts: list[AccountOverlap]


class DedupLedgerEntry(BaseModel):
    idempotency_hash: str
    amount_paise: str  # string — JSON numbers lose paise precision
    value_date: str
    account_ref: str
    transaction_type: str
    is_counted: bool
    exclusion_reason: str | None


class DedupLedgerResponse(BaseModel):
    total_seen: int
    total_counted: int
    total_excluded: int
    entries: list[DedupLedgerEntry]


class PairingLeg(BaseModel):
    role: str
    idempotency_hash: str


class ResolverPairing(BaseModel):
    event_id: str
    event_type: str
    matched_by: str
    confidence: int
    value_date: date
    legs: list[PairingLeg]


# ── Business logic (testable, called directly by endpoints) ───────────────────


def get_sync_history(session: Session, user_id: uuid.UUID) -> list[SyncHistoryEntry]:
    """Return all ingestion events for user_id, newest first."""
    rows = session.scalars(
        select(IngestionEvent)
        .where(IngestionEvent.user_id == user_id)
        .order_by(IngestionEvent.created_at.desc())
    ).all()

    entries: list[SyncHistoryEntry] = []
    for row in rows:
        payload = decrypt_payload(session, row.encryption_key_id, row.payload)
        entries.append(
            SyncHistoryEntry(
                event_id=str(row.id),
                account_ref=str(payload.get("account_ref", "")),
                bank=str(payload.get("bank", "")),
                period_start=row.period_start,
                period_end=row.period_end,
                status=row.status,
                records_added=row.records_added,
                records_skipped=row.records_skipped,
                balance_check=row.balance_check,
                confidence=row.confidence,
                created_at=row.created_at,
            )
        )
    return entries


def _periods_overlap(
    a_start: date | None,
    a_end: date | None,
    b_start: date | None,
    b_end: date | None,
) -> bool:
    """Return True iff two date ranges overlap. None means unknown — treated as no overlap."""
    if a_start is None or a_end is None or b_start is None or b_end is None:
        return False
    return a_start <= b_end and b_start <= a_end


def get_overlap_map(session: Session, user_id: uuid.UUID) -> OverlapMapResponse:
    """Return ingestion events grouped by account_ref with pairwise overlap detection."""
    rows = session.scalars(
        select(IngestionEvent)
        .where(IngestionEvent.user_id == user_id)
        .order_by(IngestionEvent.created_at.asc())
    ).all()

    by_account: dict[str, list[IngestionEvent]] = {}
    for row in rows:
        payload = decrypt_payload(session, row.encryption_key_id, row.payload)
        account_ref = str(payload.get("account_ref", ""))
        by_account.setdefault(account_ref, []).append(row)

    accounts: list[AccountOverlap] = []
    for account_ref, account_rows in by_account.items():
        bars: list[StatementBar] = []
        for i, row in enumerate(account_rows):
            overlaps_with: list[str] = [
                str(other.id)
                for j, other in enumerate(account_rows)
                if i != j
                and _periods_overlap(
                    row.period_start, row.period_end, other.period_start, other.period_end
                )
            ]
            bars.append(
                StatementBar(
                    event_id=str(row.id),
                    period_start=row.period_start,
                    period_end=row.period_end,
                    overlaps_with=overlaps_with,
                )
            )
        accounts.append(AccountOverlap(account_ref=account_ref, statements=bars))

    return OverlapMapResponse(accounts=accounts)


def get_dedup_ledger(
    session: Session,
    user_id: uuid.UUID,
    from_date: date | None,
    to_date: date | None,
) -> DedupLedgerResponse:
    """Return the seen-vs-counted ledger, optionally filtered by value_date range."""
    state = build_projection(session, user_id, "transactions_view")
    audit = build_audit_view(state)

    all_entries = cast(list[dict[str, object]], audit["entries"])

    if from_date is not None or to_date is not None:
        filtered: list[dict[str, object]] = []
        for entry in all_entries:
            try:
                vd = date.fromisoformat(str(entry.get("value_date", "")))
            except ValueError:
                filtered.append(entry)
                continue
            if from_date is not None and vd < from_date:
                continue
            if to_date is not None and vd > to_date:
                continue
            filtered.append(entry)
        all_entries = filtered

    ledger_entries = [
        DedupLedgerEntry(
            idempotency_hash=str(e["idempotency_hash"]),
            amount_paise=str(e["amount_paise"]),
            value_date=str(e["value_date"]),
            account_ref=str(e.get("account_ref", "")),
            transaction_type=str(e.get("transaction_type", "")),
            is_counted=bool(e["is_counted"]),
            exclusion_reason=str(e["exclusion_reason"]) if e.get("exclusion_reason") else None,
        )
        for e in all_entries
    ]

    total_seen = len(ledger_entries)
    total_counted = sum(1 for e in ledger_entries if e.is_counted)

    return DedupLedgerResponse(
        total_seen=total_seen,
        total_counted=total_counted,
        total_excluded=total_seen - total_counted,
        entries=ledger_entries,
    )


def _legs_for_pairing(event_type: str, payload: dict[str, object]) -> list[PairingLeg]:
    if event_type == MARKED_INTERNAL_TRANSFER:
        return [
            PairingLeg(role="debit", idempotency_hash=str(payload["debit_hash"])),
            PairingLeg(role="credit", idempotency_hash=str(payload["credit_hash"])),
        ]
    if event_type == MARKED_CC_PAYMENT:
        return [
            PairingLeg(role="savings_debit", idempotency_hash=str(payload["savings_debit_hash"])),
            PairingLeg(role="cc_credit", idempotency_hash=str(payload["cc_credit_hash"])),
        ]
    if event_type == MARKED_FD_BOOKING:
        return [
            PairingLeg(role="savings_debit", idempotency_hash=str(payload["savings_debit_hash"])),
            PairingLeg(role="fd_credit", idempotency_hash=str(payload["fd_credit_hash"])),
        ]
    if event_type == MARKED_REVERSAL:
        return [
            PairingLeg(role="original", idempotency_hash=str(payload["original_hash"])),
            PairingLeg(role="reversal", idempotency_hash=str(payload["reversal_hash"])),
        ]
    return []


def get_resolver_pairings(session: Session, user_id: uuid.UUID) -> list[ResolverPairing]:
    """Return all resolver decision events with matched-pair legs, newest first."""
    rows = session.scalars(
        select(TransactionEvent)
        .where(
            TransactionEvent.user_id == user_id,
            TransactionEvent.event_type.in_(list(RESOLVER_EVENT_TYPES)),
        )
        .order_by(TransactionEvent.value_date.desc(), TransactionEvent.seq.desc())
    ).all()

    pairings: list[ResolverPairing] = []
    for row in rows:
        payload = decrypt_payload(session, row.encryption_key_id, row.payload)
        pairings.append(
            ResolverPairing(
                event_id=str(row.id),
                event_type=row.event_type,
                matched_by=str(payload.get("matched_by", "")),
                confidence=int(cast(int, payload.get("confidence", 0))),
                value_date=row.value_date,
                legs=_legs_for_pairing(row.event_type, payload),
            )
        )
    return pairings


# ── FastAPI endpoints ─────────────────────────────────────────────────────────


@router.get("/sync-history", response_model=list[SyncHistoryEntry])
def sync_history(db: Session = Depends(get_db)) -> list[SyncHistoryEntry]:  # noqa: B008
    """List all statement ingestion events for the current user, newest first."""
    return get_sync_history(db, _STUB_USER_ID)


@router.get("/overlap-map", response_model=OverlapMapResponse)
def overlap_map(db: Session = Depends(get_db)) -> OverlapMapResponse:  # noqa: B008
    """Return statements grouped by account with pairwise period overlap detection."""
    return get_overlap_map(db, _STUB_USER_ID)


@router.get("/dedup-ledger", response_model=DedupLedgerResponse)
def dedup_ledger(
    from_date: date | None = Query(None, alias="from"),  # noqa: B008
    to_date: date | None = Query(None, alias="to"),  # noqa: B008
    db: Session = Depends(get_db),  # noqa: B008
) -> DedupLedgerResponse:
    """Return the seen-vs-counted dedup ledger. Optional ?from=YYYY-MM-DD&to=YYYY-MM-DD filter."""
    return get_dedup_ledger(db, _STUB_USER_ID, from_date, to_date)


@router.get("/resolver-pairings", response_model=list[ResolverPairing])
def resolver_pairings(db: Session = Depends(get_db)) -> list[ResolverPairing]:  # noqa: B008
    """List all resolver decision events with their matched-pair legs."""
    return get_resolver_pairings(db, _STUB_USER_ID)
