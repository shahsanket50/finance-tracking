"""Independent budget net-spend tests. Phase 3 Wave 5 (revision). PRD §4.3, §7.1; ADR-020/021/023.

Independent test-authoring (CLAUDE.md §6, TRD §11, PHASE_PROTOCOL §3). Written from PRD §4.3,
§7.1, TRD §10.2, DECISIONS B-4/ADR-020/021/023/024 and the contracts
(processing/budgets/contract.py, processing/exclusions.py, classifier/base.py) only. The
implementation (budgets/utilization.py, budgets/adapter.py, classifier/effective.py) was
not opened.

Every transaction row comes from real parser output (tests/factories/real_rows.py, ADR-024):
a synthetic statement is rendered to PDF, parsed by the production parser, and turned into
the exact TransactionIngested payload confirm() writes. Records reach the derivation through
the edge adapter budget_transactions_from_events. BudgetTransaction is constructed by hand
only for the corrupted-duplicate case, which real ingestion cannot produce.

Resolver exclusions come from the real matcher cascade (processing.resolver.pipeline,
no DB) and the real transactions_view projection (processing.exclusions).
"""

from __future__ import annotations

import dataclasses
import uuid
from collections.abc import Sequence
from datetime import UTC, date, datetime
from functools import cache
from typing import get_args

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from core.events.store import Event
from core.events.types import MARKED_CC_PAYMENT, MARKED_REVERSAL, TRANSACTION_INGESTED
from core.projections.builder import build_projection_from_events
from ingestion.parsers.base import ParsedStatement
from processing.budgets.contract import (
    BudgetTransaction,
    budget_transactions_from_events,
    derive_budget_utilization,
)
from processing.classifier.base import derive_effective_categories
from processing.classifier.categories import Category
from processing.classifier.events import CategoryCorrectedPayload, TransactionCategorizedPayload
from processing.exclusions import excluded_hashes_from_events
from processing.resolver.candidate import CandidateTxn
from processing.resolver.pipeline import _cascade_matchers
from tests.factories.real_rows import Txn, ingested_events, parse_statement

SAV_REF = "HDFC_SAV_9876"
CC_REF = "SBI_CC_8765"
SLICE_REF = "SLICE_SAV_4439"
USER = uuid.UUID("00000000-0000-0000-0000-0000000000a1")

JAN = date(2026, 1, 1)
FEB = date(2026, 2, 1)
MAR = date(2026, 3, 1)
APR = date(2026, 4, 1)

EXPENSE_CATEGORIES: tuple[Category, ...] = tuple(c for c in get_args(Category) if c != "income")


# ---------------------------------------------------------------------------
# Real-row helpers
# ---------------------------------------------------------------------------


@cache
def _parse(
    bank: str,
    account_ref: str,
    period_start: date,
    period_end: date,
    txns: tuple[Txn, ...],
    opening_balance_paise: int = 0,
) -> ParsedStatement:
    """parse_statement, cached: rendering + parsing a PDF is the slow part."""
    return parse_statement(bank, account_ref, period_start, period_end, txns, opening_balance_paise)


def _events(*statements: ParsedStatement) -> list[Event]:
    """TransactionIngested events for each statement, with increasing seq across statements."""
    out: list[Event] = []
    for statement in statements:
        out.extend(ingested_events(statement, user_id=USER, start_seq=len(out) + 1))
    return out


def _hash(statement: ParsedStatement, narration: str, occurrence_index: int = 0) -> str:
    matches = [
        t.idempotency_hash
        for t in statement.transactions
        if t.narration == narration and t.occurrence_index == occurrence_index
    ]
    assert len(matches) == 1, f"expected one parsed row {narration!r}#{occurrence_index}"
    return matches[0]


def _categorized(txn_hash: str, category: Category) -> TransactionCategorizedPayload:
    return TransactionCategorizedPayload(
        transaction_hash=txn_hash,
        category=category,
        method="rule",
        confidence_bps=9500,
        rule_id="test_rule",
        prompt_version=None,
        merchant_canonical="TEST MERCHANT",
    )


def _corrected(txn_hash: str, category: Category, prior: Category) -> CategoryCorrectedPayload:
    return CategoryCorrectedPayload(
        transaction_hash=txn_hash,
        category=category,
        prior_category=prior,
        merchant_canonical="TEST MERCHANT",
        corrected_by=str(USER),
    )


def _records(
    events: Sequence[Event],
    categorized: Sequence[TransactionCategorizedPayload] = (),
    corrections: Sequence[CategoryCorrectedPayload] = (),
) -> list[BudgetTransaction]:
    effective = derive_effective_categories(categorized, corrections)
    return budget_transactions_from_events(events, effective)


def _resolver_events(events: Sequence[Event]) -> list[Event]:
    """Run the real matcher cascade (no DB) over ingested events, as run_resolver does.

    Candidates are built from the TransactionIngested payload confirm() writes; each match
    becomes an event whose payload is the matcher's model_dump(), exactly as run_resolver
    persists it.
    """
    candidates = [
        CandidateTxn(
            idempotency_hash=str(e.payload["idempotency_hash"]),
            amount_paise=int(str(e.payload["amount_paise"])),
            value_date=date.fromisoformat(str(e.payload["value_date"])),
            account_type=str(e.payload["account_type"]),
        )
        for e in events
        if e.event_type == TRANSACTION_INGESTED
    ]
    next_seq = max((e.seq for e in events), default=0) + 1
    created = datetime(2026, 1, 2, tzinfo=UTC)
    return [
        Event(
            id=uuid.uuid4(),
            seq=next_seq + i,
            event_version=1,
            event_type=event_type,
            user_id=USER,
            aggregate_id="RESOLVER",
            payload=match.model_dump(),
            created_at=created,
        )
        for i, (event_type, _h1, _h2, match) in enumerate(_cascade_matchers(candidates, set()))
    ]


# ---------------------------------------------------------------------------
# Shared statements
# ---------------------------------------------------------------------------

# HDFC savings, January. Narrations avoid "Swiggy" (HdfcCcParser routing defect).
SAV_JAN = (
    Txn("NEFTCR SALARY COMPANY", 5_000_000, date(2026, 1, 1)),
    Txn("UPI COFFEE SHOP", -25_000, date(2026, 1, 10)),
    Txn("UPI COFFEE SHOP", -25_000, date(2026, 1, 10)),  # a genuine second ₹250 coffee
    Txn("UPI ZOMATO ORDER", -64_000, date(2026, 1, 15)),
    Txn("UPI BIGBASKET GROCERY", -320_000, date(2026, 1, 20)),
    Txn("UPI DMART GROCERY", -110_000, date(2026, 1, 31)),
)


def _sav_jan() -> ParsedStatement:
    return _parse("hdfc_savings", SAV_REF, JAN, date(2026, 1, 31), SAV_JAN, 1_000_000)


def _sav_jan_categorized() -> tuple[ParsedStatement, list[TransactionCategorizedPayload]]:
    s = _sav_jan()
    cats = [
        _categorized(_hash(s, "NEFTCR SALARY COMPANY"), "income"),
        _categorized(_hash(s, "UPI COFFEE SHOP", 0), "food_dining"),
        _categorized(_hash(s, "UPI COFFEE SHOP", 1), "food_dining"),
        _categorized(_hash(s, "UPI ZOMATO ORDER"), "food_dining"),
        _categorized(_hash(s, "UPI BIGBASKET GROCERY"), "groceries"),
        _categorized(_hash(s, "UPI DMART GROCERY"), "groceries"),
    ]
    return s, cats


# ---------------------------------------------------------------------------
# B2 basics
# ---------------------------------------------------------------------------


class TestNetSpendBasics:
    """PRD §4.3: net spend = −Σ signed amounts in (category, calendar month)."""

    def test_sums_category_in_month(self) -> None:
        s, cats = _sav_jan_categorized()
        records = _records(_events(s), cats)
        # 250 + 250 + 640 = ₹1,140
        assert derive_budget_utilization(records, frozenset(), "food_dining", JAN) == 114_000
        assert derive_budget_utilization(records, frozenset(), "groceries", JAN) == 430_000

    def test_other_categories_ignored(self) -> None:
        s, cats = _sav_jan_categorized()
        records = _records(_events(s), cats)
        assert derive_budget_utilization(records, frozenset(), "shopping", JAN) == 0
        assert derive_budget_utilization(records, frozenset(), "transport", JAN) == 0

    def test_result_is_int(self) -> None:
        s, cats = _sav_jan_categorized()
        records = _records(_events(s), cats)
        result = derive_budget_utilization(records, frozenset(), "food_dining", JAN)
        assert type(result) is int

    def test_empty_input_is_zero(self) -> None:
        result = derive_budget_utilization([], frozenset(), "food_dining", JAN)
        assert result == 0
        assert type(result) is int

    def test_other_month_is_zero(self) -> None:
        s, cats = _sav_jan_categorized()
        records = _records(_events(s), cats)
        assert derive_budget_utilization(records, frozenset(), "food_dining", FEB) == 0

    def test_month_boundary_jan31_feb1(self) -> None:
        jan = _parse(
            "hdfc_savings",
            SAV_REF,
            JAN,
            date(2026, 1, 31),
            (Txn("UPI ZOMATO ORDER", -40_000, date(2026, 1, 31)),),
            500_000,
        )
        feb = _parse(
            "hdfc_savings",
            SAV_REF,
            FEB,
            date(2026, 2, 28),
            (Txn("UPI DOMINOS PIZZA", -70_000, date(2026, 2, 1)),),
            460_000,
        )
        cats = [
            _categorized(jan.transactions[0].idempotency_hash, "food_dining"),
            _categorized(feb.transactions[0].idempotency_hash, "food_dining"),
        ]
        records = _records(_events(jan, feb), cats)
        assert derive_budget_utilization(records, frozenset(), "food_dining", JAN) == 40_000
        assert derive_budget_utilization(records, frozenset(), "food_dining", FEB) == 70_000

    def test_fy_boundary_mar31_apr1_by_value_date(self) -> None:
        """value_date is the IST calendar date the statement prints (CLAUDE.md §3.6)."""
        statement = _parse(
            "slice_savings",
            SLICE_REF,
            MAR,
            date(2026, 4, 30),
            (
                Txn("UPI-Debit-111111111-Uber Rides", -30_000, date(2026, 3, 31)),
                Txn("UPI-Debit-222222222-Ola Cabs", -45_000, date(2026, 4, 1)),
            ),
            200_000,
        )
        cats = [_categorized(t.idempotency_hash, "transport") for t in statement.transactions]
        records = _records(_events(statement), cats)
        assert derive_budget_utilization(records, frozenset(), "transport", MAR) == 30_000
        assert derive_budget_utilization(records, frozenset(), "transport", APR) == 45_000


# ---------------------------------------------------------------------------
# Invariant 1 — each hash counted once
# ---------------------------------------------------------------------------


class TestInvariant1Dedup:
    """CLAUDE.md §2 Invariant 1, PRD §7.2."""

    def test_same_statement_ingested_twice_counts_once(self) -> None:
        s, cats = _sav_jan_categorized()
        once = _records(_events(s), cats)
        twice = _records(_events(s, s), cats)
        assert len(twice) == 2 * len(once)
        for category in ("food_dining", "groceries"):
            assert derive_budget_utilization(
                twice, frozenset(), category, JAN
            ) == derive_budget_utilization(once, frozenset(), category, JAN)

    def test_two_genuine_identical_coffees_both_count(self) -> None:
        s = _sav_jan()
        first = _hash(s, "UPI COFFEE SHOP", 0)
        second = _hash(s, "UPI COFFEE SHOP", 1)
        assert first != second
        cats = [_categorized(first, "food_dining"), _categorized(second, "food_dining")]
        records = _records(_events(s), cats)
        assert derive_budget_utilization(records, frozenset(), "food_dining", JAN) == 50_000

    @given(picks=st.lists(st.integers(min_value=0, max_value=5), min_size=0, max_size=30))
    @settings(max_examples=150, deadline=None)
    def test_property_duplicates_never_change_net_spend(self, picks: list[int]) -> None:
        s, cats = _sav_jan_categorized()
        base = _records(_events(s), cats)
        duplicated = base + [base[i] for i in picks]
        for category in ("food_dining", "groceries", "income"):
            assert derive_budget_utilization(
                duplicated, frozenset(), category, JAN
            ) == derive_budget_utilization(base, frozenset(), category, JAN)

    @given(st.permutations(list(range(6))))
    @settings(max_examples=50, deadline=None)
    def test_property_order_does_not_matter(self, order: list[int]) -> None:
        s, cats = _sav_jan_categorized()
        base = _records(_events(s), cats)
        shuffled = [base[i] for i in order]
        assert derive_budget_utilization(
            shuffled, frozenset(), "food_dining", JAN
        ) == derive_budget_utilization(base, frozenset(), "food_dining", JAN)

    def test_corrupted_duplicate_raises(self) -> None:
        """Same hash, different amount: real ingestion can't produce this, so build it."""
        s, cats = _sav_jan_categorized()
        records = _records(_events(s), cats)
        coffee = next(r for r in records if r.amount_paise == -25_000)
        corrupted = dataclasses.replace(coffee, amount_paise=-26_000)
        with pytest.raises(ValueError):
            derive_budget_utilization([*records, corrupted], frozenset(), "food_dining", JAN)

    def test_corrupted_duplicate_other_date_raises(self) -> None:
        s, cats = _sav_jan_categorized()
        records = _records(_events(s), cats)
        coffee = next(r for r in records if r.amount_paise == -25_000)
        corrupted = dataclasses.replace(coffee, value_date=date(2026, 1, 11))
        with pytest.raises(ValueError):
            derive_budget_utilization([*records, corrupted], frozenset(), "food_dining", JAN)


# ---------------------------------------------------------------------------
# Invariant 4 — resolver-paired legs never count
# ---------------------------------------------------------------------------

CC_PAYMENT_SAV = (
    Txn("NEFTCR SALARY COMPANY", 5_000_000, date(2026, 1, 1)),
    Txn("CC PAYMENT SBI CARD", -1_500_000, date(2026, 1, 28)),
    Txn("UPI BIGBASKET GROCERY", -320_000, date(2026, 1, 20)),
)
CC_PAYMENT_CARD = (
    Txn("GROCERY STORE BIG BAZAAR", -55_000, date(2026, 1, 3)),
    Txn("AMAZON SHOPPING", -199_900, date(2026, 1, 12)),
    Txn("AMAZON REVERSAL", 199_900, date(2026, 1, 13)),
    Txn("PAYMENT RECEIVED THANK YOU", 1_500_000, date(2026, 1, 29)),
)


def _cc_payment_world() -> tuple[ParsedStatement, ParsedStatement, list[Event]]:
    sav = _parse("hdfc_savings", SAV_REF, JAN, date(2026, 1, 31), CC_PAYMENT_SAV, 1_000_000)
    card = _parse("sbi_cc", CC_REF, JAN, date(2026, 1, 31), CC_PAYMENT_CARD, -1_500_000)
    ingested = _events(sav, card)
    return sav, card, ingested + _resolver_events(ingested)


class TestInvariant4Exclusion:
    """CLAUDE.md §2 Invariant 4, PRD §7.1, ADR-023."""

    def test_every_excluded_hash_is_excluded(self) -> None:
        s, cats = _sav_jan_categorized()
        records = _records(_events(s), cats)
        excluded = frozenset({_hash(s, "UPI ZOMATO ORDER"), _hash(s, "UPI COFFEE SHOP", 1)})
        assert derive_budget_utilization(records, excluded, "food_dining", JAN) == 25_000

    def test_excluding_unknown_hash_is_harmless(self) -> None:
        s, cats = _sav_jan_categorized()
        records = _records(_events(s), cats)
        assert derive_budget_utilization(
            records, frozenset({"0" * 64}), "food_dining", JAN
        ) == derive_budget_utilization(records, frozenset(), "food_dining", JAN)

    def test_real_resolver_cc_payment_legs_are_excluded(self) -> None:
        sav, card, events = _cc_payment_world()
        debit_leg = _hash(sav, "CC PAYMENT SBI CARD")
        credit_leg = _hash(card, "PAYMENT RECEIVED THANK YOU")

        cc_events = [e for e in events if e.event_type == MARKED_CC_PAYMENT]
        assert len(cc_events) == 1, "real cc_payment matcher must pair the bill payment"
        excluded = excluded_hashes_from_events(events)
        assert {debit_leg, credit_leg} <= excluded

        # A naive classifier put the bill payment in "other" and the card credit in "shopping".
        cats = [
            _categorized(debit_leg, "other"),
            _categorized(credit_leg, "shopping"),
            _categorized(_hash(card, "GROCERY STORE BIG BAZAAR"), "groceries"),
            _categorized(_hash(sav, "UPI BIGBASKET GROCERY"), "groceries"),
        ]
        records = _records(events, cats)
        assert derive_budget_utilization(records, frozenset(), "other", JAN) == 1_500_000
        assert derive_budget_utilization(records, excluded, "other", JAN) == 0
        assert derive_budget_utilization(records, excluded, "shopping", JAN) == 0
        assert derive_budget_utilization(records, excluded, "groceries", JAN) == 375_000

    def test_real_resolver_reversal_legs_are_excluded(self) -> None:
        _sav, card, events = _cc_payment_world()
        original = _hash(card, "AMAZON SHOPPING")
        reversal = _hash(card, "AMAZON REVERSAL")

        rev_events = [e for e in events if e.event_type == MARKED_REVERSAL]
        assert len(rev_events) == 1, "real reversal matcher must pair the card reversal"
        excluded = excluded_hashes_from_events(events)
        assert {original, reversal} <= excluded

        cats = [_categorized(original, "shopping"), _categorized(reversal, "shopping")]
        records = _records(events, cats)
        assert derive_budget_utilization(records, excluded, "shopping", JAN) == 0
        # Only the debit leg categorized: without exclusion it would count as spend.
        only_debit = _records(events, [_categorized(original, "shopping")])
        assert derive_budget_utilization(only_debit, frozenset(), "shopping", JAN) == 199_900
        assert derive_budget_utilization(only_debit, excluded, "shopping", JAN) == 0

    def test_resolver_rows_own_hash_is_not_a_leg(self) -> None:
        """ADR-023: the exclusion set holds payload leg hashes only."""
        _sav, _card, events = _cc_payment_world()
        excluded = excluded_hashes_from_events(events)
        ingested = {
            str(e.payload["idempotency_hash"])
            for e in events
            if e.event_type == TRANSACTION_INGESTED
        }
        assert excluded <= ingested


# ---------------------------------------------------------------------------
# Refunds and income
# ---------------------------------------------------------------------------


class TestRefundsAndIncome:
    """PRD §4.3 / ADR-020: refunds net in the month they post; income never reduces a budget."""

    def test_refund_same_month_nets(self) -> None:
        s = _parse(
            "slice_savings",
            SLICE_REF,
            date(2026, 5, 1),
            date(2026, 5, 31),
            (
                Txn("UPI-Debit-987654321-Myntra", -300_000, date(2026, 5, 3)),
                Txn("UPI-Credit-123456789-Myntra", 120_000, date(2026, 5, 20)),
            ),
            500_000,
        )
        cats = [_categorized(t.idempotency_hash, "shopping") for t in s.transactions]
        records = _records(_events(s), cats)
        assert derive_budget_utilization(records, frozenset(), "shopping", date(2026, 5, 1)) == (
            180_000
        )

    def test_refund_in_later_month_reduces_later_month_only(self) -> None:
        may = _parse(
            "slice_savings",
            SLICE_REF,
            date(2026, 5, 1),
            date(2026, 5, 31),
            (Txn("UPI-Debit-987654321-Myntra", -300_000, date(2026, 5, 3)),),
            500_000,
        )
        june = _parse(
            "slice_savings",
            SLICE_REF,
            date(2026, 6, 1),
            date(2026, 6, 30),
            (
                Txn("UPI-Debit-555555555-Ajio", -50_000, date(2026, 6, 4)),
                Txn("UPI-Credit-123456789-Myntra", 120_000, date(2026, 6, 10)),
            ),
            200_000,
        )
        cats = [
            _categorized(t.idempotency_hash, "shopping")
            for s in (may, june)
            for t in s.transactions
        ]
        records = _records(_events(may, june), cats)
        assert derive_budget_utilization(records, frozenset(), "shopping", date(2026, 5, 1)) == (
            300_000
        )
        assert derive_budget_utilization(records, frozenset(), "shopping", date(2026, 6, 1)) == (
            -70_000
        )

    def test_net_refund_is_negative_and_unclamped(self) -> None:
        s = _parse(
            "slice_savings",
            SLICE_REF,
            date(2026, 7, 1),
            date(2026, 7, 31),
            (Txn("UPI-Credit-123456789-Myntra", 250_000, date(2026, 7, 2)),),
            0,
        )
        records = _records(
            _events(s), [_categorized(s.transactions[0].idempotency_hash, "shopping")]
        )
        assert derive_budget_utilization(records, frozenset(), "shopping", date(2026, 7, 1)) == (
            -250_000
        )

    @pytest.mark.parametrize("salary_category", ["income", None])
    def test_salary_credit_never_changes_any_expense_budget(
        self, salary_category: Category | None
    ) -> None:
        s, cats = _sav_jan_categorized()
        salary = _hash(s, "NEFTCR SALARY COMPANY")
        others = [c for c in cats if c.transaction_hash != salary]
        with_salary = others + (
            [_categorized(salary, salary_category)] if salary_category is not None else []
        )
        records = _records(_events(s), with_salary)
        without_salary = [r for r in records if r.idempotency_hash != salary]
        for category in EXPENSE_CATEGORIES:
            assert derive_budget_utilization(
                records, frozenset(), category, JAN
            ) == derive_budget_utilization(without_salary, frozenset(), category, JAN), category


# ---------------------------------------------------------------------------
# Effective category (correction → classifier → none)
# ---------------------------------------------------------------------------


class TestEffectiveCategory:
    """PRD §4.3, ADR-020: derive_effective_categories precedence."""

    def test_correction_beats_classifier(self) -> None:
        h = _hash(_sav_jan(), "UPI ZOMATO ORDER")
        effective = derive_effective_categories(
            [_categorized(h, "groceries")], [_corrected(h, "food_dining", "groceries")]
        )
        assert effective[h] == "food_dining"

    def test_correction_beats_later_classifier(self) -> None:
        h = _hash(_sav_jan(), "UPI ZOMATO ORDER")
        effective = derive_effective_categories(
            [_categorized(h, "groceries"), _categorized(h, "shopping")],
            [_corrected(h, "food_dining", "groceries")],
        )
        assert effective[h] == "food_dining"

    def test_latest_correction_wins(self) -> None:
        h = _hash(_sav_jan(), "UPI ZOMATO ORDER")
        effective = derive_effective_categories(
            [_categorized(h, "groceries")],
            [_corrected(h, "food_dining", "groceries"), _corrected(h, "shopping", "food_dining")],
        )
        assert effective[h] == "shopping"

    def test_latest_categorization_wins_without_correction(self) -> None:
        h = _hash(_sav_jan(), "UPI ZOMATO ORDER")
        effective = derive_effective_categories(
            [_categorized(h, "groceries"), _categorized(h, "food_dining")], []
        )
        assert effective[h] == "food_dining"

    def test_absent_hash_is_absent(self) -> None:
        s = _sav_jan()
        h = _hash(s, "UPI ZOMATO ORDER")
        other = _hash(s, "UPI DMART GROCERY")
        effective = derive_effective_categories([_categorized(h, "food_dining")], [])
        assert other not in effective
        records = _records(_events(s), [_categorized(h, "food_dining")])
        by_hash = {r.idempotency_hash: r for r in records}
        assert by_hash[other].effective_category is None
        assert by_hash[h].effective_category == "food_dining"

    def test_correction_moves_spend_between_budgets(self) -> None:
        s, cats = _sav_jan_categorized()
        zomato = _hash(s, "UPI ZOMATO ORDER")
        records = _records(_events(s), cats, [_corrected(zomato, "entertainment", "food_dining")])
        assert derive_budget_utilization(records, frozenset(), "food_dining", JAN) == 50_000
        assert derive_budget_utilization(records, frozenset(), "entertainment", JAN) == 64_000


# ---------------------------------------------------------------------------
# Edge adapter
# ---------------------------------------------------------------------------


class TestAdapter:
    """Contract: budget_transactions_from_events(events, effective_categories)."""

    def test_ignores_non_ingested_events(self) -> None:
        sav, card, events = _cc_payment_world()
        ingested = [e for e in events if e.event_type == TRANSACTION_INGESTED]
        assert len(ingested) < len(events), "world must contain resolver events"
        records = budget_transactions_from_events(events, {})
        assert len(records) == len(ingested) == len(sav.transactions) + len(card.transactions)

    def test_keeps_order_and_parser_values(self) -> None:
        sav, card, _ = _cc_payment_world()
        events = _events(sav, card)
        records = budget_transactions_from_events(events, {})
        parsed = [*sav.transactions, *card.transactions]
        assert [r.idempotency_hash for r in records] == [t.idempotency_hash for t in parsed]
        assert [r.amount_paise for r in records] == [t.amount_paise for t in parsed]
        assert [r.value_date for r in records] == [t.value_date for t in parsed]

    def test_value_date_is_date_and_amount_is_signed_int(self) -> None:
        sav, card, _ = _cc_payment_world()
        records = budget_transactions_from_events(_events(sav, card), {})
        for r in records:
            assert type(r.value_date) is date
            assert type(r.amount_paise) is int
            assert r.amount_paise != 0
        # B-5 / TRD §10.2: card purchases are negative, the bill payment credit positive.
        by_hash = {r.idempotency_hash: r for r in records}
        assert by_hash[_hash(card, "GROCERY STORE BIG BAZAAR")].amount_paise == -55_000
        assert by_hash[_hash(card, "PAYMENT RECEIVED THANK YOU")].amount_paise == 1_500_000
        assert by_hash[_hash(sav, "CC PAYMENT SBI CARD")].amount_paise == -1_500_000

    def test_does_not_deduplicate(self) -> None:
        s = _sav_jan()
        records = budget_transactions_from_events(_events(s, s), {})
        assert len(records) == 2 * len(s.transactions)

    def test_effective_category_lookup(self) -> None:
        s = _sav_jan()
        h = _hash(s, "UPI ZOMATO ORDER")
        records = budget_transactions_from_events(_events(s), {h: "food_dining"})
        assert [r.effective_category for r in records if r.idempotency_hash == h] == ["food_dining"]
        assert all(r.effective_category is None for r in records if r.idempotency_hash != h)

    def test_transaction_type_is_not_a_record_field(self) -> None:
        """ADR-021: the sign is the only direction signal."""
        names = {f.name for f in dataclasses.fields(BudgetTransaction)}
        assert names == {"idempotency_hash", "amount_paise", "value_date", "effective_category"}


# ---------------------------------------------------------------------------
# Reconciliation with transactions_view (blocked by B-4)
# ---------------------------------------------------------------------------


@pytest.mark.xfail(
    strict=True,
    reason=(
        "B-4: transactions_view expense total reads transaction_type 'expense' but ingestion "
        "writes 'debit'/'credit' (DECISIONS.md B-4); fix in Phase 3 Wave 6"
    ),
)
def test_category_net_spend_reconciles_with_transactions_view() -> None:
    """Σ category net spend + uncategorized debit spend == transactions_view expense_paise.

    Scenario has no credits in expense categories, so expense_paise is unambiguous.
    """
    sav, card, events = _cc_payment_world()
    cats = [
        _categorized(_hash(sav, "NEFTCR SALARY COMPANY"), "income"),
        _categorized(_hash(sav, "UPI BIGBASKET GROCERY"), "groceries"),
        # GROCERY STORE BIG BAZAAR stays uncategorized (₹550 of uncategorized debit spend).
        # AMAZON SHOPPING/REVERSAL and the CC payment legs are resolver-excluded;
        # categorize one excluded leg to prove exclusion applies on both sides.
        _categorized(_hash(card, "AMAZON SHOPPING"), "shopping"),
    ]
    records = _records(events, cats)
    excluded = excluded_hashes_from_events(events)
    categorized_spend = sum(
        derive_budget_utilization(records, excluded, category, JAN)
        for category in EXPENSE_CATEGORIES
    )
    seen: set[str] = set()
    uncategorized_spend = 0
    for r in records:
        if r.idempotency_hash in seen or r.idempotency_hash in excluded:
            continue
        seen.add(r.idempotency_hash)
        if r.effective_category is None and r.amount_paise < 0:
            uncategorized_spend -= r.amount_paise

    state = build_projection_from_events(list(events), "transactions_view")
    totals = state["totals"]
    assert isinstance(totals, dict)
    assert categorized_spend == 320_000
    assert uncategorized_spend == 55_000
    assert categorized_spend + uncategorized_spend == totals["expense_paise"]
