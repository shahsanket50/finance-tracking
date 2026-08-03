"""Balance-check validator: Invariant 2 enforcement. Implements PRD §14.2."""

from __future__ import annotations

from enum import Enum

from ingestion.parsers.base import ParsedTransaction


class BalanceCheckResult(Enum):
    PASS = "pass"
    FAIL = "fail"


def validate_balance(
    opening_paise: int,
    transactions: list[ParsedTransaction],
    closing_paise: int,
) -> BalanceCheckResult:
    """Return PASS iff opening + credits + debits == closing (exact integer arithmetic).

    credits = sum of positive amount_paise
    debits = sum of negative amount_paise (already negative)
    running_balance_paise is excluded — it is validation-only signal, not identity.
    """
    credits = sum(t.amount_paise for t in transactions if t.amount_paise > 0)
    debits = sum(t.amount_paise for t in transactions if t.amount_paise < 0)
    return (
        BalanceCheckResult.PASS
        if opening_paise + credits + debits == closing_paise
        else BalanceCheckResult.FAIL
    )
