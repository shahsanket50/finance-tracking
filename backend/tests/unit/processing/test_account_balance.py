"""Account balance derivation unit tests. PRD §8.1, §7.1; ADR-022; defects B-5, B-6.

Independent test-authoring (CLAUDE.md §6, TRD §11, PHASE_PROTOCOL §3). Revised in Phase 3
Wave 5 from the spec and processing/accounts/contract.py only; balance.py, adapter.py and
the routers were not opened.

Balances are statement-anchored (ADR-022): closing balance of the latest statement plus the
signed legs dated after its period end, each hash once, ALL legs counted (resolver-paired
legs included). No anchor → None, never 0. Card liability = −anchored balance, unclamped.

Every leg comes from real parser output via tests/factories/real_rows.py (ADR-024) and the
balance_legs_from_events edge adapter; anchors come from the parsed statement's
account_ref, period_end and closing_balance_paise. BalanceLeg is built by hand only for the
float-amount case, which real ingestion cannot produce.
"""

from __future__ import annotations

import dataclasses
import uuid
from collections.abc import Sequence
from datetime import date
from functools import cache
from pathlib import Path

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from core.events.store import Event
from core.events.types import MARKED_CC_PAYMENT
from ingestion.parsers.base import ParsedStatement
from processing.accounts.balance import BalanceSummary
from processing.accounts.contract import (
    BalanceLeg,
    StatementAnchor,
    balance_legs_from_events,
    derive_cc_outstanding_liability,
    derive_savings_balance,
)
from processing.resolver.candidate import CandidateTxn
from processing.resolver.pipeline import _cascade_matchers
from tests.factories.real_rows import Txn, ingested_events, parse_pdf, parse_statement

GOLDEN_DIR = Path(__file__).parents[2] / "fixtures" / "golden"
USER = uuid.UUID("00000000-0000-0000-0000-0000000000b2")
SAV_REF = "HDFC_SAV_9876"
CC_REF = "SBI_CC_8765"


@cache
def _parse(
    bank: str,
    account_ref: str,
    period_start: date,
    period_end: date,
    txns: tuple[Txn, ...],
    opening_balance_paise: int = 0,
) -> ParsedStatement:
    return parse_statement(bank, account_ref, period_start, period_end, txns, opening_balance_paise)


def _events(*statements: ParsedStatement) -> list[Event]:
    out: list[Event] = []
    for statement in statements:
        out.extend(ingested_events(statement, user_id=USER, start_seq=len(out) + 1))
    return out


def _anchor(statement: ParsedStatement) -> StatementAnchor:
    return StatementAnchor(
        account_ref=statement.account_ref,
        period_end=statement.period_end,
        closing_balance_paise=statement.closing_balance_paise,
    )


def _legs(account_ref: str, *statements: ParsedStatement) -> list[BalanceLeg]:
    return balance_legs_from_events(_events(*statements), account_ref)


def _hash(statement: ParsedStatement, narration: str) -> str:
    matches = [t.idempotency_hash for t in statement.transactions if t.narration == narration]
    assert len(matches) == 1, narration
    return matches[0]


# ---------------------------------------------------------------------------
# Statements (real parser output)
# ---------------------------------------------------------------------------

DEC_OPENING = 2_000_000


def _sav_dec() -> ParsedStatement:
    """HDFC savings, Dec 2025: closes at ₹19,000 (the January opening)."""
    return _parse(
        "hdfc_savings",
        SAV_REF,
        date(2025, 12, 1),
        date(2025, 12, 31),
        (Txn("UPI DMART GROCERY", -100_000, date(2025, 12, 15)),),
        DEC_OPENING,
    )


# AC7 (B-6 corrected): salary +₹50,000, CC bill payment −₹15,000, grocery −₹3,200.
AC7_OPENING = 1_900_000
AC7_TXNS = (
    Txn("NEFTCR SALARY COMPANY", 5_000_000, date(2026, 1, 1)),
    Txn("UPI BIGBASKET GROCERY", -320_000, date(2026, 1, 20)),
    Txn("CC PAYMENT SBI CARD", -1_500_000, date(2026, 1, 28)),
)


def _sav_jan() -> ParsedStatement:
    return _parse(
        "hdfc_savings", SAV_REF, date(2026, 1, 1), date(2026, 1, 31), AC7_TXNS, AC7_OPENING
    )


def _card_jan() -> ParsedStatement:
    """SBI card, Jan 2026: owes ₹15,000 at open, buys ₹550, pays ₹15,000 → owes ₹550."""
    return _parse(
        "sbi_cc",
        CC_REF,
        date(2026, 1, 1),
        date(2026, 1, 31),
        (
            Txn("GROCERY STORE BIG BAZAAR", -55_000, date(2026, 1, 3)),
            Txn("PAYMENT RECEIVED THANK YOU", 1_500_000, date(2026, 1, 29)),
        ),
        -1_500_000,
    )


def _card_feb() -> ParsedStatement:
    return _parse(
        "sbi_cc",
        CC_REF,
        date(2026, 2, 1),
        date(2026, 2, 28),
        (
            Txn("FUEL PUMP HPCL", -40_000, date(2026, 2, 10)),
            Txn("NETFLIX SUBSCRIPTION", -64_900, date(2026, 2, 18)),
        ),
        -55_000,
    )


# ---------------------------------------------------------------------------
# Savings: anchor rule
# ---------------------------------------------------------------------------


class TestSavingsAnchoredBalance:
    """PRD §8.1, ADR-022: anchored_balance = closing + Σ later legs (each hash once)."""

    def test_equals_statement_closing_with_no_later_legs(self) -> None:
        jan = _sav_jan()
        result = derive_savings_balance(SAV_REF, "savings", _anchor(jan), _legs(SAV_REF, jan))
        assert result.derived_balance_paise == jan.closing_balance_paise

    def test_equals_closing_with_no_legs_at_all(self) -> None:
        jan = _sav_jan()
        result = derive_savings_balance(SAV_REF, "savings", _anchor(jan), [])
        assert result.derived_balance_paise == jan.closing_balance_paise

    def test_later_legs_added_earlier_legs_ignored(self) -> None:
        dec, jan = _sav_dec(), _sav_jan()
        legs = _legs(SAV_REF, dec, jan)  # Dec legs are inside the Dec closing balance
        result = derive_savings_balance(SAV_REF, "savings", _anchor(dec), legs)
        expected = dec.closing_balance_paise + sum(t.amount_paise for t in jan.transactions)
        assert result.derived_balance_paise == expected
        # The chain reconciles to the next statement's printed closing balance.
        assert result.derived_balance_paise == jan.closing_balance_paise

    def test_leg_on_period_end_is_ignored(self) -> None:
        statement = _parse(
            "hdfc_savings",
            SAV_REF,
            date(2026, 3, 1),
            date(2026, 3, 31),
            (
                Txn("UPI ZOMATO ORDER", -40_000, date(2026, 3, 30)),
                Txn("UPI DMART GROCERY", -90_000, date(2026, 3, 31)),
            ),
            700_000,
        )
        result = derive_savings_balance(
            SAV_REF, "savings", _anchor(statement), _legs(SAV_REF, statement)
        )
        assert result.derived_balance_paise == statement.closing_balance_paise == 570_000

    def test_duplicate_hash_counted_once(self) -> None:
        dec, jan = _sav_dec(), _sav_jan()
        once = derive_savings_balance(SAV_REF, "savings", _anchor(dec), _legs(SAV_REF, dec, jan))
        twice = derive_savings_balance(
            SAV_REF, "savings", _anchor(dec), _legs(SAV_REF, dec, jan, jan)
        )
        assert twice.derived_balance_paise == once.derived_balance_paise

    def test_no_anchor_is_none_not_zero(self) -> None:
        jan = _sav_jan()
        result = derive_savings_balance(SAV_REF, "savings", None, _legs(SAV_REF, jan))
        assert result.derived_balance_paise is None
        assert result.outstanding_liability_paise is None

    def test_no_anchor_and_no_legs_is_none(self) -> None:
        result = derive_savings_balance(SAV_REF, "savings", None, [])
        assert result.derived_balance_paise is None

    def test_result_shape(self) -> None:
        jan = _sav_jan()
        result = derive_savings_balance(SAV_REF, "savings", _anchor(jan), _legs(SAV_REF, jan))
        assert isinstance(result, BalanceSummary)
        assert result.account_ref == SAV_REF
        assert result.account_type == "savings"
        assert result.outstanding_liability_paise is None
        assert type(result.derived_balance_paise) is int

    def test_current_account_accepted(self) -> None:
        jan = _sav_jan()
        result = derive_savings_balance(SAV_REF, "current", _anchor(jan), _legs(SAV_REF, jan))
        assert result.account_type == "current"
        assert result.derived_balance_paise == jan.closing_balance_paise


class TestGuards:
    """Contract guards: account match, int-only amounts, account type."""

    def test_anchor_for_other_account_raises(self) -> None:
        with pytest.raises(ValueError):
            derive_savings_balance(
                SAV_REF, "savings", _anchor(_card_jan()), _legs(SAV_REF, _sav_jan())
            )

    def test_cc_anchor_for_other_account_raises(self) -> None:
        with pytest.raises(ValueError):
            derive_cc_outstanding_liability(CC_REF, _anchor(_sav_jan()), _legs(CC_REF, _card_jan()))

    def test_float_leg_amount_raises_type_error(self) -> None:
        dec, jan = _sav_dec(), _sav_jan()
        legs = _legs(SAV_REF, dec, jan)
        later = next(leg for leg in legs if leg.value_date > dec.period_end)
        bad = dataclasses.replace(later, amount_paise=float(later.amount_paise))  # type: ignore[arg-type]
        with pytest.raises(TypeError):
            derive_savings_balance(SAV_REF, "savings", _anchor(dec), [*legs, bad])

    def test_float_leg_amount_raises_type_error_for_card(self) -> None:
        jan = _card_jan()
        legs = _legs(CC_REF, jan, _card_feb())
        later = next(leg for leg in legs if leg.value_date > jan.period_end)
        bad = dataclasses.replace(later, amount_paise=float(later.amount_paise))  # type: ignore[arg-type]
        with pytest.raises(TypeError):
            derive_cc_outstanding_liability(CC_REF, _anchor(jan), [bad])

    @pytest.mark.parametrize("account_type", ["credit_card", "investment", "fd"])
    def test_savings_function_rejects_non_savings_types(self, account_type: str) -> None:
        jan = _sav_jan()
        with pytest.raises(ValueError):
            derive_savings_balance(SAV_REF, account_type, _anchor(jan), _legs(SAV_REF, jan))


# ---------------------------------------------------------------------------
# Edge adapter: balance_legs_from_events
# ---------------------------------------------------------------------------


class TestBalanceLegsAdapter:
    def test_filters_by_account_and_keeps_parser_values(self) -> None:
        sav, card = _sav_jan(), _card_jan()
        legs = balance_legs_from_events(_events(sav, card), SAV_REF)
        assert [leg.idempotency_hash for leg in legs] == [
            t.idempotency_hash for t in sav.transactions
        ]
        assert [leg.amount_paise for leg in legs] == [t.amount_paise for t in sav.transactions]
        assert all(type(leg.value_date) is date for leg in legs)
        assert all(type(leg.amount_paise) is int for leg in legs)

    def test_no_dedup(self) -> None:
        sav = _sav_jan()
        legs = balance_legs_from_events(_events(sav, sav), SAV_REF)
        assert len(legs) == 2 * len(sav.transactions)

    def test_unknown_account_has_no_legs(self) -> None:
        assert balance_legs_from_events(_events(_sav_jan(), _card_jan()), "AXIS_SAV_0000") == []


# ---------------------------------------------------------------------------
# Card liability (B-5): real CC parser output, purchases negative
# ---------------------------------------------------------------------------


class TestCardLiability:
    """PRD §8.1, ADR-022, B-5: outstanding = −anchored signed balance, unclamped."""

    def test_golden_sbi_cc_purchases_are_negative_and_liability_positive(self) -> None:
        golden = parse_pdf((GOLDEN_DIR / "sbi_cc" / "statement_001.pdf").read_bytes())
        assert all(t.amount_paise < 0 for t in golden.transactions)
        events = ingested_events(golden, user_id=USER)
        legs = balance_legs_from_events(events, golden.account_ref)
        result = derive_cc_outstanding_liability(golden.account_ref, _anchor(golden), legs)
        assert golden.closing_balance_paise < 0
        assert result.outstanding_liability_paise == -golden.closing_balance_paise
        assert result.outstanding_liability_paise is not None
        assert result.outstanding_liability_paise > 0

    def test_liability_after_payment_credit(self) -> None:
        jan = _card_jan()
        result = derive_cc_outstanding_liability(CC_REF, _anchor(jan), _legs(CC_REF, jan))
        # owed ₹15,000 + ₹550 purchase − ₹15,000 payment = ₹550 owed
        assert result.outstanding_liability_paise == 55_000

    def test_later_purchases_raise_liability(self) -> None:
        jan, feb = _card_jan(), _card_feb()
        result = derive_cc_outstanding_liability(CC_REF, _anchor(jan), _legs(CC_REF, jan, feb))
        assert result.outstanding_liability_paise == 55_000 + 40_000 + 64_900
        assert result.outstanding_liability_paise == -feb.closing_balance_paise

    def test_overpaid_card_is_negative_liability(self) -> None:
        card = _parse(
            "sbi_cc",
            CC_REF,
            date(2026, 3, 1),
            date(2026, 3, 31),
            (Txn("PAYMENT RECEIVED THANK YOU", 800_000, date(2026, 3, 5)),),
            -500_000,
        )
        assert card.closing_balance_paise == 300_000
        result = derive_cc_outstanding_liability(CC_REF, _anchor(card), _legs(CC_REF, card))
        assert result.outstanding_liability_paise == -300_000

    def test_no_anchor_is_none(self) -> None:
        result = derive_cc_outstanding_liability(CC_REF, None, _legs(CC_REF, _card_jan()))
        assert result.outstanding_liability_paise is None
        assert result.derived_balance_paise is None

    def test_result_shape(self) -> None:
        jan = _card_jan()
        result = derive_cc_outstanding_liability(CC_REF, _anchor(jan), _legs(CC_REF, jan))
        assert isinstance(result, BalanceSummary)
        assert result.account_ref == CC_REF
        assert result.account_type == "credit_card"
        assert result.derived_balance_paise is None
        assert type(result.outstanding_liability_paise) is int


# ---------------------------------------------------------------------------
# AC7 corrected (B-6): resolver-paired legs DO count in balances
# ---------------------------------------------------------------------------


def _cascade_pairs(events: Sequence[Event]) -> list[tuple[str, str, str]]:
    """Real resolver matcher cascade (no DB) over ingested payloads."""
    candidates = [
        CandidateTxn(
            idempotency_hash=str(e.payload["idempotency_hash"]),
            amount_paise=int(str(e.payload["amount_paise"])),
            value_date=date.fromisoformat(str(e.payload["value_date"])),
            account_type=str(e.payload["account_type"]),
        )
        for e in events
    ]
    return [(t, h1, h2) for t, h1, h2, _ in _cascade_matchers(candidates, set())]


class TestAC7ResolverPairedLegsCountInBalance:
    """B-6: the savings balance is the statement's ₹31,800 net movement, not ₹46,800."""

    def test_ac7_balance_is_opening_plus_31800(self) -> None:
        dec, jan = _sav_dec(), _sav_jan()
        assert dec.closing_balance_paise == AC7_OPENING == jan.opening_balance_paise

        # The CC bill payment debit really is resolver-paired with the card credit.
        payment = _hash(jan, "CC PAYMENT SBI CARD")
        card_credit = _hash(_card_jan(), "PAYMENT RECEIVED THANK YOU")
        pairs = _cascade_pairs(_events(jan, _card_jan()))
        assert (MARKED_CC_PAYMENT, payment, card_credit) in pairs

        result = derive_savings_balance(SAV_REF, "savings", _anchor(dec), _legs(SAV_REF, dec, jan))
        assert result.derived_balance_paise == AC7_OPENING + 3_180_000
        assert result.derived_balance_paise == jan.closing_balance_paise
        assert result.derived_balance_paise != AC7_OPENING + 4_680_000

    def test_ac7_card_liability_counts_paired_payment_credit(self) -> None:
        jan = _card_jan()
        prior = _parse(
            "sbi_cc",
            CC_REF,
            date(2025, 12, 1),
            date(2025, 12, 31),
            (Txn("AMAZON SHOPPING", -1_500_000, date(2025, 12, 10)),),
            0,
        )
        result = derive_cc_outstanding_liability(CC_REF, _anchor(prior), _legs(CC_REF, prior, jan))
        # ₹15,000 owed − ₹15,000 paired payment + ₹550 purchase
        assert result.outstanding_liability_paise == 55_000


# ---------------------------------------------------------------------------
# Formulas are distinct
# ---------------------------------------------------------------------------


class TestFormulasAreDistinct:
    def test_fields_are_mutually_exclusive(self) -> None:
        sav, card = _sav_jan(), _card_jan()
        s = derive_savings_balance(SAV_REF, "savings", _anchor(sav), _legs(SAV_REF, sav))
        c = derive_cc_outstanding_liability(CC_REF, _anchor(card), _legs(CC_REF, card))
        assert s.derived_balance_paise is not None and s.outstanding_liability_paise is None
        assert c.outstanding_liability_paise is not None and c.derived_balance_paise is None

    def test_card_liability_is_negated_balance(self) -> None:
        card = _card_jan()
        c = derive_cc_outstanding_liability(CC_REF, _anchor(card), _legs(CC_REF, card))
        assert c.outstanding_liability_paise == -card.closing_balance_paise


# ---------------------------------------------------------------------------
# AC5 — BalanceSummary is immutable (unchanged)
# ---------------------------------------------------------------------------


class TestBalanceSummaryIsImmutable:
    """AC5: BalanceSummary is a frozen dataclass — field assignment raises."""

    def test_frozen_dataclass_raises_on_assignment(self) -> None:
        summary = BalanceSummary(
            account_ref="HDFC_1234",
            account_type="savings",
            derived_balance_paise=100_00,
            outstanding_liability_paise=None,
        )
        with pytest.raises((dataclasses.FrozenInstanceError, AttributeError, TypeError)):
            summary.derived_balance_paise = 999_00  # type: ignore[misc]


# ---------------------------------------------------------------------------
# AC6 — int only, dedup holds for any duplication of real legs (property)
# ---------------------------------------------------------------------------


class TestPropertyAnchoredBalance:
    @given(picks=st.lists(st.integers(min_value=0, max_value=3), max_size=25))
    @settings(max_examples=150, deadline=None)
    def test_savings_balance_is_int_and_dedup_invariant(self, picks: list[int]) -> None:
        dec, jan = _sav_dec(), _sav_jan()
        legs = _legs(SAV_REF, dec, jan)
        assert len(legs) == 4
        noisy = legs + [legs[i] for i in picks]
        result = derive_savings_balance(SAV_REF, "savings", _anchor(dec), noisy)
        assert type(result.derived_balance_paise) is int
        assert result.derived_balance_paise == jan.closing_balance_paise

    @given(picks=st.lists(st.integers(min_value=0, max_value=3), max_size=25))
    @settings(max_examples=150, deadline=None)
    def test_card_liability_is_int_and_dedup_invariant(self, picks: list[int]) -> None:
        jan, feb = _card_jan(), _card_feb()
        legs = _legs(CC_REF, jan, feb)
        assert len(legs) == 4
        noisy = legs + [legs[i] for i in picks]
        result = derive_cc_outstanding_liability(CC_REF, _anchor(jan), noisy)
        assert type(result.outstanding_liability_paise) is int
        assert result.outstanding_liability_paise == -feb.closing_balance_paise
