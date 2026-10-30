"""Property-based invariant tests for the category classifier.

Tests are derived from TRD §9.2 spec — implementation files were NOT read.
These tests assert that classifier behaviours hold across the full input space,
not just the hand-picked examples in the unit tests.
"""

from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from processing.classifier.base import classify_transaction, resolve_category
from processing.classifier.categories import ALL_CATEGORIES
from processing.classifier.events import CategoryCorrectedPayload

# ---------------------------------------------------------------------------
# Property: resolve_category is deterministic
# ---------------------------------------------------------------------------


@given(st.sampled_from(ALL_CATEGORIES))
@settings(max_examples=50)
def test_resolve_category_with_single_correction_always_returns_correction(category: str) -> None:
    """For any valid category, a single CategoryCorrectedPayload → that category returned.

    This property ensures resolve_category is a pure DERIVATION: same input events,
    same output, always. If an implementation stores mutable state between calls,
    this will catch it.
    """
    correction = CategoryCorrectedPayload(
        transaction_hash="hash_prop",
        category=category,  # type: ignore[arg-type]
        prior_category="other",
        merchant_canonical="SomeMerchant",
        corrected_by="user_prop",
    )
    result = resolve_category("hash_prop", "user_prop", [correction])
    assert result == category, (
        f"resolve_category returned '{result}' but expected '{category}' "
        "— derivation is not deterministic"
    )


@given(
    st.sampled_from(ALL_CATEGORIES),
    st.sampled_from(ALL_CATEGORIES),
)
@settings(max_examples=50)
def test_last_correction_always_wins_over_prior(first_category: str, second_category: str) -> None:
    """When two corrections exist, the second (chronologically later) one always wins,
    regardless of which categories are involved."""
    first_correction = CategoryCorrectedPayload(
        transaction_hash="hash_prop_two",
        category=first_category,  # type: ignore[arg-type]
        prior_category="other",
        merchant_canonical="SomeMerchant",
        corrected_by="user_prop",
    )
    second_correction = CategoryCorrectedPayload(
        transaction_hash="hash_prop_two",
        category=second_category,  # type: ignore[arg-type]
        prior_category=first_category,  # type: ignore[arg-type]
        merchant_canonical="SomeMerchant",
        corrected_by="user_prop",
    )
    result = resolve_category("hash_prop_two", "user_prop", [first_correction, second_correction])
    assert result == second_category, (
        f"With two corrections ({first_category!r} → {second_category!r}), "
        f"resolve_category returned '{result}' — last correction did not win"
    )


# ---------------------------------------------------------------------------
# Property: classify_transaction always returns a valid category
# ---------------------------------------------------------------------------

# Restrict to rule-matching merchants so no LLM is invoked — keeps the test
# fast and deterministic. The golden merchants from C5 are the safest anchors.
_RULE_MERCHANTS = ["Swiggy", "Zomato", "Amazon", "BigBasket", "Uber", "Ola", "Netflix"]


@given(st.sampled_from(_RULE_MERCHANTS))
@settings(max_examples=len(_RULE_MERCHANTS) * 3)
def test_classify_transaction_always_returns_valid_category(merchant: str) -> None:
    """For any rule-matching merchant, classify_transaction must return a category
    that is in ALL_CATEGORIES. An implementation that returns an ad-hoc string
    would fail this property across many merchants simultaneously."""
    result = classify_transaction("hash_prop_cat", merchant, [])
    assert result.category in ALL_CATEGORIES, (
        f"classify_transaction('{merchant}') returned category '{result.category}' "
        "which is not a member of ALL_CATEGORIES"
    )


@given(st.sampled_from(_RULE_MERCHANTS))
@settings(max_examples=len(_RULE_MERCHANTS) * 3)
def test_classify_transaction_confidence_is_valid_bps(merchant: str) -> None:
    """confidence_bps must be in [0, 10000] for any rule-matching merchant.

    This guards against implementations that return raw floats (0.0–1.0) or
    percentages (0–100) instead of basis points (0–10000).
    """
    result = classify_transaction("hash_prop_bps", merchant, [])
    assert 0 <= result.confidence_bps <= 10000, (
        f"classify_transaction('{merchant}') returned confidence_bps={result.confidence_bps} "
        "which is outside [0, 10000] — likely a scale error (float or percentage instead of bps)"
    )
