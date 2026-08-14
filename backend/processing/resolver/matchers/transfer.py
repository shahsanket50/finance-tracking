"""Transfer matcher: detects savings↔savings internal transfer pairs (ADR-014)."""

from processing.resolver.candidate import CandidateTxn
from processing.resolver.config import (
    RESOLVER_CONFIDENCE_THRESHOLD,
    TRANSFER_MATCH_WINDOW_DAYS,
)
from processing.resolver.events import MarkedInternalTransferPayload
from processing.resolver.matching import score_candidate_pair


def find_matches(candidates: list[CandidateTxn]) -> list[MarkedInternalTransferPayload]:
    """Find savings↔savings transfer pairs among candidates.

    Criteria:
    - Both legs must have account_type == "savings"
    - One leg is a debit (amount_paise < 0), the other a credit (amount_paise > 0)
    - Magnitudes equal, within TRANSFER_MATCH_WINDOW_DAYS
    - Confidence >= RESOLVER_CONFIDENCE_THRESHOLD
    """
    debits = [c for c in candidates if c.account_type == "savings" and c.amount_paise < 0]
    credits = [c for c in candidates if c.account_type == "savings" and c.amount_paise > 0]
    results: list[MarkedInternalTransferPayload] = []
    matched_hashes: set[str] = set()
    for debit in debits:
        if debit.idempotency_hash in matched_hashes:
            continue
        for credit in credits:
            if credit.idempotency_hash in matched_hashes:
                continue
            confidence = score_candidate_pair(
                debit.amount_paise, debit.value_date,
                credit.amount_paise, credit.value_date,
                TRANSFER_MATCH_WINDOW_DAYS,
            )
            if confidence >= RESOLVER_CONFIDENCE_THRESHOLD:
                results.append(MarkedInternalTransferPayload(
                    debit_hash=debit.idempotency_hash,
                    credit_hash=credit.idempotency_hash,
                    matched_by="transfer_v1",
                    confidence=confidence,
                ))
                matched_hashes.add(debit.idempotency_hash)
                matched_hashes.add(credit.idempotency_hash)
                break
    return results
