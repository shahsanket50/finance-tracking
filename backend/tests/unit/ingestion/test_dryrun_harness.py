"""Tests for dry-run harness — mocked Redis, no DB."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock, patch
from uuid import UUID

import pytest

from ingestion.dryrun.harness import dry_run
from ingestion.dryrun.session import (
    SESSION_TTL,
    DryRunSession,
    delete_session,
    load_session,
    save_session,
)
from ingestion.parsers.base import ParsedStatement
from ingestion.validators.balance_check import BalanceCheckResult

HDFC_GOLDEN_PDF = (
    Path(__file__).parent.parent.parent / "fixtures" / "golden" / "hdfc_cc" / "statement_001.pdf"
)
SBI_GOLDEN_PDF = (
    Path(__file__).parent.parent.parent / "fixtures" / "golden" / "sbi_cc" / "statement_001.pdf"
)

_TEST_USER_ID = UUID("12345678-1234-5678-1234-567812345678")


# ── Fixtures ───────────────────────────────────────────────────────────────────


@pytest.fixture
def mock_redis() -> MagicMock:
    return MagicMock()


@pytest.fixture
def hdfc_pdf_bytes() -> bytes:
    return HDFC_GOLDEN_PDF.read_bytes()


@pytest.fixture
def sbi_pdf_bytes() -> bytes:
    return SBI_GOLDEN_PDF.read_bytes()


@pytest.fixture
def minimal_session() -> DryRunSession:
    """A minimal DryRunSession for session-store unit tests (no PDF parsing needed)."""
    from datetime import date

    stmt = ParsedStatement(
        bank="hdfc_cc",
        account_ref="HDFC_CC_4321",
        period_start=date(2026, 1, 1),
        period_end=date(2026, 1, 31),
        opening_balance_paise=0,
        closing_balance_paise=0,
        transactions=[],
        confidence=9000,
        raw_text="",
    )
    return DryRunSession(
        session_id="test-session-abc",
        user_id=_TEST_USER_ID,
        account_ref="HDFC_CC_4321",
        statement=stmt,
        balance_check=BalanceCheckResult.PASS,
        raw_artifact_content_hash="a" * 64,
        created_at=datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC),
    )


# ── Session store tests ────────────────────────────────────────────────────────


def test_save_and_load_session(mock_redis: MagicMock, minimal_session: DryRunSession) -> None:
    """save_session stores with correct key + TTL; load_session round-trips correctly."""
    save_session(mock_redis, minimal_session)

    mock_redis.setex.assert_called_once()
    call_args = mock_redis.setex.call_args
    key, ttl, payload = call_args[0]

    assert key == f"dryrun:{minimal_session.session_id}"
    assert ttl == SESSION_TTL

    # Simulate load by returning the pickled payload
    mock_redis.get.return_value = payload
    loaded = load_session(mock_redis, minimal_session.session_id)
    assert loaded == minimal_session


def test_load_session_returns_none_when_expired(mock_redis: MagicMock) -> None:
    """load_session returns None when Redis returns None (TTL-evicted or not found)."""
    mock_redis.get.return_value = None
    result = load_session(mock_redis, "any-session-id")
    assert result is None


def test_delete_session_calls_client_delete(mock_redis: MagicMock) -> None:
    """delete_session calls client.delete with the correct prefixed key."""
    delete_session(mock_redis, "abc123")
    mock_redis.delete.assert_called_once_with("dryrun:abc123")


def test_session_key_prefix(mock_redis: MagicMock, minimal_session: DryRunSession) -> None:
    """save_session stores the session under a key that starts with 'dryrun:'."""
    save_session(mock_redis, minimal_session)
    key = mock_redis.setex.call_args[0][0]
    assert key.startswith("dryrun:")


# ── Harness tests (patch get_redis_client) ────────────────────────────────────


def test_dry_run_hdfc_golden_returns_session(hdfc_pdf_bytes: bytes) -> None:
    """dry_run on HDFC golden PDF returns a DryRunSession with correct account_ref and PASS."""
    mock_redis = MagicMock()
    with patch("ingestion.dryrun.harness.get_redis_client", return_value=mock_redis):
        session = dry_run(hdfc_pdf_bytes, _TEST_USER_ID, "HDFC_CC_4321")

    assert isinstance(session, DryRunSession)
    assert session.account_ref == "HDFC_CC_4321"
    assert session.balance_check == BalanceCheckResult.PASS


def test_dry_run_sbi_golden_returns_session(sbi_pdf_bytes: bytes) -> None:
    """dry_run on SBI golden PDF returns a DryRunSession with correct account_ref and PASS."""
    mock_redis = MagicMock()
    with patch("ingestion.dryrun.harness.get_redis_client", return_value=mock_redis):
        session = dry_run(sbi_pdf_bytes, _TEST_USER_ID, "SBI_CC_8765")

    assert isinstance(session, DryRunSession)
    assert session.account_ref == "SBI_CC_8765"
    assert session.balance_check == BalanceCheckResult.PASS


def test_dry_run_stores_in_redis(hdfc_pdf_bytes: bytes) -> None:
    """dry_run calls setex on the Redis client once."""
    mock_redis = MagicMock()
    with patch("ingestion.dryrun.harness.get_redis_client", return_value=mock_redis):
        dry_run(hdfc_pdf_bytes, _TEST_USER_ID, "HDFC_CC_4321")

    mock_redis.setex.assert_called_once()


def test_dry_run_sets_redis_ttl(hdfc_pdf_bytes: bytes) -> None:
    """dry_run stores the session with TTL equal to SESSION_TTL (3600s)."""
    mock_redis = MagicMock()
    with patch("ingestion.dryrun.harness.get_redis_client", return_value=mock_redis):
        dry_run(hdfc_pdf_bytes, _TEST_USER_ID, "HDFC_CC_4321")

    ttl = mock_redis.setex.call_args[0][1]
    assert ttl == SESSION_TTL


def test_dry_run_content_hash(hdfc_pdf_bytes: bytes) -> None:
    """dry_run sets raw_artifact_content_hash to SHA-256 hex of the PDF bytes."""
    mock_redis = MagicMock()
    with patch("ingestion.dryrun.harness.get_redis_client", return_value=mock_redis):
        session = dry_run(hdfc_pdf_bytes, _TEST_USER_ID, "HDFC_CC_4321")

    expected = hashlib.sha256(hdfc_pdf_bytes).hexdigest()
    assert session.raw_artifact_content_hash == expected


def test_dry_run_no_db_writes(hdfc_pdf_bytes: bytes) -> None:
    """dry_run makes no DB writes — only Redis setex is called as external I/O."""
    mock_redis = MagicMock()
    with patch("ingestion.dryrun.harness.get_redis_client", return_value=mock_redis):
        dry_run(hdfc_pdf_bytes, _TEST_USER_ID, "HDFC_CC_4321")

    # Only Redis setex was called — confirm sqlalchemy is not in the harness namespace
    import ingestion.dryrun.harness as harness_module

    assert "sqlalchemy" not in harness_module.__dict__
    mock_redis.setex.assert_called_once()


def test_dry_run_session_id_is_uuid_string(hdfc_pdf_bytes: bytes) -> None:
    """session_id is a valid UUID string (parseable by UUID())."""
    mock_redis = MagicMock()
    with patch("ingestion.dryrun.harness.get_redis_client", return_value=mock_redis):
        session = dry_run(hdfc_pdf_bytes, _TEST_USER_ID, "HDFC_CC_4321")

    # Should not raise
    UUID(session.session_id)


def test_dry_run_unknown_pdf_raises() -> None:
    """dry_run on garbage bytes raises an exception (not a DryRunSession)."""
    mock_redis = MagicMock()
    with patch("ingestion.dryrun.harness.get_redis_client", return_value=mock_redis):
        with pytest.raises(Exception, match=r"."):
            dry_run(b"not a pdf", _TEST_USER_ID, "X")


# ── G18 — harness parser registration ────────────────────────────────────────


def test_all_concrete_parsers_registered_in_default_parsers() -> None:
    """Every concrete AbstractParser subclass must appear in _DEFAULT_PARSERS (G18).

    When a new parser is added, updating _DEFAULT_PARSERS is required before merge.
    Rationale: three parsers shipped Phase 1 unregistered — this test prevents recurrence.
    """
    from ingestion.dryrun.harness import _DEFAULT_PARSERS
    from ingestion.parsers.hdfc_cc import HdfcCcParser
    from ingestion.parsers.hdfc_savings import HdfcSavingsParser
    from ingestion.parsers.sbi_cc import SbiCcParser
    from ingestion.parsers.sbi_savings import SbiSavingsParser
    from ingestion.parsers.slice_savings import SliceSavingsParser

    registered_types = {type(p) for p in _DEFAULT_PARSERS}
    required = {HdfcCcParser, SbiCcParser, HdfcSavingsParser, SbiSavingsParser, SliceSavingsParser}
    missing = required - registered_types
    assert not missing, f"Parsers not registered in _DEFAULT_PARSERS: {missing}"
