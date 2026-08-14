"""Tests for HDFC Savings parser — independently authored from spec (PRD §14.2).

Tests are derived from the spec and golden fixture design, NOT from the implementation.
The implementation does not exist yet (T2); these tests will fail at import until it does.
See brief: .superpowers/sdd/t1-hdfc-savings-tests-brief.md
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
from ingestion.parsers.hdfc_savings import HdfcSavingsParser  # ImportError until T2 — expected

GOLDEN_PDF = (
    Path(__file__).parent.parent.parent
    / "fixtures"
    / "golden"
    / "hdfc_savings"
    / "statement_001.pdf"
)

# Narrations as they appear in the golden fixture (statement_001.json).
# Use these to derive canonical_narration — do NOT hardcode post-canonical strings separately.
_NARRATION_SALARY = "NEFTCR SALARY COMPANY"
_NARRATION_RENT = "NEFTDR RENT PAYMENT"
_NARRATION_COFFEE = "UPI COFFEE SHOP"
_NARRATION_REFUND = "IMPS REFUND"


# ── fixture ────────────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def parsed_statement() -> ParsedStatement:
    parser = HdfcSavingsParser()
    with pdfplumber.open(GOLDEN_PDF) as pdf:
        return parser.parse(pdf)


# ── can_parse ─────────────────────────────────────────────────────────────────


def test_can_parse_returns_true_for_hdfc_savings_text() -> None:
    """Text containing 'StatementFrom' and 'WithdrawalAmt' markers → True.

    pdfplumber collapses spaces in extracted text, so these tokens have no internal spaces.
    can_parse uses case-insensitive substring match on 'statementfrom' and 'withdrawalamt'.
    """
    parser = HdfcSavingsParser()
    text = (
        "HDFC Bank - Statement of Account\n"
        "StatementFrom : 01/01/2026 To : 31/01/2026\n"
        "WithdrawalAmt. DepositAmt."
    )
    assert parser.can_parse(text) is True


def test_can_parse_returns_false_for_hdfc_cc_text() -> None:
    """Text containing HDFC CC markers but no 'WithdrawalAmt' → False.

    HDFC CC statements use 'HDFC Bank Swiggy' and lack the WithdrawalAmt column.
    """
    parser = HdfcSavingsParser()
    text = "HDFC Bank Swiggy Credit Card\nAccount: HDFC_CC_4321\nSWIGGY ORDER 180.00 Dr"
    assert parser.can_parse(text) is False


def test_can_parse_returns_false_for_empty_text() -> None:
    """Empty string → False."""
    parser = HdfcSavingsParser()
    assert parser.can_parse("") is False


# ── account_ref ───────────────────────────────────────────────────────────────


def test_parse_golden_statement_account_ref(parsed_statement: ParsedStatement) -> None:
    """Parsed account_ref must be 'HDFC_SAV_9876' (from 'Account Number :' header in PDF)."""
    assert parsed_statement.account_ref == "HDFC_SAV_9876"


# ── period ────────────────────────────────────────────────────────────────────


def test_parse_golden_statement_period(parsed_statement: ParsedStatement) -> None:
    """Period parsed from 'StatementFrom : 01/01/2026 To : 31/01/2026' (four-digit years)."""
    assert parsed_statement.period_start == date(2026, 1, 1)
    assert parsed_statement.period_end == date(2026, 1, 31)


# ── balances ──────────────────────────────────────────────────────────────────


def test_parse_golden_opening_closing_balance(parsed_statement: ParsedStatement) -> None:
    """Opening is derived (first_closing - first_deposit): 15,000,000 - 5,000,000 = 10,000,000.

    Closing is the ClosingBalance of the last transaction row: 12,900,000 paise.

    The statement has NO explicit opening balance line — the parser derives it from the first
    transaction's closing balance and amount.
    """
    assert parsed_statement.opening_balance_paise == 10000000
    assert parsed_statement.closing_balance_paise == 12900000


# ── transaction count ─────────────────────────────────────────────────────────


def test_parse_golden_transaction_count(parsed_statement: ParsedStatement) -> None:
    """Golden statement has exactly 4 transactions."""
    assert len(parsed_statement.transactions) == 4


# ── amount signs ──────────────────────────────────────────────────────────────


def test_parse_golden_amount_signs(parsed_statement: ParsedStatement) -> None:
    """Deposits → positive paise; withdrawals → negative paise.

    statement_001 transactions (in order):
      NEFTCR SALARY COMPANY — Deposit 50,000.00 → +5000000
      NEFTDR RENT PAYMENT   — Withdrawal 18,000.00 → -1800000
      UPI COFFEE SHOP       — Withdrawal 5,000.00 → -500000
      IMPS REFUND           — Deposit 2,000.00 → +200000
    """
    txns = parsed_statement.transactions
    assert txns[0].amount_paise == 5000000  # Deposit 50,000.00
    assert txns[1].amount_paise == -1800000  # Withdrawal 18,000.00
    assert txns[2].amount_paise == -500000  # Withdrawal 5,000.00
    assert txns[3].amount_paise == 200000  # Deposit 2,000.00


# ── canonical_narration ───────────────────────────────────────────────────────


def test_parse_golden_canonical_narration(parsed_statement: ParsedStatement) -> None:
    """canonical_narration == canonicalize_narration(narration) for each transaction."""
    for txn in parsed_statement.transactions:
        assert txn.canonical_narration == canonicalize_narration(txn.narration)


# ── occurrence_index ──────────────────────────────────────────────────────────


def test_parse_golden_occurrence_index_unique_transactions(
    parsed_statement: ParsedStatement,
) -> None:
    """All 4 transactions are distinct (account, date, amount, canonical_narration) tuples.

    The two Jan-15 transactions have different amounts AND different narrations, so they form
    separate groups. Every occurrence_index is therefore 0.
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
    """HDFC Savings has a ClosingBalance column on every row → running_balance_paise is NOT None.

    This is the opposite of CC parsers where running_balance_paise is always None.
    """
    for txn in parsed_statement.transactions:
        assert txn.running_balance_paise is not None


def test_parse_golden_running_balance_values(parsed_statement: ParsedStatement) -> None:
    """running_balance_paise must match the ClosingBalance column from the statement.

    Sequence (opening = 10,000,000):
      After Deposit 50,000    (Jan 05): closing = 15,000,000 paise
      After Withdrawal 18,000 (Jan 10): closing = 13,200,000 paise
      After Withdrawal 5,000  (Jan 15): closing = 12,700,000 paise
      After Deposit 2,000     (Jan 15): closing = 12,900,000 paise
    """
    txns = parsed_statement.transactions
    assert txns[0].running_balance_paise == 15000000
    assert txns[1].running_balance_paise == 13200000
    assert txns[2].running_balance_paise == 12700000
    assert txns[3].running_balance_paise == 12900000


# ── confidence ────────────────────────────────────────────────────────────────


def test_parse_golden_confidence_high(parsed_statement: ParsedStatement) -> None:
    """A successfully matched HDFC Savings layout must produce confidence >= 8000 basis points."""
    assert parsed_statement.confidence >= 8000
