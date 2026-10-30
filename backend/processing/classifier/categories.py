"""Fixed category taxonomy for V1. Categories are configuration, not code."""

from __future__ import annotations

from typing import Literal

Category = Literal[
    "food_dining",
    "groceries",
    "transport",
    "shopping",
    "entertainment",
    "utilities",
    "rent_housing",
    "health_medical",
    "education",
    "travel",
    "investments",
    "transfers",
    "insurance",
    "subscriptions",
    "income",
    "other",
]

ALL_CATEGORIES: tuple[str, ...] = (
    "food_dining",
    "groceries",
    "transport",
    "shopping",
    "entertainment",
    "utilities",
    "rent_housing",
    "health_medical",
    "education",
    "travel",
    "investments",
    "transfers",
    "insurance",
    "subscriptions",
    "income",
    "other",
)

# Categories that hold spend. Income, transfers and investments are flows, not spend: a
# credit in an expense category is a refund (negative expense), anywhere else it is not
# spend at all. Single source for budget validation and expense totals (PRD §4.3, §12A).
NON_EXPENSE_CATEGORIES: frozenset[str] = frozenset({"income", "transfers", "investments"})
EXPENSE_CATEGORIES: tuple[str, ...] = tuple(
    c for c in ALL_CATEGORIES if c not in NON_EXPENSE_CATEGORIES
)
