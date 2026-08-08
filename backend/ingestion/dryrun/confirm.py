"""Confirm a DryRunSession: write IngestionEvent, RawArtifact, TransactionEvents.

Implements TRD §9.1.
"""

from __future__ import annotations

import os
from typing import Any

from sqlalchemy.orm import Session

from core.events.encryption import encrypt_payload
from core.events.models import IngestionEvent, RawArtifact
from core.events.store import append_event
from ingestion.dryrun.session import DryRunSession, _redis_key, load_session  # noqa: F401
from ingestion.validators.balance_check import BalanceCheckResult


class SessionExpiredError(Exception):
    """Raised when the DryRunSession has expired from Redis."""


def get_redis_client() -> Any:
    """Return a Redis client. Reads REDIS_URL env var. Patched in unit tests."""
    import redis  # deferred so missing redis doesn't break module import

    url = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
    return redis.from_url(url)  # type: ignore[no-untyped-call]


def confirm(session_id: str, db_session: Session) -> None:
    """Load DryRunSession, write events to DB, delete session from Redis.

    Raises SessionExpiredError if session not found in Redis.
    PASS balance: writes 1 IngestionEvent + 1 RawArtifact + N TransactionEvents.
    FAIL balance: writes 1 IngestionEvent(rejected) + 1 RawArtifact(retained=True) + 0 txns.
    Always deletes the Redis session after DB writes (whether PASS or FAIL).
    """
    redis_client = get_redis_client()

    dry_session = load_session(redis_client, session_id)
    if dry_session is None:
        raise SessionExpiredError(
            f"DryRunSession {session_id!r} not found in Redis (expired or invalid)"
        )

    statement = dry_session.statement
    is_pass = dry_session.balance_check == BalanceCheckResult.PASS

    # Encrypt the IngestionEvent payload
    payload_dict: dict[str, object] = {
        "bank": statement.bank,
        "account_ref": statement.account_ref,
        "raw_artifact_content_hash": dry_session.raw_artifact_content_hash,
        "transaction_count": len(statement.transactions),
    }
    encrypted_payload, key_id = encrypt_payload(db_session, dry_session.user_id, payload_dict)

    # Create IngestionEvent
    ingestion_event = IngestionEvent(
        user_id=dry_session.user_id,
        source="pdf_upload",
        period_start=statement.period_start,
        period_end=statement.period_end,
        records_added=len(statement.transactions) if is_pass else 0,
        records_skipped=0,
        records_flagged=0,
        balance_check=dry_session.balance_check.value,
        confidence=statement.confidence,
        status="ingested" if is_pass else "rejected",
        payload=encrypted_payload,
        encryption_key_id=key_id,
    )
    db_session.add(ingestion_event)
    db_session.flush()  # populates ingestion_event.id from DB (None in unit tests — acceptable)

    # Create RawArtifact
    raw_artifact = RawArtifact(
        ingestion_event_id=ingestion_event.id,
        user_id=dry_session.user_id,
        content_hash=dry_session.raw_artifact_content_hash,
        retained=not is_pass,
    )
    db_session.add(raw_artifact)

    # Write TransactionEvents (PASS only)
    if is_pass:
        for txn in statement.transactions:
            transaction_type = "debit" if txn.amount_paise < 0 else "credit"
            append_event(
                db_session,
                dry_session.user_id,
                "transaction_ingested",
                txn.account_ref,
                {
                    "narration": txn.narration,
                    "canonical_narration": txn.canonical_narration,
                    "occurrence_index": txn.occurrence_index,
                },
                value_date=txn.value_date,
                amount_paise=txn.amount_paise,
                idempotency_hash=txn.idempotency_hash,
                occurrence_index=txn.occurrence_index,
                transaction_type=transaction_type,
                narration=txn.narration,
                canonical_narration=txn.canonical_narration,
                actor="user",
                ingestion_event_id=ingestion_event.id,
                confidence=statement.confidence,
                running_balance_paise=txn.running_balance_paise,
            )

    # Commit all DB writes before touching Redis — if commit fails, session stays in Redis
    db_session.commit()

    # Delete session from Redis only after DB commit succeeds (always — PASS and FAIL)
    redis_client.delete(_redis_key(session_id))
