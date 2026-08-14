"""Integration tests: password-protected PDF handling (requires Docker for Postgres + Redis)."""

from __future__ import annotations

import io
from pathlib import Path
from unittest.mock import MagicMock, patch

import pikepdf
import pytest
from sqlalchemy.orm import Session

from ingestion.dryrun.harness import dry_run
from ingestion.dryrun.session import DryRunSession
from ingestion.fetchers.pdf_reader import PasswordIncorrectError, PasswordRequiredError, open_pdf
from ingestion.validators.balance_check import BalanceCheckResult

HDFC_GOLDEN_PDF = (
    Path(__file__).parent.parent / "fixtures" / "golden" / "hdfc_cc" / "statement_001.pdf"
)
CORRECT_PASSWORD = "testpass123"


@pytest.fixture(scope="session")
def encrypted_pdf_bytes() -> bytes:
    """Encrypt the HDFC CC golden PDF with AES-128 using pikepdf.

    Session-scoped — expensive operation done once per test session.
    """
    raw = HDFC_GOLDEN_PDF.read_bytes()
    with pikepdf.open(io.BytesIO(raw)) as pdf:
        buf = io.BytesIO()
        pdf.save(
            buf,
            encryption=pikepdf.Encryption(
                user=CORRECT_PASSWORD,
                owner=CORRECT_PASSWORD,
                R=4,  # AES-128
            ),
        )
        return buf.getvalue()


@pytest.mark.integration
def test_correct_password_parses_normally(
    pg_session: Session,
    test_user: object,
    encrypted_pdf_bytes: bytes,
) -> None:
    """Correct password → dry_run returns DryRunSession with balance PASS.

    The encrypted PDF is the HDFC CC golden fixture. With the right password it
    should parse identically to the unencrypted version.
    """
    from core.events.models import User

    assert isinstance(test_user, User)
    mock_redis = MagicMock()

    with patch("ingestion.dryrun.harness.get_redis_client", return_value=mock_redis):
        result = dry_run(
            encrypted_pdf_bytes,
            test_user.id,
            "HDFC_CC_4321",
            password=CORRECT_PASSWORD,
        )

    assert isinstance(result, DryRunSession)
    assert result.balance_check == BalanceCheckResult.PASS
    assert len(result.statement.transactions) > 0
    # Redis was called (session saved) — proves parse completed before Redis
    mock_redis.setex.assert_called_once()


@pytest.mark.integration
def test_missing_password_raises_password_required_error(
    encrypted_pdf_bytes: bytes,
) -> None:
    """Encrypted PDF + no password → PasswordRequiredError from open_pdf.

    No pg_session or test_user needed — error fires before any DB interaction.
    """
    with pytest.raises(PasswordRequiredError):
        open_pdf(encrypted_pdf_bytes)  # no password argument


@pytest.mark.integration
def test_wrong_password_raises_password_incorrect_error(
    encrypted_pdf_bytes: bytes,
) -> None:
    """Encrypted PDF + wrong password → PasswordIncorrectError from open_pdf."""
    with pytest.raises(PasswordIncorrectError):
        open_pdf(encrypted_pdf_bytes, password="wrongpassword")
