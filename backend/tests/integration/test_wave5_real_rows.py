"""Wave 5 real-row integration: resolver exclusion, budgets and anchored balances end to end.

PRD §4.3, §7.1, §8.1; ADR-020, ADR-022, ADR-023, ADR-024; defects B-5, B-6.

Independent test-authoring (CLAUDE.md §6, TRD §11, PHASE_PROTOCOL §3): written from the spec
and the contracts (processing/budgets/contract.py, processing/accounts/contract.py,
processing/exclusions.py) without opening the implementation files.

Every row goes through the production path: synthetic statement → PDF → real dry_run() →
real confirm() (which runs the real resolver) against testcontainers Postgres + Redis.
confirm() commits, so each test isolates by a fresh user (the test_user fixture), not by
rollback.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import date
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from core.events.models import TransactionEvent, User
from core.events.store import Event, read_since_seq
from core.events.types import MARKED_CC_PAYMENT, MARKED_INTERNAL_TRANSFER, TRANSACTION_INGESTED
from ingestion.parsers.base import ParsedStatement
from processing.accounts.contract import (
    balance_legs_from_events,
    derive_cc_outstanding_liability,
    derive_savings_balance,
    load_statement_anchor,
)
from processing.budgets.contract import budget_transactions_from_events, derive_budget_utilization
from processing.classifier.categories import Category
from processing.exclusions import load_excluded_hashes
from processing.resolver.pipeline import run_resolver
from tests.factories.real_rows import Txn, ingest_via_confirm, parse_pdf, render_statement_pdf

pytestmark = pytest.mark.integration

JAN = date(2026, 1, 1)
MAR = date(2026, 3, 1)

SAV_REF = "HDFC_SAV_9876"
CC_REF = "SBI_CC_8765"


def _ingest(
    session: Session,
    redis_client: Any,
    user_id: uuid.UUID,
    bank: str,
    account_ref: str,
    period_start: date,
    period_end: date,
    txns: Sequence[Txn],
    opening_balance_paise: int,
) -> ParsedStatement:
    """Render → real dry_run() + confirm(). Returns what the production parser read."""
    pdf_bytes = render_statement_pdf(
        bank, account_ref, period_start, period_end, txns, opening_balance_paise
    )
    ingest_via_confirm(session, redis_client, user_id, pdf_bytes, account_ref)
    return parse_pdf(pdf_bytes)


def _hash(statement: ParsedStatement, narration: str) -> str:
    matches = [t.idempotency_hash for t in statement.transactions if t.narration == narration]
    assert len(matches) == 1, narration
    return matches[0]


def _ingested_hashes(events: Sequence[Event]) -> set[str]:
    return {
        str(e.payload["idempotency_hash"]) for e in events if e.event_type == TRANSACTION_INGESTED
    }


def _resolver_rows(session: Session, user_id: uuid.UUID, event_type: str) -> list[TransactionEvent]:
    return list(
        session.scalars(
            select(TransactionEvent).where(
                TransactionEvent.user_id == user_id,
                TransactionEvent.event_type == event_type,
            )
        ).all()
    )


# ---------------------------------------------------------------------------
# Scenario 1: savings CC bill payment ↔ card payment credit (MarkedCCPayment)
# ---------------------------------------------------------------------------

SAV_OPENING = 1_900_000
SAV_TXNS = (
    Txn("NEFTCR SALARY COMPANY", 5_000_000, date(2026, 1, 1)),
    Txn("UPI BIGBASKET GROCERY", -320_000, date(2026, 1, 20)),
    Txn("CC PAYMENT SBI CARD", -1_500_000, date(2026, 1, 28)),
)
CARD_OPENING = -1_500_000  # owes ₹15,000 at open
CARD_TXNS = (
    Txn("GROCERY STORE BIG BAZAAR", -55_000, date(2026, 1, 3)),
    # Within CC_PAYMENT_MATCH_WINDOW_DAYS (3) of the savings debit; same magnitude.
    Txn("PAYMENT RECEIVED THANK YOU", 1_500_000, date(2026, 1, 29)),
)


def _cc_payment_world(
    session: Session, redis_client: Any, user_id: uuid.UUID
) -> tuple[ParsedStatement, ParsedStatement]:
    sav = _ingest(
        session,
        redis_client,
        user_id,
        "hdfc_savings",
        SAV_REF,
        JAN,
        date(2026, 1, 31),
        SAV_TXNS,
        SAV_OPENING,
    )
    card = _ingest(
        session,
        redis_client,
        user_id,
        "sbi_cc",
        CC_REF,
        JAN,
        date(2026, 1, 31),
        CARD_TXNS,
        CARD_OPENING,
    )
    return sav, card


def test_cc_payment_resolver_row_references_ingested_legs(
    pg_session: Session, redis_client: Any, test_user: User
) -> None:
    sav, card = _cc_payment_world(pg_session, redis_client, test_user.id)
    events = read_since_seq(pg_session, test_user.id, 0)
    ingested = _ingested_hashes(events)

    cc_events = [e for e in events if e.event_type == MARKED_CC_PAYMENT]
    assert len(cc_events) == 1
    payload = cc_events[0].payload
    legs = {str(payload["savings_debit_hash"]), str(payload["cc_credit_hash"])}
    assert legs <= ingested
    assert legs == {
        _hash(sav, "CC PAYMENT SBI CARD"),
        _hash(card, "PAYMENT RECEIVED THANK YOU"),
    }

    rows = _resolver_rows(pg_session, test_user.id, MARKED_CC_PAYMENT)
    assert len(rows) == 1
    assert rows[0].idempotency_hash not in ingested  # ADR-023: own hash names the event


def test_cc_payment_legs_excluded_from_spend_but_counted_in_balances(
    pg_session: Session, redis_client: Any, test_user: User
) -> None:
    sav, card = _cc_payment_world(pg_session, redis_client, test_user.id)
    payment_debit = _hash(sav, "CC PAYMENT SBI CARD")
    payment_credit = _hash(card, "PAYMENT RECEIVED THANK YOU")

    excluded = load_excluded_hashes(pg_session, test_user.id)
    assert {payment_debit, payment_credit} <= excluded

    events = read_since_seq(pg_session, test_user.id, 0)

    # Flow totals: a naive classifier put the bill payment in "other", the card credit in
    # "shopping". Exclusion must remove both legs.
    effective: dict[str, Category] = {
        payment_debit: "other",
        payment_credit: "shopping",
        _hash(sav, "UPI BIGBASKET GROCERY"): "groceries",
        _hash(card, "GROCERY STORE BIG BAZAAR"): "groceries",
        _hash(sav, "NEFTCR SALARY COMPANY"): "income",
    }
    records = budget_transactions_from_events(events, effective)
    assert derive_budget_utilization(records, excluded, "other", JAN) == 0
    assert derive_budget_utilization(records, excluded, "shopping", JAN) == 0
    assert derive_budget_utilization(records, excluded, "groceries", JAN) == 375_000
    # Contrast: without the projection's exclusions the legs would leak into budgets.
    assert derive_budget_utilization(records, frozenset(), "other", JAN) == 1_500_000

    # Balances: ALL legs count (ADR-022). The savings balance is the statement's closing.
    sav_anchor = load_statement_anchor(pg_session, test_user.id, SAV_REF)
    assert sav_anchor is not None
    assert sav_anchor.account_ref == SAV_REF
    assert sav_anchor.period_end == sav.period_end
    assert sav_anchor.closing_balance_paise == sav.closing_balance_paise
    sav_balance = derive_savings_balance(
        SAV_REF, "savings", sav_anchor, balance_legs_from_events(events, SAV_REF)
    )
    assert sav_balance.derived_balance_paise == sav.closing_balance_paise
    assert sav_balance.derived_balance_paise == SAV_OPENING + 3_180_000  # B-6: not +4,680,000

    # Card liability reflects the payment credit: ₹15,000 + ₹550 − ₹15,000 = ₹550.
    card_anchor = load_statement_anchor(pg_session, test_user.id, CC_REF)
    assert card_anchor is not None
    assert card_anchor.closing_balance_paise == card.closing_balance_paise
    liability = derive_cc_outstanding_liability(
        CC_REF, card_anchor, balance_legs_from_events(events, CC_REF)
    )
    assert liability.outstanding_liability_paise == 55_000


def test_second_resolver_run_writes_nothing(
    pg_session: Session, redis_client: Any, test_user: User
) -> None:
    _cc_payment_world(pg_session, redis_client, test_user.id)
    before = _resolver_rows(pg_session, test_user.id, MARKED_CC_PAYMENT)
    assert len(before) == 1
    before_hash = before[0].idempotency_hash

    assert run_resolver(pg_session, test_user.id) == 0
    pg_session.commit()

    after = _resolver_rows(pg_session, test_user.id, MARKED_CC_PAYMENT)
    assert len(after) == 1
    assert after[0].idempotency_hash == before_hash


# ---------------------------------------------------------------------------
# Scenario 2: own-account transfer between two savings accounts
# ---------------------------------------------------------------------------

HDFC_REF = "HDFC_SAV_1111"
SBI_REF = "SBI_SAV_2222"
HDFC_OPENING = 5_000_000
SBI_OPENING = 100_000
TRANSFER_PAISE = 2_000_000


def test_internal_transfer_moves_balances_nets_to_zero_and_is_not_spend(
    pg_session: Session, redis_client: Any, test_user: User
) -> None:
    hdfc = _ingest(
        pg_session,
        redis_client,
        test_user.id,
        "hdfc_savings",
        HDFC_REF,
        MAR,
        date(2026, 3, 31),
        (Txn("NEFTDR TRANSFER TO SBI", -TRANSFER_PAISE, date(2026, 3, 10)),),
        HDFC_OPENING,
    )
    sbi = _ingest(
        pg_session,
        redis_client,
        test_user.id,
        "sbi_savings",
        SBI_REF,
        MAR,
        date(2026, 3, 31),
        (Txn("UPI CREDIT TRANSFER FROM HDFC", TRANSFER_PAISE, date(2026, 3, 10)),),
        SBI_OPENING,
    )
    debit_leg = _hash(hdfc, "NEFTDR TRANSFER TO SBI")
    credit_leg = _hash(sbi, "UPI CREDIT TRANSFER FROM HDFC")

    events = read_since_seq(pg_session, test_user.id, 0)
    transfers = [e for e in events if e.event_type == MARKED_INTERNAL_TRANSFER]
    assert len(transfers) == 1
    assert {str(transfers[0].payload["debit_hash"]), str(transfers[0].payload["credit_hash"])} == {
        debit_leg,
        credit_leg,
    }

    excluded = load_excluded_hashes(pg_session, test_user.id)
    assert {debit_leg, credit_leg} <= excluded

    # Balances move on both accounts; combined net change is 0.
    hdfc_anchor = load_statement_anchor(pg_session, test_user.id, HDFC_REF)
    sbi_anchor = load_statement_anchor(pg_session, test_user.id, SBI_REF)
    hdfc_balance = derive_savings_balance(
        HDFC_REF, "savings", hdfc_anchor, balance_legs_from_events(events, HDFC_REF)
    ).derived_balance_paise
    sbi_balance = derive_savings_balance(
        SBI_REF, "savings", sbi_anchor, balance_legs_from_events(events, SBI_REF)
    ).derived_balance_paise
    assert hdfc_balance == HDFC_OPENING - TRANSFER_PAISE == hdfc.closing_balance_paise
    assert sbi_balance == SBI_OPENING + TRANSFER_PAISE == sbi.closing_balance_paise
    assert (hdfc_balance - HDFC_OPENING) + (sbi_balance - SBI_OPENING) == 0

    # Spend excludes both legs, even if a classifier had categorized them as spend.
    records = budget_transactions_from_events(events, {debit_leg: "other", credit_leg: "shopping"})
    assert derive_budget_utilization(records, excluded, "other", MAR) == 0
    assert derive_budget_utilization(records, excluded, "shopping", MAR) == 0


# ---------------------------------------------------------------------------
# Scenario 3: anchors
# ---------------------------------------------------------------------------


def test_account_without_statement_has_no_anchor_and_no_balance(
    pg_session: Session, redis_client: Any, test_user: User
) -> None:
    _cc_payment_world(pg_session, redis_client, test_user.id)
    other_ref = "AXIS_SAV_0000"
    anchor = load_statement_anchor(pg_session, test_user.id, other_ref)
    assert anchor is None
    events = read_since_seq(pg_session, test_user.id, 0)
    legs = balance_legs_from_events(events, other_ref)
    assert legs == []
    result = derive_savings_balance(other_ref, "savings", anchor, legs)
    assert result.derived_balance_paise is None


def test_anchor_is_latest_period_end_regardless_of_ingest_order(
    pg_session: Session, redis_client: Any, test_user: User
) -> None:
    feb = _ingest(
        pg_session,
        redis_client,
        test_user.id,
        "hdfc_savings",
        SAV_REF,
        date(2026, 2, 1),
        date(2026, 2, 28),
        (Txn("UPI ZOMATO ORDER", -64_000, date(2026, 2, 14)),),
        5_080_000,
    )
    jan = _ingest(
        pg_session,
        redis_client,
        test_user.id,
        "hdfc_savings",
        SAV_REF,
        JAN,
        date(2026, 1, 31),
        SAV_TXNS,
        SAV_OPENING,
    )
    assert jan.closing_balance_paise == feb.opening_balance_paise
    anchor = load_statement_anchor(pg_session, test_user.id, SAV_REF)
    assert anchor is not None
    assert anchor.period_end == feb.period_end
    assert anchor.closing_balance_paise == feb.closing_balance_paise
    events = read_since_seq(pg_session, test_user.id, 0)
    result = derive_savings_balance(
        SAV_REF, "savings", anchor, balance_legs_from_events(events, SAV_REF)
    )
    assert result.derived_balance_paise == feb.closing_balance_paise
