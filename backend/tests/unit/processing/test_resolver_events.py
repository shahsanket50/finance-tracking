"""Unit tests for resolver event payload schemas and config constants (Wave 1).

Tests derived from TRD §9.1 C3, §9.2, and §9.5 M4.
"""

import pytest
from pydantic import ValidationError

from processing.resolver.config import (
    CC_PAYMENT_MATCH_WINDOW_DAYS,
    FD_BOOKING_MATCH_WINDOW_DAYS,
    RESOLVER_CONFIDENCE_THRESHOLD,
    TRANSFER_MATCH_WINDOW_DAYS,
)
from processing.resolver.events import (
    RESOLVER_EVENT_TYPES,
    MarkedCCPaymentPayload,
    MarkedFDBookingPayload,
    MarkedInternalTransferPayload,
    MarkedReversalPayload,
)


def test_four_resolver_event_types_defined() -> None:
    """All four resolver event types confirmed in scope (owner, 2026-08-14)."""
    assert RESOLVER_EVENT_TYPES == {
        "MarkedInternalTransfer",
        "MarkedCCPayment",
        "MarkedFDBooking",
        "MarkedReversal",
    }


def test_marked_internal_transfer_valid() -> None:
    p = MarkedInternalTransferPayload(
        debit_hash="a" * 64,
        credit_hash="b" * 64,
        matched_by="transfer_v1",
        confidence=9500,
    )
    assert p.confidence == 9500
    assert p.debit_hash != p.credit_hash


def test_marked_cc_payment_valid() -> None:
    p = MarkedCCPaymentPayload(
        savings_debit_hash="a" * 64,
        cc_credit_hash="b" * 64,
        matched_by="cc_payment_v1",
        confidence=9000,
        match_window_days=CC_PAYMENT_MATCH_WINDOW_DAYS,
    )
    assert p.match_window_days == CC_PAYMENT_MATCH_WINDOW_DAYS


def test_marked_fd_booking_valid() -> None:
    p = MarkedFDBookingPayload(
        savings_debit_hash="a" * 64,
        fd_credit_hash="b" * 64,
        matched_by="fd_booking_v1",
        confidence=9000,
        match_window_days=FD_BOOKING_MATCH_WINDOW_DAYS,
    )
    assert p.match_window_days == FD_BOOKING_MATCH_WINDOW_DAYS


def test_marked_reversal_valid() -> None:
    p = MarkedReversalPayload(
        original_hash="a" * 64,
        reversal_hash="b" * 64,
        matched_by="reversal_v1",
        confidence=9500,
    )
    assert p.original_hash != p.reversal_hash


def test_confidence_above_max_rejected() -> None:
    with pytest.raises(ValidationError):
        MarkedInternalTransferPayload(
            debit_hash="a" * 64,
            credit_hash="b" * 64,
            matched_by="v1",
            confidence=10001,
        )


def test_confidence_negative_rejected() -> None:
    with pytest.raises(ValidationError):
        MarkedInternalTransferPayload(
            debit_hash="a" * 64,
            credit_hash="b" * 64,
            matched_by="v1",
            confidence=-1,
        )


def test_payloads_are_frozen() -> None:
    """Frozen Pydantic models — prevent accidental mutation after construction."""
    p = MarkedInternalTransferPayload(
        debit_hash="a" * 64,
        credit_hash="b" * 64,
        matched_by="v1",
        confidence=9000,
    )
    with pytest.raises(ValidationError):
        p.confidence = 5000


def test_match_window_constants_are_positive_ints() -> None:
    for val in (
        TRANSFER_MATCH_WINDOW_DAYS,
        CC_PAYMENT_MATCH_WINDOW_DAYS,
        FD_BOOKING_MATCH_WINDOW_DAYS,
    ):
        assert isinstance(val, int)
        assert val > 0


def test_resolver_confidence_threshold_in_range() -> None:
    assert isinstance(RESOLVER_CONFIDENCE_THRESHOLD, int)
    assert 0 < RESOLVER_CONFIDENCE_THRESHOLD <= 10000


def test_transfer_payload_round_trips_through_dict() -> None:
    """Payload survives dict() → model reconstruct (Pydantic serialization)."""
    original = MarkedInternalTransferPayload(
        debit_hash="a" * 64,
        credit_hash="b" * 64,
        matched_by="transfer_v1",
        confidence=9500,
    )
    reconstructed = MarkedInternalTransferPayload(**original.model_dump())
    assert reconstructed == original


def test_all_payload_classes_are_importable() -> None:
    """All four payload classes must be importable from events module."""
    from processing.resolver.events import (  # noqa: F401
        MarkedCCPaymentPayload,
        MarkedFDBookingPayload,
        MarkedInternalTransferPayload,
        MarkedReversalPayload,
    )
