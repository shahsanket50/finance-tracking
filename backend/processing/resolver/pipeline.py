"""Resolver pipeline: match TransactionIngested events and persist resolver decisions.

Implements TRD §2.3. Called by confirm.py immediately after ingestion. Also safe
to call from audit endpoints as an idempotent catch-up (RESOLVED events already
written are skipped via deterministic idempotency_hash check).

Invariant 3 (replay determinism) is maintained because:
  - Decisions are written exactly once and read back unchanged on replay.
  - Matchers are never called at projection/replay time — only here, at write time.
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from core.events.encryption import decrypt_payload
from core.events.models import TransactionEvent
from core.events.store import append_event
from core.events.types import (
    MARKED_CC_PAYMENT,
    MARKED_FD_BOOKING,
    MARKED_INTERNAL_TRANSFER,
    MARKED_REVERSAL,
    RESOLVER_EVENT_TYPES,
    TRANSACTION_INGESTED,
)
from processing.resolver.candidate import CandidateTxn
from processing.resolver.events import (
    MarkedCCPaymentPayload,
    MarkedFDBookingPayload,
    MarkedInternalTransferPayload,
    MarkedReversalPayload,
)
from processing.resolver.matchers import cc_payment, fd_booking, reversal, transfer


def _resolver_idempotency_hash(event_type: str, h1: str, h2: str) -> str:
    """Deterministic, order-independent idempotency hash for a resolver event."""
    key = event_type + ":" + ":".join(sorted([h1, h2]))
    return hashlib.sha256(key.encode()).hexdigest()


def run_resolver(session: Session, user_id: uuid.UUID) -> int:
    """Match ingested transactions and write resolver events for new pairs.

    Idempotent: pairs already written (by a previous run) are detected via their
    deterministic idempotency_hash and skipped. Returns the count of new events
    written in this call.
    """
    # 1. Read all TransactionIngested rows for this user.
    txn_rows = session.scalars(
        select(TransactionEvent)
        .where(
            TransactionEvent.user_id == user_id,
            TransactionEvent.event_type == TRANSACTION_INGESTED,
        )
        .order_by(TransactionEvent.seq)
    ).all()

    if not txn_rows:
        return 0

    # 2. Build candidates and a lookup map for ingestion_event_id + value_date.
    candidates: list[CandidateTxn] = []
    hash_to_ingestion_id: dict[str, uuid.UUID] = {}
    hash_to_value_date: dict[str, date] = {}

    for row in txn_rows:
        payload = decrypt_payload(session, row.encryption_key_id, row.payload)
        account_type = str(payload.get("account_type", "savings"))
        candidates.append(
            CandidateTxn(
                idempotency_hash=row.idempotency_hash,
                amount_paise=row.amount_paise,
                value_date=row.value_date,
                account_type=account_type,
            )
        )
        hash_to_ingestion_id[row.idempotency_hash] = row.ingestion_event_id
        hash_to_value_date[row.idempotency_hash] = row.value_date

    # 3. Read existing resolver event hashes so we can skip already-matched pairs.
    existing_resolver_hashes: set[str] = set(
        session.scalars(
            select(TransactionEvent.idempotency_hash).where(
                TransactionEvent.user_id == user_id,
                TransactionEvent.event_type.in_(RESOLVER_EVENT_TYPES),
            )
        ).all()
    )

    # 4. Run matchers and write new events.
    new_events_written = 0

    for tm in transfer.find_matches(candidates):
        r_hash = _resolver_idempotency_hash(
            MARKED_INTERNAL_TRANSFER, tm.debit_hash, tm.credit_hash
        )
        if r_hash in existing_resolver_hashes:
            continue
        append_event(
            session,
            user_id,
            MARKED_INTERNAL_TRANSFER,
            "RESOLVER",
            tm.model_dump(),
            value_date=hash_to_value_date[tm.debit_hash],
            amount_paise=0,
            idempotency_hash=r_hash,
            transaction_type="transfer",
            narration="",
            ingestion_event_id=hash_to_ingestion_id[tm.debit_hash],
        )
        new_events_written += 1

    for cm in cc_payment.find_matches(candidates):
        r_hash = _resolver_idempotency_hash(
            MARKED_CC_PAYMENT, cm.savings_debit_hash, cm.cc_credit_hash
        )
        if r_hash in existing_resolver_hashes:
            continue
        append_event(
            session,
            user_id,
            MARKED_CC_PAYMENT,
            "RESOLVER",
            cm.model_dump(),
            value_date=hash_to_value_date[cm.savings_debit_hash],
            amount_paise=0,
            idempotency_hash=r_hash,
            transaction_type="transfer",
            narration="",
            ingestion_event_id=hash_to_ingestion_id[cm.savings_debit_hash],
        )
        new_events_written += 1

    for fm in fd_booking.find_matches(candidates):
        r_hash = _resolver_idempotency_hash(
            MARKED_FD_BOOKING, fm.savings_debit_hash, fm.fd_credit_hash
        )
        if r_hash in existing_resolver_hashes:
            continue
        append_event(
            session,
            user_id,
            MARKED_FD_BOOKING,
            "RESOLVER",
            fm.model_dump(),
            value_date=hash_to_value_date[fm.savings_debit_hash],
            amount_paise=0,
            idempotency_hash=r_hash,
            transaction_type="transfer",
            narration="",
            ingestion_event_id=hash_to_ingestion_id[fm.savings_debit_hash],
        )
        new_events_written += 1

    for rm in reversal.find_matches(candidates):
        r_hash = _resolver_idempotency_hash(
            MARKED_REVERSAL, rm.original_hash, rm.reversal_hash
        )
        if r_hash in existing_resolver_hashes:
            continue
        append_event(
            session,
            user_id,
            MARKED_REVERSAL,
            "RESOLVER",
            rm.model_dump(),
            value_date=hash_to_value_date[rm.original_hash],
            amount_paise=0,
            idempotency_hash=r_hash,
            transaction_type="transfer",
            narration="",
            ingestion_event_id=hash_to_ingestion_id[rm.original_hash],
        )
        new_events_written += 1

    return new_events_written
