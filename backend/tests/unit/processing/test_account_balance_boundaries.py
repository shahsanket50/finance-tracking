"""Anchor selection by statement provenance (review C1, ADR-022 as amended). Real parser rows.

C1: a statement's own row value-dated after its period_end is already inside its closing
balance and must never be added again. Legs are placed by the statement that wrote them, not
by value_date. Also pinned here: rows from a later statement are added, upload order and
overlap don't matter, a same-period_end tie goes to the latest upload (highest seq), unplaceable
legs mark the result stale without being added, and any split of a history into consecutive
statements derives the last statement's printed closing balance.
"""

from __future__ import annotations

import dataclasses
from datetime import date, timedelta

from hypothesis import given, settings
from hypothesis import strategies as st

from ingestion.parsers.base import ParsedStatement
from processing.accounts.contract import (
    BalanceLeg,
    balance_legs_from_events,
    derive_cc_outstanding_liability,
    derive_savings_balance,
    select_anchor,
)
from tests.factories.real_rows import Txn, ingested_events, parse_statement, statement_record

SAV_REF = "SBI_SAV_7701"
CC_REF = "SBI_CC_4402"


def _closing(statement: ParsedStatement) -> int:
    assert statement.closing_balance_paise is not None
    return statement.closing_balance_paise


def _legs(account_ref: str, *statements: ParsedStatement) -> list[BalanceLeg]:
    records = [statement_record(s, seq=i + 1) for i, s in enumerate(statements)]
    events = [e for i, s in enumerate(statements) for e in ingested_events(s, start_seq=100 * i)]
    return balance_legs_from_events(events, account_ref, records)


def test_c1_repro_own_row_value_dated_after_period_end_is_not_double_counted() -> None:
    """The reviewer's repro: Mar statement, +₹1,000 value-dated 1 Apr, closing ₹5,600."""
    march = parse_statement(
        "sbi_savings",
        SAV_REF,
        date(2026, 3, 1),
        date(2026, 3, 31),
        [Txn("UPI CREDIT SALARY", 100_000, date(2026, 4, 1))],
        460_000,
    )
    legs = _legs(SAV_REF, march)
    assert legs[0].value_date > march.period_end  # the bank's value date is after period end

    anchor = select_anchor([statement_record(march, seq=1)])
    result = derive_savings_balance(SAV_REF, "savings", anchor, legs)

    assert _closing(march) == 560_000
    assert result.derived_balance_paise == 560_000  # not 660,000
    assert result.stale is False


def _march_then_april(bank: str, ref: str, narration: str) -> tuple[ParsedStatement, ...]:
    march = parse_statement(
        bank, ref, date(2026, 3, 1), date(2026, 3, 31),
        [Txn(narration, -40_000, date(2026, 3, 31))], 500_000,
    )  # fmt: skip
    april = parse_statement(
        bank, ref, date(2026, 4, 1), date(2026, 4, 30),
        [Txn(narration, -25_000, march.period_end + timedelta(days=1))], _closing(march),
    )  # fmt: skip
    return march, april


def test_rows_of_a_later_statement_are_added_to_an_earlier_anchor() -> None:
    march, april = _march_then_april("sbi_savings", SAV_REF, "UPI DMART GROCERY")
    anchor = select_anchor([statement_record(march, seq=1)])  # April's closing not used

    result = derive_savings_balance(SAV_REF, "savings", anchor, _legs(SAV_REF, march, april))

    assert result.derived_balance_paise == _closing(march) - 25_000 == _closing(april)


def test_card_rows_of_a_later_statement_are_added() -> None:
    march, april = _march_then_april("sbi_cc", CC_REF, "AMAZON PURCHASE")
    anchor = select_anchor([statement_record(march, seq=1)])

    result = derive_cc_outstanding_liability(CC_REF, anchor, _legs(CC_REF, march, april))

    assert result.outstanding_liability_paise == -_closing(april)


def test_out_of_order_upload_anchors_on_latest_period_end() -> None:
    """April uploaded first (seq 1), March second (seq 2): the anchor is still April."""
    march, april = _march_then_april("sbi_savings", SAV_REF, "UPI DMART GROCERY")
    records = [statement_record(april, seq=1), statement_record(march, seq=2)]

    anchor = select_anchor(records)
    assert anchor is not None and anchor.period_end == april.period_end
    events = ingested_events(april, start_seq=1) + ingested_events(march, start_seq=10)
    legs = balance_legs_from_events(events, SAV_REF, records)

    result = derive_savings_balance(SAV_REF, "savings", anchor, legs)
    assert result.derived_balance_paise == _closing(april)


def test_overlapping_statements_anchor_on_the_one_ending_last() -> None:
    """15 Mar–14 Apr overlaps 1–31 Mar; the overlap's rows are never added twice."""
    march = parse_statement(
        "sbi_savings", SAV_REF, date(2026, 3, 1), date(2026, 3, 31),
        [Txn("UPI DMART GROCERY", -40_000, date(2026, 3, 20))], 500_000,
    )  # fmt: skip
    overlap = parse_statement(
        "sbi_savings", SAV_REF, date(2026, 3, 15), date(2026, 4, 14),
        [
            Txn("UPI DMART GROCERY", -40_000, date(2026, 3, 20)),
            Txn("UPI ZOMATO ORDER", -10_000, date(2026, 4, 5)),
        ],
        500_000,
    )  # fmt: skip
    records = [statement_record(march, seq=1), statement_record(overlap, seq=2)]
    anchor = select_anchor(records)
    assert anchor is not None and anchor.period_end == overlap.period_end

    result = derive_savings_balance(SAV_REF, "savings", anchor, _legs(SAV_REF, march, overlap))
    assert result.derived_balance_paise == _closing(overlap)


def test_same_period_end_tie_goes_to_latest_upload() -> None:
    original, reissue = (
        parse_statement(
            "sbi_savings", SAV_REF, date(2026, 3, 1), date(2026, 3, 31),
            [Txn(narration, -40_000, date(2026, 3, 10))], 500_000,
        )
        for narration in ("UPI DMART GROCERY", "UPI DMART GROCERY STORE")
    )  # fmt: skip
    first = select_anchor([statement_record(original, seq=7), statement_record(reissue, seq=9)])
    second = select_anchor([statement_record(reissue, seq=9), statement_record(original, seq=7)])
    assert first == second
    assert first is not None and first.seq == 9


def test_statement_with_unknown_closing_never_anchors() -> None:
    march, april = _march_then_april("sbi_savings", SAV_REF, "UPI DMART GROCERY")
    empty_may = dataclasses.replace(
        april, period_start=date(2026, 5, 1), period_end=date(2026, 5, 31),
        transactions=[], opening_balance_paise=None, closing_balance_paise=None,
    )  # fmt: skip
    anchor = select_anchor([statement_record(march, seq=1), statement_record(empty_may, seq=2)])
    assert anchor is not None and anchor.period_end == march.period_end
    assert select_anchor([statement_record(empty_may, seq=1)]) is None


def test_leg_without_statement_provenance_marks_stale_and_is_not_added() -> None:
    march = parse_statement(
        "sbi_savings", SAV_REF, date(2026, 3, 1), date(2026, 3, 31),
        [Txn("UPI DMART GROCERY", -40_000, date(2026, 3, 10))], 500_000,
    )  # fmt: skip
    legs = _legs(SAV_REF, march)
    orphan = dataclasses.replace(
        legs[0], idempotency_hash="no-provenance", value_date=date(2026, 4, 9),
        source_period_end=None,
    )  # fmt: skip
    anchor = select_anchor([statement_record(march, seq=1)])

    result = derive_savings_balance(SAV_REF, "savings", anchor, [*legs, orphan])

    assert result.stale is True
    assert result.derived_balance_paise == _closing(march)  # anchor closing, never a guess


_AMOUNTS = st.lists(
    st.integers(min_value=-500_000, max_value=500_000).filter(lambda a: a != 0),
    min_size=1,
    max_size=8,
)


@settings(max_examples=25, deadline=None)
@given(amounts=_AMOUNTS, cuts=st.lists(st.integers(min_value=1, max_value=7), max_size=3))
def test_any_split_into_consecutive_statements_derives_the_last_closing(
    amounts: list[int], cuts: list[int]
) -> None:
    """One month of real-parser rows split into 1-4 consecutive statements, any anchor."""
    days = [date(2026, 6, 1) + timedelta(days=3 * i) for i in range(len(amounts))]
    bounds = sorted({c for c in cuts if c < len(amounts)})
    pieces = [
        (lo, hi) for lo, hi in zip([0, *bounds], [*bounds, len(amounts)], strict=True) if lo < hi
    ]
    statements: list[ParsedStatement] = []
    opening = 1_000_000
    for lo, hi in pieces:
        start = days[lo]
        end = days[hi] - timedelta(days=1) if hi < len(amounts) else days[-1] + timedelta(days=2)
        txns = [Txn(f"UPI MERCHANT {i:02d}", amounts[i], days[i]) for i in range(lo, hi)]
        statement = parse_statement("sbi_savings", SAV_REF, start, end, txns, opening)
        statements.append(statement)
        opening = _closing(statement)

    legs = _legs(SAV_REF, *statements)
    for anchor_index in range(len(statements)):
        anchor = select_anchor([statement_record(statements[anchor_index], seq=1)])
        result = derive_savings_balance(SAV_REF, "savings", anchor, legs)
        assert result.derived_balance_paise == _closing(statements[-1])
        assert result.stale is False
