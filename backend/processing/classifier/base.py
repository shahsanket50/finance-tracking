"""Category classifier public contract. Implements PRD §4 Step 5."""

from __future__ import annotations

from processing.classifier.categories import Category
from processing.classifier.events import CategoryCorrectedPayload, TransactionCategorizedPayload


def classify_transaction(
    transaction_hash: str,
    merchant_canonical: str,
    user_id: str,
) -> TransactionCategorizedPayload:
    """Classify a transaction by merchant canonical name.

    Tries per-user learned rules first, then global rules, then LLM fallback.
    Returns a classification payload — the caller records it as an event.
    Raises BelowConfidenceThreshold if LLM result is below threshold.

    Args:
        transaction_hash: The idempotency hash of the transaction (TRD §9.1).
        merchant_canonical: The normalized merchant name from the normalizer.
        user_id: The owning user's id, for per-user rule lookup.

    Returns:
        TransactionCategorizedPayload with the assigned category, method, and confidence.

    Raises:
        BelowConfidenceThreshold: If LLM classification confidence is below threshold.
        RuntimeError: If no adapter is configured and LLM fallback is needed.
    """
    ...


def record_correction(
    transaction_hash: str,
    merchant_canonical: str,
    corrected_category: Category,
    prior_category: Category,
    user_id: str,
) -> CategoryCorrectedPayload:
    """Record a user's manual category correction as an event payload.

    The returned payload is stored as a CategoryCorrected event. On replay,
    this event supersedes any prior TransactionCategorized event for the same
    transaction_hash. The prior classification is preserved in prior_category.

    Args:
        transaction_hash: The idempotency hash of the transaction (TRD §9.1).
        merchant_canonical: The normalized merchant name.
        corrected_category: The user's chosen category.
        prior_category: The category that was previously assigned.
        user_id: The owning user's id.

    Returns:
        CategoryCorrectedPayload ready to be recorded as an event.
    """
    ...


def resolve_category(
    transaction_hash: str,
    user_id: str,
    events: list[object],
) -> Category:
    """Derive the effective category for a transaction from its event history.

    Applies CategoryCorrected events in chronological order, so the most recent
    user correction wins. Returns the category from the last CategoryCorrected
    event if any exist; otherwise returns the category from the
    TransactionCategorized event.

    This is a DERIVATION (pure arithmetic over recorded facts) — safe to recompute.
    The decisions (classify_transaction, record_correction) are recorded separately.

    Args:
        transaction_hash: The idempotency hash of the transaction (TRD §9.1).
        user_id: The owning user's id.
        events: All events for this transaction (both TransactionCategorized
            and CategoryCorrected), in chronological order.

    Returns:
        The effective category for this transaction.

    Raises:
        ValueError: If no classification event exists in the event history.
    """
    ...
