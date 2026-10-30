"""Anchor period_end boundary, both sides. ADR-022. (Implementation-session test.)

test_account_balance.py (independent) pins that a leg dated ON period_end is ignored. This
pins the other side of the off-by-one: a leg dated period_end + 1 day IS counted, for both
the savings and the card derivation. Rows come from real parser output (ADR-024).
"""

from __future__ import annotations

from datetime import date, timedelta

from ingestion.parsers.base import ParsedStatement
from processing.accounts.contract import (
    StatementAnchor,
    balance_legs_from_events,
    derive_cc_outstanding_liability,
    derive_savings_balance,
)
from tests.factories.real_rows import Txn, ingested_events, parse_statement

SAV_REF = "HDFC_SAV_4401"
CC_REF = "SBI_CC_4402"


def _anchor(statement: ParsedStatement) -> StatementAnchor:
    return StatementAnchor(
        account_ref=statement.account_ref,
        period_end=statement.period_end,
        closing_balance_paise=statement.closing_balance_paise,
    )


def _march_then_april(bank: str, ref: str, narration: str) -> tuple[ParsedStatement, ...]:
    march = parse_statement(
        bank,
        ref,
        date(2026, 3, 1),
        date(2026, 3, 31),
        [Txn(narration, -40_000, date(2026, 3, 31))],
        500_000,
    )
    april = parse_statement(
        bank,
        ref,
        date(2026, 4, 1),
        date(2026, 4, 30),
        [Txn(narration, -25_000, march.period_end + timedelta(days=1))],
        march.closing_balance_paise,
    )
    return march, april


def test_savings_leg_on_day_after_period_end_is_counted() -> None:
    march, april = _march_then_april("hdfc_savings", SAV_REF, "UPI DMART GROCERY")
    legs = balance_legs_from_events(
        ingested_events(march) + ingested_events(april, start_seq=10), SAV_REF
    )
    assert [leg.value_date for leg in legs] == [date(2026, 3, 31), date(2026, 4, 1)]

    result = derive_savings_balance(SAV_REF, "savings", _anchor(march), legs)

    assert result.derived_balance_paise == march.closing_balance_paise - 25_000
    assert result.derived_balance_paise == april.closing_balance_paise


def test_card_leg_on_day_after_period_end_is_counted() -> None:
    march, april = _march_then_april("sbi_cc", CC_REF, "AMAZON PURCHASE")
    legs = balance_legs_from_events(
        ingested_events(march) + ingested_events(april, start_seq=10), CC_REF
    )

    result = derive_cc_outstanding_liability(CC_REF, _anchor(march), legs)

    assert result.outstanding_liability_paise == -april.closing_balance_paise
    assert result.outstanding_liability_paise == -march.closing_balance_paise + 25_000
