"""CC payment matcher: savings debit + credit_card credit pair (ADR-014)."""

from core.events.types import ACCOUNT_TYPE_CREDIT_CARD, ACCOUNT_TYPE_SAVINGS
from processing.resolver.candidate import CandidateTxn
from processing.resolver.config import (
    CC_PAYMENT_MATCH_WINDOW_DAYS,
    RESOLVER_CONFIDENCE_THRESHOLD,
)
from processing.resolver.events import MarkedCCPaymentPayload
from processing.resolver.matching import score_candidate_pair


def find_matches(candidates: list[CandidateTxn]) -> list[MarkedCCPaymentPayload]:
    """Find savings-debit + credit-card-credit pairs.

    Criteria:
    - Debit leg: account_type == "savings", amount_paise < 0
    - Credit leg: account_type == "credit_card", amount_paise > 0
    - Magnitudes equal, within CC_PAYMENT_MATCH_WINDOW_DAYS
    - Confidence >= RESOLVER_CONFIDENCE_THRESHOLD
    """
    debits = [c for c in candidates if c.account_type == ACCOUNT_TYPE_SAVINGS and c.amount_paise < 0]
    credits = [c for c in candidates if c.account_type == ACCOUNT_TYPE_CREDIT_CARD and c.amount_paise > 0]
    results: list[MarkedCCPaymentPayload] = []
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
                CC_PAYMENT_MATCH_WINDOW_DAYS,
            )
            if confidence >= RESOLVER_CONFIDENCE_THRESHOLD:
                results.append(
                    MarkedCCPaymentPayload(
                        savings_debit_hash=debit.idempotency_hash,
                        cc_credit_hash=credit.idempotency_hash,
                        matched_by="cc_payment_v1",
                        confidence=confidence,
                        match_window_days=CC_PAYMENT_MATCH_WINDOW_DAYS,
                    )
                )
                matched_hashes.add(debit.idempotency_hash)
                matched_hashes.add(credit.idempotency_hash)
                break
    return results
