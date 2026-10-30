"""Account balance public contract. Implements PRD §8.1, ADR-022. Fixes defects B-5, B-6.

Records:
    StatementAnchor — the latest ingested statement for an account: its account_ref, its
        period_end, and its SIGNED closing balance in paise, exactly as the parser read it
        (TRD §10.2: Cr positive, Dr negative). confirm() records it in the IngestionEvent
        payload under the keys "account_ref", "opening_balance_paise" and
        "closing_balance_paise" (int), with period_end in the IngestionEvent.period_end
        column. Statements ingested before that change carry no anchor.
    BalanceLeg — one ingested transaction on the account: hash, SIGNED amount, value date.

Anchor rule (both derivations):
    anchored_balance = anchor.closing_balance_paise
                       + Σ amount_paise of legs with value_date > anchor.period_end,
                         each idempotency_hash counted once (Invariant 1).
    • ALL legs count, including resolver-paired legs. Exclusion is for flow totals only,
      never balances (ADR-022); these derivations take no excluded_hashes input.
    • Legs dated on or before anchor.period_end are already inside the closing balance and
      are ignored.
    • anchor is None → the balance is unknown → the field is None, never 0 (TRD §10.3).
    • anchor.account_ref must equal account_ref, else ValueError.
    • Every amount must be an int, else TypeError (no floats, CLAUDE.md §3.5).

derive_savings_balance(account_ref, account_type, anchor, legs):
    account_type must be "savings" or "current" (else ValueError).
    Returns BalanceSummary(derived_balance_paise=anchored_balance,
                           outstanding_liability_paise=None).

derive_cc_outstanding_liability(account_ref, anchor, legs):
    outstanding_liability_paise = −anchored_balance. It is UNCLAMPED: a negative value is a
    real credit balance (an overpayment), shown as "credit balance ₹X" at display (B-5 fix).
    Returns BalanceSummary(derived_balance_paise=None, outstanding_liability_paise=...).

Edge adapters:
    balance_legs_from_events(events, account_ref) — TransactionIngested events whose
        aggregate_id (account_ref) matches; payload fields as ingestion writes them;
        order-preserving; no dedup (the derivation dedups).
    load_statement_anchor(session, user_id, account_ref) — among this user's ingested
        statements for account_ref whose payload records a closing balance, the one with the
        latest period_end; None if there are none.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date

from sqlalchemy.orm import Session

from core.events.store import Event
from processing.accounts.balance import BalanceSummary


@dataclass(frozen=True)
class StatementAnchor:
    account_ref: str
    period_end: date
    closing_balance_paise: int  # signed, as parsed: Cr positive, Dr negative


@dataclass(frozen=True)
class BalanceLeg:
    idempotency_hash: str
    amount_paise: int  # signed: debit negative, credit positive
    value_date: date


def derive_savings_balance(
    account_ref: str,
    account_type: str,
    anchor: StatementAnchor | None,
    legs: Sequence[BalanceLeg],
) -> BalanceSummary:
    """DERIVATION: statement-anchored savings/current balance. See module docstring."""
    from processing.accounts.balance import derive_anchored_savings_balance as _derive

    return _derive(account_ref, account_type, anchor, legs)


def derive_cc_outstanding_liability(
    account_ref: str,
    anchor: StatementAnchor | None,
    legs: Sequence[BalanceLeg],
) -> BalanceSummary:
    """DERIVATION: statement-anchored, unclamped card liability. See module docstring."""
    from processing.accounts.balance import derive_anchored_cc_liability as _derive

    return _derive(account_ref, anchor, legs)


def balance_legs_from_events(events: Sequence[Event], account_ref: str) -> list[BalanceLeg]:
    """Edge adapter: decrypted TransactionIngested events for account_ref → BalanceLeg records."""
    from processing.accounts.adapter import balance_legs_from_events as _adapt

    return _adapt(events, account_ref)


def load_statement_anchor(
    session: Session, user_id: uuid.UUID, account_ref: str
) -> StatementAnchor | None:
    """Latest ingested statement anchor for account_ref, or None. See module docstring."""
    from processing.accounts.adapter import load_statement_anchor as _load

    return _load(session, user_id, account_ref)
