"""Nature tagger public contract. Implements PRD §5.1, TRD §8.3."""

from __future__ import annotations

from adapters.llm.base import LLMAdapter
from adapters.llm.stub import StubLLMAdapter
from processing.classifier.categories import Category
from processing.nature.events import Nature, NatureCorrectedPayload, NatureTaggedPayload

_llm_adapter: LLMAdapter = StubLLMAdapter()


def set_adapter(adapter: LLMAdapter) -> None:
    """Replace the module-level LLM adapter."""
    global _llm_adapter
    _llm_adapter = adapter


def tag_nature(
    transaction_hash: str,
    category: Category,
    merchant_canonical: str,
    transaction_type: str,
    correction_events: list[object],
) -> NatureTaggedPayload:
    """Assign a nature tag to an expense transaction.

    DECISION — the returned payload must be recorded as a NatureTagged event
    (TRD §9.2). The caller must pass all NatureCorrected events for this user
    so learned overrides are derived from the event log, not mutable state.

    Args:
        transaction_hash: Idempotency hash of the transaction.
        category: Canonical category from the classifier (step 5 of pipeline).
        merchant_canonical: Normalized merchant name.
        transaction_type: Must be "expense". Raises ValueError for any other value.
        correction_events: All NatureCorrected events for this user, in
            chronological order. Used to derive per-user learned overrides.

    Returns:
        NatureTaggedPayload — caller records it as an event.

    Raises:
        ValueError: transaction_type is not "expense".
        BelowConfidenceThreshold: LLM confidence below NATURE_CONFIDENCE_THRESHOLD.
    """
    from processing.nature.tagger import _tag_nature

    return _tag_nature(transaction_hash, category, merchant_canonical, transaction_type, correction_events)


def record_nature_correction(
    transaction_hash: str,
    corrected_nature: Nature,
    prior_nature: Nature,
    user_id: str,
) -> NatureCorrectedPayload:
    """Record a user's manual nature correction as an event payload.

    Pure function — no side effects. The returned payload is stored by the
    caller as a NatureCorrected event.
    """
    return NatureCorrectedPayload(
        transaction_hash=transaction_hash,
        nature=corrected_nature,
        prior_nature=prior_nature,
        corrected_by=user_id,
    )


def resolve_nature(
    transaction_hash: str,
    events: list[object],
) -> Nature:
    """Derive the effective nature from the transaction's event history.

    DERIVATION — safe to recompute. The most recent NatureCorrected event wins.
    Falls back to NatureTagged. Empty list raises ValueError.
    """
    from processing.nature.tagger import _resolve_nature

    return _resolve_nature(transaction_hash, events)
