"""Effective category derivation. Implements PRD §4.3, ADR-020.

DERIVATION over recorded decisions (TRD §3.4): per transaction hash, the latest user
correction wins, else the latest system categorization, else the hash is absent.
"""

from __future__ import annotations

from collections.abc import Sequence

from processing.classifier.categories import Category
from processing.classifier.events import CategoryCorrectedPayload, TransactionCategorizedPayload


def derive_effective_categories(
    categorized: Sequence[TransactionCategorizedPayload],
    corrections: Sequence[CategoryCorrectedPayload],
) -> dict[str, Category]:
    effective: dict[str, Category] = {}
    for decision in categorized:
        effective[decision.transaction_hash] = decision.category
    for correction in corrections:
        effective[correction.transaction_hash] = correction.category
    return effective
