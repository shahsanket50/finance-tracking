"""FD booking matcher: savings debit + FD credit pair (ADR-014)."""

from processing.resolver.candidate import CandidateTxn
from processing.resolver.config import (
    FD_BOOKING_MATCH_WINDOW_DAYS,
    RESOLVER_CONFIDENCE_THRESHOLD,
)
from processing.resolver.events import MarkedFDBookingPayload
from processing.resolver.matching import score_candidate_pair


def find_matches(candidates: list[CandidateTxn]) -> list[MarkedFDBookingPayload]:
    """Find savings-debit + FD-credit pairs.

    Criteria:
    - Debit leg: account_type == "savings", amount_paise < 0
    - Credit leg: account_type == "fd", amount_paise > 0
    - Magnitudes equal, within FD_BOOKING_MATCH_WINDOW_DAYS
    - Confidence >= RESOLVER_CONFIDENCE_THRESHOLD
    """
    debits = [c for c in candidates if c.account_type == "savings" and c.amount_paise < 0]
    credits = [c for c in candidates if c.account_type == "fd" and c.amount_paise > 0]
    results: list[MarkedFDBookingPayload] = []
    matched_hashes: set[str] = set()
    for debit in debits:
        if debit.idempotency_hash in matched_hashes:
            continue
        for credit in credits:
            if credit.idempotency_hash in matched_hashes:
                continue
            confidence = score_candidate_pair(
                debit.amount_paise,
                debit.value_date,
                credit.amount_paise,
                credit.value_date,
                FD_BOOKING_MATCH_WINDOW_DAYS,
            )
            if confidence >= RESOLVER_CONFIDENCE_THRESHOLD:
                results.append(
                    MarkedFDBookingPayload(
                        savings_debit_hash=debit.idempotency_hash,
                        fd_credit_hash=credit.idempotency_hash,
                        matched_by="fd_booking_v1",
                        confidence=confidence,
                        match_window_days=FD_BOOKING_MATCH_WINDOW_DAYS,
                    )
                )
                matched_hashes.add(debit.idempotency_hash)
                matched_hashes.add(credit.idempotency_hash)
                break
    return results
