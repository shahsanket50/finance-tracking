"""Global rule engine for merchant-to-category mapping. Implements PRD §4 Step 5."""

from __future__ import annotations

from processing.classifier.categories import Category

# (canonical_name_upper, category, rule_id)
_RULES: list[tuple[str, Category, str]] = [
    ("SWIGGY", "food_dining", "rule:swiggy"),
    ("ZOMATO", "food_dining", "rule:zomato"),
    ("AMAZON", "shopping", "rule:amazon"),
    ("UBER", "transport", "rule:uber"),
    ("OLA", "transport", "rule:ola"),
    ("NETFLIX", "subscriptions", "rule:netflix"),
    ("BIGBASKET", "groceries", "rule:bigbasket"),
    ("NEFT CREDIT", "income", "rule:neft_credit"),
]


def match_rule(merchant_canonical: str) -> tuple[Category, str] | None:
    """Return (category, rule_id) for a known merchant, or None if no rule matches.

    Matching is case-insensitive on the canonical name.
    """
    key = merchant_canonical.upper()
    for name_upper, category, rule_id in _RULES:
        if key == name_upper:
            return category, rule_id
    return None
