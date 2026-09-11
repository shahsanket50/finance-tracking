"""Nature tagger implementation. Implements PRD §5.1, TRD §8.3, TRD §9.2."""

from __future__ import annotations

import asyncio

from pydantic import BaseModel

import processing.nature.base as _base_module
from adapters.llm.base import BelowConfidenceThreshold
from processing.classifier.categories import Category
from processing.nature.config import NATURE_CONFIDENCE_THRESHOLD
from processing.nature.events import (
    ALL_NATURES,
    Nature,
    NatureCorrectedPayload,
    NatureTaggedPayload,
)
from processing.nature.rules import match_nature_rule


class NatureOutput(BaseModel):
    """LLM output schema for nature classification."""

    nature: Nature


def _build_learned_nature_overrides(
    transaction_hash: str,
    correction_events: list[object],
) -> Nature | None:
    """DERIVATION — derive the most recent nature correction for this transaction.

    Returns the corrected nature if any NatureCorrectedPayload matching
    transaction_hash exists in correction_events, else None.
    Last correction in list wins.
    """
    result: Nature | None = None
    for event in correction_events:
        if isinstance(event, NatureCorrectedPayload) and event.transaction_hash == transaction_hash:
            result = event.nature
    return result


def _tag_nature(
    transaction_hash: str,
    category: Category,
    merchant_canonical: str,
    transaction_type: str,
    correction_events: list[object],
) -> NatureTaggedPayload:
    # TRD §8.3 hard guard — nature tags exist only on expense transactions.
    if transaction_type != "expense":
        raise ValueError(
            f"Nature tags only apply to expense transactions, got transaction_type={transaction_type!r}"
        )

    # 1. Per-transaction learned override from correction_events (DERIVATION).
    learned = _build_learned_nature_overrides(transaction_hash, correction_events)
    if learned is not None:
        return NatureTaggedPayload(
            transaction_hash=transaction_hash,
            nature=learned,
            method="rule",
            confidence_bps=9500,
            rule_id=f"learned:{transaction_hash}",
            prompt_version=None,
            category=category,
        )

    # 2. Global rules — category → nature.
    rule_match = match_nature_rule(category)
    if rule_match is not None:
        nature, rule_id = rule_match
        return NatureTaggedPayload(
            transaction_hash=transaction_hash,
            nature=nature,
            method="rule",
            confidence_bps=9500,
            rule_id=rule_id,
            prompt_version=None,
            category=category,
        )

    # 3. LLM fallback for unknown/ambiguous categories (e.g. "other").
    adapter = _base_module._llm_adapter
    prompt = (
        f"Classify the spending nature of this transaction into one of {ALL_NATURES}. "
        f"Category: {category}. Merchant: {merchant_canonical}."
    )
    result = asyncio.run(adapter.complete(prompt, NatureOutput, "nature-tagger-v1"))

    if result.confidence_bps < NATURE_CONFIDENCE_THRESHOLD:
        raise BelowConfidenceThreshold(
            confidence_bps=result.confidence_bps,
            threshold=NATURE_CONFIDENCE_THRESHOLD,
        )

    llm_output: NatureOutput = result.output
    return NatureTaggedPayload(
        transaction_hash=transaction_hash,
        nature=llm_output.nature,
        method="llm",
        confidence_bps=result.confidence_bps,
        rule_id=None,
        prompt_version="nature-tagger-v1",
        category=category,
    )


def _resolve_nature(
    transaction_hash: str,
    events: list[object],
) -> Nature:
    if not events:
        raise ValueError("No nature events for transaction")

    last_correction: NatureCorrectedPayload | None = None
    base_nature: Nature | None = None

    for event in events:
        if isinstance(event, NatureCorrectedPayload):
            last_correction = event
        elif isinstance(event, NatureTaggedPayload):
            base_nature = event.nature

    if last_correction is not None:
        return last_correction.nature
    if base_nature is not None:
        return base_nature
    raise ValueError("No nature events for transaction")
