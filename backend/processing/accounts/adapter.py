"""Edge adapters for balance derivation: events → BalanceLeg, IngestionEvent → anchor.

Implements ADR-022. Contract: processing/accounts/contract.py.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from core.events.encryption import decrypt_payload
from core.events.models import IngestionEvent
from core.events.store import Event
from core.events.types import TRANSACTION_INGESTED
from processing.accounts.contract import BalanceLeg, StatementAnchor

_INGESTED_STATUS = "ingested"  # IngestionEvent.status written by confirm() for a PASS


def balance_legs_from_events(events: Sequence[Event], account_ref: str) -> list[BalanceLeg]:
    legs: list[BalanceLeg] = []
    for event in events:
        if event.event_type != TRANSACTION_INGESTED or event.aggregate_id != account_ref:
            continue
        payload = event.payload
        amount = payload["amount_paise"]
        if not isinstance(amount, int) or isinstance(amount, bool):
            raise TypeError(
                f"amount_paise must be int paise, got {type(amount).__name__} (CLAUDE.md §3.5)"
            )
        legs.append(
            BalanceLeg(
                idempotency_hash=str(payload["idempotency_hash"]),
                amount_paise=amount,
                value_date=date.fromisoformat(str(payload["value_date"])),
            )
        )
    return legs


def load_statement_anchor(
    session: Session, user_id: uuid.UUID, account_ref: str
) -> StatementAnchor | None:
    rows = session.scalars(
        select(IngestionEvent).where(
            IngestionEvent.user_id == user_id,
            IngestionEvent.status == _INGESTED_STATUS,
            IngestionEvent.period_end.is_not(None),
        )
    ).all()
    latest: StatementAnchor | None = None
    for row in rows:
        payload = decrypt_payload(session, row.encryption_key_id, row.payload)
        closing = payload.get("closing_balance_paise")
        if row.period_end is None or payload.get("account_ref") != account_ref or closing is None:
            continue  # another account, or ingested before anchors were recorded
        if not isinstance(closing, int) or isinstance(closing, bool):
            raise TypeError(
                f"closing_balance_paise must be int paise, got {type(closing).__name__}"
            )
        if latest is None or row.period_end > latest.period_end:
            latest = StatementAnchor(
                account_ref=account_ref,
                period_end=row.period_end,
                closing_balance_paise=closing,
            )
    return latest
