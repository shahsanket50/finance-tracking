"""Idempotency hash (C1) and occurrence index (C2).

C1: hash = SHA-256 of pipe-joined canonical fields.
C2: occurrence_index = 0-based ordinal within (account, date, amount, canonical_narration) group.
running_balance is deliberately excluded from the hash (C1 spec).
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from datetime import date


def canonicalize_narration(narration: str) -> str:
    """Frozen canonicalization applied at parse time (step 2). TRD §9.1 C1.

    Steps (order is significant and must never change):
    1. Unicode NFKC normalization
    2. Strip leading/trailing whitespace
    3. Collapse internal whitespace sequences to a single space
    4. Uppercase

    This function is distinct from step-4 merchant normalization.
    Any change here invalidates all historical idempotency hashes.
    """
    s = unicodedata.normalize("NFKC", narration)
    s = s.strip()
    s = re.sub(r"\s+", " ", s)
    return s.upper()


def compute_idempotency_hash(
    account_ref: str,
    value_date: date,
    amount_paise: int,
    canonical_narration: str,
    occurrence_index: int,
) -> str:
    """Compute the SHA-256 idempotency hash for a transaction (TRD §9.1 C1+C2).

    Fields joined with '|' separator. Result is a 64-char hex string.
    running_balance is NOT part of the hash — it is validation-only.
    canonical_narration must already be canonicalized via canonicalize_narration().
    """
    if not isinstance(amount_paise, int):
        raise TypeError(f"amount_paise must be int, got {type(amount_paise).__name__}")
    raw = (
        f"{account_ref}"
        f"|{value_date.isoformat()}"
        f"|{amount_paise}"
        f"|{canonical_narration}"
        f"|{occurrence_index}"
    )
    return hashlib.sha256(raw.encode()).hexdigest()


def compute_occurrence_index(
    transactions: list[dict[str, object]],
    account_ref: str,
    value_date: date,
    amount_paise: int,
    canonical_narration: str,
) -> int:
    """Return the 0-based ordinal of this (account_ref, value_date, amount_paise,
    canonical_narration) group entry within `transactions`.

    `transactions` is the full statement list in source order. Count how many
    prior entries share the same group key — that count is the occurrence_index
    for the next entry with this key.

    Usage: call this before adding the current transaction to `transactions`.
    canonical_narration must already be canonicalized via canonicalize_narration().
    """
    count = 0
    for txn in transactions:
        if (
            txn.get("account_ref") == account_ref
            and txn.get("value_date") == value_date
            and txn.get("amount_paise") == amount_paise
            and txn.get("canonical_narration") == canonical_narration
        ):
            count += 1
    return count
