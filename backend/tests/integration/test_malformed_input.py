"""Integration tests: malformed PDF input never writes DB rows. Implements TRD §9.1 / CLAUDE.md §2."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy.orm import Session

from core.events.models import IngestionEvent, TransactionEvent
from ingestion.dryrun.harness import dry_run

GARBAGE_BYTES = b"not a pdf at all -- just garbage bytes %PDF-- corrupted"


@pytest.mark.integration
def test_malformed_pdf_writes_zero_rows(pg_session: Session, test_user: object) -> None:
    """Garbage PDF bytes → exception from dry_run, zero rows in DB."""
    from core.events.models import User

    assert isinstance(test_user, User)

    mock_redis = MagicMock()

    with patch("ingestion.dryrun.harness.get_redis_client", return_value=mock_redis):
        with pytest.raises(Exception):
            dry_run(GARBAGE_BYTES, test_user.id, "TEST_ACC")

    assert pg_session.query(TransactionEvent).filter(TransactionEvent.user_id == test_user.id).count() == 0
    assert pg_session.query(IngestionEvent).filter(IngestionEvent.user_id == test_user.id).count() == 0


@pytest.mark.integration
def test_empty_pdf_bytes_writes_zero_rows(pg_session: Session, test_user: object) -> None:
    """Empty PDF bytes → exception from dry_run, zero rows in DB."""
    from core.events.models import User

    assert isinstance(test_user, User)

    mock_redis = MagicMock()

    with patch("ingestion.dryrun.harness.get_redis_client", return_value=mock_redis):
        with pytest.raises(Exception):
            dry_run(b"", test_user.id, "TEST_ACC")

    assert pg_session.query(TransactionEvent).filter(TransactionEvent.user_id == test_user.id).count() == 0
    assert pg_session.query(IngestionEvent).filter(IngestionEvent.user_id == test_user.id).count() == 0
