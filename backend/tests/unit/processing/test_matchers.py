"""Unit tests for the four resolver matchers (Wave 2, independent test-authoring).

Tests derived from TRD §9.1 C3, §9.2, §9.5 M4, ADR-014, and the Task 2 spec in
docs/superpowers/plans/2026-08-14-phase2-ledger-correctness.md.

INDEPENDENT AUTHORING: this file was written from the spec without opening
any file under processing/resolver/matchers/ or processing/resolver/matching.py.

Modules under test (not yet implemented — imports will fail until Wave 2 implementation):
  matchers.transfer   → find_matches(list[CandidateTxn]) -> list[MarkedInternalTransferPayload]
  matchers.cc_payment → find_matches(list[CandidateTxn]) -> list[MarkedCCPaymentPayload]
  matchers.fd_booking → find_matches(list[CandidateTxn]) -> list[MarkedFDBookingPayload]
  matchers.reversal   → find_matches(list[CandidateTxn]) -> list[MarkedReversalPayload]
  CandidateTxn(idempotency_hash, amount_paise, value_date, account_type)

All matchers:
- Accept list[CandidateTxn]
- Filter by account_type and sign polarity before calling score_candidate_pair
- Only return pairings where confidence >= RESOLVER_CONFIDENCE_THRESHOLD
- Never reuse the same leg in two separate pairings (each hash matched at most once)
"""

from datetime import date

from processing.resolver.candidate import CandidateTxn
from processing.resolver.config import RESOLVER_CONFIDENCE_THRESHOLD
from processing.resolver.events import (
    MarkedCCPaymentPayload,
    MarkedFDBookingPayload,
    MarkedInternalTransferPayload,
    MarkedReversalPayload,
)
from processing.resolver.matchers import cc_payment, fd_booking, reversal, transfer

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _txn(
    hash_suffix: str,
    amount_paise: int,
    value_date: date,
    account_type: str,
) -> CandidateTxn:
    return CandidateTxn(
        idempotency_hash=f"{'0' * (64 - len(hash_suffix))}{hash_suffix}",
        amount_paise=amount_paise,
        value_date=value_date,
        account_type=account_type,
    )


_DATE = date(2025, 6, 15)
_AMT = 500000  # ₹5 000 in paise — a concrete realistic amount


# ===========================================================================
# Transfer matcher
# ===========================================================================


class TestTransferMatcher:
    def test_savings_debit_and_credit_same_day_match_returned(self) -> None:
        """Canonical transfer: savings debit + savings credit, same amount, same day."""
        debit = _txn("d001", -_AMT, _DATE, "savings")
        credit = _txn("c001", _AMT, _DATE, "savings")
        results = transfer.find_matches([debit, credit])
        assert len(results) == 1
        result = results[0]
        assert isinstance(result, MarkedInternalTransferPayload)
        assert result.debit_hash == debit.idempotency_hash
        assert result.credit_hash == credit.idempotency_hash
        assert result.confidence >= RESOLVER_CONFIDENCE_THRESHOLD

    def test_savings_both_credits_no_match(self) -> None:
        """No debit leg → no transfer pair."""
        credit1 = _txn("c001", _AMT, _DATE, "savings")
        credit2 = _txn("c002", _AMT, _DATE, "savings")
        results = transfer.find_matches([credit1, credit2])
        assert results == []

    def test_savings_debit_cc_credit_no_match(self) -> None:
        """Transfer matcher requires both legs to be account_type='savings'."""
        debit = _txn("d001", -_AMT, _DATE, "savings")
        cc_credit = _txn("c001", _AMT, _DATE, "credit_card")
        results = transfer.find_matches([debit, cc_credit])
        assert results == []

    def test_two_debits_one_credit_at_most_one_match(self) -> None:
        """A credit leg may only be used once — not matched against both debits."""
        debit1 = _txn("d001", -_AMT, _DATE, "savings")
        debit2 = _txn("d002", -_AMT, _DATE, "savings")
        credit = _txn("c001", _AMT, _DATE, "savings")
        results = transfer.find_matches([debit1, debit2, credit])
        assert len(results) == 1
        credit_hashes_used = [r.credit_hash for r in results]
        assert len(credit_hashes_used) == len(set(credit_hashes_used)), (
            "same credit hash used more than once"
        )

    def test_one_debit_two_credits_at_most_one_match(self) -> None:
        """A debit leg may only be used once."""
        debit = _txn("d001", -_AMT, _DATE, "savings")
        credit1 = _txn("c001", _AMT, _DATE, "savings")
        credit2 = _txn("c002", _AMT, _DATE, "savings")
        results = transfer.find_matches([debit, credit1, credit2])
        assert len(results) == 1

    def test_confidence_below_threshold_no_result(self) -> None:
        """If window forces low confidence, no match is returned."""
        # Use a date 10 days apart with default window=3 → outside window → score=0
        debit = _txn("d001", -_AMT, _DATE, "savings")
        credit = _txn("c001", _AMT, date(2025, 6, 25), "savings")  # 10 days later
        results = transfer.find_matches([debit, credit])
        assert results == []

    def test_empty_candidates_returns_empty(self) -> None:
        assert transfer.find_matches([]) == []

    def test_only_debits_returns_empty(self) -> None:
        debits = [_txn(f"d{i:03d}", -_AMT, _DATE, "savings") for i in range(3)]
        assert transfer.find_matches(debits) == []

    def test_matched_by_field_is_transfer_v1(self) -> None:
        debit = _txn("d001", -_AMT, _DATE, "savings")
        credit = _txn("c001", _AMT, _DATE, "savings")
        results = transfer.find_matches([debit, credit])
        assert results[0].matched_by == "transfer_v1"

    def test_debit_hash_not_same_as_credit_hash(self) -> None:
        debit = _txn("d001", -_AMT, _DATE, "savings")
        credit = _txn("c001", _AMT, _DATE, "savings")
        results = transfer.find_matches([debit, credit])
        assert results[0].debit_hash != results[0].credit_hash

    def test_fd_account_type_not_matched_by_transfer(self) -> None:
        """FD account type is not a savings account — transfer matcher ignores it."""
        debit = _txn("d001", -_AMT, _DATE, "savings")
        fd_credit = _txn("c001", _AMT, _DATE, "fd")
        results = transfer.find_matches([debit, fd_credit])
        assert results == []


# ===========================================================================
# CC Payment matcher
# ===========================================================================


class TestCCPaymentMatcher:
    def test_savings_debit_cc_credit_same_day_match(self) -> None:
        """Canonical CC payment: savings debit + credit_card credit, same amount, same day."""
        debit = _txn("d001", -_AMT, _DATE, "savings")
        cc_credit = _txn("c001", _AMT, _DATE, "credit_card")
        results = cc_payment.find_matches([debit, cc_credit])
        assert len(results) == 1
        result = results[0]
        assert isinstance(result, MarkedCCPaymentPayload)
        assert result.savings_debit_hash == debit.idempotency_hash
        assert result.cc_credit_hash == cc_credit.idempotency_hash
        assert result.confidence >= RESOLVER_CONFIDENCE_THRESHOLD

    def test_savings_debit_savings_credit_no_match(self) -> None:
        """CC payment matcher requires credit leg to be account_type='credit_card'."""
        debit = _txn("d001", -_AMT, _DATE, "savings")
        savings_credit = _txn("c001", _AMT, _DATE, "savings")
        results = cc_payment.find_matches([debit, savings_credit])
        assert results == []

    def test_cc_debit_savings_credit_no_match(self) -> None:
        """Debit leg must be savings, not credit_card."""
        cc_debit = _txn("d001", -_AMT, _DATE, "credit_card")
        savings_credit = _txn("c001", _AMT, _DATE, "savings")
        results = cc_payment.find_matches([cc_debit, savings_credit])
        assert results == []

    def test_confidence_threshold_respected(self) -> None:
        """Date far outside match window → confidence=0 → no result."""
        debit = _txn("d001", -_AMT, _DATE, "savings")
        cc_credit = _txn("c001", _AMT, date(2025, 7, 15), "credit_card")  # 30 days later
        results = cc_payment.find_matches([debit, cc_credit])
        assert results == []

    def test_amount_mismatch_no_match(self) -> None:
        debit = _txn("d001", -_AMT, _DATE, "savings")
        cc_credit = _txn("c001", _AMT + 1, _DATE, "credit_card")
        results = cc_payment.find_matches([debit, cc_credit])
        assert results == []

    def test_match_window_days_field_populated(self) -> None:
        """match_window_days must be populated on the payload."""
        debit = _txn("d001", -_AMT, _DATE, "savings")
        cc_credit = _txn("c001", _AMT, _DATE, "credit_card")
        results = cc_payment.find_matches([debit, cc_credit])
        assert len(results) == 1
        assert results[0].match_window_days > 0

    def test_matched_by_field_is_cc_payment_v1(self) -> None:
        debit = _txn("d001", -_AMT, _DATE, "savings")
        cc_credit = _txn("c001", _AMT, _DATE, "credit_card")
        results = cc_payment.find_matches([debit, cc_credit])
        assert results[0].matched_by == "cc_payment_v1"

    def test_two_debits_one_cc_credit_at_most_one_match(self) -> None:
        debit1 = _txn("d001", -_AMT, _DATE, "savings")
        debit2 = _txn("d002", -_AMT, _DATE, "savings")
        cc_credit = _txn("c001", _AMT, _DATE, "credit_card")
        results = cc_payment.find_matches([debit1, debit2, cc_credit])
        assert len(results) == 1

    def test_empty_candidates_returns_empty(self) -> None:
        assert cc_payment.find_matches([]) == []

    def test_fd_credit_not_matched_by_cc_payment(self) -> None:
        debit = _txn("d001", -_AMT, _DATE, "savings")
        fd_credit = _txn("c001", _AMT, _DATE, "fd")
        results = cc_payment.find_matches([debit, fd_credit])
        assert results == []


# ===========================================================================
# FD Booking matcher
# ===========================================================================


class TestFDBookingMatcher:
    def test_savings_debit_fd_credit_same_day_match(self) -> None:
        """Canonical FD booking: savings debit + fd credit, same amount, same day."""
        debit = _txn("d001", -_AMT, _DATE, "savings")
        fd_credit = _txn("c001", _AMT, _DATE, "fd")
        results = fd_booking.find_matches([debit, fd_credit])
        assert len(results) == 1
        result = results[0]
        assert isinstance(result, MarkedFDBookingPayload)
        assert result.savings_debit_hash == debit.idempotency_hash
        assert result.fd_credit_hash == fd_credit.idempotency_hash
        assert result.confidence >= RESOLVER_CONFIDENCE_THRESHOLD

    def test_savings_debit_savings_credit_no_match(self) -> None:
        """FD booking matcher requires credit leg to be account_type='fd'."""
        debit = _txn("d001", -_AMT, _DATE, "savings")
        savings_credit = _txn("c001", _AMT, _DATE, "savings")
        results = fd_booking.find_matches([debit, savings_credit])
        assert results == []

    def test_savings_debit_cc_credit_no_match(self) -> None:
        debit = _txn("d001", -_AMT, _DATE, "savings")
        cc_credit = _txn("c001", _AMT, _DATE, "credit_card")
        results = fd_booking.find_matches([debit, cc_credit])
        assert results == []

    def test_confidence_threshold_respected(self) -> None:
        debit = _txn("d001", -_AMT, _DATE, "savings")
        fd_credit = _txn("c001", _AMT, date(2025, 7, 1), "fd")  # 16 days later, outside window
        results = fd_booking.find_matches([debit, fd_credit])
        assert results == []

    def test_amount_mismatch_no_match(self) -> None:
        debit = _txn("d001", -_AMT, _DATE, "savings")
        fd_credit = _txn("c001", _AMT + 500, _DATE, "fd")
        results = fd_booking.find_matches([debit, fd_credit])
        assert results == []

    def test_match_window_days_field_populated(self) -> None:
        debit = _txn("d001", -_AMT, _DATE, "savings")
        fd_credit = _txn("c001", _AMT, _DATE, "fd")
        results = fd_booking.find_matches([debit, fd_credit])
        assert results[0].match_window_days > 0

    def test_matched_by_field_is_fd_booking_v1(self) -> None:
        debit = _txn("d001", -_AMT, _DATE, "savings")
        fd_credit = _txn("c001", _AMT, _DATE, "fd")
        results = fd_booking.find_matches([debit, fd_credit])
        assert results[0].matched_by == "fd_booking_v1"

    def test_two_debits_one_fd_credit_at_most_one_match(self) -> None:
        debit1 = _txn("d001", -_AMT, _DATE, "savings")
        debit2 = _txn("d002", -_AMT, _DATE, "savings")
        fd_credit = _txn("c001", _AMT, _DATE, "fd")
        results = fd_booking.find_matches([debit1, debit2, fd_credit])
        assert len(results) == 1

    def test_empty_candidates_returns_empty(self) -> None:
        assert fd_booking.find_matches([]) == []

    def test_fd_debit_not_matched_as_credit(self) -> None:
        """FD debit (amount < 0) is not a credit leg."""
        savings_debit = _txn("d001", -_AMT, _DATE, "savings")
        fd_debit = _txn("d002", -_AMT, _DATE, "fd")
        results = fd_booking.find_matches([savings_debit, fd_debit])
        assert results == []


# ===========================================================================
# Reversal matcher
# ===========================================================================


class TestReversalMatcher:
    def test_savings_debit_savings_credit_same_account_type_match(self) -> None:
        """Canonical reversal: original debit + reversal credit, same account_type."""
        original = _txn("d001", -_AMT, _DATE, "savings")
        rev = _txn("c001", _AMT, _DATE, "savings")
        results = reversal.find_matches([original, rev])
        assert len(results) == 1
        result = results[0]
        assert isinstance(result, MarkedReversalPayload)
        assert result.original_hash == original.idempotency_hash
        assert result.reversal_hash == rev.idempotency_hash
        assert result.confidence >= RESOLVER_CONFIDENCE_THRESHOLD

    def test_savings_debit_credit_card_credit_no_match(self) -> None:
        """Reversal requires both legs to have the same account_type."""
        original = _txn("d001", -_AMT, _DATE, "savings")
        rev = _txn("c001", _AMT, _DATE, "credit_card")
        results = reversal.find_matches([original, rev])
        assert results == []

    def test_credit_card_debit_credit_card_credit_match(self) -> None:
        """Reversal is account-type-agnostic as long as both match."""
        original = _txn("d001", -_AMT, _DATE, "credit_card")
        rev = _txn("c001", _AMT, _DATE, "credit_card")
        results = reversal.find_matches([original, rev])
        assert len(results) == 1
        assert isinstance(results[0], MarkedReversalPayload)

    def test_confidence_threshold_respected(self) -> None:
        original = _txn("d001", -_AMT, _DATE, "savings")
        rev = _txn("c001", _AMT, date(2025, 7, 15), "savings")  # 30 days later
        results = reversal.find_matches([original, rev])
        assert results == []

    def test_amount_mismatch_no_match(self) -> None:
        original = _txn("d001", -_AMT, _DATE, "savings")
        rev = _txn("c001", _AMT + 100, _DATE, "savings")
        results = reversal.find_matches([original, rev])
        assert results == []

    def test_matched_by_field_is_reversal_v1(self) -> None:
        original = _txn("d001", -_AMT, _DATE, "savings")
        rev = _txn("c001", _AMT, _DATE, "savings")
        results = reversal.find_matches([original, rev])
        assert results[0].matched_by == "reversal_v1"

    def test_original_hash_not_same_as_reversal_hash(self) -> None:
        original = _txn("d001", -_AMT, _DATE, "savings")
        rev = _txn("c001", _AMT, _DATE, "savings")
        results = reversal.find_matches([original, rev])
        assert results[0].original_hash != results[0].reversal_hash

    def test_two_debits_one_credit_at_most_one_match(self) -> None:
        original1 = _txn("d001", -_AMT, _DATE, "savings")
        original2 = _txn("d002", -_AMT, _DATE, "savings")
        rev = _txn("c001", _AMT, _DATE, "savings")
        results = reversal.find_matches([original1, original2, rev])
        reversal_hashes = [r.reversal_hash for r in results]
        assert len(reversal_hashes) == len(set(reversal_hashes)), (
            "same reversal hash used more than once"
        )

    def test_empty_candidates_returns_empty(self) -> None:
        assert reversal.find_matches([]) == []

    def test_no_debit_returns_empty(self) -> None:
        credits = [_txn(f"c{i:03d}", _AMT, _DATE, "savings") for i in range(3)]
        assert reversal.find_matches(credits) == []

    def test_fd_debit_fd_credit_same_account_type_match(self) -> None:
        """Reversal matcher works for any account_type, not just savings."""
        original = _txn("d001", -_AMT, _DATE, "fd")
        rev = _txn("c001", _AMT, _DATE, "fd")
        results = reversal.find_matches([original, rev])
        assert len(results) == 1


# ===========================================================================
# Cross-matcher: no leg double-counted (invariant 4)
# ===========================================================================


class TestNoLegDoubleCountedAcrossMatchers:
    """Each individual matcher must not reuse a leg hash within its own results.

    Cross-matcher deduplication (e.g. a transfer pair also matching as a reversal)
    is the resolver orchestrator's responsibility, not tested here.
    """

    def test_transfer_no_hash_appears_in_two_results(self) -> None:
        candidates = [
            _txn("d001", -_AMT, _DATE, "savings"),
            _txn("d002", -_AMT, _DATE, "savings"),
            _txn("c001", _AMT, _DATE, "savings"),
            _txn("c002", _AMT, _DATE, "savings"),
        ]
        results = transfer.find_matches(candidates)
        all_hashes = [r.debit_hash for r in results] + [r.credit_hash for r in results]
        assert len(all_hashes) == len(set(all_hashes)), "a hash appears in two transfer pairs"

    def test_cc_payment_no_hash_appears_in_two_results(self) -> None:
        candidates = [
            _txn("d001", -_AMT, _DATE, "savings"),
            _txn("d002", -_AMT, _DATE, "savings"),
            _txn("c001", _AMT, _DATE, "credit_card"),
            _txn("c002", _AMT, _DATE, "credit_card"),
        ]
        results = cc_payment.find_matches(candidates)
        all_hashes = [r.savings_debit_hash for r in results] + [r.cc_credit_hash for r in results]
        assert len(all_hashes) == len(set(all_hashes))

    def test_fd_booking_no_hash_appears_in_two_results(self) -> None:
        candidates = [
            _txn("d001", -_AMT, _DATE, "savings"),
            _txn("d002", -_AMT, _DATE, "savings"),
            _txn("c001", _AMT, _DATE, "fd"),
            _txn("c002", _AMT, _DATE, "fd"),
        ]
        results = fd_booking.find_matches(candidates)
        all_hashes = [r.savings_debit_hash for r in results] + [r.fd_credit_hash for r in results]
        assert len(all_hashes) == len(set(all_hashes))

    def test_reversal_no_hash_appears_in_two_results(self) -> None:
        candidates = [
            _txn("d001", -_AMT, _DATE, "savings"),
            _txn("d002", -_AMT, _DATE, "savings"),
            _txn("c001", _AMT, _DATE, "savings"),
            _txn("c002", _AMT, _DATE, "savings"),
        ]
        results = reversal.find_matches(candidates)
        all_hashes = [r.original_hash for r in results] + [r.reversal_hash for r in results]
        assert len(all_hashes) == len(set(all_hashes))
