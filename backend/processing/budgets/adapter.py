"""Edge adapter: decrypted events → BudgetTransaction records. Implements ADR-020.

Contract: processing/budgets/contract.py. Reads the TransactionIngested payload exactly as
ingestion writes it (ingestion/dryrun/confirm.py transaction_event_payload).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date

from core.events.store import Event
from core.events.types import TRANSACTION_INGESTED
from processing.budgets.contract import BudgetTransaction
from processing.classifier.categories import Category


def budget_transactions_from_events(
    events: Sequence[Event],
    effective_categories: Mapping[str, Category],
) -> list[BudgetTransaction]:
    records: list[BudgetTransaction] = []
    for event in events:
        if event.event_type != TRANSACTION_INGESTED:
            continue
        payload = event.payload
        idempotency_hash = str(payload["idempotency_hash"])
        amount = payload["amount_paise"]
        if not isinstance(amount, int) or isinstance(amount, bool):
            raise TypeError(
                f"amount_paise must be int paise, got {type(amount).__name__} "
                f"for {idempotency_hash} (CLAUDE.md §3.5)"
            )
        records.append(
            BudgetTransaction(
                idempotency_hash=idempotency_hash,
                amount_paise=amount,
                value_date=date.fromisoformat(str(payload["value_date"])),
                effective_category=effective_categories.get(idempotency_hash),
            )
        )
    return records
