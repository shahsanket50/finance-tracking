"""Property-based tests for Invariant 4 (CLAUDE.md §2.4).

Invariant 4: a matched internal-transfer pair never appears in expense totals.
Generalised here: any transaction excluded by a resolver decision event
(MarkedInternalTransfer, MarkedCCPayment, MarkedFDBooking, MarkedReversal) must
not contribute to income_paise or expense_paise in the transactions_view totals.

Phase 3 builds budget maths directly on transactions_view — this must hold by
construction, not only by example coverage.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import cast

from hypothesis import given, settings
from hypothesis import strategies as st

from core.events.store import Event
from core.projections.builder import build_projection_from_events

_UTC = UTC
_USER = uuid.uuid4()
_NOW = datetime(2026, 1, 1, tzinfo=_UTC)

# Resolver event type names paired with their payload field names for each leg.
_RESOLVER_PAYLOAD_KEYS = {
    "MarkedInternalTransfer": ("debit_hash", "credit_hash"),
    "MarkedCCPayment": ("savings_debit_hash", "cc_credit_hash"),
    "MarkedFDBooking": ("savings_debit_hash", "fd_credit_hash"),
    "MarkedReversal": ("original_hash", "reversal_hash"),
}


def _txn_event(h: str, amount_paise: int, txn_type: str, seq: int = 1) -> Event:
    return Event(
        id=uuid.uuid4(),
        seq=seq,
        event_version=1,
        event_type="TransactionIngested",
        user_id=_USER,
        aggregate_id="ACC001",
        payload={
            "idempotency_hash": h,
            "amount_paise": amount_paise,
            "value_date": "2026-01-01",
            "account_ref": "ACC001",
            "transaction_type": txn_type,
        },
        created_at=_NOW,
    )


def _resolver_event(event_type: str, h1: str, h2: str, seq: int = 2) -> Event:
    key1, key2 = _RESOLVER_PAYLOAD_KEYS[event_type]
    return Event(
        id=uuid.uuid4(),
        seq=seq,
        event_version=1,
        event_type=event_type,
        user_id=_USER,
        aggregate_id="RESOLVER",
        payload={
            key1: h1,
            key2: h2,
            "matched_by": f"{event_type.lower()}_v1",
            "confidence": 9500,
        },
        created_at=_NOW,
    )


# Strategy: generate N distinct hashes, each with an amount and txn_type.
_hash_str = st.text(min_size=8, max_size=16, alphabet="abcdef0123456789").filter(
    lambda s: len(s) >= 8
)

_txn_type = st.sampled_from(["income", "expense"])
_resolver_type = st.sampled_from(list(_RESOLVER_PAYLOAD_KEYS.keys()))


@st.composite
def txn_set_with_optional_pair(
    draw: st.DrawFn,
) -> tuple[list[Event], set[str], dict[str, int], dict[str, str]]:
    """Draw 2–8 transactions; optionally mark one pair as matched."""
    n = draw(st.integers(min_value=2, max_value=8))
    hashes = draw(st.lists(_hash_str, min_size=n, max_size=n, unique=True))
    txn_types = [draw(_txn_type) for _ in hashes]
    # Amounts always positive; sign applied based on txn_type below.
    raw_amounts = [draw(st.integers(min_value=100, max_value=1_000_000)) for _ in hashes]

    events: list[Event] = []
    amounts_by_hash: dict[str, int] = {}
    types_by_hash: dict[str, str] = {}
    for seq, (h, txn_type, amt) in enumerate(
        zip(hashes, txn_types, raw_amounts, strict=True), start=1
    ):
        signed = -amt if txn_type == "expense" else amt
        amounts_by_hash[h] = amt  # always positive for expectation arithmetic
        types_by_hash[h] = txn_type
        events.append(_txn_event(h, signed, txn_type, seq=seq))

    matched: set[str] = set()
    if draw(st.booleans()) and len(hashes) >= 2:
        h1, h2 = hashes[0], hashes[1]
        resolver_type = draw(_resolver_type)
        events.append(_resolver_event(resolver_type, h1, h2, seq=len(hashes) + 1))
        matched.update([h1, h2])

    return events, matched, amounts_by_hash, types_by_hash


@given(txn_set_with_optional_pair())
@settings(max_examples=200)
def test_invariant4_excluded_transactions_absent_from_totals(
    data: tuple[list[Event], set[str], dict[str, int], dict[str, str]],
) -> None:
    """For any sequence of ingestion + resolver events, excluded hashes never
    contribute to income_paise or expense_paise totals (Invariant 4).
    """
    events, matched_hashes, amounts_by_hash, types_by_hash = data

    state = build_projection_from_events(events, "transactions_view")
    totals = cast(dict[str, int], state["totals"])
    excluded_set: set[str] = set(cast(list[str], state["excluded_hashes"]))

    # All hashes marked by the resolver event must be excluded.
    for h in matched_hashes:
        assert h in excluded_set, f"hash {h!r} was marked matched but is not in excluded_hashes"

    # Recompute expected totals excluding all excluded hashes.
    expected_income = sum(
        amounts_by_hash[h]
        for h, t in types_by_hash.items()
        if t == "income" and h not in excluded_set
    )
    expected_expense = sum(
        amounts_by_hash[h]
        for h, t in types_by_hash.items()
        if t == "expense" and h not in excluded_set
    )
    assert totals["income_paise"] == expected_income, (
        f"income_paise={totals['income_paise']} != expected {expected_income}; "
        f"excluded={excluded_set}"
    )
    assert totals["expense_paise"] == expected_expense, (
        f"expense_paise={totals['expense_paise']} != expected {expected_expense}; "
        f"excluded={excluded_set}"
    )
