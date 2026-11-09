"""Account balance public contract. Implements PRD §8.1, ADR-022. Fixes B-5, B-6, review C1/C2.

Records:
    StatementRecord — one ingested statement for an account: its IngestionEvent id and global
        seq, account_ref, the account_type the parser reported, period_end, and its SIGNED
        closing balance as parsed (TRD §10.2), or None when the statement printed none
        (empty statement, balance_check = not_applicable). confirm() writes account_ref and
        account_type in IngestionEvent.source_detail (plaintext routing keys) and the
        balances in the encrypted payload ("opening_balance_paise", "closing_balance_paise").
    StatementAnchor — the statement a balance is anchored to.
    BalanceLeg — one ingested transaction: hash, SIGNED amount, value date, and the
        period_end of the statement that wrote it (source_period_end; None = the row has no
        statement provenance, e.g. a future non-statement source).

Anchor selection — select_anchor(statements):
    Among statements with a known closing balance, the one with the latest period_end; a tie
    on period_end goes to the highest global seq (latest upload). None if there are none.
    Upload order never matters, and overlapping statements resolve to the one ending last.

Anchor rule (both derivations) — PROVENANCE, not value_date (review finding C1: a statement's
own row value-dated after its period_end is already inside its closing balance):
    anchored = anchor.closing_balance_paise
               + Σ amount_paise of legs whose source_period_end > anchor.period_end,
                 each idempotency_hash counted once (Invariant 1).
    • Legs from the anchor statement or any statement ending on/before it are inside the
      closing balance and are never added, whatever their value_date.
    • A leg with source_period_end None can't be placed relative to the anchor: it is NOT
      added and the result is marked stale=True. Never a guess.
    • ALL other legs count, including resolver-paired ones: exclusion is for flow totals
      only (ADR-022). These derivations take no excluded_hashes input.
    • anchor None → the balance is unknown → None, never 0 (TRD §10.3); stale=False.
    • anchor.account_ref must equal account_ref, else ValueError.
    • Every amount must be an int, else TypeError (no floats, CLAUDE.md §3.5).

derive_savings_balance(account_ref, account_type, anchor, legs):
    account_type must be "savings" or "current" (else ValueError). Returns BalanceSummary with
    derived_balance_paise = anchored, outstanding_liability_paise None.

derive_cc_outstanding_liability(account_ref, anchor, legs):
    outstanding_liability_paise = −anchored, UNCLAMPED: negative = credit balance (B-5).

Edge adapters:
    load_account_statements(session, user_id, account_ref) — ingested statements whose
        source_detail names account_ref; decrypts only those. A payload that can't be
        decrypted raises StatementDecryptionError naming the IngestionEvent, so the failure
        stays scoped to this account.
    balance_legs_from_events(events, account_ref, statements) — TransactionIngested events
        for account_ref; source_period_end looked up by event.ingestion_event_id;
        order-preserving; no dedup (the derivation dedups).
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
class StatementRecord:
    ingestion_event_id: uuid.UUID
    seq: int
    account_ref: str
    account_type: str  # as reported by the parser: "savings" | "credit_card" | "fd"
    period_end: date
    closing_balance_paise: int | None  # signed as parsed; None = not printed


@dataclass(frozen=True)
class StatementAnchor:
    account_ref: str
    ingestion_event_id: uuid.UUID
    seq: int
    period_end: date
    closing_balance_paise: int  # signed, as parsed: Cr positive, Dr negative


@dataclass(frozen=True)
class BalanceLeg:
    idempotency_hash: str
    amount_paise: int  # signed: debit negative, credit positive
    value_date: date
    source_period_end: date | None  # period_end of the statement that wrote it


class StatementDecryptionError(Exception):
    """A statement for this account could not be decrypted; no balance can be derived."""

    def __init__(self, ingestion_event_id: uuid.UUID, cause: Exception) -> None:
        self.ingestion_event_id = ingestion_event_id
        super().__init__(
            f"statement {ingestion_event_id} could not be decrypted: {type(cause).__name__}"
        )


def select_anchor(statements: Sequence[StatementRecord]) -> StatementAnchor | None:
    """Latest statement with a known closing; tie on period_end → highest seq."""
    from processing.accounts.balance import select_anchor as _select

    return _select(statements)


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


def balance_legs_from_events(
    events: Sequence[Event],
    account_ref: str,
    statements: Sequence[StatementRecord],
) -> list[BalanceLeg]:
    """Edge adapter: TransactionIngested events for account_ref → BalanceLeg with provenance."""
    from processing.accounts.adapter import balance_legs_from_events as _adapt

    return _adapt(events, account_ref, statements)


def load_account_statements(
    session: Session, user_id: uuid.UUID, account_ref: str
) -> list[StatementRecord]:
    """Ingested statements for account_ref. See module docstring."""
    from processing.accounts.adapter import load_account_statements as _load

    return _load(session, user_id, account_ref)


def load_statement_anchor(
    session: Session, user_id: uuid.UUID, account_ref: str
) -> StatementAnchor | None:
    """select_anchor(load_account_statements(...)): the account's anchor, or None."""
    return select_anchor(load_account_statements(session, user_id, account_ref))
