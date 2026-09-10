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


class MerchantCategoryOutput(BaseModel):
    """LLM output schema for merchant category classification."""

    category: Category


def build_learned_rules(correction_events: list[object]) -> dict[str, Category]:
    """Derive per-merchant learned rules from a list of CategoryCorrected events.

    This is a DERIVATION — pure function over recorded facts. Safe to recompute.
    The most recent correction for each merchant wins.
    """
    rules: dict[str, Category] = {}
    for event in correction_events:
        if isinstance(event, CategoryCorrectedPayload):
            rules[event.merchant_canonical] = event.category
    return rules


def _classify_transaction(
    transaction_hash: str,
    merchant_canonical: str,
    correction_events: list[object],
) -> TransactionCategorizedPayload:
    # 1. Per-user learned rules — derived from recorded CategoryCorrected events.
    learned = build_learned_rules(correction_events)
    if merchant_canonical in learned:
        return TransactionCategorizedPayload(
            transaction_hash=transaction_hash,
            category=learned[merchant_canonical],
            method="rule",
            confidence_bps=9500,
            rule_id=f"learned:{merchant_canonical}",
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

    # 3. LLM fallback — adapter read from base module so tests can patch it.
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
    """Pure function — returns the event payload. No side effects."""
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
