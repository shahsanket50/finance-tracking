"""Account balance derivation. Implements PRD §8.1 (CC dual model), ADR-022; fixes B-5, B-6, C1.

DERIVATIONS (TRD §3.4): pure arithmetic over recorded facts, safe to recompute.
Contract: processing/accounts/contract.py.

Both formulas start from the same statement-anchored signed balance, selected by statement
PROVENANCE, never by value_date (review finding C1):
    anchored = anchor.closing_balance_paise
               + Σ legs written by a statement that ends after the anchor's period_end
Savings/current report it as the balance; credit cards report −anchored as the outstanding
liability, unclamped (negative = credit balance). Legs with no statement provenance are not
added and mark the result stale. With no anchor the value is None, never 0.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from processing.accounts.contract import BalanceLeg, StatementAnchor, StatementRecord


@dataclass(frozen=True)
class BalanceSummary:
    """Result of a balance derivation for one account.

    Exactly one money field belongs to the account's class; the other is always None.
    The class's own field is None when there is no statement anchor (balance unknown).
    stale=True: some legs could not be placed relative to the anchor and were not added,
    so the figure is the anchor's closing balance (plus placeable later legs), never a guess.
    """

    account_ref: str
    account_type: str  # "savings" | "current" | "credit_card"
    derived_balance_paise: int | None  # savings/current: signed net asset
    outstanding_liability_paise: int | None  # credit_card: owed; negative = credit balance
    stale: bool = False


def _require_int(value: object, what: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise TypeError(
            f"{what} must be int paise, got {type(value).__name__} — "
            "floats are never permitted (CLAUDE.md §3.5)"
        )
    return value


def select_anchor(statements: Sequence[StatementRecord]) -> StatementAnchor | None:
    from processing.accounts.contract import StatementAnchor

    known = [
        s for s in statements if s.balance_check == "pass" and s.closing_balance_paise is not None
    ]
    if not known:
        return None
    latest = max(known, key=lambda s: (s.period_end, s.seq))
    return StatementAnchor(
        account_ref=latest.account_ref,
        ingestion_event_id=latest.ingestion_event_id,
        seq=latest.seq,
        period_end=latest.period_end,
        closing_balance_paise=_require_int(
            latest.closing_balance_paise, "statement closing_balance_paise"
        ),
    )


def _anchored_balance(
    account_ref: str, anchor: StatementAnchor | None, legs: Sequence[BalanceLeg]
) -> tuple[int | None, bool]:
    for leg in legs:
        _require_int(leg.amount_paise, f"amount_paise of {leg.idempotency_hash}")
    if anchor is None:
        return None, False
    if anchor.account_ref != account_ref:
        raise ValueError(f"anchor belongs to account {anchor.account_ref!r}, not {account_ref!r}")
    balance = _require_int(anchor.closing_balance_paise, "anchor closing_balance_paise")
    stale = False
    counted: set[str] = set()
    for leg in legs:
        if leg.idempotency_hash in counted:
            continue
        counted.add(leg.idempotency_hash)
        if leg.source_period_end is None:
            stale = True  # can't tell whether the closing balance already includes it
        elif leg.source_period_end > anchor.period_end:
            balance += leg.amount_paise
    return balance, stale


def derive_anchored_savings_balance(
    account_ref: str,
    account_type: str,
    anchor: StatementAnchor | None,
    legs: Sequence[BalanceLeg],
) -> BalanceSummary:
    if account_type not in ("savings", "current"):
        raise ValueError(
            f"savings balance only applies to savings/current accounts, got "
            f"account_type={account_type!r}; use derive_cc_outstanding_liability for cards"
        )
    balance, stale = _anchored_balance(account_ref, anchor, legs)
    return BalanceSummary(
        account_ref=account_ref,
        account_type=account_type,
        derived_balance_paise=balance,
        outstanding_liability_paise=None,
        stale=stale,
    )


def derive_anchored_cc_liability(
    account_ref: str,
    anchor: StatementAnchor | None,
    legs: Sequence[BalanceLeg],
) -> BalanceSummary:
    balance, stale = _anchored_balance(account_ref, anchor, legs)
    return BalanceSummary(
        account_ref=account_ref,
        account_type="credit_card",
        derived_balance_paise=None,
        outstanding_liability_paise=None if balance is None else -balance,
        stale=stale,
    )
