"""Transactions-view projection reducer (TRD §9.1 C3, §9.2).

Builds a view of all ingested transactions, tracking which are excluded by
resolver decisions (internal transfers, CC payments, FD bookings, reversals).

This reducer reads resolver DECISIONS from recorded events — it never calls
matcher logic. Calling matchers here would break Invariant 3 (replay
determinism) and violate TRD §9.2 (decisions vs derivations).

Registers the 'transactions_view' projection type with the builder registry.
"""

from __future__ import annotations

from typing import cast

from core.events.store import Event
from core.projections.builder import register_reducer


def _initial_state() -> dict[str, object]:
    return {
        "transactions": [],
        "excluded_hashes": [],
        "exclusion_reasons": {},  # hash → exclusion reason (one of RESOLVER_EVENT_TYPES)
        "totals": {
            "income_paise": 0,
            "expense_paise": 0,
            "excluded_count": 0,
        },
    }


def _reducer(state: dict[str, object], event: Event) -> dict[str, object]:
    transactions: list[dict[str, object]] = list(
        cast(list[dict[str, object]], state["transactions"])
    )
    excluded: list[str] = list(cast(list[str], state["excluded_hashes"]))
    reasons: dict[str, str] = dict(cast(dict[str, str], state["exclusion_reasons"]))

    if event.event_type == "TransactionIngested":
        p = event.payload
        transactions.append(
            {
                "idempotency_hash": p["idempotency_hash"],
                "amount_paise": p["amount_paise"],
                "value_date": p["value_date"],
                "account_ref": p.get("account_ref", event.aggregate_id),
                "canonical_narration": p.get("canonical_narration"),
                "transaction_type": p.get("transaction_type", "expense"),
            }
        )
    elif event.event_type == "MarkedInternalTransfer":
        p = event.payload
        h1, h2 = str(p["debit_hash"]), str(p["credit_hash"])
        excluded.extend([h1, h2])
        reasons[h1] = "internal_transfer"
        reasons[h2] = "internal_transfer"
    elif event.event_type == "MarkedCCPayment":
        p = event.payload
        h1, h2 = str(p["savings_debit_hash"]), str(p["cc_credit_hash"])
        excluded.extend([h1, h2])
        reasons[h1] = "cc_payment"
        reasons[h2] = "cc_payment"
    elif event.event_type == "MarkedFDBooking":
        p = event.payload
        h1, h2 = str(p["savings_debit_hash"]), str(p["fd_credit_hash"])
        excluded.extend([h1, h2])
        reasons[h1] = "fd_booking"
        reasons[h2] = "fd_booking"
    elif event.event_type == "MarkedReversal":
        p = event.payload
        h1, h2 = str(p["original_hash"]), str(p["reversal_hash"])
        excluded.extend([h1, h2])
        reasons[h1] = "reversal"
        reasons[h2] = "reversal"
    # Unknown event types are silently ignored (forward compatibility).

    excluded_set = set(excluded)
    active = [t for t in transactions if t["idempotency_hash"] not in excluded_set]

    income_paise = sum(
        cast(int, t["amount_paise"]) for t in active if t.get("transaction_type") == "income"
    )
    expense_paise = sum(
        abs(cast(int, t["amount_paise"])) for t in active if t.get("transaction_type") == "expense"
    )
    excluded_count = len(transactions) - len(active)

    return {
        "transactions": transactions,
        "excluded_hashes": excluded,
        "exclusion_reasons": reasons,
        "totals": {
            "income_paise": income_paise,
            "expense_paise": expense_paise,
            "excluded_count": excluded_count,
        },
    }


register_reducer("transactions_view", _initial_state, _reducer)
