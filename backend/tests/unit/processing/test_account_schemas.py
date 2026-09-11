"""Account API schema unit tests. Derived from PRD §13 and CLAUDE.md §3.5.

Implementation files were NOT read. Tests authored from schemas.py contract only.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from processing.accounts.schemas import (
    AccountBalanceResponse,
    AccountCreate,
    AccountResponse,
    AccountUpdate,
)


# ---------------------------------------------------------------------------
# SC1 — AccountCreate schema
# ---------------------------------------------------------------------------


class TestAccountCreateSchema:
    """SC1: AccountCreate validates account_type, last4, and nickname."""

    def test_valid_input_creates_account(self) -> None:
        obj = AccountCreate(
            nickname="HDFC Savings",
            account_type="savings",
            last4="1234",
            account_ref="HDFC_SAVINGS_1234",
        )
        assert obj.nickname == "HDFC Savings"
        assert obj.account_type == "savings"
        assert obj.last4 == "1234"

    def test_last4_non_digits_raises(self) -> None:
        with pytest.raises(ValidationError):
            AccountCreate(
                nickname="HDFC Savings",
                account_type="savings",
                last4="12AB",
                account_ref="HDFC_1234",
            )

    def test_last4_too_short_raises(self) -> None:
        with pytest.raises(ValidationError):
            AccountCreate(
                nickname="HDFC Savings",
                account_type="savings",
                last4="123",
                account_ref="HDFC_1234",
            )

    def test_last4_too_long_raises(self) -> None:
        with pytest.raises(ValidationError):
            AccountCreate(
                nickname="HDFC Savings",
                account_type="savings",
                last4="12345",
                account_ref="HDFC_1234",
            )

    def test_last4_none_is_allowed(self) -> None:
        obj = AccountCreate(
            nickname="HDFC Savings",
            account_type="savings",
            last4=None,
            account_ref="HDFC_1234",
        )
        assert obj.last4 is None

    def test_empty_nickname_raises(self) -> None:
        with pytest.raises(ValidationError):
            AccountCreate(
                nickname="",
                account_type="savings",
                last4="1234",
                account_ref="HDFC_1234",
            )

    def test_account_type_savings_valid(self) -> None:
        obj = AccountCreate(
            nickname="SBI", account_type="savings", account_ref="SBI_1234"
        )
        assert obj.account_type == "savings"

    def test_account_type_current_valid(self) -> None:
        obj = AccountCreate(
            nickname="ICICI Current", account_type="current", account_ref="ICICI_5678"
        )
        assert obj.account_type == "current"

    def test_account_type_credit_card_valid(self) -> None:
        obj = AccountCreate(
            nickname="HDFC CC", account_type="credit_card", account_ref="HDFC_CC_7890"
        )
        assert obj.account_type == "credit_card"

    def test_account_type_investment_valid(self) -> None:
        obj = AccountCreate(
            nickname="Zerodha", account_type="investment", account_ref="ZERODHA_001"
        )
        assert obj.account_type == "investment"

    def test_invalid_account_type_raises(self) -> None:
        with pytest.raises(ValidationError):
            AccountCreate(
                nickname="Unknown",
                account_type="loan",  # type: ignore[arg-type]
                account_ref="LOAN_001",
            )

    def test_invalid_account_type_fd_raises(self) -> None:
        with pytest.raises(ValidationError):
            AccountCreate(
                nickname="FD",
                account_type="fixed_deposit",  # type: ignore[arg-type]
                account_ref="FD_001",
            )


# ---------------------------------------------------------------------------
# SC2 — AccountBalanceResponse schema (money as string)
# ---------------------------------------------------------------------------


class TestAccountBalanceResponseSchema:
    """SC2: AccountBalanceResponse stores money amounts as str | None, never int/float."""

    def test_savings_balance_as_string_constructs(self) -> None:
        obj = AccountBalanceResponse(
            account_ref="HDFC_1234",
            account_type="savings",
            derived_balance_paise="4215000",
            outstanding_liability_paise=None,
        )
        assert obj.derived_balance_paise == "4215000"
        assert obj.outstanding_liability_paise is None

    def test_cc_liability_as_string_constructs(self) -> None:
        obj = AccountBalanceResponse(
            account_ref="HDFC_CC_7890",
            account_type="credit_card",
            derived_balance_paise=None,
            outstanding_liability_paise="1500000",
        )
        assert obj.outstanding_liability_paise == "1500000"
        assert obj.derived_balance_paise is None

    def test_both_fields_none_is_valid(self) -> None:
        # e.g. investment account with no balance derivation yet
        obj = AccountBalanceResponse(
            account_ref="ZERODHA_001",
            account_type="investment",
            derived_balance_paise=None,
            outstanding_liability_paise=None,
        )
        assert obj.derived_balance_paise is None
        assert obj.outstanding_liability_paise is None

    def test_int_for_derived_balance_is_rejected(self) -> None:
        # CLAUDE.md §3.5: money must be string in API, not int — JSON.parse would corrupt it
        with pytest.raises((ValidationError, TypeError)):
            AccountBalanceResponse(
                account_ref="HDFC_1234",
                account_type="savings",
                derived_balance_paise=4215000,  # type: ignore[arg-type]
                outstanding_liability_paise=None,
            )

    def test_int_for_outstanding_liability_is_rejected(self) -> None:
        with pytest.raises((ValidationError, TypeError)):
            AccountBalanceResponse(
                account_ref="HDFC_CC_7890",
                account_type="credit_card",
                derived_balance_paise=None,
                outstanding_liability_paise=1500000,  # type: ignore[arg-type]
            )

    def test_float_for_derived_balance_is_rejected(self) -> None:
        with pytest.raises((ValidationError, TypeError)):
            AccountBalanceResponse(
                account_ref="HDFC_1234",
                account_type="savings",
                derived_balance_paise=42150.00,  # type: ignore[arg-type]
                outstanding_liability_paise=None,
            )

    def test_large_paise_value_as_string_preserves_precision(self) -> None:
        # A value that would lose precision as float64: 9_007_199_254_740_993
        large_paise = "9007199254740993"
        obj = AccountBalanceResponse(
            account_ref="HDFC_1234",
            account_type="savings",
            derived_balance_paise=large_paise,
            outstanding_liability_paise=None,
        )
        assert obj.derived_balance_paise == large_paise
