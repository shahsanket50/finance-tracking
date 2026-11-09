"""Nature tagging rule engine. Implements PRD §5.1."""

from __future__ import annotations

from processing.classifier.categories import Category
from processing.nature.events import Nature

# (category, nature, rule_id)
# PRD §5.1: rules-based for obvious cases.
_RULES: list[tuple[str, Nature, str]] = [
    # Essential-fixed: predictable monthly amounts
    ("rent_housing", "essential_fixed", "nature:rent_housing"),
    ("insurance", "essential_fixed", "nature:insurance"),
    # Essential-variable: expected monthly, amount varies
    ("groceries", "essential_variable", "nature:groceries"),
    ("utilities", "essential_variable", "nature:utilities"),
    ("health_medical", "essential_variable", "nature:health_medical"),
    ("education", "essential_variable", "nature:education"),
    # Discretionary: optional wants
    ("food_dining", "discretionary", "nature:food_dining"),
    ("entertainment", "discretionary", "nature:entertainment"),
    ("shopping", "discretionary", "nature:shopping"),
    ("transport", "discretionary", "nature:transport"),
    ("subscriptions", "discretionary", "nature:subscriptions"),
    # Luxury: aspirational
    ("travel", "luxury", "nature:travel"),
]

_RULE_MAP: dict[str, tuple[Nature, str]] = {cat: (nat, rid) for cat, nat, rid in _RULES}


def match_nature_rule(category: Category) -> tuple[Nature, str] | None:
    """Return (nature, rule_id) for a known category, or None to fall through to LLM."""
    return _RULE_MAP.get(category)
