"""Unknown statement balances are None, never a fabricated 0 (review C2, TRD §10.3).

Sweep of all five production parsers on an empty statement whose real balance is ₹12,345:
a parser either reads the printed balance or reports None. None + no rows is accepted as
not_applicable (never pass); None + rows is rejected (FAIL).
"""

from __future__ import annotations

from datetime import date

import pytest

from ingestion.validators.balance_check import BalanceCheckResult, validate_balance
from tests.factories.real_rows import BANKS, Txn, parse_statement

REAL_BALANCE = 1_234_500
REFS = {
    "hdfc_cc": "HDFC_CC_4321",
    "sbi_cc": "SBI_CC_1234",
    "hdfc_savings": "HDFC_SAV_9876",
    "sbi_savings": "SBI_SAV_5280",
    "slice_savings": "SLICE_SAV_4439",
}
# Which layouts print a closing balance on an empty statement (the rest derive it from rows).
PRINTS_CLOSING = {"hdfc_cc", "sbi_cc", "slice_savings"}


@pytest.mark.parametrize("bank", BANKS)
def test_empty_statement_never_reports_a_fabricated_zero(bank: str) -> None:
    statement = parse_statement(
        bank, REFS[bank], date(2026, 3, 1), date(2026, 3, 31), [], REAL_BALANCE
    )
    assert statement.transactions == []
    assert statement.opening_balance_paise in (None, REAL_BALANCE)
    assert statement.closing_balance_paise in (None, REAL_BALANCE)
    if bank in PRINTS_CLOSING:
        assert statement.closing_balance_paise == REAL_BALANCE
    else:
        assert statement.closing_balance_paise is None


@pytest.mark.parametrize("bank", BANKS)
def test_empty_statement_balance_check_is_pass_or_not_applicable(bank: str) -> None:
    statement = parse_statement(
        bank, REFS[bank], date(2026, 3, 1), date(2026, 3, 31), [], REAL_BALANCE
    )
    result = validate_balance(
        statement.opening_balance_paise, statement.transactions, statement.closing_balance_paise
    )
    expected = (
        BalanceCheckResult.PASS if bank in PRINTS_CLOSING else BalanceCheckResult.NOT_APPLICABLE
    )
    assert result is expected


def test_rows_with_unknown_balance_are_rejected_not_applicable_is_never_pass() -> None:
    statement = parse_statement(
        "sbi_savings", REFS["sbi_savings"], date(2026, 3, 1), date(2026, 3, 31),
        [Txn("UPI DMART GROCERY", -40_000, date(2026, 3, 9))], REAL_BALANCE,
    )  # fmt: skip
    assert validate_balance(None, statement.transactions, None) is BalanceCheckResult.FAIL
    assert validate_balance(REAL_BALANCE, statement.transactions, None) is BalanceCheckResult.FAIL
    assert validate_balance(None, [], None) is BalanceCheckResult.NOT_APPLICABLE
