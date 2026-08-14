"""Integration tests: idempotency invariants at the full pipeline level.

Two distinct idempotency scenarios:
1. Overlapping statement windows: confirming two sessions that share identical transactions
   triggers the unique constraint on (user_id, idempotency_hash) — Invariant 1.
2. Genuine same-day duplicate: two transactions with identical fields on the same day are
   distinguished by occurrence_index — both rows survive as distinct events.

Implements CLAUDE.md §2 Invariant 1, TRD §9.1 C1/C2.
Requires Docker (testcontainers). Verify syntax with:
    cd backend && PYTHONPATH=. python -c "import tests.integration.test_idempotent_ingest"
"""

from __future__ import annotations

import pickle
import uuid
from datetime import UTC, date, datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from core.events.models import TransactionEvent
from core.hashing.hash import canonicalize_narration, compute_idempotency_hash
from ingestion.dryrun.confirm import confirm
from ingestion.dryrun.harness import dry_run
from ingestion.dryrun.session import DryRunSession
from ingestion.parsers.base import ParsedStatement, ParsedTransaction
from ingestion.validators.balance_check import BalanceCheckResult

HDFC_CC_GOLDEN_PDF = (
    Path(__file__).parent.parent / "fixtures" / "golden" / "hdfc_cc" / "statement_001.pdf"
)


@pytest.fixture
def mock_redis() -> MagicMock:
    mock = MagicMock()
    mock.get.return_value = None  # default: no pre-existing session
    return mock


@pytest.fixture
def hdfc_cc_pdf_bytes() -> bytes:
    return HDFC_CC_GOLDEN_PDF.read_bytes()


def _dry_run_with_mock(
    pdf_bytes: bytes,
    user_id: uuid.UUID,
    account_ref: str,
    mock_redis: MagicMock,
) -> DryRunSession:
    """Run dry_run with a patched Redis client; return the DryRunSession."""
    with patch("ingestion.dryrun.harness.get_redis_client", return_value=mock_redis):
        return dry_run(pdf_bytes, user_id, account_ref)


def _confirm_with_session(dry_session: DryRunSession, pg_session: Session) -> None:
    """Run confirm() with a mocked Redis client that returns the given DryRunSession."""
    confirm_redis = MagicMock()
    confirm_redis.get.return_value = pickle.dumps(dry_session)
    with patch("ingestion.dryrun.confirm.get_redis_client", return_value=confirm_redis):
        confirm(dry_session.session_id, pg_session)


# ── Test 1: Overlapping statement confirms → IntegrityError on second ─────────


@pytest.mark.integration
def test_overlapping_statement_confirms_raises_on_duplicate(
    pg_session: Session,
    test_user: object,
    mock_redis: MagicMock,
    hdfc_cc_pdf_bytes: bytes,
) -> None:
    """Confirming two statements with identical transactions → IntegrityError on second.

    Verifies Invariant 1: no idempotency_hash appears twice in transaction_events.
    The unique constraint (user_id, idempotency_hash) enforces this at DB level.

    Simulates overlapping statement windows by constructing a second DryRunSession
    that carries the same ParsedStatement (identical idempotency_hashes) but has a
    different session_id and a distinct raw_artifact_content_hash. The second confirm
    must fail — the DB constraint is the enforcement mechanism, not application code.
    """
    from core.events.models import User

    assert isinstance(test_user, User)

    # First DryRunSession: parse HDFC CC golden PDF
    first_session = _dry_run_with_mock(hdfc_cc_pdf_bytes, test_user.id, "HDFC_CC_4321", mock_redis)
    first_session.user_id = test_user.id

    expected_count = len(first_session.statement.transactions)
    assert expected_count > 0, "Golden fixture must contain at least one transaction"

    # Confirm first session — should succeed and commit N rows
    _confirm_with_session(first_session, pg_session)

    count_after_first = pg_session.query(TransactionEvent).filter_by(user_id=test_user.id).count()
    assert count_after_first == expected_count

    # Build a second session: same statement data, new session_id, different content_hash
    # This simulates a second statement PDF that overlaps with the first.
    second_session = DryRunSession(
        session_id=str(uuid.uuid4()),
        user_id=test_user.id,
        account_ref=first_session.account_ref,
        statement=first_session.statement,  # identical transactions → identical hashes
        balance_check=BalanceCheckResult.PASS,
        raw_artifact_content_hash="c" * 64,  # distinct content hash avoids raw_artifact conflict
        created_at=datetime.now(UTC),
    )

    # Second confirm must raise IntegrityError — the unique constraint fires
    with pytest.raises(Exception) as exc_info:
        _confirm_with_session(second_session, pg_session)

    # The underlying cause must be an IntegrityError (may be wrapped)
    assert isinstance(exc_info.value, IntegrityError) or any(
        isinstance(cause, IntegrityError)
        for cause in (exc_info.value.__cause__, exc_info.value.__context__)
        if cause is not None
    ), f"Expected IntegrityError chain, got: {type(exc_info.value).__name__}: {exc_info.value}"

    # Roll back the failed second attempt; the total must not exceed N
    pg_session.rollback()

    total = pg_session.query(TransactionEvent).filter_by(user_id=test_user.id).count()
    assert total <= expected_count, (
        f"Expected at most {expected_count} rows after rollback, got {total}"
    )


# ── Test 2: Genuine same-day duplicate → both rows survive ────────────────────


@pytest.mark.integration
def test_genuine_same_day_duplicate_both_rows_survive(
    pg_session: Session,
    test_user: object,
    mock_redis: MagicMock,
) -> None:
    """Two ₹250 charges from same merchant on same day → both in transaction_events
    with occurrence_index 0 and 1 respectively.

    Verifies TRD §9.1 C2: occurrence_index differentiates genuinely identical-looking
    transactions. They produce distinct idempotency_hashes and both must land in the DB.
    """
    from core.events.models import User

    assert isinstance(test_user, User)

    account_ref = "HDFC_CC_TEST"
    txn_date = date(2025, 1, 15)
    amount_paise = -25000  # −₹250 debit
    narration = "Swiggy Order 12345"
    canonical = canonicalize_narration(narration)

    # Build two ParsedTransactions: same fields, but occurrence_index 0 and 1
    txn0 = ParsedTransaction(
        account_ref=account_ref,
        value_date=txn_date,
        amount_paise=amount_paise,
        narration=narration,
        canonical_narration=canonical,
        occurrence_index=0,
        idempotency_hash=compute_idempotency_hash(
            account_ref, txn_date, amount_paise, canonical, 0
        ),
        running_balance_paise=None,
    )
    txn1 = ParsedTransaction(
        account_ref=account_ref,
        value_date=txn_date,
        amount_paise=amount_paise,
        narration=narration,
        canonical_narration=canonical,
        occurrence_index=1,
        idempotency_hash=compute_idempotency_hash(
            account_ref, txn_date, amount_paise, canonical, 1
        ),
        running_balance_paise=None,
    )

    assert txn0.idempotency_hash != txn1.idempotency_hash, (
        "C2 invariant: different occurrence_index must produce different hashes"
    )

    # Construct a synthetic ParsedStatement with a valid balance (opening + txn0 + txn1 == closing)
    # opening=100000 (₹1000), two debits of -25000 each → closing=50000 (₹500)
    opening = 100_000
    closing = opening + amount_paise + amount_paise  # 100000 − 25000 − 25000 = 50000
    statement = ParsedStatement(
        bank="HDFC",
        account_ref=account_ref,
        period_start=txn_date,
        period_end=txn_date,
        opening_balance_paise=opening,
        closing_balance_paise=closing,
        transactions=[txn0, txn1],
        confidence=9000,
        raw_text="synthetic",
    )

    # Build a DryRunSession directly (no PDF parsing needed)
    dry_session = DryRunSession(
        session_id=str(uuid.uuid4()),
        user_id=test_user.id,
        account_ref=account_ref,
        statement=statement,
        balance_check=BalanceCheckResult.PASS,
        raw_artifact_content_hash="d" * 64,
        created_at=datetime.now(UTC),
    )

    # Confirm the session — both transactions must land in the DB
    _confirm_with_session(dry_session, pg_session)

    rows = (
        pg_session.query(TransactionEvent)
        .filter_by(user_id=test_user.id, account_ref=account_ref)
        .order_by(TransactionEvent.occurrence_index)
        .all()
    )

    assert len(rows) == 2, f"Expected 2 transaction rows, got {len(rows)}"
    assert rows[0].occurrence_index == 0
    assert rows[1].occurrence_index == 1
    assert rows[0].idempotency_hash != rows[1].idempotency_hash, (
        "Both rows must have distinct idempotency_hashes"
    )
    assert rows[0].amount_paise == amount_paise
    assert rows[1].amount_paise == amount_paise
    assert rows[0].canonical_narration == canonical
    assert rows[1].canonical_narration == canonical
