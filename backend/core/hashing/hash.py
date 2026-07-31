"""Idempotency hash (C1) and occurrence index (C2).

C1: hash = SHA-256 of pipe-joined canonical fields.
C2: occurrence_index = 0-based ordinal within (account, date, amount, narration) group.
running_balance is deliberately excluded from the hash (C1 spec).
"""

from __future__ import annotations

import hashlib
from datetime import date


def compute_idempotency_hash(
    account_ref: str,
    value_date: date,
    amount_paise: int,
    normalized_narration: str,
    occurrence_index: int,
) -> str:
    """Compute the SHA-256 idempotency hash for a transaction (C1+C2).

    Fields joined with '|' separator. Result is a 64-char hex string.
    running_balance is NOT part of the hash — it is validation-only.
    """
    raw = (
        f"{account_ref}"
        f"|{value_date.isoformat()}"
        f"|{amount_paise}"
        f"|{normalized_narration}"
        f"|{occurrence_index}"
    )
    return hashlib.sha256(raw.encode()).hexdigest()


def compute_occurrence_index(
    transactions: list[dict[str, object]],
    account_ref: str,
    value_date: date,
    amount_paise: int,
    normalized_narration: str,
) -> int:
    """Return the 0-based ordinal of this (account_ref, value_date, amount_paise,
    normalized_narration) group entry within `transactions`.

    `transactions` is the full statement list in source order. Count how many
    prior entries share the same group key — that count is the occurrence_index
    for the next entry with this key.

    Usage: call this before adding the current transaction to `transactions`.
    """
    count = 0
    for txn in transactions:
        if (
            txn.get("account_ref") == account_ref
            and txn.get("value_date") == value_date
            and txn.get("amount_paise") == amount_paise
            and txn.get("normalized_narration") == normalized_narration
        ):
            count += 1
    return count
