"""Sign-convention contract across all five production parsers. TRD §10.2, ADR-024, B-5.

Pins: debit negative, credit positive, for every parser's golden output, and the same
signed convention for statement balances (opening + Σ signed amounts == closing). Also pins
that ingestion's payload carries the parser's signed amount unchanged (no abs, no flip).
The golden JSON beside each PDF is the oracle: it was authored with debits negative.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from ingestion.dryrun.confirm import transaction_event_payload
from ingestion.parsers.base import ParsedStatement
from tests.factories.real_rows import BANKS, parse_pdf

GOLDEN_DIR = Path(__file__).parents[2] / "fixtures" / "golden"


def _golden(bank: str) -> tuple[ParsedStatement, dict[str, Any]]:
    statement = parse_pdf((GOLDEN_DIR / bank / "statement_001.pdf").read_bytes())
    oracle = json.loads((GOLDEN_DIR / bank / "statement_001.json").read_text())
    return statement, oracle


def test_all_five_production_parsers_are_covered() -> None:
    assert set(BANKS) == {"hdfc_cc", "sbi_cc", "hdfc_savings", "sbi_savings", "slice_savings"}
    for bank in BANKS:
        assert (GOLDEN_DIR / bank / "statement_001.pdf").is_file(), bank


@pytest.mark.parametrize("bank", BANKS)
def test_each_amount_sign_matches_oracle(bank: str) -> None:
    statement, oracle = _golden(bank)
    expected = [int(str(t["amount_paise"])) for t in oracle["transactions"]]
    actual = [t.amount_paise for t in statement.transactions]
    assert actual == expected, f"{bank}: parsed signed amounts differ from the golden oracle"


@pytest.mark.parametrize("bank", BANKS)
def test_debits_negative_credits_positive_none_zero(bank: str) -> None:
    statement, _ = _golden(bank)
    amounts = [t.amount_paise for t in statement.transactions]
    assert all(isinstance(a, int) for a in amounts)
    assert 0 not in amounts, f"{bank}: a zero amount carries no direction"
    assert any(a < 0 for a in amounts), f"{bank}: golden output has no negative (debit) row"


@pytest.mark.parametrize("bank", BANKS)
def test_balances_use_the_same_signed_convention(bank: str) -> None:
    statement, oracle = _golden(bank)
    assert statement.opening_balance_paise == oracle["opening_balance_paise"]
    assert statement.closing_balance_paise == oracle["closing_balance_paise"]
    assert (
        statement.opening_balance_paise + sum(t.amount_paise for t in statement.transactions)
        == statement.closing_balance_paise
    ), f"{bank}: opening + Σ signed amounts != closing"


@pytest.mark.parametrize("bank", BANKS)
def test_ingestion_payload_keeps_parser_sign(bank: str) -> None:
    statement, _ = _golden(bank)
    for txn in statement.transactions:
        payload = transaction_event_payload(statement, txn)
        assert payload["amount_paise"] == txn.amount_paise
        assert isinstance(payload["amount_paise"], int)
