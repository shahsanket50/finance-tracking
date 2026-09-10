"""Category classifier implementation. Implements PRD §4 Step 5, TRD §9.2."""

from __future__ import annotations

import asyncio

from pydantic import BaseModel

import processing.classifier.base as _base_module
from adapters.llm.base import BelowConfidenceThreshold
from processing.classifier.categories import ALL_CATEGORIES, Category
from processing.classifier.config import CATEGORIZATION_CONFIDENCE_THRESHOLD
from processing.classifier.events import CategoryCorrectedPayload, TransactionCategorizedPayload
from processing.classifier.rules import match_rule

# Per-user learned rules: {user_id: {merchant_canonical: category}}
_user_rules: dict[str, dict[str, Category]] = {}


def clear_user_rules() -> None:
    """Clear all learned per-user rules. For testing only."""
    _user_rules.clear()


class MerchantCategoryOutput(BaseModel):
    """LLM output schema for merchant category classification."""

    category: Category


def _classify_transaction(
    transaction_hash: str,
    merchant_canonical: str,
    user_id: str,
) -> TransactionCategorizedPayload:
    # 1. Per-user learned rules
    user_merchant_rules = _user_rules.get(user_id, {})
    if merchant_canonical in user_merchant_rules:
        learned_category = user_merchant_rules[merchant_canonical]
        return TransactionCategorizedPayload(
            transaction_hash=transaction_hash,
            category=learned_category,
            method="rule",
            confidence_bps=9500,
            rule_id=f"user:{user_id}:{merchant_canonical}",
            prompt_version=None,
            merchant_canonical=merchant_canonical,
        )

    # 2. Global rules
    rule_match = match_rule(merchant_canonical)
    if rule_match is not None:
        category, rule_id = rule_match
        return TransactionCategorizedPayload(
            transaction_hash=transaction_hash,
            category=category,
            method="rule",
            confidence_bps=9500,
            rule_id=rule_id,
            prompt_version=None,
            merchant_canonical=merchant_canonical,
        )

    # 3. LLM fallback — adapter is read from base module so tests can patch it
    adapter = _base_module._llm_adapter
    prompt = f"Classify merchant into one of {ALL_CATEGORIES}: {merchant_canonical}"
    result = asyncio.run(adapter.complete(prompt, MerchantCategoryOutput, "classifier-v1"))

    if result.confidence_bps < CATEGORIZATION_CONFIDENCE_THRESHOLD:
        raise BelowConfidenceThreshold(
            confidence_bps=result.confidence_bps,
            threshold=CATEGORIZATION_CONFIDENCE_THRESHOLD,
        )

    llm_output: MerchantCategoryOutput = result.output
    return TransactionCategorizedPayload(
        transaction_hash=transaction_hash,
        category=llm_output.category,
        method="llm",
        confidence_bps=result.confidence_bps,
        rule_id=None,
        prompt_version="classifier-v1",
        merchant_canonical=merchant_canonical,
    )


def _record_correction(
    transaction_hash: str,
    merchant_canonical: str,
    corrected_category: Category,
    prior_category: Category,
    user_id: str,
) -> CategoryCorrectedPayload:
    if user_id not in _user_rules:
        _user_rules[user_id] = {}
    _user_rules[user_id][merchant_canonical] = corrected_category

    return CategoryCorrectedPayload(
        transaction_hash=transaction_hash,
        category=corrected_category,
        prior_category=prior_category,
        merchant_canonical=merchant_canonical,
        corrected_by=user_id,
    )


def _resolve_category(
    transaction_hash: str,
    user_id: str,
    events: list[object],
) -> Category:
    if not events:
        raise ValueError("No classification events for transaction")

    last_correction: CategoryCorrectedPayload | None = None
    base_category: Category | None = None

    for event in events:
        if isinstance(event, CategoryCorrectedPayload):
            last_correction = event
        elif isinstance(event, TransactionCategorizedPayload):
            base_category = event.category

    if last_correction is not None:
        return last_correction.category
    if base_category is not None:
        return base_category
    raise ValueError("No classification events for transaction")
