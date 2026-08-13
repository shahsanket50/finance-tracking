"""Tests for SBI Savings parser — independently authored from spec (PRD §14.2).

Tests are derived from the spec and golden fixture design, NOT from the implementation.
The implementation does not exist yet (T4); these tests will fail at import until it does.
See brief: .superpowers/sdd/t3-sbi-savings-tests-brief.md

SBI Savings column layout (page.extract_tables()):
  Txn Date | Value Date | Description | Ref No./Cheque No. | Debit | Credit | Balance

Date format in table cells: "DD Mon\\nYYYY" (e.g. "05 Feb\\n2026")
Opening balance header:  "Balance as on DD Mon YYYY : X,XXX.XX"
Period header:           "Account Statement from DD Mon YYYY to DD Mon YYYY"
can_parse markers:       "Txn Date" and "Account Statement from"
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pdfplumber
import pytest

from core.hashing.hash import (
    canonicalize_narration,
    compute_idempotency_hash,
)
from ingestion.parsers.base import ParsedStatement, ParsedTransaction  # noqa: F401
from ingestion.parsers.sbi_savings import SbiSavingsParser  # ImportError until T4 — expected

GOLDEN_PDF = (
    Path(__file__).parent.parent.parent
    / "fixtures"
    / "golden"
    / "sbi_savings"
    / "statement_001.pdf"
)

# Narrations as they appear in the golden fixture (statement_001.json).
# Use these to derive canonical_narration — do NOT hardcode post-canonical strings separately.
_NARRATION_SALARY = "UPI CREDIT SALARY"
_NARRATION_SWIGGY = "UPI DEBIT SWIGGY"
_NARRATION_NETFLIX = "UPI DEBIT NETFLIX"


# ── fixture ────────────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def parsed_statement() -> ParsedStatement:
    parser = SbiSavingsParser()
    with pdfplumber.open(GOLDEN_PDF) as pdf:
        return parser.parse(pdf)


# ── can_parse ─────────────────────────────────────────────────────────────────


def test_can_parse_returns_true_for_sbi_savings_text() -> None:
    """Text containing 'Account Statement from' and 'Txn Date' markers → True.

    Both tokens appear in SBI Savings statements and are distinctive enough
    to act as the can_parse signal for this parser.
    """
    parser = SbiSavingsParser()
    text = (
        "State Bank of India - Savings Account Statement\n"
        "Account Number : SBI_SAV_5280\n"
        "Account Statement from 01 Feb 2026 to 28 Feb 2026\n"
        "Balance as on 01 Feb 2026 : 5,000.00\n"
        "Txn Date Value Date Description Ref No./Cheque No. Debit Credit Balance\n"
    )
    assert parser.can_parse(text) is True


def test_can_parse_returns_false_for_hdfc_savings_text() -> None:
    """Text with HDFC Savings markers ('StatementFrom', 'WithdrawalAmt') but no SBI markers → False.

    HDFC Savings uses text-extraction (not table-based) and has no 'Txn Date'
    or 'Account Statement from' header lines.
    """
    parser = SbiSavingsParser()
    text = (
        "HDFC Bank - Statement of Account\n"
        "StatementFrom : 01/01/2026 To : 31/01/2026\n"
        "WithdrawalAmt. DepositAmt. ClosingBalance\n"
    )
    assert parser.can_parse(text) is False


def test_can_parse_returns_false_for_empty_text() -> None:
    """Empty string → False."""
    parser = SbiSavingsParser()
    assert parser.can_parse("") is False


# ── account_ref ───────────────────────────────────────────────────────────────


def test_parse_golden_statement_account_ref(parsed_statement: ParsedStatement) -> None:
    """Parsed account_ref must be 'SBI_SAV_5280' (from 'Account Number :' header in PDF)."""
    assert parsed_statement.account_ref == "SBI_SAV_5280"


# ── period ────────────────────────────────────────────────────────────────────


def test_parse_golden_statement_period(parsed_statement: ParsedStatement) -> None:
    """Period parsed from 'Account Statement from 01 Feb 2026 to 28 Feb 2026'."""
    assert parsed_statement.period_start == date(2026, 2, 1)
    assert parsed_statement.period_end == date(2026, 2, 28)


# ── balances ──────────────────────────────────────────────────────────────────


def test_parse_golden_opening_closing_balance(parsed_statement: ParsedStatement) -> None:
    """Opening balance parsed from 'Balance as on ... : 5,000.00' → 500000 paise.

    Closing balance = running_balance_paise of the last transaction = 10700 * 100 = 1070000 paise.

    Balance check: 500000 + 1000000 - 350000 - 80000 = 1070000 ✓
    """
    assert parsed_statement.opening_balance_paise == 500000
    assert parsed_statement.closing_balance_paise == 1070000


# ── transaction count ─────────────────────────────────────────────────────────


def test_parse_golden_transaction_count(parsed_statement: ParsedStatement) -> None:
    """Golden statement has exactly 3 transactions."""
    assert len(parsed_statement.transactions) == 3


# ── amount signs ──────────────────────────────────────────────────────────────


def test_parse_golden_amount_signs(parsed_statement: ParsedStatement) -> None:
    """Credits → positive paise; debits → negative paise.

    statement_001 transactions (in order):
      UPI CREDIT SALARY — Credit 10,000.00 → +1000000 paise
      UPI DEBIT SWIGGY  — Debit  3,500.00  → -350000 paise
      UPI DEBIT NETFLIX — Debit  800.00    → -80000 paise
    """
    txns = parsed_statement.transactions
    assert txns[0].amount_paise == 1000000    # Credit 10,000.00
    assert txns[1].amount_paise == -350000    # Debit 3,500.00
    assert txns[2].amount_paise == -80000     # Debit 800.00


# ── canonical_narration ───────────────────────────────────────────────────────


def test_parse_golden_canonical_narration(parsed_statement: ParsedStatement) -> None:
    """canonical_narration == canonicalize_narration(narration) for each transaction."""
    for txn in parsed_statement.transactions:
        assert txn.canonical_narration == canonicalize_narration(txn.narration)


# ── occurrence_index ──────────────────────────────────────────────────────────


def test_parse_golden_occurrence_index_all_unique(
    parsed_statement: ParsedStatement,
) -> None:
    """All 3 transactions are distinct (account, date, amount, canonical_narration) tuples.

    All three have different narrations, dates, and amounts, so every occurrence_index is 0.
    """
    for txn in parsed_statement.transactions:
        assert txn.occurrence_index == 0


# ── idempotency_hash format ───────────────────────────────────────────────────


def test_parse_golden_idempotency_hash_format(parsed_statement: ParsedStatement) -> None:
    """Each idempotency_hash is a 64-character lowercase hex string (SHA-256)."""
    for txn in parsed_statement.transactions:
        assert len(txn.idempotency_hash) == 64
        assert all(c in "0123456789abcdef" for c in txn.idempotency_hash)


# ── idempotency_hash correctness ──────────────────────────────────────────────


def test_parse_golden_idempotency_hash_correctness(
    parsed_statement: ParsedStatement,
) -> None:
    """Each hash equals compute_idempotency_hash(account_ref, value_date, amount_paise,
    canonical_narration, occurrence_index) — no implementation shortcut allowed."""
    for txn in parsed_statement.transactions:
        expected = compute_idempotency_hash(
            txn.account_ref,
            txn.value_date,
            txn.amount_paise,
            txn.canonical_narration,
            txn.occurrence_index,
        )
        assert txn.idempotency_hash == expected


# ── running_balance ───────────────────────────────────────────────────────────


def test_parse_golden_running_balance_not_none(parsed_statement: ParsedStatement) -> None:
    """SBI Savings has a Balance column on every row → running_balance_paise is NOT None.

    The Balance column is populated for every transaction row in this format.
    """
    for txn in parsed_statement.transactions:
        assert txn.running_balance_paise is not None


def test_parse_golden_running_balance_values(parsed_statement: ParsedStatement) -> None:
    """running_balance_paise must match the Balance column from the statement.

    Sequence (opening = 500000):
      After Credit 10,000  (Feb 05): balance = 500000 + 1000000 = 1500000 paise
      After Debit  3,500   (Feb 12): balance = 1500000 - 350000 = 1150000 paise
      After Debit  800     (Feb 20): balance = 1150000 - 80000  = 1070000 paise
    """
    txns = parsed_statement.transactions
    assert txns[0].running_balance_paise == 1500000
    assert txns[1].running_balance_paise == 1150000
    assert txns[2].running_balance_paise == 1070000


# ── confidence ────────────────────────────────────────────────────────────────


def test_parse_golden_confidence_high(parsed_statement: ParsedStatement) -> None:
    """A successfully matched SBI Savings layout must produce confidence >= 8000 basis points."""
    assert parsed_statement.confidence >= 8000


# ── NULL ≠ 0 guard ────────────────────────────────────────────────────────────


def test_missing_opening_balance_header_raises_value_error() -> None:
    """Text that passes can_parse but has no 'Balance as on' line must raise ValueError.

    This tests the CRITICAL-2 fix: _extract_opening_balance must raise, never coerce None→0.
    A missing header line must never produce a false balance-check PASS.
    """
    from ingestion.parsers.sbi_savings import SbiSavingsParser

    parser = SbiSavingsParser()
    bad_text = (
        "Account Statement from 01 Jan 2026 to 28 Feb 2026\n"
        "Txn Date Value Date Description Ref No. Debit Credit Balance\n"
        "05 Jan 2026 05 Jan 2026 NEFT CREDIT 1000.00 1000.00\n"
        # No 'Balance as on' line here
    )
    assert parser.can_parse(bad_text), "Precondition: text must pass can_parse"
    with pytest.raises(ValueError, match="Opening balance not found"):
        parser._extract_opening_balance(bad_text)
