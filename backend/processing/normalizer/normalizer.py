"""Merchant normalizer: rules-first, LLM fallback. Implements PRD §4 Step 4, TRD §9.2."""

from __future__ import annotations

import asyncio
from typing import Any

from pydantic import BaseModel

from adapters.llm.base import BelowConfidenceThreshold, LLMAdapter
from adapters.llm.stub import StubLLMAdapter
from processing.normalizer.config import NORMALIZATION_CONFIDENCE_THRESHOLD
from processing.normalizer.events import MerchantNormalizedPayload
from processing.normalizer.rules import match_rule

# Module-level adapter — patch this in tests via set_adapter().
# Defaults to the stub so the module is usable without external configuration.
_adapter: LLMAdapter[Any] = StubLLMAdapter()


def set_adapter(adapter: LLMAdapter[Any]) -> None:
    """Replace the module-level LLM adapter. Call before invoking normalize_merchant."""
    global _adapter
    _adapter = adapter


class MerchantNameOutput(BaseModel):
    """LLM output schema for merchant name normalization."""

    canonical_name: str


def normalize_merchant(
    transaction_hash: str,
    raw_narration: str,
) -> MerchantNormalizedPayload:
    """Return a normalization decision for raw_narration.

    Tries rules first. Falls back to LLM if no rule matches.
    Result is always recorded as an event — never recomputed on replay.

    Raises:
        BelowConfidenceThreshold: If LLM result is below the configured threshold.
        RuntimeError: If no adapter is configured and LLM fallback is needed.
    """
    rule_match = match_rule(raw_narration)

    if rule_match is not None:
        canonical_name, rule_id = rule_match
        return MerchantNormalizedPayload(
            transaction_hash=transaction_hash,
            raw_narration=raw_narration,
            canonical_name=canonical_name,
            method="rule",
            confidence_bps=9500,
            rule_id=rule_id,
            prompt_version=None,
        )

    # LLM fallback
    if _adapter is None:
        raise RuntimeError("No LLM adapter configured")

    prompt = f"Normalize merchant name from bank narration: {raw_narration}"
    result = asyncio.run(_adapter.complete(prompt, MerchantNameOutput, "normalizer-v1"))

    if result.confidence_bps < NORMALIZATION_CONFIDENCE_THRESHOLD:
        raise BelowConfidenceThreshold(
            confidence_bps=result.confidence_bps,
            threshold=NORMALIZATION_CONFIDENCE_THRESHOLD,
        )

    merchant_output: MerchantNameOutput = result.output
    return MerchantNormalizedPayload(
        transaction_hash=transaction_hash,
        raw_narration=raw_narration,
        canonical_name=merchant_output.canonical_name,
        method="llm",
        confidence_bps=result.confidence_bps,
        rule_id=None,
        prompt_version="normalizer-v1",
    )
