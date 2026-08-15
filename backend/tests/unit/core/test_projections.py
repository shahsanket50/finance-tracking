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


# ── Replay determinism, snapshots, decisions vs derivations (C-1, C-2, C-3) ───


def test_build_projection_from_events_is_pure() -> None:
    """build_projection_from_events is a pure function: same input → byte-identical output (I3)."""
    import json

    from core.events.store import Event

    user_id = uuid.uuid4()
    events = [
        Event(
            id=uuid.uuid4(),
            seq=1,
            event_version=1,
            event_type="TransactionIngested",
            user_id=user_id,
            aggregate_id="ACC",
            payload={"narration": "coffee", "amount": "-500"},
            created_at=datetime(2026, 1, 1, tzinfo=UTC),
        )
    ]

    result_a = build_projection_from_events(events)
    result_b = build_projection_from_events(events)

    assert json.dumps(result_a, sort_keys=True) == json.dumps(result_b, sort_keys=True)


def test_load_snapshot_corrupt_returns_none() -> None:
    """Corrupt snapshot must return None so callers trigger a full rebuild, not use empty state.

    Current load_snapshot returns ({}, last_seq) for unexpected data types — a bug.
    A caller receiving ({}, 500) treats it as a valid snapshot, skipping events 0–500
    and producing a wrong projection.
    """
    from unittest.mock import MagicMock

    from core.projections.snapshot import load_snapshot

    session = MagicMock()
    # Raw column returns an integer — neither str nor dict (simulates a corrupt/migrated row)
    session.execute.return_value.first.return_value = (42, 500)

    result = load_snapshot(session, uuid.uuid4(), "events_list")

    # EXPECTED TO FAIL against current code: load_snapshot returns ({}, 500) not None.
    # Must return None so the caller detects corruption and rebuilds from seq=0.
    assert result is None, "Corrupt snapshot must return None, not ({}, last_seq)"


def test_resolver_decisions_read_from_events_not_recomputed() -> None:
    """MarkedInternalTransfer events are read from the log; resolver is never re-invoked (TRD §9.2).

    build_projection_from_events must not call any matching/resolver logic —
    the decision is already recorded in the event payload.
    Forward-compatibility guard for Phase 2 expense-totals projection.
    """
    from core.events.store import Event

    user_id = uuid.uuid4()
    transfer_event = Event(
        id=uuid.uuid4(),
        seq=1,
        event_version=1,
        event_type="MarkedInternalTransfer",
        user_id=user_id,
        aggregate_id="HDFC_SAVINGS_001",
        payload={
            "debit_hash": "deadbeef",
            "credit_hash": "cafebabe",
            "matched_by": "resolver_v1",
            "confidence": 9500,
        },
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
    )

    # Must not raise — no resolver is invoked during projection replay
    result = build_projection_from_events([transfer_event])

    events_out = result["events"]
    assert isinstance(events_out, list)
    assert len(events_out) == 1
    assert events_out[0]["event_type"] == "MarkedInternalTransfer"
