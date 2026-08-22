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

The order is enforced by iterating _MATCHER_PRIORITY directly in run_resolver() via
_cascade_matchers(). There is no separately-ordered call sequence that could drift.
"""

from __future__ import annotations

import hashlib
import logging
import uuid
from collections.abc import Callable
from datetime import date
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
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

logger = logging.getLogger(__name__)

# Single source of truth for matcher priority, event type constants, and hash extraction.
# run_resolver() iterates this tuple via _cascade_matchers() — there is no other ordering.
# Reversal is last: its criteria (same account_type, opposite signs) are a superset of
# transfer's, so it must not claim pairs that transfer has already handled.
_MATCHER_PRIORITY: tuple[tuple[str, Any, Callable[[Any], tuple[str, str]]], ...] = (
    (MARKED_INTERNAL_TRANSFER, transfer, lambda m: (m.debit_hash, m.credit_hash)),
    (MARKED_CC_PAYMENT, cc_payment, lambda m: (m.savings_debit_hash, m.cc_credit_hash)),
    (MARKED_FD_BOOKING, fd_booking, lambda m: (m.savings_debit_hash, m.fd_credit_hash)),
    (MARKED_REVERSAL, reversal, lambda m: (m.original_hash, m.reversal_hash)),
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


def _cascade_matchers(
    candidates: list[CandidateTxn],
    claimed: set[str],
) -> list[tuple[str, str, str, Any]]:
    """Run matchers in _MATCHER_PRIORITY order with cascading exclusion.

    Returns (event_type, h1, h2, match_obj) for each match found.
    `claimed` is mutated in-place — lower-priority matchers only see unclaimed candidates.
    This is the single function that implements the cascade; run_resolver() calls it and
    then handles DB persistence. Tests call it directly to verify the cascade invariant.
    """
    results: list[tuple[str, str, str, Any]] = []

    def available() -> list[CandidateTxn]:
        return [c for c in candidates if c.idempotency_hash not in claimed]

    for event_type, matcher, hash_extractor in _MATCHER_PRIORITY:
        for match in matcher.find_matches(available()):
            h1, h2 = hash_extractor(match)
            claimed.update([h1, h2])
            results.append((event_type, h1, h2, match))

    return results


def _write_if_new(
    session: Session,
    user_id: uuid.UUID,
    event_type: str,
    payload: dict[str, object],
    h1: str,
    h2: str,
    existing_hashes: set[str],
    hash_to_value_date: dict[str, date],
    hash_to_ingestion_id: dict[str, uuid.UUID],
) -> bool:
    """Write a resolver event to DB if not already present. Returns True if written.

    Uses a savepoint so a concurrent duplicate-key write does not poison the outer
    transaction. Only the specific constraint uq_transaction_events_user_idempotency_hash
    is treated as a benign race; all other IntegrityErrors are re-raised.
    """
    r_hash = _resolver_idempotency_hash(event_type, h1, h2)
    if r_hash in existing_hashes:
        return False
    sp = session.begin_nested()
    try:
        append_event(
            session,
            user_id,
            event_type,
            "RESOLVER",
            payload,
            value_date=hash_to_value_date[h1],
            amount_paise=0,
            idempotency_hash=r_hash,
            transaction_type="transfer",
            narration="",
            ingestion_event_id=hash_to_ingestion_id[h1],
        )
        sp.commit()
    except IntegrityError as exc:
        sp.rollback()
        orig = getattr(exc, "orig", None)
        pgcode = getattr(orig, "pgcode", None)
        diag = getattr(orig, "diag", None)
        constraint = getattr(diag, "constraint_name", None)
        if pgcode == "23505" and constraint == "uq_transaction_events_user_idempotency_hash":
            logger.warning(
                "Resolver concurrent-write race suppressed (event_type=%s h1=%.8s h2=%.8s)",
                event_type,
                h1,
                h2,
            )
            return False
        raise
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

    # 4. Cascade through matchers (order from _MATCHER_PRIORITY) then persist each match.
    new_events_written = 0
    for event_type, h1, h2, match in _cascade_matchers(candidates, claimed):
        written = _write_if_new(
            session,
            user_id,
            event_type,
            match.model_dump(),
            h1,
            h2,
            existing_resolver_hashes,
            hash_to_value_date,
            hash_to_ingestion_id,
        )
        new_events_written += int(written)

    return new_events_written
