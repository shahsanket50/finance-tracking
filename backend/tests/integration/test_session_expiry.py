"""Integration test: TTL expiry before confirm → zero DB writes.

Verifies Invariant 6 (confidence gate) and the session-expiry contract: when a
DryRunSession TTL expires in Redis before the user calls confirm(), the confirm()
call raises SessionExpiredError and no IngestionEvent or TransactionEvent is
written to the database.

Uses a real Redis container with actual TTL expiry — not a MagicMock returning None.
Implements PRD §9 / TRD §9.1 session lifecycle requirements.
"""

from __future__ import annotations

import time
import uuid
from datetime import UTC, datetime
from unittest.mock import patch

import pytest
import redis as redis_module
from sqlalchemy.orm import Session

from core.events.models import IngestionEvent, TransactionEvent
from core.hashing.hash import canonicalize_narration, compute_idempotency_hash
from ingestion.dryrun.confirm import SessionExpiredError, confirm
from ingestion.dryrun.session import DryRunSession, save_session
from ingestion.parsers.base import ParsedStatement, ParsedTransaction
from ingestion.validators.balance_check import BalanceCheckResult


def _build_minimal_dry_run_session(user_id: uuid.UUID) -> DryRunSession:
    """Build a synthetic DryRunSession with one transaction and a passing balance check.

    Balance check: opening(10000) + debit(-1000) = 9000 = closing → PASS.
    """
    account_ref = "TEST_ACC_EXPIRY"
    narration = "TEST PAYMENT EXPIRY"
    canonical = canonicalize_narration(narration)
    occurrence_index = 0
    value_date = datetime(2026, 1, 5).date()
    amount_paise = -1000

    idempotency_hash = compute_idempotency_hash(
        account_ref,
        value_date,
        amount_paise,
        canonical,
        occurrence_index,
    )

    txn = ParsedTransaction(
        account_ref=account_ref,
        value_date=value_date,
        amount_paise=amount_paise,
        narration=narration,
        canonical_narration=canonical,
        occurrence_index=occurrence_index,
        idempotency_hash=idempotency_hash,
        running_balance_paise=None,
    )

    statement = ParsedStatement(
        bank="test",
        account_ref=account_ref,
        period_start=datetime(2026, 1, 1).date(),
        period_end=datetime(2026, 1, 31).date(),
        opening_balance_paise=10000,
        closing_balance_paise=9000,
        transactions=[txn],
        confidence=9000,
        raw_text="synthetic test statement for session expiry test",
    )

    return DryRunSession(
        session_id=str(uuid.uuid4()),
        user_id=user_id,
        account_ref=account_ref,
        statement=statement,
        balance_check=BalanceCheckResult.PASS,
        raw_artifact_content_hash="a" * 64,
        created_at=datetime.now(UTC),
    )


@pytest.mark.integration
def test_confirm_after_session_expiry_writes_nothing(
    pg_session: Session,
    test_user: object,
    redis_client: redis_module.Redis,
) -> None:
    """Session TTL expires before confirm → SessionExpiredError, zero DB writes.

    Flow:
    1. Build a DryRunSession with a PASS balance check.
    2. Store it in real Redis with TTL=1 second.
    3. Sleep 2 seconds so Redis evicts the key naturally.
    4. Attempt confirm() — must raise SessionExpiredError (key gone).
    5. Assert no IngestionEvent or TransactionEvent rows were written.
    """
    from core.events.models import User

    assert isinstance(test_user, User)

    dry_session = _build_minimal_dry_run_session(test_user.id)

    # Store in real Redis with TTL=1 second
    save_session(redis_client, dry_session, ttl=1)

    # Confirm the key is present before expiry
    from ingestion.dryrun.session import _redis_key

    assert redis_client.get(_redis_key(dry_session.session_id)) is not None, (
        "Key must be present immediately after save_session"
    )

    # Wait for real TTL expiry
    time.sleep(2)

    # Confirm key is genuinely gone (not mocked)
    assert redis_client.get(_redis_key(dry_session.session_id)) is None, (
        "Key must have expired from real Redis after 2 seconds (TTL=1)"
    )

    # Capture DB row counts before the confirm attempt
    rows_before_txn = pg_session.query(TransactionEvent).count()
    rows_before_ing = pg_session.query(IngestionEvent).count()

    # confirm() must raise SessionExpiredError because the session is gone
    with pytest.raises(SessionExpiredError):
        with patch("ingestion.dryrun.confirm.get_redis_client", return_value=redis_client):
            confirm(dry_session.session_id, pg_session)

    # No DB writes may have occurred
    assert pg_session.query(TransactionEvent).count() == rows_before_txn, (
        "TransactionEvent rows must not increase after SessionExpiredError"
    )
    assert pg_session.query(IngestionEvent).count() == rows_before_ing, (
        "IngestionEvent rows must not increase after SessionExpiredError"
    )
