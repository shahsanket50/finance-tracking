"""Integration: confirm() automatically runs the resolver after ingestion (TRD §2.3).

Verifies that a real confirm() call on a statement containing a transfer pair produces
a MarkedInternalTransfer event WITHOUT any audit endpoint being called. This is the
Phase 2.5 Wave 3 wiring test — it proves the resolver runs automatically at confirm time.
"""

from __future__ import annotations

import pickle
import uuid
from datetime import UTC, datetime
from datetime import date as date_type
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from core.events.models import TransactionEvent, User
from core.events.store import read_since_seq
from core.events.types import MARKED_INTERNAL_TRANSFER, TRANSACTION_INGESTED
from core.hashing.hash import canonicalize_narration, compute_idempotency_hash
from core.projections.builder import build_projection_from_events
from ingestion.dryrun.confirm import confirm
from ingestion.dryrun.session import DryRunSession
from ingestion.parsers.base import ParsedStatement, ParsedTransaction
from ingestion.validators.balance_check import BalanceCheckResult
from processing.resolver.pipeline import run_resolver


def _make_transfer_pair_session(user_id: uuid.UUID) -> DryRunSession:
    """Build a DryRunSession containing a savings↔savings transfer pair.

    Debit: -50000 paise; Credit: +50000 paise. Same account, same date.
    The transfer matcher will produce a MarkedInternalTransfer for this pair.
    """
    account_ref = "HDFC_SAVINGS_TEST"
    value_date = date_type(2026, 1, 15)

    debit_narration = "TRANSFER TO SBI"
    debit_canonical = canonicalize_narration(debit_narration)
    debit_hash = compute_idempotency_hash(account_ref, value_date, -50000, debit_canonical, 0)
    debit = ParsedTransaction(
        account_ref=account_ref,
        value_date=value_date,
        amount_paise=-50000,
        narration=debit_narration,
        canonical_narration=debit_canonical,
        occurrence_index=0,
        idempotency_hash=debit_hash,
        running_balance_paise=None,
    )

    credit_narration = "TRANSFER FROM HDFC"
    credit_canonical = canonicalize_narration(credit_narration)
    credit_hash = compute_idempotency_hash(account_ref, value_date, 50000, credit_canonical, 0)
    credit = ParsedTransaction(
        account_ref=account_ref,
        value_date=value_date,
        amount_paise=50000,
        narration=credit_narration,
        canonical_narration=credit_canonical,
        occurrence_index=0,
        idempotency_hash=credit_hash,
        running_balance_paise=None,
    )

    statement = ParsedStatement(
        bank="hdfc_savings",
        account_ref=account_ref,
        account_type="savings",
        period_start=date_type(2026, 1, 1),
        period_end=date_type(2026, 1, 31),
        opening_balance_paise=0,
        closing_balance_paise=0,  # debit + credit nets to 0; balance passes
        transactions=[debit, credit],
        confidence=9000,
        raw_text="synthetic transfer pair statement",
    )

    return DryRunSession(
        session_id=str(uuid.uuid4()),
        user_id=user_id,
        account_ref=account_ref,
        statement=statement,
        balance_check=BalanceCheckResult.PASS,
        raw_artifact_content_hash="b" * 64,
        created_at=datetime.now(UTC),
    )


@pytest.mark.integration
def test_confirm_wires_resolver_automatically(pg_session: Session, test_user: User) -> None:
    """confirm() on a statement with a transfer pair → MarkedInternalTransfer written.

    No audit endpoint is called. The resolver runs as part of confirm() (TRD §2.3).
    """
    assert isinstance(test_user, User)
    dry_session = _make_transfer_pair_session(test_user.id)

    mock_redis = MagicMock()
    mock_redis.get.return_value = pickle.dumps(dry_session)

    with patch("ingestion.dryrun.confirm.get_redis_client", return_value=mock_redis):
        confirm(dry_session.session_id, pg_session)

    txn_rows = pg_session.scalars(
        select(TransactionEvent).where(
            TransactionEvent.user_id == test_user.id,
            TransactionEvent.event_type == TRANSACTION_INGESTED,
        )
    ).all()
    assert len(txn_rows) == 2, f"Expected 2 TransactionIngested rows, got {len(txn_rows)}"

    resolver_rows = pg_session.scalars(
        select(TransactionEvent).where(
            TransactionEvent.user_id == test_user.id,
            TransactionEvent.event_type == MARKED_INTERNAL_TRANSFER,
        )
    ).all()
    assert len(resolver_rows) == 1, (
        f"Expected 1 MarkedInternalTransfer event from automatic resolver run, "
        f"got {len(resolver_rows)}"
    )


@pytest.mark.integration
def test_confirm_resolver_idempotent_on_rerun(pg_session: Session, test_user: User) -> None:
    """run_resolver() called again after confirm() writes 0 new events (idempotent catch-up)."""
    assert isinstance(test_user, User)
    dry_session = _make_transfer_pair_session(test_user.id)

    mock_redis = MagicMock()
    mock_redis.get.return_value = pickle.dumps(dry_session)

    with patch("ingestion.dryrun.confirm.get_redis_client", return_value=mock_redis):
        confirm(dry_session.session_id, pg_session)

    resolver_rows_after_confirm = pg_session.scalars(
        select(TransactionEvent).where(
            TransactionEvent.user_id == test_user.id,
            TransactionEvent.event_type == MARKED_INTERNAL_TRANSFER,
        )
    ).all()
    assert len(resolver_rows_after_confirm) == 1

    new_events = run_resolver(pg_session, test_user.id)
    assert new_events == 0, f"Idempotent re-run must write 0 new events, wrote {new_events}"

    resolver_rows_after_rerun = pg_session.scalars(
        select(TransactionEvent).where(
            TransactionEvent.user_id == test_user.id,
            TransactionEvent.event_type == MARKED_INTERNAL_TRANSFER,
        )
    ).all()
    assert len(resolver_rows_after_rerun) == 1, (
        "Duplicate resolver events must not be written on idempotent re-run"
    )


@pytest.mark.integration
def test_confirm_event_type_casing_end_to_end(pg_session: Session, test_user: User) -> None:
    """End-to-end B-1 regression: real confirm() → real DB event → reducer recognizes it.

    The unit-level casing test only checks that confirm.py passes the constant to a mock.
    This test verifies the full chain: correct event_type string written to Postgres,
    read back via read_since_seq(), processed by the reducer, and recognized as a
    TransactionIngested event (transactions list non-empty).

    If event_type were "transaction_ingested" (snake_case), the reducer would silently
    skip every event and return an empty transactions list — wrong-but-confident.
    """
    assert isinstance(test_user, User)
    dry_session = _make_transfer_pair_session(test_user.id)

    mock_redis = MagicMock()
    mock_redis.get.return_value = pickle.dumps(dry_session)

    with patch("ingestion.dryrun.confirm.get_redis_client", return_value=mock_redis):
        confirm(dry_session.session_id, pg_session)

    # Read events back from DB and run reducer
    events = read_since_seq(pg_session, test_user.id, since_seq=0)
    state = build_projection_from_events(events, "transactions_view")

    import typing

    transactions = typing.cast(list[dict[str, object]], state["transactions"])
    assert len(transactions) == 2, (
        f"Expected 2 transactions, got {len(transactions)}. "
        "If 0, reducer is not recognizing TransactionIngested (check event_type casing)."
    )
