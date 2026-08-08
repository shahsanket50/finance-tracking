"""Tests for confirm() — independently authored from spec (PRD phase 1, Wave 4A)."""

from __future__ import annotations

import pickle
import uuid
from datetime import UTC, date, datetime
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy.orm import Session

from core.hashing.hash import canonicalize_narration, compute_idempotency_hash
from ingestion.dryrun.confirm import (  # ImportError until T12 — expected
    SessionExpiredError,
    confirm,
)
from ingestion.dryrun.session import DryRunSession
from ingestion.parsers.base import ParsedStatement, ParsedTransaction
from ingestion.validators.balance_check import BalanceCheckResult

_TEST_USER_ID = uuid.UUID("12345678-1234-5678-1234-567812345678")
_TEST_KEY_ID = uuid.UUID("aaaabbbb-aaaa-bbbb-aaaa-bbbbaaaabbbb")
_FAKE_ENCRYPTED = b"fake_encrypted_payload_bytes"
_FAKE_CONTENT_HASH = "a" * 64  # 64-char hex


def _make_txn(
    narration: str,
    amount_paise: int,
    value_date: date,
    account_ref: str = "TEST_CC_0001",
) -> ParsedTransaction:
    canonical = canonicalize_narration(narration)
    return ParsedTransaction(
        account_ref=account_ref,
        value_date=value_date,
        amount_paise=amount_paise,
        narration=narration,
        canonical_narration=canonical,
        occurrence_index=0,
        idempotency_hash=compute_idempotency_hash(
            account_ref, value_date, amount_paise, canonical, 0
        ),
        running_balance_paise=None,
    )


def _make_statement(transactions: list[ParsedTransaction]) -> ParsedStatement:
    total = sum(t.amount_paise for t in transactions)
    return ParsedStatement(
        bank="test_cc",
        account_ref="TEST_CC_0001",
        period_start=date(2026, 1, 1),
        period_end=date(2026, 1, 31),
        opening_balance_paise=0,
        closing_balance_paise=total,  # balance passes
        transactions=transactions,
        confidence=9000,
        raw_text="test statement text",
    )


def _make_session(
    balance_check: BalanceCheckResult = BalanceCheckResult.PASS,
    transactions: list[ParsedTransaction] | None = None,
) -> DryRunSession:
    if transactions is None:
        transactions = [
            _make_txn("GROCERY STORE", -10000, date(2026, 1, 5)),
            _make_txn("FUEL PUMP", -5000, date(2026, 1, 10)),
        ]
    return DryRunSession(
        session_id=str(uuid.uuid4()),
        user_id=_TEST_USER_ID,
        account_ref="TEST_CC_0001",
        statement=_make_statement(transactions),
        balance_check=balance_check,
        raw_artifact_content_hash=_FAKE_CONTENT_HASH,
        created_at=datetime.now(UTC),
    )


def _mock_redis_with_session(session: DryRunSession) -> MagicMock:
    """Return a mock Redis client that returns the given session when .get() is called."""
    mock = MagicMock()
    mock.get.return_value = pickle.dumps(session)
    return mock


def _mock_redis_expired() -> MagicMock:
    """Return a mock Redis client that simulates an expired key."""
    mock = MagicMock()
    mock.get.return_value = None
    return mock


# ── session not found ─────────────────────────────────────────────────────────


def test_confirm_expired_session_raises_session_expired_error() -> None:
    """Session not in Redis → SessionExpiredError raised, no DB writes."""
    mock_db = MagicMock(spec=Session)
    mock_redis = _mock_redis_expired()
    with patch("ingestion.dryrun.confirm.get_redis_client", return_value=mock_redis):
        with pytest.raises(SessionExpiredError):
            confirm("no-such-id", mock_db)
    mock_db.add.assert_not_called()


def test_confirm_expired_session_writes_nothing() -> None:
    """SessionExpiredError path writes zero rows to DB."""
    mock_db = MagicMock(spec=Session)
    with patch("ingestion.dryrun.confirm.get_redis_client", return_value=_mock_redis_expired()):
        with pytest.raises(SessionExpiredError):
            confirm("no-such-id", mock_db)
    mock_db.add.assert_not_called()
    mock_db.flush.assert_not_called()


# ── balance PASS ──────────────────────────────────────────────────────────────


def test_confirm_pass_writes_ingestion_event() -> None:
    """PASS balance → db.add called at least once with an IngestionEvent."""
    from core.events.models import IngestionEvent

    session = _make_session(BalanceCheckResult.PASS)
    mock_db = MagicMock(spec=Session)
    mock_redis = _mock_redis_with_session(session)
    with (
        patch("ingestion.dryrun.confirm.get_redis_client", return_value=mock_redis),
        patch(
            "ingestion.dryrun.confirm.encrypt_payload",
            return_value=(_FAKE_ENCRYPTED, _TEST_KEY_ID),
        ),
        patch("ingestion.dryrun.confirm.append_event"),
    ):
        confirm(session.session_id, mock_db)
    added_types = [type(c.args[0]) for c in mock_db.add.call_args_list]
    assert IngestionEvent in added_types


def test_confirm_pass_writes_raw_artifact() -> None:
    """PASS balance → db.add called with a RawArtifact."""
    from core.events.models import RawArtifact

    session = _make_session(BalanceCheckResult.PASS)
    mock_db = MagicMock(spec=Session)
    mock_redis = _mock_redis_with_session(session)
    with (
        patch("ingestion.dryrun.confirm.get_redis_client", return_value=mock_redis),
        patch(
            "ingestion.dryrun.confirm.encrypt_payload",
            return_value=(_FAKE_ENCRYPTED, _TEST_KEY_ID),
        ),
        patch("ingestion.dryrun.confirm.append_event"),
    ):
        confirm(session.session_id, mock_db)
    added_types = [type(c.args[0]) for c in mock_db.add.call_args_list]
    assert RawArtifact in added_types


def test_confirm_pass_ingestion_event_status_ingested() -> None:
    """PASS balance → IngestionEvent.status == 'ingested'."""
    from core.events.models import IngestionEvent

    session = _make_session(BalanceCheckResult.PASS)
    mock_db = MagicMock(spec=Session)
    with (
        patch(
            "ingestion.dryrun.confirm.get_redis_client",
            return_value=_mock_redis_with_session(session),
        ),
        patch(
            "ingestion.dryrun.confirm.encrypt_payload",
            return_value=(_FAKE_ENCRYPTED, _TEST_KEY_ID),
        ),
        patch("ingestion.dryrun.confirm.append_event"),
    ):
        confirm(session.session_id, mock_db)
    ie = next(
        c.args[0] for c in mock_db.add.call_args_list if isinstance(c.args[0], IngestionEvent)
    )
    assert ie.status == "ingested"


def test_confirm_pass_ingestion_event_user_id() -> None:
    """PASS → IngestionEvent.user_id matches session.user_id."""
    from core.events.models import IngestionEvent

    session = _make_session(BalanceCheckResult.PASS)
    mock_db = MagicMock(spec=Session)
    with (
        patch(
            "ingestion.dryrun.confirm.get_redis_client",
            return_value=_mock_redis_with_session(session),
        ),
        patch(
            "ingestion.dryrun.confirm.encrypt_payload",
            return_value=(_FAKE_ENCRYPTED, _TEST_KEY_ID),
        ),
        patch("ingestion.dryrun.confirm.append_event"),
    ):
        confirm(session.session_id, mock_db)
    ie = next(
        c.args[0] for c in mock_db.add.call_args_list if isinstance(c.args[0], IngestionEvent)
    )
    assert ie.user_id == _TEST_USER_ID


def test_confirm_pass_ingestion_event_records_added() -> None:
    """PASS → records_added == len(transactions)."""
    from core.events.models import IngestionEvent

    txns = [
        _make_txn("TXN A", -5000, date(2026, 1, 5)),
        _make_txn("TXN B", -3000, date(2026, 1, 6)),
        _make_txn("TXN C", -2000, date(2026, 1, 7)),
    ]
    session = _make_session(BalanceCheckResult.PASS, txns)
    mock_db = MagicMock(spec=Session)
    with (
        patch(
            "ingestion.dryrun.confirm.get_redis_client",
            return_value=_mock_redis_with_session(session),
        ),
        patch(
            "ingestion.dryrun.confirm.encrypt_payload",
            return_value=(_FAKE_ENCRYPTED, _TEST_KEY_ID),
        ),
        patch("ingestion.dryrun.confirm.append_event"),
    ):
        confirm(session.session_id, mock_db)
    ie = next(
        c.args[0] for c in mock_db.add.call_args_list if isinstance(c.args[0], IngestionEvent)
    )
    assert ie.records_added == 3


def test_confirm_pass_calls_append_event_n_times() -> None:
    """PASS → append_event called once per transaction."""
    txns = [
        _make_txn("TXN A", -5000, date(2026, 1, 5)),
        _make_txn("TXN B", -3000, date(2026, 1, 6)),
    ]
    session = _make_session(BalanceCheckResult.PASS, txns)
    mock_db = MagicMock(spec=Session)
    with (
        patch(
            "ingestion.dryrun.confirm.get_redis_client",
            return_value=_mock_redis_with_session(session),
        ),
        patch(
            "ingestion.dryrun.confirm.encrypt_payload",
            return_value=(_FAKE_ENCRYPTED, _TEST_KEY_ID),
        ),
        patch("ingestion.dryrun.confirm.append_event") as mock_append,
    ):
        confirm(session.session_id, mock_db)
    assert mock_append.call_count == 2


def test_confirm_pass_raw_artifact_not_retained() -> None:
    """PASS → RawArtifact.retained == False."""
    from core.events.models import RawArtifact

    session = _make_session(BalanceCheckResult.PASS)
    mock_db = MagicMock(spec=Session)
    with (
        patch(
            "ingestion.dryrun.confirm.get_redis_client",
            return_value=_mock_redis_with_session(session),
        ),
        patch(
            "ingestion.dryrun.confirm.encrypt_payload",
            return_value=(_FAKE_ENCRYPTED, _TEST_KEY_ID),
        ),
        patch("ingestion.dryrun.confirm.append_event"),
    ):
        confirm(session.session_id, mock_db)
    ra = next(c.args[0] for c in mock_db.add.call_args_list if isinstance(c.args[0], RawArtifact))
    assert ra.retained is False


def test_confirm_pass_raw_artifact_content_hash() -> None:
    """PASS → RawArtifact.content_hash == session.raw_artifact_content_hash."""
    from core.events.models import RawArtifact

    session = _make_session(BalanceCheckResult.PASS)
    mock_db = MagicMock(spec=Session)
    with (
        patch(
            "ingestion.dryrun.confirm.get_redis_client",
            return_value=_mock_redis_with_session(session),
        ),
        patch(
            "ingestion.dryrun.confirm.encrypt_payload",
            return_value=(_FAKE_ENCRYPTED, _TEST_KEY_ID),
        ),
        patch("ingestion.dryrun.confirm.append_event"),
    ):
        confirm(session.session_id, mock_db)
    ra = next(c.args[0] for c in mock_db.add.call_args_list if isinstance(c.args[0], RawArtifact))
    assert ra.content_hash == _FAKE_CONTENT_HASH


def test_confirm_pass_deletes_redis_session() -> None:
    """PASS → Redis session deleted after DB writes."""
    session = _make_session(BalanceCheckResult.PASS)
    mock_redis = _mock_redis_with_session(session)
    mock_db = MagicMock(spec=Session)
    with (
        patch("ingestion.dryrun.confirm.get_redis_client", return_value=mock_redis),
        patch(
            "ingestion.dryrun.confirm.encrypt_payload",
            return_value=(_FAKE_ENCRYPTED, _TEST_KEY_ID),
        ),
        patch("ingestion.dryrun.confirm.append_event"),
    ):
        confirm(session.session_id, mock_db)
    mock_redis.delete.assert_called_once()


# ── balance FAIL ──────────────────────────────────────────────────────────────


def test_confirm_fail_writes_rejected_ingestion_event() -> None:
    """FAIL balance → IngestionEvent.status == 'rejected'."""
    from core.events.models import IngestionEvent

    session = _make_session(BalanceCheckResult.FAIL)
    mock_db = MagicMock(spec=Session)
    with (
        patch(
            "ingestion.dryrun.confirm.get_redis_client",
            return_value=_mock_redis_with_session(session),
        ),
        patch(
            "ingestion.dryrun.confirm.encrypt_payload",
            return_value=(_FAKE_ENCRYPTED, _TEST_KEY_ID),
        ),
        patch("ingestion.dryrun.confirm.append_event"),
    ):
        confirm(session.session_id, mock_db)
    ie = next(
        c.args[0] for c in mock_db.add.call_args_list if isinstance(c.args[0], IngestionEvent)
    )
    assert ie.status == "rejected"


def test_confirm_fail_raw_artifact_retained() -> None:
    """FAIL balance → RawArtifact.retained == True."""
    from core.events.models import RawArtifact

    session = _make_session(BalanceCheckResult.FAIL)
    mock_db = MagicMock(spec=Session)
    with (
        patch(
            "ingestion.dryrun.confirm.get_redis_client",
            return_value=_mock_redis_with_session(session),
        ),
        patch(
            "ingestion.dryrun.confirm.encrypt_payload",
            return_value=(_FAKE_ENCRYPTED, _TEST_KEY_ID),
        ),
        patch("ingestion.dryrun.confirm.append_event"),
    ):
        confirm(session.session_id, mock_db)
    ra = next(c.args[0] for c in mock_db.add.call_args_list if isinstance(c.args[0], RawArtifact))
    assert ra.retained is True


def test_confirm_fail_zero_transaction_events() -> None:
    """FAIL balance → append_event never called (zero TransactionEvents)."""
    session = _make_session(BalanceCheckResult.FAIL)
    mock_db = MagicMock(spec=Session)
    with (
        patch(
            "ingestion.dryrun.confirm.get_redis_client",
            return_value=_mock_redis_with_session(session),
        ),
        patch(
            "ingestion.dryrun.confirm.encrypt_payload",
            return_value=(_FAKE_ENCRYPTED, _TEST_KEY_ID),
        ),
        patch("ingestion.dryrun.confirm.append_event") as mock_append,
    ):
        confirm(session.session_id, mock_db)
    mock_append.assert_not_called()
