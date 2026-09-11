"""Account balance derivation. Implements PRD §8.1 (CC dual model), TRD §9.2.

Balance derivation is a DERIVATION — pure arithmetic over recorded events.
Safe to recompute. Two distinct formulas, one per account class:

  Savings/current: derived_balance_paise = sum of non-excluded amount_paise
      (signed: credits positive, debits negative per CLAUDE.md §3.5)

  Credit card: outstanding_liability_paise = abs(sum of non-excluded amount_paise)
      A CC account carries a liability — the amount owed to the bank.
      Credits on the CC account (i.e. payments reducing the balance) are negative.
      Excluded transactions (CC payments from the savings side, resolver-marked)
      are already not in the non-excluded set.

The two formulas are kept separate and named explicitly so callers never
accidentally derive a liability total using the savings formula or vice versa.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class BalanceSummary:
    """Result of a balance derivation for one account.

    For savings/current accounts: derived_balance_paise is the net asset
    (positive = you have money, negative = overdrawn).

    For credit card accounts: outstanding_liability_paise is the amount owed
    (always >= 0; positive = you owe money).
    """

    account_ref: str
    account_type: str  # "savings" | "current" | "credit_card" | "investment"
    # Exactly one of the two fields below is populated; the other is None.
    # This prevents callers from accidentally using a savings balance as a CC liability.
    derived_balance_paise: int | None
    outstanding_liability_paise: int | None


def derive_savings_balance(
    account_ref: str,
    account_type: str,
    non_excluded_amounts_paise: list[int],
) -> BalanceSummary:
    """DERIVATION: net asset balance for savings / current accounts.

    Args:
        account_ref: Account identifier string.
        account_type: Must be "savings" or "current". Raises ValueError otherwise.
        non_excluded_amounts_paise: Signed integer paise amounts for all
            non-excluded transactions for this account. Credits positive,
            debits negative. No floats.

    Returns:
        BalanceSummary with derived_balance_paise set, outstanding_liability_paise None.

    Raises:
        ValueError: account_type is not "savings" or "current".
        TypeError: any element of non_excluded_amounts_paise is not int.
    """
    if account_type not in ("savings", "current"):
        raise ValueError(
            f"derive_savings_balance only applies to savings/current accounts, "
            f"got account_type={account_type!r}. "
            f"For credit cards use derive_cc_outstanding_liability()."
        )
    for amt in non_excluded_amounts_paise:
        if not isinstance(amt, int):
            raise TypeError(
                f"amount_paise must be int (paise), got {type(amt).__name__} — "
                "floats are never permitted (CLAUDE.md §3.5)"
            )
    balance = sum(non_excluded_amounts_paise)
    return BalanceSummary(
        account_ref=account_ref,
        account_type=account_type,
        derived_balance_paise=balance,
        outstanding_liability_paise=None,
    )


def derive_cc_outstanding_liability(
    account_ref: str,
    non_excluded_amounts_paise: list[int],
) -> BalanceSummary:
    """DERIVATION: outstanding liability for a credit card account (PRD §8.1).

    A credit card account's balance is a liability — the amount owed to the bank.
    On a CC statement, spend transactions are debits (positive amounts in our
    signed-integer model: money leaving the account owner's perspective is positive
    spend). Payments received by the bank reduce the liability (negative amounts).

    outstanding_liability = abs(sum(non_excluded_amounts_paise))
    when the sign convention is: CC spend = positive, CC payment = negative.

    If your sum is already negative (payments exceeded spend in the period — rare,
    possible with cashback/refunds), the liability is zero, not negative.

    Args:
        account_ref: Account identifier string.
        non_excluded_amounts_paise: Signed paise amounts for all non-excluded
            CC account transactions. No floats.

    Returns:
        BalanceSummary with outstanding_liability_paise >= 0, derived_balance_paise None.

    Raises:
        TypeError: any element of non_excluded_amounts_paise is not int.
    """
    for amt in non_excluded_amounts_paise:
        if not isinstance(amt, int):
            raise TypeError(
                f"amount_paise must be int (paise), got {type(amt).__name__} — "
                "floats are never permitted (CLAUDE.md §3.5)"
            )
    net = sum(non_excluded_amounts_paise)
    # Liability cannot be negative (credit/refund surplus → 0, not a credit balance)
    outstanding = max(0, net)
    return BalanceSummary(
        account_ref=account_ref,
        account_type="credit_card",
        derived_balance_paise=None,
        outstanding_liability_paise=outstanding,
    )
