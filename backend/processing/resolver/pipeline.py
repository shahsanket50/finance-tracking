"""Resolver pipeline: match TransactionIngested events and persist resolver decisions.

Implements TRD §2.3. Called by confirm.py immediately after ingestion. Also safe
to call from audit endpoints as an idempotent catch-up (RESOLVED events already
written are skipped via deterministic idempotency_hash check).

Invariant 3 (replay determinism) is maintained because:
  - Decisions are written exactly once and read back unchanged on replay.
  - Matchers are never called at projection/replay time — only here, at write time.

Matcher priority: transfer → cc_payment → fd_booking → reversal. Each matcher
receives only candidates not yet claimed by a higher-priority matcher in this run
OR already covered by an existing DB resolver event. This prevents a candidate pair
from being claimed by two matchers (e.g. savings↔savings matching both as a
transfer AND a reversal).
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
    ACCOUNT_TYPE_SAVINGS,
    MARKED_CC_PAYMENT,
    MARKED_FD_BOOKING,
    MARKED_INTERNAL_TRANSFER,
    MARKED_REVERSAL,
    RESOLVER_EVENT_TYPES,
    TRANSACTION_INGESTED,
)
from processing.resolver.candidate import CandidateTxn
from processing.resolver.matchers import cc_payment, fd_booking, reversal, transfer

# Explicit priority order. Lower index = higher priority = runs first and claims candidates
# before later matchers see them. Reversal is last because it matches any same-account-type
# debit+credit pair — including savings↔savings transfers that the transfer matcher already
# claimed. Without this ordering, a single pair could be claimed by two matchers.
_MATCHER_PRIORITY = (
    ("transfer", transfer),  # savings↔savings: most specific
    ("cc_payment", cc_payment),  # savings debit + credit_card credit
    ("fd_booking", fd_booking),  # savings debit + fd credit
    ("reversal", reversal),  # catch-all: same account_type, opposite sign
)


def _resolver_idempotency_hash(event_type: str, h1: str, h2: str) -> str:
    """Deterministic, order-independent idempotency hash for a resolver event."""
    key = event_type + ":" + ":".join(sorted([h1, h2]))
    return hashlib.sha256(key.encode()).hexdigest()


def _hashes_covered_by_resolver_event(session: Session, row: TransactionEvent) -> frozenset[str]:
    """Return the transaction hashes that a resolver event claims."""
    payload = decrypt_payload(session, row.encryption_key_id, row.payload)
    if row.event_type == MARKED_INTERNAL_TRANSFER:
        return frozenset([str(payload["debit_hash"]), str(payload["credit_hash"])])
    if row.event_type == MARKED_CC_PAYMENT:
        return frozenset([str(payload["savings_debit_hash"]), str(payload["cc_credit_hash"])])
    if row.event_type == MARKED_FD_BOOKING:
        return frozenset([str(payload["savings_debit_hash"]), str(payload["fd_credit_hash"])])
    if row.event_type == MARKED_REVERSAL:
        return frozenset([str(payload["original_hash"]), str(payload["reversal_hash"])])
    return frozenset()


def _write_if_new(
    session: Session,
    user_id: uuid.UUID,
    event_type: str,
    payload: dict[str, object],
    debit_hash: str,
    credit_hash: str,
    existing_hashes: set[str],
    claimed: set[str],
    hash_to_value_date: dict[str, date],
    hash_to_ingestion_id: dict[str, uuid.UUID],
) -> bool:
    """Write a resolver event if not in DB. Updates claimed in-place; returns True if written."""
    r_hash = _resolver_idempotency_hash(event_type, debit_hash, credit_hash)
    if r_hash in existing_hashes:
        return False
    append_event(
        session,
        user_id,
        event_type,
        "RESOLVER",
        payload,
        value_date=hash_to_value_date[debit_hash],
        amount_paise=0,
        idempotency_hash=r_hash,
        transaction_type="transfer",
        narration="",
        ingestion_event_id=hash_to_ingestion_id[debit_hash],
    )
    claimed.update([debit_hash, credit_hash])
    return True


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

    # 2. Build candidates and lookup maps for ingestion_event_id + value_date.
    candidates: list[CandidateTxn] = []
    hash_to_ingestion_id: dict[str, uuid.UUID] = {}
    hash_to_value_date: dict[str, date] = {}

    for row in txn_rows:
        payload = decrypt_payload(session, row.encryption_key_id, row.payload)
        account_type = str(payload.get("account_type", ACCOUNT_TYPE_SAVINGS))
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

    # 3. Read existing resolver events — their idempotency hashes (for skip checks)
    #    and the transaction hashes they cover (for cascade exclusion on re-runs).
    existing_resolver_rows = session.scalars(
        select(TransactionEvent).where(
            TransactionEvent.user_id == user_id,
            TransactionEvent.event_type.in_(RESOLVER_EVENT_TYPES),
        )
    ).all()

    existing_resolver_hashes: set[str] = {row.idempotency_hash for row in existing_resolver_rows}
    claimed: set[str] = set()
    for row in existing_resolver_rows:
        claimed.update(_hashes_covered_by_resolver_event(session, row))

    # 4. Run matchers in priority order with cascading exclusion.
    #    Each matcher only sees candidates not yet claimed. Newly written pairs are
    #    added to `claimed` so lower-priority matchers can't re-match them.
    new_events_written = 0

    def _available() -> list[CandidateTxn]:
        return [c for c in candidates if c.idempotency_hash not in claimed]

    for tm in transfer.find_matches(_available()):
        written = _write_if_new(
            session,
            user_id,
            MARKED_INTERNAL_TRANSFER,
            tm.model_dump(),
            tm.debit_hash,
            tm.credit_hash,
            existing_resolver_hashes,
            claimed,
            hash_to_value_date,
            hash_to_ingestion_id,
        )
        new_events_written += int(written)

    for cm in cc_payment.find_matches(_available()):
        written = _write_if_new(
            session,
            user_id,
            MARKED_CC_PAYMENT,
            cm.model_dump(),
            cm.savings_debit_hash,
            cm.cc_credit_hash,
            existing_resolver_hashes,
            claimed,
            hash_to_value_date,
            hash_to_ingestion_id,
        )
        new_events_written += int(written)

    for fm in fd_booking.find_matches(_available()):
        written = _write_if_new(
            session,
            user_id,
            MARKED_FD_BOOKING,
            fm.model_dump(),
            fm.savings_debit_hash,
            fm.fd_credit_hash,
            existing_resolver_hashes,
            claimed,
            hash_to_value_date,
            hash_to_ingestion_id,
        )
        new_events_written += int(written)

    for rm in reversal.find_matches(_available()):
        written = _write_if_new(
            session,
            user_id,
            MARKED_REVERSAL,
            rm.model_dump(),
            rm.original_hash,
            rm.reversal_hash,
            existing_resolver_hashes,
            claimed,
            hash_to_value_date,
            hash_to_ingestion_id,
        )
        new_events_written += int(written)

    return new_events_written
