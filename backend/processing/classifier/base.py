"""Category classifier public contract. Implements PRD §4 Step 5."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from adapters.llm.base import LLMAdapter
from adapters.llm.stub import StubLLMAdapter
from processing.classifier.categories import Category
from processing.classifier.events import CategoryCorrectedPayload, TransactionCategorizedPayload

# Module-level LLM adapter — patch via set_adapter() or mock.patch in tests.
# Defaults to the stub so the module is usable without external configuration.
_llm_adapter: LLMAdapter[Any] = StubLLMAdapter()


def set_adapter(adapter: LLMAdapter[Any]) -> None:
    """Replace the module-level LLM adapter."""
    global _llm_adapter
    _llm_adapter = adapter


def build_learned_rules(correction_events: list[object]) -> dict[str, Category]:
    """Derive per-merchant learned rules from CategoryCorrected events.

    DERIVATION — pure function, safe to recompute on every classify call.
    The most recent correction for each merchant canonical wins.
    """
    from processing.classifier.classifier import build_learned_rules as _build

    return _build(correction_events)


def classify_transaction(
    transaction_hash: str,
    merchant_canonical: str,
    correction_events: list[object],
) -> TransactionCategorizedPayload:
    """Classify a transaction by merchant canonical name.

    Checks learned rules (derived from correction_events) first, then global
    rules, then LLM fallback. The caller passes the full CategoryCorrected
    event history so classification is reproducible from the event log alone —
    no separate mutable state (TRD §9.2).

    Args:
        transaction_hash: Idempotency hash of the transaction.
        merchant_canonical: Normalized merchant name from the normalizer.
        correction_events: All CategoryCorrected events for this user, in
            chronological order. Used to derive per-user learned rules.

    Returns:
        TransactionCategorizedPayload — caller records it as an event.

    Raises:
        BelowConfidenceThreshold: LLM confidence below threshold.
    """
    from processing.classifier.classifier import _classify_transaction

    return _classify_transaction(transaction_hash, merchant_canonical, correction_events)


def record_correction(
    transaction_hash: str,
    merchant_canonical: str,
    corrected_category: Category,
    prior_category: Category,
    user_id: str,
) -> CategoryCorrectedPayload:
    """Record a user's manual category correction as an event payload.

    Pure function — no side effects. The returned payload is stored by the
    caller as a CategoryCorrected event. On replay, this event supersedes
    any prior TransactionCategorized event for the same transaction_hash.
    """
    from processing.classifier.classifier import _record_correction

    return _record_correction(
        transaction_hash, merchant_canonical, corrected_category, prior_category, user_id
    )


def resolve_category(
    transaction_hash: str,
    user_id: str,
    events: list[object],
) -> Category:
    """Derive the effective category from the transaction's event history.

    DERIVATION — safe to recompute. The most recent CategoryCorrected event
    wins. If none exist, uses TransactionCategorized. Empty list raises ValueError.
    """
    from processing.classifier.classifier import _resolve_category

    return _resolve_category(transaction_hash, user_id, events)


def derive_effective_categories(
    categorized: Sequence[TransactionCategorizedPayload],
    corrections: Sequence[CategoryCorrectedPayload],
) -> dict[str, Category]:
    """DERIVATION: transaction_hash → effective category (PRD §4.3, ADR-020).

    Precedence per hash: the latest user correction, else the latest system
    categorization, else absent (no category). "Latest" means last in the given
    sequence; callers pass events in event-log order. Pure over recorded decisions,
    so it is safe to recompute on every read.
    """
    from processing.classifier.effective import derive_effective_categories as _derive

    return _derive(categorized, corrections)
