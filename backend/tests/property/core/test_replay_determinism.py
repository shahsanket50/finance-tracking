"""Property test: replaying the same event stream twice produces identical output (I3)."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime

from hypothesis import given, settings
from hypothesis import strategies as st

from core.events.store import Event
from core.projections.builder import build_projection_from_events


def _make_event(seq: int, event_type: str, payload: dict[str, object]) -> Event:
    return Event(
        id=uuid.uuid4(),
        seq=seq,
        event_version=1,
        event_type=event_type,
        user_id=uuid.uuid4(),
        aggregate_id="ACC001",
        payload=payload,
        created_at=datetime.now(tz=UTC),
    )


@given(
    event_count=st.integers(min_value=0, max_value=50),
    event_types=st.lists(
        st.sampled_from(["TransactionIngested", "CategoryAssigned", "CategoryCorrected"]),
        min_size=0,
        max_size=50,
    ),
)
@settings(max_examples=100)
def test_replay_is_deterministic(event_count: int, event_types: list[str]) -> None:
    """Build the same projection twice from the same event list — must be byte-identical (I3)."""
    # Truncate event_types to event_count
    types = (event_types + ["TransactionIngested"] * event_count)[:event_count]
    events = [
        _make_event(i + 1, types[i], {"amount": str(i * 100), "seq": i}) for i in range(event_count)
    ]

    result_a = build_projection_from_events(events)
    result_b = build_projection_from_events(events)

    # Byte-identical after JSON normalization
    assert json.dumps(result_a, sort_keys=True) == json.dumps(result_b, sort_keys=True)
