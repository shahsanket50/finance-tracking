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
