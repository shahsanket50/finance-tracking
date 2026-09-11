"""Account balance derivation unit tests. Derived from PRD §8.1 and CLAUDE.md §3.5.

Implementation files were NOT read. Tests authored from contract (balance.py) and spec only.
"""

from __future__ import annotations

import dataclasses

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from processing.accounts.balance import (
    BalanceSummary,
    derive_cc_outstanding_liability,
    derive_savings_balance,
)


# ---------------------------------------------------------------------------
# AC1 — Savings balance derivation
# ---------------------------------------------------------------------------


class TestSavingsBalanceDerivation:
    """AC1: derive_savings_balance returns net signed asset balance for savings/current."""

    def test_positive_amounts_sum_correctly(self) -> None:
        result = derive_savings_balance("HDFC_1234", "savings", [100_00, 200_00, 50_00])
        assert result.derived_balance_paise == 350_00

    def test_negative_net_is_valid_overdrawn(self) -> None:
        result = derive_savings_balance("HDFC_1234", "savings", [-500_00, 100_00])
        assert result.derived_balance_paise == -400_00

    def test_empty_list_is_zero_not_null(self) -> None:
        result = derive_savings_balance("HDFC_1234", "savings", [])
        assert result.derived_balance_paise == 0
        assert result.derived_balance_paise is not None

    def test_single_credit(self) -> None:
        result = derive_savings_balance("SBI_5678", "savings", [42_150_00])
        assert result.derived_balance_paise == 42_150_00

    def test_mix_of_credits_and_debits(self) -> None:
        amounts = [10_000_00, -3_500_00, 5_000_00, -1_200_00]
        result = derive_savings_balance("AXIS_9012", "savings", amounts)
        assert result.derived_balance_paise == 10_300_00

    def test_result_type_is_balance_summary(self) -> None:
        result = derive_savings_balance("HDFC_1234", "savings", [100_00])
        assert isinstance(result, BalanceSummary)

    def test_derived_balance_set_outstanding_is_none(self) -> None:
        result = derive_savings_balance("HDFC_1234", "savings", [100_00])
        assert result.derived_balance_paise is not None
        assert result.outstanding_liability_paise is None

    def test_current_account_type_accepted(self) -> None:
        result = derive_savings_balance("ICICI_3456", "current", [500_00])
        assert result.derived_balance_paise == 500_00
        assert result.account_type == "current"

    def test_float_input_raises_type_error(self) -> None:
        with pytest.raises(TypeError):
            derive_savings_balance("HDFC_1234", "savings", [100.50])  # type: ignore[list-item]

    def test_float_mixed_with_ints_raises_type_error(self) -> None:
        with pytest.raises(TypeError):
            derive_savings_balance("HDFC_1234", "savings", [100_00, 200.50])  # type: ignore[list-item]


# ---------------------------------------------------------------------------
# AC2 — CC outstanding liability derivation
# ---------------------------------------------------------------------------


class TestCCOutstandingLiabilityDerivation:
    """AC2: derive_cc_outstanding_liability returns non-negative liability for credit cards."""

    def test_positive_net_equals_liability(self) -> None:
        # Spend = ₹15,000 (positive), partial payment = -₹5,000 → owe ₹10,000
        result = derive_cc_outstanding_liability("HDFC_CC_7890", [15_000_00, -5_000_00])
        assert result.outstanding_liability_paise == 10_000_00

    def test_zero_net_is_zero_not_negative(self) -> None:
        # Full payment: spend ₹10,000, payment -₹10,000 → owe ₹0
        result = derive_cc_outstanding_liability("HDFC_CC_7890", [10_000_00, -10_000_00])
        assert result.outstanding_liability_paise == 0

    def test_negative_net_floors_at_zero(self) -> None:
        # Refund exceeds spend: spend ₹5,000, refund -₹8,000 → liability is 0 not -₹3,000
        result = derive_cc_outstanding_liability("HDFC_CC_7890", [5_000_00, -8_000_00])
        assert result.outstanding_liability_paise == 0

    def test_outstanding_never_negative(self) -> None:
        result = derive_cc_outstanding_liability("HDFC_CC_7890", [-100_000_00])
        assert result.outstanding_liability_paise >= 0

    def test_result_type_is_balance_summary(self) -> None:
        result = derive_cc_outstanding_liability("HDFC_CC_7890", [5_000_00])
        assert isinstance(result, BalanceSummary)

    def test_outstanding_set_derived_balance_is_none(self) -> None:
        result = derive_cc_outstanding_liability("HDFC_CC_7890", [5_000_00])
        assert result.outstanding_liability_paise is not None
        assert result.derived_balance_paise is None

    def test_account_type_is_credit_card(self) -> None:
        result = derive_cc_outstanding_liability("HDFC_CC_7890", [5_000_00])
        assert result.account_type == "credit_card"

    def test_float_input_raises_type_error(self) -> None:
        with pytest.raises(TypeError):
            derive_cc_outstanding_liability("HDFC_CC_7890", [100.50])  # type: ignore[list-item]

    def test_empty_list_is_zero_liability(self) -> None:
        result = derive_cc_outstanding_liability("HDFC_CC_7890", [])
        assert result.outstanding_liability_paise == 0


# ---------------------------------------------------------------------------
# AC3 — Account type guard
# ---------------------------------------------------------------------------


class TestAccountTypeGuard:
    """AC3: derive_savings_balance rejects wrong account types; CC function has no type guard."""

    def test_savings_rejects_credit_card_type(self) -> None:
        with pytest.raises(ValueError, match="credit_card"):
            derive_savings_balance("HDFC_CC_7890", "credit_card", [100_00])

    def test_savings_rejects_investment_type(self) -> None:
        with pytest.raises(ValueError):
            derive_savings_balance("ZERODHA_001", "investment", [100_00])

    def test_savings_accepts_savings_type(self) -> None:
        result = derive_savings_balance("HDFC_1234", "savings", [100_00])
        assert result.account_type == "savings"

    def test_savings_accepts_current_type(self) -> None:
        result = derive_savings_balance("ICICI_3456", "current", [100_00])
        assert result.account_type == "current"

    def test_cc_function_has_no_type_guard_error(self) -> None:
        # No account_type parameter on this function — just verify it doesn't raise
        result = derive_cc_outstanding_liability("HDFC_CC_7890", [5_000_00])
        assert result.outstanding_liability_paise is not None


# ---------------------------------------------------------------------------
# AC4 — Formulas are distinct (the critical test)
# ---------------------------------------------------------------------------


class TestFormulasAreDistinct:
    """AC4: savings and CC formulas produce semantically different results from the same inputs."""

    def test_all_positive_amounts_savings_vs_cc(self) -> None:
        amounts = [10_000_00, 5_000_00, 3_000_00]
        savings = derive_savings_balance("HDFC_1234", "savings", amounts)
        cc = derive_cc_outstanding_liability("HDFC_CC_7890", amounts)

        # Both produce the same numeric sum, but in different fields
        assert savings.derived_balance_paise == 18_000_00
        assert savings.outstanding_liability_paise is None

        assert cc.outstanding_liability_paise == 18_000_00
        assert cc.derived_balance_paise is None

        # The BalanceSummary objects themselves are different (different fields populated)
        assert savings != cc

    def test_negative_net_distinguishes_formulas(self) -> None:
        # Amounts where net is negative: savings allows negative, CC floors at 0
        amounts = [-8_000_00, 3_000_00]  # net = -5_000_00

        savings = derive_savings_balance("HDFC_1234", "savings", amounts)
        cc = derive_cc_outstanding_liability("HDFC_CC_7890", amounts)

        # Savings: net asset is negative (overdrawn)
        assert savings.derived_balance_paise == -5_000_00

        # CC: liability cannot go below zero (negative net = full payoff + refund)
        assert cc.outstanding_liability_paise == 0

        # This is the key semantic distinction: same input, different result
        assert savings.derived_balance_paise != cc.outstanding_liability_paise

    def test_return_fields_are_mutually_exclusive(self) -> None:
        amounts = [1_000_00]
        savings = derive_savings_balance("HDFC_1234", "savings", amounts)
        cc = derive_cc_outstanding_liability("HDFC_CC_7890", amounts)

        assert savings.derived_balance_paise is not None
        assert savings.outstanding_liability_paise is None

        assert cc.outstanding_liability_paise is not None
        assert cc.derived_balance_paise is None


# ---------------------------------------------------------------------------
# AC5 — BalanceSummary is immutable
# ---------------------------------------------------------------------------


class TestBalanceSummaryIsImmutable:
    """AC5: BalanceSummary is a frozen dataclass — field assignment raises."""

    def test_frozen_dataclass_raises_on_assignment(self) -> None:
        summary = BalanceSummary(
            account_ref="HDFC_1234",
            account_type="savings",
            derived_balance_paise=100_00,
            outstanding_liability_paise=None,
        )
        with pytest.raises((dataclasses.FrozenInstanceError, AttributeError, TypeError)):
            summary.derived_balance_paise = 999_00  # type: ignore[misc]


# ---------------------------------------------------------------------------
# AC6 — Money never float (property test)
# ---------------------------------------------------------------------------


class TestMoneyNeverFloat:
    """AC6: balance derivation always returns int, never float, for any int input list."""

    @given(
        st.lists(
            st.integers(min_value=-1_000_000_000, max_value=1_000_000_000),
            min_size=0,
            max_size=100,
        )
    )
    @settings(max_examples=200)
    def test_savings_derived_balance_is_always_int(self, amounts: list[int]) -> None:
        result = derive_savings_balance("HDFC_1234", "savings", amounts)
        assert isinstance(result.derived_balance_paise, int), (
            f"derived_balance_paise is {type(result.derived_balance_paise).__name__}, "
            "not int — float has been introduced into savings balance derivation"
        )

    @given(
        st.lists(
            st.integers(min_value=-1_000_000_000, max_value=1_000_000_000),
            min_size=0,
            max_size=100,
        )
    )
    @settings(max_examples=200)
    def test_cc_outstanding_liability_is_always_int(self, amounts: list[int]) -> None:
        result = derive_cc_outstanding_liability("HDFC_CC_7890", amounts)
        assert isinstance(result.outstanding_liability_paise, int), (
            f"outstanding_liability_paise is {type(result.outstanding_liability_paise).__name__}, "
            "not int — float has been introduced into CC liability derivation"
        )
