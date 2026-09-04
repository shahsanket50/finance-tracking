"""Statement ingestion API endpoints. Implements TRD §9.1 (upload → dry-run → confirm/abandon)."""

from __future__ import annotations

import os
import uuid
from collections.abc import Generator
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from ingestion.dryrun.abandon import abandon
from ingestion.dryrun.confirm import SessionExpiredError, confirm
from ingestion.dryrun.harness import dry_run
from ingestion.dryrun.session import DryRunSession
from ingestion.fetchers.pdf_reader import PasswordIncorrectError, PasswordRequiredError

DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql+psycopg://localhost/finance")
_engine = None
_SessionLocal = None


def _get_session_local() -> sessionmaker:  # type: ignore[type-arg]
    """Lazily initialise the engine so importing this module without psycopg is safe."""
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


router = APIRouter(tags=["statements"])

# TODO: replace with real auth dependency
_STUB_USER_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")


class SessionActionResponse(BaseModel):
    status: str
    session_id: str


class TransactionPreview(BaseModel):
    account_ref: str
    value_date: date
    amount_paise: str  # serialized as string — JSON numbers lose paise precision
    narration: str
    idempotency_hash: str
    occurrence_index: int


class DryRunPreview(BaseModel):
    session_id: str
    account_ref: str
    period_start: date
    period_end: date
    opening_balance_paise: str  # serialized as string — JSON numbers lose paise precision
    closing_balance_paise: str  # serialized as string — JSON numbers lose paise precision
    balance_check: str  # "pass" or "fail"
    transaction_count: int
    transactions: list[TransactionPreview]
    confidence: int


def _session_to_preview(session: DryRunSession) -> DryRunPreview:
    stmt = session.statement
    return DryRunPreview(
        session_id=session.session_id,
        account_ref=stmt.account_ref,
        period_start=stmt.period_start,
        period_end=stmt.period_end,
        opening_balance_paise=str(stmt.opening_balance_paise),
        closing_balance_paise=str(stmt.closing_balance_paise),
        balance_check=session.balance_check.value,
        transaction_count=len(stmt.transactions),
        transactions=[
            TransactionPreview(
                account_ref=t.account_ref,
                value_date=t.value_date,
                amount_paise=str(t.amount_paise),
                narration=t.narration,
                idempotency_hash=t.idempotency_hash,
                occurrence_index=t.occurrence_index,
            )
            for t in stmt.transactions
        ],
        confidence=stmt.confidence,
    )


@router.post("/upload", response_model=DryRunPreview)
async def upload_statement(
    file: UploadFile,
    account_ref: str,
    password: str | None = None,
) -> DryRunPreview:
    """Parse a PDF statement and return a dry-run preview. Writes nothing to the database."""
    pdf_bytes = await file.read()

    try:
        session = dry_run(pdf_bytes, _STUB_USER_ID, account_ref, password)
    except PasswordRequiredError as exc:
        raise HTTPException(status_code=400, detail="PDF requires a password") from exc
    except PasswordIncorrectError as exc:
        raise HTTPException(status_code=400, detail="PDF password is incorrect") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="Unsupported PDF format") from exc

    return _session_to_preview(session)


@router.post("/{session_id}/confirm", response_model=SessionActionResponse)
def confirm_session(
    session_id: str,
    db: Session = Depends(get_db),  # noqa: B008
) -> SessionActionResponse:
    """Commit a dry-run session to the database."""
    try:
        confirm(session_id, db)
    except SessionExpiredError as exc:
        raise HTTPException(status_code=404, detail="Session not found or expired") from exc

    return SessionActionResponse(status="confirmed", session_id=session_id)


@router.post("/{session_id}/abandon", response_model=SessionActionResponse)
def abandon_session(session_id: str) -> SessionActionResponse:
    """Delete a dry-run session from Redis without writing to the database."""
    abandon(session_id)
    return SessionActionResponse(status="abandoned", session_id=session_id)
