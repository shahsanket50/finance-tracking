"""Tests for abandon() — deletes Redis session, zero DB writes."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from ingestion.dryrun.abandon import abandon


def test_abandon_calls_redis_delete() -> None:
    """abandon() calls redis.delete with the correct key."""
    mock_redis = MagicMock()
    with patch("ingestion.dryrun.abandon.get_redis_client", return_value=mock_redis):
        abandon("test-session-id")
    mock_redis.delete.assert_called_once_with("dryrun:test-session-id")


def test_abandon_idempotent_on_missing_key() -> None:
    """abandon() is safe to call when the session is already gone."""
    mock_redis = MagicMock()
    mock_redis.delete.return_value = 0  # Redis returns 0 when key doesn't exist
    with patch("ingestion.dryrun.abandon.get_redis_client", return_value=mock_redis):
        abandon("nonexistent-session")
    mock_redis.delete.assert_called_once()


def test_abandon_no_db_import() -> None:
    """abandon() module imports no DB or SQLAlchemy code."""
    import ingestion.dryrun.abandon as abandon_module

    assert "sqlalchemy" not in dir(abandon_module)
    assert "Session" not in dir(abandon_module)
