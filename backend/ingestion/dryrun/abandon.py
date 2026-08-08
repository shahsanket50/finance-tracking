"""Abandon a DryRunSession: delete from Redis, assert zero DB writes. Implements TRD §9.1."""

from __future__ import annotations

import os
from typing import Any


def get_redis_client() -> Any:
    """Return a Redis client. Reads REDIS_URL env var. Patched in unit tests."""
    import redis

    url = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
    return redis.from_url(url)  # type: ignore[no-untyped-call]


def abandon(session_id: str) -> None:
    """Delete a DryRunSession from Redis. Writes nothing to the database.

    This is safe to call even if the session has already expired — Redis delete
    is idempotent on a missing key.
    """
    from ingestion.dryrun.session import _redis_key

    redis_client = get_redis_client()
    redis_client.delete(_redis_key(session_id))
