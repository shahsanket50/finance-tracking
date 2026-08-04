"""Tests for pdf_reader — password handling and malformed input."""

from __future__ import annotations

import io
from pathlib import Path

import pdfplumber
import pytest

from ingestion.fetchers.pdf_reader import (
    PasswordIncorrectError,
    PasswordRequiredError,
    open_pdf,
)

# Golden PDFs are unencrypted — use them as "normal PDF" fixtures
HDFC_GOLDEN = Path(__file__).parent.parent.parent / "fixtures" / "golden" / "hdfc_cc" / "statement_001.pdf"
SBI_GOLDEN = Path(__file__).parent.parent.parent / "fixtures" / "golden" / "sbi_cc" / "statement_001.pdf"


def test_open_pdf_returns_pdfplumber_pdf() -> None:
    """Opens HDFC golden PDF, returns pdfplumber.PDF, has >= 1 page."""
    pdf_bytes = HDFC_GOLDEN.read_bytes()
    pdf = open_pdf(pdf_bytes)
    try:
        assert isinstance(pdf, pdfplumber.PDF)
        assert len(pdf.pages) >= 1
    finally:
        pdf.close()


def test_open_pdf_no_password_normal_pdf() -> None:
    """Opens SBI golden PDF without password, succeeds."""
    pdf_bytes = SBI_GOLDEN.read_bytes()
    pdf = open_pdf(pdf_bytes)
    try:
        assert isinstance(pdf, pdfplumber.PDF)
        assert len(pdf.pages) >= 1
    finally:
        pdf.close()


def test_open_pdf_extracts_text() -> None:
    """Opens HDFC golden PDF, extract_text() on page 0 is non-empty."""
    pdf_bytes = HDFC_GOLDEN.read_bytes()
    pdf = open_pdf(pdf_bytes)
    try:
        text = pdf.pages[0].extract_text()
        assert text is not None
        assert len(text) > 0
    finally:
        pdf.close()


def test_open_pdf_garbage_bytes_raises() -> None:
    """Passes garbage bytes → raises any exception (not PasswordRequiredError/PasswordIncorrectError)."""
    with pytest.raises(Exception) as exc_info:
        pdf = open_pdf(b"this is not a pdf")
        pdf.close()
    assert not isinstance(exc_info.value, PasswordRequiredError)
    assert not isinstance(exc_info.value, PasswordIncorrectError)


def test_open_pdf_truncated_pdf_raises() -> None:
    """Passes HDFC golden bytes truncated to first 10 bytes → raises any exception."""
    pdf_bytes = HDFC_GOLDEN.read_bytes()[:10]
    with pytest.raises(Exception) as exc_info:
        pdf = open_pdf(pdf_bytes)
        pdf.close()
    assert not isinstance(exc_info.value, PasswordRequiredError)
    assert not isinstance(exc_info.value, PasswordIncorrectError)


def test_password_required_error_is_exception() -> None:
    """PasswordRequiredError is a subclass of Exception."""
    assert issubclass(PasswordRequiredError, Exception)


def test_password_incorrect_error_is_exception() -> None:
    """PasswordIncorrectError is a subclass of Exception."""
    assert issubclass(PasswordIncorrectError, Exception)
