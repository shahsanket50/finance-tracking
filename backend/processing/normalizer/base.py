"""Merchant normalizer contract. Implements PRD §4 (Step 4: Merchant normalization)."""

from __future__ import annotations

from processing.normalizer.events import MerchantNormalizedPayload


def normalize_merchant(
    transaction_hash: str,
    raw_narration: str,
) -> MerchantNormalizedPayload:
    """Return a normalization decision for raw_narration.

    Tries rules first. Falls back to LLM if no rule matches.
    Result is always recorded as an event — never recomputed on replay.
    Raises BelowConfidenceThreshold if LLM result is below threshold.

    Args:
        transaction_hash: The transaction's idempotency hash (TRD §9.1 C1/C2).
        raw_narration: The original narration string from the statement.

    Returns:
        MerchantNormalizedPayload recording the normalization decision,
        method (rule or LLM), confidence, and rule/prompt version.

    Raises:
        BelowConfidenceThreshold: If LLM result is below the configured threshold.
    """
    ...
