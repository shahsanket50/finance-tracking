"""DryRunSession dataclass and Redis store functions. Implements TRD §9.1."""

from __future__ import annotations

import pickle
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any, cast
from uuid import UUID

from ingestion.parsers.base import ParsedStatement
from ingestion.validators.balance_check import BalanceCheckResult

if TYPE_CHECKING:
    import redis as redis_module

SESSION_TTL = 3600  # 1 hour in seconds
_KEY_PREFIX = "dryrun"


@dataclass
class DryRunSession:
    session_id: str  # UUID string (uuid4)
    user_id: UUID
    account_ref: str
    statement: ParsedStatement
    balance_check: BalanceCheckResult
    raw_artifact_content_hash: str  # SHA-256 hex of original PDF bytes
    created_at: datetime


def _redis_key(session_id: str) -> str:
    return f"{_KEY_PREFIX}:{session_id}"


def save_session(
    client: redis_module.Redis, session: DryRunSession, ttl: int = SESSION_TTL
) -> None:
    """Serialize and store a DryRunSession in Redis with a TTL."""
    client.setex(_redis_key(session.session_id), ttl, pickle.dumps(session))


def load_session(client: redis_module.Redis, session_id: str) -> DryRunSession | None:
    """Load a DryRunSession from Redis; returns None if expired or not found."""
    data: Any = client.get(_redis_key(session_id))
    if data is None:
        return None
    return cast(DryRunSession, pickle.loads(data))  # noqa: S301


def delete_session(client: redis_module.Redis, session_id: str) -> None:
    """Delete a DryRunSession from Redis."""
    client.delete(_redis_key(session_id))
