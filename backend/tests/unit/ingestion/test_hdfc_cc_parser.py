"""Tests for HDFC CC parser — independently authored from spec (PRD §14.2)."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pdfplumber
import pytest
from ingestion.parsers.hdfc_cc import HdfcCcParser  # will fail until T6 — expected

from core.hashing.hash import (
    canonicalize_narration,
    compute_idempotency_hash,
)
from ingestion.parsers.base import ParsedStatement, ParsedTransaction  # noqa: F401

GOLDEN_PDF = (
    Path(__file__).parent.parent.parent / "fixtures" / "golden" / "hdfc_cc" / "statement_001.pdf"
)

# Narrations as they appear in the golden fixture (statement_001.json).
# These are used to derive canonical_narration — do NOT hardcode post-canonical
# values separately; compute them from these raw strings.
_NARRATION_REFUND_AMAZON = "REFUND AMAZON"
_NARRATION_SWIGGY_ORDER = "SWIGGY ORDER"
_NARRATION_ZOMATO_ORDER = "ZOMATO ORDER"


# ── fixture ────────────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def parsed_statement() -> ParsedStatement:
    parser = HdfcCcParser()
    with pdfplumber.open(GOLDEN_PDF) as pdf:
        return parser.parse(pdf)


# ── can_parse ─────────────────────────────────────────────────────────────────


def test_can_parse_returns_true_for_hdfc_text() -> None:
    """Text containing HDFC Bank and Swiggy markers → True."""
    parser = HdfcCcParser()
    text = "HDFC Bank Swiggy Credit Card\nAccount: HDFC_CC_4321"
    assert parser.can_parse(text) is True


def test_can_parse_returns_false_for_sbi_text() -> None:
    """Text from a different bank (SBI) → False."""
    parser = HdfcCcParser()
    text = "State Bank of India Credit Card\nAccount: SBI_CC_1234"
    assert parser.can_parse(text) is False


def test_can_parse_returns_false_for_empty_text() -> None:
    """Empty string → False."""
    parser = HdfcCcParser()
    assert parser.can_parse("") is False


# ── account_ref ───────────────────────────────────────────────────────────────


def test_parse_golden_statement_account_ref(parsed_statement: ParsedStatement) -> None:
    """Parsed account_ref must be 'HDFC_CC_4321' (from Account: header in PDF)."""
    assert parsed_statement.account_ref == "HDFC_CC_4321"


# ── period ────────────────────────────────────────────────────────────────────


def test_parse_golden_statement_period(parsed_statement: ParsedStatement) -> None:
    """Period parsed from 'Statement Period: 01/01/2026 to 31/01/2026'."""
    assert parsed_statement.period_start == date(2026, 1, 1)
    assert parsed_statement.period_end == date(2026, 1, 31)


# ── balances ──────────────────────────────────────────────────────────────────


def test_parse_golden_statement_opening_closing_balance(
    parsed_statement: ParsedStatement,
) -> None:
    """Previous Balance: 4,200.00 Cr → 420000 paise; New Balance: 1,700.00 Cr → 170000 paise."""
    assert parsed_statement.opening_balance_paise == 420000
    assert parsed_statement.closing_balance_paise == 170000


# ── transaction count ─────────────────────────────────────────────────────────


def test_parse_golden_statement_transaction_count(parsed_statement: ParsedStatement) -> None:
    """Golden statement has exactly 3 transactions."""
    assert len(parsed_statement.transactions) == 3


# ── first transaction ─────────────────────────────────────────────────────────


def test_parse_golden_first_transaction(parsed_statement: ParsedStatement) -> None:
    """First transaction: 05/01/2026, REFUND AMAZON, 500.00 Cr → 50000 paise."""
    txn = parsed_statement.transactions[0]
    assert txn.value_date == date(2026, 1, 5)
    assert txn.amount_paise == 50000
    assert txn.narration == _NARRATION_REFUND_AMAZON


# ── amount signs ──────────────────────────────────────────────────────────────


def test_parse_golden_amount_signs(parsed_statement: ParsedStatement) -> None:
    """Credits ('Cr') → positive paise; debits ('Dr') → negative paise.

    statement_001 transactions:
      REFUND AMAZON  — 500.00 Cr  → +50000
      SWIGGY ORDER   — 180.00 Dr  → -18000
      ZOMATO ORDER   — 2,820.00 Dr → -282000
    """
    txns = parsed_statement.transactions
    assert txns[0].amount_paise == 50000  # 500.00 Cr
    assert txns[1].amount_paise == -18000  # 180.00 Dr
    assert txns[2].amount_paise == -282000  # 2,820.00 Dr


# ── canonical_narration ───────────────────────────────────────────────────────


def test_parse_golden_canonical_narration(parsed_statement: ParsedStatement) -> None:
    """canonical_narration == canonicalize_narration(narration) for each transaction."""
    for txn in parsed_statement.transactions:
        assert txn.canonical_narration == canonicalize_narration(txn.narration)


# ── occurrence_index ──────────────────────────────────────────────────────────


def test_parse_golden_occurrence_index_all_unique(parsed_statement: ParsedStatement) -> None:
    """All 3 transactions are distinct tuples → every occurrence_index is 0."""
    for txn in parsed_statement.transactions:
        assert txn.occurrence_index == 0


# ── idempotency_hash format ───────────────────────────────────────────────────


def test_parse_golden_idempotency_hash_format(parsed_statement: ParsedStatement) -> None:
    """Each idempotency_hash is a 64-character lowercase hex string (SHA-256)."""
    for txn in parsed_statement.transactions:
        assert len(txn.idempotency_hash) == 64
        assert all(c in "0123456789abcdef" for c in txn.idempotency_hash)


# ── idempotency_hash correctness ──────────────────────────────────────────────


def test_parse_golden_idempotency_hash_matches_canonical(
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


def test_parse_golden_running_balance_is_none(parsed_statement: ParsedStatement) -> None:
    """CC statements have no per-row balance column → running_balance_paise is None for all."""
    for txn in parsed_statement.transactions:
        assert txn.running_balance_paise is None


# ── confidence ────────────────────────────────────────────────────────────────


def test_parse_golden_confidence_high(parsed_statement: ParsedStatement) -> None:
    """A successfully matched HDFC CC layout must produce confidence >= 8000 basis points."""
    assert parsed_statement.confidence >= 8000


# ── raw_text ──────────────────────────────────────────────────────────────────


def test_parse_golden_raw_text_nonempty(parsed_statement: ParsedStatement) -> None:
    """raw_text must be a non-empty string containing content from the statement."""
    assert isinstance(parsed_statement.raw_text, str)
    assert len(parsed_statement.raw_text) > 0
    # The full extracted text must contain at least one known narration
    assert "SWIGGY" in parsed_statement.raw_text or "HDFC" in parsed_statement.raw_text
