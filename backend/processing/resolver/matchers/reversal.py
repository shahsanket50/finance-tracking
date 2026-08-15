"""Reversal matcher: original transaction + reversal credit pair (ADR-014)."""

from processing.resolver.candidate import CandidateTxn
from processing.resolver.config import (
    RESOLVER_CONFIDENCE_THRESHOLD,
    REVERSAL_MATCH_WINDOW_DAYS,
)
from processing.resolver.events import MarkedReversalPayload
from processing.resolver.matching import score_candidate_pair


def find_matches(candidates: list[CandidateTxn]) -> list[MarkedReversalPayload]:
    """Find original-debit + reversal-credit pairs.

    Criteria:
    - Original leg: amount_paise < 0 (debit)
    - Reversal leg: amount_paise > 0 (credit), same account_type as original
    - Magnitudes equal, within _REVERSAL_WINDOW_DAYS
    - Confidence >= RESOLVER_CONFIDENCE_THRESHOLD
    """
    debits = [c for c in candidates if c.amount_paise < 0]
    credits = [c for c in candidates if c.amount_paise > 0]
    results: list[MarkedReversalPayload] = []
    matched_hashes: set[str] = set()
    for debit in debits:
        if debit.idempotency_hash in matched_hashes:
            continue
        for credit in credits:
            if credit.idempotency_hash in matched_hashes:
                continue
            if credit.account_type != debit.account_type:
                continue
            confidence = score_candidate_pair(
                debit.amount_paise,
                debit.value_date,
                credit.amount_paise,
                credit.value_date,
                REVERSAL_MATCH_WINDOW_DAYS,
            )
            if confidence >= RESOLVER_CONFIDENCE_THRESHOLD:
                results.append(
                    MarkedReversalPayload(
                        original_hash=debit.idempotency_hash,
                        reversal_hash=credit.idempotency_hash,
                        matched_by="reversal_v1",
                        confidence=confidence,
                    )
                )
                matched_hashes.add(debit.idempotency_hash)
                matched_hashes.add(credit.idempotency_hash)
                break
    return results
