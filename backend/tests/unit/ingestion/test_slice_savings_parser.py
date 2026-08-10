"""Tests for Slice Savings parser — independently authored from spec (PRD §14.2).

Tests are derived from the spec and golden fixture design, NOT from the implementation.
The implementation does not exist yet (T6); these tests will fail at import until it does.
See brief: .superpowers/sdd/t5-slice-savings-tests-brief.md

Slice Savings (Northeast Small Finance Bank, NESF) statement layout:
  Extract method: page.extract_text() — no table structure
  Columns (space-separated): DATE | DETAILS | REF NO. | AMOUNT | BALANCE
  Date format: "DD Mon 'YY" (e.g. "05 May '26") — apostrophe before 2-digit year
  Amount format: "Rs.X,XXX.XX" or "₹X,XXX.XX" — always positive; direction from DETAILS keyword
  Direction: DETAILS contains "Credit" or "Cr." → positive; "Debit" or "Dr." → negative
  Opening balance: explicit header line "Opening balance Rs.X,XXX.XX"
  Closing balance: explicit header line "Closing balance Rs.X,XXX.XX"
  Period: header line "Statement Period: DD Mon 'YY - DD Mon 'YY"
  can_parse signal: "slice small finance bank" in text.lower()
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
from ingestion.parsers.slice_savings import SliceSavingsParser  # ImportError until T6 — expected

GOLDEN_PDF = (
    Path(__file__).parent.parent.parent
    / "fixtures"
    / "golden"
    / "slice_savings"
    / "statement_001.pdf"
)

# Narrations as they appear in the golden fixture (statement_001.json).
# Use these to derive canonical_narration — do NOT hardcode post-canonical strings separately.
_NARRATION_UPI_CREDIT = "UPI-Credit-123456789-Test Merchant"
_NARRATION_UPI_DEBIT = "UPI-Debit-987654321-Coffee Shop"
_NARRATION_INTEREST = "Interest Cr. for 14-May-2026"


# ── fixture ────────────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def parsed_statement() -> ParsedStatement:
    parser = SliceSavingsParser()
    with pdfplumber.open(GOLDEN_PDF) as pdf:
        return parser.parse(pdf)


# ── can_parse ─────────────────────────────────────────────────────────────────


def test_can_parse_returns_true_for_slice_text() -> None:
    """Text containing 'slice small finance bank' (case-insensitive) → True.

    The can_parse signal is the bank name appearing verbatim in the page text.
    """
    parser = SliceSavingsParser()
    text = (
        "Slice Small Finance Bank\n"
        "Northeast Small Finance Bank (NESF)\n"
        "Account Number : SLICE_SAV_4439\n"
        "Statement Period: 01 May '26 - 31 May '26\n"
        "Opening balance Rs.1,000.00\n"
    )
    assert parser.can_parse(text) is True


def test_can_parse_returns_false_for_hdfc_savings_text() -> None:
    """Text with HDFC Savings markers but no Slice markers → False.

    HDFC Savings uses 'StatementFrom' and 'WithdrawalAmt' tokens that are
    absent from Slice statements.
    """
    parser = SliceSavingsParser()
    text = (
        "HDFC Bank - Statement of Account\n"
        "StatementFrom : 01/01/2026 To : 31/01/2026\n"
        "WithdrawalAmt. DepositAmt. ClosingBalance\n"
    )
    assert parser.can_parse(text) is False


def test_can_parse_returns_false_for_empty_text() -> None:
    """Empty string → False."""
    parser = SliceSavingsParser()
    assert parser.can_parse("") is False


# ── account_ref ───────────────────────────────────────────────────────────────


def test_parse_golden_statement_account_ref(parsed_statement: ParsedStatement) -> None:
    """Parsed account_ref must be 'SLICE_SAV_4439' (last 4 digits from 'Account Number :' header)."""
    assert parsed_statement.account_ref == "SLICE_SAV_4439"


# ── period ────────────────────────────────────────────────────────────────────


def test_parse_golden_statement_period(parsed_statement: ParsedStatement) -> None:
    """Period parsed from "Statement Period: 01 May '26 - 31 May '26".

    Date format "DD Mon 'YY": apostrophe-prefixed 2-digit year → expand to 4-digit year.
    '26 → 2026 (21st-century assumption; Slice statements are always current-year).
    """
    assert parsed_statement.period_start == date(2026, 5, 1)
    assert parsed_statement.period_end == date(2026, 5, 31)


# ── balances ──────────────────────────────────────────────────────────────────


def test_parse_golden_opening_closing_balance(parsed_statement: ParsedStatement) -> None:
    """Opening balance parsed from 'Opening balance Rs.1,000.00' → 100000 paise.

    Closing balance parsed from 'Closing balance Rs.1,488.00' → 148800 paise.

    Balance check: 100000 + 50000 - 20000 + 18800 = 148800 ✓
    """
    assert parsed_statement.opening_balance_paise == 100000
    assert parsed_statement.closing_balance_paise == 148800


# ── transaction count ─────────────────────────────────────────────────────────


def test_parse_golden_transaction_count(parsed_statement: ParsedStatement) -> None:
    """Golden statement has exactly 3 transactions."""
    assert len(parsed_statement.transactions) == 3


# ── amount signs ──────────────────────────────────────────────────────────────


def test_parse_golden_amount_signs(parsed_statement: ParsedStatement) -> None:
    """Credits → positive paise; debits → negative paise.

    Direction is determined from the DETAILS (narration) field keywords:
      "UPI-Credit-..." → contains "Credit" → positive
      "UPI-Debit-..."  → contains "Debit"  → negative
      "Interest Cr. ..." → contains "Cr." → positive

    statement_001 transactions (in order):
      UPI-Credit-123456789-Test Merchant — Credit 500.00 → +50000 paise
      UPI-Debit-987654321-Coffee Shop    — Debit  200.00 → -20000 paise
      Interest Cr. for 14-May-2026       — Credit 188.00 → +18800 paise
    """
    txns = parsed_statement.transactions
    assert txns[0].amount_paise == 50000    # Credit 500.00
    assert txns[1].amount_paise == -20000   # Debit 200.00
    assert txns[2].amount_paise == 18800    # Credit 188.00


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
    """Slice Savings has a BALANCE column on every row → running_balance_paise is NOT None.

    Every parsed transaction must carry the balance value from the BALANCE column.
    This is the opposite of CC parsers where running_balance_paise is always None.
    """
    for txn in parsed_statement.transactions:
        assert txn.running_balance_paise is not None


def test_parse_golden_running_balance_values(parsed_statement: ParsedStatement) -> None:
    """running_balance_paise must match the BALANCE column from the statement.

    Sequence (opening = 100000 paise = Rs.1,000.00):
      After Credit 500.00  (May 05): balance = 100000 + 50000 = 150000 paise
      After Debit  200.00  (May 10): balance = 150000 - 20000 = 130000 paise
      After Credit 188.00  (May 15): balance = 130000 + 18800 = 148800 paise
    """
    txns = parsed_statement.transactions
    assert txns[0].running_balance_paise == 150000
    assert txns[1].running_balance_paise == 130000
    assert txns[2].running_balance_paise == 148800


# ── confidence ────────────────────────────────────────────────────────────────


def test_parse_golden_confidence_high(parsed_statement: ParsedStatement) -> None:
    """A successfully matched Slice Savings layout must produce confidence >= 8000 basis points."""
    assert parsed_statement.confidence >= 8000
