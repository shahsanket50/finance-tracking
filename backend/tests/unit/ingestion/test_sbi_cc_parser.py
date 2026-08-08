"""Tests for SBI CC parser — independently authored from spec (PRD §14.2)."""

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
from ingestion.parsers.sbi_cc import SbiCcParser  # ImportError until T8 — expected

GOLDEN_PDF = (
    Path(__file__).parent.parent.parent / "fixtures" / "golden" / "sbi_cc" / "statement_001.pdf"
)

# Narrations as they appear in the golden fixture (statement_001.json).
# Derive canonical_narration by calling canonicalize_narration() — never hardcode
# the post-canonical string separately.
_NARRATION_GROCERY = "GROCERY STORE BIG BAZAAR"
_NARRATION_FUEL = "FUEL PUMP HPCL"


# ── fixture ────────────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def parsed_statement() -> ParsedStatement:
    parser = SbiCcParser()
    with pdfplumber.open(GOLDEN_PDF) as pdf:
        return parser.parse(pdf)


# ── can_parse ─────────────────────────────────────────────────────────────────


def test_can_parse_returns_true_for_sbi_text() -> None:
    """Text containing 'State Bank of India' and 'Credit Card' markers → True."""
    parser = SbiCcParser()
    text = "State Bank of India Credit Card\nAccount: SBI_CC_8765"
    assert parser.can_parse(text) is True


def test_can_parse_returns_false_for_hdfc_text() -> None:
    """Text from HDFC Bank (different parser) → False."""
    parser = SbiCcParser()
    text = "HDFC Bank Swiggy Credit Card\nAccount: HDFC_CC_4321"
    assert parser.can_parse(text) is False


def test_can_parse_returns_false_for_empty_text() -> None:
    """Empty string → False."""
    parser = SbiCcParser()
    assert parser.can_parse("") is False


# ── account_ref ───────────────────────────────────────────────────────────────


def test_parse_golden_account_ref(parsed_statement: ParsedStatement) -> None:
    """Parsed account_ref must be 'SBI_CC_8765' (from Account: header in PDF)."""
    assert parsed_statement.account_ref == "SBI_CC_8765"


# ── period ────────────────────────────────────────────────────────────────────


def test_parse_golden_period(parsed_statement: ParsedStatement) -> None:
    """Period parsed from 'Statement Period: 01/02/2026 to 28/02/2026'."""
    assert parsed_statement.period_start == date(2026, 2, 1)
    assert parsed_statement.period_end == date(2026, 2, 28)


# ── balances ──────────────────────────────────────────────────────────────────


def test_parse_golden_opening_balance(parsed_statement: ParsedStatement) -> None:
    """Previous Balance: 0.00 Cr → opening_balance_paise = 0."""
    assert parsed_statement.opening_balance_paise == 0


def test_parse_golden_closing_balance(parsed_statement: ParsedStatement) -> None:
    """New Balance: 950.00 Dr → closing_balance_paise = -95000 (Dr = negative)."""
    assert parsed_statement.closing_balance_paise == -95000


# ── transaction count ─────────────────────────────────────────────────────────


def test_parse_golden_transaction_count(parsed_statement: ParsedStatement) -> None:
    """Golden statement has exactly 2 transactions."""
    assert len(parsed_statement.transactions) == 2


# ── first transaction ─────────────────────────────────────────────────────────


def test_parse_golden_first_transaction_fields(parsed_statement: ParsedStatement) -> None:
    """First transaction: 03/02/2026, GROCERY STORE BIG BAZAAR, 550.00 Dr → -55000 paise."""
    txn = parsed_statement.transactions[0]
    assert txn.value_date == date(2026, 2, 3)
    assert txn.amount_paise == -55000
    assert txn.narration == _NARRATION_GROCERY


# ── amount signs ──────────────────────────────────────────────────────────────


def test_parse_golden_amount_signs(parsed_statement: ParsedStatement) -> None:
    """Both transactions are debits ('Dr') → both must have negative paise values.

    statement_001 transactions:
      GROCERY STORE BIG BAZAAR — 550.00 Dr → -55000
      FUEL PUMP HPCL           — 400.00 Dr → -40000
    """
    txns = parsed_statement.transactions
    assert txns[0].amount_paise == -55000  # 550.00 Dr
    assert txns[1].amount_paise == -40000  # 400.00 Dr


# ── canonical_narration ───────────────────────────────────────────────────────


def test_parse_golden_canonical_narration(parsed_statement: ParsedStatement) -> None:
    """canonical_narration == canonicalize_narration(narration) for each transaction."""
    for txn in parsed_statement.transactions:
        assert txn.canonical_narration == canonicalize_narration(txn.narration)


# ── occurrence_index ──────────────────────────────────────────────────────────


def test_parse_golden_occurrence_index(parsed_statement: ParsedStatement) -> None:
    """Different narrations → separate groups → occurrence_index is 0 for both."""
    for txn in parsed_statement.transactions:
        assert txn.occurrence_index == 0


# ── idempotency_hash ──────────────────────────────────────────────────────────


def test_parse_golden_idempotency_hash(parsed_statement: ParsedStatement) -> None:
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


def test_parse_golden_running_balance_is_none(parsed_statement: ParsedStatement) -> None:
    """SBI CC statements have no per-row balance column → running_balance_paise is None for all."""
    for txn in parsed_statement.transactions:
        assert txn.running_balance_paise is None


# ── confidence ────────────────────────────────────────────────────────────────


def test_parse_golden_confidence_high(parsed_statement: ParsedStatement) -> None:
    """A successfully matched SBI CC layout must produce confidence >= 8000 basis points."""
    assert parsed_statement.confidence >= 8000
