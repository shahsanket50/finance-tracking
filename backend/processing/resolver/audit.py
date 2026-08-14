"""Audit view builder: Level B seen-vs-counted ledger (PRD §15).

Consumes the 'transactions_view' projection state and returns a structured
audit view proving zero double-counting — every excluded transaction hash
has a recorded reason from a resolver decision event.
"""

from __future__ import annotations

from typing import cast


def build_audit_view(state: dict[str, object]) -> dict[str, object]:
    """Build the audit view from a transactions_view projection state.

    Returns a dict with:
      total_seen    — count of all TransactionIngested events
      total_counted — count of transactions included in totals
      total_excluded — count of transactions excluded by resolver decisions
      entries       — list of audit entries, one per transaction, sorted by value_date

    Each entry:
      idempotency_hash   — str
      amount_paise       — int (signed)
      value_date         — str (ISO date)
      account_ref        — str
      transaction_type   — str
      is_counted         — bool
      exclusion_reason   — str | None  ("internal_transfer" | "cc_payment" | "fd_booking" | "reversal")
    """
    transactions: list[dict[str, object]] = list(
        cast(list[dict[str, object]], state.get("transactions", []))
    )
    exclusion_reasons: dict[str, str] = dict(
        cast(dict[str, str], state.get("exclusion_reasons", {}))
    )
    excluded_set: set[str] = set(
        cast(list[str], state.get("excluded_hashes", []))
    )

    entries = []
    for txn in transactions:
        h = str(txn["idempotency_hash"])
        is_counted = h not in excluded_set
        entries.append(
            {
                "idempotency_hash": h,
                "amount_paise": txn["amount_paise"],
                "value_date": txn["value_date"],
                "account_ref": txn.get("account_ref", ""),
                "transaction_type": txn.get("transaction_type", ""),
                "is_counted": is_counted,
                "exclusion_reason": exclusion_reasons.get(h),
            }
        )

    entries.sort(key=lambda e: str(e["value_date"]))
    total_seen = len(entries)
    total_counted = sum(1 for e in entries if e["is_counted"])
    total_excluded = total_seen - total_counted

    return {
        "total_seen": total_seen,
        "total_counted": total_counted,
        "total_excluded": total_excluded,
        "entries": entries,
    }
