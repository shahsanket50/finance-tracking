"""Balance-check validator: Invariant 2 enforcement. Implements PRD §14.2."""

from __future__ import annotations

from enum import Enum

from ingestion.parsers.base import ParsedTransaction


class BalanceCheckResult(Enum):
    PASS = "pass"
    FAIL = "fail"
    # Empty statement whose balances are unknown: nothing to check, and never PASS (C2).
    NOT_APPLICABLE = "not_applicable"


def validate_balance(
    opening_paise: int | None,
    transactions: list[ParsedTransaction],
    closing_paise: int | None,
) -> BalanceCheckResult:
    """Return PASS iff opening + credits + debits == closing (exact integer arithmetic).

    Unknown (None) balances: an empty statement is NOT_APPLICABLE (accepted, no anchor);
    a statement with transactions is FAIL (rejected) — its rows can't be verified.

    credits = sum of positive amount_paise
    debits = sum of negative amount_paise (already negative)
    running_balance_paise is excluded — it is validation-only signal, not identity.
    """
    if opening_paise is None or closing_paise is None:
        return BalanceCheckResult.FAIL if transactions else BalanceCheckResult.NOT_APPLICABLE
    credits = sum(t.amount_paise for t in transactions if t.amount_paise > 0)
    debits = sum(t.amount_paise for t in transactions if t.amount_paise < 0)
    return (
        BalanceCheckResult.PASS
        if opening_paise + credits + debits == closing_paise
        else BalanceCheckResult.FAIL
    )
