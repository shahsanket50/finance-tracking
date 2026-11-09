"""Edge adapters for balance derivation: events → BalanceLeg, IngestionEvents → StatementRecord.

Implements ADR-022. Contract: processing/accounts/contract.py.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Sequence
from datetime import date

from cryptography.exceptions import InvalidTag
from sqlalchemy import select
from sqlalchemy.orm import Session

from core.events.encryption import decrypt_payload
from core.events.models import IngestionEvent
from core.events.store import Event
from core.events.types import TRANSACTION_INGESTED
from processing.accounts.contract import BalanceLeg, StatementDecryptionError, StatementRecord

logger = logging.getLogger(__name__)

_INGESTED_STATUS = "ingested"  # IngestionEvent.status written by confirm() when accepted
STATEMENT_DECRYPTION_ALERT = "statement_decryption_failed"


def _require_int(value: object, what: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise TypeError(f"{what} must be int paise, got {type(value).__name__} (CLAUDE.md §3.5)")
    return value


def balance_legs_from_events(
    events: Sequence[Event],
    account_ref: str,
    statements: Sequence[StatementRecord],
) -> list[BalanceLeg]:
    period_end_by_statement = {s.ingestion_event_id: s.period_end for s in statements}
    legs: list[BalanceLeg] = []
    for event in events:
        if event.event_type != TRANSACTION_INGESTED or event.aggregate_id != account_ref:
            continue
        payload = event.payload
        idempotency_hash = str(payload["idempotency_hash"])
        legs.append(
            BalanceLeg(
                idempotency_hash=idempotency_hash,
                amount_paise=_require_int(payload["amount_paise"], f"amount of {idempotency_hash}"),
                value_date=date.fromisoformat(str(payload["value_date"])),
                source_period_end=(
                    None
                    if event.ingestion_event_id is None
                    else period_end_by_statement.get(event.ingestion_event_id)
                ),
            )
        )
    return legs


def load_account_statements(
    session: Session, user_id: uuid.UUID, account_ref: str
) -> list[StatementRecord]:
    rows = session.scalars(
        select(IngestionEvent).where(
            IngestionEvent.user_id == user_id,
            IngestionEvent.status == _INGESTED_STATUS,
            IngestionEvent.period_end.is_not(None),
        )
    ).all()
    statements: list[StatementRecord] = []
    for row in rows:
        detail = row.source_detail or {}
        if detail.get("account_ref") != account_ref or row.period_end is None:
            continue  # another account, or a statement predating routing keys (no anchor)
        try:
            payload = decrypt_payload(session, row.encryption_key_id, row.payload)
        except (InvalidTag, ValueError) as err:
            logger.error(
                STATEMENT_DECRYPTION_ALERT,
                extra={
                    "alert": STATEMENT_DECRYPTION_ALERT,
                    "ingestion_event_id": str(row.id),
                    "account_ref": account_ref,
                    "error": type(err).__name__,
                },
            )
            raise StatementDecryptionError(row.id, err) from err
        closing = payload.get("closing_balance_paise")
        statements.append(
            StatementRecord(
                ingestion_event_id=row.id,
                seq=int(row.seq),
                account_ref=account_ref,
                account_type=str(detail.get("account_type", "")),
                period_end=row.period_end,
                closing_balance_paise=(
                    None if closing is None else _require_int(closing, "closing_balance_paise")
                ),
            )
        )
    return statements
