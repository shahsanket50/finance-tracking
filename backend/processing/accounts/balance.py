"""Account balance derivation. Implements PRD §8.1 (CC dual model), ADR-022; fixes B-5, B-6.

DERIVATIONS (TRD §3.4): pure arithmetic over recorded facts, safe to recompute.
Contract: processing/accounts/contract.py.

Both formulas start from the same statement-anchored signed balance:
    anchored = anchor.closing_balance_paise + Σ legs dated after anchor.period_end
Savings/current report it as the balance. Credit cards report −anchored as the outstanding
liability, unclamped (negative = credit balance). Every leg counts, resolver-paired or not:
exclusion is for flow totals only. With no anchor the value is None, never 0.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from processing.accounts.contract import BalanceLeg, StatementAnchor


@dataclass(frozen=True)
class BalanceSummary:
    """Result of a balance derivation for one account.

    Exactly one money field belongs to the account's class; the other is always None.
    The class's own field is None when there is no statement anchor (balance unknown).
    """

    account_ref: str
    account_type: str  # "savings" | "current" | "credit_card"
    derived_balance_paise: int | None  # savings/current: signed net asset
    outstanding_liability_paise: int | None  # credit_card: owed; negative = credit balance


def _require_int(value: object, what: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise TypeError(
            f"{what} must be int paise, got {type(value).__name__} — "
            "floats are never permitted (CLAUDE.md §3.5)"
        )
    return value


def _anchored_balance(
    account_ref: str, anchor: StatementAnchor | None, legs: Sequence[BalanceLeg]
) -> int | None:
    for leg in legs:
        _require_int(leg.amount_paise, f"amount_paise of {leg.idempotency_hash}")
    if anchor is None:
        return None
    if anchor.account_ref != account_ref:
        raise ValueError(f"anchor belongs to account {anchor.account_ref!r}, not {account_ref!r}")
    balance = _require_int(anchor.closing_balance_paise, "anchor closing_balance_paise")
    counted: set[str] = set()
    for leg in legs:
        if leg.value_date <= anchor.period_end or leg.idempotency_hash in counted:
            continue
        counted.add(leg.idempotency_hash)
        balance += leg.amount_paise
    return balance


def derive_anchored_savings_balance(
    account_ref: str,
    account_type: str,
    anchor: StatementAnchor | None,
    legs: Sequence[BalanceLeg],
) -> BalanceSummary:
    if account_type not in ("savings", "current"):
        raise ValueError(
            f"savings balance only applies to savings/current accounts, got "
            f"account_type={account_type!r}; use derive_cc_outstanding_liability for cards"
        )
    return BalanceSummary(
        account_ref=account_ref,
        account_type=account_type,
        derived_balance_paise=_anchored_balance(account_ref, anchor, legs),
        outstanding_liability_paise=None,
    )


def derive_anchored_cc_liability(
    account_ref: str,
    anchor: StatementAnchor | None,
    legs: Sequence[BalanceLeg],
) -> BalanceSummary:
    balance = _anchored_balance(account_ref, anchor, legs)
    return BalanceSummary(
        account_ref=account_ref,
        account_type="credit_card",
        derived_balance_paise=None,
        outstanding_liability_paise=None if balance is None else -balance,
    )
