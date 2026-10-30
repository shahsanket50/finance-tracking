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
        assert result.outstanding_liability_paise is not None
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


# ---------------------------------------------------------------------------
# AC7 — Resolver-exclusion propagation into balance derivation
#
# Concrete scenario (PRD §8.1, Phase 2 resolver):
#
#   HDFC Savings account (account_ref="HDFC_1234"):
#     - txn A: ₹50,000 salary credit        (+5_000_000 paise) — counted
#     - txn B: ₹15,000 CC bill payment debit (-1_500_000 paise) — EXCLUDED via MarkedCCPayment
#     - txn C: ₹3,200 grocery debit          (  -320_000 paise) — counted
#
#   HDFC CC account (account_ref="HDFC_CC_7890"):
#     - txn D: ₹15,000 CC bill credit        (+1_500_000 paise) — EXCLUDED via MarkedCCPayment
#     (The CC statement's individual spend transactions are categorized separately)
#
#   The resolver paired (B, D) as a MarkedCCPayment event.
#   Both hashes must be excluded before the balance derivation sums amounts.
#
# Correct savings balance (exclusion-aware):
#   +5_000_000 (A) + (-320_000) (C) = +4_680_000 paise = ₹46,800
#
# Incorrect savings balance (WITHOUT exclusion filter):
#   +5_000_000 (A) + (-1_500_000) (B) + (-320_000) (C) = +3_180_000 paise = ₹31,800
#   — ₹15,000 short because the CC payment was counted as a real debit twice:
#     once here in the savings balance, and again as spend on the CC account.
# ---------------------------------------------------------------------------


class TestResolverExclusionPropagatesIntoBalance:
    """AC7: resolver-excluded hashes must be filtered BEFORE summing balance amounts.

    This is the highest-stakes correctness claim in Wave 4. If excluded transactions
    are included in the balance derivation, the savings balance shows a lower net
    (double-counted CC payments, transfers) and the CC liability shows a lower
    outstanding balance (payment credit counted as spend reduction, not excluded).
    """

    # Paise amounts — all int, no floats
    SALARY_CREDIT_PAISE = 5_000_000  # ₹50,000 credit  (txn A, counted)
    CC_PAYMENT_PAISE = -1_500_000  # ₹15,000 debit   (txn B, EXCLUDED)
    GROCERY_DEBIT_PAISE = -320_000  # ₹3,200 debit    (txn C, counted)
    CC_BILL_CREDIT_PAISE = 1_500_000  # ₹15,000 credit  (txn D, EXCLUDED — CC side of same pair)

    SAVINGS_ACCOUNT_REF = "HDFC_1234"
    CC_ACCOUNT_REF = "HDFC_CC_7890"

    HASH_A = "salary_abc123"  # txn A — counted
    HASH_B = "cc_payment_def456"  # txn B — excluded (savings debit leg)
    HASH_C = "grocery_ghi789"  # txn C — counted
    HASH_D = "cc_credit_jkl012"  # txn D — excluded (CC credit leg)

    def _non_excluded_amounts(
        self,
        all_amounts: dict[str, int],
        excluded_hashes: set[str],
    ) -> list[int]:
        """Simulate what get_account_balance does: filter before summing."""
        return [amt for h, amt in all_amounts.items() if h not in excluded_hashes]

    def test_savings_balance_with_exclusion_applied(self) -> None:
        """Correct path: CC payment debit (B) excluded → balance = ₹46,800."""
        savings_amounts = {
            self.HASH_A: self.SALARY_CREDIT_PAISE,
            self.HASH_B: self.CC_PAYMENT_PAISE,  # resolver marked this excluded
            self.HASH_C: self.GROCERY_DEBIT_PAISE,
        }
        excluded = {self.HASH_B, self.HASH_D}  # both legs from MarkedCCPayment

        non_excluded = self._non_excluded_amounts(savings_amounts, excluded)
        result = derive_savings_balance(self.SAVINGS_ACCOUNT_REF, "savings", non_excluded)

        expected_paise = self.SALARY_CREDIT_PAISE + self.GROCERY_DEBIT_PAISE  # 4_680_000
        assert result.derived_balance_paise == expected_paise, (
            f"Savings balance with exclusion applied: expected {expected_paise} paise (₹46,800), "
            f"got {result.derived_balance_paise} paise. "
            "The CC payment debit must be excluded from the savings balance — "
            "it is the settlement of CC spend already counted on the CC account."
        )

    def test_savings_balance_without_exclusion_is_wrong(self) -> None:
        """Contrast path: including excluded txn B gives the wrong, lower balance.

        This test is here to prove what the incorrect (non-exclusion-aware) result
        would be, making the correctness of the exclusion path unambiguous.
        """
        savings_amounts_including_excluded = [
            self.SALARY_CREDIT_PAISE,
            self.CC_PAYMENT_PAISE,  # ← should be excluded but isn't here
            self.GROCERY_DEBIT_PAISE,
        ]
        wrong_result = derive_savings_balance(
            self.SAVINGS_ACCOUNT_REF, "savings", savings_amounts_including_excluded
        )

        wrong_paise = (
            self.SALARY_CREDIT_PAISE + self.CC_PAYMENT_PAISE + self.GROCERY_DEBIT_PAISE
        )  # 3_180_000
        correct_paise = self.SALARY_CREDIT_PAISE + self.GROCERY_DEBIT_PAISE  # 4_680_000

        assert wrong_result.derived_balance_paise == wrong_paise, (
            "Contrast test setup error: expected the without-exclusion result to be "
            f"{wrong_paise} paise"
        )
        assert wrong_paise != correct_paise, (
            "The contrast test must produce a different number than the correct result — "
            "if they're equal, the test proves nothing."
        )
        # Document the difference explicitly
        shortfall_paise = correct_paise - wrong_paise
        assert shortfall_paise == abs(self.CC_PAYMENT_PAISE), (
            "The shortfall should equal the CC payment amount "
            f"({abs(self.CC_PAYMENT_PAISE)} paise). "
            f"Got shortfall={shortfall_paise} paise."
        )

    def test_cc_liability_with_exclusion_applied(self) -> None:
        """Correct path: CC bill credit (D) excluded → liability = spend only.

        On the CC account side, the ₹15,000 bill credit reduces the outstanding
        liability — but it is a resolver-paired leg (HASH_D) and must be excluded
        from the liability derivation for the same reason. The individual spend
        transactions on the CC account are the correct input, not the settlement credit.
        """
        cc_amounts = {
            self.HASH_D: self.CC_BILL_CREDIT_PAISE,  # excluded — settlement credit
        }
        # In this example, no individual CC spend transactions are present —
        # we're testing that the settlement credit (D) is excluded.
        excluded = {self.HASH_B, self.HASH_D}

        non_excluded = self._non_excluded_amounts(cc_amounts, excluded)
        result = derive_cc_outstanding_liability(self.CC_ACCOUNT_REF, non_excluded)

        assert result.outstanding_liability_paise == 0, (
            f"CC liability after excluding settlement credit: expected 0 paise "
            f"(no uncovered spend), got {result.outstanding_liability_paise} paise. "
            "HASH_D (the CC bill credit) must be excluded — it is the resolver-paired "
            "settlement leg, not independent spend."
        )

    def test_both_exclusion_hashes_come_from_resolver_event(self) -> None:
        """The excluded set is populated from RESOLVER_EVENT_TYPES in the event log.

        This test documents the two hashes that the resolver would have recorded
        in a MarkedCCPayment event, to make the link between resolver output and
        balance-derivation input explicit.
        """
        from processing.resolver.events import MarkedCCPaymentPayload

        # Simulate what the resolver records
        resolver_event = MarkedCCPaymentPayload(
            savings_debit_hash=self.HASH_B,
            cc_credit_hash=self.HASH_D,
            matched_by="cc_payment_matcher",
            confidence=9000,
            match_window_days=5,
        )

        # The balance derivation excludes both legs of the resolved pair
        excluded = {resolver_event.savings_debit_hash, resolver_event.cc_credit_hash}
        assert self.HASH_B in excluded
        assert self.HASH_D in excluded

        # Verify: savings balance with these hashes excluded = ₹46,800
        savings_amounts = {
            self.HASH_A: self.SALARY_CREDIT_PAISE,
            self.HASH_B: self.CC_PAYMENT_PAISE,
            self.HASH_C: self.GROCERY_DEBIT_PAISE,
        }
        non_excluded = self._non_excluded_amounts(savings_amounts, excluded)
        result = derive_savings_balance(self.SAVINGS_ACCOUNT_REF, "savings", non_excluded)

        assert result.derived_balance_paise == 4_680_000, (
            f"Expected ₹46,800 (4_680_000 paise) after excluding resolver-paired hashes, "
            f"got {result.derived_balance_paise} paise."
        )
