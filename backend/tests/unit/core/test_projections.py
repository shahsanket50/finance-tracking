"""Unit tests for projection builder and timezone utilities."""

import uuid
from datetime import UTC, datetime

import pytest

from core.projections.builder import build_projection_from_events
from core.projections.timezone import ist_fy_year, ist_statement_period, utc_to_ist

# ── Timezone + FY logic (H4) ───────────────────────────────────────────────────


def test_fy_boundary_march_31_night() -> None:
    """2026-03-31T23:30Z = 2026-04-01T05:00 IST → FY 2026."""
    dt = datetime(2026, 3, 31, 23, 30, tzinfo=UTC)
    assert ist_fy_year(dt) == 2026


def test_fy_boundary_march_31_morning() -> None:
    """2026-03-31T00:00Z = 2026-03-31T05:30 IST → FY 2025."""
    dt = datetime(2026, 3, 31, 0, 0, tzinfo=UTC)
    assert ist_fy_year(dt) == 2025


def test_fy_april_1() -> None:
    """2026-04-01T00:00Z = 2026-04-01T05:30 IST → FY 2026."""
    dt = datetime(2026, 4, 1, 0, 0, tzinfo=UTC)
    assert ist_fy_year(dt) == 2026


def test_fy_january() -> None:
    """January is Q4 of the FY that started the previous April."""
    dt = datetime(2026, 1, 15, 10, 0, tzinfo=UTC)
    assert ist_fy_year(dt) == 2025


def test_statement_period_q1() -> None:
    """April is Q1."""
    dt = datetime(2026, 4, 15, 0, 0, tzinfo=UTC)
    fy, quarter = ist_statement_period(dt)
    assert fy == 2026
    assert quarter == 1


def test_statement_period_q4() -> None:
    """March is Q4."""
    dt = datetime(2026, 3, 15, 0, 0, tzinfo=UTC)
    fy, quarter = ist_statement_period(dt)
    assert fy == 2025
    assert quarter == 4


def test_utc_to_ist_offset() -> None:
    """IST is UTC+5:30."""
    dt = datetime(2026, 1, 1, 0, 0, tzinfo=UTC)
    ist = utc_to_ist(dt)
    offset = ist.utcoffset()
    assert offset is not None
    assert offset.total_seconds() == 5.5 * 3600


# ── Projection builder (pure function) ────────────────────────────────────────


def test_build_projection_from_empty_events() -> None:
    result = build_projection_from_events([])
    assert result == {"events": [], "count": 0}


def test_build_projection_from_events_counts() -> None:
    from core.events.store import Event

    events = [
        Event(
            id=uuid.uuid4(),
            seq=1,
            event_version=1,
            event_type="TransactionIngested",
            user_id=uuid.uuid4(),
            aggregate_id="ACC001",
            payload={"amount": "1000"},
            created_at=datetime.now(tz=UTC),
        )
    ]
    result = build_projection_from_events(events)
    assert result["count"] == 1
    events_out = result["events"]
    assert isinstance(events_out, list)
    assert len(events_out) == 1


def test_build_projection_unknown_type_raises() -> None:
    with pytest.raises(ValueError, match="Unknown projection type"):
        build_projection_from_events([], projection_type="nonexistent")
