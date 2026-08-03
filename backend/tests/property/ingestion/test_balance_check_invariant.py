"""Property-based test for Invariant 2: statement balance check."""

from datetime import date

from hypothesis import given
from hypothesis import strategies as st
from ingestion.validators.balance_check import BalanceCheckResult, validate_balance

from ingestion.parsers.base import ParsedTransaction


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


@given(
    opening_paise=st.integers(min_value=0, max_value=10_000_000_00),
    amounts=st.lists(
        st.integers(min_value=-1_000_000_00, max_value=1_000_000_00).filter(lambda x: x != 0),
        min_size=0,
        max_size=20,
    ),
)
def test_balance_check_result_is_always_pass_or_fail(
    opening_paise: int, amounts: list[int]
) -> None:
    """Every statement either passes or fails the balance check — no other outcome."""
    transactions = [make_txn(a) for a in amounts]
    closing_paise = opening_paise + sum(amounts)  # construct a known-balanced statement
    result = validate_balance(opening_paise, transactions, closing_paise)
    assert result == BalanceCheckResult.PASS


@given(
    opening_paise=st.integers(min_value=0, max_value=10_000_000_00),
    amounts=st.lists(
        st.integers(min_value=-1_000_000_00, max_value=1_000_000_00).filter(lambda x: x != 0),
        min_size=1,
        max_size=20,
    ),
    skew=st.integers(min_value=1, max_value=1000),
)
def test_balance_check_fails_when_closing_is_wrong(
    opening_paise: int, amounts: list[int], skew: int
) -> None:
    """Any off-by-skew closing triggers FAIL."""
    transactions = [make_txn(a) for a in amounts]
    correct_closing = opening_paise + sum(amounts)
    wrong_closing = correct_closing + skew  # always wrong by at least 1
    result = validate_balance(opening_paise, transactions, wrong_closing)
    assert result == BalanceCheckResult.FAIL
