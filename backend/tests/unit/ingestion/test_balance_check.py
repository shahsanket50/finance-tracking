"""Tests for balance_check validator — authored independently from spec (PRD §14.2, Invariant 2)."""

from datetime import date

from ingestion.parsers.base import ParsedTransaction
from ingestion.validators.balance_check import BalanceCheckResult, validate_balance


def make_txn(amount_paise: int) -> ParsedTransaction:
    return ParsedTransaction(
        account_ref="TEST_001",
        value_date=date(2026, 1, 1),
        amount_paise=amount_paise,
        narration="test",
        canonical_narration="TEST",
        occurrence_index=0,
        idempotency_hash="a" * 64,
        running_balance_paise=None,
    )


# ── empty statement ────────────────────────────────────────────────────────────


def test_empty_statement_same_opening_closing_is_pass() -> None:
    """No transactions: opening == closing → PASS (trivially balanced)."""
    result = validate_balance(50_000_00, [], 50_000_00)
    assert result == BalanceCheckResult.PASS


def test_empty_statement_different_opening_closing_is_fail() -> None:
    """No transactions: opening != closing → FAIL."""
    result = validate_balance(50_000_00, [], 50_001_00)
    assert result == BalanceCheckResult.FAIL


# ── single-transaction cases ───────────────────────────────────────────────────


def test_single_credit_matches_closing() -> None:
    """1 credit: opening=0, credit=100_00, closing=100_00 → PASS."""
    # opening=0, credit=+100_00 → closing must be 100_00
    result = validate_balance(0, [make_txn(100_00)], 100_00)
    assert result == BalanceCheckResult.PASS


def test_single_debit_matches_closing() -> None:
    """1 debit: opening=100_00, debit=-50_00, closing=50_00 → PASS."""
    # opening=100_00 + (-50_00) = 50_00
    result = validate_balance(100_00, [make_txn(-50_00)], 50_00)
    assert result == BalanceCheckResult.PASS


# ── multi-transaction cases ────────────────────────────────────────────────────


def test_mixed_credits_and_debits_pass() -> None:
    """Multiple txns: opening + sum(signed amounts) == closing → PASS."""
    # opening=10_000_00
    # credits: +5_000_00, +2_000_00
    # debits:  -1_500_00, -3_000_00
    # net: 10_000_00 + 5_000_00 + 2_000_00 - 1_500_00 - 3_000_00 = 12_500_00
    transactions = [
        make_txn(5_000_00),
        make_txn(2_000_00),
        make_txn(-1_500_00),
        make_txn(-3_000_00),
    ]
    result = validate_balance(10_000_00, transactions, 12_500_00)
    assert result == BalanceCheckResult.PASS


def test_off_by_one_paise_is_fail() -> None:
    """Off by 1 paise → FAIL (any mismatch is a rejection)."""
    # correct closing: 100_00 + 50_00 = 150_00, but we pass 150_01
    result = validate_balance(100_00, [make_txn(50_00)], 150_01)
    assert result == BalanceCheckResult.FAIL


def test_credits_only_no_debits() -> None:
    """All positive amounts — only credits, no debits."""
    transactions = [make_txn(1_00), make_txn(2_00), make_txn(3_00)]
    # opening=0, sum=6_00, closing=6_00
    result = validate_balance(0, transactions, 6_00)
    assert result == BalanceCheckResult.PASS


def test_debits_only_no_credits() -> None:
    """All negative amounts — only debits, no credits."""
    transactions = [make_txn(-1_00), make_txn(-2_00), make_txn(-3_00)]
    # opening=10_00, sum=-6_00, closing=4_00
    result = validate_balance(10_00, transactions, 4_00)
    assert result == BalanceCheckResult.PASS


# ── zero-amount transaction ────────────────────────────────────────────────────


def test_zero_amount_transaction_ignored() -> None:
    """A zero-amount txn should not affect the balance (neither credit nor debit)."""
    # With a zero txn: opening=100_00 + 0 should equal closing=100_00
    result = validate_balance(100_00, [make_txn(0)], 100_00)
    assert result == BalanceCheckResult.PASS

    # Adding a zero txn to a balanced statement must not break it
    result_with_real = validate_balance(
        100_00,
        [make_txn(50_00), make_txn(0)],
        150_00,
    )
    assert result_with_real == BalanceCheckResult.PASS


# ── enum contract ──────────────────────────────────────────────────────────────


def test_result_is_enum_pass_or_fail() -> None:
    """Result is BalanceCheckResult; its .value is 'pass' or 'fail'."""
    pass_result = validate_balance(0, [], 0)
    fail_result = validate_balance(0, [], 1)

    assert isinstance(pass_result, BalanceCheckResult)
    assert isinstance(fail_result, BalanceCheckResult)
    assert pass_result.value == "pass"
    assert fail_result.value == "fail"


# ── running_balance is excluded ────────────────────────────────────────────────


def test_running_balance_not_used_in_calculation() -> None:
    """Two txns with same amount_paise but different running_balance_paise → same result.

    Invariant 2 formula: opening + credits + debits == closing
    running_balance_paise is NOT a term in that formula.
    """
    txn_no_rb = ParsedTransaction(
        account_ref="TEST_001",
        value_date=date(2026, 1, 1),
        amount_paise=100_00,
        narration="test",
        canonical_narration="TEST",
        occurrence_index=0,
        idempotency_hash="a" * 64,
        running_balance_paise=None,
    )
    txn_with_rb = ParsedTransaction(
        account_ref="TEST_001",
        value_date=date(2026, 1, 1),
        amount_paise=100_00,
        narration="test",
        canonical_narration="TEST",
        occurrence_index=0,
        idempotency_hash="b" * 64,
        running_balance_paise=999_999_99,  # wildly different — must not affect result
    )

    result_no_rb = validate_balance(0, [txn_no_rb], 100_00)
    result_with_rb = validate_balance(0, [txn_with_rb], 100_00)

    assert result_no_rb == BalanceCheckResult.PASS
    assert result_with_rb == BalanceCheckResult.PASS
    assert result_no_rb == result_with_rb


# ── large amounts / integer arithmetic ────────────────────────────────────────


def test_large_amounts_in_paise() -> None:
    """₹50 lakh credit in paise (5_000_000_00) — pure integer arithmetic, no float overflow."""
    # ₹50,00,000 = 5_000_000 rupees = 500_000_000 paise
    fifty_lakh_paise = 5_000_000_00  # 500_000_000
    result = validate_balance(0, [make_txn(fifty_lakh_paise)], fifty_lakh_paise)
    assert result == BalanceCheckResult.PASS

    # Ensure it fails correctly when closing is wrong by 1 paise
    result_fail = validate_balance(0, [make_txn(fifty_lakh_paise)], fifty_lakh_paise + 1)
    assert result_fail == BalanceCheckResult.FAIL
