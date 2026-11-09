"""Budget utilization public contract. Implements PRD §4.3, ADR-020.

Records:
    BudgetTransaction — one ingested transaction as budgets see it: its idempotency hash,
    its SIGNED amount in paise (debit negative, credit positive, TRD §10.2), its value date,
    and its effective category (user correction → classifier → None; derived separately by
    processing.classifier.base.derive_effective_categories).

Derivation contract — derive_budget_utilization(transactions, excluded_hashes, category, month):
    net_spend_paise = −Σ amount_paise over transactions where
        • effective_category == category,
        • value_date falls in the calendar month of `month` (month must be the 1st),
        • idempotency_hash is NOT in excluded_hashes (resolver legs, PRD §7.1),
        • each idempotency_hash is counted once, however many times it appears (Invariant 1).
    • Refunds (positive amounts in the category) reduce net spend in the month they post.
    • The result is a signed int and is NEVER clamped; it may be negative (net refund).
      Clamping is a display concern only.
    • transaction_type is not an input (ADR-021); the sign is the only direction signal.
    • An empty input, or no matching rows, returns 0 (genuinely zero, not unknown).
    • Duplicate hashes are assumed to be the same transaction. Two records with the same
      hash but different amount/date/category are a corrupted input: raise ValueError.

Edge adapter contract — budget_transactions_from_events(events, effective_categories):
    • Reads decrypted Event objects; keeps only TransactionIngested events, and ignores
      resolver events and every other type.
    • hash, amount_paise and value_date come from the event payload as ingestion writes them.
    • effective_category = effective_categories.get(hash), so an absent hash is None.
    • Order-preserving; does NOT deduplicate (that is the derivation's job, Invariant 1).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence, Set
from dataclasses import dataclass
from datetime import date

from core.events.store import Event
from processing.classifier.categories import Category


@dataclass(frozen=True)
class BudgetTransaction:
    idempotency_hash: str
    amount_paise: int  # signed: debit negative, credit positive
    value_date: date
    effective_category: Category | None


def derive_budget_utilization(
    transactions: Sequence[BudgetTransaction],
    excluded_hashes: Set[str],
    category: Category,
    month: date,
) -> int:
    """DERIVATION: signed net spend (paise) for (category, calendar month). See module doc."""
    from processing.budgets.utilization import derive_budget_utilization as _derive

    return _derive(transactions, excluded_hashes, category, month)


def budget_transactions_from_events(
    events: Sequence[Event],
    effective_categories: Mapping[str, Category],
) -> list[BudgetTransaction]:
    """Edge adapter: decrypted TransactionIngested events → BudgetTransaction records."""
    from processing.budgets.adapter import budget_transactions_from_events as _adapt

    return _adapt(events, effective_categories)
