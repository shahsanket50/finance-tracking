"""Independent budget utilization tests. Wave 5, B2/B3 + Invariants 1 and 4.

Independent test-authoring (CLAUDE.md §6, TRD §11, PHASE_PROTOCOL §3): written from
PRD §3.2, §4.1, §7.1, §7.2, CLAUDE.md §2 and the Wave 5 checklist (B2, B3) without
opening backend/processing/budgets/utilization.py or router.py.

Contract assumed by these tests (inferred from spec, not from the implementation):

    derive_budget_utilization(events, category, month) -> int

- ``events`` is a list of dict rows: the raw transaction event stream for the user,
  keyed like ``transaction_events`` columns (event_type, idempotency_hash, account_ref, value_date,
  amount_paise) plus the recorded ``category`` decision for the transaction. It contains
  both ``TransactionIngested`` events and resolver events (RESOLVER_EVENT_TYPES).
- A resolver event's ``idempotency_hash`` names the excluded leg — the same mechanism
  Wave 4 uses to derive account balances (crud_router: hashes of RESOLVER_EVENT_TYPES
  rows are filtered out before summing). Exclusion therefore comes from the event log,
  never from a caller-supplied flag.
- ``month`` is the first day of a calendar month (BudgetCreate.month validator).
- The result is spend in int paise, positive (B6: spent is compared against a positive
  ``target_paise`` limit).

Refund / credit netting within a category is deliberately NOT tested: the spec does not
say how a credit in a budgeted category affects utilization (needs_decision).
"""

from __future__ import annotations

import random
from datetime import date

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from core.events.types import (
    MARKED_CC_PAYMENT,
    MARKED_FD_BOOKING,
    MARKED_INTERNAL_TRANSFER,
    MARKED_REVERSAL,
    RESOLVER_EVENT_TYPES,
    TRANSACTION_INGESTED,
)
from processing.budgets.utilization import derive_budget_utilization

MONTH = date(2026, 9, 1)
CATEGORY = "food_dining"
OTHER_CATEGORY = "shopping"
SAVINGS_REF = "HDFC_1234"
CC_REF = "HDFC_CC_7890"


LedgerEvent = dict[str, object]
"""A transaction_events-shaped row plus its recorded category, as a plain mapping."""


def ingested(
    txn_hash: str,
    amount_paise: int,
    *,
    category: str = CATEGORY,
    value_date: date = date(2026, 9, 15),
    account_ref: str = SAVINGS_REF,
) -> LedgerEvent:
    return {
        "event_type": TRANSACTION_INGESTED,
        "idempotency_hash": txn_hash,
        "account_ref": account_ref,
        "value_date": value_date,
        "amount_paise": amount_paise,
        "category": category,
    }


def resolver_mark(
    event_type: str,
    leg_hash: str,
    amount_paise: int,
    *,
    value_date: date = date(2026, 9, 15),
    account_ref: str = SAVINGS_REF,
    category: str | None = None,
) -> LedgerEvent:
    return {
        "event_type": event_type,
        "idempotency_hash": leg_hash,
        "account_ref": account_ref,
        "value_date": value_date,
        "amount_paise": amount_paise,
        "category": category,
    }


# ---------------------------------------------------------------------------
# B2 — utilization = sum of non-excluded expenses in category for calendar month
# ---------------------------------------------------------------------------


class TestB2UtilizationBaseline:
    """B2: spend in the category for the calendar month, nothing else."""

    def test_sums_debits_in_category_and_month(self) -> None:
        events = [
            ingested("h_lunch", -450_00),
            ingested("h_dinner", -1_200_00),
            ingested("h_swiggy", -650_50),
        ]
        spent = derive_budget_utilization(events, CATEGORY, MONTH)
        assert spent == 2_300_50, (
            f"Expected 2_300_50 paise (₹2,300.50) of food_dining spend, got {spent}"
        )

    def test_empty_stream_is_zero_int(self) -> None:
        spent = derive_budget_utilization([], CATEGORY, MONTH)
        assert spent == 0
        assert type(spent) is int

    def test_other_category_not_counted(self) -> None:
        events = [
            ingested("h_lunch", -450_00),
            ingested("h_shoes", -4_999_00, category=OTHER_CATEGORY),
        ]
        assert derive_budget_utilization(events, CATEGORY, MONTH) == 450_00

    def test_calendar_month_boundaries(self) -> None:
        """PRD §3.1/§3.2: month view = 1st to last day; a txn belongs to exactly one month."""
        events = [
            ingested("h_prev_last_day", -100_00, value_date=date(2026, 8, 31)),
            ingested("h_first_day", -200_00, value_date=date(2026, 9, 1)),
            ingested("h_last_day", -300_00, value_date=date(2026, 9, 30)),
            ingested("h_next_first_day", -400_00, value_date=date(2026, 10, 1)),
        ]
        spent = derive_budget_utilization(events, CATEGORY, MONTH)
        assert spent == 500_00, (
            f"Expected only 1 Sep + 30 Sep debits (500_00 paise), got {spent}. "
            "31 Aug and 1 Oct belong to other months."
        )

    def test_result_is_int_never_float(self) -> None:
        spent = derive_budget_utilization([ingested("h_a", -333_33)], CATEGORY, MONTH)
        assert type(spent) is int, f"spent is {type(spent).__name__}, must be int paise"


# ---------------------------------------------------------------------------
# B3 / Invariant 1 — the same transaction hash is never counted twice
# ---------------------------------------------------------------------------


class TestB3NoDoubleCount:
    """B3 + Invariant 1: a hash presented twice (e.g. two sources) is counted once."""

    def test_same_hash_twice_counted_once(self) -> None:
        """PRD §7.2: same transaction via two sources → same hash → counted once."""
        events = [
            ingested("h_zomato", -850_00),
            ingested("h_zomato", -850_00),
        ]
        spent = derive_budget_utilization(events, CATEGORY, MONTH)
        assert spent == 850_00, (
            f"Hash h_zomato presented twice must count once: expected 850_00, got {spent}. "
            "Invariant 1 violated — budget utilization double-counts a transaction."
        )

    def test_same_hash_three_times_with_other_txns(self) -> None:
        events = [
            ingested("h_a", -100_00),
            ingested("h_dup", -999_00),
            ingested("h_b", -200_00),
            ingested("h_dup", -999_00),
            ingested("h_dup", -999_00),
        ]
        spent = derive_budget_utilization(events, CATEGORY, MONTH)
        assert spent == 1_299_00, f"Expected 1_299_00 (h_dup once), got {spent}"

    def test_identical_amount_distinct_hashes_both_counted(self) -> None:
        """PRD §7.2 occurrence_index: two real ₹250 coffees are two hashes, both count.

        Guards against over-deduplication by amount/date instead of by hash.
        """
        events = [
            ingested("h_coffee_occ0", -250_00),
            ingested("h_coffee_occ1", -250_00),
        ]
        spent = derive_budget_utilization(events, CATEGORY, MONTH)
        assert spent == 500_00, (
            f"Two distinct hashes with identical amount must both count: expected 500_00, "
            f"got {spent}"
        )

    @given(
        amounts=st.lists(
            st.integers(min_value=1, max_value=10_000_000_00), min_size=0, max_size=40
        ),
        duplicate_mask=st.lists(st.integers(min_value=0, max_value=3), max_size=40),
        seed=st.randoms(use_true_random=False),
    )
    @settings(max_examples=200)
    def test_property_duplicates_never_inflate(
        self,
        amounts: list[int],
        duplicate_mask: list[int],
        seed: random.Random,
    ) -> None:
        """Property: re-presenting any hashes any number of times, in any order,
        yields exactly the sum over unique hashes."""
        unique = [ingested(f"h_{i}", -amount) for i, amount in enumerate(amounts)]
        stream: list[LedgerEvent] = list(unique)
        for i, extra in enumerate(duplicate_mask[: len(unique)]):
            stream.extend([dict(unique[i]) for _ in range(extra)])
        seed.shuffle(stream)

        expected = sum(amounts)
        spent = derive_budget_utilization(stream, CATEGORY, MONTH)
        assert spent == expected, (
            f"Unique-hash spend is {expected} paise but utilization returned {spent} "
            f"for a stream of {len(stream)} events over {len(unique)} hashes."
        )


# ---------------------------------------------------------------------------
# Invariant 4 — resolver-paired legs never count as spend
#
# Scenario (PRD §7.1, mirrors Wave 4 AC7):
#   HDFC savings, September:
#     A: ₹1,200 restaurant debit, food_dining        — counted
#     B: ₹15,000 CC bill payment debit, food_dining  — EXCLUDED via MarkedCCPayment
#        (deliberately mis-categorized into the budgeted category, so only the
#         resolver exclusion — not the category filter — can keep it out)
#   HDFC CC:
#     D: ₹15,000 CC bill credit                      — EXCLUDED via MarkedCCPayment
#
#   Correct food_dining spend: ₹1,200.  Without exclusion: ₹16,200.
# ---------------------------------------------------------------------------


class TestInvariant4ResolverLegsExcluded:
    """Invariant 4: exclusion is driven by RESOLVER_EVENT_TYPES rows in the event log."""

    RESTAURANT_PAISE = -1_200_00
    CC_PAYMENT_PAISE = -15_000_00
    CC_CREDIT_PAISE = 15_000_00

    def test_resolver_event_types_cover_the_four_pairings(self) -> None:
        assert RESOLVER_EVENT_TYPES == frozenset(
            {MARKED_INTERNAL_TRANSFER, MARKED_CC_PAYMENT, MARKED_FD_BOOKING, MARKED_REVERSAL}
        )

    def test_cc_payment_leg_excluded(self) -> None:
        events = [
            ingested("h_restaurant", self.RESTAURANT_PAISE),
            ingested("h_cc_payment", self.CC_PAYMENT_PAISE),
            ingested("h_cc_credit", self.CC_CREDIT_PAISE, account_ref=CC_REF),
            resolver_mark(MARKED_CC_PAYMENT, "h_cc_payment", self.CC_PAYMENT_PAISE),
            resolver_mark(
                MARKED_CC_PAYMENT, "h_cc_credit", self.CC_CREDIT_PAISE, account_ref=CC_REF
            ),
        ]
        spent = derive_budget_utilization(events, CATEGORY, MONTH)

        correct = abs(self.RESTAURANT_PAISE)
        without_exclusion = abs(self.RESTAURANT_PAISE) + abs(self.CC_PAYMENT_PAISE)
        assert correct != without_exclusion
        assert spent == correct, (
            f"Expected {correct} paise (₹1,200) food_dining spend, got {spent}. "
            f"{without_exclusion} would mean the MarkedCCPayment leg was counted as spend "
            "on top of the card purchases it settles (Invariant 4)."
        )

    @pytest.mark.parametrize("resolver_event_type", sorted(RESOLVER_EVENT_TYPES))
    def test_every_resolver_event_type_excludes_its_leg(self, resolver_event_type: str) -> None:
        events = [
            ingested("h_counted", -300_00),
            ingested("h_paired_leg", -50_000_00),
            resolver_mark(resolver_event_type, "h_paired_leg", -50_000_00),
        ]
        spent = derive_budget_utilization(events, CATEGORY, MONTH)
        assert spent == 300_00, (
            f"{resolver_event_type} leg h_paired_leg must not count as spend: "
            f"expected 300_00, got {spent}"
        )

    def test_exclusion_independent_of_event_order(self) -> None:
        """Resolver event arriving before the ingested leg still excludes it."""
        events = [
            resolver_mark(MARKED_INTERNAL_TRANSFER, "h_transfer", -50_000_00),
            ingested("h_transfer", -50_000_00),
            ingested("h_lunch", -450_00),
        ]
        assert derive_budget_utilization(events, CATEGORY, MONTH) == 450_00

    def test_resolver_event_amount_itself_never_counted(self) -> None:
        """A resolver row carries amount_paise; it is a decision, not a spend event."""
        events = [
            ingested("h_lunch", -450_00),
            # category set so only event_type (not the category filter) can keep it out
            resolver_mark(MARKED_FD_BOOKING, "h_fd_not_in_stream", -1_00_000_00, category=CATEGORY),
        ]
        spent = derive_budget_utilization(events, CATEGORY, MONTH)
        assert spent == 450_00, (
            f"Resolver event amount leaked into spend: expected 450_00, got {spent}"
        )

    def test_duplicated_leg_and_duplicated_resolver_event_still_excluded(self) -> None:
        """Invariant 1 + 4 together: duplicates of an excluded leg stay excluded."""
        events = [
            ingested("h_cc_payment", self.CC_PAYMENT_PAISE),
            ingested("h_cc_payment", self.CC_PAYMENT_PAISE),
            resolver_mark(MARKED_CC_PAYMENT, "h_cc_payment", self.CC_PAYMENT_PAISE),
            resolver_mark(MARKED_CC_PAYMENT, "h_cc_payment", self.CC_PAYMENT_PAISE),
            ingested("h_restaurant", self.RESTAURANT_PAISE),
        ]
        assert derive_budget_utilization(events, CATEGORY, MONTH) == abs(self.RESTAURANT_PAISE)

    @given(
        counted=st.lists(st.integers(min_value=1, max_value=1_000_000_00), max_size=20),
        excluded=st.lists(st.integers(min_value=1, max_value=1_000_000_00), max_size=20),
        resolver_type=st.sampled_from(sorted(RESOLVER_EVENT_TYPES)),
    )
    @settings(max_examples=200)
    def test_property_excluded_legs_never_change_spend(
        self,
        counted: list[int],
        excluded: list[int],
        resolver_type: str,
    ) -> None:
        events: list[LedgerEvent] = [ingested(f"c_{i}", -amt) for i, amt in enumerate(counted)]
        for i, amt in enumerate(excluded):
            events.append(ingested(f"x_{i}", -amt))
            events.append(resolver_mark(resolver_type, f"x_{i}", -amt))

        spent = derive_budget_utilization(events, CATEGORY, MONTH)
        assert spent == sum(counted), (
            f"Spend over non-excluded legs is {sum(counted)} paise; utilization returned "
            f"{spent} with {len(excluded)} {resolver_type} legs present."
        )
