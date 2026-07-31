"""Tests for the synthetic statement fixture generator."""
from __future__ import annotations

from datetime import date

import pytest

import tests.fixtures  # registers templates
from tests.fixtures.generator import generate_statement


TXN_CREDIT: dict[str, object] = {
    "narration": "Salary credit ACME Corp",
    "amount_paise": 500_000_00,
    "value_date": date(2026, 1, 1),
    "type": "income",
}
TXN_DEBIT: dict[str, object] = {
    "narration": "Swiggy food order",
    "amount_paise": -50_000,
    "value_date": date(2026, 1, 5),
    "type": "expense",
}


def test_generate_statement_returns_dict() -> None:
  stmt = generate_statement(
      bank="hdfc_savings",
      account_ref="HDFC_TEST_0001",
      period_start=date(2026, 1, 1),
      period_end=date(2026, 1, 31),
      transactions=[TXN_CREDIT, TXN_DEBIT],
      seed=42,
  )
  assert isinstance(stmt, dict)


def test_balance_check_always_passes() -> None:
  """Generator must produce passing balance check (I2)."""
  stmt = generate_statement(
      bank="hdfc_savings",
      account_ref="HDFC_TEST_0001",
      period_start=date(2026, 1, 1),
      period_end=date(2026, 1, 31),
      transactions=[TXN_CREDIT, TXN_DEBIT],
  )
  assert stmt["balance_check"] == "pass"


def test_balance_check_math() -> None:
  """opening + credits - debits == closing."""
  stmt = generate_statement(
      bank="hdfc_savings",
      account_ref="HDFC_TEST_0001",
      period_start=date(2026, 1, 1),
      period_end=date(2026, 1, 31),
      transactions=[TXN_CREDIT, TXN_DEBIT],
      seed=100,
  )
  opening = int(stmt["opening_balance_paise"])
  closing = int(stmt["closing_balance_paise"])
  credits = int(stmt["credits_total_paise"])
  debits = int(stmt["debits_total_paise"])  # positive (abs value)
  assert opening + credits - debits == closing


def test_transaction_has_idempotency_hash() -> None:
  stmt = generate_statement(
      bank="hdfc_savings",
      account_ref="HDFC_TEST_0001",
      period_start=date(2026, 1, 1),
      period_end=date(2026, 1, 31),
      transactions=[TXN_CREDIT],
  )
  txns = stmt["transactions"]
  assert isinstance(txns, list)
  assert len(txns) == 1
  txn = txns[0]
  assert isinstance(txn, dict)
  assert "idempotency_hash" in txn
  assert len(str(txn["idempotency_hash"])) == 64


def test_duplicate_transactions_get_different_occurrence_index() -> None:
  """Two identical transactions must get occurrence_index 0 and 1."""
  txns = [TXN_DEBIT, TXN_DEBIT]
  stmt = generate_statement(
      bank="hdfc_savings",
      account_ref="HDFC_TEST_0001",
      period_start=date(2026, 1, 1),
      period_end=date(2026, 1, 31),
      transactions=txns,
  )
  result_txns = stmt["transactions"]
  assert isinstance(result_txns, list)
  assert result_txns[0]["occurrence_index"] == 0
  assert result_txns[1]["occurrence_index"] == 1


def test_duplicate_transactions_get_different_hashes() -> None:
  """Two identical transactions must have different idempotency hashes (C2)."""
  txns = [TXN_DEBIT, TXN_DEBIT]
  stmt = generate_statement(
      bank="hdfc_savings",
      account_ref="HDFC_TEST_0001",
      period_start=date(2026, 1, 1),
      period_end=date(2026, 1, 31),
      transactions=txns,
  )
  result_txns = stmt["transactions"]
  assert isinstance(result_txns, list)
  h0 = str(result_txns[0]["idempotency_hash"])
  h1 = str(result_txns[1]["idempotency_hash"])
  assert h0 != h1


def test_sbi_template_works() -> None:
  stmt = generate_statement(
      bank="sbi_savings",
      account_ref="SBI_TEST_0001",
      period_start=date(2026, 1, 1),
      period_end=date(2026, 1, 31),
      transactions=[TXN_CREDIT],
  )
  assert stmt["bank"] == "sbi_savings"
  assert stmt["balance_check"] == "pass"


def test_unknown_bank_raises() -> None:
  with pytest.raises(ValueError, match="Unknown bank template"):
    generate_statement(
        bank="fake_bank",
        account_ref="TEST",
        period_start=date(2026, 1, 1),
        period_end=date(2026, 1, 31),
        transactions=[],
    )


def test_empty_transactions_balance_check() -> None:
  """Empty transaction list: closing == opening, balance check passes."""
  stmt = generate_statement(
      bank="hdfc_savings",
      account_ref="HDFC_TEST_0001",
      period_start=date(2026, 1, 1),
      period_end=date(2026, 1, 31),
      transactions=[],
      seed=99,
  )
  assert stmt["balance_check"] == "pass"
  assert stmt["opening_balance_paise"] == stmt["closing_balance_paise"]
