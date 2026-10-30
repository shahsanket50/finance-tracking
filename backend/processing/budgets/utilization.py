"""Budget utilization derivation. Implements PRD §4.3 (B2, B3, B6), ADR-020.

DERIVATIONS (TRD §3.4): computed freely from recorded facts; never stored as events.
Contract: processing/budgets/contract.py.
"""

from __future__ import annotations

from collections.abc import Sequence, Set
from dataclasses import dataclass
from datetime import date
from typing import Any

from processing.budgets.contract import BudgetTransaction
from processing.classifier.categories import Category


@dataclass(frozen=True)
class BudgetProjection:
    """One budget row with its derived net spend for the budget's month (B6)."""

    id: Any
    user_id: Any
    category: str
    month: date
    # All money fields are int paise (CLAUDE.md §3.5)
    spent_paise: int  # signed net spend; negative = net refund (never clamped)
    limit_paise: int
    remaining_paise: int  # limit - spent; negative when over budget
    pct_used_bps: int  # status-only display value: floors at 0 for a net refund


def derive_budget_utilization(
    transactions: Sequence[BudgetTransaction],
    excluded_hashes: Set[str],
    category: Category,
    month: date,
) -> int:
    if month.day != 1:
        raise ValueError(f"month must be the first day of a month, got {month.isoformat()}")

    seen: dict[str, BudgetTransaction] = {}
    for txn in transactions:
        if not isinstance(txn.amount_paise, int) or isinstance(txn.amount_paise, bool):
            raise TypeError(
                f"amount_paise must be int paise, got {type(txn.amount_paise).__name__} "
                f"for {txn.idempotency_hash} (CLAUDE.md §3.5)"
            )
        prior = seen.get(txn.idempotency_hash)
        if prior is None:
            seen[txn.idempotency_hash] = txn
        elif prior != txn:
            raise ValueError(
                f"corrupted input: hash {txn.idempotency_hash} appears with different "
                f"fields ({prior} vs {txn})"
            )

    net_paise = 0
    for txn in seen.values():
        if txn.idempotency_hash in excluded_hashes:
            continue
        if txn.effective_category != category:
            continue
        if (txn.value_date.year, txn.value_date.month) != (month.year, month.month):
            continue
        net_paise -= txn.amount_paise
    return net_paise


def derive_budget_projection(budget: Any, spent_paise: int) -> BudgetProjection:
    """Combine a budget row with its derived net spend.

    spent_paise and remaining_paise stay signed. pct_used_bps drives the green/amber/red
    status only, so it floors at 0 for a net refund (PRD §4.3 display clamp).
    """
    limit: int = budget.target_paise
    pct_used_bps = max(0, (spent_paise * 10_000) // limit) if limit > 0 else 0
    return BudgetProjection(
        id=budget.id,
        user_id=budget.user_id,
        category=budget.category,
        month=budget.month,
        spent_paise=spent_paise,
        limit_paise=limit,
        remaining_paise=limit - spent_paise,
        pct_used_bps=pct_used_bps,
    )
